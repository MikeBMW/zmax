# 轨迹回放带夹爪开合 (2026-11-13 定案)

## 事实
- `tools/web/real_traj_joints.json` 只有 `{p,q,j,t}` —— **没有夹爪字段**。原录制 `rec_20261111_181020` 的 `poses.jsonl` 也只记位姿；`l2_daemon.log` 与 `agent_hub/out/*` 在该时段查不到任何 grip 记录。
- 所以夹爪动作点**推不出来**，必须由计划给定。

## 机制(三层，各管一段)
1. 计划文件 `tools/web/real_traj_grip.json`：`{"grip":[{"i":<下标0基|负数从末尾>,"act":"open"|"close","hold_ms":2000}]}`；`candidates.static_frames` 记静止帧(9/19/109/111/112/158)作参考点位。
2. `tools/rokae/arm_step_traj.py`：读 `spec.grip`，走到该帧后打印 `{"grip_due":true,"i":..,"act":..,"hold_ms":..}` 并**原地 sleep hold_ms**(默认 2600)，之后打印 `grip_done`。dry 模式只回 `grip_plan`，不下发。
3. `tools/tcp_ar_server.py`：`step_traj` 把 body.grip（否则计划文件）按 `_start` 换算成本轮局部下标写进 `traj_step_cmd.json`；`_step_traj_status` 扫日志的 `grip_due`，每事件只发一次（key=`轮t0:i:act`，记进 `state.grip_sent`），下发动作见下面「真通道」一节 —— **不要再往 `cmd_arm.fifo` 写 skill 串，那条路没有夹爪分支（见坑）**。

实测(215 点整轮): `grip_due i=1 close` 与 `grip_due i=213 open` 都发出, status 的 `grip_events` 两条都 `sent:true`，且与逐点 `progress` 行交替、没拖慢节拍。
⚠️ `sent:true` 只代表**指令写进了通道**，不代表夹爪动过 —— 判断夹爪有没有动只能读 `/gripper_pos`（见「真通道」）。

## 验法(零硬件)
`/home/ubuntu/.hermes/cache/scratch/test_grip_plan.py`：造一个 `xcoresdk_python` stub（假 SDK），`ZMAX_SDK_DIR` 指过去跑 `arm_step_traj.py --dry`，断言 `grip_plan` 解析正确 ⇒ PASS。

## 真机到底有没有在走(别只看页面)三处交叉验证, 缺一不可:
1. 服务端日志: `grep -a 'step_traj' /tmp/tcp_ar_server.log | tail` —— 用户说“点了/开始了”但这儿没有新 POST = 请求根本没到服务端(旧标签页/JS 报错), 不是机器人的问题。
2. `GET /api/arm/step_traj/status`: `running` 为真且 `done` 在涨; `cursor` 只在整轮结束时按 `n_done` 推进。
3. 真值: `zmax_data/rokae_sdk/tcp_out/latest.json` 的 `joint` 两次采样必须有变化。
4. 采集侧交叉验真(有建图时最直接): `8806/health` 的 `frames_total` 不涨、而 `frames_skipped_static` 隔 6~10s 两次采样在涨(约 10/s) ⇒ 守护活着、位姿新鲜，**臂确实没动**；两者都不涨才去怀疑 ros-bridge/位姿卡死。
- 🔴 `GET .../status` 里的 `running=false, cursor=215, done=215` 是**上一趟的残留**，不能当“刚跑过”的证据；判定“本次在跑”只能靠日志里今天的新 `POST /api/arm/step_traj` 与 `done` 在涨。
- 补发前一次性核完三样：授权 `epoch/until` 剰多少秒、机器人 `power/idle/automatic`、`status.grip_plan` 条数与计划文件是否一致(只剩 2 条事件 = 读的是旧计划文件)。
- 状态里出现 `finished:true, done:215, cursor:215` = 这条轨迹**已全程走完**; 要重跑必须先 `POST {"reset":true}`, 否则下一次起跑直接报“已到 215/215”。
- `reset` 可能被 `stage:"busy"` 拒(上一轮容器还在收尾), 等 5~10s 重试。
- `grip_due` / `grip_done` 是执行器 stdout, 落在 `traj_step_out.log`; 与 `progress` 行交替出现, 状态接口的 `grip_events` 只含本轮。
- 执行器容器时钟可能比主机慢 8h(`grip_due.t` 写的是容器时间), 对日志时间戳时要换算。

## 怎么证「新代码真的生效了」(重启后必做)
- `bash tools/ar_server_ctl.sh restart` 可能打出一次 `Address already in use`(重复拉起的那只进程抢端口失败), **别据此判断没起来**。
- 认代码版本要看只有新版本才有的字段: `GET /api/arm/step_traj/status` 出现 `grip_events` / `grip_plan` 即新代码在线。
- 认计划文件被读: 跑一轮 `{"n":1,"dry":true}` 后读 `zmax_data/rokae_sdk/traj_step_cmd.json` 的 `grip_src`(应为 `real_traj_grip.json`)。
- **`n=1` 演练里 `grip` 为空是正确行为**: 计划点 `i=1`/`i=-2` 都不在这一轮的下标范围内, 越界不动作。看到空就当 bug 改, 会把正常逻辑改坏。
- 演练完先确认 `cursor==0` 再让老倪起跑(必要时 `POST {"reset":true}`), 否则真机会从第 2 点开始。

## 坑
- 计划里 `i` 是**全轨迹**下标；`start` 非 0 时必须减 `start`，越界不动作。顺带一条：`i=-2` 在 215 点轨迹上就是 0 基 213 = 第 214 点，没有隐藏语义。
- 🔴 **夹爪不能靠 `cmd_arm.fifo` 下发**：这条 FIFO 的唯一读者是 SDK 桥（容器内 `/repo/sdk_agent.py`），它的 `handle()` 只认 `ping/state/pose/path/follow/stop/reset/move-*`，**没有 grip 分支** ⇒ 写进去的 `{"skill":"L2.grip_open"}` 被读走就丢，日志还会因为“写成功”打出 OK。判据：`sudo grep -n grip /proc/<桥pid>/root/repo/sdk_agent.py` 没命中 = 这条路是死的。
- 改完 `tcp_ar_server.py` 要重启 8797 才生效(重启须老倪点名)；计划 JSON 是每次启动读，改它不用重启。
- 🔴 **计划顺序要保证起跑那一下有可见变化**：夹爪开合是**保持型**状态（不随臂动/授权到期复位）。
  实测把第一个事件排成 `i=1 close`、而夹爪本来就张着 ⇒ 一开跑只看到"夹上然后一路闭着",
  直接判"夹爪没修好"。排计划前先读当前 `/gripper_pos`，第一个动作应当是**改变现状**的那个，
  且 open/close 至少各有一次。

## 夹爪真通道 + 真值取证（唯一可信口径）

Orin（`tashan@192.168.23.66`）上有现成的 ROS2 夹爪驱动：

```bash
# 🔴 必须先 source 工作区, 否则报 `The passed service type is invalid`(看着像服务不存在, 其实是 interfaces 包没进环境)
source /opt/ros/humble/setup.bash
source /home/tashan/zl/*/install/setup.bash     # 目录名带版本号 ⇒ 用 glob, 别写死
# 真值（只读）：0.0 = 全闭，正值 = 开口(mm)
ros2 topic echo /gripper_pos std_msgs/msg/Float32 --once
# 下发：target_pos 是开口 mm；负值参数 = 保持当前
ros2 service call /gripper_driver interfaces/srv/GripperSrv \
  '{target_pos: 0.0, target_speed: -1.0, target_force: 40, target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}'
```
- 实测口径: 开 = `target_pos 70` ⇒ `/gripper_pos` 70.0; 合 = `target_pos 0` ⇒ 0.0; 回执里的 `curr_pos`
  是**途中值**(发 70 时回 `curr_pos=35.0`), **不能当结果**, 必须隔 1~2s 再读一次话题。
- 单次调用(ssh + source + 服务 + 回读)约 **10~12s** ⇒ 计划里每个事件的 `hold_ms` 给 **15000**,
  默认 2600 会让下一帧在夹爪还在走的时候就动臂。
- 这条 ssh 调用**不要放在 HTTP 处理器里同步跑**: 实测会把 `/api/arm/step_traj/status` 一起堵十几秒,
  页面进度看起来"卡住"。放线程里发, 状态里回 `pos_before/pos_after` 作回证。
- 服务类型定义在 Orin 工作区 `install/interfaces/share/interfaces/srv/GripperSrv.srv`（`target_pos/target_speed/target_force/target_acc/target_push_length/target_push_speed` → `curr_pos`）。CLI 里 `ros2 interface show interfaces/srv/GripperSrv` 会报 `Unknown package`，因为没 source 工作区 —— 去文件里看定义，别以为接口不存在。
- 历史快照脚本 `docs/6-开阳-工程落地/data_snapshots/*_gripper_v5187/scripts/bump_v5187_grip_*.sh` 就是这条口径（闭合 = `target_pos: 0.0, target_force: 40`）。

🔴 **取证纪律：说“夹爪开合好了”之前必须有真值前后值**。
- 每次动作前后各读一次 `/gripper_pos`，把 `{"ts","pos"}` 落 jsonl；`tools/grip_tap.py` 是现成的流式录制器（订阅 `/gripper_pos` 打时间戳落 `zmax_data/ar_rs/grip_<ts>.jsonl`），但它起不来时不要空口断言 —— **确认它真在写**（进程在 + jsonl 在长），否则改用下面这条一定起得来的：
```bash
# 在 Orin 上后台起，整轮回放 ~5Hz 连续落盘（不依赖任何自研录制器）
ssh tashan@192.168.23.66 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; \
  F=$HOME/grip_pos_$(date +%Y%m%d_%H%M%S).jsonl; \
  setsid nohup timeout 2400 ros2 topic echo /gripper_pos std_msgs/msg/Float32 > $F 2>&1 < /dev/null & echo FILE=$F'
```
- 8797 侧每发一次动作就写一行证据到 `zmax_data/rokae_sdk/grip_events.jsonl`（`t/act/target_mm/pos_before/pos_after/answer/ok`）；`ok` 只在**回读值进容差**（`max(3mm, 15%×开口)`）时为真 —— 服务回了 `curr_pos` 但没到位一律记 FAIL。
- 判“这轮到底有没有夹”看**事件文件 + 真值曲线**，不看日志里那句 OK；日志行形如 `[grip] HH:MM:SS 走到点#i ⇒ 夹爪 close: OK (真值 70.0 → 0.0 mm, 目标 0.0)`，落在 **`/tmp/tcp_ar_server.log`**（`/var/log/zmax-traj-ar.log` 只有更早版本的行，别在那儿找不到就以为没执行）。
- 现场症状对照：夹爪一直闭着而“日志说 open OK” ⇒ 先查通道有没有 grip 分支，不要怀疑夹爪本体/气压。
- 计划顺序的另一半：夹爪状态是**保持型**，起跑前读一次 `/gripper_pos` 记下初始开口，汇报时说清“起跑时 X mm → 现在 Y mm”，用户才有依据判断他看到的画面。
