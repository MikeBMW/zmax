# Z-MAX 功能说明（交付版 5.50.B）

文档编号: ZMAX-FUNC-20261013 · 版本: v1.0
编制: Z-MAX 工程组 · 日期: 2026-10-13 · 适用版本: 5.50.B（Z-MAX 优化配置版；对应开发版 5.50.2）
适用场景: 光模块工厂精细操作（插拔 / 摆盘 / 光学质量检测）· 对外口径:「符合 5 个场景的具身方案技术协议」

> 本说明逐条给出：功能名 / 做什么 / 唯一依据文件 / 验证方式（判据脚本名）/ 当前状态。
> **所有数字均取自工程唯一依据并可复核；凡未实测或未核出处者，一律标注「待现场实测」/「待核」并给出取数命令，不作推测。**

---

## 0. 版本语义与本文档定位

| 版本号段 | 语义 | 产物重点 |
|:---|:---|:---|
| **5.50.A** | 原型产品发布版 | 原型创新（新功能原型落地） |
| **5.50.B** | 优化配置版 | 优化 · 标定 · 诊断 · 配置（本文件所描述版本） |
| **5.50.C** | 量产交付版 | 量产交付（详见《版本策略_5.50.A_B_C.md》） |

本文件即 5.50.B（优化配置版）的功能说明。相较 5.50.A，5.50.B 的重点是**把系统能力做成可配置、可标定、可诊断、可复核的对外交付口径**。

---

## 1. 产品定位

Z-MAX 是面向光模块工厂精细操作工序的**具身智能机器人平台**。它以「状态空间」为核心数据结构、以「配置驱动」为功能切换方式，用一台工控计算机 + 珞石机械臂 + 多路工业相机，覆盖从**上料、插拔、摆盘、光学检测到数据闭环**的完整工序链。

三个设计原则（唯一依据口径，见 `config/platform/zmax_platform.json`）：

| 原则 | 含义 | 在系统中的体现 |
|:---|:---|:---|
| **配置驱动** | 改功能不改代码 | 任务/场景/档位由 `config/ss_task_binding.json` 与画布唯一依据共同决定 |
| **逐层收窄可行域** | 上层只给意图与条件，执行永远由最下层收口 | L5 规划 → L4 认知监督 → L3 调度 → L2 检测/执行 |
| **安全由下层保障** | 稳定性由势函数/守卫保证，不依赖上层正确 | L2 势场 + 逐轴相关性闸 + 运动包络/天花板/抬升闸 |

---

## 2. 系统分层与能力（按 L5 / L4 / L3 / L2）

| 层 | 名称 | 职责 | 唯一依据实现位置 |
|:---|:---|:---|:---|
| **L5** | 规划 / 安全（造数据 · 下指令） | 任务拆解、阶段链规划、安全约束（意图与条件） | `src/lerobot/policies/left_right/state_space/planner.py` · `.../safety.py` |
| **L4** | 认知 / 监督 | 世界模型预判与恢复、意图解码、专家监督与否决 | `src/lerobot/manifold/engine_loop.py`（L4 监督真否决） |
| **L3** | 调度 | 阶段链调度、档位参数、序列规划 | 策略侧 `src/lerobot/policies/`（SmolVLA/LEW 运行时 ckpt，指针 `models/active_models.json`） |
| **L2** | 检测 / 执行收口 | 安全层 + 运动学 + 原子技能 + 肌肉记忆 + 收口闸 | `src/lerobot/engineering/nodes/library.py` · `models/yolo_peg_live.pt` |

> 分层与子系统唯一依据：`config/platform/zmax_platform.json`。功能节点唯一依据：工程库 `data/database/zmax/zmax_engineering.db`（`functions` 表）。
> ⚠️ **待核**：L5/L4/L3/L2 各层的「模型是否真在回路」逐层证据，历史口径见 `reports/SUMMARY_v5.37.3.md` 与 `docs/deliverables/` 旧文档；本版未重跑该逐层取证。核验入口：`python3 tools/audit_full_chain.py`（**待现场实测/待核**）。

---

## 3. 功能清单（按分组）

### 3.1 结构化流形 / 引擎（本版核心）

| # | 功能名 | 做什么 | 唯一依据文件 | 验证方式（判据脚本） | 当前状态 |
|:--|:---|:---|:---|:---|:---|
| E1 | **主参数 M（度量张量）** | 把「参数之间怎么互相影响」建成可标定矩阵 g_ij(x) = M·G_ij(x)，`det G = 1`；M 为整体尺度（范围 [0,8]），G 为形状（各向异性 + 状态相关） | `src/lerobot/manifold/metric_field.py` · 配置 `config/calib/zmax_manifold.json` | `tools/verify_metric_main_param.py` → **实测 23/23 PASS** | **在役** |
| E2 | **健康度 H 与分级** | 每帧输出标量健康度 H=(1/κ)·λ_min（κ=λ_max/λ_min），按阈值分级 | `src/lerobot/manifold/health.py` · 阈值 `config/calib/zmax_health.json` | `tools/verify_engine_loop.py`（含 H 分级）→ **20/20 PASS** | **在役** |
| E3 | **流形引擎闭环** | 度量→H→动力 τ→L5/L4/L3/L2 五层→记忆上行→L5 汇总指挥；L4 真否决 | `src/lerobot/manifold/engine_loop.py` | `tools/verify_engine_loop.py` → **实测 20/20 PASS** | **在役** |
| E4 | **配置单 → M 映射** | 读任务配置单，按显式规则表 R1–R5 算出 M 的分量（可审计） | `tools/config_to_M.py` | `tools/verify_config_to_M.py` → **实测 51/51 PASS** | **在役** |
| E5 | **配置中心配置导入节点** | 画布「主参数 M」节点加载配置中心全部配置（json/yaml/工程库），直接指导模型 | `src/lerobot/engineering/nodes/library.py`（`node_ss_calib_mani`）· `tools/config_center_load.py` | `tools/verify_node_cfg_import.py` → **实测 15/15 PASS** | **在役** |

配置唯一依据当前值（`config/calib/zmax_manifold.json#M` / `#metric`）：**M = 3.643 · dim = 6 · mode = diag · diag = [10,10,50,10,10,10] · range = [0,8]**。
健康度分级阈值（`config/calib/zmax_health.json#grades`）：**excellent 0.5 · good 0.1 · warning 0.01**（即 H>0.5 优秀 / 0.1–0.5 良好 / 0.01–0.1 警告 / ≤0.01 危险）。

### 3.2 平台 / 数据空间（本版新增）

| # | 功能名 | 做什么 | 唯一依据文件 | 验证方式（判据脚本） | 当前状态 |
|:--|:---|:---|:---|:---|:---|
| P1 | **数据总线每节点独立输出 topic** | 每个画布节点各有 ≥1 个独立输出 topic（89/89），有出线的用唯一依据 topic、无出线的用合成 topic（不覆盖唯一依据） | `tools/ss_bus_topics.py` · 总线唯一依据 `zmax_data/dataspace/busdb.json` | `tools/verify_ss_bus_topics.py` → **实测 14/14 PASS** | **在役** |
| P2 | **单步运行高亮当前节点输出 topic** | 单步运行 → 真序列化（trace 追加一行 + step_current 指针）+ 数据总线视图**置顶+金色**高亮；**整体运行不序列化（性能闸）** | `tools/gui/simulink_module.py`（`_run_node_single`）· `tools/ss_bus_topics.py` | `tools/verify_ss_bus_topics.py` ④⑤⑥⑩ → **14/14 PASS 内含** | **在役** |
| P3 | **全系统总配置清单（扫描生成器）** | 从**在役系统**扫出全系统总配置清单（md+json），每个数可回读复核（版本/端口/systemd/cron/配置 sha256/任务场景/模型/相机AOI/数据空间/画布/环境） | `tools/delivery/gen_config_inventory.py` | 产物 `docs/deliverables/全系统配置清单_5.50.B_20261013.md`（可回读） | **在役** |
| P4 | **画布工具栏新增「配置中心独立窗口」** | 画布工具栏新增按钮，打开配置中心独立窗口；与主控制台**同一唯一依据**（打开即重读磁盘、每 3s 对齐指纹），再点置顶复用 | `tools/gui/simulink_module.py`（`open_config_window`，本批次新增） | **待核**（本批次代码在开发工作区，尚无独立判据脚本；核验入口：控制台画布工具栏点「🗂 配置中心」） | **建设中（本批次）** |
| P5 | **「元数据MOE门控路由」节点改名** | 原「阶段专家MOE门控路由」节点改名为「**元数据MOE门控路由**」；实现元数据（根服务）→ topic（原子/分子）→ 映射关系（全息系统）→ 硬先验门控路由 | `tools/meta_moe_router.py`（本批次新增）· 唯一依据 `zmax_data/dataspace/busdb.json` | 可运行核 CLI：`python3 tools/meta_moe_router.py report\|holography\|route` | **建设中（本批次，判据待补）** |

### 3.3 画布 / 工程库

| # | 功能名 | 做什么 | 唯一依据文件 | 验证方式 | 当前状态 |
|:--|:---|:---|:---|:---|:---|
| C1 | **状态空间画布（89 节点 / 184 连线）** | 一个工程承载全部任务；节点可插拔、可拖拽、可增删 | `data/database/zmax/sources/canvas/state_space_obs.json`（结构指纹见 `config/ss_task_binding.json#project.canvas_md5`，随节点配置更新） | `tools/verify_node_cfg_import.py` ⑨（89 节点/184 连线未回归） | **在役** |
| C2 | **单一工程库** | 一个 `.db` = 一套工程（平台/功能/画布/参数等），支持 `build`/`check` | `data/database/zmax/zmax_engineering.db` · 工具 `tools/engineering_db.py` | `python3 tools/engineering_db.py check` | **在役** |
| C3 | **任务 ↔ 场景绑定** | 一个工程承载 7 个任务；按任务机械推导启用/禁用节点集 | `config/ss_task_binding.json`（`active_task` = `TASK-01-FW`） | `python3 tools/ss_task_bind.py --check` | **在役** |

### 3.4 数据空间（DDS 中间件）

| # | 功能名 | 做什么 | 唯一依据文件 | 验证方式 | 当前状态 |
|:--|:---|:---|:---|:---|:---|
| D1 | **总线 DBC 唯一依据** | 节点/信号/报文定义：89 节点 · 271 信号 · 16 报文（按层 L2 26 / L3 5 / L4 18 / L5 11 / meta 14；合成 topic 89） | `zmax_data/dataspace/busdb.json` | `python3 -c "import json;d=json.load(open('zmax_data/dataspace/busdb.json'));print(d['counts'])"` | **在役** |
| D2 | **话题注册表** | DDS 话题清单（生产者/消费者/质量判据） | `src/lerobot/dataspace/topics.py` | `tools/dds_verify_real.py selftest` | **在役** |

### 3.5 任务场景（5 个场景 · 7 个任务）

| 场景 | 色标 | 说明 | 核心任务唯一依据 | 状态 |
|:---|:---|:---|:---|:---|
| 插拔 | 绿 `#2e8b57` | 电口金手指精细插装（含 FW/EEPROM 校验） | `TASK-01-FW` | **在役** |
| 摆盘 | 蓝 `#1f6feb` | 周转盘 → 上料 Tray 盘逐颗取放 | `TASK-06-TRAY` | **在役** |
| AR / AOI | 紫 `#8957e5` | 金手指(10082)/表面(10083)检测 + AR 底图叠加 | `TASK-07-AOI` | **在役** |
| 上下料搬运 | 基础白 `#ffffff`(未分类) | 料盘/治具搬运 | `TASK-02-HANDLE` | 已建模（**待现场**） |
| 老化/热海/ATS | 基础白 `#ffffff`(未分类) | 老化箱/柜体/线外检测插接 | `TASK-03-BI` · `TASK-04-THERMAL` · `TASK-05-ATS` | 已建模（**待现场**） |

> 色标唯一依据：`config/topics/scene_tags.json`（`colors` 段：插拔 `#2e8b57` / 摆盘 `#1f6feb` / AR `#8957e5` / 未分类 `#ffffff`）。
> 任务唯一依据：`config/tasks/tasks.json`（7 任务）；活跃任务唯一依据：`config/ss_task_binding.json#active_task`。

### 3.6 GUI / 交付与运维

| # | 功能名 | 做什么 | 唯一依据文件 | 状态 |
|:--|:---|:---|:---|:---|
| G1 | **PyQt5 控制台** | 配置中心 / 状态空间画布 / 3D 场景 / 信号分析 / 数据空间 / 文档中心 | `tools/gui/studio.py` | **在役** |
| G2 | **配置中心（独立窗口 + 主控制台）** | 任务/工艺/性能配置、活跃属性三态、场景列、文档配置；与主控制台同一唯一依据 | `tools/gui/veh6_config_page.py` · `tools/gui/simulink_module.py` | **在役**（独立窗口为本批次新增，见 P4） |
| G3 | **交付文档包** | 功能说明 / 全系统配置清单 / SOR / 立项 / 版本策略 + 汇总索引 | `docs/deliverables/` | **在役** |
| G4 | **AR 标定叠加服务** | AR 底图多路相机 + 3D 位姿叠加 + L5 视觉理解 | `tools/tcp_ar_server.py` · `tools/ar_l5_understand.py` · `tools/ar_aoi_bus.py` | **在役**（服务 `:8797`） |

---

## 4. 本版（5.50.1 → 5.50.B / 开发版 5.50.2）新增与变更

| # | 项目 | 结果（判据） |
|:--|:---|:---|
| 1 | 数据总线每节点独立输出 topic | 89/89 节点各有独立输出 topic；判据 `verify_ss_bus_topics.py` **14/14 PASS** |
| 2 | 单步运行高亮当前节点输出 topic | 置顶 + 金色高亮；**整体运行不序列化**（性能闸）；判据 14/14 内含 ④⑤⑥⑩ |
| 3 | 主参数 M（度量张量） | 判据 `verify_metric_main_param.py` **23/23 PASS** |
| 4 | 健康度 H 与流形引擎闭环 | 判据 `verify_engine_loop.py` **20/20 PASS** |
| 5 | 配置单 → M 映射 | 判据 `verify_config_to_M.py` **51/51 PASS** |
| 6 | 配置中心配置导入节点 | 判据 `verify_node_cfg_import.py` **15/15 PASS** |
| 7 | 画布工具栏「配置中心独立窗口」 | 本批次新增（`simulink_module.open_config_window`）；**判据待补** |
| 8 | 「元数据MOE门控路由」节点改名 | 本批次新增 `tools/meta_moe_router.py`（原「阶段专家MOE门控路由」）；**判据待补** |

> 复核命令（4 条判据 + 1 条总线判据，全部可复跑）：
> ```bash
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_metric_main_param.py   # 23/23 PASS
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_engine_loop.py         # 20/20 PASS
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_to_M.py         # 51/51 PASS
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_node_cfg_import.py     # 15/15 PASS
> QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_ss_bus_topics.py       # 14/14 PASS
> ```

---

## 5. 验收口径（不夸大）

1. **每次改动必须同口径对照**：有提升才算成果，未证明提升的不得进默认档。
2. **判据先定后跑**：判据写在前，跑完按判据报数；样本量 <20 不下结论。
3. **量具必须用判据自己的取像口**（AOI：`kind=origin`，`kind=judge` 为派生缓存图，不可做 A/B）。
4. **如实标注未达标项**：未实测项一律写「待现场实测」并给出取数命令。
5. **交付件中的数字必须可回读复核**：全系统配置清单由 `tools/delivery/gen_config_inventory.py` 从在役系统扫出。

---

## 6. 待现场实测 / 待核清单（诚实列出）

| # | 条目 | 现状 | 取数命令 / 核验入口 |
|:--|:---|:---|:---|
| 1 | 成功率 **≥99%** | **待现场实测** — 唯一依据 `perf.success_rate` 为 PVT 目标，尚无实测值 | 见 SOR 第 5 节 E 组；实测方法 `how` 字段（现场连续作业逐件记录成功/干预） |
| 2 | 节拍 **≤3.15s**（PVT） | **待现场实测** — 唯一依据 `perf.cycle_s`；SIL 阶段实测已超口径 | `python3 -c "import json;d=json.load(open('config/platform/zmax_perf_spec.json'))"` 查 `perf.cycle_s` |
| 3 | 全部 58 条 `perf.*` 指标 | **待现场实测**（唯一依据 `value` 为空） | SOR 第 5 节六表；逐条 `how` 为实测方法 |
| 4 | 「配置中心独立窗口」一致性 | **待核**（本批次代码在开发工作区，无独立判据） | 控制台画布工具栏点「🗂 配置中心」，再点一次核置顶复用 |
| 5 | 「元数据MOE门控路由」节点 | **待核**（可运行核已落地，判据待补） | `python3 tools/meta_moe_router.py report` |
| 6 | 各层「模型是否真在回路」 | **待核** — 未重跑逐层取证 | `python3 tools/audit_full_chain.py`（如不可用则**待现场实测**） |
| 7 | 站点几何 `T_base_cam` / `plane_z` / `cell_geometry.points` | **未标定**（唯一依据 `null`） | `config/calib/zmax_calib.json` 对应键；现场标定命令见其 `_reason` |

---

## 7. 唯一依据文件清单

| 唯一依据文件 | 用途 |
|:---|:---|
| `config/ss_task_binding.json` | 任务 ↔ 场景绑定（`active_task`、89 节点/184 连线、覆盖度） |
| `config/tasks/tasks.json` | 任务配置（7 任务） |
| `config/topics/scene_tags.json` | 信号 → 场景标签与色标 |
| `config/platform/zmax_perf_spec.json` | 性能指标（6 组 58 条 + 8 标准） |
| `config/calib/zmax_calib.json` | 标定参数注册表（相机内参/未标定项） |
| `config/calib/zmax_manifold.json` | 主参数 M / 度量形状（M=3.643 · dim=6 · mode=diag） |
| `config/calib/zmax_health.json` | 健康度 H 分级阈值 |
| `data/database/zmax/zmax_space.proj` | 总工程文件 |
| `data/database/zmax/zmax_engineering.db` | 单一工程库 |
| `data/database/zmax/sources/canvas/state_space_obs.json` | 画布唯一依据（89 节点 / 184 连线） |
| `zmax_data/dataspace/busdb.json` | 数据总线 DBC 唯一依据（节点/信号/报文） |
| `src/lerobot/manifold/{metric_field.py,health.py,engine_loop.py}` | 流形/健康度/引擎闭环实现 |
| `src/lerobot/engineering/nodes/library.py` | 配置导入 / 主参数 M 等画布节点实现 |
| `tools/{config_to_M.py,ss_bus_topics.py,meta_moe_router.py,engineering_db.py,ss_task_bind.py}` | 映射/总线/门控路由/工程库/任务绑定工具 |
| `tools/verify_{metric_main_param,engine_loop,config_to_M,node_cfg_import,ss_bus_topics}.py` | 判据脚本（23/20/51/15/14 PASS） |
| `tools/delivery/gen_config_inventory.py` | 全系统总配置清单生成器 |

---

*本说明所有判据数字均来自 2026-10-13 在本机真跑的输出；未实测/未核项一律标注，不作推测性结论。*
