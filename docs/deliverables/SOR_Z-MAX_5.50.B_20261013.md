# Z-MAX 供应商需求规格书（SOR · 交付版 5.50.B）

文档编号: ZMAX-SOR-20261013 · 版本: v1.0
编制: Z-MAX 工程组 · 日期: 2026-10-13 · 适用版本: 5.50.B（Z-MAX 优化配置版；对应开发版 5.50.2）
密级: 对外发放（供应商 / 整机厂）
项目: 光模块工厂精细操作 · 对外口径:「符合 5 个场景的具身方案技术协议」

> 本文件面向供应商与整机厂，约定 Z-MAX 平台在光模块精细操作场景下的**范围、交付物、接口、验收标准、里程碑**。
> 所有验收数字引工程真源（`config/platform/zmax_perf_spec.json` 等），标注指标 id；**凡真源 `value` 为空者一律标注「待实测」**并给出实测入口，不提供未经验证的数值。

---

## 1. 范围

### 1.1 五个场景（对外交付内容）

本项目技术交付内容为「**符合 5 个场景的具身方案技术协议**」，即围绕以下五个场景约定功能、性能、接口与验收：

| 编号 | 场景 | 说明 | 核心任务真源 |
|:--|:---|:---|:---|
| 1 | 插拔 | 电口金手指精细插装与拔出（含 FW/EEPROM 校验） | `TASK-01-FW` · `TASK-03-BI` · `TASK-04-THERMAL` · `TASK-05-ATS` |
| 2 | 摆盘 | 周转盘 → 上料 Tray 盘（30 槽）逐颗取放 | `TASK-06-TRAY` |
| 3 | AOI 光学质量检测 | 金手指（端口 10082）/ 表面（端口 10083）缺陷检测 | `TASK-07-AOI` |
| 4 | AR 标定叠加 | 多路相机底图 + 3D 位姿叠加 + L5 视觉理解 | `TASK-07-AOI`（AR 服务 `:8797`） |
| 5 | 数据闭环（CICD） | 边缘采集 → 中转 → 训练 → 部署 | 平台级 |

> 任务配置真源：`config/tasks/tasks.json`（7 任务）。任务 ↔ 场景映射：`tools/ss_scene_switch.py`；色标：`config/topics/scene_tags.json`。

### 1.2 本版（5.50.B 优化配置版）范围侧重

5.50.B 的重点是**可配置、可标定、可诊断、可复核**，具体在本版体现为：

| 项 | 内容 | 真源/判据 |
|:---|:---|:---|
| 主参数 M（度量张量） | 把系统特性做成可标定几何量 g_ij(x)=M·G_ij(x) | `src/lerobot/manifold/metric_field.py` · 判据 23/23 |
| 健康度 H + 引擎闭环 | 每帧标量健康度与五层闭环监督 | `src/lerobot/manifold/health.py` · 判据 20/20 |
| 配置单 → M 映射 | 任务配置单 → 主参数 M（显式规则可审计） | `tools/config_to_M.py` · 判据 51/51 |
| 配置导入节点 | 画布「主参数 M」节点加载配置中心全部配置 | 判据 15/15 |
| 数据总线每节点独立 topic | 89/89 节点各有独立输出 topic + 单步高亮 | `tools/ss_bus_topics.py` · 判据 14/14 |
| 全系统总配置清单 | 从在役系统扫出，每个数可回读 | `tools/delivery/gen_config_inventory.py` |

### 1.3 供货边界（交什么 / 不交什么）

**交付范围**

- L3 动作执行：将上游意图/条件转成可执行动作序列。
- 摆盘取放循环的策略与序列规划（取件 → 转运对位 → 放入 → 判态循环）。
- 多型号/多摆放自适应配方选择。
- 异常处置与断点续作决策。
- 运行状态与事件上报（阶段/成功/失败/异常码/断点/CT 计时）。
- 优化配置版交付物：主参数 M 与健康度 H 的配置、标定、诊断接口与判据；全系统总配置清单。

**不在范围**

- 不供相机/机械臂/夹爪/真空等硬件本体。
- 不供站点几何真值（`T_base_cam` / `plane_z` / `cell_geometry.points`）——现场标定。
- 不供安全红线（急停/限速/禁区）——只读消费，不产生否决权。
- 不供 L2 底层力控/伺服回路。

> 供货边界真源：`tools/sys1_delivery.py` `SCOPE_IN`/`SCOPE_OUT`。

---

## 2. 交付物

| 序号 | 交付物 | 形式/路径 | 状态 |
|:--|:---|:---|:---|
| 1 | 功能说明（5.50.B） | `docs/deliverables/功能说明_Z-MAX_5.50.B_20261013.md` | 已交付 |
| 2 | 全系统配置清单（5.50.B） | `docs/deliverables/全系统配置清单_Z-MAX_5.50.B_20261013.md`（+ 机读件 `全系统配置清单_5.50.B.{md,json}`） | 已交付 |
| 3 | 供应商 SOR（本文） | `docs/deliverables/SOR_Z-MAX_5.50.B_20261013.md` | 已交付 |
| 4 | 项目立项文档（5.50.B） | `docs/deliverables/立项文档_Z-MAX_5.50.B_20261013.md` | 已交付 |
| 5 | 版本策略 | `docs/deliverables/版本策略_5.50.A_B_C.md` | 已交付 |
| 6 | 交付文档包汇总索引 | `docs/deliverables/INDEX_5.50.B.md` | 已交付 |
| 7 | 性能指标体系 | 真源 `config/platform/zmax_perf_spec.json`（6 组 58 条 + 8 标准） | 真源在册 |
| 8 | 主参数 M 与健康度配置 | 真源 `config/calib/zmax_manifold.json` · `config/calib/zmax_health.json` | 真源在册 |
| 9 | 判据脚本集 | `tools/verify_{metric_main_param,engine_loop,config_to_M,node_cfg_import,ss_bus_topics}.py` | 已真跑（23/20/51/15/14 PASS） |
| 10 | 接口契约 | 真源 `tools/sys1_delivery.py` `CONTRACT` 段 | 真源在册 |

---

## 3. 接口要求

### 3.1 上游输入

| 来源 | 内容 |
|:---|:---|
| 认知决策层（意图/条件） | 任务号 + 物料型号 + 目标盘位/槽位策略 + 速度/力上限（只给意图，不给轨迹） |
| 感知域 | 目标位姿 `T_base_obj` · 抓取点/放置点 · 盘面槽位几何与占用状态 |
| 真值域 | 相机内参 `K` · 放置面 `plane_z` · `T_base_cam`（标定件，现场一次标定） |
| 图像域 | 腕部相机 RGB（工作距离 0.1–0.6m）+ 全局定位相机 |
| 状态域 | 关节/末端位姿 · 夹爪开合 · 真空压力 · 力/力矩 |

### 3.2 下游输出

| 去向 | 内容 |
|:---|:---|
| 基石执行层（执行） | 动作块（位姿序列 @ 推理步频）· 夹爪/真空指令 · 力控参数（L2 势函数收口） |
| 认知决策层（上报） | 阶段/成功/失败/异常码 · 断点信息 · 单颗 CT 计时 · 料盘空/满事件 |
| 交付配置面 | 主参数 M · 健康度 H/分级 · 动力 τ · 度量尺度（经 `tools/engine_bus_publish.py` 入总线） |

### 3.3 检测服务接口

| 服务 | 端口 | 调用方式 |
|:---|:---|:---|
| 金手指检测 | 10082 | `POST /capture_detect`（受理）→ 轮询 `GET /last_result`（判决） |
| 表面检测 | 10083 | 同口径；曝光 `GET /exposure`（只读）/ `POST /exposure?us=&gain=`（写） |
| AR 底图服务 | 8797 | `GET /api/cams` · `GET /snap/<cam>.jpg` · `GET /api/tcp` |

> 端口与调用口径真源：`tools/aoi_link.py`（`PORTS={"gf":10082,"housing":10083}`）· `tools/tcp_ar_server.py`。

### 3.4 节拍/时延接口口径

| 项 | 目标值 | 说明 |
|:---|:---|:---|
| 单颗 CT（PVT） | ≤3.15s | 起止口径写死：从吸取离盘到下一位就位 |
| 动作块下发 | ≥10Hz | **待实测标定**（缺口：未纳入诊断断言，需补） |
| 型号识别单帧 | ≤100ms | 统一取子项口径 |

> 接口契约真源：`tools/sys1_delivery.py` `CONTRACT`。

---

## 4. 验收标准

### 4.1 主验收判据（真源）

| 指标 | 判据 | 真源 id | 阶段 |
|:---|:---|:---|:---|
| 取放成功率 | **≥99%**（人工干预即记不完整成功） | `perf.success_rate` | PVT |
| 单颗节拍 CT | **≤3.15s**（五段预算合计 ≤3.15s） | `perf.cycle_s` / `perf.cycle_split` | PVT |
| 连续自主作业 | ≥12 盘周转盘（硬下限 ≥6） | `perf.endurance` | PVT |
| 换型时间 | ≤30min（12+ 型号） | `perf.changeover` | PVT |
| 料位识别准确率 | ≥99.9% | `perf.slot_accuracy` | PVT |
| 产能 UPH | ≥1100 颗/h（PVT） | `perf.uph` | PVT |
| 单颗取放精度 | 单边 ≤1mm · 角度 ≤1° | `config/ss_task_binding.json#tasks[TASK-06-TRAY].targets.取放精度` | — |

### 4.2 全量指标验收

以真源 `config/platform/zmax_perf_spec.json` **全部 58 条 `perf.*`** 为验收基准，分 **EVT / DVT / PVT** 三阶段，判据方法取各指标 `how` 字段。

| 组 | 名称 | 条数 |
|:--|:---|--:|
| A | 运动学与机械性能（ISO 9283 / 230-2） | 12 |
| B | 视觉与测量链 | 8 |
| C | 电口（金手指）精细插装 | 10 |
| D | 光口 · 光纤 · 光耦合 | 12 |
| E | 节拍 · 吞吐 · 可靠性 | 8 |
| F | 环境 · ESD · 洁净度 · 安全 | 8 |
| — | **合计** | **58** |

> 复核：`gui-venv311/bin/python -c "import json;d=json.load(open('config/platform/zmax_perf_spec.json'));print('组',len(d['groups']),'条',sum(len(g['metrics']) for g in d['groups']),'标准',len(d['standards']))"` → **组 6 条 58 标准 8**。

### 4.3 工程侧质量门

| 门 | 内容 | 判据脚本 / 结果 |
|:---|:---|:---|
| 主参数 M 几何口径 | 独立分量数/联络/曲率/零回归/写盘闸门 | `tools/verify_metric_main_param.py` → **23/23 PASS** |
| 引擎闭环完整性 | 五层真跑/记忆上行/L4 真否决/零回归 | `tools/verify_engine_loop.py` → **20/20 PASS** |
| 配置单 → M 映射 | 幂等/闸门/审计 sha 一致 | `tools/verify_config_to_M.py` → **51/51 PASS** |
| 配置导入节点 | 装载/指导项/画布未回归(89/184) | `tools/verify_node_cfg_import.py` → **15/15 PASS** |
| 数据总线每节点 topic | 89/89 独立 topic + 单步高亮 + 性能闸 | `tools/verify_ss_bus_topics.py` → **14/14 PASS** |
| 工程库一致性 | 画布/参数/链接 | `python3 tools/engineering_db.py check` |

### 4.4 引用标准

ISO 9283 · ISO 230-2 · ISO 9787 · IEC 61300-3-35 · IEC 61753 / GR-326 · ANSI/ESD S20.20 · ISO 14644-1 · ISO 13849-1（真源 `zmax_perf_spec.json#standards`，共 8 项）。

---

## 5. 待实测清单（强制知会 · 诚实列出）

下列项在工程真源中**尚无实测值**，供应商报价与承诺须以「目标值 + 实测入口」为依据，不得引用未经验证的实测数据：

| # | 项 | 现状 | 实测入口 |
|:--|:---|:---|:---|
| 1 | **取放成功率 ≥99%** | **待现场实测** — 真源 `perf.success_rate` 为 PVT 目标，无实测值；需现场连续作业逐件记录成功/干预 | SOR §4.1 判据 + `perf.success_rate.how` |
| 2 | **单颗节拍 ≤3.15s** | **待现场实测** — 真源 `perf.cycle_s` 为 PVT 目标；SIL 阶段实测摆盘已超口径 | `perf.cycle_s.how`（CT 起止：吸取离盘→下一位就位） |
| 3 | 全部 58 条 `perf.*` | **待实测**（真源 `value` 为空） | 逐条 `how` 字段 |
| 4 | 目标值本身待定/待确认 | `perf.contact_pressure` · `perf.mate_life` · `perf.coplanarity` · `perf.conn_mate_force` · `perf.opm_res`(采样率口径) · `perf.cleanliness` · `perf.temp_hum` · `perf.noise` · `perf.mtbf` · `perf.anomaly_recovery` | 需端子/连接器厂家或现场条件给定 |
| 5 | 站点几何 | `T_base_cam` / `plane_z` / `cell_geometry.points` 未标定（真源 null） | `config/calib/zmax_calib.json` 对应键 + `_reason` 中的现场标定命令 |
| 6 | 动作块下发频率 ≥10Hz | 未纳入诊断断言 | 需补断言并实测标定 |
| 7 | 深度通道帧率 | 扫描值 0 fps / 卡死 | `curl -s http://127.0.0.1:8791/api/cams` |

> 缺口真源：`tools/sys1_delivery.py` `GAPS`；环境项 `perf.*` F 组真源 `value` 为空。

---

## 6. 里程碑（EVT / DVT / PVT）

| 阶段 | 名称 | 目标指标（真源口径） | 计划节点 |
|:---|:---|:---|:---|
| EVT | 对内 Demo | 取放成功率 ≥90% · 单颗 20–25s | 2026-10-30 |
| DVT | 对外 POC 功能测试 | 成功率 ≥95% · 单颗 ≤8s · 连续 ≥6 盘无干预 | 2026-12-20 |
| — | 技术协议/商务备忘签订 | — | 2026-12-25 |
| PVT | 达到对外交付指标 | CT ≤3.15s · 成功率 ≥99% · 连续 ≥12 盘 | 2027-04-15 |

> 里程碑真源：`config/platform/zmax_project_bom.json` `project.milestones`。

---

## 7. 术语表

| 术语 | 说明 |
|:---|:---|
| SOR | Statement of Requirements，需求规格/技术要求书 |
| EVT/DVT/PVT | 工程验证 / 设计验证 / 生产验证 |
| CT | Cycle Time，单颗取放周期 |
| UPH | Units Per Hour，每小时产能 |
| AOI | Automated Optical Inspection，自动光学检测 |
| AR | Augmented Reality，增强现实（底图叠加） |
| M | 主参数（度量张量尺度）· H 健康度 · τ 动力 |
| L5/L4/L3/L2 | 平台四层：规划 / 认知监督 / 调度 / 检测执行 |

---

*本文件所引验收数字均来自工程真源 `config/platform/zmax_perf_spec.json` 等；未实测项一律标注「待实测」并给出入口。*
