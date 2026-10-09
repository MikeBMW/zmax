# 状态空间画布 · 单步跟随 + 逐节点实现审计 (v5.22.0)

> 2026-10-09 · 静静 · 老倪: 「我要全面检查状态空间工程的每个节点的实现, 现在我需要单步运行,
> 运行到哪个节点, 哪个节点要高亮显示, **而且画布要跳到这个节点** —— 因为现在的画布太大了, 我找不到单步节点到底在哪里了。升级」

## 0. 结论先说
高亮本来就有 (`node["status"]="step_active"` → 金框 2.8px / `node["hl"]` → 金框);**缺的是"画布跳过去"**。
本轮补三件套 + 一张全表:

| 东西 | 位置 | 作用 |
|---|---|---|
| 🎯 **跟随单步** (复选框, 默认开) | 画布工具栏 ⏭单步 右侧 | ⏭单步 / 右键运行节点时, **画布自动平移+调到看得清**; 关掉=画布不动, 只在终端报位置 |
| 📍 **定位节点** (按钮) | 同上 | 不管跟随开关, 直接跳到"当前单步/运行到的那个节点" |
| 🏠 **全览** (按钮) | 同上 | 一次缩放到能看见全部 89 节点 (画布太大时的回家路) |
| 🧾 **节点实现审计** (按钮) | 同上 | 逐节点查实现 → 终端汇总 + `reports/node_impl_audit.{txt,json}` 全表 |
| 实现位置行 | ⏭单步 的终端输出 | 每步多一行 `实现: <key> → <函数>() <文件>:<行>` (与双击看源码同源) |

## 1. 实现 (代码落点)
- `simulink_module.py::SimCanvas.focus_node(node_id, min_scale=0.45, max_scale=1.6)`
  —— 缩放夹到"看得清"区间 (太远放大 / 太近缩小), 再 `centerOn(节点包围盒中心)` + `viewport().update()` (VcXsrv 滚动后强制重绘的既有惯例)。
- `SimCanvas.fit_all(margin=240)` —— 所有节点包围盒 `united` → `fitInView` → 同步 `self._scale`。
- `SimulinkModule._follow_to(node, force=False)` —— 跟随开关在这里收口; 同一节点 2 秒内只跳一次
  (一次 ⏭单步 会经 `step_sim → _run_node_single → _highlight_node` 两条路进来, 否则终端刷两行)。
- `SimulinkModule._impl_line(node)` —— `registry.match_node(名) → key → fn`, 位置用 `sourceview.get_node_location(key)`
  (自动处理 `_EXTERNAL_LOC`: 真实现在 `left_right/state_space/*.py` 等外部文件, 并按符号名现搜行号)。
- 挂钩点: `_highlight_node(node, ms, follow=True)` 末尾调 `_follow_to`; 状态空间单步 `_state_space_step()` 与老单步 `step_sim()` 各加一行 `_impl_line` + `_follow_to`。
  于是 **⏭单步 / 右键「运行节点」/ 其他节点级高亮** 都会跳 (全局 ▶运行 的节点高亮也跳; 不想跳就取消勾选)。
- 反馈纪律沿用老倪 2026-10-01 定稿: **画布上不铺文字**, 文字只进下面终端; 画布靠金框/状态色, 按钮文字由点击驱动。

## 2. 逐节点实现审计 (`tools/ss_node_impl_audit.py`, 只读)
```
python3 tools/ss_node_impl_audit.py [--level L4] [--json] [--write] [--no-code]
```
- 每行: 序号 / id / 名称 / 层级(按 row_bg 色带) / 实现 key / 单步(✔) / **实现位置 文件:行**
- 单步序判据 **直接调用 GUI 的 `_ss_node_cap_level` / `_ss_is_observer`** (不是抄一份), 并逐节点交叉核对内联副本
- 实测: 节点 89 (功能 74 / 背景 15) · **实现命中 74/74 · 未命中 0** · 判据交叉核对 74/74 ✅ · 同 key 多节点 2 (`ss_world`×2, `n_dsvl`×2)
- 单步序: L2 档 45 节点会执行 (排除背景行 / 档位开关 radio / 观察器·质量门 —— 执行它们=弹窗轰炸或触发切档副作用)
- 输出: `reports/node_impl_audit.txt` (全表) + `reports/node_impl_audit.json` (机器可读)

## 3. 实测证据 (`tools/verify_step_follow.py`, 离屏真建 SimulinkModule + 真加载画布)
```
① 渲染回归   节点项 89/89 · 连线项 183/184 (差 1 = 既有 (f,t) 去重) · 加载无异常
② 新增控件   🎯跟随单步(默认勾选) · 📍定位节点 · 🏠全览 全部在位
③ 实现位置   「融合定位」→ ss_sensor → node_ss_s1()  …/left_right/state_space/perception.py:20
             「机器人执行器」→ ss_act → node_ss_exec()  …/state_space/execution.py:14
             「标定诊断测量」→ n_calib_mani → node_ss_calib_mani()  …/manifold/manifold_engine.py:101
④ 真跳       「融合定位」偏差 13px · 「标定诊断测量」1px · 「机器人执行器」1px (画布跨到 x=15806 也跳得到)
⑤ 跟随开     中心落到「安全执行边界」偏差 4px · 位移 1578px · 缩放调到 1.97 · 终端有「📍 画布已跳到」
⑥ 跟随关     中心位移 0.0px (画布完全不动) · 终端提示「🎯 已关跟随单步」
⑦ 📍定位     跟随关着也能跳回当前节点 (偏差 4px)
⑧ 🏠全览     缩放 0.45 → 0.05 (一次看到全图) · 终端报「🏠 … 全览」
⑨ 高亮       节点 hl=True (金框) 且同时跳转
→ 全部 ✅ (exit 0)
```
回归: `verify_engineering.py` ✅ 工程架构自检通过 · `verify_canvas_render.py` ✅ 89/183 · `ss_node_impl_audit.py` ✅ 74/74。

## 4. 老倪怎么用
1. **重启一次控制台** (代码改了才生效; 控制台在跑时改文件不影响运行中的实例)。
2. 画布页点 **⏭ 单步** → 每点一次, 当前节点金框高亮, **画布自己跳过去**, 终端一路打:
   `⏭ 单步 [k/N] <节点名>` + `实现: <key> → <函数>() <文件>:<行>` + 该节点真实 I/O。
3. 想先看全图 → **🏠 全览**; 跳偏了 → **📍 定位节点** 回来; 不想让画布动 → 取消 **🎯 跟随单步**。
4. 要一张"每个节点是哪个函数实现的"全表 → **🧾 节点实现审计** (或命令行 `tools/ss_node_impl_audit.py --write`)。

## 5. 坑 (本轮踩到并记下)
- 🔴 **`load_flow_file` 会给每个节点重新 `gen_id()`** ⇒ 文件里的 id (`sssensor`/`n_calib_mani`) 在 GUI 内存里查不到,
  只有 `self.nodes` 里运行时生成的 id 有效。**任何"按 id 找画布节点"的代码都必须带名字兜底**
  (GUI 里既有 `_ov_live_target_item` 就是这个写法)。`tools/ss_node_sync.py` 也补了"按语义标记兜底"。
- 一次单步走两条路进 `_follow_to`, 不做去重会连跳两次/刷两行终端。
- `_follow_to` / `_highlight_node` 必须能接受 `node is None` (画布为空或名字没匹配时) —— 否则点一下就 Traceback。
- 画布上**不铺任何状态文字** (老倪定稿): 位置/进度只进下面终端, 画布留给金框和状态色。
