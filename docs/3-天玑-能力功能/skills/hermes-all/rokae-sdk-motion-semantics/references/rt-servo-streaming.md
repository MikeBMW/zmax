# RT 实时模式（RtCommandMode）—— 接口面、必要前置、失败码判别

用途：`MoveAbsJ` 的 `speed` 到 200% 就是天花板（见 SKILL.md），再往上只能走 RT 实时模式，
控制器每个控制周期回调客户端要一个关节目标。本文只写**已实测到的契约与失败码**，不写"推荐流程"，
因为容器内实测没能跑到录制速度（原因见 §4）。

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

## 4. 🔴 容器内实测的上限：回调只有 ~7Hz，且每次失败都掉电锁急停

- 实拍：472 拍 / 66.9s ⇒ **~7Hz**（预期 100~1000Hz）。容器无 PREEMPT_RT、无实时优先级，
  `priority` 参数只在实时 OS 下生效。
- 按**墙上时间索引**取目标（想"按录制时间轴"）：7Hz 下单拍 delta 过大 ⇒
  `kActualJointVelocityLimitsViolation`（"Joint commands exceed joint angle/velocity limit, or trajectory is discontinuity"）。
- 改**弧长参数积分**（`s_dot = min(rate·v_rec(s), VMAX)`，再钳单拍 ≤1°）后不再报速度越限，
  但第 17 拍触发 `kCollision`（"Detected collision or EStop, motor off"）——臂实际只动了约 2°。
- **每一次 RT 失败都让控制器 `PowerState.off`**，且 `clearServoAlarm()` + `moveReset()` 返回 ok
  之后 `setPowerState(True)` 仍回 `-3 The robot is in EStop state, please recover`
  ⇒ 只能示教器/控制柜复位或控制器断电重启。**软件侧清不掉。**
- 另有：仅切进 RT 再切回 Nrt，也可能留下 `power=off`；任何 RT 试验结束后都要**重读 power 再谈下发**。

**闸门（省下一次掉电）**：动 RT 之前先做零运动探针——切 RT、`startMove(jointPosition)`、
回调只返回当前关节角，数 5s 的拍数。**<50Hz 就没有继续调参的价值**（不是参数问题，是宿主实时性），
直接结论"这台机/这个容器做不了按录制速度的 RT 流式"，别再拿 `VMAX`/`rate`/`zone` 反复试。

## 5. 汇报口径

被问"能不能真按录制速度跑"时给三段：① 录制真值（0.2 s/点、末端 862 mm/s、关节 124~141°/s）
② MoveAbsJ 阶梯（100%→1.6 s/点、200%→0.96 s/点、400%→掉电拒发） ③ RT 的实测上限与失败码。
不要承诺"改 RT 就能达到录制速度"，也不要掩饰每次失败会掉电这一现场代价。
