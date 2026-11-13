# 「同步操作」：仿真先走 N 点 → 真机逐点跟走（画面实时跟随）

> 用户说「画面右臂的位置不对/太靠前」时先分诊：游标落后（本文）vs 画面被接管（`references/right-arm-display-truth.md`）
> vs 几何真错（URDF 正解 ≤ 5mm）。

左栏三个按钮的语义分工，别混：

| 按钮 | 行为 | 用途 |
|---|---|---|
| `bRTraj` 📍 右臂跑真实轨迹 | 按真实时间连续回放（1×，时间轴插值） | 看整条轨迹「怎么跑」 |
| `bSyncStep` ⏭ 同步操作 + 输入框 N | 仿真逐点走 N 点（每点 settle）→ 走完自动驱动真机按同一批关节角帧逐点走 N 点 | 对点/逐点校验 |

## 数据同源

`tools/web/real_traj_joints.json` 的 `frames[i].j`（6 轴关节角，录制里 SDK 直读）—— 仿真与真机吃**同一批帧**，
姿态/翻面天然保真，不要中途改走位置 IK。真机腿脚本 `tools/rokae/arm_step_traj.py`，
端点 `POST :8797/api/arm/step_traj {n,start,speed,dry}` + `GET .../status`（服务端按 `frames[start:start+n]` 取点，
游标 = `start + n_done`）。

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
- **忙闲判 pid 存活**：`t0` 被 NTP 回拨打乱，`time.time()-t0 < 1800` 会把结束的上一轮当在跑 ⇒ 新任务全被拒。用 `os.kill(pid,0)`，但**必须 `pid > 1` 才判活**：`os.kill(0,0)` 是「发给整个进程组」恒成功，state 里没有 pid（align/reset 写的状态）时就把「没在跑」当「在跑」，新任务被 busy 永拒。
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
  + 单点跳变 ≤40° + 单点等到位超时 60s。任一条不过就停，且文案要说清是哪一条。
- **授权只在校验一次，长跑不用续**：入口是 `http://<主机>:8793/room` 的「🔓 授权真动(两步)」连点两次
  （第一步先确认机器旁没人、手不在臂内），窗口 1800s（`ctl_auth.json` 的 `window`/`until` + `epoch`；改时长见文末「授权窗口」）。这道闸只在
  `POST /api/arm/step_traj` 起跑时查一次、跑起来中途不再查 ⇒ 215 点走 21~32min 也不必中途续授权。
  反过来窗口过期后点「同步操作」：仿真那遍照走，真机一步不动（`stage:"auth"`），此时**游标不动、真机没动
  ⇒ 补授权再点一次即可，别让人重来**。
- **验收取证三件**：真值关节角（前后 + 每点 `err_deg`）、控制器状态（power/operation/mode）、
  页面文案时序。三者分开写，别只报“已走完”。
- **零运动自验**：假 SDK 在本 skill 的 `scripts/stub_xcoresdk_python.py` ——
  `ZMAX_SDK_DIR=<目录> ZMAX_STEP_CMD=<cmd.json> python tools/rokae/arm_step_traj.py`，
  开关 `STUB_J0/STUB_POWER/STUB_OP/STUB_STUCK/STUB_REJECT/STUB_FAIL_CONNECT` 可验
  跳变闸、起点归位段、到位超时即停、控制器拒发、断链文案（真机时序仍需现场）。

## 相对游标（输入 N = 「接着再走 N 点」，不是「从头走 N 点」）

老倪口径（2026-11-13）：「我输入 10，你应该再继续走 10 个点，而不是重头开始走」。

- **唯一游标真源** = `zmax_data/rokae_sdk/traj_step_state.json` 的 `cursor`（= 下一点的下标，0 基）。
  页面不自己记游标：进页面/每次开跑前读 `GET /api/arm/step_traj/status` 的 `cursor/total`，
  按 `frames[cursor : cursor+N]` 走仿真，`POST {n, start}` 让真机腿吃同一段 ⇒ 刷新/换浏览器都接得上。
- **推进规则**：status 在读到本轮收尾行时置 `cursor = start + n_done`（走成几点推几点；被闸拦住 n_done=0 就原地不动），
  并用 `advanced` 标记保证只推进一次（幂等）。dry 轮 `n_done` 为 None ⇒ 归 0 ⇒ 游标不动（没动就是没动）。
- **第一次用/旧状态没有 cursor** ⇒ 按真机当前关节角对齐最近的帧（现场实测臂停在 frame 8，与真值差 0.1°）。
  显式入口：`POST {align:true}` 把游标对到真机姿态（只读真值、不动臂）、`POST {reset:true}` 归零；
  页面两个小按钮就是这两个接口。手动拖过示教器后点「◎ 对齐当前位置」把游标接回来。
- **首尾同一姿态 ⇒ align 会挑错点**：这条录制里 frame 0 / 69 / 214 三处都在初始姿态（互差 ≤1.7°）。
  实测把归零位姿 align 到 105、把人手动摆回起点时又 align 到 69。人回到初始姿态要的是
  **「↺ 回起点」(reset)**，不是 align；align 只用于「从半路某点接着走」。
- **首点预检**：`POST {n}` 若目标点离真机当前姿态 >30° ⇒ 直接 `stage:"jump"` 拒绝并给 `hint`「最接近第 k 点」
  （别白起容器、别让脚本闸在容器里才拒）。
- **游标会被「别处动臂」甩开**：手动示教、别处执行、真实链路跑过一段之后，游标仍停在老位置（实测游标 34，真机已在第 105 点）。
  这时点同步就是从旧点起走，用户看到的是「位置不对 / 太靠前」。用户一说位置不对，先 `POST {align:true}` 拿 `cursor/diff_deg`
  对一下真值最近点，再谈画面或几何 —— 游标错和画错是两个故障，别混着查。
- **报位置必须带采样时刻**：先说「刚才/现在」，再给 6 轴或 TCP；隔几分钟的数字会被当成记错。报之前重采一次
  `zmax_data/rokae_sdk/tcp_out/latest.json`（文件龄 ≤2s 才算现在），并顺手算一下它离游标有多远。
- **末端**：`cursor >= total` ⇒ `stage:"end"`「已在轨迹末端 · 点『↺ 回起点』」；`n` 自动夹到 `total-start`。

### 这一版顺手踩到的三个坑

- **`os.kill(0, 0)` 恒真**：state 里没有 `pid`（align/reset 写的状态）时 `int(None or 0)=0`，
  `os.kill(0,0)` 发给整个进程组必成功 ⇒ `running:true` 永远是「在跑」，新任务全被 busy 拒。判活必须 `pid > 1`。
- **日志尾巴必须按轮切段**：状态解析逐行扫日志取最后一条 `progress`/收尾行，跨轮会把**上一轮走完**当成本轮 ⇒ 游标跳。
  扫到 `=== round` 就清空 `_prog/_fin`，只认最后一段。
- **跳变闸与真实数据打架**：这条轨迹相邻点实测最大 31.1°（`frames[19]→[20]`），原闸 30° 必然在中途拒发。
  `MAX_JUMP_DEG=40` 才是「>40° 才防瞬移」。改闸常量必须先用真值算出相邻点跳变分布，别拍。

## 离线验证（不重启线上 8797，也绝不动臂）

- **第二实例，不碰线上进程**：用 importlib 加载模块、自己把 `H` 挂到备用端口（8897/8898），**别走 `main()`** ——
  `main()` 会 `OB3.warm()` 起光模块检测线程去抢相机、写 `/dev/shm`，两个实例互相踩。端口虽是 `AR_PORT` 环境变量，
  第二实例必须显式换端口（撞 8797 会 bind 失败，且看着像"改了没生效"）。

  ```python
  spec = importlib.util.spec_from_file_location("t", "tools/tcp_ar_server.py")
  m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
  threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", 8897), m.H).serve_forever, daemon=True).start()
  ```

- **哪些端点零运动可测**：`status` / `align` / `reset` / `{dry:true}` 都不下发指令（脚本里 `if dry:` 直接算完 return，
  不 moveAppend），可以把游标逻辑、越界夹取、末端拒绝全验完再上线。
- **有状态规则要造数据验，别赌**：写 `traj_step_state.json`（`start/cursor/advanced/pid=0/log=<临时日志>`）+ 临时日志
  （`=== round …` 段 + 收尾行 `{ok,n_done,steps}`），再 GET status 看 cursor 是否 `start+n_done`；再造"上一轮走完、本轮刚起"
  验证分段解析。**验完必须 `POST {align:true}` 把游标回到真机姿态**，别把测试值留在现场。
- **页面热读、服务端不热读**：`tcp-ar.html` 改完刷新即生效，`tcp_ar_server.py` 改完必须重启。页面侧不用起浏览器验语法：
  抽出内联 `<script>`（跳过 `type=application/json` 的数据块）逐块 `node --check`；再用浏览器打开页面读 console
  （`js_errors` 必须为空）+ 确认新按钮 id 存在、状态行文案确实来自接口。
- **重启**：`bash tools/ar_server_ctl.sh restart`（按端口找 pid、循环 kill 到端口真空释放，否则会报 started 却在跑旧代码）。
  线上服务重启要老倪点名才动；重启前先确认没有在跑的真机任务（`status.running=false`）。

## 开跑前自检（人问「现在可以了吧」）

五项全绿再让人点按钮，别只答「可以了」——每项都把实测数字报出来：

1. 授权：`ctl_auth.json` 的 `until - now > 0` 且 `revoked_at == 0`，顺报剩几秒 / 到期时刻 / epoch；
2. 游标：`GET /api/arm/step_traj/status` 的 `cursor/total`，且 `running=false`（没有上一轮还在跑）；
3. 真值新鲜：`zmax_data/rokae_sdk/tcp_out/latest.json` 文件龄 ≤2s，报 6 轴角度（°）；
4. 首点跳变：`max|frames[cursor].j[i] - live[i]|`（度）≤ 40，报数（人回到初始位姿时约 1~2°）；
5. 链路与状态：`ping 192.168.23.160` 通 + heartbeat 的 `power=on / operation=idle / mode=automatic`。

## 验收口径

- **全跑一遍的成本（人问「输多少能全跑」）**：总点数 = `frames` 长度（本条 215）。游标 0 时输入 215 即全程；
  仿真那遍约 2.6min（每点 move 420ms + dwell 300ms），真机在关节速度 20% 下每点 6~9s ⇒ **约 21~32min**；
  要快只能抬 speed（40% ≈ 3~4.5s/点，全程 11~16min），别改 dwell 去凑。

- 仿真段：文案按时序出现「已到第 k/N 点 · 停一下」→「仿真走完 N 点」。
- 跟随段：同时抓 `PREV.q` 与 `/api/tcp` 的 `joints`，六轴逐帧差应 ≤0.3°（实测 0.0~0.3°）。
- 真机段：`zmax_data/rokae_sdk/traj_step_out.log` 每点一行 `progress`（含 `err_deg`、`secs`），
  末行总结 `ok/n_done/why`；页面文案「✅ 真机走完 N/N 点」。日志必须**追加**写（每轮打一行 `=== round <时间> n=… dry=… ===` 分隔），
  用 `"w"` 会覆盖上一轮 —— 下一轮一旦被跳变闸拒，上一轮的成功证据就没了。
- 闸门未满足时的文案必须指路（未授权 → 8793 授权真动；产线网不通 → 插回网线），不能只写"失败"。

## 「仿真走完了，真机一步没动」分诊（先判消息发没发出去）

判序固定，别一上来查控制器/执行腿：

1. `sudo grep 'POST /api/arm/step_traj' /var/log/zmax-traj-ar.log` —— **8797 的真实 stdout 是 `/var/log/zmax-traj-ar.log`**
   （`zmax_data/logs/` 下同名文件可能是旧的，或根本没人写）。
   一条都没有 ⇒ **请求压根没发出**，是页面侧交棒没触发：`syncArmRun()` 里原写的是
   `if(!cb||!cb.checked) return;`（未勾「真机也走」就静默退出），控制器/授权/执行腿全都不相干。
2. 有 POST 且回 `stage:"auth"` ⇒ 授权过期；回 `stage:"jump"` ⇒ 起点跳变（见下）；回 `ok:true` ⇒ 才去看
   `traj_step_out.log` 与执行腿。
3. **静默 `return` 是这类故障的通病**：任何「仿真走完 → 真机」的交棒点，跳过的分支必须在状态行写清
   「只走了仿真，真机未下发」——不许无声退出，否则现场只能猜，而日志干净得像一切正常。

## 中途续走的 `start` 怎么定（轨迹会自相交）

- 预检是 `frames[start]` 与真机当前姿态的夹角 ≤30°（脚本内硬闸 `MAX_JUMP_DEG=40`），超了回
  `stage:"jump"` + `near=<最近点下标>`；**按 `near` 续走，不要"回第 1 点重来"** —— 那就是闸要拦的瞬移。
- 录制轨迹**会自相交**：实测臂正好站在第 70 点（差 0.1°）时，离第 4 点却有 33.7°，而 frame 0..2 与 frame 70
  是同一个物理位姿 ⇒ **"游标 3" 不代表臂在第 4 点附近**。选 start 前先在整条轨迹上按 `min|关节差|` 扫一遍，
  别用「游标 + 1」硬算；这一步也等价于页面上的「◎ 对齐当前位置」。
- 页面挂了也能直接下发（同一条授权链）：`POST /api/arm/step_traj {"n":146,"start":69,"speed":20}`，
  回 `{ok,started,pid,n,start,total}`；之后只看 `/status` 的 `running/done/n/why`。

## 授权窗口时长（现口径 30 分钟）

- 两处同口径：`tools/ctl_auth.py` 的 `DEFAULT_WINDOW`（env `ZMAX_CTL_WINDOW` 优先）+ `~/zmax_data/ctl_auth.json`
  的 `window` 字段；`grant()` 优先取**文件里的值** ⇒ 改文件即对新授权生效，**不必重启 8793**。
- **已 armed 的那一次不会变**（`until = since + 旧 window`）⇒ 要拿满新时长必须**再点一次授权**，别代点
  （授权只能从 8793 那一下来）。授权只在开跑那一刻校验一次，所以长回放可以跑过窗口到期时间。
- 回读判据用 `python3 -c "import ctl_auth as CA;print(CA.info())"` 的 `armed/left_s/window/epoch`；
  文件顶层的 `motion_armed` 字段可能不存在，别拿它当判据。

## 判「臂在不在动」要比较数字，不是比较输出行

两次采样把整行文本（含时间戳）直接比对会**永远判成"变了"**。要比 6 轴关节角或 TCP 的数值差：
静止时 `sqrt(Δmm) = 0.00`，一眼可判；再配合 `latest.json` 文件龄 ≤2s 才算「现在」。
