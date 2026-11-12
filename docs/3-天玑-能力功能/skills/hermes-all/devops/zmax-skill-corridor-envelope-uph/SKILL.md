---
name: zmax-skill-corridor-envelope-uph
description: Use when 做原子技能约束通道包络或验 UPH≥300.
version: 1.0.0
author: 静静 (Hermes)
license: MIT
metadata:
  hermes:
    tags: [zmax, corridor, uph, ar, constraints]
    related_skills: [zmax-ar-traj-8797, zmax-state-space-architecture]
---

# 原子技能 · 约束通道包络 + 节拍/UPH 验收

## When to Use

- 要给 AR/真机轨迹加“原子技能约束”，让机器人只能在实际轨迹的扫掠包络内运行
- 加了约束后 UPH 掉了 / 要验 UPH≥300
- 要在 8797 `/ar3d` 画通道边界、控制包络显隐/按顺序点亮
- 通道画得“离机器人很远”要查坐标系

老倪要的口径: **约束 = 实际轨迹的扫掠包络外表面, 机器人只能在这个面内跑**; 加了约束还不能掉 UPH。

## 唯一真源(别用别的)

| 用途 | 真源 |
|---|---|
| 轨迹(AR 页面按拍走的就是它) | `plan_long_impl` 段表: `P.run({})` 后读 `P._S['segs']` (392 段, 每段 `kind/label/a/b/t`) |
| 通道数据 | `zmax_data/ss_live/skill_corridors.json` (schema `zmax.ss_skill_corridor/3`) |
| AR 画面边界 | `zmax_data/ar_rs/fences.json` (id 前缀 `COR-`) → `GET /api/fence` |
| 算法 | `src/lerobot/policies/left_right/state_space/corridor.py` (`build_polys`/`closest_on_polys`/`project_stage`) |

❌ 不要用 `trace_live.json` 的 `末端/光模块`(另一路话题、另一套坐标, 会飘到机器人一米外)
❌ 不要用 `sim_transport.json`(槽位盒轨迹, 不是 AR 画的那条)

## 建通道

```bash
cd ~/zmax
./gui-venv311/bin/python tools/ss_corridor_build.py               # 重算 8 段 + 写 AR 管道线
./gui-venv311/bin/python tools/ss_corridor_build.py --check 插入   # 单段自检
```

分组(kind/label → 技能): 接近=move·「上方」, 对位=move·「孔口」, 转移=move·「行进高度」,
下降=down, 抓取=grip, 抬起=up, 插入=insert+pull, 完成=release。同种动作的**每次机动各一条管子**(并集)。

半径(外廓 mm): 接近/转移/抬起 25, 对位 8, 下降 6, 抓取 3, 插入 3, 完成 6。

## 按节拍定速度上限(关键)

每段 `v_cap = clamp(v_need × 1.15, 0.35, 1.2)` m/s, `单拍 s_step = v_cap × dt`。
实测: 接近 0.724(72mm/拍)、转移 0.726(73mm)、下降/抬起 0.383、对位/插入 0.35、抓取/完成 0.146。

**坑**: 单拍固定 35mm(老 0.35 m/s 口径)会把自由段压到 1/3 速度 → 392 段拖慢 28% → UPH 246。单拍必须跟段速度给。

## 验收 UPH

```bash
./gui-venv311/bin/python tools/ss_uph_300_check.py
```
基线(闸/通道口径合一后): 闸后 189.12s/16 件 ⇒ **305 UPH**(plan 闸模型, 严) · 通道模型 315 (计划 159.43s, 0% 拖慢)。

**坑**: 别按 0.1s 拍取整(ceil 把 0.3s 段算成 0.5s, 虚高 60%); 用连续口径 `v_eff=min(v_req,v_cap,s_tick/dt)`, `t=L/v_eff`。

## AR 页面(8797 /ar3d, tools/web/tcp-ar.html)

- 包络默认全隐藏 1288 条(`CORSET` 空), 总开关 + 8 个按技能按钮
- `🔴 预执行约束`(默认开): 四条执行链(插拔全流程/插入仿真/生产演练/ar_cmd)取到即将执行的段时,
  把该段技能包络画红(不受隐藏开关影响); 钩子一律用 `corPreMark(d)`(只置状态不重画,
  动画循环里每帧都会重画), 不要用会调 `drawVR()` 的版本(递归)
- `🔗 跟随播放`: 播放到哪段只亮该技能包络(`corSkillOfSeg` 在 `arCmdSolve` 里勾)
- COR- 线**不进** `paintFenceBtns`/`renderFenceList`(否则 1288 个 button 撑爆), 也不画 A/B 文字
- 改完: 抽脚本 `node --check` + 无头浏览器实测开关/顺序 + 升版本戳 `rNN`

## 通道真进 plan 发布路径 (2026-11-01 「要真有效 接入 plan 节点」)

光有 `r_mm` 数字(算段时长)和 AR 边界 = 通道只是画了条线。必须在 **plan 的发布函数**里夹点:

```python
# src/lerobot/engineering/nodes/plan_long_impl.py
P._cor_fit(o1)                 # 段端点 (a,b) 夹进该技能通道, 按 seq 缓存, 每段只算一次
P._cor_pub(o1, corr, a, b, u)  # 每拍: 发布点越界 ⇒ u 二分收回到管内最大进度
P._cor(stage)                  # stage→通道 (mtime 热读); 关闸 ZMAX_PLAN_CORRIDOR=0
```

- 几何算法**只有一份**: `corridor.clamp_into(corr, pos)` (切外+回中到管壁, moved = dev−r 精确等式),
  plan 用 `importlib` 按路径加载同一个 `corridor.py` (`zmax_skill_corridor`), 不写第二套。
- 取证写进 `ar_cmd.gate.cor`: `{stage, skill, r_mm, dev_a, dev_b, cut, moved_mm, why, tick:{dev_mm,in,cut,n,dev_max}, u_pub}`;
  被夹回时保留 `a_raw` / `b_raw`(原目标), 页面仍按 `a`/`b` 动画 ⇒ 画出来的就是管内轨迹。
- 实际起点 `a_eff`(段间连续用的真实位姿) 也必须夹 ⇒ 零点漂移在页面上直接可见。
- 🔴 **零位移检测段 (AOI 金手指/侧面, kind=golden/side, a==b) 没有技能通道**: 别跳过, 用「保持点通道」
  (轴 = 保持点→保持点下方 1mm, r 取本段闸 r) ⇒ 偏离保持点 > r 夹回; 否则 70/392 段是空的。
- 自检: `./gui-venv311/bin/python tools/ss_plan_corridor_selfcheck.py` — 17 项 (覆盖 392/392 · 名义 dev 0 ·
  注入 3r/3000mm 夹回且 moved=dev−r · 每拍核点 · 起点漂移 · 关闸逐位不变 · 算法同源)。全绿才算接进去了。

### 🔴 两条段→技能口径 (最贵的坑)
`tools/plan_gate_corridor.py` 原来**只按 kind** 映射 (move→转移), 而通道侧按 kind+label 细分
(孔口=对位 / 行进高度=转移 / 其余=接近)。提速档把转移提到 1596mm/s 后, **14 段孔口对位也在吃 1596 (真值 350)**。
修法: gate 侧加 `stage_of(kind,label)` 与 `ss_corridor_build.group_polys` 同规则。
代价(实测, 16 件/圈): 闸后 178.59s→189.12s, 322→**305 UPH**(闸模型) / 315(通道模型) —— 只掉 1.8%, 但口径才对齐;
对外报数一律用闸模型(更严), 别拿通道模型当交付值。
残留名称差异属**设计**: `完成↔放入`、`插入(pull)↔拔出` —— 拔出是独立物理限速 (60mm/s), 通道把它并入插入几何,
不要强行合并 (会放松拔出安全限)。

## 动力学约束 (v/a/jerk) 实测口径 —— 「有效么」怎么答

`./gui-venv311/bin/python tools/ss_plan_dyn_selfcheck.py [秒数] [Hz]` 按 loop 节奏驱真 `plan.run()`,
用**全局位置 p=a+u·(b−a)** 反算拍间速度 (不能用 `u·L`, 段边界 u 归零会造出假超速)。现场实测 (456 拍/60s):

| 约束 | 结论 | 实测 |
|---|---|---|
| 几何通道 r_mm | ✅ 有效 | 392/392 段覆盖、名义 dev 0、注入 3r/3000mm 夹回且 moved=dev−r |
| 速度 v_cap | ✅ 段内有效 | 接近 0.726 / cap 0.724 (正好贴住); 残余超限 17/400 拍 (~4%) 集中在段首重锚与 L<50mm 短段 |
| 加速度 a_cap | ⚠️ 峰值仍超 | a 峰 4.6~6.8 vs cap 4.17 (1.1~1.6×); 已加 Δv≤a·dt 限幅 |
| 加加速度 j_cap | ❌ 峰值数倍 | jerk 峰 50~180 vs cap 2~38 (4~5×) |

**根因两条, 都是「口径不一致」而不是限幅器不够:**
1. 闸 `_t_min` 按**连续梯形**剖面 (v_lim=min(阶段v_cap, sqrt(a·r) 拐角)) 定段时长, 而发布曾用
   **每段启停的五次 S 曲线** (峰速 = 1.875×平均) ⇒ v 峰天然超 1.9×。已加 `ZMAX_PLAN_PROFILE`,
   默认 `linear` (= L/T 恒速, 与闸同剖面); 要老动效 `=scurve`。
2. 段本身太短: 0.3s 段里完成 jerk 受限加减速需要 `2·sqrt(v/j)` (0.724/15 ⇒ 0.44s) ⇒ **物理上装不进去**。
   硬要装: 按 jerk 受限时长重算 ⇒ 195.6s→216.3s, **295→266 UPH (-10%)**。

🔴 报 UPH 三个口径要分清: 通道模型 315 / 闸模型 305 / **plan 自己时间表 295** (12.2s/件, 交付按这个说)。
🔴 blend 段必须用 `a_eff` 算段长: 用原始 a 会把行程算短, 实测 L_eff/L_raw≈1.4 ⇒ 超速 40%。
🔴 画布 loop 实测 220~310ms/拍 (预算 100ms) ⇒ 有效 4~7Hz, 一段只有 1~2 拍, 动力学分辨率不够;
   提高发布频率是 a/jerk 能体现的前提 (plan 节点本身只耗 0.2ms, 不是它造成的)。

## 动力学约束 (v/a/jerk) —— 「折中方案」实现与验收 (2026-11-01)

**约束必须来自真实世界, 且有配置参数** (老倪硬要求)。三条工具链:

| 环节 | 工具/文件 | 说明 |
|---|---|---|
| 标定入库 | `tools/ss_dyn_calibrate.py --write` | v_cap←通道扫掠包络, a←F/m(5N/1.2kg), jerk←实测 P99 14.84×4; **缺来源拒写** |
| 唯一依据 | `config/calib/zmax_calib.json:dyn_limits` | 39 个可写数字, `tools/param_registry.py` 给单位/范围/中文名, 改文件热生效(mtime) |
| 溯源 | `config/calib/zmax_dyn_provenance.json` | 每个数字 = 哪个物理量/实测算来的 |
| 验收 | `tools/ss_dyn_verify.py [秒]` / `--watch` | 驱真 `plan.run()` 逐拍反算 v/a/jerk + 写 `zmax_data/ss_live/dyn_status.json` |

剖面 `policy.profile_mode`: 1=stopgo(默认) / 0=linear / 2=scurve; `stopgo_mode`: 0=只认工件边界(折中, 保 UPH) / 1=任何静止邻段(严)。

实现要点 (每条都是被坑出来的):
- `o1["seq"]` 是**发布计数器**(每写+1), 不能当段身份 —— 拿它当 key ⇒ 每拍重锚, 限幅整体失效 (实测 v 冲上限 1.8×)。段身份 = 技能 + 端点坐标。
- 段切换时 **连续段要接着上一段的速度/加速度**, 只有起停段归零; 否则 0→v 假加速把 jerk 顶到上限 6×。
- 新段第一拍也要限速 (曾直接放行 ⇒ 一拍跳 87mm)。
- 末端不能用 `sqrt(2a·rem)` 收油: a/jerk 都有限时刹不住, u 撞 1.0 被截断 ⇒ 假阶跃。要用制动距离 `k1v²+k2v=rem` (k1=1/2a, k2=a/2j) 反解 v。
- 限幅器用 `j_eff = jerk_cap·policy.jerk_safety` (默认 0.7), 抵离散拍 ~1.5× 超调。
- 单位陷阱: 分析器 `jump(mm)/dt(s)` 直接就是 **mm/s**, 不要再 ×/÷1000; 与配置上限(mm 口径)直接比。

实测结论 (10Hz 受控节拍, 55s/541 拍): v 超限 0 拍 ✅ · a 超限 1 拍 · jerk 超限 7 拍 (1.5~3×, 集中在加速→匀速交接拍)。
根本瓶颈是**发布频率**: 画布 loop 220~310ms/拍 (预算 100ms) ⇒ 一段只有 1~2 拍, 10Hz 下 jerk 分辨率本就不够; plan 节点自身只耗 0.2ms。要把 jerk 做实必须先提 loop 频率。

## 自检判据(全绿才算完)

0. 改了 `tcp-ar.html` 先 `node --check` 抽出的 script 块, **再用无头浏览器实际点一遗执行链**——
   光看语法过不算。本坑: 用 `if 'PRE_SK_CH' not in s` 判“常量已定义”会误判(引用行也算包含),
   结果定义没插进去 ⇒ 第一帧 `ReferenceError` ⇒ 动画直接冻在 seg 0。判断要写 `'const X=' not in s`。
1. 轨迹点到最近轴心最大距离 0.000000 mm
2. `ar_cmd.b` 落在所属技能通道内, dev≈0
3. 越界点(逐级外移到**所有**管子之外, 通道是并集)被切外+回中
4. 392 段顺序过通道后 UPH ≥ 300

## 数据归档

验收后归档 `zmax_data/archive/corridor_uph_<日期>/`: corridors、fences、state_space_obs、
skill_calls_tail.jsonl、ar_cmd.json + `MANIFEST.json`(sha256/字节数)。
