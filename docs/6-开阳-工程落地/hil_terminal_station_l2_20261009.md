# HIL 终端接口 · station 进旁路 · station→规划→L2 架构设计（2026-10-09）

老倪要求原文：
> 新版本状态空间工程的人机在环节点，要有当前的终端的接口，即，我可以通过当前的静静，遥控人机在环节点。
> `hil_bridge.py — 🙋 HIL 人机在环桥 (状态空间状态 → ECS web; 人的指示 → 回灌工程)`
> 你来设计接口；我会运行 L5 功能，你自动连接人机在环节点，代码要明确写进去；
> `http://10.163.146.78:8793/station` 这个服务，要写进 旁路实时可视化 节点，你设计接口，
> 这样，我在 station 操作这些点的时候，可以直接调用 状态空间 的路径规划能力，这接输出 L2 的功能；
> L2 规划能力，是 moveit 节点 规划的，你来设计架构，更新代码逻辑。

---

## 0. 铁律（本设计不越过的线）

1. **上层只给意图/条件；执行永远由 L2 收口**（老倪架构原则，长期有效）。
2. **规划只规划、绝不动臂**：状态空间的 MoveIt 是 `plan_only.launch.py` 起的 move_group，
   `allow_trajectory_execution=False` ⇒ 规划链路**在构造上不可能**让机器人运动。
   任何"从 station 直接下发"的实现都属于违规。
3. **动作只从 8793 出**：所有真机动作仍走 `l2_daemon`（8793 `/ctl/move`），
   并保留全部既有守卫：授权窗 `auth.armed` · 包络 env_model · 爬升 ≤100mm · 防连点 1.5s ·
   30s 超时 · **抬升需警报服务在线** · 危险点/新点位老倪先做。
4. **不可用即如实报**：规划/引擎不可用时返回 `ok:false` 与原因，不编造计划，不静默降级。

---

## 1. 组件与真实落点（都在仓库里，非新造）

| 角色 | 文件 / 端点 | 现状 |
|---|---|---|
| HIL 大脑 | `src/lerobot/policies/left_right/state_space/hil_bridge.py` | `build_snapshot()` / `handle_instruction(text, snap)` / `_append_instruction()` / `poll_instructions()` / `publish_once()`；`REPORTS` 落盘 |
| HIL 本地 API | `tools/hil_local_api.py`（0.0.0.0:**8795**） | `GET /hil/state`、`POST /hil/say`、`/hil/pause`；与画布 n_hil 节点、datadrive hil.html **同一个大脑** |
| 画布 HIL 节点 | `tools/gui/studio.py` 的 `n_hil`（v5.15.36 起） | 手机现场页 `room.html` 也直连 8795 |
| station 服务 | `tools/cam_live_stream.py`（`--station-port`，**8793**） | `_station_page()` → `tools/web/station.html`；`/station`、`/station/status`、`/ctl/*` |
| 旁路可视化节点 | `tools/gui/ss_bypass_view.py:383` `class SSBypassView` | 数据源 `~/zmax/zmax_data/ss_live/`、`~/zmax/zmax_data/ss_bypass/`；`simulink_module.py:11718` 按 `kind=="bypass"` 实例化 |
| 规划能力（MoveIt） | `tools/moveit_plan_req.py`（宿主写请求）→ `~/zmax/zmax_data/runtime/moveit_plan/plan_req.json` → 容器内 `tools/moveit_plan_live.py` → `live_plan.jsonl` / `live_plan_latest.json` | **只规划**；`tools/moveit_plan_only.py` 为 plan-only 客户端（`--group arm --out ...`） |
| L5 视觉语言 | `left_right/state_space/scene_vlm.py :: SceneVLM`；编排 `tools/l5_hil_agent.py` | L5 运行时要**自动连接** HIL 节点 |

---

## 2. 接口设计 A：终端（静静/Hermes）↔ HIL 人机在环节点

### 2.1 为什么是这个形状
终端代理需要三件事：**便宜的一次读**、**带裁决的写**、**可审计的流水**。
因此不做"新一套 HIL"，而是在 `hil_local_api.py`（同一个大脑）上加一组 `/hil/term/*`，
token 门控（本机/局域网），与画布节点共享同一份状态与同一套红线。

### 2.2 端点

```
GET  /hil/term/state
     → 200 {
         ok: true, ts, stage, frame_age_s,
         layers: {L2:"active", L3:"active", L4:"offline", L5:"active"},
         canvas: {nodes, edges}, paused: bool,
         peers: [{name:"L5", kind:"scene_vlm", pid, age_s, note}, ...],
         last_instructions: [{seq, t, from, text, verdict}... 最近5条],
         verbs: ["状态","停","继续","看画面","标注","去<点>","计划<点>"],
         hint: "一行中文现状(给终端直接念给用户)"
       }

POST /hil/term/say        {"text": "...", "from": "hermes", "seq": 0}
     → 200 { ok:true, verdict, reply, seq, wrote_to:"reports/hil_instructions.jsonl" }
     ⇒ 服务端原样调用 HB.handle_instruction(text, snap)  —— 与画布节点/手机页同一条路径

GET  /hil/term/log?n=20   → 最近 N 条指示（读 same jsonl）
POST /hil/term/peer       {"name":"L5","kind":"scene_vlm","pid":123,"note":"..."}   ← L5 自动调用
GET  /hil/term/peers      → 在线 peer（age_s 超过 TTL 视为离线）
```

### 2.3 鉴权
- 头 `X-Zmax-Term: <token>`；token 存 `zmax_data/secrets/hil_term.token`（首次启动自动生成 32B hex，0600）。
- 仅允许回环 + 局域网网段（`192.168.23.*`、`10.163.146.*`）；其它来源 403。
- 未带 token ⇒ 403 且**不改任何状态**（与"动作需授权"同一条哲学）。

### 2.4 红线
- `/hil/term/say` **绝不代发真机动作**；动作类指示一律 `verdict=refused_motion`（沿用大脑现有红线），
  只登记待授权 + 落台账。

---

## 3. 接口设计 B：L5 运行时"自动连接人机在环节点"

- 新增 `hil_bridge.register_peer(name, kind, pid=None, note="")` / `peers_alive(ttl=30)`，
  落盘 `zmax_data/ss_bypass/hil_peers.json`（追加式、原子写）。
- `tools/l5_hil_agent.py`：**启动时 + 每轮循环**调用 `register_peer("L5","scene_vlm",...)`，
  并在日志里明写一行 `🙋 已连接人机在环节点 (HIL peers 已登记)`。
- `hil_bridge.build_snapshot()` 增加 `links.peers` 段 ⇒ 画布 HIL 节点、手机页、终端三处**同时**能看到
  "L5 在线 / 终端在线"。
- 反向：L5 判读结果按既有 `seq` 回执路径写回人的界面（沿用 `l5_hil_agent.py` 现有实现）。

---

## 4. 接口设计 C：station 服务进"旁路实时可视化"节点

- 配置化地址（不硬编码）：`zmax_data/ss_bypass/station_url.json`
  `{"url":"http://10.163.146.78:8793/station","status":"http://10.163.146.78:8793/station/status","hil":"http://127.0.0.1:8795"}`
- `SSBypassView` 增加一条 **🛰 工位总览 station** 带：
  1) 可点开 `station` 页（外部浏览器，避免把 6 路 MJPEG 塞进画布）；
  2) 每 1.5s 轮询 `/station/status` 显示：6 路在线/帧龄 · TCP 位姿 · 授权剩余秒 · 模式/idle；
  3) 显示 HIL peers（谁连着我）；
  4) 显示最近一条 `station→规划→L2` 台账（见 §5）。
- 画布节点与 station 的状态**同源**（都读 8793/8795），不做第二份真相。

---

## 5. 接口设计 D：station 点位 → 状态空间规划 → 输出 L2（本设计的核心）

### 5.1 数据流（严格三段，规划与执行分离）

```
【1 意图】 station 页点"空间点1/金手指点1/point N"
        ↓  POST /station/plan  {"target":"space1","from":"current","solver":"moveit"}
【2 规划·只规划】 station 后端 → tools/moveit_plan_req.py --to <target> --once
        （写 plan_req.json；容器内 moveit_plan_live.py 用真机关节角做起状态、RRTConnect 规划）
        → 读回 live_plan_latest.json（关节轨迹 + 可行性 + 误差）
        → **段化器 plan_to_l2()**：把轨迹切成 L2 原子技能段，每段带
          {seg_id, L2_skill, params(d_mm/deg/pose), pred_delta, guard(≤50mm/下降≤20mm/自转≤10°)}
        → 返回 station：{ok, plan_id, segments[..], meta{solver, ik_ok, plan_ms, source}}
        同时落台账 reports/station_plan_ledger.jsonl（只规划，不动）
【3 执行·L2 收口】 人在 station 页看段表 → 点"按计划执行"
        ↓  POST /station/exec_plan {"plan_id":..,"confirm":true}
        → 逐段调用既有 L2 通道（8793 /ctl/move），每段：下发 → 等停稳 → 读位姿真值对账 → 下一段
        → 任一段失败/残差超限 ⇒ **停手**并回报（不重发、不自动补偿）
        → 执行记录追加同一台账
```

### 5.2 关键约束
- **规划器永不执行**；执行器永不规划。中间唯一产物是"段表(计划)"这个**数据**。
- 段表可在 station 页**逐段勾选**执行（可只走前两段）；默认全不勾，需人工确认。
- 未标定/未就绪（`zmax_calib.json` 缺项、规划容器离线）⇒ `ok:false` + 原因，**不编造段落**。
- 每段执行前仍过全部既有守卫（授权窗/包络/爬升/防连点/超时/抬升警报在线）。

### 5.3 新增路由（station 后端）
```
POST /station/plan        body {target|goal_xyz+goal_quat, from, solver}  → 段表
GET  /station/plan/<id>   → 段表 + 状态(planned/executing/done/failed)
POST /station/exec_plan   body {plan_id, seg_ids[], confirm:true}          → 逐段执行
GET  /station/ledger?n=20 → 最近规划/执行记录
```
无 `confirm:true` 或授权窗不在 ⇒ 403，不产生任何动作。

---

## 6. 验收判据（每条都要实据）

1. `curl :8795/hil/term/state` 返回一行可读现状；无 token 403。
2. `POST /hil/term/say {"text":"状态"}` → `verdict=status`；
   `{"text":"把机械臂伸过去"}` → `verdict=refused_motion`（红线在服务端）。
3. 起 L5 ⇒ `hil_peers.json` 出现 `L5`，且 `/hil/term/state` 的 `peers` 可见；
   画布 HIL 节点/手机页同样可见。
4. `SSBypassView` 带显示 station 在线 + 授权剩余 + 最近台账。
5. `POST /station/plan {"target":"space1"}` → 段表（含每段 L2 技能与守卫值），
   **且此步之后机器人位置一字未变**（规划只规划）。
6. `POST /station/exec_plan` 未带 confirm ⇒ 403；带 confirm 时逐段执行并逐段落台账。
7. 全程：`INCIDENT-INDEX.md` 无新增未记录事件；10083/相机不受影响。

---

## 7. 版本与后续

- 本轮改动涉及：`tools/hil_local_api.py`、`hil_bridge.py`、`tools/l5_hil_agent.py`、
  `tools/cam_live_stream.py`（station 路由）、`tools/gui/ss_bypass_view.py`、
  新增 `tools/plan_to_l2.py`（段化器）。全部**小版本迭代**（不重写既有逻辑），
  完成→保存数据→更新代码→共享技能（commit+push+沉淀）。
- 待老倪现场确认项：station 页是否要"逐段勾选"还是"一键全走"；段化粒度（50mm 是否再放小）。
