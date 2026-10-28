# Z-MAX 具身智能机器人平台 · 项目立项文档（5.50.B）

文档编号: ZMAX-CHTR-20261013 · 版本: v1.0
编制: Z-MAX 工程组 · 日期: 2026-10-13 · 适用版本: 5.50.B（Z-MAX 优化配置版；对应开发版 5.50.2）
项目: 光模块工厂精细操作 · 对内外统一口径:「符合 5 个场景的具身方案技术协议」
密级: 内部

> 本文件用于项目立项评审。所有数字均引自工程唯一依据并可复核，文末给出唯一依据清单。凡唯一依据无实测值者一律标注「待实测」。

---

## 1. 立项背景与必要性

### 1.1 业务背景

光模块制造为高精度、多品种、小批量工序。现场作业包括：从满料周转盘逐颗取放光模块至上料 Tray 盘（摆盘）、电口金手指精细插装、光口光纤对接、光学质量检测（AOI）等。现状由人工完成，存在以下痛点：

- **节拍受限**：人工逐颗取放，节拍与稳定性依赖熟练度。
- **良率依赖人工**：对位精度、力控稳定性、端面洁净度难以标准化。
- **ESD / 洁净风险**：精细插装对手工防静电与洁净度要求高。

### 1.2 本版（5.50.B）立项必要性

5.50.A（原型产品发布版）已把原型创新落地；进入 **5.50.B（优化配置版）** 后，项目重心转向**让系统可配置、可标定、可诊断、可复核**——即把「原型能跑」升级为「配置可交付、指标可复核、标定可现场执行」。这是由 POC 走向量产交付（5.50.C）的必经阶段。

> 背景唯一依据：`config/platform/zmax_project_bom.json` `project`/`market` 段。

---

## 2. 项目目标

### 2.1 核心目标（唯一依据口径）

| 目标 | 唯一依据口径 | 唯一依据 id | 阶段 |
|:---|:---|:---|:---|
| 取放成功率 | ≥99% | `perf.success_rate` | PVT |
| 单颗取放节拍 CT | ≤3.15s | `perf.cycle_s` | PVT |
| 连续自主作业 | ≥12 盘周转盘（硬下限 ≥6） | `perf.endurance` | PVT |
| 单颗取放精度 | 单边 ≤1mm · 角度 ≤1° | `config/ss_task_binding.json#tasks[TASK-06-TRAY].targets.取放精度` | — |

### 2.2 本版（5.50.B）阶段性目标

| # | 目标 | 验收方式 |
|:--|:---|:---|
| 1 | 主参数 M（度量张量）几何口径成立 | 判据 `verify_metric_main_param.py` 23/23 PASS |
| 2 | 健康度 H 与流形引擎闭环成立 | 判据 `verify_engine_loop.py` 20/20 PASS |
| 3 | 配置单 → M 映射可审计 | 判据 `verify_config_to_M.py` 51/51 PASS |
| 4 | 配置导入节点接线成立 | 判据 `verify_node_cfg_import.py` 15/15 PASS |
| 5 | 数据总线每节点独立输出 topic | 判据 `verify_ss_bus_topics.py` 14/14 PASS |
| 6 | 全系统总配置清单可回读 | `tools/delivery/gen_config_inventory.py` 产物 |
| 7 | 「元数据MOE门控路由」节点改名并落地 | 可运行核 `tools/meta_moe_router.py` |

### 2.3 节拍口径（验收 vs 提优，二者分开）

- **验收口径（唯一依据，硬指标）**：单颗 CT **≤3.15s（PVT）**，拆解五段预算 `perf.cycle_split`：取件 ≤0.8 + 转运 ≤1.0 + 对位 ≤0.6 + 插入 ≤0.5 + 判态 ≤0.25 = ≤3.15s。CT 起止预先固定：**吸取离盘 → 下一位就位**。
- **提优目标（非验收口径）**：在验收达成基础上向 **<3s** 提优；作为工程追求值，不作为合同验收判据。

---

## 3. 技术路线

### 3.1 总体架构：四层解耦 + 一个工程承载全部任务

| 层 | 名称 | 职责 | 子系统 |
|:---|:---|:---|:---|
| L5 | 规划 / 造数据 | 任务拆解、阶段链规划、安全约束、自主进化 | System 2 |
| L4 | 认知 / 监督 | 世界模型预判与恢复、意图解码、专家监督与否决 | System 2 |
| L3 | 调度 | 阶段链调度、档位参数、序列规划 | System 1 |
| L2 | 检测 / 执行 | 安全层 + 运动学 + 原子技能 + 肌肉记忆 + 收口闸 | System 0 |

> 架构唯一依据：`config/platform/zmax_platform.json`；功能节点唯一依据：`data/database/zmax/zmax_engineering.db`（`functions` 表）。

### 3.2 核心技术一：主参数 M（度量张量）

流形引擎主参数为**随状态变化的度量张量**：

```
g_ij(x) = M · G_ij(x),   det G = 1,   M > 0,   M ∈ [0, 8]
```

- **M（标量）** = 度量整体尺度（等效惯量尺度）；各向同性时 `Γ=0` 且 `g^{kl}=δ^{kl}/M` ⇒ `a=F/M`，与旧标量语义逐字一致（**零回归**）。
- **G_ij(x)（det=1）** = 形状（各向异性 + 状态相关）；联络 Γ 对尺度不变 ⇒ **弯曲只由形状决定，尺度不产生曲率**。
- **独立分量数**：n(n+1)/2（3→6 · 6→21 · 16→136 · 43→946）。
- **健康度**：H=(1/κ)·λ_min，分级 >0.5 优秀 / 0.1–0.5 良好 / 0.01–0.1 警告 / ≤0.01 危险。
- **三种形状参数化**：`isotropic`（G=I 零回归）/ `diag`（每轴 n 参数）/ `full`（一般度量）。

唯一依据实现：`src/lerobot/manifold/metric_field.py`；配置唯一依据：`config/calib/zmax_manifold.json`（当前 M=3.643 · dim=6 · mode=diag · diag=[10,10,50,10,10,10]）；判据：`tools/verify_metric_main_param.py` → **23/23 PASS**。

### 3.3 核心技术二：五层闭环

```
度量 g_ij(x) → 健康度 H → 动力 τ → L5/L4/L3/L2 五层 → 记忆上行 → L5 汇总指挥
```

- 五层真跑 + 记忆四通道上行 + L5 汇总回写 + **L4 监督真否决**。
- 唯一依据实现：`src/lerobot/manifold/engine_loop.py`；判据：`tools/verify_engine_loop.py` → **20/20 PASS**。

### 3.4 核心技术三：元数据MOE门控路由（本版新落地）

原「阶段专家MOE门控路由」节点改名为「**元数据MOE门控路由**」。其口径（唯一依据 `tools/meta_moe_router.py`）：

| 层 | 对应 | 实现 |
|:--|:---|:---|
| ① 元数据 = 系统数据库根服务 | 基础核心组成（类似标准原子模型的玻色子/费米子） | `META_PRIMITIVES`：玻色子型（场/连续量）+ 费米子型（离散实体） |
| ② topic = 由元数据组合成的「原子/分子/有机物」 | 数据空间每条 topic | `COMPOSE`：每个 topic 的基元组合（显式规则表，可复核） |
| ③ 映射关系 + 全息系统 | topic × 基元映射 | `INCIDENCE` 矩阵 P(topic×基元) + 全息重构算子 |
| ④ 门控路由（硬先验，可复核） | 阶段 → 专家 1:1（单射） | `ROUTE`：路由熵 0 |

唯一依据：`zmax_data/dataspace/busdb.json`（节点/信号/报文）+ `config/calib/*.json`；CLI：`python3 tools/meta_moe_router.py report|holography|route`。

### 3.5 五场景技术实现

| 场景 | 技术实现（唯一依据文件） |
|:---|:---|
| 插拔 | 全链原子技能 SK01–SK08 + 板坐标系定位 + 接触流形 + 力控插拔保护（`src/lerobot/engineering/nodes/library.py`） |
| 摆盘 | 长程序列规划 + VLM 编码 + Flow-Matching 动作 + 肌肉记忆抓放循环 |
| AOI | 工控机 AOI 客户端（10082/10083）+ 在役 YOLO（`models/yolo_peg_live.pt`）+ AR 底图联合检查 |
| AR 叠加 | AR 服务 `:8797` 多路相机底图 + L5 视觉理解桥（`tools/tcp_ar_server.py` · `tools/ar_l5_understand.py`） |
| 数据闭环 | 边缘采集 → 中转 → 训练 → 部署（`tools/cicd_pipeline.py` 等） |

### 3.6 在役模型

| 层 | 模型 | 路径（唯一依据 `models/active_models.json`） |
|:---|:---|:---|
| L2 | YOLO 光模块检测（真机域） | `models/yolo_peg_live.pt` |
| L3 | SmolVLA+LEW 策略（运行时 ckpt） | `outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model` |
| L4 | INTACT-JEPA 意图-动作 | `zmax_data/stable-wm-cache/checkpoints/intact_l4_current` |

---

## 4. 组织与分工

按职能角色组织（唯一依据 `config/platform/zmax_project_bom.json` `project.team` 段）。

### 4.1 项目管理层

| 角色 | 分工 |
|:---|:---|
| 项目/产品经理 | 立项、计划、里程碑与对内外接口总协调 |
| 市场接口人 | 客户接口、技术协议/商务备忘签订 |
| 研发接口人-软件 / 硬件 / 结构 | 软件交付联调 / 硬件选型集成 / 结构设计与验证 |
| 采购 / 财务 / 客户接口人 | BOM 核价 / 成本 ROI 口径 / 现场需求与验收对接 |

### 4.2 研发执行组

| 角色 | 分工 |
|:---|:---|
| 软件系统 | L3/L4/L5 软件栈、状态空间引擎、CICD |
| 机械臂运控 | 运动规划、宏微复合、力控插拔 |
| 视觉系统 | 手眼标定、2D→3D、AR 叠加、YOLO/VLM |
| 硬件 / 结构 | 控制器与边缘算力 / 上装结构与工装适配 |

---

## 5. 预算与工期

### 5.1 预算（唯一依据）

| 项 | 数值 | 唯一依据 |
|:---|:---|:---|
| 单价基准（首台 POC） | 450,000 元（未税） | `zmax_project_bom.json` `commercial.poc_price` |
| 阶段目标成本 | 样机期 250,000 / 生产期 190,000 / 量产期 170,000 元 | `bom.stage_targets` |
| 人力成本 | 单人月综合 25,000 元（**假设值，待财务确认**） | `labor.cost_per_pm` |
| ROI 目标回收期 | ≤2 年 | `roi.target_payback_years` |

> BOM 单价状态为「估算（采购未核价）」；人力成本为假设值，需财务确认后替换。上述为唯一依据现值，非本文件推算。

### 5.2 工期（里程碑驱动）

见 §7 里程碑；关键路径为「现场标定（站点几何）→ 动作级节拍优化 → 现场复测」。

---

## 6. 风险与对策

唯一依据：`config/platform/zmax_project_bom.json` `project.risks` 段。

| 风险 | 对策 |
|:---|:---|
| 7 轴臂无法达到节拍要求，需改用协作臂 | 年底完成第一版样机，测试升级，次年 4 月上产线 |
| 料盒变形/表面偏差导致夹持不稳 | 增加防滑橡胶垫 + 夹持力/掉落检测（力反馈确认） |
| 托盘内料盒来料定位偏差 | 夹爪预留 ≥10mm 行程余量 + 视觉定位补偿抓取点 |
| 人力风险（研发资源按单项目预测，需新招 6 人） | 人力申请 |
| 周转盘内光模块不同摆放位置/数量的泛化性 | 过程中验证（多型号配方 + 视觉自适应） |

**本版补充工程风险（依据缺失）**

| 风险 | 对策 | 状态 |
|:---|:---|:---|
| 站点几何未标定（`T_base_cam`/`plane_z`/`cell_geometry.points`）⇒ 坐标类参数与工单阻塞 | 现场标定后重跑配置中心 check | **待现场实测** |
| 成功率 ≥99% 与节拍 ≤3.15s 尚无实测支撑 | 现场连续作业标定 / 动作级优化 | **待现场实测** |
| 在役模型哈希未登记 | 登记权重路径 + sha256 | 部分缺口 |
| 动作块下发频率 ≥10Hz 未纳入诊断断言 | 补诊断断言并实测标定 | 缺口 |

---

## 7. 里程碑

| 阶段 | 名称 | 目标指标（唯一依据口径） | 计划节点 |
|:---|:---|:---|:---|
| EVT | 对内 Demo | 取放成功率 ≥90% · 单颗 20–25s | 2026-10-30 |
| DVT | 对外 POC 功能测试 | 成功率 ≥95% · 单颗 ≤8s · 连续 ≥6 盘无干预 | 2026-12-20 |
| — | 技术协议/商务备忘签订 | — | 2026-12-25 |
| PVT | 达到对外交付指标 | CT ≤3.15s · 成功率 ≥99% · 连续 ≥12 盘 | 2027-04-15 |

> 里程碑唯一依据：`config/platform/zmax_project_bom.json` `project.milestones`。

---

## 8. 附：唯一依据文件清单

| 唯一依据文件 | 用途 |
|:---|:---|
| `config/platform/zmax_perf_spec.json` | 性能指标体系（6 组 58 条 + 8 标准） |
| `config/platform/zmax_project_bom.json` | BOM/成本/ROI/里程碑/团队/风险 |
| `config/platform/zmax_platform.json` | 平台/产品/子系统 |
| `config/tasks/tasks.json` | 任务配置（7 任务） |
| `config/ss_task_binding.json` | 任务 ↔ 场景绑定 |
| `config/calib/zmax_manifold.json` | 主参数 M / 度量形状 |
| `config/calib/zmax_health.json` | 健康度 H 分级阈值 |
| `config/calib/zmax_calib.json` | 标定参数注册表 |
| `data/database/zmax/zmax_engineering.db` | 单一工程库 |
| `src/lerobot/manifold/{metric_field.py,health.py,engine_loop.py}` | 流形/健康度/引擎实现 |
| `tools/meta_moe_router.py` | 元数据MOE门控路由（本版） |
| `tools/delivery/gen_config_inventory.py` | 全系统总配置清单生成器 |
| `tools/verify_{metric_main_param,engine_loop,config_to_M,node_cfg_import,ss_bus_topics}.py` | 判据脚本 |
| `models/active_models.json` | 各层在役模型指针 |

---

*本文件所引数字均来自工程唯一依据；未实测项一律标注「待实测」，不作推测性结论。*
