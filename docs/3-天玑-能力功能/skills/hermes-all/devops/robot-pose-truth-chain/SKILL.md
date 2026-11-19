---
name: robot-pose-truth-chain
description: "Use when 机器人位姿真值读不到或疑似陈旧(执行器报「位姿缓存未就绪」) — 真值来源分级、链路判别、跨跳板兜底。"
version: 1.0.0
author: hermes-agent
license: proprietary
tags: [robot, telemetry, pose, ros2, ssh-tunnel, diagnosis]
platforms: [linux]
metadata:
  hermes:
    tags: [robot, telemetry, pose, ros2, ssh-tunnel, diagnosis]
    related_skills: [real-arm-motion-control, rokae-direct-control, orin-lan-direct-access]
---

# 机器人位姿真值链路：读不到 / 疑似陈旧时怎么定位与兜底

## When to Use
- 常驻运动执行器对**所有**技能一律回 `拒绝: 位姿读不到(直读失败且常驻缓存过期)` / `受理: 位姿缓存未就绪`
- 页面/文件里的 TCP 位姿与现场明显不符，或 `latest.json` 的文件龄是几小时/几天
- 要做任何按 Δ 计算的动作之前（**先证位姿是新鲜的，再谈动**）

## 真值来源分级（三条会同时死，症状一模一样）
| 级 | 来源 | 依赖 | 失效时表现 |
|---|---|---|---|
| ① | SDK 直采文件 `tcp_out/latest.json` | 本机能到控制器的 xCore 端口 | 文件龄停住；采样容器 `Restarting`，日志 `RuntimeError: network: network connection` |
| ② | 本机 docker tap 容器（`--network host`）订阅 `/robot/tcp_pose` | 本机 DDS 发现 + 到产线网段的路由 | `docker exec` 报容器不在 / `Publisher count: 0` / 全 0 |
| ③ | 状态流 `ssh <机器人主机>` + `ros2 topic echo --once` | 到主机 IP 的 22 端口 | 日志反复 `No route to host`，5s 重连一次 |
| ④ | **兜底：走跳板机的宿主 ROS CLI**（见下） | 只需一条能 ssh 到机器人主机的跳板 | 无（这条就是为了前三条全灭时用） |

## 30 秒判别（全只读，不下发任何指令）
```bash
ip -4 route | grep <产线网段>          # 空 = 本机根本没有该网段路由
ip -br link; ip -4 addr show <enx*>   # 有载波 LOWER_UP 却没地址 = 网线通、网段不对
for h in <主机> <控制器>; do ping -c1 -W2 $h; done   # 本机全灭不说明别人不行
ssh <跳板别名> 'ping -c2 <控制器>'                    # 跳板侧 alive ⇒ 死的是本机这一段
stat -c %y <真值文件>                 # 文件龄 >10s 就当没有位姿（与执行器同口径）
```
判读铁律：**跳板 alive 而本机全灭 ⇒ 问题在本机网口/布线/交换机口，不是控制器、不是执行器代码。**
给网口配上同网段地址后仍 `No route to host`（ARP 无回应）⇒ 那根线**根本不在产线网段**，
别再反复改 IP：现场换口，或直接用下面的兜底通道。

## 🔴 ROS 话题上可能挂着第二个发布者：`echo --once` 会取到错的
同一个 `/robot/tcp_pose` 上可以同时有**真机驱动(≈50Hz) 和一个残留节点**（仿真壳、旧进程、别的机器的桥）。
`ros2 topic echo --once` 取的是“谁先发”，于是同一条命令能给出相差近 200mm 的两套位姿，**而且各自都自洽**
（它读到的关节角与它读到的 TCP 互相对得上）—— 只检查“有没有数据 / 频率多少”永远发现不了。

- `ros2 topic hz` 有稳定 ~50Hz 只说明**至少有一个**活发布者，不说明你读到的是它。
- 真值以**控制器直出**为准：SDK 桥 `/status` 的 `jointPos` + `endInRef`（与页面同一个源）；ROS 话题只作兜底。
  顺序：`SDK 直采文件(新鲜时) → 控制器 SDK 桥 → 跳板 ROS 话题 → 本地文件`。
- 拿到关节后**必须 FK 复算并与 TCP 比对**，差 >15mm 直接拒检 —— 这是唯一能挡住“关节读的是 A、TCP 读的是 B”的门。
  🔴 **目标 link 必须锁 `tool1`**：同一组关节角，`tools/fk_check_tool_frame.py` 的 `fk(URDF, link, q)`
  算 `tool1` 与上报 `endInRef` 差 **2.7mm / 3.36°**(实测 2026-10-26, 位置 dx1.4 dy-0.9 dz2.1)；
  算 `tool0` 差 **260.2mm / 137°**、算 `link6` 差 **720.5mm** —— 拿错 link 会得出“位姿全错”的假结论。
  口径: 这 2.7mm 是 **URDF 模型 vs 控制器** 的差，控制器上报值仍是真值；但凡是 MoveIt/URDF 算出来的
  目标点落到真机就带这个量级偏差 ⇒ 精密插入(光模块类)不能靠它收口，要靠视觉伺服/力控。

## “位姿准不准”的四件取证(用户问“现在的位姿准确么”时照这个答，不要只说新鲜)
1. **新鲜度**: `stat -c %y latest.json` 的文件龄(<1s 才算在刷)；容器内 `t` 字段比宿主早 8h 是 NTP 回拨的已知现象，只看 mtime。
2. **双路同源**: Orin SDK 桥 `/status` 的 `endInRef` 与本机 `latest.json` 逐位比，实测差 <0.001mm。
3. **静止稳定**: 2s 内 6 次采样求极差，实测 x/y/z 极差 0.0000mm(臂真停着，不是抖出来的伪静止)。
4. **独立算路对账**: 关节角 → URDF FK → 与上报比(见上面 tool1 口径)。四条齐了才能说“准”。
- SDK 桥拿不到时，用 `ssh <跳板别名> 'curl -s http://127.0.0.1:<桥端口>/status'` 直取，别依赖本机那条隧道（隧道会半开、返回空串）。

## 兜底通道：跳板机宿主 ROS CLI（不需要本机 DDS / 不需要 docker）
```bash
ssh <跳板别名> 'bash -lc "source /opt/ros/humble/setup.bash; \
  for ws in <工作空间通配>/install/setup.bash; do [ -f \"$ws\" ] && source \"$ws\" && break; done; \
  export ROS_DOMAIN_ID=0; timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"'
```
- 实测 3~5s 返回 7 个数（pos+quat），与 tap 同口径。
- **宿主 `ros2` 不需要 docker 权限，`docker exec` 需要 sudo** ⇒ 同等效果优先用宿主 CLI，少一层权限少一条依赖。
- 只在 `use_sim_time=false`、`ROS_DOMAIN_ID` 与产线一致时有效；不确定就先 `ros2 topic list` 确认能看到话题。

## 落地到常驻执行器的两个固定改法
1. **主机地址自动选路**：启动时探 `tcp/<robot_host>:22`（2s 超时），通就用直连地址，不通自动退 **ssh 别名**
   （别名里配 ProxyJump 走跳板）。写死在代码里的 IP 一旦网段漂走，整套运动链就全线哑掉，而日志只有一行 `No route to host`。
2. **`_pose_direct()` 增加第四条通道**：SDK 文件 → 跳板宿主 ROS 直读 → 本机 tap。顺序按“依赖越少越靠前”排，
   每条都带自己的超时并 `try/except`，失败只记一行日志、不抛。

## 验收（缺一条就会把“没修”当“修好了”）
- 干跑任意相对技能（`arm=0`），受理行必须是 **`位姿来源 direct`** —— 不是 `cache`、更不是 `位姿缓存未就绪`。
- 改完真值优先级后，**只认 `main()` 的输出**：不少工具在**模块导入时**还会跑一段旧路径的自检并打印位姿，
  `head -7` 抓到的往往就是那段旧值 ⇒ 会误判"改了没用"。要 grep 关键判定行(一致性/PASS/帧龄)或直接调 `read_joints()`。
- 同一时刻**只该有一个真值源在生效**：预检报的 TCP 若和页面 `/api/tcp` 差 >15mm，先怀疑两边读的不是同一个发布者，
  不要拿这个差去质疑机械臂位置。
- 同时报出**目标位姿数值**与**文件龄**，两者都要能对上现场。
- 只有 `cache` 就说明直读仍坏（缓存可能是几小时前的旧值，且守卫会拿它算 Δ）。

## 位姿中继：让 “活着的桥” 嗂回 “死掉的真源文件” (症状链最长的一条)

采样器容器 CrashLoop(本机无产线路由) 时, `tcp_out/latest.json` 会冻住。冻住的代价不只是“读不到”, 而是**三个下游同时静默坏掉**:

| 下游 | 表现 |
|---|---|
| 规划/执行入口 | 拒跑: `规划已 N 分钟, 位姿早变了 ⇒ 请重新规划`(页面点按钮无反应, 不弹原因) |
| 常驻执行器 | 每条命令 `拒绝: 位姿读不到(直读失败且常驻缓存过期)` ⇒ 看上去“点了不动” |
| 轨迹执行器 | 等到位观测全失效(trace/real 空), 最后报 timeout |

修法 = **中继**(不是去修采样器): 把还能读到的真值源(控制器 SDK 桥 `/status` 的 `endInRef`)按 2Hz 搬回那个文件, 字段与采样器**逐字一致**, 只把 `src` 标成中继好追溯。
```
fetch /status → [x,y,z,rx,ry,rz] → rpy→quat(ZYX) → 写 tmp → os.replace() 原子落盘
桥断了就不写    ← 宁可让文件变旧(下游按 stale 自己拒绝), 绝不用旧值刷 ts 冒充新鲜
```
验收: `age < 10s` 且数值与 `/status` 逐位相同(实测 age=0.5s, quat 与中继前完全一致)。

- 🔴 **root 跑的 systemd 里 `os.path.expanduser("~/...")` = `/root/...`**: 中继会“成功写入”到 `/root/zmax/...`,
  日志照打“已中继 N 次”, 而 `/home/<user>/...` 那份一动不动 —— 极容易当“中继没生效”去改代码。
  一律写死绝对路径或从 env 传 (`ZMAX_POSE_OUT`), 不要指望 `~`。
- 🔴 中继不能只在文件不存在时写、也不能带自己的小缓存; 真值的时间戳必须来自**本次**读到的那一帧。
- 判据顺序固定: 先 `stat` 文件龄 + `drift` 与桥比对, 再看下游日志 —— 倒着查会把中继问题当执行器问题。

## 从 ROS 话题全速采真值 (48Hz 只读记录器)

要「学动作」先要**同频度、同字段**的真值样本。HTTP 桥那份 `/pose` 是快照，轮询到 2Hz 就丢 96% 信号
(实测单拍位移 243mm ⇒ 严重混叠)。直订 ROS 才能拿到 48Hz 轨迹。

1. **先逐话题量频率，别按名字假设**: `ros2 topic hz <话题>` 一条一条量。实测同一台机上
   `/joint_states` **静默**(仿真壳留下的空话题)、真关节在 `/robot/joint_states`(45Hz) 与 `/real_joint_states`(61Hz)，
   `/gripper_pos` 12Hz，`/robot/tcp_pose` 47.9Hz。订到空话题时不会报错，只会字段永远 `None`。
2. **解释器与 env**: `rclpy` 在系统 `python3`(ROS 发行版)；systemd unit 的 `ExecStart` 必须
   `/bin/bash -lc 'source /opt/ros/<distro>/setup.bash && exec python3 …'`，否则 import 失败；
   且 `ROS_DOMAIN_ID` 要显式给(与产线一致)。**不要**用装 torch 的那个 venv( numpy 冲突)。
3. **QoS 用 BEST_EFFORT 订阅**(`qos_profile_sensor_data`): 发布端是传感器 QoS 时，RELIABLE 订阅收不到任何消息。
4. **采集器必须自证频率**: 每 5s 写一份 `status.json` = 每话题**实测 Hz** + 行数 + 图-位姿 skew，
   判据 `pose≥40Hz / joints≥40Hz / frames>0 / skew<25ms`。
   🔴 **没有 `status.json` 就是主循环没跑到**，哪怕 `systemctl is-active` 是 active、帧与计划文件也在长
   (实测回调里一个计数器 key 写错 ⇒ KeyError 打穿主线程、systemd 反复重启 `NRestarts=16`，
   而其余子线程照写盘 ⇒ 看上去“在跑”)。先 `systemctl show -p NRestarts` + 前台跑 12s 看 traceback，
   再看数据。
5. **字段集决定能不能学策略**: 只有末端位姿 = 只能做记录/回放；要训动作必须 pose + 全关节位置/速度 + 夹爪 + 当时下发的计划段。
   落盘按集分片(5min)、图按运动门控(动 5Hz / 静 0.5Hz，实测 2Hz 全量写一天≈30GB)、超量删最老集。
6. **图-位姿对齐用本机墙钟捕图时刻** + 单独记 ROS header 漂移(实测控制器时钟快 51s)；skew 正常 1~13ms。

## action 出口怎么用这份真值（对齐契约，模型输出也要同口径）

真值不只是给“看一眼新鲜”——**动作出口必须每拍重新锚在真值上**。标准写法（`action_bus.from_ss`）：

- 位置 = **真值** + `u[:3]*dt`（mm）。禁止把上一拍 action 自己积分累加：那会与真机越跑越偏，而日志里的目标值看着完全正常。
- 姿态 = 真值的 `a/b/c` + 四元数 `qx/qy/qz/qw` 原样带过去（`u` 只动位置）。
- 夹爪 = `u[3]` 通道（`>=0.5` 合 / `<0.5` 开）。丢掉第 4 维 ⇒ action 里夹爪永远只是“保持实测”，下游拿不到开合意图，模型也学不到。
- 每拍带**对齐证据块**（页面/终端/报告直接看这几个数，不靠嘴说对齐了）：
  `align{pose_truth, u_mm, step_mm, max_step_mm, truth_age_s, truth_fresh, step_ok}`；并附 `needs_ik`/`joints_src`。
- 🔴 **真值缺 ⇒ 不出目标位姿**（返回空、报“宁缺不编”）。拿实测位姿冒充目标会把“没读到位姿”伪装成“目标就是不动”，是最难查的一种假数据。
- 兜底闸：单拍位移上限（实测取 25mm）+ 真值帧龄 ≤1.0s，超了置 `step_ok/truth_fresh=false` 而不是静默裁掉。

自证（不靠肉眼，不靠“看着对”）：
```bash
python3 tools/action_align_probe.py --selftest   # 拿真机录制位姿当时流逐拍核
python3 tools/action_align_probe.py --live 30    # 读 ss_live/action.json 看线上
```
判据：pose 与（真值+u·dt）最大偏差 ≤0.05mm（实测 0.005mm 取整）、夹爪跟随 `u[3]` 0 次错、单拍超限 0 次、
`truth_fresh` 比例 ≥95%。只改输出、没跑这两个判据，就不算对齐。

模型侧同口径（改 action 时必须一并交代）：`u` 的单位是 **m/s × dt**、第 4 维是夹爪、坐标系 base；
训练归一化必须与这条契约同源，否则“action 对了、模型输出还是错帧错尺度”。

## “全部重启了, 你看到了么” → 先判重启**范围**, 再报状态

用户说重启不等于**工控机**重启。三处证据并列, 一句话说清是谁重启了:
```bash
uptime -s                                                      # 主机开机时刻
for u in <关键unit>; do systemctl show -p ActiveEnterTimestamp --value $u; done   # 各服务启动时刻
python3 -c "import json,time;d=json.load(open('<latest.json>'));print(time.time()-float(d['ts']), d.get('power'), d.get('mode'))"
```
- 判读: 主机 uptime 没变 + 关键 unit 启动时刻没变 + 真值断流几十秒 + 控制器 `power=off`
  ⇒ **是控制器/机器人那头重启**, 本机链路一根没动。反之 uptime 刚起 + unit 全部新时间戳 ⇒ 整机重启。
- 汇报顺序: 重启范围(谁重启了) → 真值新鲜度 + 当前位姿 → 控制器安全状态(power/mode/op) → 我的服务状态。
  别把“我看到重启了”写成笼统一句, 用户问的就是“你分得清是谁重启了吗”。
- 真值断流期不许把冻住的位姿当实时: 采集端 `age_s>5s` 就跳过并写原因; 恢复后**重锚**(记 gap 点,
  不计跳变也不计弧长) —— 重启期间臂可能被搬走, 那是断流不是跳变。
- 重启后臂停在完全不同的数值上不是故障(实测 767/228/190 → 663/-29/292mm); 报“当前 TCP + 帧龄 + 双源一致”即可。
- 上电后 `power=off` 时手动能动能读, 但要我**下发**必须回到 `power=on + automatic + idle`。

## 坑
- 🔴 **单位: `tcp_out/latest.json` 的 `x/y/z` 是「米」(SDK 口径), 而段表/执行器要的是「mm」** ——
  拿真值直接做几何规划不乘 1000, 起点就变成 `0.66, -0.03, 0.29`“mm”, 规划器以为臂在原点附近,
  算出的抬升/倒落段全是废的(实测抬到 50mm = 起点上方 49.3mm, 而真实高度是 292mm)。
  自己用读值前先 `print` 一次起点量级对账 (正常应是几百 mm); 产出段表时一路用 mm, 单位换在**读入那一处**收口。
- 🔴 **起点新鲜度不达标就不出段表**, 不要“拿旧位姿照规划”: `age > 2s` 就返回 `tcp_stale` 并拒出,
  比产出一张基于陈旧位姿的段表诚实得多(后者到下发那一步才被闸门拦, 用户只看到“点了不动”)。
- 🔴 **绕不开的旧值陷阱**: 真值文件是“宿主 mtime 判断新鲜”的, 但其他进程/中继可能刚写过 ts 而值没变
  ⇒ 判新鲜要看**数值是否在变**, 而不是只看 `age_s`。定式三步（每次报位姿前都跑，很便宜）:
  ① 连采 3 次 `latest.json`：`ts` 每拍前进、而 `x/y/z` 三次**一位不差** ⇒ 假新鲜（保活/中继拿旧值重写 ts）；
  ② 同时 `curl -s 127.0.0.1:<桥端口>/status`，`endInRef` 与文件值**逐位对不上** ⇒ 文件不是这份真值写的；
  ③ 回头查承载链路 `systemctl show <隧道unit> -p NRestarts` —— 文件在刷新**完全不能证明**隧道活着（保活模式下它每秒都在写）。
  三个数字并列报给用户（ts 序列/文件值/桥值），比“位姿在线”四个字有用得多。
- 🔴 **下电会让位姿“静默冻结”：`/status` 里的 `powerState` 先于数值看**。控制器 `powerState=off`（或未使能）时，SDK 桥仍按节拍吐数据、采样 `ts` 每秒前进、`age_s` 显示 0.0~0.2s，但 `jointPos` / `endInRef` 一位不变、`jointVel` 全 0、`jointTorque` 照旧有值（靠重力/残压读数）。此时无论你怎么挪臂、挪完多久，真值都不会变 —— 先报 `powerState` 再判断“链路坏了”，否则会把“没上电”误诊成中继/隧道故障，去改一堆没坏的代码。
  ⇒ 报位姿时必须同时给：`powerState` + `jointVel` 是否非零 + 连采两次 `jointPos` 是否变。三者一起说，用户才知道该去上电还是等软件修。
- 🔴 **绝不用文件龄 >10s 的位姿算 Δ**：陈旧值与真值可以差 450mm 量级，按它算出的目标会把臂开错地方。
- 🔴 **页面显示“有位姿”不等于位姿新鲜**：页面读的就是同一个文件，文件冻住时页面照旧画点。
- 🔴 **容器重启循环本身就是证据**：`docker ps` 里 `Restarting (N)` + 日志尾 `network: network connection`
  ⇒ 不要再去查代码/SDK 版本，先按上面的链路判别走。
- 🔴 **`age_s=0.0` 不代表数据新**：若这个龄是按“请求时间”打的，桥吐的是冻结快照也照样显示 0.0s。
  验真是**连采两次看数值变不变** + 看源侧 `conn_ts`，不是看页面那个龄。
- 🔴 **隧道 unit `active` 不代表转发活着**：反向隧道（`ssh -R`）在对端重启后会半开 —— 进程在、
  `systemctl is-active` 还是 active、日志整段静默，但端口不再可用。两头都要治：
  对端装 watchdog（连续 N 次探不到端口才 restart，单次失败会误杀），本机把隧道 unit 的目标写成 **Host 别名**，
  这样直连/跳板切换只改 ssh config 一处。
  自动切换的判据要**三条同时成立**才切：有线网卡 `carrier=1` + 该网卡上有产线网段地址 + `ping <机器人主机>` 真通；
  巡检 30s 一次就够，宁可不切也不要把好链路切坏。
- 🔴 **改 ssh config 里那个 `Host <别名>` 时, 匹配要带换行**(找 `'\nHost <别名>\n'`, 不要用子串 `'Host <别名>'`):
  文件里常有一行注释提到同一个别名, 子串匹配会命中注释 ⇒ 判定"已存在"、实际一个字节都没追加,
  然后你继续重启隧道/查 unit, 却不知道配置文件根本没变。改完 `read_file` 回读那一段再动服务。
- 🔴 **“页面上的手臂不跟着真机动”先分类再查链路**：8797 的 AR/3D 页在 `ar_scene=true`（画布「🤖 机器人执行器」开关打开）时按设计 `VR.real=false` —— **真机臂被隐藏**，画的是段表仿真/幽灵臂，按钮会写着「🦾 右臂_真机(已隐藏)」。判据顺序：
  ① `curl -s 127.0.0.1:8797/api/ar/mode` 看 `ar_scene` 与 `src`；② 页面上的真机臂按钮文案；③ 才轮到 `/api/tcp` 的 `joints` 连采是否在变。
  前两条命中就是**显示层**（点「右臂_真机」或把状态空间拨关即可，真机臂的正运动学每帧用 `TCP.joints` 现算，显示出来就会跟），别去查位姿中继。
  同理：页面上「🎥 8802 同视角」那块是 MuJoCo 渲染帧，永远不跟真机，别拿它当“真机画面”。
- 🔴 **双源对账要拿“同刻读数”比, 不要拿时间戳比**: 桥 `/status` 里的 `conn_ts` 是**建连接那一瞬**的 epoch(可能早几个钟头), 不是本帧采样时刻 ⇒ 拿它和 `latest.json` 的 `ts` 一比就会得出“两边差 N 十分钟”的假结论。
  正确比法: 文件 `x/y/z`(单位米, ×1000 转 mm)对 `endInRef` 前三位, 文件 `joint[:6]` 对 `jointPos` 逐位 —— 实测一位不差(663.03/-29.35/291.57mm ↔ 0.66/-0.03/0.29)。两个数字一列出来就能答“准”。
- 🔴 **重启/上电后位姿数值变了不是故障**: 臂可能被人挪过、也可能上电位置本身就不一样(实测同一台机重启前后 767/228/190 → 663/-29/292 mm)。
  报告口径是「当前 TCP x/y/z + 帧龄 + 双源一致」, 顺手问一句“现场是不是挪过”, **不要当成漂移/标定坏了去重标**。
- 🔴 **别为了恢复链路去重启产线机器人主机上的生产栈**：跳板宿主只用来“读”，不启停任何服务。
