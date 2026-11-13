# 「同步操作」：仿真先走 N 点 → 真机逐点跟走（画面实时跟随）

左栏三个按钮的语义分工，别混：

| 按钮 | 行为 | 用途 |
|---|---|---|
| `bRTraj` 📍 右臂跑真实轨迹 | 按真实时间连续回放（1×，时间轴插值） | 看整条轨迹「怎么跑」 |
| `bSyncStep` ⏭ 同步操作 + 输入框 N | 仿真逐点走 N 点（每点 settle）→ 走完自动驱动真机按同一批关节角帧逐点走 N 点 | 对点/逐点校验 |

## 数据同源

`tools/web/real_traj_joints.json` 的 `frames[i].j`（6 轴关节角，录制里 SDK 直读）—— 仿真与真机吃**同一批帧**，
姿态/翻面天然保真，不要中途改走位置 IK。真机腿脚本 `tools/rokae/arm_step_traj.py`，
端点 `POST :8797/api/arm/step_traj {n,dry}` + `GET .../status`。

## 编排

1. 点按钮 → 仿真按 `SYNC` 状态机逐点走（move 420ms + dwell 300ms），文案逐点更新。
2. 仿真走完 → `syncArmRun(n)`：POST 起真机任务（异步，返回 pid），立刻 `syncArmFollow(true)`。
3. 页面每 100ms `fetch('/api/tcp')` 拿真值关节角写进 `PREV.q` → `urdfFK` → `drawVR` + `mjPushQ`
   ⇒ 画面里仿真臂就是真机的实时镜像。
4. 每 800ms 轮询 `status` 更新「真机 第 k/N 点 · Xs」；`finished` 时停跟随、按 `ok_all` 给绿/红文案。

## 六个坑（每个都表现为「不同步 / 不动 / 卡住」）

- **真值字段是 `joints`（复数）**：只有 `latest.json` 原始文件叫 `joint`。写 `d.joint` 得到 undefined，
  跟随循环静默空转 —— 最隐蔽的失败形态。任何跟随循环都要在拿不到 6 分量时打一行日志，别 `return` 了事。
- **关节速度 5% 太慢**：实测 0.3°/s（7.5° 走 25s、12° 走 35s），现场判「卡住」。用 20%（3 点 15/7/9s）。
- **restart 8797 会杀掉真机任务**：`KillMode=control-group` 把 Popen 的 docker 子进程一起 SIGTERM
  （实测真机走到第 3 点被打断）。unit 加 `KillMode=process`（`tools/systemd/zmax-traj-ar-killmode.conf`），
  restart 前先等任务结束；被打断后**先查 power/operation/mode + 真值是否静止**再继续。
- **忙闲判 pid 存活**：`t0` 被 NTP 回拨打乱，`time.time()-t0 < 1800` 会把结束的上一轮当在跑 ⇒ 新任务全被拒。用 `os.kill(pid,0)`。
- **status 端点要支持 GET**：页面轮询走 GET，只写在 `do_POST` 分支 ⇒ 404 `not found`。逻辑抽方法给两条路共用。
- **连点第二次必失败（起点跳变）**：走完 N 点后臂停在点 N，再点从点 1 起 ⇒ `|当前→点1|` 实测 69.4° > 30° 跳变闸，直接拒发「第 0 点跳变超限」。真机腿必须带**起点归位段**：
  `jump0 > MAX_JUMP` 时按 `ceil(jump0 / (MAX_JUMP*0.6))` 插中间点先走回点 1（单独上报 `prep`/`prep_progress`，不占 N 点计数），
  归位段任一点未到位就停并明说「正式点一个没走」。验收时**连续点两次**，第二次必须能走。

## 真机腿口径（为什么这么写，不是可选风格）

- **关节绝对目标 MoveAbsJ，不用笛卡尔线/IK**：逐点走本身是一停一走，不需要直线插补；
  关节空间还避开了 50102/50120 奇异与 50113 姿态阈值（单步姿态 >20.49° 会被拒）。
  且绝对目标 ⇒ 每点独立，不累积漂移（相对运动走 N 点的漂移实测有 27mm 量级）。
  仿真侧同理：位置 IK 会丢掉腕部翻转（J4 跨度可达 254°），必须回放录制的 6 轴角度。
- **三道闸，缺一不下发**：① `ctl_auth.json` 已授权（与执行器同一真源，读不到就 fail-closed）
  ② ping 控制器（真机腿走容器直连控制器 IP，走 WiFi 不行）③ 脚本内 `power=on` + `operation=idle`
  + 单点跳变 ≤30° + 单点等到位超时 60s。任一条不过就停，且文案要说清是哪一条。
- **验收取证三件**：真值关节角（前后 + 每点 `err_deg`）、控制器状态（power/operation/mode）、
  页面文案时序。三者分开写，别只报“已走完”。
- **零运动自验**：假 SDK 在本 skill 的 `scripts/stub_xcoresdk_python.py` ——
  `ZMAX_SDK_DIR=<目录> ZMAX_STEP_CMD=<cmd.json> python tools/rokae/arm_step_traj.py`，
  开关 `STUB_J0/STUB_POWER/STUB_OP/STUB_STUCK/STUB_REJECT/STUB_FAIL_CONNECT` 可验
  跳变闸、起点归位段、到位超时即停、控制器拒发、断链文案（真机时序仍需现场）。

## 验收口径

- 仿真段：文案按时序出现「已到第 k/N 点 · 停一下」→「仿真走完 N 点」。
- 跟随段：同时抓 `PREV.q` 与 `/api/tcp` 的 `joints`，六轴逐帧差应 ≤0.3°（实测 0.0~0.3°）。
- 真机段：`zmax_data/rokae_sdk/traj_step_out.log` 每点一行 `progress`（含 `err_deg`、`secs`），
  末行总结 `ok/n_done/why`；页面文案「✅ 真机走完 N/N 点」。日志必须**追加**写（每轮打一行 `=== round <时间> n=… dry=… ===` 分隔），
  用 `"w"` 会覆盖上一轮 —— 下一轮一旦被跳变闸拒，上一轮的成功证据就没了。
- 闸门未满足时的文案必须指路（未授权 → 8793 授权真动；产线网不通 → 插回网线），不能只写"失败"。
