---
name: industrial-lan-recon
description: Use when 清点产线局域网设备或判定工控机能否访问。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [network, ot, industrial, smb, reconnaissance, zmax]
    related_skills: [orin-lan-direct-access, real-arm-motion-control, http-relay-service]
---

# 产线 / 工业局域网 设备清点与访问判定

## When to Use（触发）
- 「这个局域网都有哪台电脑」「某 IP 能不能访问」「这台工控机能不能连」
- 拿到一个网段（如 192.168.23.0/24）要摸清有哪些设备、各是什么、能开到什么程度
- 需要判定某账号在 Windows 工控机上到底有没有权限（**认证通 ≠ 有权限**）

> 📌 本轮实测快照（设备清单 + 访问结论 + 待办）: `references/lan-inventory-2026-09-18.md`
> 📌 直接可跑的枚举脚本: `scripts/lan_inventory.py`

## 一、枚举必须走 ARP 层，不能只 ping

现场设备常开防火墙不回 ICMP，ping 扫描会漏。ARP 层做法（**不需要 root**）：
```bash
ip neigh flush all dev <if>          # 清表, 避免 STALE 假阳性
# 对 <net>.1-254 逐个 UDP sendto((ip, 9)) → 触发内核 ARP 解析 (几秒内全部完成)
ip neigh show dev <if>               # 有 lladdr 的 = 真设备; FAILED/INCOMPLETE = 空地址
```
- 比 nmap ping-scan 准，且一次拿到 MAC（供厂商识别复用）。
- 本机自己的 IP 不会出现在表里（内核不为自己 ARP）→ 手工补上。

## 二、身份四件套（按信息量排序）

1. **MAC OUI → 厂商**：`https://api.macvendors.com/<mac>`
   ⚠️ **必须串行 + 间隔 ≥1s**；线程池并发会被限流成 `?`（实测 6 台并发丢 4 台）。
   实测有价值前缀：`00:02:c4`=OPT 奥普特(机器视觉) · `cc:82:7f`=研华 Advantech(工控机) · `34:df:20`=深圳康士达(控制器) · `3c:6d:66`/`74:25:54`=NVIDIA(Jetson/Orin)。
2. **TTL 指纹**：`ping -c1 -W1 <ip>` 读 `ttl=` → Linux≈64 / Windows≈128 / 网络设备≈255。
3. **端口 + banner**：SSH banner 直接暴露发行版（`OpenSSH_7.2p2 Ubuntu-4ubuntu2.10` = 老 16.04 系 → 老控制器）。
4. **Windows 名字**：NetBIOS **NBSTAT**（UDP 137）→ 机器名 + 工作组 + suffix（`<00>`工作站 `<20>`文件服务）。
   坑：应答 header 的 `qdcount` 可能是 0（不回显问题段）⇒ **别按固定偏移解析**，直接在载荷里扫
   18 字节名字记录（15B 可打印名 + 1B suffix + 2B flags<0x8000）。

## 三、工业设备专用探测（TCP 扫描会骗你）

**GigE Vision 相机/视觉控制器常没有任何 TCP 端口**（只讲 UDP），纯 TCP 扫描会判成"没服务"。
标准 GVCP 发现包：UDP `3956` 发 8 字节 `42 11 00 02 00 00 00 01` → 有 256B 应答 = 确是 GigE Vision 设备（应答含设备 MAC）。
同理 Modbus 502 / OPC UA 4840 / EtherNet-IP 44818 都是"有没有服务"的判据，别只看 TCP 常见段。

## 四、SMB 权限阶梯（认证通过 ≠ 有权限）

```bash
smbclient -L //<ip> -U 'user%pass'                      # ① 列共享: 只有 ADMIN$/C$/D$/IPC$ = 无用户级共享
rpcclient -U 'user%pass' <ip> -c 'lookupnames <user>'   # ② SID 末位 RID: 500=内置管理员, 1001+=普通用户
rpcclient -U 'user%pass' <ip> -c 'srvinfo'              # ③ 版本/机器类型 (platform_id 500, os version 10.0)
rpcclient -U 'user%pass' <ip> -c 'netshareenumall'      # ④ 非管理员 → WERR_ACCESS_DENIED
smbclient //<ip>/C\$ -U 'user%pass' -c 'ls'             # ⑤ ACCESS_DENIED + RID≠500 ⇒ 该账号不是管理员
```
错误码速查：`NT_STATUS_ACCESS_DENIED`(匿名/无权限) · `NT_STATUS_ACCOUNT_DISABLED`(guest 被禁用)
· `NT_STATUS_LOGON_FAILURE`(密码错) · `WERR_ACCESS_DENIED`(该 RPC 要管理员)。
依赖：`sudo apt-get install -y samba-common-bin smbclient`（提供 nmblookup / rpcclient / smbclient）。

**取不到文件时的三条出路（按最小权限排序，交给用户选）**：
1. 让现场在那台机上**建只读共享**指向目标目录，授权给已有普通账号（不交出管理员密码）
2. 拿一个 Administrator / Administrators 组成员的账号（**RID 500**）→ 才能进 `C$` / `D$`
3. 要远程执行 → 需管理员开 **RDP(3389)** 或 **WinRM(5985)**（默认都关）

## 五、红线与纪律

- **网络可达 ≠ 获得授权动作**：只做只读探测（列共享 / 协议协商 / 查名字 / 拿版本）。
- **不猜密码、不爆破**：会锁账户，也可能触发产线安全软件与告警。同一密码试另一个账号名（如 Administrator）最多一次。
- 任何写操作、远程执行、调会改状态的接口（产线 HMI / 控制类 HTTP）都要用户**点名**才做，并留前后证据。
- 工控机上的自研 HTTP 服务（Flask/FastAPI）只 GET 文档类路径（`/openapi.json`、`/docs`、根路径）；
  POST / action 一律等点名。

## 六、等一个端口/服务起来（常见需求）

用户说「我一会儿从工控机起服务」时：**挂后台轮询器**（每 20s 探一次 TCP，最长等 30-50 分钟，`notify_on_complete`），
一起来就自动抓：HTTP `Server` 头（确认 uvicorn/FastAPI + 版本）· `/openapi.json`（FastAPI 默认暴露
**全部路由** = 接口清单）· `/docs` 标题 · 根路径响应。
若对方关了 docs（`docs_url=None`），`/openapi.json` 也会 404 → 只能报"端口开了 + Server 头"，接口清单要人工给。

## 七、已知的段与角色（持续更新，详细见 references）
| 段 | 谁在用 |
|---|---|
| 192.168.23.0/24 | 产线网：本机 .50（USB 千兆直连）· Orin .66 · 珞石控制器 .160 · 研华工控机 .23 · NVIDIA 边缘盒 .203 · OPT 视觉 .2/.8 · 诺达佳 Intel 边缘机 .70（X7 358H · NPU+Arc B390 · RT 内核 · ROS2 Jazzy · 6×CAN） |
| 10.163.146.0/23 | 本机 WiFi（公司网，未清点） |
| 192.168.124.0/24 | Orin 的 WiFi（另一张网，未清点） |
⚠️ **网关 .1 不回应 ARP**（本机/Orin 的路由表都指向它，但该地址没有设备）→ 别把它当可用网关。

🔴 **本机是双网卡两条独立路径, 诊断前先认这张脸**: 产线网走**有线**(USB 千兆, 路由 metric **100**), 外网/办公网走 **WiFi**(metric **600**)。
⇒ ① 访问 `192.168.23.x` 一定走网线, 不会串到 WiFi; ② 反过来 **产线设备只有网线走得到, 从 WiFi 侧永远够不着** ——
"某台机器连不上"先确认探询是从哪张网卡出去的, 别拿 WiFi 段的结论去判产线设备。
判据就是 `ip route` 里那行 `192.168.23.0/24 dev <有线> metric 100`, 以及 `ip -br addr` 里 `enx*`(USB 有线)与 `wlp*`(WiFi)的分工。
部署/同步数据也同理: 跨机拉文件走哪条路由由目标 IP 决定, 不需要手工指定网卡。

## 八、跨机视觉链路: 点云通道(梅卡曼德/Mech-Vision 那一类)怎么判活

点云不是相机直连，是一条**跨机 HTTP 链**: Windows 侧出 `.npy` → 边缘侧(Orin)拉取 → 转成 ROS 话题。实测这条链的落点是:
- Windows 工控机上另开一个端口(实测 10081)承载视觉软件通道；**它与产线检测端口(10082/10083)互不影响** ——
  检测正常不代表它活着, 反之亦然。"点云没了"先查它。
- Orin 侧有一个 ROS2 包专门做接收(自述 = 从 Windows 经 HTTP 收 `.npy` 点云 → 发 `PointCloud2`)。
  **它不在 `ros2 node list` 里 = 消费端也没在跑**; 那时 `ros2 topic list` 只剩 RealSense 那几条。
- 视觉软件的指向写在**每套产品的配置**里(`<产品>/vision/mech_vision_*.yaml`): 位姿那条与点云那条**可能指向不同的 Windows 主机**,
  其中一台可能早已下线 ⇒ 断链要**分别查三处**: ① 出点云那台在不在线 ② 端口在不在听 ③ 接收节点在不在跑。

**判活三层(别把三件事混成一句"连不上")**:
```bash
ip -br addr | grep '\.23\.'                        # ⓿ 本机有没有该网段的地址/网卡 (USB 网卡不在位 ⇒ 以下全是假阴性)
ping -c2 -W2 <ip>                                  # ① 整机: 100% 丢包 = 机器不在(关机/拔线/网口)
timeout 3 bash -c "echo > /dev/tcp/<ip>/<port>"     # ② 服务: 连接被拒 = 机器在、服务没起
curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://<ip>:<port>/<path>   # ③ 应用: 000=端口无应答
```
- ⓿ **先查本机地址**: 本机连 `192.168.23.x` 都没有 ⇒ 结论是"**网卡不在位**"(USB 网卡没插/被拔), 不是"设备挂了/服务挂了", 也不要因此去重启任何服务; 同时按铁律不下发动作。
- 🔴 **`ping` 不通时先去读 ARP 状态 —— 它一句话就能分开"关机"与"防火墙"**: 对同一 IP 发过一次探询后看
  `ip neigh show <ip>`。`INCOMPLETE`(= 内核发了 ARP 但**没有任何设备回 MAC**) ⇒ 对端**根本不在这个二层网里**
  (关机 / 拔线 / 网口 down), 与防火墙、路由、服务全都无关: 此时不要再试端口、不要改本机网络、不要重启服务;
  `REACHABLE` + 有 `lladdr` 而 ping 不通 ⇒ 机器在、只是挡了 ICMP, 继续往下判端口。
  **判决力差异**: ICMP 被防火墙丢掉 和 机器关掉, 在 ping 眼里是同一个现象; 在 ARP 眼里不是。别用 ping 一家之言下"机器挂了"的结论。
- **判"不在线"之前再扫一遍全段, 排除"它换了 IP"**: ARP 层扫 `<net>.1-254`(见 §一), 同时看两件事 ——
  ① 目标 IP 回来没有 ② 有没有**陌生 MAC**(换地址会冒出一个从没见过的 lladdr)。
  只有"原 IP 没有 + 也没有新 MAC"才可下"机器物理不在网里"的结论; 只 ping 一个地址就报"连不上",
  会把"换了 IP"误判成"没开机"(反之亦然)。扫完顺手把存活清单连同 MAC 一起报给用户, 他一眼就能认设备。
- 查**远程**服务的端口不要用本机 `ss -ltn` —— 那只列本机监听, 拿它报"10082/10083 DOWN"是纯误报; 要用 `timeout 3 bash -c 'echo > /dev/tcp/<ip>/<port>'`。
三种组合结论不同: ① 失败 ⇒ 先回 ⓿ 确认本机地址在位, 在位才是整机不在线(否则是本机网卡/线的问题); ① 通而 ② 失败 ⇒ 服务没起;
② 通而 ③ 给 404 ⇒ **服务在、只是该路由不存在**(版本会推翻历史结论 ⇒ 现探再断言, 见 §四)。
- 本机要"借道上网"时别改产线机的网络设置 —— 见 `windows-plant-host-operations` §七(在操作机侧起受限代理, 产线机只借一条命令)。

## 九、新接入一台 Linux 设备：指纹 → 拿访问权 → 一轮家底

### 9.1 先三层指纹，别先要账号
`ping -c3`(TTL: 64=Linux/128=Windows) → `ip neigh`(MAC) → 端口扫描 + **SSH banner**（banner 一行就把发行版/版本交出来）。
- 扫描用 python socket + 线程池，不要卡在"装 nmap"; 必扫的身份口:
  `22` `80` `443` `8080` `16992/16993`(Intel AMT) `623/664`(IPMI) `3389` `5900` `502` `4840` `1883`。
- **结论要按实际端口说话**: 只开 22 + `OpenSSH_x.xp1 Ubuntu-y` ⇒ 就是一台 Ubunty 主机,
  不是"带 Web 管理页的工业控制器"; 没有 AMT/IPMI ⇒ 它没有带外管理，重启只能找人现场或远程桌面。
- OUI 查不到厂商不等于杂牌: `api.macvendors.com` / `api.maclookup.app` 对小批量前缀常返空 ⇒ 以 banner/系统信息为准。

### 9.2 SSH 不泄露用户名 —— 别枚举
不存在的用户与密码错，`Permission denied (publickey,password)` 提示**一模一样**，试名字试不出结果，爆破还会锁号。
用户名只有三个来源: ① 机器登录界面（Ubuntu 会显示上次登录用户）② 在那台机上 `whoami` ③ 别人原有机器上的 `~/.ssh/config` / `history | grep ssh`。

### 9.3 拿访问权：给现场人员的命令永远只有一行
他会直接回你"代码太多了，还得手动操作"。定式:
- 他在**操作机**上: `ssh-copy-id -i ~/.ssh/id_ed25519.pub <user>@<ip>`（口令由他自己输，我不碰）。
- 他在**目标机**终端里: 一行装完并回执——
  `mkdir -p ~/.ssh; chmod 700 ~/.ssh; echo '<pubkey>' >> ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; echo OK`
  （`chmod` 不能省，sshd 会因权限过宽拒收；`echo OK` 是回执，比"应该好了吧"可靠）。
- 他把口令直接打在聊天里时: `sshpass -p '<pw>' ssh-copy-id ...` 一次装好公钥，随后**全部走密钥**
  （`ssh -o BatchMode=yes` 验通），口令不写进任何文件，并提醒弱口令（如 user/user）风险。
- 装完立刻验一行: `ssh -o BatchMode=yes <user>@<ip> 'hostname; whoami; uname -sr'` —— 验不过就不要继续摸家底。

### 9.4 一轮家底（一条 ssh 批量跑，别一条条问）
系统/内核(`uname -a` · `/etc/os-release` · `uptime -p`) · CPU(`lscpu` 型号/核数/主频/L3) · 内存磁盘 ·
加速器(`lspci | grep -iE "vga|display|3d|accelerator|npu"` · `ls /dev/dri /dev/accel` · `sycl-ls` · `clinfo -l`) ·
网口(`ip -br addr`) · 监听(`ss -ltnp`) · 非默认 running 单元 · 容器 · `ls /opt ~` · 关键包
(`openvino` `onnxruntime` `torch` `ros-*` 计数)。
判读要点:
- `nproc` < `lscpu` 的 CPU 数 ⇒ 有核被 RT 隔离 (`isolcpus`)；内核名带 `-rt` ⇒ PREEMPT_RT ⇒ **产线执行端**候选，不是纯推理机。
- "装了 ROS 但没装推理栈"(有 `ros-jazzy-*` 296 个包、无 openvino/onnxruntime/torch) ⇒ NPU/GPU 空着，先装推理栈跑基准再谈"能不能替代 Orin"。
- 有 `/dev/accel/accel0` + `level-zero-npu` 才是真 NPU；只有 `/dev/dri/renderD*` 是核显。
- 跨版本 ROS (Humble ↔ Jazzy, aarch64 ↔ x86_64) **不假设互通**: 标准 msg 的 DDS 能过，自定义 msg 的字段/类型不一致会静默不匹配 ⇒ 走网关/桥。
- 顺手看 `~/.bash_history` 最后几条: 常暴露上一家在这台机上试过什么(如 `ping` 过哪台机、跑过哪个 tuning 脚本)。
