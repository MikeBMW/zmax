# 右侧侧边栏精简 + 「主参数 M」页 (v5.24.0, 2026-10-09)

老倪: 「右边的侧边栏，重点是 配置 和 标定，以及主参数 M；其它的功能要精简，如果没有联系，
全都注释掉，如果确定没用，都删掉」+ (同一轮) 「INTACT机器人 / 数据闭环引导 / 数据闭环控制台
你觉得有必要保留么？没用就删掉」

## 1. 判据先说：右侧栏哪些视图跟状态空间工程**有真联系**

取证对象 = 状态空间工程真源 `src/lerobot/engineering/flows/state_space_obs.json` (89 节点 / 184 连线):

```
grep 统计:  z700_internal = 0 处      gain_schedule = 0 处
```

右侧栏里那一套「配置/标定/诊断」视图全部建立在**另一套画布**(「⚙️ 前馈 PD」顶层，带
`z700_internal` 节点 + 状态机 `gain_schedule`)之上：

| 视图 | 代码依赖 | 在状态空间工程里的实际表现 | 结论 |
|---|---|---|---|
| 📏 数据字典 | 画布节点 params + `feature.dbc` | 真数据 | **保留** |
| 📏 状态空间变量 | 引擎 `module._ss_tr` io_trace + 画布连线 | 真数据 | **保留** |
| 📏 数据总线 | 同上 (io_trace) | 真数据 | **保留** |
| 🔧 运行开关 (6 个) | `self.chk_*` → 引擎运行分支 | 改了真生效 | **保留** |
| 🎛 参数标定 (极点配置) | `_write_back` 要求 `z700_internal` | 点了弹「当前画布无 Z700 内部模块」 | 停用 |
| 📐 现场标定 | 找状态机节点导出 scene_config.yaml | 找不到节点；无引擎读它的输出 | 停用 |
| 📊 性能指标 | `_stage_gains()` ← `z700_internal` | 找不到 ⇒ 用硬编码默认增益 | 停用 |
| 🎯 场景状态 | 同上 (`_DEFAULTS`) | 同上 = 默认数字 | 停用 |
| 🚀 运行汇总 | `analyze_system()` | 走 else 分支 → m=1.0/b=2.0/k=5.0 默认值 | 停用 |
| 🧮 数学分析 | `analyze_system()` | 同上 (传函/极点/复平面都是默认参数算的) | 停用 |
| 📋 工程需求 | 面板内 `module._eng_req` | 引擎/工具都不读 | 停用 |

⇒ 这就是老倪最忌讳的「看着接了，其实是假数」。**不是删，是注释掉**：8 个部件类 + 5 个分析函数
整体挪到 `tools/gui/_model_tree_ffpd_legacy.py` (带复活说明头)，`model_tree.py` 里原文位置留注记。
面板 `cmb_view` 11 项 → **5 项**，`_switch_view` 保持表驱动 (`VIEW_KEYS`)。

## 2. 新页「🧮 主参数 M · 测量 / 标定 / 诊断 / 配置」= 右侧栏重点

数据源 = **画布上的 M 节点**「🧮 标定诊断测量 · 主参数 M」(`n_calib_mani`) 的 params
(`cfg_entries` 9 条真源路径 / `cfg_snapshot` / `measure_view` / `calib_view` / `diagnose_view` /
`task_layer`) —— 这些快照由 `tools/ss_node_sync.py` 从**真源文件**同步进节点 ⇒ 页 ↔ 节点 ↔ 文件
三方同源，点是：

* 4 个页签：📏 测量 / 🎛 标定 / 🔍 诊断 / 🔧 配置 (每行「项 / 值」，值可选中复制)
* 「✏️ 写 M」：`zmax_params.write_manifold_M` = 范围校验 + 只改 `manifold_engine` 键 + 写真源
  `config/calib/zmax_manifold.json`，**写完立刻回读** (三段纪律在工具里，面板不另开写口)
* 「📥 从真源同步到节点」：跑 `tools/ss_node_sync.py`
* 「🔁 刷新」/「📋 复制摘要」；没有 M 节点的画布 → 诚实空态 + 给补救命令
* 默认页 = 本页 (`_switch_view(0)`)；画布加载后 (`model_tree.refresh()`) 自动刷新，不用先切页

## 3. 顺带清掉的死面板 (同一轮「确定没用就删掉」)

* `CICDPanel` / `CICDStageItem` / `CICDLinkItem` / `open_cicd_panel` / `_cicd_panel` 刷新钩子
  —— 全仓零引用 (画布 6 环节走 `PipelinePanel` + `on_collect…on_infer`)，**删 295 行**；
  `CICDWorker` 保留 (PipelinePanel 训练仍在用)。
* 「🧭 数据闭环引导」按钮由工具栏**搬进**数据闭环面板表头 (引导的是那个面板，就地放)。
* 保留：🤖 INTACT机器人 (真功能：INTACT 上游机器人切换面板，列出 reacher)、🎯 数据闭环控制台
  (PipelinePanel 6 环节，每个都对到画布节点动作)。

## 4. 判据 (8 个 verifier 全绿，`tools/run_gui_verifiers.sh` 一键跑)

| verifier | 关键数 |
|---|---|
| `verify_mparam_page.py` | 载画布后**自动**出 13 行；就绪度 10/24；活跃 TASK-01-FW；真源路径 9 条；标定页 M 行与节点 `calib_view` 逐字相同；M=99 被钳到 8；写 M 幂等 (真源数值不变)；ss_node_sync exit 0；空态诚实 |
| `verify_run_cfg_panel.py` | 6 开关仍是**同一对象** (搬不是复制)；视图数 5；5 视图索引→控件全对；默认停在 M 页；停用类已不在 `model_tree` |
| `verify_entries_cleanup.py` | 三入口：2 保留真能开 (机器人面板/reacher、6 环节面板)、1 搬位；CICD 类全无；引导高亮真起 |
| `verify_step_follow.py` · `verify_canvas_render.py` · `verify_engineering.py` · `verify_l2_compat_checkbox.py` · `ss_node_impl_audit.py` | 回归 89 节点/183 连线、单步跟随 9 组、架构自检全 ✅ |

## 5. 踩到的坑 (已进 skill)

* **`load_flow_file` 会给节点重编 id** (`n_calib_mani` → `n1791534…acq`) ⇒ 面板取节点必须
  「语义标记 + 名字」兜底，不能只按 id；按 id 写判据的 verifier 会假红。
* **插代码块要按「方法体末尾」定位**：本次把懒刷新块插到了类方法**之间**，语法能过 (`ast.parse` ✅)
  但挂到了上一个方法体上 ⇒ 现象是「钩子不生效」。定位方式：找到 `def X` 再找**下一个** `^    def `
  之前的最后一行。同类错误 `ast.parse` 抓不到，只能靠判据抓。
* 状态空间画布上 `analyze_system()` 的 else 分支会把 m/b/k 全填默认值 ⇒ 那类页看着有数，其实与
  画布无关。判断「有没有真联系」的判据是**画布真源里有没有它读的键**，不是「点了有没有反应」。
