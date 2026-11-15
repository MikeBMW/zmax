---
name: rokae-sdk-motion-semantics
description: Use when 用 xCoreSDK 下发珞石臂运动或排查节拍异常。
version: 1.0.0
author: Hermes Agent
license: proprietary
tags: [rokae, xcoresdk, robot-arm, motion, estop]
platforms: [linux]
metadata:
  hermes:
    tags: [rokae, xcoresdk, robot-arm, motion, estop]
    related_skills: [rokae-direct-control, real-arm-motion-control]
---

# xCoreSDK 运动指令契约 —— 命令对象、moveAppend/moveStart、逐点节拍下限

## When to Use
- 要用 SDK 直接下发珞石臂运动（不经 ROS 层），特别是**沿一串关节角逐点走**或想「连续跑不停顿」
- `moveStart` 返回异常码（尤其 `-60611`），或调用后控制器 `PowerState.estop` / `off`
- 逐点回放比录制慢一个数量级，想判断「还能不能优化」
- 脚本在容器里读不到自己的调试开关，量级悄悄放大

配套：连接/读状态/授权链见 `rokae-direct-control`；产线闸门、安全区、事故台账见 `real-arm-motion-control`。

## 命令对象语义（按位置猜参数会 TypeError，读 `.pyi`）

权威来源是 `xCoreSDK_python/Release/linux/xCoreSDK_python/__init__.pyi`（含逐接口中文文档），
**不要用 `dir()` + 关键字筛**——会漏（例：`calibrateForceSensor` 不含 torque/collision 关键字）。

| 对象 | 参数 | 语义 |
|---|---|---|
| `MoveLCommand(cart, speed, zone)` | `CartesianPosition` | 笛卡尔直线 |
| `MoveJCommand(cart, speed, zone)` | `CartesianPosition` | **轴插补到笛卡尔目标**，不是关节目标 |
| `MoveAbsJCommand(jointPos, speed, zone)` | `JointPosition` | 关节空间插值（绕奇异/贴限位的救命通道） |
| `setPowerState(on, ec)` | `on: bool` | 传 `x.PowerState.on` 枚举会 `TypeError` |

- **第三参 `zone` 是转弯区，不是速度**（代码里常见的 `-1` = 默认转弯区）。
- `moveAppend` 第一个参数是 **Sequence** ⇒ 传 `[cmd]`，不要传裸 cmd。
- `cmdID` 必须 `x.PyString(...)` 包装，传 python `str` 直接 `TypeError`。
- 关节目标只能用 `MoveAbsJCommand`：J3 贴近限位时任何笛卡尔下降都被拒，用它把关节拧开即可恢复。

## 🔴🔴 「多次 moveAppend + 只 moveStart 一次」= 控制器 -60611 + 急停 + 真碰撞

想连续跑多点（不停顿）时最直觉的写法 —— `moveReset` → 循环 `moveAppend` 追加 N 条命令 →
只 `moveStart` 一次 —— **被控制器拒绝并直接进急停**：

```
Process joints [...], s:100, z:2, js:-1
Append cmd absj#12
moveStart end (-60611)          ← 一次性追加多条后单次启动被拒
⇒ power=PowerState.estop · 臂已动了一小段(实测 ~8°) · 现场碰撞
```

正常逐点日志是 `Notified absj#214 finish:true (0)`，差别就在**每点一个 `moveStart`**。

- **铁律**: 这条控制器只接受 **每条 append 后单独 `moveStart`**。`-60611` 不是参数问题，
  换 `zone`/`speed` 都救不回来——不要在同一方向上反复试参数。
- 要真连续插补只能换 `MoveL`/`MoveJ` 或 RT/RL 实时接口（另一套下发方式，风险高于本路径）。
  没在空跑/仿真拿到证据前不许上真机。
- ⚠️ 急停后 `setPowerState` **救不回来**（回 `-3 The robot is in EStop state, please recover`）
  ⇒ 必须人工按示教器/控制柜急停复位。崩了第一件事是**只读确认关节角没乱动**
  （与下发前数值逐轴比），确认臂停在安全位置后再谈下一步。

## moveStart 之后的等待序列（顺序错了会误判「0.15s 就跑完了」）

`moveStart` 返回时控制器**还没起转**，此刻查 `opstate` 仍是 `idle`。写成
`if "idle" in opstate: break` 会当场跳出，日志出现 `secs=0.15` / `sent=0`，
看着像「跑完了」其实一步没走。正确顺序：

1. `moveStart` → **先等它进 `moving`**（上限 2~3s；等不到就判失败，不能判完成）
2. 再等回 `idle`（这一段才是运动时长）
3. 两步都要**先看 `power`**：变 `estop`/`off` 就是被保护拦了 ⇒ 立刻中止并上报，别继续轮询到位。
4. 状态读数**连采几次**再看结论——`on`/`off`、`manual`/`automatic` 在相邻两次调用间会来回跳，
   单次采样不能作判据。

## 逐点执行的固定开销 = 录制速度的物理天花板

录制轨迹常是 5Hz 采样（`frames[].t` 相邻中位 0.200s ⇒ 0.199 s/点），而逐点 MoveAbsJ 每点有
**~0.33s 固定开销**（`moveAppend` + `moveStart` + 轮询 `opstate` 的通信往返）。开销已超过录制单点间隔
⇒ 逐点执行**物理上不可能**达到录制节拍：实测 215 点，录制 42.85s ↔ 逐点 436s（2.028 s/点）。

- **一次定死的诊断手法**: 找轨迹里 `jump≈0.1°` 的那个点看耗时。实测仍要 0.21~0.33s
  ⇒ 那就是通信底线，与位移无关。此时再调 speed、去 dwell 都无用，不要拿它当「还能优化」继续试。
- **汇报口径**: 录制真值与实跑真值**分开列、写清来源**（录制读轨迹 JSON 的 `dur_s`，
  实跑取全程实测逐点求和），并给「达不到」的机制原因。别把调试档当节拍、也别把录制值当承诺值。
- ⚠️ 逐点日志里的 `secs` 是**单点耗时不是累计值**（依据：全部求和应等于总时长）。
  误当累计会算出偏 2 倍的节拍；报数前先 `sum(secs) == 总时长` 对一次。

## 包装脚本必须显式透传脚本要读的 env（默认一条都不带）

`rokae_sdk_run.sh` 这类 docker 包装只传 `ZMAX_HOST_TS` / `ZMAX_ROBOT_IP`。脚本里
`ZMAX_REPLAY_N` 这类**小批量调试开关不透传 ⇒ 容器里读不到 ⇒ 悄悄变成「整条一次性下发」**，
这正是上面那次急停的诱因。

- 加 `-e ZMAX_REPLAY_N="${ZMAX_REPLAY_N:-}"` 等逐条透传；加完**先 `--dry` 核对 `n_points` 真的是 10**，
  再碰真机——否则「只跑 10 点」的意图会在无声中变成全量。
- ⚠️ 透传成空串后 `os.environ.get("K", default)` **返回 `""` 而不是 default**（变量存在但为空）⇒
  路径变空串报 `FileNotFoundError: No such file ''`。脚本一律写 `os.environ.get("K") or default`。

## 起点跳变：该走归位段，不该整条拒发

真机停在中途、距轨迹第 0 点 60~80° 是常态（上一轮被打断/人工回位）。
**起点跳变单独走归位段**（插中间点，每段 ≤16.5°），帧内跳变另外预检（上限 40°）；
归位点也要有到位超时，超时必须报 **「归位段第 k/N 点未到位，正式点一个没走」**——
只写「失败」会被误读成轨迹本身有问题。

开跑前先把「当前位姿 ↔ 第 0 点」的逐轴差算出来报给现场：实测 1.84° 可直接开跑，
>40° 就请现场归位、别硬发。

## 验收纪律

- **先 dry 再动**：`--dry` 只读状态 + 算跳变，不 append 任何命令。dry 通过不等于可以真发，
  但 dry 不通过一定不能真发。
- **逐步加量**：3 点 → 10 点 → 全程，每级都看「全部到位 + 最大到位误差」再升级。
  实测 215 点全程 max 0.140° / 均 0.115°（阈值 0.6°）。
- **异常即停不重发**：任一点失败/被拒立即中止，不重发不补偿（重发会叠加成第二个动作）。
- 跑完留证：`power=on · idle · automatic` + 逐点 `err_deg` 全表 + `sum(secs)`。
- 上电/下电用仓库现成的 `tools/rokae/sdk_power.py --on|--off`，别另写一个。
