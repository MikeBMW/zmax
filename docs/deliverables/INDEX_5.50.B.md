# Z-MAX 5.50.B 交付文档包 · 汇总索引

文档编号: ZMAX-IDX-5.50.B-20261013 · 版本: v1.0
编制: Z-MAX 工程组 · 日期: 2026-10-13 · 适用版本: 5.50.B（Z-MAX 优化配置版；对应开发版 5.50.2）
工程: `/home/ubuntu/zmax` · 对外口径:「符合 5 个场景的具身方案技术协议」

> 本索引汇总 5.50.B 交付文档包的全部文件、编号、适读对象与真源依据。所有数字取自工程真源并可复核；未实测项一律标注「待实测/待核」。

---

## 1. 交付文档清单

| # | 文档 | 编号 | 文件 | 适读对象 |
|:--|:---|:---|:---|:---|
| 1 | 功能说明（5.50.B） | ZMAX-FUNC-20261013 | `docs/deliverables/功能说明_Z-MAX_5.50.B_20261013.md` | 客户 / 供应商 / 内部 |
| 2 | 全系统配置清单（5.50.B） | ZMAX-CFGL-20261013 | `docs/deliverables/全系统配置清单_Z-MAX_5.50.B_20261013.md` | 客户 / 供应商 / 运维 |
| 3 | 供应商 SOR（5.50.B） | ZMAX-SOR-20261013 | `docs/deliverables/SOR_Z-MAX_5.50.B_20261013.md` | 供应商 / 整机厂 |
| 4 | 项目立项文档（5.50.B） | ZMAX-CHTR-20261013 | `docs/deliverables/立项文档_Z-MAX_5.50.B_20261013.md` | 内部 / 评审 |
| 5 | 版本策略（5.50.A/B/C） | ZMAX-VSEM-20261013 | `docs/deliverables/版本策略_5.50.A_B_C.md` | 内部 / 客户 |
| 6 | 本索引 | ZMAX-IDX-5.50.B-20261013 | `docs/deliverables/INDEX_5.50.B.md` | 全部 |

**配套机读/历史件**

| 文件 | 说明 |
|:---|:---|
| `docs/deliverables/全系统配置清单_5.50.B.md` / `.json` | 在役系统扫描件（由 `tools/delivery/gen_config_inventory.py` 生成，每个数可回读） |
| `docs/deliverables/功能说明_5.50.A.md` | 5.50.A 原型产品发布版功能说明（上一号段） |
| `docs/deliverables/全系统配置清单_5.50.A.md` / `.json` | 5.50.A 扫描件 |
| `docs/deliverables/{原型验证测试报告,任务配置单,功能清单,项目立项文档,供应商SOR}_Z-MAX_20261012.md` | 2026-10-12 首批交付文档 |

**2026-10-13 追加导出（配置中心现取 · 摆盘项目）**

| # | 文档 | 文件 | 真源 | 备注 |
|:--|:---|:---|:---|:---|
| A | 全系统总配置清单（刷新） | `docs/deliverables/全系统配置清单_5.50.B.md` / `.json` | 在役系统扫描 + 单一工程库 | 新增「配置关联性」章（links 389 · param_links 1767 · 任务关联 7）；画布口径修正为被绑定方 89 节点/184 连线 |
| B | 供应商外发 SOR · 摆盘 TASK-06-TRAY | `docs/deliverables/供应商SOR_摆盘_TASK-06-TRAY_5.50.B_20261013.md` / `.docx` / `.json` / `.manifest.json` | 单一工程库 + `config/tasks/tasks.json` + `config/platform/zmax_perf_spec.json` + 项目档案 PROJ-TH-TRAY | 章节 1–15 + 附录 A–G；新增 附录 E 配置表关联性（需求↔配置项追溯矩阵）· 附录 F 架构兼容性 · 附录 G 任务迁移。**md 为 Word 版原序渲染（同源同内容，自动同步）** |
| C | SOR 导出器（可复跑到最新） | `tools/sor_export.py` | — | 复跑：`gui-venv311/bin/python tools/sor_export.py --project PROJ-TH-TRAY --task TASK-06-TRAY --json` |
| D | 交付包（飞书发送件） | `docs/deliverables/Z-MAX_交付文档_摆盘TASK-06-TRAY_5.50.B_20261013.zip` + `README_交付包_摆盘TASK-06-TRAY_5.50.B.md` | — | 7 件打包（117,518 B · sha256 `f9049c6e…`）；README = 包内说明 + 已证明/未证明两段 + 复核命令 |

> 交付分工口径（本批明确）：**供应商研制摆盘作业具身模型（L3）· 我方做工程集成与收口（L2 执行链接入 / 几何真值 / 安全红线）**。见 SOR 第 2.1 节交付分工表。

---

## 2. 每条文档的编号行与引用真源

| 文档 | 编号行 | 主要真源 |
|:---|:---|:---|
| 功能说明 | `ZMAX-FUNC-20261013 · 版本: v1.0` · 编制/日期/适用版本 | `config/ss_task_binding.json` · `config/calib/*.json` · `zmax_data/dataspace/busdb.json` · `tools/verify_*.py` |
| 全系统配置清单 | `ZMAX-CFGL-20261013 · 版本: v1.0` · 编制/日期/适用版本 | `tools/delivery/gen_config_inventory.py` 扫描 + 各 config/键路径 |
| SOR | `ZMAX-SOR-20261013 · 版本: v1.0` · 编制/日期/适用版本 | `config/platform/zmax_perf_spec.json` · `config/tasks/tasks.json` · `tools/aoi_link.py` |
| 立项文档 | `ZMAX-CHTR-20261013 · 版本: v1.0` · 编制/日期/适用版本 | `config/platform/zmax_project_bom.json` · `config/platform/zmax_platform.json` · `zmax_perf_spec.json` |
| 版本策略 | `ZMAX-VSEM-20261013 · 版本: v1.0` · 编制/日期/适用版本 | `VERSION.md` |

---

## 3. 本版（5.50.B）核心交付点（判据可复跑）

| 能力 | 判据脚本 | 结果 |
|:---|:---|:---|
| 主参数 M（度量张量） | `tools/verify_metric_main_param.py` | **23/23 PASS** |
| 健康度 H 与流形引擎闭环 | `tools/verify_engine_loop.py` | **20/20 PASS** |
| 配置单 → M 映射 | `tools/verify_config_to_M.py` | **51/51 PASS** |
| 配置中心配置导入节点 | `tools/verify_node_cfg_import.py` | **15/15 PASS** |
| 数据总线每节点独立输出 topic | `tools/verify_ss_bus_topics.py` | **14/14 PASS** |
| 全系统总配置清单（扫描） | `tools/delivery/gen_config_inventory.py` | 产物可回读 |
| 画布工具栏「配置中心独立窗口」 | **待核**（本批次代码，判据待补） | — |
| 「元数据MOE门控路由」节点改名 | `tools/meta_moe_router.py report`（可运行核） | **待核**（判据待补） |

> 复跑命令：
> ```bash
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_metric_main_param.py
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_engine_loop.py
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_to_M.py
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_node_cfg_import.py
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_ss_bus_topics.py
> gui-venv311/bin/python tools/delivery/gen_config_inventory.py --ver 5.50.B
> ```

---

## 4. 待实测 / 待核清单（跨文档汇总 · 诚实列出）

| # | 条目 | 现状 | 出现在 | 取数命令 / 入口 |
|:--|:---|:---|:---|:---|
| 1 | 取放成功率 **≥99%** | **待现场实测** | SOR §5 · 功能说明 §6 · 立项 §6 | 现场连续作业逐件记录（`perf.success_rate.how`） |
| 2 | 单颗节拍 **≤3.15s** | **待现场实测** | SOR §5 · 功能说明 §6 | `perf.cycle_s.how`（CT 起止：吸取离盘→下一位就位） |
| 3 | 全部 58 条 `perf.*` | **待实测**（真源 `value` 空） | SOR §5 · 功能说明 §6 · 配置清单 §9 | `zmax_perf_spec.json` 逐条 `how` |
| 4 | 目标值待定/待确认 10 项 | **待厂家/现场给定** | SOR §5 | `perf.contact_pressure`·`mate_life`·`coplanarity`·`conn_mate_force`·`opm_res`·`cleanliness`·`temp_hum`·`noise`·`mtbf`·`anomaly_recovery` |
| 5 | 站点几何 `T_base_cam`/`plane_z`/`cell_geometry.points` | **未标定**（真源 null） | 全篇 | `config/calib/zmax_calib.json` + `_reason` 现场命令 |
| 6 | 「配置中心独立窗口」一致性 | **待核**（本批次代码，无独立判据） | 功能说明 §3.2/§6 | 画布工具栏点「🗂 配置中心」 |
| 7 | 「元数据MOE门控路由」节点 | **待核**（判据待补） | 功能说明 §3.2 · 立项 §3.4 | `python3 tools/meta_moe_router.py report` |
| 8 | 各层「模型是否真在回路」 | **待核** | 功能说明 §2 | `python3 tools/audit_full_chain.py` |
| 9 | 深度通道帧率 | **0 fps / 卡死** | 配置清单 §5/§9 | `curl -s http://127.0.0.1:8791/api/cams` |
| 10 | 动作块下发频率 ≥10Hz | **未纳入诊断断言** | SOR §3.4/§5 | 需补断言并实测标定 |
| 11 | 动态项（活跃任务 / 画布结构指纹 / 帧率） | 扫描时点值，随现场变动 | 配置清单 §9 | 当次回读 |
| 12 | 5.50.C 量产交付版 | **未发布**（准入项 C1–C5 均待现场实测） | 版本策略 §2.3 | — |

---

## 5. 引用真源清单（跨文档汇总）

| 真源文件 | 用途 |
|:---|:---|
| `config/ss_task_binding.json` | 任务 ↔ 场景绑定（`active_task` · 89 节点/184 连线 · 覆盖度） |
| `config/tasks/tasks.json` | 任务配置（7 任务 · 每任务 targets/工序） |
| `config/topics/scene_tags.json` | 信号 → 场景标签与色标 |
| `config/platform/zmax_perf_spec.json` | 性能指标（6 组 58 条 + 8 标准） |
| `config/platform/zmax_project_bom.json` | BOM/成本/ROI/里程碑/团队/风险 |
| `config/platform/zmax_platform.json` | 平台/产品/子系统架构 |
| `config/calib/zmax_calib.json` | 标定参数注册表（内参/未标定项） |
| `config/calib/zmax_manifold.json` | 主参数 M / 度量形状（M=3.643 · dim=6 · mode=diag） |
| `config/calib/zmax_health.json` | 健康度 H 分级阈值 |
| `data/database/zmax/zmax_space.proj` | 总工程文件 |
| `data/database/zmax/zmax_engineering.db` | 单一工程库 |
| `data/database/zmax/sources/canvas/state_space_obs.json` | 画布真源（89 节点 / 184 连线） |
| `zmax_data/dataspace/busdb.json` | 数据总线 DBC 真源（节点/信号/报文） |
| `src/lerobot/manifold/{metric_field.py,health.py,engine_loop.py}` | 流形/健康度/引擎闭环实现 |
| `src/lerobot/engineering/nodes/library.py` | 画布节点实现（配置导入/主参数 M） |
| `src/lerobot/policies/left_right/state_space/{planner.py,safety.py}` | L5 规划/安全 |
| `tools/{config_to_M.py,ss_bus_topics.py,meta_moe_router.py,engineering_db.py,ss_task_bind.py}` | 映射/总线/门控路由/工程库/任务绑定 |
| `tools/delivery/gen_config_inventory.py` | 全系统总配置清单生成器 |
| `tools/verify_{metric_main_param,engine_loop,config_to_M,node_cfg_import,ss_bus_topics}.py` | 判据脚本 |
| `VERSION.md` | 版本管理规范与历史 |
| `models/active_models.json` | 各层在役模型指针 |

---

## 6. 复核与再生成

```bash
# 1) 复跑 5 条判据
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_metric_main_param.py   # 23/23
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_engine_loop.py         # 20/20
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_to_M.py         # 51/51
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_node_cfg_import.py     # 15/15
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_ss_bus_topics.py       # 14/14

# 2) 重新扫描全系统配置清单
gui-venv311/bin/python tools/delivery/gen_config_inventory.py --ver 5.50.B
```

---

*本索引所引数字均来自工程真源与 2026-10-13 在役系统扫描；未实测/未核项一律标注，不作推测。*
