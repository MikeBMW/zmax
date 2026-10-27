---
name: trajectory-loop-execution
description: "Use when 要让一条多段轨迹「点一次全走完」(规划→一次性下发→真值取证), 或出现只走一段/段间被拦。"
version: 1.0.0
author: hermes-agent
license: proprietary
tags: [robot, trajectory, fifo, safety-gate, forensics]
platforms: [linux]
metadata:
  hermes:
    tags: [robot, trajectory, fifo, safety-gate, forensics]
    related_skills: [real-arm-motion-control, robot-pose-truth-chain, dispatch-chain-integrity]
---

# 多段轨迹闭环：规划 → 一次性下发 → 真值取证

## When to Use
- 用户要「1 2 3 4 步一次性发过去、点执行就全执行、中间不能停顿」或提到「执行轨迹 / 旁路控制」
- 轨迹点下去**只走了一段**、段间卡住，或报 `起点已变 Nmm > 5mm`
- 要回答“这条轨迹是不是运动规划器给的”，或重规划后形状变了要解释
- 改 `traj_plan.py` / `traj_exec.py` / `/api/traj/*` 任一环

现场要求形如「1 2 3 4 步一次性发到运动节点，点执行就全执行，中间不停顿」。
这里只讲这条链的执行语义和取证；单步/多阶段技能的守卫与授权见 `real-arm-motion-control`，
位姿真值来源分级见 `robot-pose-truth-chain`。

## 数据流（唯一执行收口不变，不新开写入口）

```
traj_plan.py → zmax_data/runtime/traj/plan.json   （tcp0_mm 起点 + 段表 + 预检结果）
traj_exec.py → 一次性写 N 行 JSON 进 l2_daemon FIFO（不逐段等位）
l2_daemon    → 唯一执行收口（授权 / 守卫 / 安全闸都在它这一层）
```

FIFO 一行一条：`{"skill":"L2.lift","d_mm":60,"auth_epoch":N,"src":"traj_exec","note":"..."}`。

## 下发：全部段一次写完，然后只观察

```python
with open(FIFO, "w", encoding="utf-8") as f:
    for s in segs:
        f.write(json.dumps({"skill": s["skill"], "d_mm": float(s["d_mm"]),
                            "auth_epoch": epoch, "src": "traj_exec"}, ensure_ascii=False) + "\n")
        f.flush()
        time.sleep(0.12)      # 只为给 FIFO 读端呼吸，不是等位
```

写完后**不再由脚本决定节奏**：只轮询真值记每段残差，用于汇报/取证。
「发第 1 段 → 等到位 → 再发第 2 段」在慢速真机上等于每段之间停十几秒，不是用户要的。

## 到位判据：只认控制器真值，**绝不等执行器的 phase**

执行器可能把动作真做完（日志已有 `ROS: response: TargetPose_Response(...)`、臂已到位），
而 `exec_state.json` 的 `phase` 一直停在 `accepted` 永不写 `done` —— 它靠**日志文本匹配**推进状态机，
某类技能的收尾行不匹配任何规则。上层若等 `phase==done` 就永远等不到，卡死在段间。

```python
_q, _tcp, _age = read_joints()          # 控制器直出，见 robot-pose-truth-chain
if dist(_tcp, to_mm) <= ARRIVE_TOL_MM and _age <= 5.0:   # ARRIVE_TOL_MM = 8.0
    ...
```

`phase` 只用来读 `blocked`（被闸拦 ⇒ 立即中止余下所有段），**不用来判到位**。

## 执行前的四道闸（都 fail-closed，缺一条别发）

1. **规划新鲜度**：`age > PLAN_MAX_AGE(30min)` 拒发 —— 位姿早就变了，轨迹含义已变。
2. **预检**：`plan.precheck.ok` 必须 True 并报最差净空；**拿不到实时真值就拒检**，绝不用旧位姿算净空。
3. **起点闸**：`|当前TCP − plan.tcp0_mm| > 5mm` ⇒ 拒发「这条相对段轨迹含义已变」。
   🔴 **只在第一段之前校验一次**。段间再拿「规划起点」比对，等于把自己走完第一段的正常位移
   判成「人手挪过臂」⇒ 第 2 段必被拦（日志 `起点已变 Nmm > 5mm`，现场看到的就是“只走了第一段”）。
   段间要校验就校验「当前 ≈ 上一段目标」的容差。
4. **执行锁**：`fcntl.flock(LOCK_EX|LOCK_NB)`，第二个实例直接拒。
   两个执行器并发会把两条轨迹交替写进同一条 FIFO，在途指令互相覆盖目标位姿。

## 命名轨迹(现成点列) → 可执行段表: 高亮的那条必须就是真执行的那条

触发: 页面上有一组「轨迹按钮」(命名轨迹/建图路径/历史路径), 用户说「点高亮 → 在三维里看着 → 点执行就发指令」。

- 🔴 **先核「看的」与「执行的」是不是同一份真源**: 『▶ 执行』通常读**规划航路**(`planned_traj.json`, traj_plan 产物),
  而轨迹按钮读的是 `/api/traj/named` 这类**另一份点列** ⇒ 看着 A、执行 B, 而确认框只写"执行这条轨迹"。
  判据 = 打开执行端点/执行器处理函数, 看它 `open()` 的文件或 fetch 的接口, 与按钮的数据源逐字比对。
- 转换管线(形态: `tools/traj_from_named.py`):
  1. 取点列(**米**) → **先统一单位再抽稀**: `rdp([[v*1000 for v in p] …], tol_mm)`。
     直接 `rdp(pts_m, 5.0)` 等于拿 5 **米**当容差 ⇒ 120mm 的方框整条被抽成一个点,
     报「轨迹全部点与当前 TCP 重合」(看着像数据错, 其实是单位错)。
  2. 骨架点之间拆**轴对齐段**: 先 Z、再 X、再 Y; 单段 ≤ registry 上限(300mm); <0.5mm 的轴差丢弃或并入上一段。
     副作用要主动说清: 斜线会被执行成**阶梯**, 与画出来那条直线不完全重合。
  3. **起点闸**: 当前 TCP 距轨迹首点 ≤20mm(命名轨迹口径; 相对段轨迹那套是 5mm), 否则拒绝并回「差 N mm」。
     去起点的移动是**另一次运动**, 不许混进这条轨迹里。
     \u4f8b外(仅限**覆盖扫描类**: 建图/巡检): 用 `--lead-in` 把「TCP→首点」也拆成轴对齐段写进同一份段表,
     段表起点=当前 TCP ⇒ 起点闸自然过, 不用让用户先手动去起点; 代价是段数变多(三行扫描≈12 段),
     所以**远端执行器的收包上限要同步放宽**(实测 8 → 24), 否则发布出去被静默丢弃、只看到"发放出去了没动"。
  4. 逐点净空预检(复用 `traj_plan.precheck_point`, ≥20mm), 不过就**不写段表**。
     🔴 净空是以**围栏盒(AABB) + margin** 为基准算的, 不是相对工件表面 —— 实测「模块顶面上方 50mm」
     只算出 **17.9mm**(料盘盒顶 140 + margin 10 = 150; 168−150 = 18)，抬到 172 才 21.9mm 过线。
     ⇒ 用户说「停在上方 N 厘米」时, 先按围栏盒口径反算高度, 别按工件表面算(否则预检必 FAIL 而数看着很宽裕)。
  5. 写两份: `planned_traj.json`(执行器读) + `plan_latest.json`(远端桥读, 带 `start_mm`), 再画到 overlay。
- 🔴 **三维里画的那条 ≠ 执行的那条；最常见的错源是 `zmax_data/ar_rs/fences.json` 里 `type=points` 的轨迹**：
  它只是可视化（不参与 `check_point` 避让，所以不会自我阻挡），而执行链只读
  `zmax_data/runtime/traj/planned_traj.json`。于是「AR 里明明有一条线 → 点执行 → 臂不动」的真因是
  **那条线从来没进过执行链**，页面也不会报错。
  判据 = 打开 `/api/traj/exec` 的处理函数，看它 `open()` 哪个文件，与画线的数据源逐字比对。
  要让用户能执行，必须拿同一份点列走下面的转换管线写出 `planned_traj.json`（并把 3D 那条同步成同一份点列，
  否则"画的和跑的不是一条"）。
- **不可执行的来源默认拒绝并给理由**: 栅格/示意坐标(2D 栅格平移到台面的建图路径)、"已走过的记录"(实时轨迹)。
  留 `--force` 口子, 但拒绝理由要出现在**用户点按钮的那一面**。
- 服务端收 `{k: <轨迹名>}`: 先跑转换脚本 → 失败时把脚本 stdout 里 `⛔` 那行**原文**回页面
  (起点闸 / 预检不过 / 不可执行 三种原因, 用户必须能分辨), 成功再走原执行闸。
- **零运动自检**(拿到真机前必跑): `--self-test` 用**当前 TCP** 生成的闭环方框点(首点必须等于当前 TCP,
  否则会被起点闸挡, 那是设计如此)走同一条数学, 断言 段数 / 总长 / 预检 PASS / 闭环误差 ≈0。

## 场景段表(几百段/多件) → 550C plan 序列: 先切、再补空走、再算节拍

大场景(整盘插拔 / 摆盘 / UPH 全流程, 实测一份 392 段 / 14 件 / 8 批)不能整份下发 ——
550C 的载荷闸硬限 `n_seg` 1..8。切分 + 校验有现成工具:

```bash
./gui-venv311/bin/python tools/scene_550_planify.py                       # 切 plan + 补空走 + 跑离线闸门
./gui-venv311/bin/python tools/scene_550_planify.py --no-bridge           # 对照: 不补(段内连续必 ❌)
./gui-venv311/bin/python tools/scene_550_planify.py --bridge-speed 300    # 看节拍随空走速度的变化
```

产物 `zmax_data/runtime/traj/plan_550c/`: `index.json`(逐项判据 + 两个节拍口径) + 每 plan 一个 json。
纯离线, 不下发、零运动。

- 🔴 **换槽处的 `a` 是「中转位」, 不是上一段末端**: 场景段表每换槽就把下一段起点写成同一个中转位
  (实测 27 处, 与上一段末端差 400~570mm) ⇒ 照 `abs_mm` 直发就是一条穿过工装的 400mm+ 大直线。
  必须显式补 bridge 段; 判据 = 段内 `a[i]==b[i-1]` 与 plan 间「上末点==下起点」都 ≤0.5mm。
- 🔴 **节拍只能按含空走的口径报**: 场景 json 的 `total_t` **不含**换槽空走。同一场景实测:
  自报 316 → 空走 100mm/s 时 163 → 300mm/s 时 241 → 顶到运动安全上限 1000mm/s 仍只有 289。
  **空走顶到上限还差, 就不是调参问题, 而是要并行工位**(另一条臂承担上下料/周转, 把空走藏进对方插拔时间里);
  这个结论要连对照表一起给, 不写"再优化一下"。
- **plan 数 = 下发次数 × 每次闸门开销**: 419 段 = 53 个 plan, 每次都要过授权/幂等/逐段真值对账,
  按 200ms/次往返 ≈ 10.6s —— 对「300UPH = 12s/件」的预算已是全部余量。要提节拍, 先减执行臂那一条链的段数
  (只让它做插拔), 而不是盲目缩短空走; 放宽分段上限属于改安全闸, 要人点头。
- 切 plan 只解决"能不能发", **不改变"谁下发/到没到位"**: 仍按本技能的闸门与真值口径取证。

字段定义、补空走算法、完整节拍对照表、下发次数换算: 见 `references/scene-plan-splitting.md`。

## 连续性：分段口径 vs 控制器队列(真连续)

**分段发 `/move_pose`(`TargetPose`) 没有 blend 可言** —— 请求字段只有 `speed` + `joint_state`，
每条被控制器当成独立点到点运动，走到位停住再接下一段 ⇒ 软件层零等待，**拐点仍有一次停稳**
（实测每段 ~0.67s：4 段 280mm @60mm/s 合计 **7.32s**，而纯行程只 4.7s）。

要机器人层面真连续，只有一条路：**把多点 append 进 SDK 的命令队列，只 start 一次**。
xCoreSDK 上实测可行的调用形态（Orin 的 `zmax_arm_sdk_bridge` 已长出一个 `/path` 路由做这件事）：

```
setDefaultSpeed(speed, ec) · setDefaultZone(zone_mm, ec) · setDefaultConfOpt(False, ec) · moveReset(ec)
for each 目标点:  cp = x.CartesianPosition([x,y,z], rpy)
                  mc = x.MoveLCommand(cp, speed, -1)          # -1 = 用默认 zone
                  r.moveAppend(mc, x.PyString(cmd_id), ec)     # 逐点 append, 不 start
r.moveStart(ec)                                                # 只 start 一次 ⇒ 段间按 zone 圆滑过渡
```

- `zone=0` 等于段段精确停车（失去连续收益）；矩形闭环 **5mm** 够用。`moveStart` **不阻塞**，
  所以「到位」仍要自己轮询真值（到末点 ≤2mm 且 `jointVel<0.02`）。
- 提速是两根**独立**杠杆：①速度 60→200mm/s（规划段口径 150~300，控制器允许到 1000）
  ②从分段改连续。只提速度不改形态，一半时间仍花在停稳上。
- 增量点语义：`/path` 的 `points` 是**相对起点的累加增量(mm)**，不是绝对坐标 —— 先把段表换算成增量，
  再靠 dry 预演把每个目标点与规划点逐点对账（≤0.5mm）才允许真发。
- 状态要诚实：连续形态目前只做到 **dry 目标点已对账**（与规划 5 点逐点一致），真跑耗时**未实测**；
  在实测出数前，汇报里只能给「预期 ~2.0~2.5s（280mm/200mm/s + 加减速）」，不能说成已验证。

## 下发前的第 0 道闸：授权窗（现查，不自补）

派发任何真动前先读授权真源 `tools/ctl_auth.py::info()`：`armed` / `left_s` / `epoch`（默认窗口 900s）。

- `armed=False`（自然到期或已撤销）⇒ **停手，请现场在 8793 重新授权**。绝不自己写授权文件、
  绝不复用上一轮的 `epoch` 顶上去 —— 授权只能来自现场那一个入口。
- 用户口头上说「执行完 / 继续跑」时，**先读 `info()['events']`**：现场往往已经点过页面授权
  （note 形如「页面两步确认(现场安全)」）。已经 `armed=True` 就**只触发执行，不要重复 grant** ——
  重复签发会抬 `epoch`，把在途/排队的命令判成过期作废。
- 窗口短于计划耗时（多段/连续都算）就先算耗时再决定跑不跑；跑到一半过期，后续段一律被拦。
- 取证时把 `epoch` 与剩余秒数一并记进执行台账，事后能对上「这次是谁、哪一次授权」放行的。

## 🔴🔴 探真动端点 = 真动: 不要为了"看它返回什么"去 POST 真实载荷

`POST /api/traj/exec {k}`、`POST /ctl/move {arm:1}`、桥 `POST /move_pose {dry:false}` —— **这些请求本身就是下发**。
只因想去确认"过期授权会不会被拒"、而现场恰好刚授权过 ⇒ 那段轨迹真的跑了起来，之后只能对用户说"这几步是我触发的"。
要验口径只看三条：① 读代码/日志；② `dry:true` / `arm:0` 空跑；③ 发一份**故意非法**的载荷让它必被闸拒
（`auth_remaining=0` + `start_mm` 离当前 TCP 几百 mm + 1mm 单段，三重保险）—— 既有信息量又零运动。

## 中止路径的健壮性: 失败原因比"停下来"更容易丢

现场表现 = 「只走了两段就停了，页面也不报错」。真因往往不在运动，而在**失败分支自己崩了**:

1. **失败台账必须在刹车之前写**。写成 `bridge("/stop")` → `ledger({ev:"seg_fail"})` ⇒ stop 一抛异常，
   那句失败原因永远不落盘，事后只能看到"上一个 plan 的最后一条 seg_ok"，看起来像跑了一半就消失。
   顺序固定：`ledger(失败原因, 带桥返回的 ec/why) → try: stop() → state(phase="aborted")`。
2. **安全停止调用必须被 try 包住**。`/stop` 是异常路径里最脆弱的一环（见下条），它一抛就把调用方打死 ——
   而"停下来"这件事本身已经执行了（`moveAppend`+`moveStart` 是阻塞前的异步下发，臂会自己走到位）。
3. **常驻订阅进程顶层要兜异常**：`try: execute(note) except: ledger({ev:"crash", tb}) + state(phase="error")`。
   不兜的后果是 systemd 重启后 `state` 回到 `idle`，现场看到的只是"没报错、就是不动了"。
4. **SDK 桥的 stop 接口签名**（Orin `zmax_arm_sdk_bridge.py`）：`stopMove()` / `moveReset()` 裸调会
   `TypeError: incompatible function arguments` ⇒ HTTP 500。逐个带 `ec` 字典试
   `stopMove(ec) → moveStop(ec) → moveReset(ec) → moveClear(ec)`，任一 `ec==0` 即停，
   **任何异常都返回 200 + {note, ec, err}**，永不把 500 抛给调用方。
   ⚠️ **`/reset` 与 `/stop` 同病**：只修 stop 不够 —— 下一次调 `/reset` 又 `TypeError` → 500 → 执行器再死一遍。
   两个路由都要逐个带 `ec` 试 + 恒返 200；改完用 `curl -X POST .../reset -d '{}'` 回读 `ec.ec==0` 才算生效。
   同一把钥匙也适用于所有路由里的裸 SDK 调用(`moveReset/stopMove/moveClear`): 签名都是 `(ec)`。
   ⚠️ 桥上在跑的文件常比仓库副本新（实测在 `~/.zmax/arm/`，`do_move` 已带 `ok/why`；仓库版没有 ⇒
   调用方 `if not res.get("ok")` 会把每次成功下发判成失败）。改桥前先 `ps -eo pid,cmd | grep arm_sdk_bridge`。

## 🔴 `ok=true` + 所有 ec=0，但臂一格不动 —— 三个病因要分开判 (按这个顺序查)

桥回 `moveAppend_ec.ec=0` / `moveStart_ec.ec=0`，等 25s 零位移。不是通信、不是授权、不是起点闸：

| 病因 | 实测判据 | 修法 |
|---|---|---|
| **单段太长** | 222mm 一条 MoveL: 25s 零位移; **同一位置拆 100mm 立刻正常** | 覆盖扫描/长直线一律拆 ≤100mm(`--seg-max 100`)，不要用 registry 的 300mm 上限当计划值 |
| **目标不可达(超工作空间)** | 控制器对不可达目标同样 ec=0 静默丢弃; 沿轴二分定边(实测 y=−200/z=230 上 x=442 动、x=432 不动) | 工作区下限取**实测边界**并留余量，不要用图纸/标称行程 |
| **上一条未收尾** | seg1 报到位后立刻发 seg2 ⇒ moveStart 报错或空跑 | 下发前等真静止: `max\|jointVel\|<0.05` **且连续两次位置变化 <0.1mm**(速度会瞬时归零，只看速度不够); 失败 0.3s 后重试一次; append/start 两个 ec 都写进台账 |

- 台账字段要**分开放** `append_ec` / `start_ec`；写成 `x or y` 会把有值那个吞掉，事后看不到真正报错的是哪个。
- 断点/边界探测一律**小步 + 每步读 `endInRef`**：动了再加量，不动就不要猜阈值。

## 🔴 `moveStart 报错`（硬报错）—— 先读机器人**模式/上电**，别从轨迹找原因

桥 `GET /status` 就带着答案的两个字段：`operateMode`（`OperateMode.manual` / `automatic`）与
`powerState`（`PowerState.on` / `off`）。**这两个字段不读，就会一路去查轨迹/授权/速度/段长，全是空转。**

- 实测症状链（每一环都正常，最后还是不动）：FIFO 收到 → 段表 1 段 → VL 安全闸放行 → bridge 腿下发
  → `moveStart 报错`。真因是 `operateMode=OperateMode.manual` + `powerState=PowerState.off`
  ⇒ 控制器必然拒，与轨迹参数、速度档位、授权都无关。
- **判据顺序固定**：① `GET /status` 读 `operateMode` / `powerState`；② `POST /move_pose {dry:true}`
  看 `result.plan.delta_mm` 是否正好等于要走的位移（dry 只算不下发，零运动）；③ 两者都正常，才去查段长 /
  可达性 / 控制器队列残留。反过来查会把"状态没上电"误判成"轨迹算错"。
- 现场动作（servo 上电、manual→automatic）**必须由人在现场做**：不要代做，也不要试 `moveEnable` 一类旁路。
  做完重发同一条即可，**规划不用重算**（起点闸、预检都还是过的）。
- 执行失败时把这两个值写进台账：光写"控制器拒发"没有信息量，写 `operateMode/powerState` 才可复现。
- 机器人"上次能走、这次同一个点不走"时优先怀疑这个：上电/模式是被别处（急停、重启、别人手动）改掉的，
  而轨迹文件、授权窗、段表可能全都还是好的。

## 诊断「怎么只执行了一段」（按这个顺序，别猜）

1. `zmax_data/runtime/traj/exec_stdout.log` 尾：有 `已下发 L2.xxx` = 真发出去了；
   有 `🛑 起点已变` = 段间被起点闸拦。
   🔴 **先把 `blocked_by` 那个数算一遍**: 若它 ≈ `|当前TCP − plan.tcp0_mm|`（整条轨迹的**起点**），
   而不是「上段目标」，就证明执行器在拿**规划起点**比**已走完前半程的当前位姿** —— 是判据口径错，臂没被人动过。
   实测 9 段走完 7 段后报 `起点已变 336.4mm`，正好等于起始点(347,353,260)到当时真值(647,206,300)的距离。
   ⇒ 处置：**不重发原段表**（重发 = 叠加第二条轨迹），也**不从原起点重规划**；按当前真值单独规划「剩余那一截」
   （起点闸天然通过），汇报时分开说「前 N 段已到位 / 后 M 段因判据口径被拦」。
2. `exec_state.json` 的 `phase`/`skill`/`t`：停在 `accepted` 不推进 = 状态机不写 done。
3. 执行进程是否还在：`/proc/<pid>/wchan` = `hrtimer_nanosleep` + `State: S` = 在 sleep 轮询一个永不来的条件。
4. 真值是否已到第一段目标：到了就证明**动作成功、问题在判定不在下发**。
5. **下发方是 550C 时换三条证据源**：`plan_exec_state.json`（`phase` / `seg` / `last` / `resid_mm`）、
   `plan_exec_550c.jsonl` 台账（`seg_ok` / `seg_fail` / `reject` / `crash`）、Orin 桥 `GET /status` 的 `endInRef`。
   **先读桥的 `/status` 对一下臂到底在哪**：若它已经停在第 N 段的目标点上，那结论是"动了但被判失败"，
   绝不能再发一次（重发 = 叠加第二条轨迹）。实测该情形：seg1 落账 `resid 0.28mm`，seg2 的 ok=false 触发
   `/stop` → 500 → 执行器崩，臂其实已停在 seg2 目标点。
6. **判"慢"之前先分段量 RTT**：客户端→桥 `/status` 的分位（实测 550B→Orin 7~10ms、550C→Orin 5~7ms、ping 1.8ms），
   段本身耗时（实测 60mm / 0.9s 含加减速）。两者都正常而现场感觉"卡很久" ⇒ 慢在那段**进程已死、状态文件被重启清零**
   的空窗，页面在这段时间什么都不更新；把这层讲出来，别去改网络。

## 汇报口径：两条必须分开说

- **「指令由谁发出」要说准**: 脚本在 Orin 上直打 SDK 桥 与 「550C 的 plan 节点下发」是两件不同的事。
  plan 节点若还是 plan-only，就只能说“规划在 550B、执行由我在 Orin 上直发”，不能说成“550C 在执行”。
- **时间要拆成两段**: ①动作耗时（真值实测秒数）②被阻塞的时间（无产线路由、桥的真下发报错、跳板抖）。
  两者的修法完全不同；混成一句“跑了很久”，现场只会追问“都规划好了怎么还这么久”。

## 坑

- 🔴 **经跳板跑动作脚本一律脱会话**: 长命令随时被跳板掐断，**当场被掐的表现是「日志空/没输出」**，
  极易误判成脚本失败而白等一轮。用 `setsid nohup python3 -u <script> > /tmp/<name>.log 2>&1 </dev/null &` 起，
  再轮询日志（`stat -c %s` 在长 + `tail` 有新行）确认真在跑；不要用一条长 ssh 扛着动作命令。
  被杀后先读真值确认臂在哪，别急着重发（重发 = 叠加第二条轨迹）。
- 🔴 **桥的 `dry=false` 自己会 500 时，dry 对账通过也不代表能发**: 老桥的 `moveAppend(list, speed, True, ref, {})`
  在本 SDK 里是**不存在的重载**（`TypeError: incompatible function arguments`），dry 只算目标所以一切正常。
  真下层只认 `moveAppend(cmd, PyString(cmdID), ec)`。改完必须 `compile → restart → curl /health 回读 sdk:true` 三步才算生效。
- 🔴 **别用 `pkill -f traj_exec.py` 收尾**：自己的命令行含同一串 ⇒ SIGKILL 掉整个 shell，后续步骤全不执行。
  按 `/proc/<pid>/cmdline` 精确匹配，或把模式串写进脚本文件再执行。
  ⚠️ **跨机(`ssh host '… pgrep -f <脚本名> …'`)同病且更难认**: 远端 shell 的命令行就是整串 ssh 命令,
  它自己含那个模式 ⇒ 杀掉自己 ⇒ **ssh 返回 255 、一行输出都没有**, 看起来像"网断了/主机不可达"。
  判据: 单独跑一句 `ssh host 'echo alive'` 通就是自杀不是断网。定式 = **方括号法** `pgrep -f 'map_record[e]r_550c'`
  (正则自己不会匹配到自己的字面串), 或先 `echo $$` 记 pid 再排除它。
- 🔴 **页面/API 里的执行状态是上一次失败留下的**：`traj_state.json` 可能是几小时前某个 `blocked`，
  用户看到的是那行旧文案。报原因前先看它的 mtime，别把旧 `blocked_by` 当本次病因。
- 🔴 **规划脚本每次按当前 TCP 重算** ⇒ 臂移动过后形状/位置必然变。用户问「怎么跟之前不一样了」时，
  先答“起点变了多少、是不是上一份是续走版”，再谈重规划；别拿新图去解释旧图。
- 轨迹是**直线段拼接 + 净空采样**，不是运动规划器输出。被问「是不是规划出来的」要直说不是；
  真规划要起 MoveIt 容器后把两条线同画对比。
