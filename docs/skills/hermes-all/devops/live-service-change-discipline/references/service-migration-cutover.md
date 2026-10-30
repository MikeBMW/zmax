# 把线上站点/服务整套搬到另一台机器并切流

适用于「web/服务从 A 机迁到 B 机」这类活。核心不是搬文件，是**新栈必须在切流前就和现网逐条对拍一致**，且切流动作自带回滚。

## 0. 分阶段，别一把梭
按「站点+DB → 后端服务 → 大静态(模型/归档)」三段推进。大文件往往占总量的 2/3 且只在下载接口用到，
**把它们留在原机直出**（薄反代里单独一个 `location ^~ /models/`），其余先切 —— 否则要等几小时传输才能上线。

## 1. 目标机在 NAT 后、安全组只开 22/80/443 ⇒ SSH 反向隧道

```bash
# 目标机上: 生成专用密钥并装到云端 root
ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519 -C <tag>
ssh-copy-id -i /root/.ssh/id_ed25519.pub root@<公网IP>
```

```ini
# zmax-ssh-tunnel.service (目标机)
[Unit]
After=network-online.target nginx.service
[Service]
ExecStart=/usr/bin/ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
  -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no \
  -i /root/.ssh/id_ed25519 -R 127.0.0.1:18790:127.0.0.1:8081 root@<公网IP>
Restart=always
[Install]
WantedBy=multi-user.target
```

`-R 127.0.0.1:<云端口>:127.0.0.1:<目标端口>` 只绑云端回环，**不需要开新端口、不需要改安全组、不需要 GatewayPorts**。
验证：在云端 `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18790/` —— 拿到目标站的码即隧道通。
（frp 需要 bindPort 可达，安全组没放行时反而更麻烦；SSH 走已开的 22 最省事。）

## 2. 搬站点（慢链路上按重要性排序）

```bash
rsync -a --exclude 'models/' -e "ssh -i /root/.ssh/id_ed25519 -o ServerAliveInterval=15" \
  root@<公网IP>:<webroot>/ <目标目录>/
```

- 传输期间**不要急着测页面**：WordPress/PHP 站点缺 `wp-includes/*` 时首页 500，看着像迁坏了。
- 判完成看 `du -sh` 与源一致 + 关键文件在位（`wp-includes/version.php`、`index.php`）。
- 同时把小件（服务脚本、systemd unit、DB dump、证书）单独先搬，先干活。

## 3. 目标机栈落地顺序（固定）

1. `apt-get update` 后装 `nginx php-fpm php-mysql mysql-server`（先 update，旧索引会 404）。
2. nginx vhost：**保留原 `server_name`**，只听 `8081 http`，TLS 仍在云端终结。变换清单：
   - 删 `listen 443 ssl*`、`ssl_*`、HSTS；`listen 80` → `listen 8081`；
   - `root`/`alias` 换成本机站点目录；
   - 源 vhost 若来自面板（宝塔等）会 `include fastcgi.conf; include pathinfo.conf;` —— 原生 nginx **没有这两个 snippet**，必须一并搬，
     否则 `nginx -t` 直接失败；`pathinfo.conf` 用正则把 `.php/PATH_INFO` 拆开，WordPress 伪静态/`/index.php/<slug>` 依赖它。
   - `fastcgi_pass` 的 socket 名按目标机核对：`grep '^listen' /etc/php/*/fpm/pool.d/www.conf`（8.3 是 `/run/php/php8.3-fpm.sock`，别照抄源机的）。
   - 每个 `proxy_pass` 的端口按**目标机真实端口**改 —— 同一服务在两台机常常不同号（云端 18794 → 目标机 8803）。
3. DB：用站点配置里的库名/账号/**原密码**在目标机建同名账号（脚本里读源机配置，值不回显），再导 dump，核对表数与关键行数。
4. 服务 unit：路径从源机目录改成目标机目录、补 `User=`；脚本权限 `chmod 644`（搬到 600 后服务读不到，报错却不明显）。
   依赖缺就装（`pip3 install --break-system-packages`）。
5. 权限：`chmod o+x /home/<用户>`（否则 nginx 无法穿越 → 403），`chown -R www-data:www-data <webroot>`。

## 4. 症状三分法（比读日志快）

| 现象 | 根因 | 处置 |
|---|---|---|
| 403，日志 `Permission denied` | 父目录缺 o+x / 文件 root 600 | `chmod o+x` + `chown www-data` |
| 000 / 空响应 | `fastcgi_pass` socket 名不匹配 | 核对 pool `listen` 与 vhost |
| 500 且响应体被截断 | PHP fatal | CLI 复现拿真错误：`php -d display_errors=1 -r 'include "<webroot>/index.php";'` |
| 502 | 反代目标没起 / 端口改错 | `ss -ltnp \| grep :<port>` |

## 5. 切流前必做：与现网逐条对拍

```bash
for u in / /index.php /<关键页> /<json 接口> /<ws 路径>; do
  printf '%-18s ' "$u"
  curl -s -o /dev/null -w 'new=%{http_code}/%{size_download}B ' -H "Host: <域名>" http://127.0.0.1:8081$u
  curl -s -o /dev/null -w 'live=%{http_code}/%{size_download}B\n' "https://<域名>$u"
done
```

🔴 **现网也 500/404 的路径 = 既有故障，不是迁入缺陷**。照搬下来即可，别在迁移轮次里顺手修（未验证改动 + 切流同时发生，出事分不清是谁干的）；
要修另开一轮。同理 WebSocket 要单独验握手码 `101`（`-H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Key: ...'`）。

## 6. 切流：薄反代 + 自带回滚的脚本

薄 vhost 只需四段：`/.well-known/`（证书续期留本地）· 大静态 `location ^~ /models/`（留本地）· 隧道专用路径 · `location /` 反代到 `127.0.0.1:<隧道口>`。
反代段必须带：`proxy_http_version 1.1` · `Upgrade`/`Connection $connection_upgrade` · `X-Forwarded-For/Proto` · `client_max_body_size`（上传）·
`proxy_buffering off`（mjpg 流）· 长 `proxy_read_timeout`（大文件下载/长连接）。

`map $http_upgrade $connection_upgrade` 属于 http 上下文，放 `/etc/nginx/conf.d/00-upgrade-map.conf`，空值写 `'' close;`。

切流脚本形态（一次性、可重跑、失败自动还原）：备份 `<conf>.bak` → 装入薄配置 → `nginx -t` 不过就还原 → `reload` →
自测站点根必须是 200，否则还原并 reload → 打印备份路径。**这种脚本会触发权限确认，先准备好、一次说清再执行，别反复重发。**

## 7. 两个切流后才暴露的坑

- 🔴 **`nginx -s reload` 后仍可能按旧 upstream 应答**：实测改完 `/map/` 的反代端口，reload 后错误日志里打出的还是旧端口（旧 worker 继承），
  `curl` 继续 502。验证新反代目标要 `systemctl restart nginx`。
- 迁完别忘了把「哪一段还在旧机」（大静态、归档数据）写进一句话记录 + 回滚命令，用户问「都搬完了么」时才答得出边界。
- 🔴 **隧道会话会「半死」：转发没了，进程还在**。判据是云端 `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:<隧道口>/` 得 `000`
  且 `ss -tnp | grep <隧道口>` 显示 `CLOSE-WAIT`。此时 `systemctl is-active` 仍是 active，`Restart=always` 一生效条件都不满足 ⇒
  只能靠外部看门狗（按 HTTP 结果判、不看端口不看进程）或云端定时重启那段 ssh。把它写进巡检，别等用户报「网站打不开」。
- 🔴 **目标机的物理入口比隧道更脆**：站点全在车间局域网那台机时，本机那块 USB 网卡一掉就是「全部 No route to host」。
  排障第一步先量链路：`ip -br addr` 看那块网卡还在不在 → `sudo dmesg | grep -iE 'usb.*disconnect|r8152|cdc_ether'` 看是不是物理断开 →
  再谈服务。**别在断链状态下反复重试 scp/ssh，也别据此报「迁移失败」**：栈本身没事，等链路回来一条命令就能续。
- 用户点名不能动的东西（签名 keystore、鉴权模型、设备绑定方式）在迁移里**原样不动**，且要在报告里明确「没动」。
