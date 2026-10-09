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
| 192.168.23.0/24 | 产线网：本机 .50（USB 千兆直连）· Orin .66 · 珞石控制器 .160 · 研华工控机 .23 · NVIDIA 边缘盒 .203 · OPT 视觉 .2/.8 |
| 10.163.146.0/23 | 本机 WiFi（公司网，未清点） |
| 192.168.124.0/24 | Orin 的 WiFi（另一张网，未清点） |
⚠️ **网关 .1 不回应 ARP**（本机/Orin 的路由表都指向它，但该地址没有设备）→ 别把它当可用网关。

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
ping -c2 -W2 <ip>                                  # ① 整机: 100% 丢包 = 机器不在(关机/拔线/网口)
timeout 3 bash -c "echo > /dev/tcp/<ip>/<port>"     # ② 服务: 连接被拒 = 机器在、服务没起
curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://<ip>:<port>/<path>   # ③ 应用: 000=端口无应答
```
三种组合结论不同: ① 失败 ⇒ 整机不在线(别去修本机网卡/通道); ① 通而 ② 失败 ⇒ 服务没起;
② 通而 ③ 给 404 ⇒ **服务在、只是该路由不存在**(版本会推翻历史结论 ⇒ 现探再断言, 见 §四)。
- 本机要"借道上网"时别改产线机的网络设置 —— 见 `windows-plant-host-operations` §七(在操作机侧起受限代理, 产线机只借一条命令)。
