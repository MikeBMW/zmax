# 🏭 Z-MAX 平台 + 产品/子系统功能清单 + 工程数据库 (2026-10-09 老倪)

> 老倪: 「所有产品特性/系统配置/标定参数/功能清单汇总的数据库, 要和状态空间工程文件形成**统一数据结构**,
> 加载工程就一起把所有 特性·配置·参数·功能·模块代码 链接出来; **最好只用一个数据库文件**承载所有工程
> 数据, 这样 GUI 与整个工程解耦, 随时迁移工程文件, 统一 GUI 加载; 全局优化控制台, 实现工程数据与用户
> 界面分离, 重构整个框架; 总数据库放 /home/ubuntu/zmax/data, 建 database 文件夹统一管理。」

## 一、产品逻辑 (产品经理视角)

```
🏭 Z-MAX 平台产品 (具身智能机器人平台 · 三子系统解耦)
│
├─ 🏷 产品线 (平台产品的两个型号, 由同一平台架构派生)
│    ├─ Z700 精细操作机器人   光模块/精密件 抓取—对位—插拔; 精细力控 + 宏微复合
│    └─ Z100 通用操作机器人   跨工位上下料/流转/抓放; 移动即工位, 一台上装适配多工序
│
├─ 🎯 产品特征清单 (卖点级, 18 条)  ← 特征引用能力库 (feature.dbc BO_), 标注 KPI·状态·归属子系统·用到模块
│     Z700 10 条 (完整作业执行 / 精细对位 / 力控插拔保护 / 宏微复合 / L4专家自主 /
│                 场景理解与任务拆解 / 视触觉质量检测 / 标定与主参数M / 真机安全急停 / 边学边练)
│     Z100  8 条 (跨工位流转 / 工位精准对接 / 举升调节 / 双形态作业 / 通用抓放翻转 /
│                 双臂协同 / 多车协同调度 / 第三方模型接入)
│
├─ 🧠 System 2 认知决策 (L4/L5)  ─┐
├─ 🚀 System 1 动作执行 (L3)      ├─ 三子系统组成全系统实现产品特征
├─ 🔧 System 0 基石执行 (L2)      ─┘
└─ 🧩 平台支撑 (数据源 / Feature 质量门 / 观察器 · 跨子系统, 由平台统一治理)
```

**每个子系统的功能清单由三轴定义** (老倪: 系统2/1/0 都通过 配置·标定·诊断 定义功能清单):

| 轴 | 含义 | 真源 |
|---|---|---|
| ⚙️ 配置 CFG | 功能可调项 (权重/档位/开关/阈值/速度/记忆层…) | 画布节点 `params` 真键 + 子系统轴声明 |
| 📐 标定 CAL | 功能依赖的标定参数 (内参/外参/台面/工具/TCP/主参数 M) | `config/calib/zmax_calib.json` 9 段 + `zmax_manifold.json` |
| 🩺 诊断 DIA | 功能怎么自证 (断言/审计/一致性/帧龄) | `verification_layer.py FEATURES` (57 条) + 节点实现审计 |

**功能 → 模块**: 每条功能 = 状态空间画布上的一个模块节点 (74 条功能 = 74 个功能节点, 一一对应, 不重复计数),
模块再链到**引擎代码真源** `nodes/library.py` 的函数与行号 (实测 74/74 全部链上)。

## 二、数据结构 (单一数据库文件)

`data/database/zmax_engineering.db` (SQLite, ~0.8 MB) —— 一个文件 = 一套工程。

| 表 | 行数 | 来源 |
|---|---|---|
| platform / products / product_features | 1 / 2 / **18** | `config/platform/zmax_platform.json` |
| subsystems / subsystem_axes | 4 / 48 | 同上 (每子系统 × 三轴) |
| functions / fn_axes | **74** / 1594 | 画布行带 + 节点 params + 子系统三轴 |
| calib_params | 41 | `zmax_calib.json` + `zmax_manifold.json` (含 未标定缺口) |
| modules / module_code | 74 / 74 | 画布节点 ↔ `NODE_LOGIC` 代码位置 |
| capability_dbc / interfaces | 31 / 62 | `feature.dbc` (BO_ + 输入输出) |
| verification_features | 57 | `verification_layer.py FEATURES` |
| canvas_nodes / canvas_links | 74 / 184 | 状态空间画布 |
| project_sections / projects | 27 / 1 | `.proj` 全部顶层键 + 7 段语义别名 (canvas/pane/calib/measure/mparam/task/meta) |
| links | 368 | 特征→子系统 / 特征→模块 / 功能→模块 / 特征→能力 / 模块→代码 |
| library_removed | 33 | 模块库删除名单 |

**真源 (人可编) → 库 (生成物)**: 库随时可由 `engineering_db.py build` 重建; `check` 判据 11 项全绿
(特征→子系统 0 悬空 · 功能→模块 0 悬空 · 三轴 74/74 · 特征→能力 0 悬空 · 工程 7 段齐 ·
功能=节点无重复 · 库↔真源哈希一致)。

## 三、GUI ↔ 工程数据解耦 (重构要点)

- 新页 `tools/gui/platform_spec.py`「📋 功能清单」: **只认一个 .db 文件**, 不 import 任何工程文件;
  数据全走 `engineering_db.load(db)` (纯 sqlite)。
- 侧栏新卡 **🏭 Z-MAX 平台** 位于 System 2 之上; 点 Z-MAX / System 2 / System 1 / System 0 → 切到清单页并选中对应页签。
- 页内功能: 📂 打开工程数据库 (换库=换工程) · 🔁 从真源重建 · 📋 复制本页 · 💾 导出 JSON · 📡 服务状态。
- 旧功能页 (数据集/训练/硬件) 不丢: 每个子系统页签带「→ 打开该子系统对应的功能页面」一键进。
- 只读 JSON 服务: `127.0.0.1:8798` (`/summary /platform /products /product/<id> /systems /system/<id>
  /functions /function/<id> /modules /capabilities /calib /project[/<section>] /graph /sync`)。
- 迁移: `engineering_db.py migrate --to <路径>` 把库拷走, 换台机器用同一套 GUI 加载即得同一套工程。

## 四、data/ 精简 (老倪: 这个路径数据太多, 没用的都删掉)

`/home/ubuntu/zmax/data` **354 MB → 21 MB** (删 333 MB): 删的是 `data/handeye/` 79 张手眼标定
**采集截图** (6 MB/张); 代码只读同目录 7 个 json 结果 (已保留), 数值另在 `models/handeye_state.json`,
需要图重跑 `tools/a5_handeye_collect.py` 即可。留痕 `docs/notes/docs/notes/cleanup_manifest_20261009.txt`。
新建 `data/database/` 统一管理工程库 (库 + README + 清理清单)。

## 五、踩过的坑

1. **画布行带归属重复计数**: 平台 JSON 里 6 条「🔧 L2 基础辅助功能 · X」都用前缀匹配 → 全部命中同一行,
   同一批节点被数了 6 遍 (85 条功能 ≠ 74 节点)。修法: 行名按「· 后缀」唯一解析 + 节点全局**唯一**归属
   (中心落在带内取最具体的行带), 判据加 ⑤b/⑤c 卡死。
2. **行带缝隙里的节点**: 画布有 2 个节点 (「🛡 安全执行边界」「① 接近 · SK01」) 落在两条行带之间的缝隙 →
   按**最近行**归属并标 `kind=行外节点(就近归属)`, 不丢节点。
3. **.proj 段名与 7 段语义不一致**: 真实键是 canvas/panel/calibration/master_param/measure/tasks
   (元信息在顶层) → 入库时**全量顶层键都存** + 同时按 7 段语义名存别名, 判据按语义名校验。 
4. **懒加载页导致下标漂移**: 画布页 400ms 后才插进 stack (index 10), 之后所有页下标 +1 →
   `self.modules["spec"]` 记死的下标失效, 点击卡片切不到清单页。修法: 一律 `setCurrentWidget` + 现场刷新下标。
5. **`current_payload()` 页签匹配**: 用子系统全名 (`System 2 认知决策`) 去匹配页签 (`🧠 System 2`) 永远不中 →
   改成按 `System 2` 关键词匹配。
