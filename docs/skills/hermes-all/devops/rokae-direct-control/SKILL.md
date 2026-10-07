---
name: rokae-direct-control
description: "Use when 本机直连珞石控制器(绕开Orin)读状态或控臂。"
version: 1.0.0
author: agent
tags: [zmax, rokae, xcoresdk, direct-control, robot-arm]
platforms: [linux]
---

# 本机(4060) 直连珞石控制器 — 不经 Orin 的独立控制 (2026-09-21 实测通)

## 何时用
- 老倪问「能不能不启动 Orin 上的工程，本机从头控制机械臂」
- 要在本机读真值(关节/位姿/力矩)而不依赖 Orin 的 robot_driver
- 产线 ROS2 栈没起、但要看机械臂状态或要自己算守卫 Δ

## 关键事实（一次说清）
- 控制器 IP: **192.168.23.160**（珞石 XMS5-R800-W4G3B4C），本机 ping 0.09ms 可达
- SDK: 厂家 xCoreSDK，在 Orin 工作空间
  `.../install/robot_driver/lib/python3.10/site-packages/robot_driver/rokae/xcoresdk_python/`
  —— **同时打包 arm 与 x86_64 两套 .so**（`Release/linux/xCoreSDK_python.cpython-310-x86_64-linux-gnu.so`）
- SDK 是 **cpython-310** 扩展：本机 3.12 不能直接用 → 用 `ros:humble-ros-base`（python3.10）容器跑，
  挂 `~/zmax_data/rokae_sdk`，`--network host`
- 机型类必须匹配：XMS5 → **`xMateRobot`**；用 `xMateErProRobot` 会报
  `Robot instance type does not match with the connected robot XMS5-R800-W4G3B4C`
- API 形状：几乎每个方法都要 **`ec` 错误码 dict**（`r.jointPos({})`）；`connectToRobot(ip)` 无返回值，
  靠异常报错；`cartPosture(CoordinateType.xxx, {})` 需要坐标系参数
- 同口径：`CoordinateType.endInRef` = 工具系在参考系 = 产线 `/robot/tcp_pose` 口径（实测逐位一致）；
  `flangeInBase` 是法兰（比 TCP 少了工具偏移，差 15~23cm，别混）

## 步骤
```bash
# 1) 拷 SDK 到本机（含两套 .so，17M）
mkdir -p ~/zmax_data/rokae_sdk
ssh tashan@192.168.23.66 "cd /home/tashan/0810/<ws>/install/robot_driver/lib/python3.10/site-packages/robot_driver/rokae && tar -cf - xcoresdk_python" \
  | tar -C ~/zmax_data/rokae_sdk -xf -
# 2) 只读探针（零运动）
sudo docker run --rm --network host -v ~/zmax_data/rokae_sdk:/sdk -w /sdk ros:humble-ros-base python3 /sdk/rokae_direct_probe.py
```
仓库里有现成脚本：`tools/rokae_direct_probe.py`（读关节/速度/力矩/TCP/模式，落 JSON）。
校验口径：与 Orin 的 `/real_joint_states`、`/robot/tcp_pose` 对比，偏差应是 µrad / 逐位一致。

## 实测证据（可引用）
| 项 | 值 |
|---|---|
| 连接 | 0.09s 成功，Orin 不参与 |
| 关节 | 与 `/real_joint_states` 最大偏差 **0.96 µrad** |
| TCP | `endInRef` 与 `/robot/tcp_pose` 逐位一致 |
| 额外可读 | `jointVel`、`jointTorque`（六轴力矩）、`operateMode`、`getStateData` |

## 运动侧（接口齐备，尚未实动）
`moveAppend(...) → moveStart()`（点位）；`moveReset()`；`getRtMotionController()`（实时/伺服）；
`forceControl`；`enableCollisionDetection`；`setOperateMode`。共 91 个方法 → Orin `robot_driver` 的功能可在本机自实现。

## 坑 / 红线（务必先看）
1. **接管前必须 `moveReset`**：SDK 文档原文「RL程序和SDK运动指令切换控制，需要先运动重置」→
   产线在跑时你一发运动就是抢控制，两边同时下发会互抢。**"完全由我控制"= 产线运动栈不起或先交权**。
2. **夹爪暂时跑不到本机**：DH 夹爪 SDK `pyDHgripper` 只有 `aarch64-linux-gnu.so`，没有 x86 版
   → 要 x86 SDK，或拿 Modbus/RS485 协议自己实现。别以为"机械臂能直连 = 夹爪也能"。
3. **安全层要自兜**：直连绕开 MES/HMI/急停软件互锁 → Δ 守卫、向下限幅、势函数、急停必须挂在本机链路上。
4. 首次实动一律走现场闸门（逐条请示、低速、有人看着），并用真值核对（不看 success）。
5. 只读探针也别在产线节拍里高频连——控制器的 SDK 会话是共享资源。

## 独立实现(2026-10-07 老倪现场指令:「不要改变 orin 原来的任何服务。你可以直接调用SDK，但要独立实现」)
口径: 运动/读状态**全部由本机 SDK 会话直接完成, 与 Orin 零耦合** —— 不读不写 Orin 的文件/单元/服务,
不依赖它的 ROS/DDS/驱动栈(产线栈起没起都与这条路无关)。**不要去启 Orin 上的栈来"恢复"控制**。

仓库里的落地(单一入口, 本文件与脚本以只读方式挂进容器 ⇒ 无副本漂移):
```bash
bash tools/rokae_sdk_run.sh state                 # 只读: 电源/状态/模式/报警/位姿/关节
bash tools/rokae_sdk_run.sh pose
bash tools/rokae_sdk_run.sh move-rel --dz 1.0 --speed 5   # 相对运动(mm, 姿态不变)
bash tools/rokae_sdk_run.sh stop | reset
```
包装脚本 `tools/rokae_sdk_run.sh`(docker run --rm --network host -v SDK:/sdk -v tools/rokae:/repo:ro **-w /sdk**),
控制层 `tools/rokae/sdk_ctl.py`(守卫: 前置 on/idle/automatic → 构造回读校验 → moveReset → 越界立刻 stop → 证据 JSON → 收尾回 Idle)。

首次实动(2026-10-07 实测)固化的四条:
1. **API 顺序**: `setMotionControlMode(MotionControlMode.NrtCommandMode, ec)` → `setDefaultSpeed(mm_s, ec)` →
   `moveReset(ec)` → `moveAppend(MoveLCommand(CartesianPosition([x,y,z],[rx,ry,rz]), speed, zone), x.PyString(cmdID), ec)`
   → `moveStart(ec)`。**cmdID 必须是 `x.PyString(...)` 包装**, 传 python `str` 直接 `TypeError`(参数猜错=潜在意外运动, 动前务必先对签名)。
2. **取数用 `.trans`/`.rpy`**: `CartesianPosition.pos` 是 16 元素矩阵(常读成全 0), 位置在 `.trans`(3 元素)。
3. **工具系必须核对再动**: SDK 运动用的是 **SDK 自带 toolset**(`toolset(ec).end.trans` z≈0.2587m = 真 TCP);
   `toolsInfo` 里 18 个工程工具全是零偏移 ⇒ 别拿它当运动工具。判据: 动后**法兰与 TCP 位移一致**(不一致就是 26cm 级工具偏移事故)。
4. **容器工作目录必须可写**: SDK 要写 `logs/global_logger_<date>.log`, `-w` 挂到只读目录会 `RuntimeError: Failed opening file`。
   容器钟比宿主**慢 8h** —— 证据 JSON 里同时记 `ZMAX_HOST_TS`(宿主) 与容器时间, 别把时间戳看错。

实测证据(可引用): 端末 Z **+1.001mm** / Z **−1.000mm** @5mm/s, 逐帧真值单调到目标(0.023→1.002mm, 2.6s moving→idle),
法兰同步 ±1.000mm, 横向漂移峰值 0.007mm, **控制器报警无新增**; 证据 JSON 在 `~/zmax_data/rokae_sdk/logs/sdk_ctl_*.json`。
未通: 夹爪(DH 夹爪只有 aarch64 的 .so) ⇒ 直连只能控臂。

## 常驻动作链(2026-10-07 落地, 纯新增件; 老服务/老页面一行未改)
- 组成: 容器 `zmax-sdk-arm-agent`(`tools/rokae/sdk_agent.py`, 持一条 SDK 会话) + 主机服务
  `tools/sdk_motion_service.py`(:8798 极简点动页 + JSON API) + 授权 CLI `tools/sdk_arm_auth.sh` + 起停 `tools/start_sdk_arm.sh`
- 数据流: 页面/API → FIFO `~/zmax_data/rokae_sdk/cmd_arm.fifo`(每行一个 JSON) → 代理执行 →
  `tcp_out/agent_result.json` + 每秒心跳 `tcp_out/agent_heartbeat.json` + 流水 `logs/agent_<date>.jsonl`(逐帧真值)
- 授权铁律: **只能命令行给**(`--ttl/--uses/--by`), 页面只能看倒计时、**不能自助授权**; POST /revoke 永远允许;
  未授权 → HTTP 403。硬上限: 单步 ≤20mm · 速度 ≤60mm/s · 间隔 ≥0.5s(代理侧另有 cap_mm 复核)
- 坑1: 容器 root 造出的 FIFO 默认 0644 ⇒ 宿主写 PermissionError。代理里必须 `os.mkfifo(FIFO, 0o666)` + `os.chmod(FIFO, 0o666)`
- 坑2: FIFO 写失败必须回 JSON 错误(不能抛异常把 HTTP 响应吞掉), 并把已核销的授权**退还**(refund), 否则白扣次数
- 坑3: 后台起服务用 `setsid ... </dev/null >>log 2>&1 &`; 用工具调起停脚本时把输出**重定向到文件**
  (否则后台进程持有的管道会把调用方拖住 ⇒ 假"卡死", 表现为 exit 124)
- 实测: 页面 API 点动 Z **+1.001mm / −1.000mm** @5mm/s, 法兰同步, 最大偏差 0.001mm, 报警无新增; 未授权 403; 流水可导出
