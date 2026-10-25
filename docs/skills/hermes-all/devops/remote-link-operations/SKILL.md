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
