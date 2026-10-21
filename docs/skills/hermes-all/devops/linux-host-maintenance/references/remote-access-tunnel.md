# 4060 内网服务 → 公网: ssh -R + nginx 路径反代 (不用 frp, 不改安全组)

背景: 4060=192.168.23.50, Orin=192.168.23.66 同一局域网。阿里云 ECS 39.102.211.79 **安全组只开了 22/80/443/41000**
(41000 还被宝塔占着), 所以 frp 要的 7000 从外网是被丢包(i/o timeout, 不是 refused)。结论: **根本不需要 frp** ——
只要能 ssh 到 ECS, 用 ssh -R 把端口反向映射到 ECS 回环, 再由 nginx 的 **路径** 反代到那个回环端口, 全程只用 80/443。

## 最终拓扑 (2026-10-21 定稿)
| 公网地址 | nginx → | ECS 回环 | ssh -R | 4060 本地 | systemd 单元 |
|---|---|---|---|---|---|
| https://datadrive.world/st/?k=zmax-live | /st/ | 127.0.0.1:18793 | 18793 | 127.0.0.1:8893 (tunnel_proxy → 8793) | zmax-ecs-station |
| https://datadrive.world/ov/?k=zmax-live | /ov/ | 127.0.0.1:18791 | 18791 | 127.0.0.1:8891 (tunnel_proxy → 8791 AR) | zmax-ecs-ov |
| https://datadrive.world/dash/dashboard.json | /dash/ | 127.0.0.1:18799 | 18799 | 127.0.0.1:8799 (dashboard_server) | zmax-ecs-dash |
| (公网直连 22022) | — | 0.0.0.0:22022 | 22022 | Orin 192.168.23.66:22 | zmax-ecs-orin |

前置: `zmax-tunnel-proxy.service` 长起两个 tunnel_proxy (8893→8793 station, 8891→8791 AR, `--token zmax-live`, POST//ctl//station//gen 一律 403 —— 是**故意**的)。

## 已废弃/不要再加
- `zmax-frpc` / `zmax-tunnel`: 删/停。frp 控制口 7000 被安全组挡死, 且 41000 已属于宝塔; 走 443 的 frp-websocket 方案是多余的。
- nginx 旧的 `location /station → 127.0.0.1:18795` 已无监听(502), 改用 /st/。

## 关机前: 把上行隧道挪到"不会关的那台"
隧道跟着**发起端**走: 主机一关, 它建的 -R 全部消失。要关机又要保远程访问时:
1. 把 ECS 上能用的私钥 (`id_ecs_tunnel`) 拷到备机 `~/.ssh/zmax_ecs` + `chmod 600`。
2. **先停旧机上的同名单元腾出远端端口** (`systemctl disable --now zmax-ecs-orin`), 再在备机启
   `zmax-orin-tunnel.service` (`-R 0.0.0.0:22022:127.0.0.1:22`)。不先腾端口 = `remote port forwarding failed`,
   备机侧永远 `activating`。
3. 验证落到谁: 从 ECS 自己 `ssh -p 22022 <user>@127.0.0.1 hostname` —— 能到 sshd 就对了
   (`Permission denied` 也是证据, 说明链路通、只是没配钥匙)。
4. **路径反代那几条会一起死**: /st/ /dash/ /ov/ 的目标服务就在被关的机器上, 关机后 nginx 只会 502。
   关机前必须跟用户讲清楚哪几条断、哪几条还活, 不要让他出门才发现。

## 坑
- **`sudo -S` 不能和 heredoc 同时用**: `echo pw | sudo -S tee file <<EOF` 的 stdin 被 heredoc 占走,
  sudo 读不到密码 → `3 次错误密码尝试`。正确顺序: 本地 `cat > /tmp/unit` → `scp /tmp/unit host:/tmp/` →
  `echo pw | sudo -S cp /tmp/unit /etc/systemd/system/` → `daemon-reload` → `enable --now`。
- ECS 的 sshd 必须 `GatewayPorts yes` 才能 -R 0.0.0.0 (回环绑定则无所谓)。
- systemd 里跑 ssh **必须显式 `-i <key> -o IdentitiesOnly=yes`**: 能用的钥匙是 `id_ecs_tunnel` / `zmax_ecs_ed25519`,
  `id_ed25519` 不在 ECS authorized_keys 里 (交互式和 systemd 环境 HOME 不同会掩盖这个问题)。
- **`pkill -f <pattern>` 会先杀掉执行它的那个 shell**(命令行本身就含这个 pattern, `-f` 全匹配) ——
  表现是命令返回 `exit -15/SIGTERM`、后面的步骤一个都没跑。三种正确写法:
  ① 括号技巧 `pkill -f "edge_serv[i]ce.py"`;
  ② 写成脚本文件再执行, 脚本里用 `[s]sh .*-R` / `[d]ashboard_server` 这种模式;
  ③ 按端口/pid 反查 `ss -ltnp` 或 `pgrep -f '^/usr/share/code/code'` 锚定完整 argv 再 `kill`。
  杀之前先 `ps -eo pid,args | grep -c` 看一眼会杀到几个。
- **登录失败的典型不是密码错, 是用户名错**: 主机名(如 `ubuntu`) ≠ 登录账号。先在目标机
  `getent passwd | awk -F: '$3>=1000 && $3<65534 {print $1}'` 列出真实用户; 用主机名当用户名去登录 →
  `Permission denied`, 看起来一模一样。区分"链路不通/账号不对/密码不对": 从公网侧 `sshpass -p <pw> ssh
  -o PubkeyAuthentication=no -p <port> <user>@<public>` 一跑就三样分开。
- 多个旧单元会抢同一个 -R 端口 → 新服务 `ExitOnForwardFailure` 直接退出、状态永远 activating。先 `ss -ltn` 看 ECS 监听、清重复。
- 插 nginx location 用 python 在**最后一个 `}` 前**插入并 `nginx -t` + reload; 写 `$host` 时注意 shell/python 双重转义 (写成 `\$host` 会留下字面反斜杠)。
- tunnel_proxy 需要 `?k=<token>`(首次种 cookie), 否则 403 71B —— 这不是故障。

## 验证口径 (每次都从外部打, 不用浏览器)
```
for u in "/dash/dashboard.json" "/st/?k=zmax-live" "/st/snapshot/arm.jpg?k=zmax-live" "/ov/?k=zmax-live"; do
  curl -sk -o /dev/null -w "$u %{http_code} %{size_download}B\n" "https://datadrive.world$u"; done
# 期望: 200 / 12719B / 200 4275B / 200 ~57KB jpg / 200 4275B
```
