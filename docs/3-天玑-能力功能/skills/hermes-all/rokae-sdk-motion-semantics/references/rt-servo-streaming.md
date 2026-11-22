# RT 实时模式（RtCommandMode）—— 接口面、必要前置、失败码判别

用途：`MoveAbsJ` 的 `speed` 到 200% 就是天花板（见 SKILL.md），再往上只能走 RT 实时模式，
控制器每个控制周期回调客户端要一个关节目标。本文只写**已实测到的契约与失败码**，不写"推荐流程"。
当前状态：回调 1kHz 已稳；段级 1x 与**全程低倍率（0.15x：286.05s / 279059 拍 / 终点误差 0.00°）都已跑通**；
全程 1x 仍被关节额定力矩卡住（§4c）——倍率是唯一的快慢旋钮，不是调参问题。

## 1. 接口面（`dir()` 看不到，`.pyi` 也没有 RT 类，只能运行期探）

```
x.MotionControlMode.RtCommandMode            # = 3
x.OperationState.rtControlling               # 切成功后的 op 状态
r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
rt = r.getRtMotionController()               # -> xCoreSDK_python.motioncontrolRT.PyRTmotioncontrol6
x.RtControllerMode: jointPosition=0, cartesianPosition=1, jointImpedance=2,
                    cartesianImpedance=3, torque=4
```

`PyRTmotioncontrol6` 的方法（全量）：`MoveC/MoveJ/MoveL, automaticErrorRecovery, disconnectNetwork,
reconnectNetwork, setCartesianImpedance(+DesiredTorque), setCartesianLimit, setCollisionBehaviour,
setControlLoop / setControlLoopJoi / setControlLoopCar / setControlLoopTor, setEndEffectorFrame,
setFcCoor, setFilterFrequency, setFilterLimit, setJointImpedance, setLoad,
setTorqueFilterCutOffFrequency, startLoop, startMove, stopLoop, stopMove`。

## 2. 四个必踩的接口坑（都已实测复现）

| 现象 | 根因 | 正确写法 |
|---|---|---|
| `realtime: 1338 Failed to open UDP socket.Invalid argument` | 没告诉 SDK 用哪张网卡开 UDP | `r.connectToRobot(IP, "192.168.23.50")` —— 第二参传**本机到控制器的出口 IP**（用 `socket.connect((IP,9)); getsockname()[0]` 自动取） |
| `setControlLoop(...)` 恒 `TypeError: incompatible function arguments` | 该名是**三重载**（JointPosition / CartesianPosition / Torque），pybind 无法从 Python callable 推断返回类型；传函数、传带 `__call__` 的实例都失败 | 用**类型化变体** `setControlLoopJoi(cb, 0, False)`（笛卡尔用 `Car`、力矩用 `Tor`） |
| `connectToRobot(IP, 2)` → `TypeError` | 签名只有 `(remoteIP, localIP='')` 与 `(ec)` 两种 | `connectToRobot(IP)` 或 `connectToRobot(IP, localIP)` |
| `disconnectFromRobot()` → `TypeError` | 需要 `ec` 字典 | `r.disconnectFromRobot({})` |

`setPowerState(True, ec)`（bool，不是 `PowerState` 枚举）；`setFilterFrequency(jointHz, cartHz, torqueHz, ec)`
允许 1~1000Hz、建议 10~100Hz，指令抖动大时先降它再谈别的。

## 3. 最小可跑骨架（结构，不是已验证可达录制速度的方案）

```python
r.connectToRobot(IP, LOCAL_IP)
r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
rt = r.getRtMotionController()
rt.setFilterFrequency(50.0, 50.0, 50.0, {})
rt.startMove(x.RtControllerMode.jointPosition)
rt.setControlLoopJoi(cb, 0, False)      # cb() -> x.JointPosition([6 浮动])
rt.startLoop(False)                      # 非阻塞；主线程负责监控 + 收尾
...                                      # 收尾: rt.stopLoop(); rt.stopMove(); 切回 NrtCommandMode
```

回调里**不要**读 `r.jointPos()` 每拍一次（SDK 往返会拉长周期）；要读就每 30~50 拍读一次写入日志。

## 4. 🔴 回调频率：1009.6Hz 可达（2026-11-21 实测推翻了「容器内只有 7Hz」的旧结论）

旧结论（472 拍 / 66.9s ≈ 7Hz ⇒ 判死）**是缺前置条件**，不是宿主实时性。三条缺一不可：

| 前提 | 少了的后果 | 正确顺序 |
|---|---|---|
| `r.setRtNetworkTolerance(0~100, {})` **必须在** `setMotionControlMode(RtCommandMode)` **之前** | `19-kInstabilityDetection`「Network is not stable」 | connect → tolerance → (可选)startReceiveRobotState → switch RT |
| `useStateDataInLoop=True` 之前必须 `r.startReceiveRobotState(timedelta(milliseconds=1), [x.RtSupportedFields.jointPos_m])` | `rtState: Not start receiving data` | 状态流先开，再 `setControlLoopJoi(cb, 0, True)` |
| `useStateDataInLoop=True`（**不要 False**） | False = 自由跑线程被饿 ⇒ 就是那个 7Hz | 回调由 1ms 状态包驱动 |

实测结果（`rt_ticks_1795222003.txt`）：**8105 拍 / 8.03s = 1009.6Hz，间隔 p50 1.00ms、p90 1.04ms、max 12.6ms**，
回调里干活（算插值 + `os.write` 写 tick 文件）也不掉频。⇒ 伺服流本身完全够 1kHz，别再把「频率不够」当结论。

收尾坑：这种会话里 `rt.stopLoop()` **可能永久阻塞**（两次实测挂死，主线程 `os.write` 都不再输出）。
稳妥做法：回调把 tick 直接 `os.write` 到 `/sdk/logs/*.txt`（不进 Python 缓冲），够时长后 `os._exit(0)`，
另起一次容器跑 `rt_back_nrt.py` 退 RT。**强杀后控制器会残留 `OperationState.rtControlling`**，
此时任何 NRT 指令/上电都被拒（`模式不满足`）⇒ 每个脚本进场先查 op，含 `rt` 就先 `setMotionControlMode(NrtCommandMode)`。

### 4b. 真正的拦路虎：录制时间戳抖动 ⇒ `15-kCollision`（真机实测）

按「frames[].t」原样回放（位置伺服，无前馈）时，轨迹里一段 **dt=0.047s / 6.6°（等效 141°/s）** 的抖动
会让那一拍出现位置阶跃，控制器判碰撞下电（实测第 0.85s、臂忠实跟到第 5 帧才掉）。修法三件套：

1. **均匀时间基** `t_i = i/(n-1)·dur`（丢掉抖动的原始时间戳），再按 1ms 网格插值；
2. 🔴 **只做时间缩放，绝不做平滑/限速**：早期版本用「三角核平滑 + 逐拍限速」压振动，代价是**真实偏离录制路径** ——
   关节空间最大偏离 40ms→**8.1°**、150ms→**29.9°**、150ms+40°/s→**54.2°**（离线复算；现场看到的就是
   「位置跟以前回放不一样」+ 撞工装）。振动另有独立根因（表建在错误的时基上，见 §4e）；`setFilterFrequency(20,20,20)` + 降倍率只是补充，单独用治不住。
3. 脚本必须把 `path_dev`（dense 表相对严格录制路径的最大关节偏离）打进 plan 输出，**= 0.00° 才可下发**。

`rt.setCollisionBehaviour([75,75,45,30,30,20], ec)` 是厂商文档给的 6 轴机型上限（N），
已知无遮挡的路径可以放到上限；默认阈值对伺服加速段的扭尖峰过于敏感。
⚠️ 但它**只改“外力碰撞”阈值**，改不动关节**额定传动力矩**——`30400 传动力矩超限` 那条压不住（§4c）。

⚠️ 代价不变：一旦 `kCollision`/`kActualJointVelocityLimitsViolation` 掉电，
`clearServoAlarm` + `moveReset` + RT `automaticErrorRecovery` **全返回 success 也解不开**，
`setPowerState` 仍回 `-3 The robot is in EStop state` ⇒ 只能示教器复位或控制器断电重启（实测两次）。

**闸门（省下一次掉电）**：动 RT 前先跑零运动探针（`rt_tick3.py`：切 RT、回调返回当前关节角、数 8s 拍数）。
<50Hz 才判定做不到；≥500Hz 就可以继续做流式，剩下的问题在轨迹质量而不在频率。

### 4c. 已验证的成功组合 / 两种停止码 / 会话生命周期

同一台臂、同一条 215 点轨迹（`real_traj_joints.json`，42.85s）：

| 区间 | 倍率 | 结果 |
|---|---|---|
| 帧 0-30 | 0.5x | 通过：12363 拍 / 12.23s / 1010Hz / 末误差 0.0° |
| 帧 15-42（含 #19→#20 的 31° 跳变） | 1.0x | 通过：5852 拍 / 5.81s / 末误差 0.0° |
| 帧 0-215 | 1.0x | **未通过**：跑到第 183 点（t≈36.6s）时 `30400 4 轴 23.04 Nm > 限定力矩 22.00 Nm` 柔顺停止 |

- `30401` / `13036 …关节外力超限`：位置伺服把命令阶跃当成外力 ⇒ 轨迹质量问题，用 §4b 三件套治。
- `30400 关节传动力矩超限 … 超过限定力矩 X Nm`：该轴**额定/损伤上限**（不是碰撞灵敏度），
  `setCollisionBehaviour` 改不动；超限常常只差百分之几，**降低该段速度/加速度是唯一方向**。
- **先量再降，别猜**：把臂 NRT 移到超限位姿、静止 5s 读 `39071` 桥的 `jointTorque`，得到该姿态的静态需求；
  静态就贴着上限 ⇒ 降速无用，得改路径。
- 调参顺序：`ZMAX_RT_MODE=blend`（墙钟表，见 §4e）→ `ZMAX_RT_RATE`（唯一的快慢旋钮）→ `ZMAX_RT_BUDGET`
  （拐点过渡预算，默认 0.15°）→ `ZMAX_RT_AMAX` → `ZMAX_RT_INTERVAL`(4ms) → 最后才动碰撞阈值。
  **VMAX 不当限速用**（限速=改位置=偏航）。每次只改一个，改完先 `--dry` 看 `plan_peak_deg_s` / `path_dev_deg` 再上真机。

**会话生命周期（每次都照这个走）**

1. 进场：`op` 含 `rt` ⇒ `setMotionControlMode(NrtCommandMode)`；再查 `power`，`off` 就 `arm_power.py on`。
2. 起流：`setRtNetworkTolerance` → `startReceiveRobotState(1ms,[q_m])` → 切 RT →（可选）`setCollisionBehaviour`
   → `setControlLoopJoi(cb,0,True)` → `startMove(jointPosition)` → `startLoop(False)`。
3. 回调只做 O(1)（查表+拷贝），日志每 100~200 拍 `os.write` 一次；主线程只判“够时长 / 超时 / hold 计数”。
4. 收尾：**不要**在主线程等 `stopLoop()`（实测永久阻塞）⇒ `fsync` 后 `os._exit(0)`，下一次容器 `rt_back_nrt.py` 退 RT。
5. 残局：`power=off + op=automatic + hasError=None` 但上电报 `-3 EStop` ⇒ 运动中掉链锁急停，只能示教器复位；
   复位后第一件事是只读比对关节角，定出臂停在哪一帧再谈续跑。

## 5. 汇报口径

被问"能不能真按录制速度跑"时给四段：① 录制真值（0.2 s/点、末端 862 mm/s、关节 124~141°/s）
② MoveAbsJ 阶梯（100%→1.6 s/点、200%→0.96 s/点、400%→掉电拒发）
③ RT 已实测到的：回调 1009.6Hz / 段级 1x 误差 0.0° / 全程 1x 跑到 183/215 点
④ 还差的一步是**关节额定力矩**（4 轴 22 Nm 上限），修法是降速，不是改频率/参数。
不得把"段级跑通"说成"全程已达到录制速度"，也不得隐矞每次失败会掉电锁急停这一现场代价。

**工具位置（写完别再另写一份）**：`tools/rokae/rt_tick3.py`（零运动数频率）、`tools/rokae/arm_rt_stream2.py`
（时间基重建 + 平滑 + 1kHz 流式，env `ZMAX_RT_MODE(blend|path)/RATE/I0/I1/VMAX/SMOOTH/BUDGET/AMAX/LOAD/COLLISION/INTERVAL`）、
`tools/rokae/rt_back_nrt.py`（退 RT）、`tools/rokae/estop_recover.py`（软清报警的完整尝试，失败即说明必须现场复位）。

### 顺带否定掉的一条路（省得再试）
控制器自带 `startRecordPath / stopRecordPath / saveRecordPath / replayPath(name, rate<3.0) / queryPathLists`，
看着能绕开主机实时性，但本机实测 `startRecordPath` 恒拒：`{ec:-18, message:'task_space unsupported operation'}`
（power=on / idle / automatic、moveReset 后、显式 setNrt 后都一样）。
`queryPathLists` 倒能读，返回的是控制器里既有的 `project/xxx/track0` 路径（来路不明，别随手 replay 未知路径）。

### 4d. 四条用四次停机换来的铁律（2026-11-21）

1. **RT 会话必须自己设负载**：`rt.setLoad(x.Load(mass, cog, inertia), ec)`，负载从 `r.toolsInfo(ec)` 读
   （本机 `tool1` = **1.51 kg / cog (0.016, 0.013, 0.031) m**）。不设 = 控制器按零负载算，腕关节白扛工具重量，
   这正是 4/5 轴顶到 22 Nm 的常见原因。脚本 env：`ZMAX_RT_LOAD=1.51,0.016,0.013,0.031`。
2. **`rtControlling` 残留会锁死现场**：中断 RT 后控制器停在 `OperationState.rtControlling`，此时**示教器手动/点动/
   所有 NRT 指令全被拒**（现场话术就是「我现在动不了了」）。进场先查 op，含 `rt` 就先 `setMotionControlMode(NrtCommandMode)`；
   收尾统一跑 `tools/rokae/rt_back_nrt.py`（只切模式不发运动）。
3. **控制器时钟比主机慢约 4 分 30 秒**：`queryControllerLog` 的时间戳先扣偏移再和主机日志对齐，
   否则会把「跑到 37s 那次」错配成「12s 那次」，复盘结论全错。
4. **频率/滤波/看门狗**：状态流 `1ms` 能跑但易抖，实战用 `4ms(250Hz)` + `setFilterFrequency([20,20,20])`；
   主线程用 `r.jointTorque({})` 或 `39071` 桥卡扭矩，在 **17.5 Nm（腕轴）/ 85 Nm（肩轴）** 就主动 hold 停，
   别等 22/101 Nm 碰硬墙（撞上去就要示教器复位）。

### 4e. 「一直抖」（慢放最明显）—— 指挥表建在了错误的时基上

- **症状**：路径对、无报警，臂持续高频抖/嗡；**越慢越明显**（现场会连着说两次“还是抖”）。
- **根因**：1ms 表建在**录制时间轴**（≈43k 项）上，回调却按**墙钟**推进索引。0.15x 时每墙钟毫秒只前进 0.15 项
  ⇒ 同一条位置命令被连续重复下发 6~7 拍（先“停住”再“跳一格”）。这是命令侧的台阶，跟机械/滤波器无关。
- **判据（离线 30 秒就能量，不用碰机器人）**：把表按控制周期（250Hz = 4ms）抽样，统计
  ①「与上一拍完全相同」的占比 ②步长变异系数 ③最大步长。现场那版 **40% / CV 1.05**，修好 **0% / CV 0.38**。
  40% 就意味着每秒上百次“停—跳”，这就是抖动的指纹。**报“治好了”必须给这两个数，不许只写“已优化”。**
- **修法三件（`ZMAX_RT_MODE=blend` 已实现）**：
  1. 表按**墙钟** 1ms 建（长度 = 播放时长×1000），索引与时间一一对应；
  2. 表项之间做**亚毫秒线性插值**（`f = t*1000 - idx`），慢放也不出现重复拍；
  3. 拐点用二次贝塞尔过渡，修剪长度由**显式预算**反算：`d = 2ε/(1−cos(θ/2))`
     （贝塞尔中点偏离顶点 = `d·(1−cos(θ/2))/2`），预算默认 `ZMAX_RT_BUDGET=0.15°`，
     并把实测 `path_dev_deg` 打进 plan —— **预算是承诺，不是“看情况”**。
- 🔴 **近 180° 反向（取放点的“进-退”）不能做圆弧过渡**：硬做会让表里出现 0.003° 量级的来回，1kHz 下就是“抖一下”。
  这类顶点必须**减速后反向**；速度给 0 会让积分时长爆炸（表长要 clamp 上限），给 `2°/s` 慢爬即可。
- **验收**：`path_dev_deg` ≤ 预算（实测 0.10~0.15°）、250Hz 重复拍 0%、峰值加速度与 `ZMAX_RT_AMAX` 同量级，
  再上真机。只看 `peak_v` 不够 —— 速度曲线好看不代表命令流没有台阶。

### 4f. 动真机前先离线量指挥表（不连控制器也能算）

建表函数是纯计算，可以把 SDK 桩掉单独跑：

```python
import sys, types, importlib.util
sys.modules['xcoresdk_python'] = types.ModuleType('xcoresdk_python')      # 桩掉 SDK
spec = importlib.util.spec_from_file_location('rt2', 'tools/rokae/arm_rt_stream2.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
dense, peak_v, peak_a, dur = m.build_play_blend(js, ts, rate=0.15, budget_deg=0.15,
                                                smooth_ms=120, amax_deg=300, vmax=100)
```

- 量四个数就够判：`path_dev`、250Hz 重复拍占比、步长 CV、最大步长。
- 🔴 **偏离必须按“点到折线的最短距离”算**，不能用“同下标相减”：弧长重定时后同一下标对应路径上不同点，
  同下标比会把时间相位差误报成 13~18° 的偏离（自己吓自己也掩盖真实偏离）。
- 价值：调参一轮离线 5 分钟 vs 上机一次 5 分钟 + 可能一次示教器复位。**先离线，再上机。**
- ⚠️ 桩 SDK 时注意模块级 import 与常量（URDF 路径、`VMAX` 等）；只截函数体搬到别处跑的写法会 `NameError`
  被宽 `except` 吞成“恒 0”（同一族坑见 `zmax-real-traj-215-autorun` 的相图采样定式）。

### 4g. “跑了但不走”：32006 把整条流拒掉 ⇒ 先查首拍是否贴着实测位姿

症状三件同时成立，就不要再怀疑表/频率/滤波：

```
· 回调 987~1000Hz（ticks/elapsed 正常）
· 脚本自报 err_deg ≈ 0.0（命令确实走到了末点）
· 臂关节角几乎没变；controller log 里成对出现 `32006 即将发给伺服的位置指令发生大的跳变，位置指令被拒绝`
```

根因：进场归位（`align_to`）容差 1.5°，臂停在离表首 1.0~1.4° 的地方也算“已到位”，RT 位置模式要求
**第一拍命令就落在实测位姿上**，差这一点点就被当成跳变 ⇒ 之后每一拍都被拒 ⇒ 状态流随即变慢、脚本只能等超时。

- 修法：起流前强制精确归位 —— 容差放到 `ZMAX_RT_ALIGN_TOL=0.02`（`TOL_DEG` 已改成 env 可控）。
- 验收：4 帧小段先把臂挪到 `frames[3]`，实测到位误差 **0.01°**；之后再跑长段。
- 🔴 **判据只认“关节角真的变了”**：脚本的 `err_deg` 是命令与目标的差，命令被拒时它照样报 0.00°。
  每次都拿 `39071` 桥（或 SDK 直读）与 `frames[k]` 逐轴比一次再宣布成功。
- 顺手一个读数陷阱：日志里 `vmax_seen_deg_s` 实际是 **rad/s**（代码里乘的是 1000 未换 °），`0.1` ≈ 5.7°/s；
  拿它当 °/s 读会误判“臂没动/表没推进”。

### 4h. 实测关节速度频谱（量“还在抖”，不猜）

抖动分两种，必须先分开：**命令在抖**（表/插值问题）与**臂自己在抖**（伺服/机械）。判据是同一时间窗内
“下发指令”和“实测位置微分”两条谱。

采样通道（只有这一条能用）：

```python
vec = x.PyTypeVectorDouble([0.0] * 6)          # 不是 list、不能下标、不能迭代
r.getStateData(x.RtSupportedFields.jointPos_m, vec, 6)   # 枚举值 = 'q_m'；传字符串 'jointPos_m' 恒回 -1
vals = vec.content()                            # 只能这样取值
```

- 必须在**回调里**读（每 10 拍一次 ≈100Hz，够看 50Hz 以内），回调只多做一次缓冲读，不掉频。
- 🔴 **主线程读都不行**：`r.jointPos({})` 每 5ms 一次（RCI 锁）⇒ 回调掉到 **4.8Hz**；
  主线程 `time.sleep(0.002)` 轮询（500 次/秒抢 GIL）⇒ 回调掉到 **8Hz**。主线程一次长睡 50~100ms 最稳。
- 分析：`./gui-venv311/bin/python tools/rokae/joint_spectrum.py <meas_*.jsonl>` —— 每关节 Welch 峰值频率、
  RMS、以及 0.5–5 / 5–20 / 20–50 / 50–100 / 100–200 Hz 五段能量，并给出“指令 vs 实测”的重复拍占比对照。
- 读法：峰值落在 100Hz 且指令侧同样高 = 命令台阶（回 §4e）；只有实测侧高 = 伺服/机械（低速粘滑、共振），
  换 `setFilterFrequency`、改倍率再复测，别继续改表。
- 采样文件由 `ZMAX_RT_MEAS=1` 落盘（`/sdk/logs/meas_<ts>.jsonl`，字段 `t/q/c`）。
