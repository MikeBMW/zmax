---
name: zmax-meta-task-planning
description: "Use when 派生或导出 Z-MAX 元任务开发计划(Word/PDF)。"
version: 1.0.0
author: Hermes (Z-MAX)
license: proprietary
metadata:
  hermes:
    tags: [zmax, meta-task, planning, project-charter, config-center]
    related_skills: [deliverable-doc-authoring, zmax-engineering-repo, state-space-canvas-engineering]
---

# Z-MAX 元任务开发计划（派生 + 排期 + 导出）

## When to Use
- 老倪要「把状态空间工程里所有任务进行分析, 每个功能清单的功能叠加配置参数, 转化成元任务」。
- 要重出/改「元任务开发计划 · 项目立项书」, 或在配置中心「任务配置」里导出 Word/PDF。
- 版本升级 / 加任务 / 改配置后要同步这份计划 —— 它是**派生件**, 真源一动就得重出。

## 1. 口径
**元任务 = 一个功能(FN-SYSx-N) + 该功能全部配置参数 + 依赖 + 验证方法 + 归属层**
(不是「一个任务」, 也不是「一个画布节点」; 只有功能带完整元数据: 字段/范围/单位/依赖/验证)

## 2. 真源与映射链（4 个文件）
| 真源 | 内容 |
|---|---|
| `data/database/zmax/config_meta.json` | 77 个功能的字段/范围/单位/依赖/验证 (2026-10 起 77, 老文案 74 已过时) |
| `sources/config/tasks/tasks.json` | 8 个任务(工艺步骤/overrides/触发循环) + **作者字段 meta_tasks/long_horizon** |
| `sources/config/ss_task_binding.json` | 任务 × 节点 × 配方段 绑定 |
| `src/lerobot/engineering/flows/state_space_obs.json` | 画布 89 节点 / 184 连线 |

映射链: `任务.enabled_nodes → 节点id →(byname)→ 功能的 module_ref → fn_id → 元任务`

🔴 **坑: 功能对画布节点要用 `module_ref` 经 `{node.name: node.id}` 反查, 不是 `row_name`。**
`row_name` 匹配到的是 15 个**行背景节点**(type=row_bg), 会让 74 个功能只落到 13 个行上,
任务归属全空。症状: 「有任务归属的元任务 0/74」、优先级**全是 P2**、每月分布看着正常但毫无意义。
修完的自检: `module_ref → canvas id` 必须 **74/74 命中**, 且各任务元任务数 == 该任务 enabled_nodes 数。

## 3. 关键事实（排序方式由它决定, 别自己设计优先级）
**7 个任务的启用节点都是同一 51 节点集的子集, 无任何任务专属节点**
(节点服务任务数: 31 个服务全部 7 个任务 · 11 个服务 6 个 · 9 个服务 5 个)。
⇒ 元任务为**全工程共用**, 任务之间只差配置(`overrides` 参数覆盖 + `applies_segments` 配方段 + `run_cfg` 执行开关)。
⇒ 所以「某任务优先」**不能**靠「给它单独排一批元任务」, 而是把它所需的**那 51 个元任务整体压在排期前段**。
曾按「任务优先级」给元任务打标 ⇒ 51 个全落 P0, 区分度为 0。

## 4. 优先级（按功能服务多少个任务, 不是按任务）
- **P0** = 服务全部 7 个任务 (31 个): 核心底座 —— 感知/控制/执行/安全 + L4 决策, 任何任务都绕不开
- **P1** = 服务 5~6 个 (20 个): 多任务共用的扩展能力
- **P2** = 未被任何任务启用 (23 个): 已登记但未接入, 收口阶段处理
核对恒等式: `P0 + P1 == 任务启用节点并集(51)`

## 5. 排期
周期 2026-10 ~ 2027-12 共 15 个月。**两阶段**:
- 阶段一 9 个月压完 51 个(P0+P1) = 摆盘/插拔所需**全集** ⇒ 出口 = 摆盘+插拔全链闭环可验收
- 阶段二 6 个月收 23 个(P2) ⇒ 出口 = 74/74 完成, 一致性校验全绿
月配额 `[6,6,6,6,6,6,5,5,5, 4,4,4,4,4,3]`(合计 74)。
排序键: `(优先级, 层序 L2→L3→L4/L5→PLAT, -参数数, 名称)` —— 参数多的先开工(迭代久)。

## 6. 导出（Word/PDF）
- 脚本 `tools/export_meta_doc.py` —— 真源 → md → HTML → LibreOffice → docx + pdf; 内建一致性校验。
  CLI: `--check`(只校验不出文档) / `--no-pdf` / `--no-docx` / `--out DIR` / `--json`
- GUI 入口: 配置中心「📋 任务配置」首屏按钮「📄 元任务计划 (Word/PDF)」→ `_run_doc("metaplan")`;
  注册点在 `tools/gui/veh6_config_page.py` 的 `DOC_SCRIPTS` + `DOCS`; 文档交付页挂同一个导出器。
- 判据 `tools/verify_meta_doc_export.py` —— 离屏真起 ConfigCenterPage + 真点按钮 + 核产物新生成(13/13)。
- md→docx/pdf 的链路细节与 LibreOffice 的坑(HTML 必须先转 `.odt` 再转 docx)见 `deliverable-doc-authoring` 铁律十。

## 7. 一致性校验（交付前必过, 脚本内建 `--check`）
| 校验项 | 期望 |
|---|---|
| 元任务数 = 功能数 | 74 = 74 |
| 功能 module_ref → 画布节点 | 74/74 命中 |
| 任务 enabled_nodes → 画布节点 | 全部存在 |
| 各任务元任务数 = 启用节点数 | 51/51/42/51/51/51/31 |
真源 sha256 随文档发布冻结; 任一真源变更 ⇒ 重出计划 + 重跑校验。

## 9. 运行时输出（与文档同一映射链, 2026-10-14）
问「流形引擎需要根据任务输出元任务, 哪个节点输出合理? 意图直读么?」时的定论:

| 项 | 口径 |
|---|---|
| 内容 | 元任务 = 功能+参数+依赖+验证+层; **只能真源现算**, 不从意图/技能直读 |
| 派生器 | `tools/ss_meta_task.py` → 复用 `export_meta_doc.build_meta_tasks()`（不重写映射链）; 19ms/次 |
| 出口节点 | **主参数节点 n_calib_mani**（与「已加载配置名」同一个 5s 节拍）→ 话题 `zmax/ss_meta_task`; 订阅 `tools/dds_sub_meta_task.py` |
| 流形引擎的角色 | 每周期只带 `meta_n/meta_all`（运行时可观测量）+ 任务变时重算派生件落盘; **不在 step() 里每步带清单**（污染高频记录） |
| 🔮 意图直读 | **不参与内容**。`ss_intent_direct`（mem_nodes.py）是 Δz→技能 kNN, 输出**技能ID**, 没有功能登记/参数/验证/层; 意图只决定选哪一批（任务切换触发重算） |
| 判据 | `ss_meta_task.py --selftest` 3/3（74/74 映射 + 各任务元任务数 == enabled_nodes 数） |

## 11. 元任务**预测**节点（2026-10-14 老倪）
「元任务可以被预测出来 ⇒ 把意图直读节点改名为元任务预测, 输出元任务预测值, 输入为流形引擎的驱动扭矩」

| 项 | 定稿 |
|---|---|
| 画布节点 | id 仍 `n_intent_direct`（保 id 不改，免得断线）; 名 → 「🧾 元任务预测 (驱动扭矩 → 元任务预测值)」 |
| 输入边 | `ssintact_dec → n_intent_direct`(Δz→技能 kNN) **重接为** `ss_mani_eng → n_intent_direct` 标签「驱动扭矩 T_drive=M·(−∇Φ) (6D)」 |
| 输出边 | `n_intent_direct → sssched` 标签改为「元任务预测值 → 动作调制」 |
| 实现 | `tools/ss_meta_predict.py` + `mem_nodes.node_ss_intent_direct`; 真源 tap `/dev/shm/zmax_torque/torque_<scene>.jsonl` |
| 口径 | 结构先验原型 + 真算特征（trained=false）; 层响应选择向量 LAYER_SEL + 画布入度 + 参数规模 |
| ⚠️ 输入真相 | **驱动扭矩目前恒定**(std=0, 发布器跑固定状态) ⇒ 预测无区分度, 输出必带 `frozen/degraded` + 说明; 要真预测需时变扭矩 + 阶段标签后 `--fit` |
| 判据 | `ss_meta_predict.py --selftest` 4/4（输入真读 / 分数归一Σ=1 / 信息量如实 / 与真源集对照） |
| 改名连带（必做） | `config_meta.json` 的 FN-SYS2-24 name+module_ref（**同名才能保住 74/74**）→ `ss_task_bind.py` 重绑 → `engineering_db.py build` → 两 check |

## 13. 任务 ↔ 元任务 对应关系（2026-10-28, 两轮）
老倪: 「配置中心 TASK-07-AOI 任务的元任务要有对应关系, 点击 TASK0-7, 下面的元任务要对应变化」

两层必须分开讲, 混一起就是「点了没反应」:

| 层 | 是什么 | 真源 | 量 |
|---|---|---|---|
| **任务级元任务** | 该任务跑起来的那几条执行元任务(取料插入/拔出/AOI五点检测/良品下料/NG下料) | `tasks.json[task].meta_tasks` + `long_horizon` | TASK-07-AOI = 5 条 (MT-01..05, 392 段/159.43s/316 UPH) |
| **功能级元任务** | 一个功能 FN-SYSx-N + 全部配置参数 | config_meta.json + 画布 + binding | 77 条 / 8 任务 |

- 功能级**没有一条是单任务专属** (29 全 8 任务共用 · 9 五任务 · 3 六任务 · 12 七任务 · 24 无任务接入) ⇒ 只按 enabled_nodes 过滤, 看到的就是同一批底座, 老倪会判定「没有对应关系」。界面必须: 「归属」列 + **最专用优先**排序 + 表头写清 `启用N条: 仅本任务x · 全8共用y · 其余多任务z`。
- 联动链: `tasks_table.itemSelectionChanged → _meta_from_task_row → _filter_meta_tasks(tid)`, 里面同时刷 `_fill_task_level(tid)`(任务级表) + 功能级表; tid=None 回落到 binding 的 active_task。任务级无登记 ⇒ 由 `steps` 派生并**标明派生**, 不冒充登记元任务。
- 🔴 根因坑: `tools/task_build.py` 整份重写 tasks.json, 把 `ss_meta_task_ar.py` 写的 `meta_tasks/long_horizon/_meta_note` 全抹掉 (症状: 配置中心 AOI 元任务突然变空 / `--check` 报不一致)。已修: `AUTHORED_KEYS` + `_carry_authored()` —— 生成物重算, 作者字段按 task_id 原样搬。
- 判据: `tools/verify_task_meta_link.py` **36/36** (8 行逐个点 · 序列互不相同 · AOI=5 条登记元任务 · task_build 重跑不丢 meta_tasks · 像素截图) · `tools/verify_task_meta_geom.py` (任务级必一屏装全; 功能级 ≤40 行装全, 53 行允许表内滚, 有 9px 分隔条)。
- 几何根因: `QLabel(wordWrap=True)` 垂直方向也 Expanding ⇒ 三个标签各吃 480px, 把表挤成 222/480px。给标签 `QSizePolicy.Maximum + setMaximumHeight` 才正常。
- 界面即时生效: 配置中心窗口 close 会 `deleteLater` 页面; 另在 `simulink_module.open_config_window` 加了源码 mtime 变 ⇒ `importlib.reload(veh6_config_page)` (主控制台不动)。⚠️ 这两个改动**本身**要控制台重启一次才进内存, 之后改界面才免重启。
- 导出连带修: QUOTA 只覆盖 74 条 ⇒ 第 75~77 条没 `mt_id`, 渲染 md `KeyError` ⇒ 「📄 元任务计划(Word/PDF)」按钮点了不出版。已改成全部派号 + 配额溢出落最后一月并标 `month_overflow`; `TASK_ORDER` 硬编码 7 个任务 ⇒ 第 8 个被静默漏掉, 已改 `task_order(tasks)`; 判据 `verify_meta_doc_export.py` 13/13 (任务配置页签已非 tab0, 放宽到前两屏)。

### 13.1 手别 / 时空窗 / 段级明细（2026-10-28 第二轮）
老倪: 「TASK-07 只有 5 个元任务么? 名称也不全; 能对应 AR 场景的具体操作么? 左右手任务也不一样 —— 元任务该有一列标 左手/右手/左右, 要有时空对应关系」

- **手别真源**（不猜）: MT-01..05 = 右手（段表是单臂插拔循环 + 工单 goal「左臂摆盘 + 右臂插拔与 AOI 五点检测」）· MT-06 = 左手摆盘（工单「左臂摆盘」+ `tasks.json TASK-06-TRAY.steps` 5 段）· MT-07 = 双手交接同步（工单「双臂并行」+ 实测节拍 11.4s/件）。
- **7 条不是 5 条**: 只有 392 段表就只能归纳出 5 条（全右手）；左臂与双臂协同不在段表里, 必须从工单/tasks.json 补, 并标 `in_392=False` 不参与段守恒。
- **时空窗** = 首例 t 起→止（MT-01 0.00→2.83s … MT-05 50.05→51.44s）; 左/双 = 「并行/常驻」。**目标对象** = 从段 label 解析 槽k/孔k/金手指点/侧面点N/下料盘 槽k/废料盘, 无编号段继承手里那个（下料盘优先于槽, 否则会把下料盘槽位错认成上料槽）。
- **段级明细 40 行**（seq/动作/目标/手别/时长/累计）才是「对应 AR 场景具体操作」的证据: MT-03 = 10 段覆盖 金手指点 + 侧面点0..3。
- 界面: 任务级表 8 列（手别上色 右蓝/左绿/双紫）+ ↳ 段级表（点元任务行摊开）+ 舱高按实际行数重算 `_fit_meta_box()`。
- 其它任务无 meta_tasks ⇒ 由 steps 派生, 手别从 desc 的 左臂/右臂 读, 真源没写的显示 `—(真源未标)`, **不猜**。
- 判据: `verify_task_meta_link.py` **47/47** + `verify_task_meta_geom.py` PASS。

## 14. 活跃任务驱动的三页 (功能配置 / 模型配置 / 性能配置, 2026-10-28)
老倪: 「根据元任务的编排, 继续完成 功能配置 模型配置 性能配置; 当前激活的是 任务7, 功能上要将任务7的任务都对应上;
功能配置的UI 你再设计一下; 在功能配置页面, 要提示 当前的活跃任务, 随即显示当前活跃任务的功能配置」

**真源链 (三份, 不手抄)**
1. `config/ss_task_binding.json` → `active_task`(=TASK-07-AOI) / `enabled_nodes`(32) / `disabled_nodes`(21) /
   `applies_segments`(4) / `excluded_segments`(4) / `segment_node_map`(段→节点) / `targets` / `ss_mode`
2. `config/tasks/tasks.json` → 该任务的 `meta_tasks`(7 条) + `long_horizon`(tact/UPH/段数/轮模板)
3. `export_meta_doc.build_meta_tasks()` → 77 条功能级元任务(归属 `tasks` / 参数 / 验证)

**派生映射**: 功能 → 节点(`node_id`) → 启用? (`enabled_nodes`) → 段(`segment_node_map` 反查)。
TASK-07-AOI: 77 条里 33 条归它; 8 段里 4 启用; 33 条里 7 条缺参数; 其中 FN-PLAT-63 在 `function_layer_map` 没条目(真源缺口, 如实标)。

**功能配置页版面 (自上而下)**: ①🎯活跃任务横幅(名字+元任务数+段 x/8+功能 33/77+启用/禁用节点+场景/站点+真源)
②元任务编排表(元任务/名称/手别/层/段数/时空窗/目标对象/动作要点) ③工艺段→功能覆盖(8 行: 本任务✅/⛔ + 节点/启用节点/对应功能/缺参数)
④本任务功能明细 33 行(全部/仅启用节点/缺参数/仅专用 四个过滤, 用 setRowHidden) ⑤参数明细(特征库功能域 —— 保留点参数名定位行的旧口径)。
**性能配置页** = 同一横幅 + 该任务 KPI 表(节拍 11.42 / UPH 300 / 一轮 392段·159.43s·14件 / 驻留·AOI·落盘 / 良率 / targets 质量目标)。
**模型配置页** = 同一横幅 + 映射表默认只列本任务(32/79)、一键全量; 按钮文字按**表里真实行数**算, 不写死 77/33。

**判据**: `tools/verify_config_active_task.py` 33/33 —— 含「改 active_task 成 TASK-06-TRAY ⇒ 三页跟着换(功能 53 条)」再还原。

**坑**
- `config/` 是软链到 `data/database/...`, **不进代码库**; 改完 tasks.json / ar_meta_tasks.json 不要指望 git 提交它们。
- `_task_funcs()` 每次重建 77 条清单(缓存按 mtime), 页构 1.0s / 缓存后 0.47s —— 别在循环里反复调。
- 模型映射表 `function_layer_map` 是 **79 行**(77 FN + 2 PLAT), 不等于 77; 拿它当报数基准会被用户抓到不对。
- `_build_fpm_view` 造的是「特征库三域」原页, 功能配置已被 `_build_func_active_view` 取代;
  但 `self.tab3_table / tab3_btns / fpm_rows / self.fpm_views["功能配置"]` 仍被左树定位/星图用 ⇒ **必须保留别名**
  (新页里把参数明细表当 tab3_table)。
- `verify_config_center_text_copy.py` 的针是「产品配置 —— **产品标识**」, 而页面真实标题是
  「产品配置 —— **产品档** · 点卡片切换(写回真源)」⇒ 12/13 假红; 改针为真源文案后 13/13。
  看到单条「找不到该行」先对页面文案, 不要回去改页。
- 控制台里的配置中心是进程内模块: 改完要么重启控制台, 要么靠 `simulink_module` 的源码 mtime 判定自动 reload (下次开窗生效)。

## 14.1 元任务 ↔ 功能 的连接 (2026-10-28 二轮)
老倪: 「功能配置, 怎么和元任务连接呢? 在功能配置里, 看到元任务了, 但是一个列, 应该是功能, 哪里去了?」

- **唯一公共轴 = 工艺段**: 功能只带 `node_id`, 元任务只带动作段, 两边没有直接外键; 但
  `ss_task_binding.segment_node_map`(段→节点) 与 `node_id` 同属画布节点 ⇒
  `元任务 --(MT_SEG8 按动作性质归段)--> 工艺段 --(段→节点)--> 功能`。用关键词猜配一定被追问, 不要做。
- `MT_SEG8`(SS_meta_task_ar.py 模块级, 作者口径, 依据逐条注释): MT-01=段1+2+4 · MT-02=段5 · MT-03=段3 ·
  MT-04/05=段6 · MT-06=段0+1 · MT-07=段7。派生到 `meta_tasks[].seg8` 落盘。
- 界面三条列(两向都有才能“对上”):
  元任务表 `元任务|名称|功能(承载·经工艺段)|功能数|手别|工艺段|动作段|时空窗|目标对象` ·
  段表 `…|承载元任务|…` · 功能明细 `功能ID|功能名称|承载元任务|层|段|…`。
- 实测 TASK-07: 7 条元任务的功能列**并集 = 33** (全覆盖); **MT-02(拔出) 落段「5 拔出/取回」在该映射里
  没有任何落成本任务功能的节点 ⇒ 0 承载**, 界面标 `⛔ 无功能承载` + 红字 tooltip(真源缺口, 不许静默补)。
- 判据 `verify_config_active_task.py` **39/39** (含并集=33 / 零承载如实标 / 两条反向列都在 / 段表 8 段全有元任务)。
- 坑: 自验写 `_hidx(t, "工艺段")` 会先命中表头 `功能 (承载 · 经工艺段)` ⇒ 取到错列、断言假绿;
  定列表头要用**全等匹配**。

## 14.2 功能配置重写: 子系统→功能树 + 四件套 + 逻辑实现 (2026-10-28 三轮)
老倪: 「功能, 应该有 功能名称, 输入, 输出, 描述, 这些信息, 对应着元任务; 可以是 1 个功能, 也可以由功能组成子系统。
重写功能配置, 每个功能要有 function 这样的逻辑实现」

**四个字段各自的真源 (逐字段标来源, 不混)**
| 字段 | 真源 | 覆盖 |
|---|---|---|
| 名称/子系统/层/描述 | `engineering.db : functions(name,system_id,layer,row_name,note_work)` | 33/33 |
| 逻辑实现 | `links(kind='对应模块')` 功能→画布节点 → `module_code(file,line,logic_key)` + `functions.params.source/source_symbol` | 33/33 |
| 输入/输出 | `tools/spec/fn_io_seed.json` (作者整理, 逐条自该功能 note_work 改写) | 33/33 |

**坑 ① 自动派生的 I/O 是「能力级」不是「功能级」**: config_meta.py 把 功能→产品特征→capability_dbc 的 inputs/outputs
合并起来, 一个功能挂 3 个 PF 就把 3 个能力的输入都揃进来 (如肌肉记忆技能库“输入=待考核模型”) ⇒ 老倪一眼看出假。
只当「派生(参考)」灰字保留, 当输入/输出用一定被打回。
**坑 ② 逻辑实现校验不能靠自报**: 必须 文件存在 + 行号在界内 + 往上 12 行内真有 `def/class` 才算 ✅。
`FN-PLAT-63` 无 `对应模块` link, 但 config_meta.module_ref 有 ⇒ mname 降级链:
`fn2mod → f.module_ref → cm.module_ref`, 否则 32/33 差一条。
**坑 ③ 主题键名**: 本页 `th` 是 `C_BG2/C_WHITE/C_BORDER/C_CARD/C_GRAY/C_BLUE`, 写 `BG2/FG/LINE` 直接 KeyError 打不开页。
**界面**: 左树 `子系统→功能` (5/33, ✅N 实现数) + 右 `QTextBrowser` 详情 (四件套/元任务/参数/实现/验证) +
`📋 复制功能定义` `📋 复制实现路径` (老倪要可复制); 点子系统出「由 N 个功能组成」+ 成员 I/O 并集。
**判据** `verify_config_active_task.py` **43/43** (含 33/33 有 I/O、33/33 实现可定位、剪贴板真写进、切任务树跟着换)。

## 14.3 功能总表 (2026-10-28 四轮, 老倪三轮纠正后的定稿)
老倪: 「你的功能也没有对应上啊, 例如 FN-SYS0-36 也没有对应; 每个功能, 都要有对应关系, 要有功能总表;
第一个表应该是所有当前任务的所有功能, 再对应哪个元任务; 我现在看不到功能啊。每个功能都要列出来」

**版面顺序定稿 (功能配置页)**: ① 活跃任务横幅 → ② **功能总表** (33 行平铺) → ③ 元任务编排 (带功能列)
→ ④ 工艺段覆盖 → ⑤ 子系统→功能树 + 功能定义详情 (钻取) → ⑥ 参数明细。
**“看不到功能”的根因**: 只有树 + 单条详情面板时, 33 个功能没有“一张表”一眼看完 ⇒ 老倪认为功能丢了。
树是钻取, **平铺总表才是他要的第一张表**。以后做任何“功能/能力”页, 先给总表再给钻取。

总表列: `功能ID | 功能名称 | 输入 | 输出 | 描述 | 对应元任务 | 逻辑实现(function)`
- 不内滚: 表高按全部行撑开 (`sum(rowHeight)+48`), 页面整体滚; 行高封顶 58px (3 行字), 全文进 tooltip。
- 实现列短写 `library.py:5176 def node_n_l2_muscle`, tooltip 给完整路径。
- 过滤 chips: 本任务 / MT-01..MT-07 / 全部 77 (全部模式下对应列写「— 不服务本任务」, 不冒充有)。
- 点行 → 跳右下详情面板 (file:line / 参数 / 验证 / 承载元任务)。

**坑**: 只开 `wordWrap` + `resizeRowsToContents()` 时, 宽窄列错配会把行高撑到 **174px** (33 行 = 5738px),
页面直接爆到 7733px; 必须列宽先排好 (92/200/246/226/296/82/stretch) + 行高封顶。
判据 `verify_config_active_task.py` **54/54**。

## 14.4 模型配置 ↔ 功能配置: 用实际在役模型 (2026-10-28 五轮)
老倪: 「继续 模型配置, 如何对应功能配置, 要用实际的模型」

**两张表定稿 (模型配置页置顶)**
① 功能 → 实际模型 (33 行): `功能ID|名称|层|实际模型/加载物|类型|实际文件/端点|大小·时间|状态|依据|层模型(真源)`
② 模型台账 (按模型聚合 9 条): 模型|类型|权重路径或端点|大小|时间|状态|服务功能数|服务功能

**依据优先级 (先具体后笼统)**:
1. 工程库 `modules.params`: `model` / `skill` / `llm` / `expert`+`decoder` ← 最准 (如 FN-SYS0-36 `skill=data/skills/l2_muscle/*.json`)
2. `models/active_models.json` 里 `used_by` 点名该 `fn_id` 的条目 (如 `ar:L2:aoi` → FN-SYS0-40)
3. `tools/spec/model_links.json` 的 `fn_overrides` (层模型点名但模块漏登权重, 显式对齐)
4. 都没登记 → 写「无权重 · 代码/规则实现」+ 实现 file:line (25/33 属此)
**不要拿 `function_layer_map.models` 当实际模型**: 它是层级粗话 (L2 全部写 YOLO), 单独放「层模型(真源)」列供对照。

**真源坑 (active_models.json 里的死指针)**: `ar:L5:vlm` → `models/qwen2.5-vl-3b` 不存在 (真实文件
`zmax_data/models/l5_vlm_merged_20261009_231339` 1019MB); `ar:L2:sam3` → `models/sam3` 不存在
(真实 `zmax_data/models/sam3_hf/model.safetensors` 3439MB)。已修正 + note 记变更。
`models/` 被 .gitignore ⇒ **指针修正不进 git**, 换机/回滚会丢, 必须当场报。

**当前 AR 场景真实在役**: 技能库 1KB · YOLO 6MB · SAM3 3439MB · L3 SmolVLA 1289MB · INTACT-JEPA 84MB ·
AR VLM 1019MB · AOI 端点 10082/10083; **Qwen3-7B 未配置(走规则) · DeepSeek 视觉 API 本机无 key**。
判据 `verify_config_active_task.py` **67/67**。

## 14.5 模型配置定稿 + 性能配置能力边界 (2026-10-28 六轮)
老倪: 「模型 Qwen3 怎么和 INTACT-JEPA 层模型对应呢？不对, 再次检查对应关系; 要有模型名称, 要有 L2~L5 分层,
要有状态空间的节点; 改完后, 继续写性能配置, 要体现模型的能力边界」

**模型配置 = 功能×模型 对表 (一个 (功能,模型) 一行, 107 行)**, 列: `功能ID|名称|层|模型名称|状态空间节点|来源|实际文件|大小|状态`
- **三个来源必须分开写**, 混在一起就是“对应不对”: `层模型`(function_layer_map 声明, 层级的粗话) /
  `模块登记`(modules.params 的 model·skill·llm·expert) / `场景登记`(active_models used_by)。
- 层模型声明 ≠ 实际加载时, 来源列追加 `⚠ 与本功能实际加载(X)不一致`。
  Qwen3 与 INTACT-JEPA 就是因为混写才被老倪抓出: Qwen3 = FN-SYS2-02/04 的**模块登记 llm** (L4/L5), INTACT = L4 **权重**行, 两者必须各自成行。
- 每行必须有: 层(L2~L5) + 状态空间节点(n_l2_muscle / ssintact_dec / sssched …) —— 这是他要的“能对上号”。

**性能配置 = 能力边界 (tools/spec/capability_limits.json, 12 条) + 指标真源 (config/platform/zmax_perf_spec.json)**
边界表列: `域|模型|层|状态空间节点|输入域→输出域|上限/量程|阈值/精度|时延|越界行为/闸门|真源校验`
- 真源校验必须现场: 文件存在 + 行号在界内 + JSON 键取得到 (12/12); 写死字符串不算。
- 关键边界值: YOLO conf 0.4 · L3 image 3×480×480+state39→action4 chunk7 · L4 image 224×224×3帧+skill24→action8 ·
  `safety.py:12` VEL_LIMIT 1.0 / FORCE_LIMIT 5.0N / POS_LIMIT 0.6 · 相机 fx394.06 image640×480 · `plane_z` 未标定 ·
  运动 1~1000mm/s · 插入力≤40N · 姿态>5°被 50113 拒。
- 指标表 `value` 空 = 未实测, **不编数字**; 按 `links ∩ 本任务功能` 过滤 (本任务 9 条)。
判据 `verify_config_active_task.py` **83/83**。

## 14.6 性能指标按模型配置分档 (P1/P2/P3) → 成本核算入口 (2026-10-28 七轮)
老倪: 「根据不同的模型配置, 性能指标也要分出级别, 这样下一步的成本组成就可以核算了。
L2 能满足速度节拍/单任务; L3 能满足多任务编排; L4(含L5) 能满足不同安全等级」

真源 `tools/spec/perf_tiers.json`, 页面块 `_perf_tier_block()`。三档定义 (不能自行加档):
- **P1 = L2** 速度节拍级: 11.42s/件 · 316.1UPH · YOLO conf0.4 + 技能库 + AOI 10082/10083 · 单机限幅 · 不能多任务、不能异常自恢复
- **P2 = L2+L3** 多任务编排级: +SmolVLA 1289MB (image 3×480×480 + state39 → action4, chunk7) · 技能序列可组合 · 异常只能预案分支
- **P3 = L2+L3+L4(可含L5)** 安全分级自主级: +INTACT 84MB (image224×224×3帧 + skill24 → action8, 稳态101ms) + Qwen3/DeepSeek/VLM · 动作授权 + 分层否决链 · 目标 PL d 未认证

硬规则:
- 每档必须同时写 **能做到 / 做不到 / 安全等级 / 成本因子 / 适用任务**; 只写能力不写边界 = 不可核算。
- 成本因子只列**项目** (硬件·算力·数据采集·LoRA·API·安全认证), **不在本步编金额**, 老倪会分两步问。
- 分档指标逐条 `src` 必须能被 `_src_check()` 现场校 (文件存在 + 行号在界 + JSON 键取得到); 写「同上」「...」一律会被判 FAIL。
- `_src_check` 必须放**模块级**, 误插到 class 内会提前结束 class (症状: `ConfigCenterPage` 缺 `_back_home`)。
- 本任务所需档位由该任务功能的层集合推出 (含 L4/L5 ⇒ P3), 并在表里高亮, 不靠人工选。
判据 `verify_config_active_task.py` **96/96**。

## 14.7 性能配置终稿: 一张表三档 (2026-10-28 八轮)
老倪: 「性能指标太多了, 就要一张表, 保留 性能指标/值/对应的模型/对应的功能层级; 要为产品成本组成提供参考,
要能看出来 基本性能、精细操作的性能、专业性能」

真源 `tools/spec/perf_bands.json`, 页面方法 `_perf_one_table()`。**只有一张表**, 19 行 x 6 列:
`性能档次(合并单元格) | 性能指标 | 值 | 对应的模型 | 功能层级 | 真源校验`
- A 基本性能 (L2): 6 行 —— 节拍/UPH/长程/定位精度/检测能力/安全限幅/视觉量程
- B 精细操作性能 (L2+L3): 7 行 —— 插入力/策略输入输出/控制频率/双臂并行/准确度/模型资源
- C 专业性能 (L2+L3+L4含L5): 6 行 —— 意图时延/输入输出/否决重规划/任务规划/VLM/安全等级

硬规则:
- **每档第二行就是成本组成** (`cost_hint` + `cost_items`): A 工控机+相机+AOI · B +推理GPU+数据采集+LoRA · C +L4训练+API/3B显存+安全认证。
- 指标数量控制: **15~24 行**一个屏能看完; 超过就是没整合。旧版 15 条分档指标 + 12 条能力边界 + KPI 块 = 太多, 已被老倪砍。
- 表一旦定稿就要**删死代码** (`_task_perf_block`/`_perf_tier_block`/`_perf_boundary_block` 全删), 否则判据里 `getattr(p, 'perf_tier_table') is None` 会报幽灵表。
- 每行 `src` 必须能被 `_src_check()` 现场校; 数组型真源 (如 tasks.json) 用 `#tasks` 这种可索引键, 不支持 `[i]` 下标。
- 判据 `verify_config_active_task.py` **87/87**, 含「基本只用L2 / 精细含L3 / 专业含L4-L5」的层级一致性断言。

## 14.8 工程配置 + 操作手册 (WI) 按性能等级落地 (2026-10-28 九轮)
老倪: 「根据性能等级, 进行工程配置, 要有操作手册 working instruction, 保证能够工程实现」

真源 `tools/spec/eng_profiles.json` → **两处消费**: 配置中心「⚙️ 工程配置」页 (A/B/C 切换 + 四张表 + 每步「▶ 跑」)
+ `docs/deliverables/工程操作手册_三档_A_B_C.md/.docx` (`tools/export_wi_doc.py` 生成)。

每步 WI 五要素缺一不可: **做什么 / 在哪做(local|onsite|orin) / 可粘命令 / 期望输出 / 失败处理**。
规模: A 9 步 · B 8 步 · C 8 步 = 25 步。

硬规则 (踩过的坑):
- **expect 必须是输出里真有的子串**, 不能写「>=1000」「200/404 都算通」这种语义判据 —— 要么改成 python 内判输出 `OK/SMALL`, 要么写实际字符串。
- **判据里跑判据会递归**: 自指步骤 (`verify_config_active_task`) 必须跳过并单独说明。
- **需要 PyQt5 的脚本要用 `gui-venv311/bin/python`**, 用系统 python3 会 ModuleNotFoundError。
- **输出末行不是结论时** (`| tail -1` 抓到「截图: ...」) 改 `| grep -E 'PASS|FAIL' | tail -1`。
- **已知缺口用 `"gate": "gap"` 标记**: 判据反过来要求「确实跑不通」才算缺口真实; 今天 = B5 DATA_LOW (datasets 无 parquet/无 LeRobot info.json)。
- 现场项 (plane_z 未标定 / AOI 网段 / 急停演练 / 安全认证) 一律 `need=onsite`, 不许在手册里假装已过。
- docx 用 `python-docx` 在 **gui-venv311** 里导出 (系统 python 无), 中文字体要设 `w:eastAsia`。
判据 `verify_eng_wi.py` **62/62** (其中 15 条命令是真执行拿到的输出)。

## 14.9 性能指标: 物理可测值 + 算力分档 (2026-10-28 十轮)
老倪: 「值要用物理可测量的值, 跟时间和距离有关, 可以计算, 可以用工具测量; 指标太零散, 要专业有依据;
对应的模型不要写 D405 这种硬件, 要有算力对应: L2 ≤30 TOPS, L2+L3 ≤80, L2+L3+L4 ≤300」

真源 `tools/spec/perf_bands.json` schema 2.0, 表 32 行 x 8 列:
`档次 | 指标(符号) | 物理可测值 | 测量工具/方法 | 依据(ISO/真源) | 算力预算 | 层级 | 真源校验`

- **值必须是从 sim_insert.json 392 段算出来的**: T_c=11.39s · Q=316.1件/h · L=3200.6mm · v̄=281mm/s · v_max=631 ·
  insert 47mm/156.7mm/s · golden 0.8s + side 2.0s ⇒ 检测 2.8s/件; 九项相加 11.38s 与 T_c 对得上 (自洽校验)。
- **算力档位是硬闸**: 算力列只许写 `≤30/≤80/≤300 TOPS`, **禁止出现相机/主机型号**; 估算公式要写出来
  (FLOPS≈2·N·f, 例 YOLOv8s 28.6GFLOP/帧×30fps ⇒ 0.86 TFLOPS ≈1.7 TOPS INT8)。
- **每行必须有测量工具** (控制器时间戳 / 激光跟踪仪 / 千分表 / 六维力传感器 / 标定板) 与**依据** (ISO 9283 §6.3/§6.5/§7.2/§7.4, ISO 13850, ISO/TS 15066, IEC 61754);
  没实测的就写「(目标)」「未实测」, 不编。
- 判据断言: 每行带物理单位 (mm/s/N/Hz/ms/MB/维) · 时间/距离类 ≥12 行 · 工具与依据非空 · ISO ≥4 条 · 三档 TOPS 与档位--对应 · 算力列无硬件型号。
- 坑: `tops_estimate` 只放 tooltip 会判「缺口径」⇒ 必须在**可见标签**里渲染。
判据 `verify_config_active_task.py` **95/95**。

## 14.10 三档成本 / 三张工单 / ar3d 生产演练 / 三方分成 (2026-10-28 十一轮)
老倪: 「给出基础/精细/专业成本, 做成本分析, 出三种工单生产, 由 ar3d 安排生产, 按产量与价值给销售建议与市场策略,
三方(本体硬件/模型软件/运营数据)分成, 都要在 ar3d 演练给出预期, 三方分成出 PPT, 产量通过仿真给出, 屏幕下方独立窗口显示市场预期」

**成本内核单一真源**: `tools/cost_model.py::build_tiers()` + `tools/spec/cost_model.json` (**只放单价口径**, 结论现算)。
页面/工单/PPT/API 四处同源, 自动一致。
- ❗ **节拍口径坑**: `sim_insert.json` 的 `cycles=8` 是「循环块」不是件数, 件数在 `mods=14`;
  必须用 `tact_steady_s=11.42` —— 用错会把 11.42 算成 19.93, 全年产量直接差 40%。
- 单位成本 = (capex/5 + opex/年 + NRE/3) / 年产量; 回收期 = (capex+NRE)/(收入−运营现金)。
- 判据要**独立重算一遍** capex/单位成本/回收期/分成合计 100%, 不能只信函数自己。

**三档结论** (单价为市场参考口径, 待报价):
A 18.9万+9.0万 · 1,286,164 件/年 · 0.0839 元/件 · 76.0% · 回收 0.68 年
B 22.9万+21.0万 · 同产量 · 0.1339 · 68.1% · 0.91 年
C 28.1万+53.0万 · 1,664,448 件 (6000h×0.88) · 0.1697 · 69.2% · 0.94 年

**工单**: `tools/gen_tier_orders.py` → `config/orders/BS_SCN-07-AOI-T{1,2,3}.json` (带 cost 快照)。
⚠ `config/` 是指向数据盘的软链 ⇒ **工单不入 git**, 必须用生成器可重复重建; 工单表在「📄 文档配置」页 (2026-10-19 老倪定案, 无独立工单 tab)。

**ar3d 市场预期 dock** (`tools/inject_mkt_dock.py` 幂等注入): `#mktDock` fixed bottom 140px + `body{padding-bottom:196px}`
(不遮主区); 选 T1/T2/T3 · ▶安排生产 · 倍速 x1/x60/x600 · 12 个实时字段 + 三方分成; 数据只来自 `/api/ar/cost`;
`window.__PROD__` 钩子给离屏判据确定性推进 (`tick(dt)` 里 simT += dt×speed)。

**三方分成**: 投入比例 / 价值贡献 45:30:25 / **混合制(推荐)** 硬件一次性 + 软件许可 20% + 运营 0.02 元/件。
**PPT**: `tools/build_market_deck.py` → `/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx`
(10 页, 基于同目录 `模板.pptx` 母版/主题; 每页以图表为主体: 堆叠柱/簇柱/折线/饼/环形×3/100%堆叠/方框流程; **标题全用完整句子, 不出现 任务7/T1/T2/T3/工单号**; gui-venv311 有 pptx).
- 拆页时必须 `prs.part.drop_rel(rId)` 再 `sldIdLst.remove()`, 只删 sldId 会在保存时与新旧 slide1..6 重名(重复 part, 文件可能坏)。
- 自验: `soffice --headless --convert-to pdf` + `pdftoppm` 出图, 再用**视觉子代理**逐页看排版(溢字/重叠/标签被裁)。
判据 `verify_cost_split.py` **80/80**。

## 14.11 产品愿景统一 (2026-10-28 十二轮): 愿景真源 → 配置中心 / ar3d / PPT
老倪: 「根据产品愿景, 整体优化配置中心, 依次优化产品定义/任务/功能/模型/性能/工程, 最后给出成本组成、市场分成,
达到全局愿景统一; 这个愿景, 一个在 AR 场景体现; 同时优化市场分成 PPT, 要画面要图表不要只写数字表格」

**愿景真源 `tools/spec/vision.json`** — 一句话(headline/subline/problem/answer) + 三护城河(pillars) + **八步脊柱(spine)**
+ AR 口径(loop 四环节 / counters / overlay 物理量)。三处只读这一份, 禁各自写话术。
- spine 每步带 `question / answer / shows / tab`, `tab` 用来映射页签 ⇒ 愿景带高亮不靠硬编码。

**配置中心愿景带**: 不改任何页面构造, 在 `_apply_tab_order()` 之后调 `_install_vision_bars(th)`,
遍历 `self.tabs`, 取 `QScrollArea.widget().layout().insertWidget(0, bar)`。一个插入点覆盖全部七页。
bar 上挂 `_vision_keys` / `_vision_chips` 供判据真读。
**文档配置同时高亮 成本组成+市场分成 两步** (两页内容都在该页, 不拆新 tab — 尊重 2026-10-19 七星布局定案)。

**成本组成 / 市场分成两张真表**: `_tier_cost_block` / `_tier_split_block` 读 `build_tiers()`, 表格单元格与模型逐项对账;
绝不把结论数字写死在页面。

**ar3d 愿景条**: `#visBar` `bottom:140px` (正好落在市场预期窗口之上, 不遮 3D 也不抢按钮), 42px;
闭环四环节呼吸灯 + 三个可数的东西 + 四个物理量; 数据只来自 `/api/ar/vision`, 件数接 `__PROD__.read()`。
❗ 语义坑: 「动作单元」= 元任务条数 (7), 不是段数 (40) —— 两个数都要给, 不然和产品叙事对不上。

**PPT v3 = 12 页**: 愿景页 + 八步链路页在前, 成本/分成在后; 视觉复核后修 6 处 (封面标题间距/折线 A 与 B
重合改虚线且只给 C 打标签/环形图关扇区百分比改环下写/卡片文案缩短防孤字/脚注 #6B7280/「三个缺口」→「四个」)。
判据 `verify_vision_unity.py` **57/57** (含三处首句同源比对) · `verify_cost_split.py` **110/110**。

**PPT 版面铁律** (逐页视觉复核两轮后沉淀, 全部由子代理量像素发现):
1. **对齐线**: 正文 x=0.96/宽 11.40; 方框行必须 `x0=0.96, total_w=11.40` —— 默认 0.85/11.9 会左右各凸 20~30px,
   箭头被挤成 9×13px。卡片行 `X0=0.95 / WC=3.70 / gap=0.16`, 右边距才对得上。
2. **右栏半栏空白**: 图表高 5.0in 而文字只到 3.3in 时, 右栏下部 250~300px 全白 → 补 `kpi_strip()` 三条小数字
   (标签灰小字 + 数值主题色粗体), 左右两栏才视觉等高。
3. **两条线数值完全相同**时不要画两条: 后画的会完全盖住前一条 (虚线也看不见), 且数据标签叠印成乱码。
   合成一条并在图例写「基础型 / 精细型（节拍相同）」, 另一条用虚线。
4. 折线只给**一条**系列打标签 (`plots[0].has_data_labels=False` 再单独开 `series[i].data_labels`), 否则同点标签叠印。
5. 环形图窄扇区 (<6%) 的百分比标签宽于色带 → 关 `has_data_labels`, 比例写到环下方文字里。
6. 饼图 `add_chart` 给的矩形中心 ≠ 扇区中心 (图例占位) → 左移 x 并加宽, 用渲染图核对标题/图例/扇区中心三点对齐。
7. 方框内正文 ≤ 6 字, 否则出现「基/准」「三百/件」孤字行。脚注用 #6B7280 (原 #8A8A8A 对比度不够)。

**版面判据自证 `tools/verify_deck_layout.py`** (子代理视觉复核不可用时的替代, 86 项):
① 内容带形状在安全区 (排除模板自带的标题带 y<0.95 / 页脚 y>6.85 / 满幅装饰条)
② 块不重叠: 图表 / 数字条 / 卡片 / 长文本框 四类块两两不相交 (包含关系放行)
③ 图表: 不得有两条数值完全相同的系列 (会完全重合导致标签叠印); 折线只允许一条系列带标签
④ 渲染 PNG 墨迹下边界 >= 500/750 (治「上重下空」这一视觉问题)
⑤ 主体左边界落在 96px 对齐线 ±6px
⑥ 内容左边线全域统一到 **0.96in**: 图表 0.72→0.96、说明文字 0.85/0.90/0.92→0.96; 段落框高度必须按文字给
   (给 3.1in 会与下面 5.62 起的数字条框相交, 判据会红 —— 不是视觉问题但会阻断验收)
❗ 子代理 402 余额不足时不要反复重发: 换成本地可跑的形状坐标 + 像素墨迹判据, 并告知用户计费状态。

## 15. 全工程用语清理 (老倪: 不要有 AI 的味道)
禁用表述: 真源 / 写死 / 真的重写 / 说白了 / 搞定 / 兜底 / 踩坑 / 干什么活 / 卡在哪。换成:
唯一依据 / 预先固定或硬编码 / 重新生成 / 直白地说 / 完成 / 保障 / 遇到问题 / 做什么 / 阻塞点。
- 工具: `tools/sweep_wording.py` (规则表驱动, `--apply` 才改) + `tools/verify_wording.py` (判词表直接 import RULES, 不重复维护)
- ❗ 三个坑: ① 替换器会把自己的规则表也改掉 → `SKIP_FILE` 必须含两个工具自身;
  ② `config` 是软链到 `data/database/zmax/sources/config`, `os.walk` 不跟随 → 额外扫 `data/database/zmax`
  (否则功能备注里的旧词会跟着 export_meta_doc 重新流回文档);
  ③ 改完必须重新生成产物 (PPT/立项报告/工程手册 docx/元任务计划 docx/渲染图), 否则二进制文档里还是旧词。

## 12. 汇报口径
只说: 元任务数 / 优先级分布 / 排期与溢出 / 一致性结果 / 产物路径 / 飞书回读结果。
**编号必须点明**: 摆盘在工程里是 `TASK-06-TRAY`, `TASK-07-AOI` 是 AR 光学质检 ——
老倪说「task7 的摆盘」时把两种编号并列标出让他确认, **别默默按自己的理解改**。
