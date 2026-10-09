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

## 第五域「工艺·工单」(Build Sheet) —— 工艺流程怎么配
- 汽车总装 Build Sheet(单车身份+装配指令+零件清单) → 机器人产线: 工单身份+工序配方+物料清单;
  再加一节汽车表上不写的: **安全(Sys-0)**(急停/力阈值/关节限位/光幕), 它不在配方里、在站点里。
- **四层配置 + 优先级(谁说了算, 写死)**:
  `L1 站点 config/calib/*`(现场事实, 永远最高, 只读) > `L2 工序配方`(工艺定型, 参数化) >
  `L3 工件变体`(scenes_5jobs.json: 物料/穴位/朝向) > `L4 工单实例`(生成物)。
  取值优先: 安全(G1) > 站点几何(G3) > 工单覆盖(G2) > 变体 > 配方默认。
- **上下料是坐标驱动工序**: 站点几何(T_base_cam/plane_z/cell_geometry)未标定 ⇒ 穴位/工位坐标不可信
  ⇒ **工单不允许下发(拦截, 不是警告)**。实测 5 份工单全被这同一处阻塞。
  能力早就在库里(feature.dbc A1 自主流转/A2 工位对接±10mm/C4 翻转取放/C5 双臂协同, 场景字段明写"上下料")
  ⇒ 上下料是**配置问题, 不是能力缺失问题**。
- **上下料特有三级粒度**(写进变体, 差的是夹具与判据不是重写程序):
  料盘级 330×330·12槽 / 治具级 200×200·4定位孔 / 单颗级 18×9×4。
- **防错校验链(Poka-yoke)逐件 7 步**: 扫工件码→查工单→选程序(配方+变体)→校验资源→参数下发→
  安全自检→记录(判据快照+binding_id)。任一不过 = 停线, **不许"跳过校验先干"**。

## 操作面 CLI：GUI 每个按钮 = 一条命令(一份逻辑两处用)
- `tools/config_center.py` 读 `config/mcd/zmax_mcd.json` 描述后提供: 总览 / `list 域` / `show id` /
  `open id`(真源绝对路径+键) / `recipe` / `variants` / `orders` / `order --scene` / `check`。
- 规则: **GUI 只做外壳** —— 命令函数抽成可导入模块给 GUI 直接调, **不写第二份实现**。
  每个按钮 = 纯函数 + 结果面板 + 可导出 JSON; 失败给**根因行**("站点几何未标定 ⇒ 坐标类参数不可信"),
  不给"操作失败"这种空话。
- 改造方向: `ConfigModule` 从"卡片页"换成「左域树(QTreeWidget, 五域) + 右工作区
  (QStackedWidget + 三列表)」, 现有 9 组模型卡片**整块搬进**"模型配置"栈页, 不重写; 工艺域三子页 = 配方/变体/工单。
- GUI 冻结纪律照旧: 一次改完再重启, 不在演示/准备重启时动。

## 生成物三条硬规矩(工单与描述文件都是生成物)
1. **不手改生成物**: 改真源 → 重生成。工单的真源 = 场景 + 配方 + 站点配置。
2. **ID 由真源决定, 不由遍历序号决定**: 工单号取场景编号(SCN-02→0002)而非 `enumerate` 下标 ——
   否则加一个 `--scene` 筛选就换号, 追溯就断了。
3. **只读取证 = 真源 mtime 不变**: 生成器跑完 `stat -c %y` 比对真源文件, 把结果贴进交付说明 ——
   这是"未触碰在役值"最简单可信的证据。

## 已落工具(VEH.6 相关, 全部只读真源/可复算)
`tools/mcd_build.py`(MCD 描述) · `tools/model_site_match.py`(模型×站点矩阵) ·
`tools/build_sheet.py`(工单/配方) · `tools/config_center.py`(操作面 CLI)。

## 任务配置 (主要工程配置) + 配置中心新页
- **层级**: 能力(feature.dbc) → 工序配方(8 段 25 条, **全集**) → **任务配置(子集+参数覆盖)** → 工单(一次执行) → 单件记录。
  任务 = 「这台设备在这个工位干哪件活」：选哪些配方段 + 覆盖哪些参数 + 触发/循环。**换产品只改任务，不动机器人与模型。**
- 真源: `config/tasks/tasks.json`（生成物: `tools/task_build.py` ← scenes_5jobs + 配方 + 站点配置）。
  实测 5 条；上下料 `TASK-02-HANDLE` = 6/8 段（排除「4 放置/插入」「5 拔出/取回」）+ 3 级物料粒度(L1 料盘/L2 治具/L3 单颗) + 6 条参数覆盖。
- 命令: `config_center.py tasks | task <ID> | order --task <ID>`。

### GUI 接入点 (studio.py)
- 挂载点: `ConfigModule.__init__` 末尾 **`self._build_shell(container)` 这一行**（在 `container.setLayout(outer)` 之后）。
  包成 try/except + `veh6_config_page.build_config_center(container, {C_*})`，**失败回退原页**。原模型配置整块保留为「🧠 模型配置」页，不重写。
- 新页 `tools/gui/veh6_config_page.py` 只依赖 PyQt5+json，**不 import studio**（颜色由 studio 传），所以可离屏单测：
  `QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python` → ast.parse → import studio → `studio.ConfigModule()` → 断言页签/行数/按钮出结果。
- 按钮 = `config_center.py` 的**同一份函数**（redirect_stdout 抓到面板）—— 一份逻辑两处用，不要写第二份实现。

### 坑 (已踩)
- **改了 `studio.py` 要重跑 `tools/mcd_build.py`**：`studio.py::cfg_spec` 是模型域的真源，描述里的 sha16 立刻对不上（面板会报「真源同步 ❌」）——这是正确行为，不是故障。
- `patch` 工具对 studio.py 这种超大文件匹配失败时，往往是**空白行差异**；从 read_file 的连续行直接取原文，不要在中间自己加空行。

## 现状（改造起点的实测事实）
- `ConfigModule` 在 `studio.py` 约 8634–9350 行（~700 行），**只覆盖"模型配置"**：
  9 组（架构模式/UI风格/基础/VLM骨干/Action Head/世界模型/预处理后处理/优化器调度器/配置预览）
  + Lerobot 标准参数总表 `cfg_spec`（6 类 × 3 模型）+ 导出 Excel。
- 工程/功能/性能三个域**一个都没有** ⇒ 本规划的动作是"扩域 + 换骨架"，**不改 VEH.5 画布、不改在役标定值**。
- 与 VEH.5 分工：VEH.5 管结构（节点/接线），VEH.6 管参数（能力组合/几何/权重/目标/红线），VEH.9 管结果。
- 交叉跳转：VEH.6 参数行的 `affects`（由 `_EXTERNAL_LOC` + `levels.band_map()` 生成）→ 定位并高亮 VEH.5 对应节点。
