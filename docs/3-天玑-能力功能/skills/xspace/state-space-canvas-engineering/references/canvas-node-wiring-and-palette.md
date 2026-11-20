# 画布节点：从「写进 JSON」到「真执行 + 有按钮」

加节点分三段，段段有静默失败：JSON 里有了 ≠ 会执行；会执行了 ≠ 工具栏有按钮。

## 1. 会执行 = 必须有契约模块 `nodes/n_<slug>.py`

- `slug` 由**节点名**推导，不是节点 id（实测 `ss_se3_state` → `n_8815`、`ss_phase_corr` → `n_phase`）。
  先 `load_project()` 再打印 `prj.nodes[nid].spec.module_name`，用它命名文件；按 id 猜文件名必然对不上。
- 契约文件至少要有：`NODE_ID` `NAME` `LAYER` `TYPE` `EXEC_MODE` `PURE` `PORTS_IN` `PORTS_OUT`
  `IMPL_KEY` `PARAMS` `LAST_STATUS` 和 `compute(ctx)`；`compute` 返回 `{输出端口: 值}`。
- 缺契约 / 找不到实现时，trace 里是 `status="直通 (实现未注册: …)"`、`ms` 极小、`out1=None` ——
  **不抛异常**，看起来像“节点跑了”。判据只看这一行状态，不要看 ms。
- `compute()` 里要**自注册实现**：常驻循环进程（`tools/ss_canvas_loop.py`）未必 import 过
  `nodes/library.py`，registry 为空时同样报“实现未注册”。写法：
  `if not _reg.get(IMPL_KEY): _reg.register(IMPL_KEY, [匹配词], doc, impl_fn)`。
- `out1` 取值别拿 `IMPL_KEY` 当 `_SS_STATE` 的键：实现里写哪个键就取哪个键
  （实现写 `"se3_state"`，契约就取 `"se3_state"`），否则恒 None。
- 三处登记别漏：`impl_manifest.json`（file/func/module）、`nodes/library.py` 的 `_reg(...)`、
  `nodes/_index.py` 的 `NODE_MODULES`（id → 模块全名）。

## 2. 验证必须走真工程路径，不要手搓 ctx

```python
spec = importlib.util.spec_from_file_location("ssloop", "tools/ss_canvas_loop.py")
m = importlib.util.module_from_spec(spec); sys.modules["ssloop"] = m
spec.loader.exec_module(m); prj = m.load_project()
tr = prj.step(only=["ss_se3_state", "ss_phase_corr"])
# 看 tr[i]["status"] / tr[i]["ms"] / tr[i]["out"]["out1"]
```

- 判据：status 出现实现自己的 ✅ 与数值，out 里有真值（含 ts / age）。只有 ms 不算通过。
- 常驻 loop 只在画布文件 mtime 变化时重载：`touch` 后等一拍，日志出现
  `加载画布: N 节点 / M 连线` 才算新代码进循环。
- GUI 日志里的 `工程库已同步 · 节点 N` 已扣掉 `row_bg` 等非执行节点，与 JSON 节点总数不等 ——
  别拿它当“我的节点没加载”的证据。

## 3. 工具栏按钮 = 进 `LIBRARY_STATIC`，不是靠画布

- 左侧模块库的「状态空间模型」组是**按画布节点现生成**，且面板只在控制台启动时建一次 ⇒
  新节点在 JSON 里、在画布上也看得见，但用户重启后仍找不到按钮。
- 可靠做法：`tools/gui/simulink_module.py` 的 `LIBRARY_STATIC` 末尾追加一个静态组：
  `("model", "🌀 组名 (L4)", [{"name":…, "type":"model", "params":{"state_space":True,"cap_level":"L4","source":…,"desc":…}}, …])`。
  静态组不依赖画布状态，一开控制台就在。
- 面板有工作流过滤：`wf_of = {t: wf for wf, t in WORKFLOW_TYPES.items()}`，`model` 最终映到 `deploy`；
  `_current_wf` 不是它时整组不渲染 —— “明明加了却看不见”先查这一条。
- 画布侧同时要给节点补 `params`（`desc` / `source` / `cap_level`）和 `layer`，
  否则条目没有分组归属与提示，在一堆按钮里等于隐形。

## 4. 两份画布文件都要改；控制台会回写

- 唯一依据：`data/database/zmax/sources/canvas/state_space_obs.json`
  （`ss_canvas_loop.py` 的 `CANVAS` 常量指它）；`flows/state_space_obs.json` 是另一份实体文件。
  两处都改，改完各自回读节点/连线数。
- 控制台 `closeEvent` 会 `save_space()` 把**内存画布**写回 ⇒ 运行中的 GUI 内存若还是旧版，
  直接关窗口会冲掉新加的节点。顺序：先 `cp` 备份到 `flows/_archive/`，再 `kill -9 <studio pid>`
  （closeEvent 只有 SIGKILL 收得住），然后改 JSON。
- `data/` 在 `.gitignore` 里 ⇒ 画布 JSON 不进库，只有代码侧（契约模块 / library / _index / GUI）可提交。

## 5. 幂等与自证

- 加节点的脚本按 id 去重（已存在就跳过），写盘前断言：id 不重复、连线端点存在、非 row_bg 节点不重叠、
  所有新连线 `f.x < t.x`（前向）、节点/连线计数 +N。
- 写盘后回读：JSON 可解析、目标 id 存在、`links` 无悬空、`node` 的 `params.source` 能落到真实文件。
