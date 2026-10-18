---
name: atomic-skill-physics-constraints
description: "Use when 给原子技能加惯性/质量变化率约束, 或要每个技能发物理量 topic/信号分析可见。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [robotics, physics, inertia, jerk, zmax, safety, skill-layer]
    related_skills: [real-arm-motion-control, robot-memory-layers, state-space-canvas-engineering, layered-capability-stack]
---

# 原子技能的物理惯性 / 质量变化率约束 (L2 技能层)

## When to Use
- 用户问"每个原子技能是否知道自己的惯性""进入技能的动作物理上能不能执行""要发偏差 error 反馈"。
- 给 L2 技能派发链加闸 / 复核已有闸（`saturate()` 只是幅值限幅，**不等于物理约束**）。

## 口径: 五条约束, 不是一条

每个技能自带物理量 (真源 `execution.py` 质量/力 + `safety.py` 力上限)，逐技能算上限:

| 约束 | 式子 | 物理含义 |
|---|---|---|
| ① 速度 | `|v| ≤ v_cap(技能)` | 技能工艺上限 |
| ② 加速度 | `|Δv| ≤ a_max·dt`, `a_max = F_max/m` | 牛顿二定律 (力/质量) |
| ③ 加加速度 | `|Δa| ≤ jerk_max·dt` | 平顺性 (从静止一脚踩不能瞬启) |
| ④ 动量/质量率 | `|m·Δv + v·Δm| ≤ F_max·dt` | 抓取/释放时质量在变 |
| ⑤ 位移 | `|v|·dt ≤ s_step` 且 段累计行程 `≤ s_max` | 位置是速度的积分: 单拍位移封顶 + 整段行程封顶 |

* `m` 按阶段取: 未夹持 = 夹爪质量; 已夹持 = 夹爪 + 工件; 抓取/释放段 `dm/dt` 非零。
* `F_max` 按阶段取: 通用 = `safety.FORCE_LIMIT`; **插入/放置段取保护值 (如金手指 ≤2N)**, 别拿通用力当插入力。
* `jerk_max` 可由**在轨道实测**定: 从真机/仿真轨迹算 v/a/jerk 的 P99, 再按 `jerk_max ∝ v_cap` 分档 ⇒ 比拍脑袋数字经得起质疑。

## 三条硬经验

1. **闸要放在"派发到技能"那一步**（每个技能一次），不是只放在全局安全边界: 全局限幅不知道
   "本技能能有多快", 所以它不能回答"这个动作物理上能不能执行"。
2. **偏差要分大小两路**: 小偏差就地进状态校正器 (`state_correction(..., err=, w_err=)`, 只动位置维, 别污染夹爪/力维);
   大偏差 (> 阈值, 如 50mm/s) 才是"顶层结构问题"。
3. **改顶层必须加三道保险**, 否则拿噪声改结构比不改更坏:
   ① 先过定位真值**新鲜度**核对 (帧龄阈值; 定位在漂时拒绝) ② 偏差须**持续**(连续 ≥N 拍, 单拍多为换段瞬态)
   ③ 补偿**限幅 + 累计封顶** (如 2mm/次 · 20mm 上限), 到顶就报"交人工/重标定", 不要无限补。
   四态 (拒绝/等持续/补偿/到顶) 都要落 trace, 界面上看得见"改了几次、改了多少"。

## 落地与取证 (Z-MAX)

```bash
./gui-venv311/bin/python tools/audit_skill_inertia.py            # 盘查表 (9 技能 × 四条约束 + 画布口径一致性 + 现场计数)
./gui-venv311/bin/python tools/verify_physics_constraints.py     # 判据 8 组 34 条 (含闸门各自触发/方向不翻转/夹爪维透传/四态)
./gui-venv311/bin/python tools/canvas_wire_skill_physics.py --apply   # 画布: 技能→⚖物理闸→(安全边界/状态校正器/融合定位)
```
* 代码真身 `src/lerobot/policies/left_right/state_space/physics_constraints.py` (`InertiaLimiter.limit/audit`, `PHYS` 表);
  消费侧 `tools/ss_skill_dispatch.py` (每拍过闸, 真源 `zmax_data/ss_live/skill_error.json`) 与
  `tools/ss_engine_loop.py::_top_compensate()` (大偏差→融合定位核对→改 `eng.goal_point`, trace 键 `顶层补偿_*`)。
* 离线验证顶层补偿用 `ZMAX_FUSION_TRUTH=<scratch 定位真值>` 覆盖 (现场恒为 `tcp_out/latest.json`);
  **别为了让它动起来去 touch 陈旧真值** —— 定位帧陈旧时"拒绝改顶层"本身就是正确行为。
* 报口径时要区分: `削因计数` 里哪条约束真被触发过。实测常态是速度/加加速度先绑, 动量/质量率可能长期 0 次
  ⇒ 那时要说"已实装并每拍检查, 但至今不是绑定约束", 不要暗示它拦过东西。
* **⑤位移常被①速度顶替**: `s_step` 默认 = `v_cap·dt`, 与①完全同界 ⇒ 只有标定时把它收紧到更小才成为绑定约束。
  所以"位移闸装好了"与"位移闸咬过东西"是两句话, 别混。`s_max` 超限**只报不杀** (`over_travel=1`),
  硬停会死锁, 停不停由上层按标志决定。

## 技能类里要有"真调用", 不是注释 (老倪 2026-10-15)

老倪: 「原子技能, 哪里是调用物理模型的? 这里没看到模型调用的语句, 怎么保证每次都有物理约束」。
方程注释 + `phys_model()` 只是**说明**; 他要的是**每拍执行真的过模型**。落地三段式:

1. 基类 `AtomicSkill`: `limiter()` 取闸实例 + `apply_physics(u, dt, v_prev, a_prev, dmdt)`
   **真调** `physics_constraints.InertiaLimiter.limit(self.stage, ...)` (唯一收口)。
2. **每个技能类体内写一条真调用** `def clamp(self, u, ...): return self.apply_physics(...)`
   —— 打开 SK05Lift 就能看到调用语句 (判据用 AST 卡住: 类体必须有 `clamp` 且真调 `apply_physics`)。
3. 派发链 (`tools/ss_skill_dispatch.py::Dispatcher._phys`) 按 stage 找**技能对象**,
   走 `skill.clamp(...)`; 无技能类的段退回 `self.lim.limit(...)` (如实登记, 不假装有技能)。
   计数 `n_gate_skill / n_gate_stage` 落盘 ⇒ 判据能证「过闸次数 == 派发拍数」(没有一拍绕过)。

### 踩过的坑
- **闸实例必须共用一份**: 技能类默认自己 lazy 建 `InertiaLimiter()`, 而派发链另有一个 `self.lim` ⇒
  段累计行程/上拍速度/削因计数**两处各记一半** (实测信号分析里 `s_mm` 直接变 0)。
  修法: `atomic_skills.bind_limiter(dispatch.lim)`, 派发链启动时把闸绑给技能调用口。
- **判据测"该削的削、不该削的不削"要用干净实例**: 闸是跨拍有状态的 (travel/last_v),
  刚灌过 5 m/s 再测 0.06 m/s 会被 ③加加速度削掉 —— 那是**正确物理**(从静止起步一拍的 Δv 有上限),
  不是 bug。测量前 `A.bind_limiter(InertiaLimiter(dt=...))` 重置; 合法值**从真源算**:
  `v_legal = 0.9·min(v_cap, a_max·dt, jerk_max·dt², s_step/dt)`。
- 取证: `tools/verify_skill_physics_calls.py` (判据 12 条: 类体内真调用 / 基类收口 / 超限真削 /
  合法不削 / 每拍过闸 / 技能口 / 批次同一闸 / 计数落盘)。

## 把闸搬进"关键路径"(u_ff → SK 段包络 → 仿真器), 而不是只做旁路观测

派发服务里的闸是**旁路**: 削出来的偏差写文件给状态校正器, 引擎的 `u` 根本没被削过。
老倪一旦问「u_ff 经过 接近/对位 等原子技能节点再给仿真器, 可以么」, 他要的是**关键路径上真削**。
落地 (Z-MAX 2026-10-16): `cognition.ActionModulator.decide()` 里把 `STAGE_V_CAP` 等比缩放换成
`InertiaLimiter.limit()`; 引擎 (`engine/sim.py` 解析 / `engine/runtime.py` metaworld) 构造闸挂到 `sched`;
画布 ①..⑧ SK 与 ⚖闸节点改读 `ss_live/skill_gate.json` (引擎 5Hz 落盘的关键路径真值)。

**四条铁律**:
1. **单点削**: 闸调用次数必须 == 拍数。两处都削 = 二次削 + 削因台账翻倍, 失去可诊断性。
2. **开关默认关**: `ZMAX_L2_GATE` 默认 0, 旧行为逐位不变; A/B 靠它切臂。
3. **Δt 用标定口径**: 真源 `zmax_skill_physics.json` 的 `dt`(0.1s) 才是表里 `s_step = v·dt` 的出处。
   改成引擎 dt(0.02) 等于把五条约束整体收紧 5 倍 ⇒ 解析引擎还能跑完但慢 6.5%, 真物理直接失败。
4. **判成功只看几何真值**: `ss_insert_metrics` 的 depth_mm/lateral_mm; 别用 `tr["mani_rem"]`
   (那是性能流形 d_axial, 不是插深 —— 拿它会得出"插了 171mm"这种假数)。

### 最重要的一条坑: `jerk_max` 标定普遍偏小 2~4 倍
真物理 seed104 实测 (metaworld peg-insert-side-v3, 500 步):

| jerk_max × | 完成 | 拍 | 插深 | 加加速度削拍 |
|---|---|---|---|---|
| ×1 (现标定) | ❌ | 500 | −2.3mm (没进孔) | 31 |
| ×2 | ✅ | 349 | 64.9mm | 2 |
| ×4 起 | ✅ | 348 | 64.3mm (与旧链逐位一致) | 0 |

消融证明真凶就是③: 只跳过加加速度, 其余四条全开 ⇒ 与不开闸**逐位相同**。
原因: 毫米级插孔靠的是每拍微修正, 加速度变化率恰好卡在 `jerk_max·dt` 上被抹平 → 伺服变迟钝 → 对不上孔口。
**结论**: jerk 不是"越小越安全", 它是**平顺性 vs 贴合精度**的权衡; 关掉或放宽到 ×2~4 前, 别指望闸能默认开。

### 消融/诊断开关 (默认不改行为)
```bash
ZMAX_L2_GATE=1 ZMAX_GATE_JERK_X=2 ./gui-venv311/bin/python <入口>      # 放宽 jerk 到 ×2
ZMAX_L2_GATE=1 ZMAX_GATE_SKIP="加加速度" ...                          # 逐条约束消融
ZMAX_GATE_DT=0.02 ...                                                # 切物理真实时间步口径
./gui-venv311/bin/python tools/ab_l2_inline_gate.py                   # 解析引擎 A/B (四条判据)
./gui-venv311/bin/python tools/ab_l2_inline_gate_real.py --seeds 104 --steps 500
./gui-venv311/bin/python tools/ablate_l2_gate_real.py --seed 104 --steps 500
```
判据里的①要按 `stage_u`(decide 实际用的段) 归因, 不是 `stage`(本步结束贴的标签): 换段那一拍两者差一段,
会误报"抓取 0.09 > cap 0.04"(其实是下降段 0.09 的合法值)。

## 技能要能「输出目标」, 不能只会削动作 (2026-10-16)

老倪: 「这些原子任务都有输出么? 最终的 MoveIt 是怎么选择实际的原子任务动作的」——
查出来的真事: 仿真 u 来自前馈加速器 (engine 里 `atomic_skills` **0 引用**)、真机动作由 `l2_daemon.build_move()`
按点位下发 (`grep moveit` = 0 次)、MoveIt 只是 plan-only 容器 (`allow_trajectory_execution=False`),
目标靠人给。三环各走各的 — 缺的是**技能执行口**。

落地 (`atomic_skills.py`): 每类声明 `TARGET = {"ref": "peg|peg_xy_table|hole_mouth|hole|point", "off_key": "params 里的偏置键"}`,
基类给两个方法:
- `next_target(ctx=几何, points=点位库, spec=阶段)` → 目标位姿; **两种上下文同一份规则**
  (仿真按 peg/hole 算, 真机按 taught_points 点位 + 偏置算)
- `command(ctx, x, k, v_cap)` → 期望速度 `u = k·(target−x)`, 限本段 v_cap, 到容差→0
- 解不出/未知段 → **None**, 绝不返回 0 目标

三条铁律:
1. **偏置只能有一份**: 引擎的 `STAGE_APPROACH_H/ALIGN/DESCEND/LIFT` 改成 `_sk_param("SK01Approach","hover_h",…)
   从技能类取, 判据卡 `最大偏差 < 1e-12` (实测 0.0e+00, 1107 拍零兜底)。
2. **真机侧 opt-in**: `build_move` 只在技能声明 `"atomic":"SK0x"` 时走技能口 ⇒ 97 条在役技能行为逐位不变。
3. **两套上下文都要测**: 空 ctx 下 8/8 段返回 None; 有点位库时 8/8 段 = 点位 + 本段偏置。

A/B 实测 (解析引擎, `tools/ab_skill_ff.py`): 技能驱动 u_ff (k=6) → **183 拍 vs 现状 369 拍 (快 2×)**,
末端 65.77 vs 65.95mm, 单拍开销不变; **k=3 推不动** (1600 拍未完成) ⇒ 增益是刚度不是精度旋钮, 必须 ≥6。

### 边界: 「技能驱动动作」只能用在解析引擎, 不能用在接触物理 (2026-10-18 实测)
metaworld 真物理路开同一个开关 = **失败**, 默认关:
| 臂 | done | 拍 | 插深 | 横向 |
|---|---|---|---|---|
| A 现状 (解析伺服+反馈) | ✅ | 348 | 64.3mm | 2.5mm |
| C 技能驱动 k=6 | ❌ | 500(上限) | 41.9mm | 18.9mm |
| C 技能驱动 k=10 | ❌ | 500(上限) | 34.4mm | 14.3mm |
根因: 纯 P 到**名义**目标即停 (`reached=True, u=0`), 而插孔靠的是接触后自适应 (两段式垂直降→横推、
遇阻螺旋搜索、夹持 `gap_z` 锁存) —— 长在「现场阶段目标 + 反馈」里, 覆盖 u_ff 等于丢掉它们。
⇒ 技能类在真物理路的职责是**给目标** (与引擎逐拍零差), 不是给动作; 解析引擎的快 2× 不可外推。

### 真物理目标对照的坑
`geom["head_off"]` = 「头 − **抓握点**」(复位时), 引擎里的 `off` = 「头 − **末端**」, 参考点差 ~2cm。
对照必须用 `peg_head() − self.x`, 否则转移/插入会假报 21mm 差 (自证伪信号)。
176 拍零差 (接近/对位/下降/转移) = 技能口与真物理路同一份目标语义; 差异只在抓取(-4mm 下探)/
抬起(-21.3mm 锁存 gap_z)/插入(段①+螺旋)。

### 无阶段/服务型技能要全覆盖且不硬塞
`rule_for_skill(sk)`: `line_abs` → `{"ref":"point"}`; `line_rel` → `{"ref":"rel","axis":…}`;
服务型 (AOI 接口) → **None (无位姿目标)**。判据口径分开数三类: 逐位一致 + 两边都拒 + 无位姿目标,
只卡「不一致 = 0」(97 条实测 60/14/23)。

### MoveIt 只规划, 目标可以由技能口给 — 但先查 systemd 常驻 writer
`moveit_plan_req.py --stage <段> --to <示教点>` ⇒ 目标 = 点位 + 本段偏置 (SK 口算), plan_req 带
`goal_src=skill/goal_stage`; `--auto` 从 5Hz 的 `ss_live/skill_gate.json` 取当前段 (超时报**帧龄**, 不猜);
无技能类的段 (拔出/AOI 等 5 段) 明确拒绝。

**两个坑**:
1. `moveit_plan_req.py --watch` 是 **systemd 常驻服务** (`zmax-moveit-plan-req.service`, `Restart=always`)。
   直接 kill 会被立刻拉起并**每秒覆盖 plan_req.json** ⇒ 你写的技能口目标根本进不了规划器。
   正确姿势: `systemctl stop` → 写请求 → 改 unit drop-in (`--auto --to …`) → `daemon-reload` + `restart`。
   判据要看 `live_plan_latest.json` 里的 `goal_xyz`, 而不是 `plan_req.json` (后者可能是别的 writer 写的)。
2. 容器内时间 = UTC (比 CST 少 8h), 对日志时间戳时必须换算, 否则会误判"没跑"。

### 内存撑不住时的排查顺序 (别先怪 LSP)
看到“某 python 占 20GB”先 `tr '\0' ' ' < /proc/<pid>/cmdline` 看**完整命令行**:
实测那个 20.2GB 是 `studio.py` 控制台 GUI (VSCode debugpy 拉起、跑 8h53m 泄漏), 不是 Pylance。
处置前必须核实两件事: ①该进程**无子进程** ②在役守护都是 `ppid=1` ⇒ 杀了不影响引擎;
然后 SIGTERM → 停 Restarting 崩溃容器 → `drop_caches` → `swapoff/swapon` 重置。实测 available 475MB→13GB, swap 满→0。
重跑控制台会再泄漏: 先看 RSS 再决定起不起。

## 物理参数标定 (v / a / s + 物理上下限)

每个物理量的**标定真源** = `config/calib/zmax_skill_physics.json`, 每项写成
`{value, min, max, unit, src}` —— `min/max` 就是物理上下限, `src` 记它从哪个常量来。

```bash
./gui-venv311/bin/python tools/skill_physics_calib.py --init-from-sources   # 从引擎/状态机真源生成 (AST 解析, 不执行代码)
./gui-venv311/bin/python tools/skill_physics_calib.py --table               # 标定表 (13 技能 × 9 量)
./gui-venv311/bin/python tools/skill_physics_calib.py --set 插入 s_step 0.002  # 按阶段名或 SK 号都行; 越界直接拒绝
./gui-venv311/bin/python tools/skill_physics_calib.py --check               # 有越界/缺项 → 非零退出
./gui-venv311/bin/python tools/verify_skill_physics_calib.py                # 判据 9 条 (端到端: 标定→闸门真的改了下发动作)
```

* 消费侧读法: `physics_constraints.limits_for(stage)` 优先读真源, 并把运行期取值**夹**在 `[min,max]`
  内 (越界进 `p["clamps"]` 取证); 真源缺失 ⇒ 回退内置 `PHYS` 表 (行为逐位保留, 不因缺文件崩)。
* **技能类自己就能读**: `SK01Approach.phys()` → 本技能完整物理上限 (m/F/v/v_min/a_max/jerk_max/s_step/s_max)
  · `SK01Approach.phys_bounds()` → 每个量的 `[min,max]` · `SK01Approach.phys_check()` → 是否齐/是否越界。
  ★ 技能类**不自带**物理数字 —— 一旦把 m/F/v 抄进类里就是第二份数字, 三处 (引擎常量/真源/技能类) 必然打架。
* **方程要写在技能类里** (老倪 2026-10-15: 「我打开 SK01Approach 的时候, 怎么没有看到任何物理方程呢?」):
  只把方程放在闸门模块 = 用户打开技能看不到模型, 等于没有。做法: 基类挂 `EQ` (五式形式) +
  `phys_model()` (方程**带本段真实数字**) + `show_phys()` (打印); 每个 SK 类体内逐条写一遍五式和
  `phys_note` (本段哪几条绑定); `list_skills()` 带上 `phys/phys_equations/phys_note` 供 GUI/文档用。
  数值仍单一真源 —— 写进类里的只有**形式**。判据要卡住这条 (方程条数=5 + 方程里能找到本段数字 + phys_note 非空),
  否则它只是个花架子。
* 名字对应关系 (真源 ↔ 闸门输出): `a → a_max` (有标定 a 用标定值, 否则 F/m)、`s → s_max` (段行程),
  `s_step` 单独一项。写自检时别忘了这层别名, 否则报"缺项"假红。
* 上下限的来源要能背出来才算合格, 例: `s_step ≤ v_cap×dt` (单拍位移不可能超过速度上限×拍)、
  `a ≤ 夹爪最大夹持力/最小运动质量`、`v ≤ safety.VEL_LIMIT`。**上限不是"随便写个大数"**。
* 标定值与引擎字面量是**两处**, 靠判据②(真源 v/v_min == `cognition.STAGE_V_CAP/STAGE_V_MIN`) 卡住;
  改了真源不改引擎 ⇒ 判据立刻红, 这正是想要的效果。

### 标定面踩过的坑
1. **写路径必须能被环境变量覆盖**: 判据脚本要在**临时副本**上验标定, CLI 若只认模块常量 `CALIB`,
  就会把测试值写进在役真源 (实测把 `接近.v` 从 0.35 改成 0.34)。做法: `calib_path()` 每次读
  环境变量, 别在 import 时定死。
2. **缓存要按 (路径, mtime) 键**: 只按 mtime 缓存, 换路径后仍命中旧数据 ⇒ 判据假绿。
3. **AST 解析引擎常量时** `dict(m=1.2, F=5.0)` 这种 `dict(...)` 调用 `ast.literal_eval` 会失败,
   要自己处理 `ast.Call`+keywords, 否则解析结果静默变成默认值 (实测所有技能 m/F 都成了同一个数)。
4. **同一段可能有两个名字**: `PHYS` 里叫「放入」, 引擎 `STAGE_V_CAP` 里叫「放下」 ⇒ 生成时引擎没有的段
   要退回该技能自带的 v 并在 `src` 里写明"待统一", 别静默填 0。
5. 打印带中文的表格要按**显示宽度**补空格 (东亚宽字符算 2), 否则列串行。
6. **物理量是按段名 (中文串) 索引的** ⇒ 段名一改/写错, 闸门原来会静默套用「接近」的 m/F/v
   (看不见的降级)。现在 `unknown_stage=1` + `stats()['n_unknown_stage']` + 盘查表"段名登记"列;
   新增段时先在心里过一遍: 这个段名在 `PHYS` 和真源里都有吗?
7. **同一字段两个名字**: 闸门里叫 `dmdt`, 报告里叫 `dmdt_max` ⇒ 取错就静默变成 0
   (实测方程里印出 `dm/dt=0.00`)。跨模块取值写 `q.get("dmdt_max") or q.get("dmdt")`, 并让判据比一次真源。
8. **技能号不要自己编**: 档位/真源里的 code→stage 映射要从 `atomic_skills.py` 的类上解析
   (`code`/`stage` 类属性), 别手写 SK09..SK13 —— SK07 在插拔链=插入、摆盘链=放入, **同号两支**都是真的。

## 物理量要"看得见": 每技能一条 topic + 信号分析可见 (老倪 2026-10-15)

老倪: 「所有的原子技能, 例如 接近, 对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有对应的信号;
我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、角度等物理值; 要实际发出来。」

做法 = **一条链, 六个落点, 缺一个就是"没发出来"**:

| 落点 | 文件 | 关键点 |
|---|---|---|
| ① 话题登记 | `src/lerobot/dataspace/topics.py` | 8 条 `skill_sk01..08` (类型 `zmax::SSSkillPhys`); diag/calib/test **三档都要登记**, 否则某档静默不发 |
| ② 类型 | `dds/ss_types.py` | `@dataclass class SSSkillPhys(IdlStruct, typename="zmax::SSSkillPhys")` — **@dataclass 不能漏** (漏了报 `SSSkillPhys() takes no arguments`) |
| ③ 注册 | `dds/zmax_node.py` | `_SS_TOPICS` 加映射 + `QOS_CLASS` 给 `beat` |
| ④ 生产 | `tools/ss_skill_dispatch.py` | 每拍过物理闸后写 `zmax_data/ss_live/skill_phys.json` (实测 + 包络 + 位姿) |
| ⑤ 发布 | `tools/dds/ss_daemon.py` | `pub_skills()` 逐技能发一条 + 挂进 `tick()` |
| ⑥ 看得到 | `tools/gui/canoe_graphic.py` | `HOST_SOURCES` 加源 + `HostJsonSource.run` 里**显式取键**; 场景色标 `tools/sig_scene_tags.py::tag()` |

消息字段 = **实测 8** (x/y/z/v/a/s/angle/err) + **包络 7** (v_cap/a_max/jerk_max/s_step/s_max/m/F)
+ 元 4 (in_service/step/frame_age_s/why)。包络必须随消息发 —— 信号分析里"实测曲线 vs 物理上限"同图叠
才叫"看到物理模型"; 只发实测等于把模型丢了。

### 这条链上踩过的坑 (都是"看着有、其实没有"的静默故障)
1. **同一份 JSON 三个读者, 字段名必须一致**: 守护按 DDS 消息名读 `v/a/x`, 而文件里叫 `v_mms/a_mms2` ⇒
   8 个物理量全读空, 目录里只剩包络 (看着"没有物理量")。判据要卡"派发写的名 == 守护读的名 == GUI 读的名"。
2. **包络要取 `limits_for` 真源, 不要取闸门每拍结果里的 `phys`**: 那是给人看的**四舍五入摘要**
   (m 4 位 / a_max 4 位 / jerk_max 3 位), 拿它发布 ⇒ 4.166667 变 4.1667, 与真源对不上 (判据 1e-6 红)。
3. **加速度不能用 (本tick−上tick)/dt**: 块内同一拍动作不变 ⇒ 只在换块那一刻出现 16ms 尖峰,
   界面按 ~50Hz 采样几乎采不到 ⇒ 现场看 a 恒为 0 (假信号)。改用**块间速度变化率**并保留到下一块。
4. **位姿只允许一个读者**: tap 由派发服务读一次写进 skill_phys.json, 守护只转发。两处各读一份、各算一次
   新鲜度 ⇒ 迟早出现"一条通道的位置是新的、另一条是旧的"。
5. **`flatten_json` 有 48 键上限** (AR 源踩过): 信号多于一屏必须走显式取键分支, 否则部分技能静默缺信号。
6. **加话题要同时改 A 档 core** (`tools/zmax_profile.py`): 否则 A 档 `topics=core` 把它静默滤掉。
7. **改完必须 restart 对应 systemd 服务**: `zmax-ss-skill-dispatch` / `zmax-dds-ss` / `zmax-dataspaces-probe`
   (在跑的 Python 不热加载); 顺序 = 派发(生产) → 守护(发布) → 探针(DDS→live.json)。
8. **判据脚本要会挑 venv**: `venvs/dds-venv` 有 cyclonedds 没 numpy/huggingface_hub; `gui-venv311` 反过来 ⇒
   纯 numpy 模块 (physics_constraints) 按**文件路径** importlib 加载, DDS 类型声明用 **AST 读字段**,
   运行期"能不能上线"用 `zmax_data/dataspace/live.json` 的实收计数与 fields 证明。

取证三件套 (都真跑):
```bash
./gui-venv311/bin/python tools/verify_skill_topics.py                      # 判据 26 条 (登记/类型/同名/生产/包络同源/在界/发布/不伪造/单读者/诚实登记)
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_signal_skill_topics.py --secs 12 --shot reports/ui_shots/signal_skill_topics.png
./gui-venv311/bin/python tools/topics_list_skill.py --md                   # 清单 (生成物, 真源=topics.py)
```
* **诚实登记比凑数重要**: 引擎 13 段里有 5 段 (拔出/AOI转移/AOI检测/回程/放下) **没有技能类** ⇒
  只在 topics.py 登记 + 标「待接生产者」+ 放进 `MODE_TOPICS_PENDING` (不进任何遥测档), 不假装有数。

