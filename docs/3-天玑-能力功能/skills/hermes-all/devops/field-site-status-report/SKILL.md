---
name: field-site-status-report
description: "Use when 不在现场要汇报产线/设备现场状态（链路·主机·生产栈·真值·周边），或要一次只读取证。"
version: 1.0.0
author: agent
tags: [zmax, field, status, probe, ros2, read-only]
platforms: [linux]
---

# 现场状态体检与汇报（只读）

适用：人不在现场（或现场机器只开了一个入口），用户说“汇报一下现场的状态 / 现在什么情况 / 到哪一步了”。
目标是一份**每条都带实测数字**的报告：链路通不通、主机有没有压力、生产栈起了哪些、真值是多少、周边设备在不在。

## 铁律（先读）

1. **只读**：体检期间不启停服务、不触发拍照、不下发任何动作。要动生产栈或真拍台面，报告完等用户一句话。
2. **“服务没起”与“链路断了”必须分开说**。同一句报障里两者混在一起，用户会去修错的东西。
   判据顺序固定：链路（能不能登） → 主机（能不能跑） → 栈（进程/单元/端口） → 真值（数据动不动） → 周边。
3. **一个数据源没响应，不等于那台设备坏了**。先换第二个独立证据（端口、`/storage`、另一个服务），再下结论。
4. 报告不承诺“我之后会去看”，当场量完再说话；量不到的字段写“无响应/未启动”，不推算、不填 0 冒充。

## 步骤

### 0. 先把“机器代号”落到主机，再动探针
用户嘴上说的是代号（550A/550B/550C/工控机/Orin），不是 IP。代号认错，整篇报告都在报另一台机器。
| 代号 | 是哪台 | 入口 |
|---|---|---|
| 550A | 本机：RTX 4060 + E 盘（`nvme0n1p5` label `ubuntu-e`） | 本机；产线 USB 网卡在位时 192.168.23.50 |
| 550B | VSCode 单线程 debug 机 | 不常在线 |
| 550C | Intel 端侧主节点，hostname `Nodka-PTL-Demo`，用户 `intel` | `ssh intel`（192.168.23.70）；无产线网卡时 `ssh intel-wifi`（经 Orin） |
| Orin | 192.168.23.66（`ssh orin-lan`）/ 手机热点 192.168.43.x（`ssh orin-wifi`） | 见 orin-lan-direct-access |
| AOI 工控机 | 192.168.23.23，22 口常拒 | 只走 10082/10083 |

- **问 550C 就 SSH 到 .70 现读**，不要拿本机状态代答“550C 正常”。反过来也一样：本机全栈 200 说明不了 550C。
- **服务归属也要先核**：本机（550A）没装 nginx/php/mysql，8081 站点在 550C 上 —— 本机 `systemctl is-active nginx` 报 inactive 不能报成“站点挂了”。
- 怀疑目标 DHCP 换了 IP / 网段里有陌生机：`python3 scripts/lan_sweep.py 192.168.23.0/24 22 8793 8799`（并发 ping + 端口；不要用 bash `&` 后台，前台会被拒）。

### 1. 先定入口，别假设能直连
```bash
ssh orin 'hostname; uptime -p'          # 免密别名优先；退路 ssh -p 22022 tashan@39.102.211.79
```
同一栋楼/同一个公司 WiFi **不等于**互通：办公 WiFi 常开 AP 客户端隔离，两台机器互相 ping 不通、
TCP 也不通。办公网段与产线网段并存时，一律走已验证的那条隧道，并在报告里把入口写出来。

🔴 **本机只剩 WiFi 时，`ping/ssh 192.168.23.x` 报 No route to host 是本机入口问题，不是设备坏了**。
先 `ip -br addr` / `ip route` 确认有没有 192.168.23.0/24（只有 10.163.x 就是没有），再走 Orin 跳板：
```bash
sshpass -p <intel密码> ssh -o StrictHostKeyChecking=no -J orin intel@192.168.23.70 'hostname; uptime -p'
# 长探测: sshpass -p <pw> ssh -J orin intel@192.168.23.70 'bash -s' < scripts/edge_intel_probe.sh
```
Orin 上通常只 ping 得通 intel、没有到它的 key 授权（`ssh orin 'ssh -o BatchMode=yes intel@…'` → Permission denied(publickey)），
所以用**本机 `-J orin` + sshpass**，别去 Orin 上折腾 key。密码从记忆/交接取，不猜。
本机产线 USB 网卡在位时，`~/.ssh/config` 里的 `Host intel`（192.168.23.70 / user intel / id_ed25519）实测免密直连，优先用它；`Host intel-wifi` 是同机经 Orin 跳板的入口。

🔴 **先核 `orin` 这个别名到底指向谁**：`grep -A4 '^Host orin' ~/.ssh/config` 可能显示
`HostName 39.102.211.79 / Port 22022`（公网跳板），登录后 `hostname` 回的是跳板自己。
此时“`ssh orin` 一切正常”只证明**跳板可达**，一个字都不能证明 Orin 活着 —— 报告里把入口写成别名会把结论说错。
判据 = 三条独立证据分开列：跳到跳板（`hostname`）字 / 跳板上 `ping 192.168.23.66` / 目标机自己的 `hostname` 是不是 Orin。
🔴 **跳板只认 key 时，`sshpass -p <跳板密码>` 会被拒，本机 `sshpass … -J <跳板> <目标>` 也常被拒**（第二跳的密码喂不进去）。
可用定式 = paramiko：本机 key（`key_filename=~/.ssh/id_ed25519`）连跳板 + 
`open_channel('direct-tcpip', (内网IP, 22), ('127.0.0.1', 0))` + 目标机用户名/密码，之后 sftp/exec_command 照常用。
⚠️ **后台起进程时 `exec_command('… &')` 会把通道挂住**（读输出超时，但进程已经起来）：发完就关、另开连接验，或把 stdout 全重定向到文件再读。
🔴 **读远端日志别 `tail -c N` 后直接 decode**：字节数会切在多字节字符中间 ⇒
`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa7`（看着像文件坏了，其实是读法）。
一律 `.decode('utf-8', errors='replace')`，或远端 `tr -d '\r'` 后按行取。

🔴 **人在办公室(本机只有办公 WiFi)、实验室内网整段不可达时, 走公网跳板两跳**:
```bash
ssh -p 22022 tashan@39.102.211.79 'hostname; ip -4 addr show | awk "/inet 192.168.23/{print \$2}"'
# 再以跳板为支点摸内网: 跳板→intel 通常没有免密 key ⇒ 用 paramiko 带密码建 direct-tcpip 通道
```
判据: 在跳板上 `ping -c1 192.168.23.70/.23/.160` 全通 = 实验室内网活着, **不是设备掉了**;
本机 `ip -4 addr` 只见 10.163.x = 只是本机没了产线路由(网卡/网线不在位), 两者必须分开报。
第二跳用 paramiko (`Transport((host,22))` + `open_channel('direct-tcpip',(内网IP,22),(…))`) 或先跳板上装 sshpass;
⚠️ 跳板上跑长探测/写文件的脚本用 paramiko 的 **SFTP 写**而不是 heredoc —— 远端 heredoc 里 `$V`/`$(date)` 会被本地 shell 先展开。

🔴 **“现场打不开页面/看不到画面”先看那套页服务到底跑在哪台机**: 相机流(`8791`)、工位控制(`8793`)、AR(`8797`)
如果跑在**笔记本(工位机)**上, 笔记本被带回办公室后实验室就真的没有这条链路了 —— 此时设备、控制器、AOI 全正常,
报的时候要写“入口在笔记本上、已离开现场”, 别让用户以为实验室死了。现场自带的服务(AOI 10082/10083、建图 8801/8803)照常。

还有一条独立入口：控制台 `/status/all`（8796）的 `edge` 块是**控制台自己那条隧道**（`http://127.0.0.1:18800/health`）看到的口径；报“界面显示在线/离线”时用它, 自己 ping 不通不等于界面显示离线, 两者要分开说。
第三个独立源是 ECS 的 `/orin/status`（`{"online":true,"last_seen":"HH:MM:SS"}`）—— 它只证明 Orin 侧上报活着,
不能代替机体/控制器真值; 三源口径不一致时以能登上去实测的那条为准。

### 2. 一条命令把状态抓全，不要一句一条 ssh
脚本随本技能：`scripts/orin_status_probe.sh`（主机/网络/单元/端口/USB/ROS/机械臂真值/AOI/边缘机/录制/遥测）。
```bash
scp -P 22022 ~/.hermes/skills/devops/field-site-status-report/scripts/orin_status_probe.sh tashan@39.102.211.79:/tmp/
ssh -p 22022 tashan@39.102.211.79 'bash /tmp/orin_status_probe.sh'
# 免落盘也行:  ssh orin 'bash -s' < scripts/orin_status_probe.sh
```
🔴 **长探测必须走 `bash -s` / 落盘脚本，不要塞进 ssh 引号里**：`$t`、引号、多行 `for` 在多层引号里会被吃坏；
循环里把 `printf` 和 `ros2 topic hz` 串在一行时，两者输出会互相插行，表格直接废掉 —— 一条话题一个 `printf`，命令先取到变量。

### 3. ROS：话题在列表里 ≠ 有人在发
```bash
ros2 topic info <t>     # Publisher count = 0 → 没有发布者（驱动没起），不是没数据
ros2 topic hz <t>       # 6s 窗口都测不到 rate → 静默
```
产线栈一律 `ROS_DOMAIN_ID=0`（用 23 只能看到 `/rosout`）。查话题前先 `ros2 daemon stop` 再等 2s，老 daemon 会
缓存上一个网络的图，给出“什么都看不见”的假象。

### 4. 机械臂真值：ROS 栈没起时走 SDK 直桥
Orin 上的 `zmax-arm-sdk-bridge`（`/health` `/status`，端口在 bridge 脚本里，通常是 39061）**不依赖 ROS2**，
直接用 xCoreSDK 连控制器 → 拿 `jointPos/jointVel/jointTorque/endInRef/flangeInBase/powerState/operateMode`。
- `/health` 的 `sdk:false` + `err: 网络连接错误` **在第一次 `/status` 之前是正常的**：连接是懒加载的，`/status` 进门才 `connect()`。
  先打一次 `/status`，再回看 `/health` 应该是 `sdk:true, err:null`。
- 🔴 **`conn_ts` 是连接时刻，不是采样时刻**。两次 `/status` 隔 10s 拿到同一个 `conn_ts` **不代表数据是旧的** ——
  字段是每次现读的。判“活/死”要看**会抖的量**：隔 4~5s 取两次 `jointTorque`（或 `jointVel`），有 ±0.x 变化 = 真在采样；
  关节静止时 `jointPos` 的 Δ 本就该 ≈0，那是机械臂没动，不是数据冻住。
- 报姿态用 **mm + 度**并换算出可读值；`flangeInBase` 前三数是米。同时报 `powerState / operateMode`（`PowerState.on` +
  `OperateMode.automatic` = 上电且自动模式，此时**任何动作都必须先走授权**）。
- 本机的 `zmax_data/rokae_sdk/tcp_out/*.json` 只当**日志**，不当真值：`agent_heartbeat.json` 可以 `agent:"up"` 而
  `state` 全是 `unknown`、`pose` 全 0、`ec:[{ec:263,message:"timeout"}]` —— 那是本机 SDK 会话断了（本机没有产线路由时必然如此），
  机器人本身是好的。报数前先量 `latest.json` 的 mtime/age（上千秒即陈旧），真值一律从 Orin 的 39061 现读。
- `latest.json` 有**两种状态，按字段分开判**：① `pose` 全 0 / `state` unknown / `ec:[{ec:263}]` = 本机 SDK 会话断，不可用；
  ② `ts` 与 `date +%s` **逐秒对齐（差 <1s）且位置非零** = 它就是可用真值（本机 SDK 会话活着时每秒覆盖一次）。
  判新鲜**只认 `ts`**（与系统 epoch 同源）；文件里的 `"t"` 是文本字段，常比系统时间少 8h（已知偏移）—— 拿 `t` 判
  “陈旧/将来时间戳”会直接报错结论。

### 5. 周边设备：各用各的判活口
| 设备 | 判活（只读） | 注意 |
|---|---|---|
| AOI 工控机 10082/10083 | **直打 `192.168.23.23:<port>/storage`** = 200 才算在；`/last_result` 的 `t` 换算帧龄 | 本机 `127.0.0.1:10082/10083` 多是 `ssh -L` 隧道（`ss -ltnp` 显示 `users:(("ssh",…))`），隧道在 ≠ AOI 在跑，此时 curl 回 `000`；`/last_result` 404「尚无检测结果」= 重启后内存空，不是坏；`/crop_info` 同理 |
| Intel 边缘推理 8800 (550C 端侧) | `/health` + `/pipeline/stats` **隔 10s 两次比计数** | 计数不涨=停了；看 `src` 判真帧还是静态图自测（见 5.1） |
| 机器人控制器 .23.160 | ping + SDK 桥 `/status` | ICMP 通≠可动；可动性看 SDK 会话 |
| 网关（Mac 等） | 不一定要 ping 通 | 有些主机不回 ICMP，ping 不通≠不通 |

AOI 报告里一定要写**帧龄**：“两路服务都在，但上次检测是 N 小时前”比“服务正常”有用得多；
要判 OK/NG 必须先触发一次真拍（需用户同意）。

#### AOI 两路都不在听时：恢复顺序与判据（只读阶段先定性，动服务前说清）

1. **先除“本机端口是隧道”这个假象**：`ss -ltnp | grep -E ':(10082|10083)\b'` 看到 LISTEN 但 `users:(("ssh",pid=…))`
   ⇒ 那是 `ssh -L 127.0.0.1:10082:192.168.23.23:10082` 的隧道占位，curl 回 `000`（不报错也不超时）。
   判活一律打真源 IP。
2. **分层定因**：`ping 192.168.23.23` 通（0.2~0.3ms）+ `~/zmax_data/agent_hub/beat` 在刷新 ⇒ 整机与反向通道都好，
   只是没人监听端口（**服务没起**，不是链路断）。
3. **反向通道回执本身就是根因证据**：`tools/station_cmd.py` 回执出现
   「由于已禁用计划任务"ZMAX_AOI_KeepAlive"，其无法运行」⇒ 计划任务是**被禁用**（与“脚本编码坏”是两码事，后者是
   State=Ready + `LastTaskResult=1` + 一行日志都不写）。两条路可以**同时**被禁，不只 10083。
   修：`schtasks /change /tn ZMAX_AOI_KeepAlive /enable; schtasks /run /tn ZMAX_AOI_KeepAlive`，
   **等 ≥100s** 再验（`netstat -ano | findstr LISTENING | findstr "10082 10083"` 或 `/storage`）；冷启期的 500 不算故障。
4. **恢复后必比档位**：KeepAlive 拉起走程序内 `file_defaults`（10082 = 20000us×8），**不会**读 4060 侧
   `zmax_data/aoi_v4/cam_param_persist.json`（那份只有部署器 ⑤b 回填）⇒ 档位会低于现场基准 **24000us×8**。
   报告里写清三行：回读 `/param` 的 `now.exposure_us` / 现场基准 / 差异后果；10083 同理对 `80000us×1.8`。
   想恢复只能改文件常数走 `aoi_remote_deploy.py`（停启 ~100s）—— **在线 POST 写不进**：现役 10082 的
   `POST /param?exposure=` 在采集态回 `applied.*.ok=false` + hint「相机在采集中拒绝写」；判生效只认 `applied.*.ok` + 回读 `now.exposure_us`，
  不认 HTTP 200，也不拿“实时可写”的旧结论当依据（10083 的 `POST /exposure` 仍即时生效，两路能力不同）。
5. **`station_cmd` 拼 PowerShell 别用 `+` 拼枚举**：`(Get-ScheduledTask -Name X).State + ' | ' + …` 会抛
   “无法把 `|` 转成 StateEnum”/`SubstringDisambiguationEnumParseThrewAnException` ⇒ 改 `Format-List` 逐项输出，或直接 `netstat`。

### 5.1 Intel 端侧 (550C)：满载不等于在干活
一条命令抓全（随本技能）：
```bash
sshpass -p <pw> ssh -J orin intel@192.168.23.70 'bash -s' < scripts/edge_intel_probe.sh
```
- **判活看计数在涨，不看 uptime**：`/pipeline/stats` 隔 10s 取两次，`devices.<NPU|GPU>.n` 的 Δ/秒 ≈ `fps` 才算真在推理；
  只报 “active/uptime 2h” 会被一个空转的守护进程骗过去。`duty_pct≈96` + `err:null` 才算满载健康。
- 🔴 **`src` 字段决定这个 fps 能说明什么**：`src` 是一张固定 jpg 名（也可能带 `zeros`）= 合成满载自测，
  527/1246 fps 只是**能力上限**，不代表真实相机流下的产线吞吐 —— 报告里必须写明“跑的是静态图”，否则等于虚报产能。
  真帧要看 `src` 是否随帧变化。
- **`n_req` / `last_req_age_s` 是 HTTP 业务口**：n_req 很小 + age 上千秒 = 没有业务在调它；内部 pipeline 线程不走 HTTP，
  不能因为 n_req 大就以为产线在用它，也不能因为 n_req 小就说服务死了。
- **`/health.hw.accel.gpu.in_use` 不可信**（实测 GPU 计数在涨它仍报 false）；判 GPU 在用只认 `/pipeline/stats` 的计数字段。
- 端侧那台**没有 `zmax_product.json`、没有 zmax 仓库、没有 ROS2/DDS**：只有 `zmax-edge.service`(8800) 与
  `zmax-edge-pipeline.service`。别在这台机上找档位文件或 DDS 话题；档位口径看工程机侧 `/status/all.profile`。
  同时报清 CAN/网口实况（can0~5 常有但全 down，往往只有一块产线网口 up）。

### 6. 出报告（用户要的形状）
中文、分段、每项带实测数字，不要选项菜单：
```
一、链路     入口 / 出网 / 产线网各设备延迟 / 多播走哪块网卡
二、主机     uptime / load / 内存 / 磁盘 / 温度
三、生产栈   起了什么（带速率），没起什么（带证据：端口没听、publisher=0）
四、真值     机械臂关节+法兰+power/mode，写明“静止”还是“在动”的判断依据
五、周边     AOI 两路（帧龄）、边缘机（模型/延迟/uptime）、录制是否在落、遥测是否在上报
结论        一句话：通的是什么，卡在哪一层
没动的事    明确列出（没拉生产栈 / 没触发拍照），把下一步交回用户
```
单位一律写上（ms / Hz / °C / MB / mm / °）；“静止”“在跑”“没起”这类判断必须紧跟证据，不写形容词。

## ⌛ 现场陪跑节奏: 用户在线等的时候, 一轮只交一个结果
用户在现场盯着页面/臂时会直接嫌「你反应太慢了」。链路通常不是瓶颈(实测局域网 ping 1.8ms、单次桥调用 5~10ms),
慢在**我把十几条远端命令串成了很多个来回**。定式:

- **先给实测数字再解释**: 用户看到“慢”时, 一句「链路 1.8ms / 桥 7ms / 一段运动 0.9s ⇒ 慢在我这边逐项查」远比描述排查过程有用。
- **一轮只推进一件事, 每轮落一句可验收的结论**; 不相干的取数用**一条 ssh 里多个 `echo '=== N. …'` 段**搞完, 不要一条一条发。
- **用户明确说"我点了X, 你准备Y"时, 先把他要的东西(规划/数据/闸状态)先出**, 并行/长任务(训练、扫描、下载)一律 `nohup` 后台 + 稍后报, 不阻塞对话。
- 不要用 narrate 代替动作, 也不要用动作代替结论: 每次回复要么带新证据, 要么给用户下一步可点的东西。

### 「这个动作是哪发出的」——先一句真值, 再一行证据, 到此为止

用户问“就现在, 谁发的 / 哪发出的”时, 他要的是**一个名字 + 一个时间**; 不是链路图, 不是备选入口, 也不是建议。
定式: 第一句直接点名 (进程 + pid / 文件名 / 状态文件 mtime), 第二行给证据 (哪个文件哪一字段、几点几分写的),
第三句只写“真机有没有动”这一个判别。**不要铺三层调用链、不要列三条通道、不要结尾加“要不要我…”** ——
那样会被“我问什么你回答什么”“别扯别的乱七八糟的”退回去重答。

- 先取新鲜度再答: `ls -l --time-style=+%H:%M:%S <状态文件>` + `date +%H:%M:%S` + 内容里 的 `src/mt_i/seq`,
  一眼能区分“正在跑”与“停了几小时”，比连链路真。
- 把“画面在动”和“真机在动”分开写一句: 仿真/画布产物只进显示文件 ⇒ 臂没动, 必须明说, 否则用户以为产线在跑。
- 他追问细节 (哪一行代码、怎么改) 时再展开; 追问前不给设计建议。

## 坑（都是花过时间的）

- **分段探测脚本出报告前先 `bash -n`，并数段标题齐不齐**：段标题写成裸词（如历史残片 `hr 4.USB`）时 bash 报
  `command not found` 但**继续往下跑** ⇒ 输出里凭空少了 4/5/6 段的标题，极易被误读成“那几项没数据/设备不在”。
  定式：段标题一律 `echo '=== N. 项目'`；跑完先核对输出里 `=== 1.`…`=== N.` 都在，缺段就是脚本坏了，不是现场坏了。
  ⚠️ **段标题里带括号（`hr 3.端口(${X})`）是硬语法错误**：报 `未预期的记号 "(" 附近有语法错误`，
  整个脚本当场停 —— 输出里只剩前一两段，后面全空白。看到这条错误先修脚本再重跑，
  别把"只有前两段"当成远端环境/设备不在（`bash -n <脚本>` 一条命令就能定案）。

- **远程 sudo 不要用 `echo pw | sudo -S tee f <<EOF`**：管道和 heredoc 抢同一个 stdin，密码读不到 → 三次失败后报
  “N 次错误密码尝试”，看着像密码错。正确做法：本地 `write_file` → `scp` 到 `/tmp` → `echo pw | sudo -S install -m 755 /tmp/x /usr/local/bin/x`。
- **改远端路由/单元后必须回读**：`systemctl is-enabled/is-active` + `ip route get <224.0.0.0/4 目标>` + 一次业务面实测
  （出网 200、控制器 ping、本地话题 still 有速率）。只报“服务已启动”不算完成。
- **双网卡主机的 DDS 多播会被上网口抢走**：给机器接了 WiFi 上网之后，`ip route get 239.255.0.1` 很可能指向 WiFi ——
  产线对端就 discovery 不到它。修法是把多播钉到产线网卡（`ip route replace 239.0.0.0/8 dev <产线网卡> scope link`，
  做 oneshot 单元开机执行），改完业务面三项复核一遍。
- **ICMP 通 ≠ 机器在服务；全端口拒连也 ≠ 机器死了 —— 必须按时刻分开报**：`ping` 通而 `22/8793/8081` 全拒连 = 网口/内核在、服务层一个没起（开机早期、卡在启动、重启循环）；
  若之后连 `ping` 也没了 = 整机掉线/掉电。口径写“某时刻能登上去（`uptime -p` 3 分钟）→ 现在无响应”，别把两个时刻揉成一句“一直连不上”。
- **一个探针失败先换第二种探针复核再定性**：远端 `ssh … 'bash -s' <<EOF` 回 `Connection closed by remote host` 时，立刻裸测端口（`/dev/tcp` 或 socket）+ `ping` 各 2~3 次；
  同刻端口也全关就按整机掉线处理，不要归因到脚本、引号或 heredoc。
- **本机墙钟会跳（NTP 回拨 8h）**：同一会话里 `date` 可以前后差 8 小时。时间线一律用对端的 `uptime -p` / `/proc/uptime` 相对时长表述；
  非写绝对时刻不可时，标明取自哪台主机，别拿本机 `date` 拼现场时间线。
- **`uptime` 会让人误判“刚重启”**：`up 2 days, 10 minutes` 是两秒不到的事，读成“两分钟前重启”就会去查不存在的重启原因。
- **报告里不要报“服务 active 就等于链通”**：开机自启的进程常常在网卡地址就绪前就建好了连接（DDS participant 尤其），
  active 但它永远收不到数据。判据是新起一个探针进程能不能收到。

- **`journalctl -u <unit>` 回 “No entries” ≠ 没日志**：unit 用 `StandardOutput=append:/path/x.log` 时日志不进 journal，
  要 `systemctl cat <unit>` 看输出重定向，再去 tail 那个文件；否则会得出“服务没跑过”的错误结论。
- **有状态服务别只看 `/health` 的字段自述**：`in_use`、`busy`、`online` 这类由服务自己算的标志位会和实测矛盾，
  先用两个会变的量（计数、fps、帧龄）对账，再决定信哪个。

- **端口号不等于服务身份**：报“某端口没起 / 那是授权口”之前，先 `ss -ltnp | grep ':<port> '` 取 pid，再
  `tr '\0' ' ' < /proc/<pid>/cmdline` 看真身。同一个端口号在本机和 Orin 上是两回事（本机 8793 是相机流的旁路口，
  不是动作授权口）—— 只凭记忆里的端口号下结论，会把一条安全结论说错给用户。
- **`ss` 里的 pid 会过期**：隧道/守护进程被重拉后 `/proc/<pid>/cmdline` 报 “No such file or directory”。
  重跑一次 `ss -ltnp` 拿新 pid；判隧道死没死只认 `curl 127.0.0.1:<隧道口>/health`，不看 pid 在不在。
- **相机报离线，先分“相机死”和“取流地址没走隧道”**：直接打源端 `/health`（Orin `8792` 回
  `{"n":…,"age_s":0.3}` = 相机活），再看本机取流进程 cmdline 里拉的是哪个地址 —— 写死 `192.168.23.66:8792` 时
  本机没产线路由必然 0fps，而 `127.0.0.1:18792` 这条隧道口是通的。两条证据一起给，用户才知道是改地址不是修相机。
- **ROS 侧命令拿不到结果 ≠ 机器人不可访问**：`ros2` 不在 PATH / 要进容器时别停在“ROS 看不到”，直接走 SDK 桥
  （Orin 39061）+ 服务单元（`systemctl list-units --state=running | grep -Ei 'zmax|arm|bridge'`）拿真值。

相关：入口/隧道/网卡配置细节归 `orin-lan-direct-access`；AOI 判决口径与端点归 `zmax-aoi-service`；
Intel 端侧的推理栈本身（单元、模型、能力上限）归 `intel-edge-npu-deployment`。
