# 连续回放档：用 zone(转弯区) 把逐点停顿变成连续轨迹

用户说「轨迹不连续 / 机器人走一下停一下，能改成连续轨迹么」时读这份。

## 根因：`zone=-1` = 精确停

`arm_step_traj.py` 每条命令都写成 `MoveAbsJCommand(JointPosition(jt), speed, -1)`，
第三参是**转弯区**：`-1` 实测等同逐点精确停 ⇒ 每点必「静止→加速→减速→静止」，
再加约 1.8s/点固定开销（moveReset/append/start + 轮询），相图上就是「贴横线 + 稀疏分支」。

## 用法：现成脚本，别自己写

`tools/rokae/arm_replay_continuous.py`（一次性 append 整批 + 一次 moveStart，zone>0）：

```bash
ZMAX_REPLAY_N=40 ZMAX_REPLAY_SPEED=100 ZMAX_REPLAY_ZONE=3 \
  bash tools/rokae_sdk_run.sh --script arm_replay_continuous.py     # 小批量先验
ZMAX_REPLAY_N=215 ZMAX_REPLAY_SPEED=100 ZMAX_REPLAY_ZONE=3 \
  bash tools/rokae_sdk_run.sh --script arm_replay_continuous.py     # 整条
```

- `ZMAX_REPLAY_ZONE`：1~5mm 起步（3 实测够用）；`-1` 会退化成逐点慢跑。
- `ZMAX_REPLAY_CHUNK`：0 = 全部一次追加（默认就是整条一批）。
- 回执里认这几个字段：`mode:"continuous"` · `zone_mm` · `sent` · `n_mid`(起点归位插值点数) ·
  `final_err_deg` · `vs_record_s` · `max_jump_at`。

## 实测（同臂同轨迹，可直接引用）

```
停点档 (step_traj flow)   2.2 s/点   |v| P50 3.2 mm/s   静止(|v|<1) 24~79%
连续档 zone=3 40 点        1.397 s/点 55.87s = 录制 1.30×  final_err 0.10°
连续档 zone=3 40 点        |v| P50 24.2 · P90 33.3 · max 36.2 mm/s   静止 13%   停顿段(>0.4s) 3 次
215 点一次追加            成功(无 -60611、无急停)，仍在 1.4 s/点量级
```

判定"连续了没有"只看两条：**|v| 的 P50 抬没抬起来** 和 **|v|<1 的样本占比降没降**。
别拿"总时长变短"当唯一证据（大跨步段会吃掉一部分收益）。

## 安全闸（脚本自带，别绕过）

1. 前置 `power=on` + `operation=idle/automatic`（drag/manual 不下发）。
2. 逐点关节跳变 > `MAX_JUMP_DEG(40°)` **整条拒发**；本轨迹最大 `#19→#20` 31.06°（不触闸）。
3. 起点离第 0 点 > `PREP_SEG_DEG(18°)` 时先插归位段；回执 `prep{n_mid, seg_deg, jump_deg}`。
4. 整批超时 = `dur_src × ZMAX_REPLAY_BUDGET_X`（默认 **3.0**），超时 `moveStop` 并回
   `why="第 1 批超时未停稳(operationState=OperationState.moving), 已停"`；任一点被拒立即停、不重发不补偿。
   🔴 **默认 3 倍对连续档必然误停**：`dur_src` 是录制时长 42.85s ⇒ 预算只有 128.6s，而连续档实测整条要
   **321–345s**（1.5–1.6 s/点）。症状是「sent=215、batch secs=321…345、`ok=false`、臂停在半路」（实测停在离末点 84.5° 处）。
   起跑就带 `ZMAX_REPLAY_BUDGET_X=8`（预算 ≈343s），别等它撞完再去查是不是轨迹有问题。
   判「是预算的锅」看一行：`budget_s` 与 `batch.secs` 同量级或更小 ⇒ 就是预算，不是超时真有卡顿。
5. 收尾只判**最终关节角误差**（`TOL_DEG=1.5`），不逐点判到位 —— 连续模式本来就不在中途停。

## 🔴 连续档 ≠ 生产节拍

连续模式**不会停在夹爪 #9/#205 与 AOI 点 #125/#151/#172**，那就是没夹、没检测。
所以它只用于：相图/节拍研究、拍录像、摸速度上限。
要"生产版连续"得做**减速不停**：在这些点前把速度降到 5%、到点精确停（zone=-1）后再加速。
报给现场时必须把这条讲明，否则会以为可以直接上产线。

## 🔴 速度阶梯：`speed` 200% 是硬上限，400% 直接掉电

同一段 21 点（`frames[40:61]`，段内最大跳变 14.5°）只改 `ZMAX_REPLAY_SPEED`：

```
speed 100   →  1.606 s/点（215 点整条 345.4s · final_err 0.12°）
speed 200   →  1.071 s/点（21 点 22.49s · final_err 0.13°）   ✅ 控制器接受
speed 400   →  moveStart 后控制器立刻 power=off，臂未动（sent=0）  ✗ 拒绝
```

200% 整条 215 点的实测（可直接引用）：**206.5s / 0.96 s/点 / final_err 0.12°**，
`|v| P50 42.2 · P90 67.9 · max 77.6 mm/s`、静止(|v|<1) 仅 **3%**。三档并排：

```
停点档           532 s  2.47 s/点   |v|P50 3.2   静止 24~79%
连续 zone3 100%  345 s  1.61 s/点   |v|P50 24.2  静止 13%
连续 zone3 200%  206 s  0.96 s/点   |v|P50 42.2  静止  3%
```

- **结论**：这条 `MoveAbsJ + speed` 路的天花板在 200% 附近（仍是录制 0.2s/点的 ~5.4 倍）。
  被问「真按录制速度可以么」就报这张表，不要拿「加 speed 试试」。
- 录制速度的真实量级（要贴它得先知道要多快）：末端峰值 **862 mm/s**（P90 348）、关节峰值 **124–141°/s**；
  实测连续档只有 36~78 mm/s ⇒ 差 5–24 倍。
- 🔴 **"上 RT 就能贴录制速度"是错的默认假设**：仓库里没有任何 RT 实现（`goto_xyz`/`axial_retract` 这些都是
  `NrtCommandMode`）。RT（`RtCommandMode` + `setControlLoopJoi`）已实测：容器内回调只有 **~7Hz**，
  按时间索引报 `kActualJointVelocityLimitsViolation`、改弧长积分后第 17 拍 `kCollision` 掉电，
  且**每次失败都锁 EStop（clearServoAlarm+moveReset 解不开，要示教器复位）**。
  细节与零运动探针闸门见 `rokae-sdk-motion-semantics` 的 `references/rt-servo-streaming.md`。
  被问"真按录制速度可以么"：先报阶梯表，再报这条实测上限，不要承诺 RT 能成。
- **掉电后的恢复动作**（实测 0.5s，臂不动、关节角逐轴不变）：
  `bash tools/rokae_sdk_run.sh --script arm_power.py on`，回执认 `power_before/after` 与 `ec.ec=0`。
  上电后连采两次 `endInRef` 确认位移 0.00mm 再谈下一步；别在这时重发轨迹。

## 采样配合：记录器必须与绘图分开

- 绘图层（pyqtgraph 重绘几千点）会把采样拖到 2~4Hz，相图速度就失真。
- 定式：无绘图 20Hz 记录器轮询 `http://127.0.0.1:39071/status`（`status.endInRef/jointPos/jointVel`），
  速度 = `J(q)·q̇`（URDF `xms5_r800_w4g3b4c.urdf`，tool1 偏移 0.2587m），`jointVel` 整帧为 0 时退回位置差分；
  每行落 `ts/pos/q/qd/v/sp/H`，跑完再离线出图。
- 统计只取跑批区间（否则跑完的静止样本把占比带偏）。文件会跨多轮累积，按 `ts` 间隔 >15~20s 切段，
  再取"最后一个含运动的簇"才是本轮（否则拿到的是几小时前的空闲样本：实测 193k 样本里 93% 是静止）。
- 同一份 jsonl 被两个进程同时写会出现半行/拼接 JSON ⇒ 解析要容错、写完去重，且**同一记录器只跑一个实例**。

## 相图选轴：z 单轴会漏掉 67% 的运动

- `(z, p_z)` 是**唯一与重力势共轭**的一对（`H = p²/2m + m·g·z`），所以能量图只能这么画；
  但它的代价是**看不到水平运动**：实测这条轨迹水平 `|v_xy|` 占 v² 的 **67%**、P90 25.7 vs 垂直 17.9 mm/s，
  且有些样本 `v_z≈0` 而水平还在 16 mm/s ⇒ 在 z 相图上正好落在横线上，会被读成"静止"。
- 汇报时要**成套给**：`(z, p_z)` 能量共轭 + 末端三轴 `(x,vx)(y,vy)(z,vz)` + 六关节 `(q_i, q̇_i)`。
  关节空间才是这台臂的真实坐标系（控制器本来就按 MoveAbsJ 逐关节走），末端三轴是雅可比变换后的产物。
- 六关节相图读法：峰值角速度 6~13°/s、P90 0.2~1.3°/s、换向次数 7~17 —— **换向多的关节才是节拍瓶颈**
  （实测 J3/J4/J6 承担主要行程，J1 最少 ⇒ 整个循环在同一个方位角内完成）。
- 用户问"为什么纵轴不是 p"时：`p = m·v_z` 只差常数 m，两套等价；标 p 更规范（共轭变量），标 mm/s 更好读。
