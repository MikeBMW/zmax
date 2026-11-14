---
name: ss-single-thread-debug
description: "Use when 单线程或断点调试状态空间(断点不进/decide不执行/停了还动)。先排除同步阻塞与已下发段。"
version: 1.0.0
author: Hermes Agent
license: private
metadata:
  hermes:
    tags: [zmax, state-space, debug, single-thread, vscode, trajectory]
    related_skills: [l2-node-signal-linkage, node-inspect-debugger, node-single-step-debug]
---

# 状态空间单线程 / 断点调试

## When to Use
- 断点打了却从不命中、`n_cycle` 一直是 0；
- 单线程/GUI 单线程档下引擎“一拍都跑不完”、界面卡；
- 按了停止或停在断点但机器人还在动；
- 轨迹 flow 一直打印“对齐到真机最近点”而一步不走；
- 出现 `SystemExit: 2` / “已有工程入口在运行”。

入口是 `src/lerobot/engineering/start.py`（持 `/tmp/zmax_start.lock`），它在同进程里 `import ss_canvas_loop as engine; engine.main()`。
周期循环在 `tools/ss_canvas_loop.py` 的 `while True:`（每拍 `prj.step(only=_run)`）。
`DispatchFSM.step()` **不在主循环里**，只在 `cognition.ActionModulator.advance()`（`cognition.py:403`）被推进一步 ——
所以 `scheduler_fsm.n_cycle` 只在调制器被调用时才涨，且只在状态迁移时落盘（`n_trans` 不变就别拿 n_cycle 判活，
要看 `zmax_data/ss_live/exec_state.json` 的 mtime）。

### 🔴 状态机住在调制器里，但真机链路原来根本没人推进它
`grep -rn '\.advance(' --include=*.py src tools` 的调用者只有 `verification/verification_layer.py`（单测）
和 `engine/sim.py`（仿真）；真机链 `safety_limit_impl.py` 只调 `mod.decide()`。
后果：`DispatchFSM.step()` 一次不跑 ⇒ `ss_fsm.json` 冻在某个 state（`n_cycle` 不动、`age` 一直涨），
**打在 `step()` 里的任何断点（含 `return self.state`）永不命中**，而 `decide()` 的断点照常进 —— 这组合极易误判成“断点坏了”。
判据：臂在走 / `decide()` 每次进，但 `ss_fsm.json` 的 state 与 `n_cycle` 半小时不变。
修法（已落地，离线实测 `n_cycle` 0→1→2）：
- `cognition.decide()` 开头每拍 `self.advance(contact_p, dist_h, d_xy, gripper=u_ff[3], depth,
  grasp_force, peg_z, peg_z_grasp, hole_z, placed, lifted, at_grasp_pose, dist_aoi)`，全部从 `meta` 取、整段 try/except。
- `safety_limit_impl.py` 调 `decide` 时把 `_SS_STATE` 里的几何/力证据打包成 `meta=` 传进去（否则 advance 拿到的全是 None，
  每次都走“证据不足”分支）。
断点选行（`scheduler_fsm.py`，**别打在 252 上**）：
- **181 `self.n_cycle += 1` = 唯一每拍必过**的行（真正的周期锚，调试首选）。
- 247 `return self.state` = 只在「证据不足 `target is None`」分支走；调试档把感知节点跳了，
  几何证据全 None ⇒ **每拍都从这里提前返回**。
- 252 `return self.state` = 只在「确认迁移」后 —— **证据为空时永远到不了**。
  用户坚持打 252 且“从不命中”时，先解释这三条出口（人话：他截的是到不了的那一站），再让他改打 181/247。
- 209 `return self.state` = 只在「夹持丢失回退」分支。

### 状态机为什么停在“接近”（证据链缺口）
`step()` 判迁移要 `dist_h / d_xy / depth / grasp_force / peg_z / hole_z`；调试档跳过 YOLO/2D→3D/AOI ⇒
这些键在 `_SS_STATE` 里根本不存在 ⇒ 永远“证据不足”。要它真走完 接近→对位→下降，
得从 `zmax_data/rokae_sdk/tcp_out/latest.json` 的真值算 `dist_h`（配孔位标定）喂进 `meta`，
而不是解开感知节点（那会把断点重新卡死）。

## 铁律: 单线程档会把异步节点变成同步阻塞

`ZMAX_SINGLE_THREAD=1` ⇒ `thread_policy.spawn_or_inline()` 当场执行，不起线程。
任何一次 HTTP/RPC/模型加载都会**卡住整拍** ⇒ 下游 `decide()` 轮不到 ⇒ 断点永不命中、`n_cycle=0`。
判定手段（不要猜）：

```bash
# 1) 找真调试进程: 别只靠 debugpy 的父子关系(launcher 的 child 会变、会查不到), 用 env 反查最稳
for p in $(ls /proc | grep -E '^[0-9]+$'); do E=/proc/$p/environ; [ -r "$E" ] || continue; \
  tr '\0' '\n' < $E 2>/dev/null | grep -qx 'ZMAX_ORCH=1' && \
  tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | grep -q 'engineering/start\.py' && echo $p; done | head -1
# 读别人的 /proc/*/environ 会 Permission denied ⇒ 必须先 [ -r ] 过滤, 否则整段循环报错中断
sudo py-spy dump --pid $CH | head -20      # 看卡在哪个 impl
```

已知会阻塞的节点（逐个实测）：`ss_llm_in` / `n_dsvl` / `ssvlm`（scene_vlm.urlopen，默认 60s）、
`ssaoi`（10082/10083 两个 HTTP）、`ssintact` 系（model_adapter._rpc）、`swds`（内部 `while+sleep(0.8)`）、
`ssdec`（Flow-Matching 动作头 `from_pretrained` 加载 SmolVLA 权重，C 层、最慢且调试器挂不住）。

固定解法（已落在 `tools/run_backend_start.sh`，调试档照抄）：

```bash
export ZMAX_SINGLE_THREAD=1
export ZMAX_AOI_OFF=1                 # ss_aoi._ensure_worker 直接不巡检
export ZMAX_SKIP_IDS="ssyolo,ssllm,ssreason,n_vlm_llm,n_dsvl,ss_l5,ss_seg,ssaoi,ssvlm,\
ssllm_in,ssintact,ssintact_dec,swintact,ss_lora_l4,ssmani_exp,ss_mem_l3,ssbg_vlm,ss_man,\
ss_mani_eng,ssmani_c,ssmani_p,n_calib_mani,n_geoplan,swds,swvideo,n_realscene,ssrender,\
ssdec,ss2d3d,ss_lora_l3"
export ZMAX_CORE_IDS="ssobs,sssensor,ssff,ssest,sspred,ssinnov,sssched,sslimit,ssact,sstactile,n_exec"
export ZMAX_FULL_EVERY=999999          # 不跑整张画布(否则第 0 拍就是全量, 照样卡)
```
权威真源是 `start.py::_debug_defaults()`（单线程档自动 setdefault 这套值），
这份 export 块只是给人看的口径——**别两处各维护一份再互相漂移**，改默认值只改代码。

### 两点容易踩空
- **`n_tick % FULL_EVERY == 0` 在第 0 拍恒成立** ⇒ 只设 CORE_IDS 不够，FULL_EVERY 必须一起放大，否则第一拍仍全量。
- **联网必须在 socket 层一次兜住**：节点各走各的路（`_vlm_ask_async` 只覆盖 VLM，L5 走 `l5_intent._call`，
  AOI 走自己的 HTTP，INTACT 走 `_rpc`），逐节点打补丁是打地鼠——补完一处，下一拍又从另一个节点卡满超时。
  正解（已落在 `start.py::_offline_guard()`，`main()` 第一步调用）：单线程档或 `ZMAX_LLM_OFF=1` 时把
  `socket.create_connection` / `socket.socket.connect` 换成**外网立即 OSError、环回放行**
  （`127.` `::1` `localhost` `0.0.0.0` —— 8793/8797 必须通），节点按“没值”降级，节拍照走。
  验收三条：外网 `0.0000s` 抛错、`urllib.request.urlopen` 抛 `URLError`、环回 `0.0001s` 通。要真联网显式 `ZMAX_LLM_ONLINE=1`。
  ⚠️ 白名单里**绝不能有空字符串**：`host.startswith("")` 恒真 ⇒ 所有主机都算本地，护栏静默失效（自测才发现）。
- **`spawn_or_inline` 再补一道标签闸**：单线程档对名称含 `l5_intent / vlm / llm / deepseek / openai / http / api`
  的后台任务直接跳过（返回 `None`，调用方按没值降级）并记账到 `thread_policy._STATE["skip_net"]`；
  非联网任务（如 `calc_ff`）照常当场执行。验收：跳过任务未执行、普通任务 `hit==[1]`。

## 排查第 0 步：先证“进程里跑的是新代码”
一个调试会话能连着跑几十分钟；用户在 VSCode 里按 F5 常常只是**继续**，不是重启 ⇒ 补丁全在磁盘上、
进程里仍是旧码，此时按原现象复诊全是白费（本类问题最常见的时间黑洞）。

```bash
ps -o etime= -p $CH                     # 进程年龄（$CH 见上面找真调试进程）
ls -l --time-style=+%H:%M <刚改的文件>   # 补丁时间
```
进程年龄 **小于** 补丁时间 ⇒ 旧码在跑。处置：`sudo kill -TERM $CH` 再 `-KILL` 关掉该会话，让用户重新 F5，
**不要在旧进程上继续找原因**；关之前确认执行器已无（见“杀容器”一节），并给一次位姿两拍静止证据。
每次改完代码，先核这一项，再谈 py-spy 栈。

## 断点不进的五类原因（按命中率）
0. **`ctl_auth.check()` 返回的是 tuple `(ok, msg)`，不是 dict** —— 答“谁在控制”时直接 `.get()` 会
   `AttributeError: 'tuple' object has no attribute 'get'`（`inspect.signature` 先看一眼，别凭记忆写报数脚本）。
   正确用法：`ok, msg = ctl_auth.check()` ⇒ `armed=True · 调试·无限 · epoch=264`。
1. 进程被卡在某个同步 IO 节点（上面）⇒ 用 py-spy 看栈，不要挪断点。
2. 会话其实**已经停在别处**（如 `start.py` 的 `hook()`，或已停在目标行本身）。
   `_do_wait_suspend → do_wait_suspend → <file>:<line>` 就是“**已命中并挂在该行**”的铁证 ——
   先出这个栈再谈别的。pydevd 报的行常是断点行的**上一行**（语句跨行/编译位置），停在 `N` 而红点在 `N+1`
   同样是命中，不要判成“没进”。此时用户说“没进”通常是编辑器打开的是另一份同名文件（仓库里有 3 份 `cognition.py`），
   让他点左侧「调用栈」第一条跳转；同时删掉多余红点、关掉 “Uncaught exceptions” 暂停，再 F5。
3. 卡在**模型权重加载的 C 层**：`_load_policy → from_pretrained → transformers init_weights`（torch C 扩展）。
   pydevd 只能在字节码层挂起，进程陷在 C 调用里时**既挂不住也命不中**，表现就是“臂在动、断点不进”。
   ⇒ `ssdec`（Flow-Matching Action Head / `n_dit`）连同 `ss2d3d`、`ss_lora_l3`、`ssmani_exp` 一起进 `ZMAX_SKIP_IDS`。
4. 行号漂移：在 `decide()` 入口插代码会让后面的行整段下移（`return u, f"阶段 {st}{tag}"` 曾是 573，插锚后是 587）。
   断点前先 `grep -n 'return u, f"阶段'` 拿真行号。
5. **这段代码根本不在你的 debuggee 里 / 不在当前链路上**（两种原因常同时成立，任一个都让红点永不命中）：
   ```bash
   grep -c '<模块名>' /proc/$CH/maps      # 0 = 该模块没被这个进程加载 ⇒ 断点无效（跑在 systemd 服务或 docker 容器里）
   awk 'NR<=<行号> && /^def /{n=NR; l=$0} END{print n": "l}' <文件>   # 该行所属函数, 再核它在不在当前链路
   ```
   已知案例：`exec/daemon.py:868` 跑在 l2_daemon（systemd 独立进程，`maps` 命中 0），且该行属于 `run_rot_chunks()`（只服务 J6 分段自转）⇒ 215 点轨迹这条链路根本不执行它。
   处置：先报“这两个原因”，再给**这条链路上**的正确落点（见 `references/breakpoint-sites-cheatsheet.md`），不要改配置
   硬试；要断服务进程的语句，也只能给它加旗标自停锚或把该服务单独跑在 debugpy 下（重启服务需用户点头）。

### 验证链会先撞你的断点（伪装成“主链卡死/死锁”）
`node_ss_feature`（`n_feature.py:91` → `shared_runtime.node_ss_feature`）原来**每拍**都
`new VerificationLayer()` + `v.engine()`，而 engine 内部跑完整 `StateSpaceSim` → `advance() → DispatchFSM.step()`。
后果：打在 `step()` / `advance()` 里的断点被这条**验证链**先停住，py-spy 栈长这样：
```
_do_wait_suspend → step (scheduler_fsm.py:251) → advance (cognition.py:403)
→ run (lerobot/engine/sim.py:569) → engine (verification_layer.py:168)
→ node_ss_feature (shared_runtime.py:4054) → compute (n_feature.py:91)
```
用户看到的是“卡住/主链没进”，实际是仿真链抢先命中。已加门闸：单线程档只首次汇总后复用 `_SS_STATE["verif"]`，
不再每拍跑仿真（`ZMAX_VERIFY_ONLINE=1` 可强制预热）。判据：栈里出现 `verification_layer.py` + `engine/sim.py`
就说明是它，不是主链。

## 「实际发出去的指令在哪一句」——四条链的文件:行
别答“在调制器里”，按语义给准确落点，并说明能不能打红点：

| 语义 | 位置 | 能否 VSCode 红点 |
|---|---|---|
| 轨迹点位真发控制器（现在跑的就是这条） | `tools/rokae/arm_step_traj.py:197` `x.MoveAbsJCommand(x.JointPosition([...]), speed, -1)` → `:64 r.moveAppend(...)` | ❌ 容器内；用旗标断点（见上节） |
| 派单（谁把点丢给 8797） | `real_traj_flow.py:250` `_post("/api/arm/step_traj", body)` | ✅ 锚点 `touch /tmp/zmax_stop_at_dispatch` |
| 每拍状态空间最终动作 | `cognition.py:587` `return u, f"阶段 {st}{tag}"` | ✅ |
| 每拍真发臂（绝对位姿/J6） | `exec/daemon.py:868` `ros2 service call /move_pose interfaces/srv/TargetPose ...` | ✅（另一进程，需单独 attach） |

关键认知：`robot_actuator_impl.py:9` 明写「只读真值/不造数/**不下发动作**」⇒ 状态空间的 `u` 只算不执行，
只写进 AR 链 `exec` 分区（`:104-108 ar_bridge.update`）。所以“u 算出来了”≠“臂收到了”。
夹爪：`tcp_ar_server.py:118 _grip_send()` → ssh 到 Orin 后 `ros2 service call /gripper_driver ...`，读 `/gripper_pos` 回证。

## 证据必须出现在**他的屏幕**上
文件日志、`ss_live/*.json`、py-spy 栈都**不算证据**——他只看 VSCode。原话：“你的证据没有用，我看着 vscode，没有变化”。
所以要么让进程**打印到他终端**（派单处已加 `print("📤 派单 n=… start=…")`），要么让**调试器真的停住**
（`debugpy.breakpoint()` / `pdb.set_trace()` 锚点）。文件类证据只能内部自用。
另：旗标文件断点不在他的调试进程里 ⇒ **VSCode 不会显示暂停**，必须提前说“停的是机器人不是代码”，
否则他会当成程序卡死；反过来，新建旗标会立刻停臂，**动手前要先告知**。

## 断点 ≠ 急停：已下发的段照跑
下发是**派单制**：`real_traj_flow` 每 3s `POST /api/arm/step_traj {n,start,speed}`，
8797 起一个 docker 容器跑 `/repo/arm_step_traj.py`，**独立进程逐点 MoveAbsJ 跑完整段**。

- 调试进程冻结 ⇒ 只是不再派新单；**在跑的那段继续走**，最多再走 `n` 个点。
- `arm_step_traj.py` 逐点**不复查授权**（文件头注释：由调用方先校验）⇒ **撤销授权也停不了在跑段**。
- 要立刻停：`sudo kill` 容器进程（普通 kill 无效）；要“断点即停”用 `ZMAX_TRAJ_CHUNK=1`（每段 1 点，最多多走 1 点）。
  ⚠️ `CHUNK` 的**优先级**：`start.py::_debug_defaults()` 是 `setdefault` ⇒ `launch.json` / `ZMAX.code-workspace` 里
  显式写的 `ZMAX_TRAJ_CHUNK=10` 会赢，你以为改了 1 实际仍是 10。改完必须回读 `/proc/<pid>/environ`，
  并在 8797 `/api/arm/step_traj/status` 里看 `n`：`n=1` 才算生效（`n=10` = 源配置没改到）。
  GUI 模板 `simulink_module._vscode_launch_cfg` 里已改成 `CHUNK=1 / SPEED=40`，但它只在下一次重写时生效。
- 停完用位姿真值验证静止：`zmax_data/rokae_sdk/tcp_out/latest.json` 的 `x/y/z` 两拍一致；8797 的 `running` 会滞后（陈旧标志）。

### 杀容器：别用 `pgrep -f` 配 kill，会杀掉自己的 shell
`pgrep -f 'docker run --rm --network host'` 会匹配到**当前 bash -c 的命令行本身** ⇒ `kill` 自己，命令无输出、看着像“没执行”。
用脚本遍历 `/proc/<pid>/cmdline`：跳过自身与祖先 pid、跳过 `/usr/bin/bash` 开头和含 `hermes-snap` 的，只认 `arm_step_traj.py`
（或 cmdline 同时含 `docker run` 与 `ZMAX_ROBOT_IP`）。

### 执行器跑在 docker 容器里 ⇒ VSCode 红点绑不上，用「旗标文件断点」
`tools/rokae/arm_step_traj.py` 由 `rokae_sdk_run.sh` 起的容器执行（`-v $SDK_DIR:/sdk`（rw）· `-v tools/rokae:/repo:ro`），
不接调试器 ⇒ 在它里面打 VSCode 红点、插 `debugpy.breakpoint()` 都没用。要停臂只能做成“旗标文件断点”：

- **位置**：旗标必须放**容器内可写、主机可见**的路径 —— 只有 `/sdk`（= 主机 `zmax_data/rokae_sdk/`）满足；`/repo` 是只读。
- **落点**：停在 `r.moveReset({})` / `MoveAbsJCommand` **之前**（这点指令还没发出 ⇒ 臂是真静止，不是“跑完这段才停”）；
  循环复检 2s、上限 3600s。
- **验收三条**：`traj_step_out.log` 出现 `{"stop_at_cmd": true, "i":…, "target_deg":…, "cur_deg":…, "max_jump_deg":…}`；
  位姿两拍完全一致；8797 `running=True` 但 `done` 不涨（段在等这一点）。
- **释放**：`rm zmax_data/rokae_sdk/stop_at_cmd`；要再停就重新 `touch`。每段都是**新容器**，所以改这个脚本后
  **下一段就生效**，不用重启任何服务/会话。
- **原则**：能停臂的“断点”必须落在**执行进程**内；下发方（调试进程）的断点只停派单。用户要“停在发指令那一刻”时，
  给的就是这个，不要拿 VSCode 红点忽悠。

### 僵尸 pid ⇒ 8797 永远判 busy（连 reset 都拒绝）
`docker run` 被杀后变 `Zs <defunct>`（父进程就是 8797，从不回收），而 busy 判据是 `os.kill(pid, 0)` ——
**僵尸对 signal 0 仍然“活着”**，于是每一段都回 `{"ok": false, "stage": "busy", "err": "上一轮真机逐点还在跑…"}`。
- 根治：判活时额外读 `/proc/<pid>/stat`，`rsplit(")",1)[1].split()[0] == "Z"` 按死处理（改完要重启 8797 才生效）。
- 不等重启的应急：把 `zmax_data/rokae_sdk/traj_step_state.json` 的 `running` 置 false、`pid` 置 0，再 `POST {"reset": true}` 归零游标（该文件每请求重读）。

## 游标死循环（实测 bug）
`real_traj_flow` 原逻辑对服务端游标只做 `max()`：一旦 flow 游标超前（如 99 vs 8797 的 69），
每轮发 `start=99` ⇒ 8797 判 `jump` ⇒ flow 发 `align` ⇒ 服务端仍 69 ⇒ **每 3s 空转，臂一步不动**。
修法：服务端游标回退时 flow 跟着退并清 `_post_cursor`；`align` 返回里用 `cursor` 同步。
现象特征：`traj_flow.json` 的 `last_msg` 停在“对齐到真机最近点: 游标已对齐到第 N 点”，而 8797 `done=0`。

## 单实例锁与 VSCode
- 锁只应由 `start.py` 持；GUI 看门狗拉起的从属引擎只探测并 0.5s 让位。
- 已有入口持锁时再 F5 会 `SystemExit: 2`（`start.py` 主动退出），不是代码错。
- `launch.json` 会被 GUI 模板重写 —— **每次 `studio.py` 启动都会重写一次**，不只是点「打开 VSCode」时：
  实测 16:19 重启 GUI 就把手加的 `ZMAX_AOI_OFF` / `ZMAX_SKIP_IDS` / `ZMAX_TRAJ_CHUNK=1` 全冲掉，
  16:21 的 F5 进程只剩 `ZMAX_SINGLE_THREAD=1` + `CHUNK=10` ⇒ 卡在 `ss_aoi._aoi_once` 打本机 10082/10083
  （环回放行，socket 护栏管不到）⇒ decide 不 tick、断点不进。
  ⇒ **别把手调 env 当正解**：调试档默认值写在 `start.py::_debug_defaults()`（`setdefault`，配置显式给了以配置为准；
  `main()` 第一步调用，早于 `import ss_canvas_loop`），并同步 GUI 模板 `simulink_module._vscode_launch_cfg`。
  验收：只给 `ZMAX_SINGLE_THREAD=1` 启动，控制台第一屏必须出现 `🧪 调试档自带默认 env: …` 和 `🔌 调试档离线护栏已开`。
  改配置文件后仍要 `Developer: Reload Window`，并用 `/proc/<pid>/environ` 核对，别信文件内容。
- 本机 HTTP（`127.0.0.1:10082/10083` 的 AOI）不受离线护栏约束 ⇒ 关它只能靠 `ZMAX_AOI_OFF=1`
  或 `ss_aoi._ensure_worker()` 里「单线程档自动关」（已加：单线程且无 `ZMAX_AOI_ONLINE=1` 就直接不巡检）。
- 无调试器想跑起来：`tools/run_backend_start.sh`（debugpy 监听 5678，可 attach）。

## 沟通口径：先答“谁在控制”，再给选项
> GUI 自己卡（点节点一顿一顿 / 翻页卡）与断点无关：那是 UI 线程里的同步子进程（`pgrep`/`du` 在点击路径上同步等），
> 判据与修法在 **skill `zmax-console`** 的「GUI 慢/卡顿」参考篇里；别拿 load/CPU 数字回他。
用户问“我停了怎么还动 / 到底是不是我在控制”时，按**三段边界 + 当下铁证**答，不铺架构史：
1. 授权（用户）：`ctl_auth.check()` 在**每段下发前**复查，撤销只能停下一段，停不了在跑段。
2. 下发方（调试进程）：断点冻结的只是它。
3. 执行方（8797 起的独立容器）：已派出去的单在走完之前不受任何一方影响。
紧跟一组实测：容器是否还在、位姿两拍是否一致、8797 `cursor/done`、`_do_wait_suspend` 所在的文件:行。
最后只给 A/B 两个可执行选项（缩 chunk / 加 stop 接口 + 逐点复查授权），让用户一句话选，别继续解释。

## 改 env 的纪律：一轮改齐，别一轮一个 F5
任何 `launch.json` / `ZMAX.code-workspace` 的 env 改动**都要 Reload + F5 才进进程**；
改完用 `/proc/<pid>/environ` 核对而不是信配置文件。用户每按一次 F5 都是成本，
“改一处、让他再按一次”连做两轮就会直接炸（“都这么多遍了”）。所以每轮收工前问一句：
**这一改能不能让同类阻塞不再可能？** 能才叫改完，否则下一拍又从另一个节点卡住。
优先顺序：代码级兜底（socket 离线护栏 / 标签闸）> 跳过表 `ZMAX_SKIP_IDS` > 单节点补丁。
催“快点/又不动/能不能修好”时，回复只要三块：一行现状数字（进程年龄 / 卡在哪一行 / 臂两拍位姿）、
一个要用户按的键、改完哪一处；不铺排查过程、不列备选方案。
