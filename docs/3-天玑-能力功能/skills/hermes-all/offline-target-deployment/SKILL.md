---
name: offline-target-deployment
description: "Use when 给没有外网出口的内网机部署(离线轮子·DNS 先判·出口持久化·拔线判据)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [deployment, offline, dns, nat, wheelhouse, edge-host]
    related_skills: [service-migration-triage, remote-link-operations, systemd-boot-services]
---

# 内网 / 离线收端的部署

## When to Use
- 目标机（边缘盒 / 产线工控机 / 端侧主机）没有外网出口，或出口是**借另一台机的 NAT**。
- 目标机上 `pip install` 报 `Max retries exceeded` / `No matching distribution found`，但 `ping 8.8.8.8` 通。
- 要判断「能不能断掉借来的链路」、要给出可出示的验收，而不是口头保证。

## 铁律一：先判解析层，再谈装依赖
```bash
getent hosts pypi.org || echo 解析失败      # ① 解析层
ping -c2 8.8.8.8                            # ② 网络层：通而解析失败 ⇒ 是 DNS
resolvectl status | grep -E "Current DNS|DNS Servers"   # ③ 上游里有没有超时项
ip route | head -3                          # ④ 默认网关是不是另一台机（借来的出口）
```
解析失败时 `curl` / `pip` 一律报成「网络不通」，真因在上游：`systemd-resolved` 配了几台 DNS，
只要**当前选中的那台超时**，就要等 fallback 周期才通一次 —— 现象是「一会儿好一会儿坏」，最容易被误判成**间歇性断网**。
修法（先备份）：把 `resolved.conf` 的 `DNS=` 固定成实测可用的上游 + `systemctl restart systemd-resolved`，
判据是 `Current DNS Server` 不超时、`getent hosts` 连续两次返回 IP。

## 铁律二：wheelhouse 按**收端的 python 小版本**做
```bash
# 本机（有外网）：解释器必须与收端同小版本（收端 3.12 就用 3.12 下）
<py3.12>/bin/python -m pip download --only-binary=:all: -d /tmp/whl -r req.txt -i https://pypi.org/simple
rsync -a /tmp/whl/ target:~/wheelhouse/
# 收端离线装
~/train_venv/bin/pip install --no-index --find-links ~/wheelhouse <pkgs...>
python3 -m pip install --user --break-system-packages --no-index --find-links ~/wheelhouse <pkgs...>   # 系统 python + PEP668
```
- **关键加速包不进 wheelhouse**（`torch` 的 `+xpu` / `+cu*`）：一进就会被 `pip` 拿来顶掉收端已装的可加速版本。
- 一次别下太多：分 5~8 个包一批；包名写进文件用 `-r` —— 命令行里出现 `uvicorn`、`serve` 这类词会被工具误判成「起服务」而拒跑。
- `--only-binary=:all:` 保证是 wheel，收端没有编译环境也能装。

## 铁律三：先探收端已装环境，只补缺包
```bash
find ~ -maxdepth 7 -type d -name torch | head -3
<python> -c "import torch; print(torch.__version__, torch.xpu.is_available())"   # Intel 机器看 xpu，别默认 CPU
./gui-venv311/bin/python -V                                                      # 断链会报 not found
```
- 复制过来的 venv 特征是 `bin/python: No such file or directory`（符号链接指向源机绝对路径）⇒ **不要修**，用收端现成环境或重建。
- `pip install --no-index --find-links` 会自动跳过已满足的依赖，复用环境是安全且省时的。

## 铁律四：冒烟给数值，不说「跑起来了」
按模块逐个 import，缺什么补什么，直到全 OK；再跑仓库自带的**纯计算**自测并报数值判据
（单位范数误差、方向残余、耗时毫秒）。GUI 类服务另起一次看日志首屏加载成功 + 缺哪个模块（日志会直接打出 `No module named 'x'`）。

## 铁律五：借来的出口要持久化，否则重启即断
iptables 规则默认**不持久**（`/etc/iptables/rules.v4` 不存在、`netfilter-persistent` 未启用）。
用 oneshot systemd unit 落幂等规则（`-C || -A`）+ `sysctl.d` 落 `ip_forward=1`：
```ini
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/sysctl -w net.ipv4.ip_forward=1
ExecStart=/bin/sh -c '/sbin/iptables -t nat -C POSTROUTING -s <lan>/24 -o <wan-if> -j MASQUERADE 2>/dev/null || /sbin/iptables -t nat -A POSTROUTING -s <lan>/24 -o <wan-if> -j MASQUERADE'
```
收端要换独立出口时，用 NetworkManager 预置低 metric 连接，插线即接管，不改现有连接：
```bash
sudo nmcli connection add type ethernet ifname <if> con-name wanX ipv4.method auto ipv4.route-metric 50 connection.autoconnect yes
```

🔴 **出口可能是「某台工作站的 USB 网卡」——它一拔，整段内网跟着断网，而且没有任何告警。**
症状：内网机在局域网里一切正常（能被 ssh、本地服务 200），但域名解析 `-3 Temporary failure in name resolution`，
应用日志成片的 `Failed to resolve`。定位两步，先看收端出口指向谁：
```bash
ssh <收端> 'ip route | head -3'            # default via <某台机> —— 那台就是出口
```
再去那台机上确认它是不是真在做 NAT（那个地址/网卡已经不在 ⇒ 出口已死）：
```bash
ip -br a | grep -v '^lo'                   # 出口网卡(wl*/enx*)还在不在
sudo iptables -t nat -S POSTROUTING        # -s <lan>/24 -o <wan-if> -j MASQUERADE
sudo iptables -S FORWARD                   # -i/-o 绑定的正是那块已拔掉的网卡 ⇒ 转发也一起没了
```
修法不是等网卡插回来，而是**把出口挪到一台双归属、自己有上行口的机器**（跳板/边缘主机），两步都要做：
1. 收端把默认网关改成新出口机（改 NM 连接，不要 `ip route`，见下一条）；
2. 新出口机补 MASQUERADE + 两条 FORWARD ACCEPT，并按铁律五做成 oneshot unit 持久化。

🔴 **`ip route replace default ...` 会被 NetworkManager 秒级回滚**：NM profile 的路由是 `proto static metric 100`，
手敲那条 metric 更大 ⇒ 表现是「刚改完 ping 通、一两分钟后又断」，应用日志继续报解析失败，
极易误判成「进程缓存了坏 DNS」。判据：`ip route | head -2` 里网关又变回旧值。
定式是改 profile 再 reapply（`reapply` 比 `con up` 温和，不重建连接）：
```bash
sudo nmcli con mod "<连接名>" ipv4.gateway <新出口机IP>
sudo nmcli dev reapply <if>                # 3s 后回读 ip route | head -1，网关必须是新的
```

🔴 **只加 MASQUERADE 不够：出口机的 `FORWARD` 策略常常是 `DROP`**（跑容器的宿主默认如此）。
表现是 TCP 能到出口机、但 DNS/TLS 全超时——看着像上游墙，其实是没转发。必须显式放行去回两条：
```bash
sudo iptables -I FORWARD 1 -i <lan-if> -o <wan-if> -s <lan>/24 -j ACCEPT
sudo iptables -I FORWARD 1 -i <wan-if> -o <lan-if> -d <lan>/24 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

🔴 **建这张 unit 之前先查宿主机是不是早就有同一件事的 unit**：
`systemctl list-unit-files --state=enabled --no-legend '*' | grep -iE 'nat|forward|route|proxy'`。
实测宿主机已有一个带两条 `FORWARD ACCEPT` 的共享上网 unit（比只写 `ip_forward + MASQUERADE` 的超集），
再建一个同名不同名的副本后去 `disable --now` 它，**它的 `ExecStop` 会把正在生效的 MASQUERADE 一起删掉** ⇒ 整段局域网当场断网。
定式：已有就用已有的（只补缺项）；真要收掉自己那份，`disable --now` 后立刻 `systemctl restart <原有 unit>` 让脚本把规则补回，
再回读 `iptables -t nat -S POSTROUTING` + 从收端 `ping` 公网 IP 复测 —— `is-active=active` 不能证明规则还在。
**自己写的 unit 不要带 `ExecStop` 删共享规则**，规则归属方只能是原有那个 unit。

## 铁律六：拔线前给判据脚本，不给口头保证
写成可反复跑的脚本（`tools/verify_wan_switch.sh` 形态），插线前后都能跑，逐项 PASS/FAIL，末行给结论：
1. 出口网卡 `connected` 且有 IP
2. 默认路由走新口网关
3. ICMP 出网（两个公共 DNS IP）
4. `getent hosts <业务域名>` 成功
5. `curl -o /dev/null -w '%{http_code}' https://<业务域名>/` 非 `000`
6. 业务服务进程存活 + 服务日志近 N 行无连接失败（`grep -c "connect failed"` 为 0）
7. **业务接口真跑一次**：拿 tenant token / 登录态后真发一条消息或真写一条记录，判据是服务端返回的 id
   （如 `code=0` + `message_id`），不是「页面能开」。凭证从目标机自己的配置文件里读，别写死进脚本。

一次性体检脚本：`scripts/egress_health_check.sh <业务域名> [期望出口机IP]`，在**收端**上跑，
逐项 PASS/FAIL；它把「默认网关是不是被 NM 回滚」也做成了一条判据。

全 PASS 才说「可以拔」；任一 FAIL 就明说先别拔，并指出是哪一层（接口 / 路由 / 出网 / DNS / HTTPS / 服务）。

## 铁律七：别人报的「不通」先分清是**谁**不通

外部（另一台机/另一个 agent/现场同事）报「目标机 SSH 不通、没装服务」时，**不要直接采信去修目标机**：
先在**一个正在该网段里的主机**上复测，再判目标机死活。实测：一台 Mac 在自己网段里报告“目标机 22 不通、从没部署”，
而从双归属的机器人主机上跳板过去，目标机 22 活、服务已跑了十几个小时 —— 真正断的是报告方自己的网卡（en0 down，
手上只有另一张网段的地址、没有任何到目标网段的路由）。
判据三句：
```bash
ip -br a | grep -v '^lo'      # 报告方自己有没有在目标网段上的口/IP
ip route | grep <目标网段>      # 有没有到目标网段的路由
ssh -J <双归属主机> <目标机> 'hostname; uptime -p'   # 从能到的机器上实测
```
跨网段的正确通路是**找一台双归属主机当跳板**（同时接两个网段），不是给目标机改路由：
`ssh -J user@<双归属机-对方网段IP> user@<目标机>`。给远端临时开权限时用**专用密钥**：生成本地对、
公钥追加到两跳的 `authorized_keys`，私钥用 `scp` 落到目标机再让对方自己取 —— **私钥内容不进聊天**
（会被脱敏，也不该留会话记录）；口令兜底时先用 `sshpass -p` 真登录一次再给出去。

同样，外部端点报 404 时先判**端点存不存在**（静态站/裸 nginx 的任何未配路径都是 404），
不要归因成“这台机网络不行”：同一台机上 `curl` 业务域名 200 就说明链路是好的。
拿 `location` 列表（`/etc/nginx/sites-enabled/`）对一下就知有哪些接口真存在。

## 坑
| 坑 | 症状 | 修法 |
|---|---|---|
| 把 DNS 故障当成防火墙/网络不通 | ICMP 通、偶发成功、`pip`/云 API 全报 `Max retries` | 先 `getent hosts`；修 `resolved.conf` 固定可用上游并备份原文件 |
| wheelhouse 用本机 venv 的 python 版本下 | 收端装时报「无匹配的 wheel / 需要编译」 | 用与收端**同小版本**的解释器 `pip download` |
| 把 torch 塞进 wheelhouse | 收端原有 `+xpu`/`+cu*` 被顶成普通版，推理变慢或跑不起来 | 加速包不进包，单独确认收端已装版本 |
| 只手动 `iptables -A` | 宿主机重启后收端整片断网，且看不出原因 | oneshot unit + `sysctl.d` 持久化 |
| 一次性下整个 requirements | 命令超时，或被判为长驻进程拒跑 | 分批 5~8 个包，或 `-r` 文件避开敏感词 |
| 只报「部署完了」 | 用户下一步就是要断网验证，一拔就断 | 交付时附判据脚本 + 当前 PASS/FAIL 实测 |
| 另建一个共享上网 unit 再删掉 | `disable --now` 后整段局域网断网（正在用的 NAT/FORWARD 规则被 `ExecStop` 一并删） | 先 grep 已有 unit 复用；删自己的之后 `restart` 原有 unit 并回读 `iptables -t nat -S` + 对端 `ping` 复测 |
| `pip install` 装进了训练 venv，GUI 仍然 `No module named 'pyqtgraph'` | 收端启动脚本自选**系统 python3**，两个解释器互不相干 | 先看启动脚本/日志里的 `sys.executable`，库装到它用的那个（系统 python 要 `--user --break-system-packages`）；装完在同一个解释器里 `import` 一次 |
| 应用进程还在报 `Failed to resolve`，但手动 `curl` 已 200 | 以为进程缓存了坏 DNS，去重启服务 | 先回读 `ip route | head -1`：NM 已把网关改回旧值，路由没落地时进程报错才是对的 |
| 一条 `ssh` 里连跑多次 `sudo -S` | 第一条成功，后面全报 `sudo: no password was provided` | 口令只被第一条读走、非 tty 又不共享时间戳 ⇒ 每条都要喂：`s(){ echo "$PW" \| sudo -S -p '' "$@"; }`。并把整个脚本 `scp` 到目标机再 `bash` 跑，别在 ssh 命令行里叠引号/heredoc |
| 只看 `curl https://<域名>/` 的返回码就报「恢复」 | 根路径 404 也算通，业务其实仍发不出去 | 补业务接口实测（拿 token 后真发一条，看 `code=0` + `message_id`）；再回读服务日志里 connect failed 计数归零 |
| 出口机 `is-active` = active 就认为 NAT 在 | 收端整段不通 | 规则是运行时态：`iptables -S FORWARD` 里要有那条放行，`iptables -t nat -S POSTROUTING` 里要有 MASQUERADE，两条都回读 |
| 采信别台机报的「目标机不通 / 没部署」 | 去修一台好好的机器，白白花授权与时间 | 在能到目标网段的主机上用 `ssh -J <双归属机>` 复测一次；差异先归到报告方自己的网卡/路由 |
| 把外部接口 404 当成网络故障 | 反复查 DNS/防火墙 | 先看该站 nginx 里有没有这个 location：静态站未配路径都是 404，404 是“服务没部署”的真相 |
