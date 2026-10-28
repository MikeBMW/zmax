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
- ⚠️ **但 ECS 上的 `frps` 仍在跑**(`/root/frp/frps.toml` · bindPort 7000 · vhost 8891 · unit `frps.service`): 它是另一路
  视频/HTTP 隧道, 与跳板无关。**不要因为它"属于已废弃的 frp"就去停/删** —— 先看 8891 上还有没有在用。
- nginx 旧的 `location /station → 127.0.0.1:18795` 已无监听(502), 改用 /st/。

## ECS 重启 / 迁移后的跳板恢复: 22022 是**本机**那条 `zmax-ecs-orin` 用 ssh -R 建出来的

推理顺序反了会白等半小时: `22022` 既不是 ECS 上的 sshd, 也不是 ECS 上的 frpc, 而是**某一个发起端**用
`ssh -R 0.0.0.0:22022:<本机>:22` 注册上去的。发起端**有两处都要查**: ①工位机的 `zmax-ecs-orin`
②**Orin 自己**的 `zmax-orin-tunnel`(`-R 0.0.0.0:22022:127.0.0.1:22`, 含义是"不依赖工位机"的那一套)。
只查工位机会得出"我这没建, 那一定是远端坏了"的错误结论。ECS 一重启这条 -R 就消失 ⇒ `ssh orin`
变成 `Connection refused / timed out`。**先在两端发起端查, 别先去 ECS 找原因**:
```bash
systemctl is-active zmax-ecs-orin; systemctl show -p NRestarts --value zmax-ecs-orin
journalctl -u zmax-ecs-orin -b --no-pager | tail -15   # remote port forwarding failed / Permission denied
sudo systemctl restart zmax-ecs-orin                   # 一次即可; 起来后 ECS 侧立刻出现 22022
nc -z <ecs> 22022 && ssh orin hostname                 # 硬判据: 端口在听 **且** 对面真是 Orin
```
⚠️ `nc -z` 成功只证明有人在听, 不证明对面是那台机器 —— 必须再补一句 `ssh orin hostname`。

**ECS 侧的 `frps` 在跑 ≠ 跳板通**: `/root/frp/frps.toml`(bindPort 7000 · token · vhost 8891)是独立的视频/HTTP 隧道组件,
`ss -tn | grep 7000` **零客户端连接是常态**, 不能据此判「远端掉线」(本次就照这条误判过一次, 把本机单元没重连说成了远端没连上来)。
判跳板只看 `22022` + `ssh orin hostname`。

### 🔴 「unit active + `Restart=always` + `ServerAliveInterval` 全都有, 隧道仍然是死的」

ECS 重启后那条 `-R` 会话可以是**半开**状态: 转发已失效、ssh 进程还活着 ⇒ systemd 不触发 Restart,
`journalctl` 40 分钟零日志, `systemctl is-active` 一直 `active`, 而现场表现是"产线静默失联"。
`ServerAliveInterval/CountMax` 在这类 drop 上并不能保证 60s 内退出。
⇒ **别信 `is-active`, 信对端**: 本机 `nc -z <ecs> 22022` 与 ECS 上 `ss -ltn | grep 22022` **两侧都看不到**才算真死。
处置两层:
1. 立刻: 在能到 Orin 时 `systemctl restart zmax-orin-tunnel` —— 实测重启后 22022 秒回, **不用动 ECS**;
2. 根治: 在**发起端**装对端可达性 watchdog(`zmax-tunnel-wd.timer`, 60s 一次): 从发起端侧连续 3 次(≈60s)
   `timeout 4 bash -c 'echo > /dev/tcp/<ecs>/22022'` 都失败才 `systemctl restart <unit>`。
   **单次失败就重启会被网络抖动误杀** ⇒ 必须"连续 N 次 + 间隔"。

### 🔁 LAN 直连 / 公网跳板 双模式: 隧道 unit 一律用 ssh 别名, 绝不预先固定 IP+端口

预先固定 `ssh -NT -p 22022 … <ECS_IP>` 的 unit, ECS 一挂四个隧道(位姿桥 / 臂相机 / 3DGS 推流 / Intel 相机)全废 ——
而当时插上网卡本来就能直连, 却没人切。定式:
- unit 里只写 `ssh -NT -L 19061:127.0.0.1:39061 orin`(**用 `~/.ssh/config` 的别名**), 一个 IP 都不写;
- config 留两个入口: `Host orin`(当前模式) + `Host orin-lan`(直连产线 IP:22); 远程模式时 `Host orin → <ECS>:22022`。
  `Host intel` / `Host gongkong` 一律 `ProxyJump orin` ⇒ 自动跟随模式;
- **切模式只改 `Host orin` 的 HostName/Port 两行**, 再 restart 那几个 unit 就全跟着切。

自动接管(不用人喊): 定时器 30s 巡一次, **判据全部满足才切 LAN** —— 出现有线网卡(排除 wlan/docker/veth/br)
· carrier=1 · 该网卡上有产线段地址 · ping 通 Orin; 任一不满足就保持/切回远程。
**宁可不动, 也不要把好链路切坏**; 拔线后判据自然失效 ⇒ 自动切回远程, 两种模式来回零人工。

⚠️ **carrier=1 不等于对面有设备**: 网线插在空口/断电交换机上时 carrier 仍是 1。真判据是**发 ARP 有没有人回** ——
`ping` 不通且 `ip neigh` 显示 `INCOMPLETE`, 再把整段 254 个地址并发扫一遍**只有自己应答** ⇒ 对面没有活设备
(不是本机网卡配错, 别急着改 netplan)。扫段用:
`seq 1 254 | xargs -P 64 -I{} sh -c 'ping -c1 -W1 192.168.23.{} >/dev/null 2>&1 && echo 192.168.23.{}'` (约 5s)。
⚠️ **别预先固定网卡名**: 换一根 USB 网卡名字就变(实测 `enxd223ec68e0a6` → `enx00e04c0c32a0`),
脚本一律按 `carrier=1` + IP 段动态找接口, 不要拿上次的名字去 `ip link set`。
⚠️ 改 `~/.ssh/config` 时判断"某段是否已存在"必须按 `'\nHost x'` **带换行**匹配 —— 注释里出现同样字样会让
`'Host x' in s` 判真, 静默跳过追加(以为写了实际没写, 用 `grep '^Host '` 复核一遍)。

### 「端口能建连、SSH 不握手、站点也不响应」= 主机用户态卡死, 不是网络
分层取数, 别 ping 完就下结论:
```bash
ping -c2 <ecs>                                  # 通(实测 28ms) ⇒ 网络没问题, 别在本机改网络配置
nc -z -w5 <ecs> 22 && nc -z -w5 <ecs> 22022     # TCP 能建连
ssh -p 22 root@<ecs> 'uptime'                   # ⇐ banner exchange timed out 才是真信号
curl -s -o /dev/null -w '%{http_code}' https://<站点>/   # 000
```
能建连 + banner 超时 + 站点 000 ⇒ **内核活着、用户态卡死**(ssh 会话吊死/负载爆/内存或盘打满), 本机侧无从下手,
只能云控制台重启。重启后 `:22022` 从 `timed out` 变成 **`Connection refused`** 就是主机已活的标志
(refused = sshd 在正常拒绝), 此时 22022 缺失按上一节处理(发起端 -R 重连)。

### 迁移到新 ECS: 先确认公网 IP 是不是 EIP —— 它决定工作量差两个数量级
- **EIP**: 解绑 → 绑到新实例 ⇒ 所有硬编码(IP/端口/域名)**一处都不用改**。迁移方式用**系统盘快照 → 自定义镜像 →
  新实例**, 别手工重装(nginx/宝塔/frps/relay 单元/站点目录都得原样带过去)。
- **非 EIP(随实例分配)**: IP 必变 ⇒ 代码面硬编码逐个改(本项目实测 `src/ tools/ deploy/ hermes_gateway_mac/` 下
  **117 个文件 / 313 处**, GUI 与 Android APK 都在其中, APK 还得重打包), 文档面另有一批。
- 顺序: **先查实例详情的公网 IP 类型, 再谈方案**; 别先动手改代码。
- 迁移后按序验: ping → 22/22022 → ssh 握手 → 站点 200 → 跳板 `ssh orin/intel` → 位姿真值回到实时(`source=orin_bridge`)。
  任一条不过就回滚旧实例(旧实例停服但**不要释放**)。

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
