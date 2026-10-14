# 全链路演练 · 功能点描述真源 · 专利一键导出（2026-10-14 老倪）

老倪原话：
> 「你来演练一下，最开始从 任务配置 开始，你通过全局数据空间，依次配置 产品配置，功能配置，模型配置，
> 性能配置，工程配置，工单配置，最后将文档配置的结果发到飞书，同时真正启动状态空间的原型运行测试验证
> 流程；当前每个任务，都要走一遍，每个场景，都要有实际 topic 的输出，实际波形的运行，以及实际模型的
> 运行与自主训练；现在有 7 个任务，要有 7 个文档要发到飞书，同时更新工程数据库，保证数据一致性。」
> 「你要注意文字表达，不要太AI化，要朴素工程化，面向问题，痛点，从实际出发。你来修改每个功能点的描述。」
> 「以后每个功能，需要独立成一个研究成果，都可以申请专利，所以你要预留专利申请一键导出的功能。」

## 1. 演练编排：`tools/run_full_drill.py`

一个任务走 9 步（**每步都留证据文件**，`reports/drill/<TASK>/`）：

| 步 | 干什么 | 真源/执行体 | 产物 |
|---|---|---|---|
| ① | 配置链 7 域快照（依序：任务→产品→功能→模型→性能→工程→工单） | 各域真源 JSON 实读 | `config_chain.json` |
| ② | 场景切换 | `tools/ss_scene_switch.py`（**只有 3 个任务有映射**，其余 skipped 明说） | 记在 config_chain |
| ③ | 原型**单步**真跑：按该任务 `enabled_nodes` 依次 `execute_node_logic` 真执行 | `lerobot.engineering.runtime` + `tools/ss_bus_topics.py` | `step_run.json` + trace.jsonl 的节点输出 topic |
| ④ | 原型**整体**运行（引擎闭环，按口径不序列化） | `tools/pipeline_closure_run.py --steps N` | `closure_run.json/.txt` |
| ⑤ | 实际波形（真数据出图，matplotlib Agg） | ③ 的 topic 载荷 + ④ 的阶段耗时 | `waveforms/*.png` |
| ⑥ | 实际模型运行证据 | 从 ④ 的 stdout 抽 L2 YOLO / L5 planner / L4 UnifiedNode·INTACT·事件头 | `models.json` |
| ⑦ | 自主训练（有界步数真跑） | `tools/joint_train_all.py --only L4 --steps N` | `train.json` + stdout |
| ⑧ | 每任务一份文档 | `md → export_meta_doc.md_to_html → soffice` | `*.md/.docx/.pdf` |
| ⑨ | 工程库 + 一致性 | 先 `engineering_db.py build`（②改了画布真源，不重建必报漂移 `['project','canvas']`）再插 `drill_runs` 表 → `check` | `INDEX.json` |

用法：`./gui-venv311/bin/python tools/run_full_drill.py --tasks all --steps 60 --train-steps 20`；
只重出文档（改模板/描述后不必重跑）：`--docs-only`。

**坑（实测）**：
- 节点逻辑里有构造 QWidget 的 ⇒ 离屏单步前必须先建 `QApplication`（`QT_QPA_PLATFORM=offscreen`），
  否则 `QWidget: Must construct a QApplication before a QWidget` **直接 core dump**（整个演练进程死）。
- `ss_bus_topics.publish()` 返回的是 `topics`（列表）+ `node_id`，**没有 `topic` 键**；trace.jsonl 里载荷键是
  `value`（不是 payload/out）。读错键 → topic 列全空、波形画不出来。
- `docs/PIPELINE_STATE.json` 的 `stages` 是 **dict**（key=l5/mem/l2/l4/l3/exec/closure），耗时在 `note` 文本里，
  没有 `ms` 字段。
- 一个任务单步 51 个节点会真加载模型（YOLO/INTACT/前馈加速器），耗时以分钟计；7 个任务串行是几十分钟量级。

## 2. 功能点描述真源：`data/database/zmax/function_notes.json`

- 结构：`{"count":N, "notes": {"FN-xxx": {"name":..., "work":"干什么活", "pain":"卡在哪", "state":"当前状态"}}}`；
  74 个功能一个不少。
- 口径：**每条 ≤60 字、须含至少一个真源具体事实**（参数 ID/数字/文件名/验证方法名）、禁宣传话术
  （赋能/生态/抓手/全面提升/显著提升/智能化升级/助力/打造/一站式/无缝/深度融合/颠覆/行业领先/大力）、
  `state` 用工程口径词（在役/未接入/待标定/缺口/接入中/待定/只有…）。
- 判据：`tools/verify_function_notes.py`（覆盖/文字/依据/进库一致 9 项）。
- 进库：`engineering_db.py` 把描述并进 `functions` 表 `note_work/note_pain/note_state` 三列（`_j` 在那里是
  **json.dumps** 不是读 JSON，要用 `json.loads(_read(path))`——踩过假空值），判据加 `⑦b`。
- 引用方：`export_meta_doc.build_meta_tasks()` 的 `note` 字段 → 元任务表 tooltip / 元任务计划文档 / 交底书。

## 3. 专利一键导出：`tools/export_patent_draft.py`

- **一个功能点 = 一份交底书**（74 份），产物 `reports/patents/<FN>_<名>_专利交底书.md/.docx/.pdf` + `INDEX.json`。
- 章节：发明名称 / 技术领域 / 背景技术（现存问题）/ 要解决的技术问题 / 技术方案 / 有益效果 / 具体实施方式
  / 附图说明 / **证据清单（每条标真源文件+字段）** / 检索关键词建议 / 待补项。
- 铁律：内容全部实读真源（`config_meta.json` + `function_notes.json` + 画布连线 + `library.py` 模块 + 演练证据），
  真源没有的写「真源未登记」，**不许编**；文件名要安全化（功能名里的 `/` 会让写文件直接失败）。
- GUI 入口：配置中心 → 📋 任务配置 → 元任务表下方 `📄 专利交底书 (选中功能) / (全部 74 份)`；
  `DOC_SCRIPTS["patent"]`（文档配置页可一键点）。

## 4. 数据总线/话题（老倪「每个场景都要有实际 topic 的输出」）

- 口径来源 `tools/ss_bus_topics.py`：每个画布节点 ≥1 个输出话题 `ss/<node_id>/out`；**单步=真序列化**
  写 `zmax_data/dataspace/trace.jsonl`，**整体运行=只登记不序列化**（性能闸）。
- `tools/dds_bus.py --check` 曾整表崩：`busdb.stats_rows` 对「族条目」（`ss_node_out`，没有单个 `topic` 字段）
  取 `m["topic"]` → KeyError。已改成 `.get` 兜底并显示 `ss_node_out (89 个话题)`。
- DDS 回灌/订阅要 `venvs/dds-venv/bin/python`，档位文件 `~/.zmax_telemetry_mode`（prod 档按量产零开销不发）。
