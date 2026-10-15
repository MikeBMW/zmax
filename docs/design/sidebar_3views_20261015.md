# 画布右侧栏 三页契约 (老倪 2026-10-15)

## 老倪原话

> 画布右侧栏，保留 主参数：对应流形引擎； 数据总线：对应数据空间的 Trace；
> 参数中心：对应数据库服务的所有参数；删除 运行开关。

## 改前 → 改后

| 下拉行 | 对应 | 改后 |
|---|---|---|
| `🧮 主参数 M` | **流形引擎** (config/calib/zmax_manifold.json · M/inertia/度规) | 保留 (第 1 行) |
| `📏 数据总线` | **数据空间的 Trace** (`zmax_data/dataspace/trace_live.json`) | 保留 (第 2 行) |
| `🎛 标定真源` | 标定 9 段真源 (config/calib/zmax_calib.json) | **撤出下拉** (数字改从「参数中心」🟡标定 类看；对象保留不删) |
| `🔧 运行开关` | 6 个引擎开关 | **撤出下拉** (开关本体保留，仍在主界面「参数中心」🟠开关 类可改) |
| `🎛 参数中心` | **数据库服务** (工程库只读服务 `127.0.0.1:8798/params`，817 条 = 全库参数) | **新增** (第 3 行) |

## 实现要点 (都不是"只写日志"，全部真跑)

- `tools/engineering_db.py`：`serve()` 新增 `GET /params` → `{total, by_cat, params[]}`，
  走独立读取 `load_params()`（不动 `load()` 的形状 ⇒ `export_json`/`/summary` 零回退）。
- `tools/gui/model_tree.py`：
  - `cmb_view` 3 行；`VIEW_KEYS = ("mparam", "bus", "param_center")`；存档段 `available_views` 同源。
  - 新控件 `ParamCenterSideView`：读服务 `/params`，显示 总数/分类计数/搜索/紧凑表/刷新；
    **只显示不改数**（改数唯一入口 = 主界面「参数中心」页，避免两条写路径）；服务没起时诚实空态
    (给启动命令)，不拿 0 或旧值冒充。
  - `calib` / `run_cfg` 两页控件对象**保留但不进可见布局** ⇒ 引擎里 40 处 `self.chk_*` 读法、
    标定真源对象零改动（6 个开关"同一对象"判据仍绿）。
- `tools/gui/simulink_module.py`：`_show_run_cfg()` 不再跳页，如实说明页面已撤出 + 开关在哪改。
- `tools/gui/project_file.py`：`available_views` 与 `VIEW_KEYS` 同源 (旧存档里的 `calib`/`run_cfg` 被安全忽略)。

## 顺带修掉的两个真缺陷 (判据当场抓到)

1. **主参数 M 页会覆盖真源**：该页原来只读**画布节点**的 M (`n_calib_mani.params.M` 画布默认 1.0)，
   而真源 `config/calib/zmax_manifold.json` 的 M 是现场标定值 **3.643** ⇒ 页面显示 1.0，
   一按「✏️ 写 M」就把真源 3.643 覆盖成 1.0。
   改：微调框**以真源为准**（真源没有才退回节点值），两者不一致时页头标 `⚠真源≠节点`（值在悬浮提示里）。
2. **注册表少 58 条 ⇒ 两张表总数对不上**：单一工程库 `engineering_db.build` 早已把
   `config/platform/zmax_perf_spec.json` 的 58 条性能指标按 `kind='spec'` 入库，
   而 `param_registry.registry()` 没有对应扫描器 ⇒ 注册表 759 vs 库 817。
   改：补 `scan_perf_spec()`（同一份真源、只读、`status=已定义(目标值)`）⇒ **817 == 817**。

## 判据

| 判据 | 结果 |
|---|---|
| `tools/verify_sidebar_views.py` (新) | **9/9** (下拉 3 行 · 三页真切换 · 参数中心 817 行 == 服务 817 · 撤下两页对象在且永不显示 · 6 开关同一对象 · `view_is` 表驱动 · 存档同源 · 三页出图) |
| `tools/verify_mparam_page.py` | 全绿 (③ 改为"微调框 == 真源 M"，④ 判据自己不再制造脏写) |
| `tools/verify_run_cfg_panel.py` | 全绿 (⑤ 改为 3 视图映射；运行开关不在下拉) |
| `tools/verify_calib_measure.py` | 全绿 (下拉 3 行；标定 9→10 段从真源推) |
| `tools/verify_ui_slim.py` | **67/67** (⑤ 改为「UI 文案字数 ≤ 预算，表格数据不计」+ 数据行不许为好看被删) |
| `tools/verify_param_center.py` | 全绿 (库 params 817 == 注册表 817) |
| `tools/verify_platform_spec.py` | 18/18 (散落在 `data/database/zmax/` 的 3 个 `.bak_*` 挪进 `archive/`) |

出图：`reports/ui_shots/sidebar_mparam.png` · `sidebar_bus.png` · `sidebar_param_center.png` (离屏真建渲染)、
`reports/ui_shots/sidebar_3views_mparam.png` (在役控制台窗口截图，下拉 3 行)。
