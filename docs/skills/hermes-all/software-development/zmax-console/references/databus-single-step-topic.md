# 数据总线 × 单步运行 topic (老倪 2026-10-12 口径)

## 需求原文 → 三条硬口径
> 「右侧的数据总线, 要有对应的 topic; topic 数据来源于全局数据空间。我单步运行的时候, 要高亮显示
>  当前节点输出的 topic。默认每个节点至少输出一个 topic; 这个 topic 数据在单步运行 debug 的时候
>  肯定会输出, 但是在整体运行的时候, 可以考虑性能, 不序列化输出 —— 单步运行是为了标定系统而启用的。」

1. **每个节点 ≥1 输出 topic** — 画布 89 节点, 每个都有**自己独立的** topic `ss/<node_id>/out`。
2. **单步高亮** — 单步到哪个节点, 数据总线 Trace 表里该节点 topic 行**置顶 + 金色高亮** (`#2b2611` 底 / `#ffd700` 字,
   与画布单步节点同色), 值列显示该步**真载荷**。
3. **序列化有闸** — 单步/调试 ⇒ 真序列化 (trace.jsonl + step_current.json); **整体运行 ⇒ 不序列化** (topic 仍登记, 零载荷开销)。

## 实现 (唯一依据与文件)
- `tools/ss_bus_topics.py` (唯一实现):
  - `topics_by_source(busdb)` — **节点的输出 topic = 该节点出线的 topic** (`busdb.signals` 是画布连线记录
    `{sid, link_id, src, dst, ..., topic}`, 按 `src` 归组)。
  - `ensure_busdb()` — 给**每个**画布节点补 `ss/<node_id>/out` (`synth=true, kind=node_out`,
    `link_topics=[…唯一依据出线 topic…]`); 幂等 + 备份 + 回读; **唯一依据 182 条连线一律不动**。
  - `publish(node, out, mode)` — `mode in ('step','debug','单步','调试')` ⇒ 真序列化; 否则只写指针 (性能闸)。
  - `highlight_topics()` / `read_current()` — 数据总线视图读它做高亮。
- `tools/gui/dds_canoe.py` — `_fill_trace_fixed()` 顶部读 `highlight_topics()`; 单步 topic 行**置顶 + 金色**;
  并把 `step_current.json` 的 topic **并入 live topics** (`zmax::SSNodeOut`, `qos=step`, 值列=`state=[…]`)。
- `tools/gui/simulink_module.py` — `_run_node_single()` 里 `self._sim_signals[n["id"]] = out` 之后调
  `ss_bus_topics.publish(...)`: 单步 ⇒ `mode="step"`, 其它节点级运行 ⇒ `mode="debug"`。
  **整体运行 (▶运行 / `_ss_tick`) 不走本函数 ⇒ 天然零序列化开销。**
- 判据 `tools/verify_ss_bus_topics.py` (14 条): 每节点 ≥1 topic · topic 语义 · 唯一依据连线不减 · 单步序列化 ·
  整体不序列化 · 高亮集合 · SINK 节点也有 topic · 幂等 · DBC 结构未破 · GUI 接线 · Trace 表并入。

## 坑 (都是实测踩过的)
1. **唯一依据连线 topic 全是同一个名** (`zmax/link_value`, 182 条里 181 条重复) ⇒ **不能按连线 topic 高亮**,
   否则整张表全亮, 定位不到当前节点。必须用**每节点独立 topic** `ss/<node_id>/out` 作高亮单元;
   唯一依据出线 topic 如实记进 `link_topics` (信息不丢)。
2. **`_fill_trace` (滚动) ≠ `_fill_trace_fixed` (默认固定行)**: 高亮/置顶要打进 **fixed** 那个函数
   (切片的行循环在 ~1164/1190); 打错函数 ⇒ 表里有行但没颜色 (离屏渲染探针才发现)。
3. **Trace 表的行只来自 `live.json` 的 `topics`** (真 DDS 流量, 常态仅 9 条), **不读 trace.jsonl**;
   `live.json` 由常驻 `tools/dds_bus.py` 每秒重写 ⇒ 单步 topic 必须**视图侧并入** (`tp[_t] = …`),
   写进 live.json 会被覆盖。
4. **`_live_vals` 只渲染白名单键** (`goal_xyz/tcp_pose6/action/state/hz/count/...`), 载荷键名不在白名单
   ⇒ 值列只出 `hz=50`。要把载荷压成 `state=[数字…]` + `count=N`, 值列才显示真数据。
5. `busdb.signals` 里混了连线(唯一依据)与合成条目 ⇒ 一切按 `synth` 标记区分; 合成条目按 "节点是否还在画布上" 清理,
   **禁止**按"有出线就删"来清 (会误删)。

## 实证 (离屏, 不动老倪在用的 GUI)
`QT_QPA_PLATFORM=offscreen` 建 `dds_canoe.BusView(standalone=True)` → 人造一次单步发布 → `_fill_trace_fixed()`:
命中行 **row 0 (置顶)** · `bg=#2b2611 fg=#ffd700` · 值列 `state=[0 0.012 -0.003 …(5)] · count=5`;
`mode="run"` 反证: 该 topic 行数 **0**。判据 **14/14 PASS**。
改动在被 GUI 启动时加载 ⇒ **要重启控制台才看到金色行** (重启前先问老倪, 别自作主张打断他的单步标定)。
