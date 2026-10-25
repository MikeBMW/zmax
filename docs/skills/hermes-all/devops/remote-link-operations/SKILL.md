---
name: remote-link-operations
description: "Use when 远端链路(跳板/反向隧道/直连)断了或要在远程与局域网双模间切换。"
version: 1.0.0
author: agent
tags: [network, ssh, tunnel, frp, systemd, watchdog]
platforms: [linux]
---

# 远端链路运维：跳板 / 反向隧道 / 双模切换

适用：本机要够到内网设备（Orin/工控机/训练机），入口只有「跳板机 + 设备自建反向隧道」，或本机能插网卡直连
同一网段。症状形态：位姿/画面/推流全断、端口能连但 SSH 不通、unit 显示 active 却没反应。

## 0. 先分层定位，不要一上来就假设是网络
按 ping → 端口 → 应用 三层各测一次，三层的组合直接给出结论：

| ping | nc 端口 | 应用层 | 结论 |
|---|---|---|---|
| 通 | open | SSH 卡 `banner exchange` 超时 / HTTP 000 | **主机用户态卡死**（内存/磁盘/负载爆），去云控制台重启实例，别再查网络 |
| 通 | refused | — | 该服务没起（不是链路问题） |
| 通 | open | 正常 | 链路没事，问题在上层（位姿桥/相机/推流各查各的） |
| 丢包 | — | — | 真网络断：网线/交换机/VLAN |

判卡死的那条最容易误判：端口是内核应答的，用户态 hung 时端口照样 `nc` 得通，只有握手和 HTTP 会超时。

🔴 **判「用户态卡死」要一次试多个不相干的端口，只看一个分不清两种病**：
同刻打 ssh 22 / 跳板 22022 / https 443 / 面板端口 —— **全部 TCP 握手成功而 SSH banner 与 TLS 都超时** ⇒ 整机应用层假死；
若只有目标端口 refused、别的端口正常应答 ⇒ 是那一个服务没起，不是卡死。ping 通（实测 27ms）也不能当成"机器好的"证据。

🔴 **一台中转机假死会同时打掉四条链，别当四个独立故障逐个修**：
① `-R` 隧道反复重启（`NRestarts` 分钟级上涨，日志 `Timeout, server … not responding`）；
② 所有 `-L` 转发**本地监听直接消失**，而它们的 unit 仍报 `active`（`ss -ltn` 里 10082/18792 这类口没了 ⇒ 靠它的 AOI/取流服务一起 000）；
③ 经它做 `ProxyJump` 的内网设备全部不可达（跳板一断，内网那几台跟着"消失"）；
④ `/ov/` `/st/` 公网口 000/502。
⇒ 判据顺序固定：**先证中转机应用层活着，再谈内网设备**；反过来先查内网设备会绕远路，还会把"环境缺失"误报成"设备坏了"。

🔴 **中转机不可达又没有带外通道时，内网设备只能报「最后已知快照 + 时刻」**：写「17:26 实测在跑，现在不可达」，
**不许写成现在时**（"X 没在跑"/"X 挂了"），也不许因为探不到就说它坏 —— 用户会把你的现在时当结论用。

🔴 **公网 502 而本机闸门 200 时，先对齐「域名 A 记录指的那台」与「隧道落地的那台」**：两台不是同一台，
表现就是首页 200（另一台也挂着同一份站点）而 `/ov/` `/st/` 全 502 —— 这不是隧道坏，是域名换了主机、隧道没跟着换。
别按本文去对端清端口（白折腾一轮）；取命令与判据见 `linux-host-maintenance` 的 §9c 末条。

🔴 **卡死后温和重启常常救不回来，用「停止 → 启动」硬复位。** 实测在控制台点一次普通重启后，
`ssh` 依旧 `banner exchange timeout`、反向端口依旧不出现；必须彻底 stop 再 start（等价于断电冷启）。
复位后**先复测再汇报**，不要假定“重启了就好了”—— 判据就用 §8 那几条。
如果 SSH 完全进不去，云控制台的 **VNC / 串行控制台 / 远程连接** 是唯一入口；进去先跑三行定性：
`df -h /` · `free -m` · `journalctl -u <跳板服务> -n 20`（磁盘满是 sshd 无法 fork／写日志的常见根因）。

🔴 **反复 banner 超时 = 容量到顶，重启只是止血。** 同一个跳板机隔几十分钟卡一次时，别再当“偶发抽风”：
重启恢复后**第一件事**就是查余量（`df -h /` + `free -m`）。实测一台 1.6G 内存 / 40G 盘用到 90% 的实例
一天内卡三次，症状全是“TCP 能连、应用层不响”，而每次重启都能“好”十几分钟 ⇒ 正确结论是**挪机器**，
不是继续重启。把这句话直接告诉用户，并给出迁移清单，不要每轮都重启一遍。

## 1. 反向隧道「unit 看着 active、转发其实已死」是最贵的坑
跳板端口往往**不是跳板机 sshd 的端口**，而是内网设备用 `ssh -R 0.0.0.0:<port>:127.0.0.1:22` 反向注册出来的。
跳板机重启后这条已建立连接半开：**ssh 进程不退出 ⇒ systemd 不重启 ⇒ unit 一直 active，端口却根本不存在**，
可以静默失联几十分钟而没人发现。

判据链（三头都要看，只看一头会判错）：
```bash
ss -ltn | grep <反向端口>                       # 跳板机上：没有监听
ss -tn | grep :<frp bindPort>                   # frp 侧零客户端 ⇒ 不是服务端挂了, 是客户端没连回来
systemctl is-active <tunnel-unit>; journalctl -u <tunnel-unit> -n 5 --no-pager   # 设备上 active, 日志停在很久以前
```
`ServerAliveInterval` / `ServerAliveCountMax` 在这种半开下**不可靠**，不要靠参数兜底。
恢复：设备上 `systemctl restart <tunnel-unit>`，实测 5s 内端口立即回来。

## 2. 主动探测式自愈（装在**内网设备**上，不是跳板机上）
跳板机挂了时，只有内网设备自己能重启自己那条隧道。设备侧装 timer：
- 从设备探 `/dev/tcp/<jump-host>/<反向端口>`（用 bash 内建，不依赖 nc 是否装）
- **连续 3 次（≈60s）失败才 restart** —— 单次抖动就重启会把好链路打断，这是必须的冷却
- `OnUnitActiveSec=60`，脚本放 `/usr/local/bin/`，oneshot service + timer

模板见 `references/tunnel-watchdog.md`。

## 3. 双模切换：一个别名当开关，别在 unit 里写 IP
本机同时可能有「远程跳板」和「插网卡直连内网」两条路。把模式做成 ssh config 里的一处：
```
Host <dev>        → <jump-host>:<port>      # 远程/默认
Host <dev>-lan    → <lan-ip>:22             # 插产线网卡时
Host <其他内网设备> → ProxyJump <dev>        # 两种模式下都成立
```
**所有隧道 unit / 脚本的 ExecStart 一律写别名 `<dev>`，绝不写 IP** ⇒ 换模式只改 config 那两行，unit 一个都不动。
这是整套设计的关键；写死 IP 之后每换一次模式就要改 N 个 unit，迟早漏一个。

## 4. 自动切换的判据要「三条同时满足」，宁可不切
本机 timer（30s）自动切 LAN，只有当：
1. 出现有线网卡（排除 `wl*` `docker*` `veth*` `br*`）且 `carrier=1`
2. 该网卡上真有 `192.168.x.x` 目标网段地址
3. `ping <目标设备>` **真通**

三条都满足才切；否则保守留 remote。**把好链路切到一个假直连上，比不切更糟。**

🔴 **拔网卡前必须先证“远程那一端能接住”**（用户说“切回远程”时尤其如此）：只测端口不够，要真走一次
`ssh -p <反向端口> <跳板> 'hostname'` 并验一个内网服务（`curl 127.0.0.1:<桥端口>/status`）。
远端还没恢复就拔网卡 = 主动把产线断掉，而且那一刻连修都修不了（LAN 已经没了）。

拔线前的验收阶梯（从上往下全过才算通，任何一层失败各自的负责人不同）：

| # | 验什么 | 命令 | 失败含义 |
|---|---|---|---|
| 1 | 跳板机 sshd | `ssh -p 22 <user>@<eip> 'uptime'` | 实例本身卡死 → 云控制台硬复位 |
| 2 | 反向隧道端口 | `nc -z -w4 <eip> <反向端口>` | 内网设备 frpc 没回连 → 设备侧 restart 隧道 |
| 3 | 穿透落到哪台 | `ssh -p <反向端口> <user>@<eip> 'hostname'` | 落到意料外的机器 → 隧道指向错实例 |
| 4 | 内网第二跳 | `ssh -J <user>@<eip>:<反向端口> <内网用户>@<内网IP> 'hostname'` | 内网段不通 → 看设备侧路由/网卡 |

每层都回显 `hostname`，不要只看“端口开了”。实测第 1 层 banner 超时、第 2 层 refused、第 3/4 层 `Connection refused`
是同一次跳板卡死的四连表现 —— 只看第 2 层会误判成“隧道没起”。
顺带：远端刚重启时反向隧道往往还没回连，设备侧 watchdog 会自己重启，不要手忙脚乱去改配置。
反过来，网卡消失/拔掉 ⇒ 判据不成立 ⇒ 自动切回 remote，不需要人发话。
注意：换 USB 网卡适配器后接口名会变（`enx<MAC>`），静态 IP 的绑定口名要跟着改，否则 IP 配到别的设备上。

🔴 **切模式后，已经在跑的长任务不会重读 config —— 必须杀掉重跑，不要等它自己好。**
模式切换只影响**新建立**的连接；切换前拉起的 `rsync`/`scp`/下载/训练监控仍卡在旧 ProxyJump 链上，
表现为“传了几十 M 就不动了”（`ps` 里 `Stat=Ss` 长时间不变）。
- `kill -TERM` 对这种挂死连接**经常无效**（它在 socket 上睡），直接 `kill -9`，再按 LAN 重跑增量——
  `rsync -a` 天然续传，不丢已传部分。
- 杀掉后先 `ssh <别名> 'hostname'` 验一次链路真通了，再重启传输；否则可能又跑在旧链上。
- 判链路的另一条：ssh 报 **`Connection to UNKNOWN port 65535 timed out`** = ProxyJump 那一跳没通，
  65535 是占位符不是真端口，别去查那个端口。此时看的是跳板机状态，不是目标机。

## 5. 守护脚本：连不上 ≠ 任务结束
凡是「等远端任务跑完再做事」的守护，都不许把 SSH 失败当成「进程不存在」：
```python
for _ in range(3):
    rc, out, _ = ssh("pgrep -fc '<cmd> .*%s'" % job)
    if rc == 0:
        return int(out.strip() or 0) > 0
    time.sleep(5)
return True     # 连不上 ⇒ 按「还活着」处理, 继续等, 绝不据此下结论
```
真实代价：链路断时守护误判「训练已退出」并跳过切换，而训练其实还在跑到 25400/30000 —— 表现为「任务完成但没结果」。

## 6. 找进程别用 `pgrep -af <名字>`，也别用 `pkill -f <名字>`
命令行里含目标字符串 ⇒ 匹配到自己的 shell，输出假阳性；`pkill -f` 更狠，**会把自己那条命令一起杀掉**
（表现为整个 terminal 调用返回 `exit_code=-9 / SIGKILL`，看起来像被 OOM 杀的）。
按 `/proc/*/cmdline` 遍历精确匹配，或 `pgrep -x`；已知 pid 就直接 `kill <pid>`。
杀之前先 `kill -TERM` 看能不能收，收不了再 `-9`。

## 7. 改 ssh config 时的两个小坑
- 判断「已存在」要用 `"\nHost <name>"`（带换行）。注释里出现同名字符串会让 `"Host <name>" in text` 永远为真 ⇒ 静默不追加。
- 改完立刻用 `ssh -o BatchMode=yes <别名> 'echo OK'` 验证；**先备份** `cp -a ~/.ssh/config ~/.ssh/config.bak-<日期>`。
- config 改坏的后果是所有远端一步都走不了，所以“改配置 + 起隧道 + 验证”要一次做完，不要留着半截。

## 8. 恢复后必做的验收（每条都要有输出，不看“应该没问题”）
```bash
ssh <dev> 'hostname; uptime'                       # 落地在哪台, 负载是否异常
for p in <各隧道端口>; do (echo > /dev/tcp/127.0.0.1/$p) 2>/dev/null && echo "$p open"; done
curl -s <本机服务>/api/tcp | grep -E 'source|age|stale'   # 期望 source 回到实时源, age≈0, stale=false
```
只测「端口 open」不够：端口通但页面仍读陈旧文件，是隧道指向了错误实例（旧进程占着 socket）的典型表现。

## 9. 迁移跳板机前先看是不是弹性 IP
若跳板机公网 IP 是 EIP：解绑再绑到新实例 ⇒ 代码里所有硬编码地址**一处都不用改**；
不是 EIP 就得逐文件改。先花 10 秒确认这一条，能省掉几十到几百处替换。
迁移方式优先「系统盘快照 → 自定义镜像 → 新实例」，不要手工重装重配。

## 9b. 非 EIP 换机的实测清单（一处不能漏，漏一条就是一片 502）
换机真正要改的只有 **谁在建那条链路**，不是“所有出现过旧 IP 的地方”。按下面四层走，每层都有验收：
```bash
# ① 本机 unit (反/正向隧道 + 跳板) —— 漏一条就少一路口
sudo grep -l '<旧IP>' /etc/systemd/system/*.service
sed -i 's/<旧IP>/<新IP>/g' <每个 unit>; systemctl daemon-reload
# ② ssh config 的跳板别名 HostName (普通用户与 root 各一份!)
sudo 跑脚本时 ~ = /root ⇒ root 的 config 没有那个别名 ⇒ `ssh: Could not resolve hostname orin`
sed -i '/^Host <alias>$/,/^$/ s/HostName <旧>/HostName <新>/' ~/.ssh/config
# ③ 口令 (sshpass -e 的 EnvironmentFile / secrets 里的 *_PW)
# ④ 新机必须收我们的公钥 —— 老机上的 authorized_keys 不会自己跟过
sshpass -e ssh root@<新> 'grep -qF "$(cat ~/.ssh/id_x.pub)" /root/.ssh/authorized_keys || echo "$(cat ~/.ssh/id_x.pub)" >> /root/.ssh/authorized_keys'
```
**新机上的坑（按出现顺序）**：
1. `ufw` 默认 deny ⇒ 反向口建得出来、外网连不进来。**跳板口（如 22022）必须单独放行，且只放行我们的出口 IP**，其余回环口（nginx 反代用）一个都不要开。
2. 端口**被新机自己的服务占了**：老机上某个口是我们的 -R，新机上同一个口可能是新迁过来的后端（实测 18794 老机=手机控制台 -R、新机=/map/ 后端）。先在新机 `ss -ltn` 看该口有没有人听，再决定改口还是复用。
3. **两条 unit 抢同一个 -R 口**（实测 zmax-tunnel 与 zmax-ecs-orin 都建 22022）⇒ 带 `ExitOnForwardFailure=yes` 的那条会无限重启。留一条，另一条停掉并 disable。
4. **-R 的末跳是在本机执行的**：`-R 0.0.0.0:22022:192.168.23.66:22` 由**持有隧道的这台机**去连 192.168.23.66 ⇒ 本机产线网卡不在位时，这个跳板口“在听但连不上”（TCP 能握、banner 超时），别当成 ECS 挂了。
**验收四连**（缺一不算切完）：公网 `/ov/ /st/` 200 · 新机 `ss -ltn` 见到 1879x/22022 · `systemctl show -p NRestarts` 隔 20s 两次不涨 · 回读 `grep -rl <旧IP> /etc/systemd/system ~/.ssh/config` 为空。
凡脚本里“部署/上传/同步到 ECS”的默认值也要一起改（实测 27 个代码文件，其中指向别的机器的那几条要单独辨：如 `host: 旧IP, port: 50054` 是老机上的转发，不是网关本身）。

## 9c. 真正的入口常常是「内网设备自建的那条隧道」，不是本机的 -R

本机没有产线网卡（远程）时，能到产线的唯一一条路往往是**内网设备自己往跳板机注册的 `-R`**
（形如 Orin 的 `zmax-orin-tunnel.service`：`ssh -R 0.0.0.0:22022:127.0.0.1:22 root@<跳板>`）。
本机再 `-L`/`-J` 从这个口进去，中间那台 ECS 只是落地点，不参与转发。

1. **先问「谁在持有那个端口」**：跳板机 `ss -ltnp | grep :<port>` 看 pid 属于哪条连接，本机 `ss -tnp | grep :<port>`
   看你的 ssh 对端是同一条还是另一条。**两条 unit 抢同一个 `-R` 口时**，带 `ExitOnForwardFailure=yes` 的那条会无限重启；
   真正提供跳板能力的是另一条 ⇒ 把本机那条 `systemctl disable --now`，让设备那条独占，别去修重启的那条。
2. **改设备侧 unit 前先要一个能进设备的壳**：域名切了新跳板后设备通常还连着老跳板 ⇒ 用**老跳板**的
   `ssh -p <反向口> <user>@<老IP>` 进去改。老机应用层半死也没关系，只要那条 `-R` 还活着就够用。
3. **unit 里写域名，不写 IP**：`root@<domain>` 让隧道跟着 A 记录走，下次换机不用再登设备。判据：设备上解析该域名可用
   （它的遥测 uplink 已经在用域名，就是现成证据）。
4. **重启那条 unit = 你自己那根网线被拔**：你的 shell 正走这条隧道，必然收到 `Connection closed by remote host`。
   **这是预期，不是失败**，别急着回滚；从外面重新验证即可。
5. **跳板口会抖，单次失败不算断**：跳板机负载高时 `Connection refused` / `closed by remote host` 几秒后自己好。
   验收要**循环 3 次、间隔 4~6s**，全失败才判断；一次 refused 就改配置，会把本来好好的链路改坏。
6. **出口 IP 会漂**：ufw 只放行“我们的出口 IP”时，换房间/重连 WiFi 就换了一个出口（实测 `103.x` → `122.x`），
   症状是**超时**而不是 refused。先 `curl -s https://ifconfig.me` 拿当前出口，再补
   `ufw allow from <新IP> to any port <跳板口> proto tcp`，别动隧道。
7. **停掉本机 `-R` 后，跳板机上的 sshd 监听会赖着不走**（实测残留 ~25 分钟）⇒ 设备那条抢不到口。
   `ss -ltnp` 找到那个 sshd pid 直接 `kill`，等口释放再重启设备侧 unit。

## 9d. 跳板口公网不通时：从跳板机自己的 22 口走 `-W` 跳板
症状组合很好认：跳板机 22/80/443 通，但反向隧道口（如 22022）从本机**超时**（不是 refused）；同时跳板机上
`ss -ltn` 明明有该口监听、`ufw status` 也已放行我们的出口 IP ⇒ 拦包在**云安全组/运营商**，不在机器里，
别再去改 ufw/sshd（改了也不会好）。先在跳板机内部证明这条链是通的：
```bash
ssh root@<jump> 'ss -ltn | grep -E ":22022|:39061"'                 # 端口在听
ssh root@<jump> 'ssh -o BatchMode=yes -p 22022 <user>@127.0.0.1 hostname'  # 127.0.0.1:22022 = 设备反向注册的 sshd
```
然后用 22 口做跳板，目标指向跳板机自己的 `127.0.0.1:<反向口>`：
```
Host <dev>-jump
    HostName 127.0.0.1
    Port 22022
    User <dev-user>
    IdentityFile ~/.ssh/<dev-key>
    StrictHostKeyChecking no
    ProxyCommand ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -i ~/.ssh/<jump-key> -W %h:%p root@<jump-eip>
```
所有隧道 unit **只改 ExecStart 末尾的别名**（见 §3），端口号一个都不用动。

🔴 两个必踩的坑：
1. **ssh-agent 会掩盖「拿错 key」**：交互式 `ssh -i <错key> root@<jump> hostname` 成功**不代表**那把被授权——
   agent 里另一把 key 顶上去了。写进 systemd unit 后环境里没有 agent，立刻变成 `Permission denied (publickey)` +
   `status=255` 无限重启（日志要去看 unit 的 `StandardError` 落地文件，journal 里只有一行 `Main process exited`）。
   写进 unit 前必须隔离验证：
   `sudo -u <user> env -i /usr/bin/ssh -o BatchMode=yes -o IdentitiesOnly=yes -i <key> root@<jump> hostname`
   （`env -i` 去掉 `SSH_AUTH_SOCK`，`IdentitiesOnly=yes` 只试指定那把）。
2. **systemd 把 `%` 当 specifier**：ExecStart 里内联 ProxyCommand 必须写 `%%h %%p`，否则 ssh 收到被替换过的怪值直接失败。
   走 ssh config 别名能避开，但别名只对**运行 unit 的那个 User** 生效：`User=ubuntu` 读 `/home/ubuntu/.ssh/config`，
   `User=root` 读 `/root/.ssh/config`，少一份就 `Could not resolve hostname`。先 `systemctl show -p User --value <unit>` 确认。

验收：`ss -ltn` 见到各 `-L` 口 · `curl 127.0.0.1:<桥口>/status` 200 · `NRestarts` 隔 20s 不涨。
把 ECS 这一跳加进去后**每段动作指令多一跳**，段表/位姿的往返会慢一点；产线网卡回来后应切回直连。

顺带：`netplan apply` **不会**摘掉 NetworkManager 已经挂上的地址 ——
试验留下的影子地址（如 `192.168.23.50/24` 挂在一块没插线的 `enx*` 上，还带 `239.0.0.0/8` 多播路由）会一直留着，
把 DDS 发现钉在死网卡上。清理必须显式 `sudo ip addr del <ip>/24 dev <if>` + `sudo ip route del 239.0.0.0/8 dev <if>`，
再 `ip -br a` / `ip route show` 回读确认；只跑 `netplan apply` 会以为已恢复而其实还在。

🔴 **产线网口的 match 用 MAC，不要用 `enx*` 通配**：`enx*` 会把插着的**手机 USB 网络共享（RNDIS）**也当成产线网口，
把 `192.168.23.50/24` 配到手机上，整段 192.168.23.0/24 就被它吃掉，真网卡插回来也不通。先 `ethtool -i <if>` 认设备：
驱动是 `rndis_host`/`cdc_ethernet` 且 `Speed: Unknown!` ⇒ 是手机，不是产线网卡；产线网卡（Realtek 等）按 `match: macaddress:`
绑定，插哪个口、名字变成 `enxe6...` 都照样拿到同一个静态 IP。

🔴 **`netplan apply` 会重启 NetworkManager ⇒ WiFi 可能换到另一个 AP，本机 IP 跟着变**：
用户手里记着的 `http://<旧IP>:<端口>/...` 会立刻打不开（他报「页面打不开」时先 `ip -4 -br addr` 对一遍 IP，
别先去查端口/进程）。改完必须回读地址、按 SSID 切回原来的 AP（`nmcli con up <SSID>`），并给常用 AP 设
`connection.autoconnect-priority`（其余置 0），否则下次 apply/重连还会跳。
