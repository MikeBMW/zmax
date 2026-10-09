# VEH.6 配置中心 —— MCD (测量/标定/诊断) 口径

来源: 2026-10-09 设计会话。VEH.6 = 控制台第 6 页 `studio.py::ConfigModule`（不是画布 flow）。
完整规划: 仓库 `docs/design/veh6_config_center_mcd_20261009.md`；M 节点侧: `docs/design/manifold_mcd_master_param_M_20261009.md`。

## 核心结构：一张参数表 + 三个视角列（不是十二个页面）
- **行 = 参数**（A2L CHARACTERISTIC 的 UI 投影）。**域 = 分组**（模型/工程/功能/性能）。**列 = 同一个参数的三种操作**：
  测量（只读·真源·帧龄）| 标定（权限·编辑器·扫描）| 诊断（判据·故障码·差异）。
- 参数行固定 14 列，缺列不许入库：
  `id | 中文名 | 域 | 级 | 真源(文件#键) | 当前值 | 单位/换算 | 范围 | 默认 | 影响面(节点/层) | 判据 | 权限 | 关联feature | 状态灯`
- 参数五级：**G0 结构(非自由拟合)** · **G1 安全红线** · G2 性能(可扫) · G3 场景(现场零运动示教) · G4 权重/版本。
- 权限四档：`readonly` / `field`(现场) / `auth`(需真动授权) / `version`(只版本比对)。

## 四条不可破的口径
1. **真源唯一**：VEH.6 是编辑面，不是第二份真相；每行必须能答"文件#键"。描述文件由生成器产出，不手改。
2. **G1 红线永无编辑控件**：`saturate/veto_th/力阈值/限位` 只读展示，诊断列只报"是否被违反"。
3. **只改本节**：写 `calib.json` 只读-改-写本域键；**禁** `sync_calib(write=True)` 整表重合并（会把其他在役域刷成"当前源"）。
4. **写后必回读**：`manifold_M()`/`calib()` 读回逐位比对；三段 = 备份 prev → 只改本节 → 回读核验。

## 生成器 `tools/mcd_build.py`（B1 已落）
只读真源 → 出 `config/mcd/zmax_mcd.json`（MEASUREMENT/CHARACTERISTIC/COMPU_METHOD/GROUPS/DIAGNOSTICS）
+ `config/mcd/param_registry.json`（扁平+就绪度）。
- 真源: `config/calib/zmax_calib.json` · `config/calib/zmax_manifold.json` · `feature.dbc` ·
  `engineering/levels.py` · `verification/verification_layer.py` · `studio.py::ConfigModule.cfg_spec`。
- `--check` 幂等判据：剔除 `_meta.generated_at` 后内容比对（**逐位比对会把时间戳误报成不一致**）。
- 实测：CHARACTERISTIC 24 · 域 工程9/性能6/功能3/模型6 · G0 2·G1 2·G2 9·G3 6·G4 5 ·
  feature.dbc 能力 30(8 域) 组合 5 · 档位契约 L2 7/L3 4/L4 6/L5 5 · 断言 57(自动 47) · 就绪 10/24 缺 14。
- 缺口分三类（诊断列要分开显示）：**现场未标定**(T_base_cam/plane_z/cell_geometry) ·
  **真源非文件**(saturate/veto_th 在源码常量里) · **未接线**(权重/第三方/档位)。

## 模型多时如何区分配置 / 如何匹配工程配置
- **区分的不是名字，是三件正交的事**：`域(domain)` × `层(layer L2/L3/L4/L5)` × `角色(检测/策略/意图/肌肉)`。
  配置差异全来自这三者；同层可并挂多个候选（在役/候选）。
- **匹配 = 契约求交**：模型声明 `requires`（要哪些现场事实）∩ 站点 `available` ⇒ **OK / 缺项 / 不适用** 三态。
  “不适用”必须与“缺项”分开（没声明 vs 声明了没有），否则矩阵一片红看不出真问题。
- **工程配置不进模型包**：`T_base_cam` 同时服务 L2/L3/L4，复制进三个包 = 三份真相。
  模型包只放 `requires` + 容差；真值永远在 `config/calib/*`。
- **域是第一判据**：仿真域(`metaworld`)模型对站点几何几乎无依赖；真机域(`real`)一缺几何就红。
  实测：10 模型可用 9/10，**唯一受阻的是唯一真机域在役模型 L4.intact**（缺 T_base_cam/plane_z/cell_geometry）。
- **已有真源不能绕过**（不要新建第二套）：`models/active_models.json`(在役指针) ·
  `engineering/models_manifest.json`(版本+probe) · `docs/third_party_model_spec.md`(模型包 manifest v1) ·
  `tools/model_autoload.py`。该补的是 manifest 的 **契约段**(domain/requires/normalization/io)，不是新体系。
- 匹配器 `tools/model_site_match.py` → `config/mcd/match_matrix.json`（纯只读，可复算）。
- 冲解规则：G1/G3 **站点永远赢**（模型只能要求）；G2 组配覆盖可可回溯；归一化 stats 谁都不可覆盖（不同源=拒绝加载）。
- 命名：模型 ID `<层>.<家族>.<版本>#<sha16>`；组配 `binding_id = sha16(逐层模型+站点+档位+覆盖)` → 事后能还原“当时哪套”。

## 现状（改造起点的实测事实）
- `ConfigModule` 在 `studio.py` 约 8634–9350 行（~700 行），**只覆盖"模型配置"**：
  9 组（架构模式/UI风格/基础/VLM骨干/Action Head/世界模型/预处理后处理/优化器调度器/配置预览）
  + Lerobot 标准参数总表 `cfg_spec`（6 类 × 3 模型）+ 导出 Excel。
- 工程/功能/性能三个域**一个都没有** ⇒ 本规划的动作是"扩域 + 换骨架"，**不改 VEH.5 画布、不改在役标定值**。
- 与 VEH.5 分工：VEH.5 管结构（节点/接线），VEH.6 管参数（能力组合/几何/权重/目标/红线），VEH.9 管结果。
- 交叉跳转：VEH.6 参数行的 `affects`（由 `_EXTERNAL_LOC` + `levels.band_map()` 生成）→ 定位并高亮 VEH.5 对应节点。
