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
| `data/database/zmax/config_meta.json` | 74 个功能的字段/范围/单位/依赖/验证 |
| `sources/config/tasks/tasks.json` | 7 个任务(工艺步骤/overrides/触发循环) |
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

## 8. 汇报口径
只说: 元任务数 / 优先级分布 / 两阶段排期 / 一致性结果 / 产物路径 / 飞书回读结果。
**编号必须点明**: 摆盘在工程里是 `TASK-06-TRAY`, `TASK-07-AOI` 是 AR 光学质检 ——
老倪说「task7 的摆盘」时把两种编号并列标出让他确认, **别默默按自己的理解改**。
