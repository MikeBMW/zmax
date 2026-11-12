---
name: patent-disclosure-authoring
description: "Use when 要把专利写成交底书/批量出交底书, 或汇总专利组合。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [patent, disclosure, docx, deliverable, zmax]
    related_skills: [docx, deliverable-doc-authoring, powerpoint]
---

# 专利技术交底书 (从唯一依据现算, 不编造)

## When to Use
- 用户说「每个专利都要写出来」「要交底书」「汇总一下专利」——交底书 ≠ 已经写好的申请文件稿，两者章节不同，
  别把申请稿当交底书交上去。
- 需要批量出一组专利的交底书（本项目 12 件），或为某件补章节。

## 🔴 两条铁律
1. **唯一依据现算，不手写**：交底书正文一律从 `config/patents/patent_registry.json` 生成，
   改 registry 重跑即同步。手写一份、复制十二份，第二天就会漂移。
2. **唯一依据里没有的，写「待发明人确认」，不臆造**。最容易犯的两处：
   替代实施方式（防规避条款）、发明人/申请号。宁可留空给代理人来问，也不要写一段看起来完整但没出处的话 ——
   交底书是要逐句能对回证据进代理所的。

## 交底书 vs 申请文件稿（别混）
| | 申请文件稿（`patent_center.py --export` 出的） | 技术交底书（本技能） |
|---|---|---|
| 章节 | 摘要 / 技术领域 / 背景 / 发明内容 / 权利要求 / 实施例 | 十节，见下 |
| 用途 | 提交/内部评审 | 交给代理人写申请文件 |
| 必须有 | 权利要求书 | 发明目的、附图说明、关键保护点、替代方案、检索关键词 |

## 十节结构（中国发明专利代理实务常用）
一 发明名称 · 二 技术领域 · 三 背景技术（3.1 现场现状=problems 原文 + 3.2 结构性原因）
· 四 要解决的技术问题（发明目的，描述目标态，不复述 problems）· 五 技术方案（solution 逐步，标「步骤 N」）
· 六 有益效果 · 七 附图说明（给图的内容与出处，不画示意图）
· 八 具体实施方式（实施例 / 实施数据 / 代码证据清单 / 挂载功能条目）
· 九 关键保护点与替代方案（含拟稿权利要求 + 独立权项=核心保护点）· 十 检索关键词建议

## 步骤
1. 读 registry：`config/patents/patent_registry.json` → `patents[]`，每件字段
   `pat_id/codename/star/layer/title/abstract/problems/solution/effects/claims/embodiment/impl_refs/data_refs/fn_ids`。
   缺字段先报，不要用「无」填充掩过去。
2. 跑生成器（本仓库已落地 `tools/patent_disclosure.py`）：
   ```bash
   python3 tools/patent_disclosure.py              # 全部
   python3 tools/patent_disclosure.py --pat ZMP-2026-003
   python3 tools/patent_disclosure.py --no-docx    # 只出 md
   ```
   输出 `docs/<域>/patents/交底书/<编号>_<名称>.md + .docx` + `00_交底书清单.md`。
3. 回读校验（必做，不看生成日志）：
   ```python
   from docx import Document
   need = ['一、发明名称','二、技术领域','三、背景技术','四、要解决的技术问题','五、技术方案',
           '六、有益效果','七、附图说明','八、具体实施方式','九、关键保护点与替代方案','十、检索关键词']
   # 每份 docx 打开、拼 paragraphs 文本、核 10 节齐全 + 表格数 ≥3
   ```
4. 目检排版：Word COM 报页数/字数并导 PDF 当样张，别只信 python-docx 能打开。
   ```powershell
   $w = New-Object -ComObject Word.Application; $w.Visible = $false
   $d = $w.Documents.Open('<abs path>', $false, $true)
   $d.ComputeStatistics(2)   # 页数
   $d.ComputeStatistics(0)   # 字数
   $d.ExportAsFixedFormat('<out.pdf>', 17)
   $d.Close($false); $w.Quit()
   ```
5. 同步/交付前对账 md5（两侧必须一致），并保留一份 PDF 样张给用户预览。

## 坑
1. **三、四节写成同一批文字 = 最典型的退化**：3.1 抄 problems 原文后，第四节又抄一遍 problems，
   两份章节就变成复读。正解：3.1 放现场记录原文；3.2 归纳结构性原因（一到三句，落在本专利的 layer 上）；
   第四节写**目标态**（「使……可比较/可追溯」），不预设手段，手段留给第五节。
2. **docx 中文必须同时设 `w:eastAsia`**：只设 `font.name='宋体'` 只写了 `a:latin`，
   中文会落到主题字体上，打印出来字形不对。`style.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')`，
   run 级同理。
3. **markdown → docx 的表格要自己解析**：按 `|` 切行、跳过 `|---|` 分隔行、`add_table(style='Table Grid')`，
   单元格字号压到 9pt，否则长句把表格撑到跨页。
4. **附图说明不要画示意图**：交底书只给「图 1 对应第五节步骤 1—N」这种内容与出处，正式图纸由代理机构按规范画；
   自己画一张还要被推翻，反而增加来回。
5. **权利要求草稿留在第九节**，不要塞进第五节的技术方案里 —— 方案描述与保护范围是两件事，代理人要分开引用。
6. 文件名带中文和 `—`，用 `re.sub(r'[\\/:*?"<>|]', '_', title)` 清洗后才可跨平台落盘。

7. **手写定稿的正文不进 registry = 现算少件**：`docs/1-天枢-产品边界/patents/ZMP-*.md` 写完了但
   `config/patents/drafts/part_*.json` 没条目，`patent_center.py --build` 出来的 registry 仍是旧件数，
   专利地图 / `00_专利申请渠道清单.md` / 功能渠道覆盖率 / UI 块全部少件。修法：
   `tools/patent_drafts_import.py --write` 从 md 反向生成 `drafts/part_c.json`（摘要取核心思想段、
   问题取背景技术各小节、权利要求逐条、实施例取具体实施方式；文字逐条抽取不改写，star/layer/fn_ids
   由脚本 MAP 人工给定），再 `--build` → `docs_index.py`。别手改 registry，`--build` 会整体覆盖。
8. **件数不许硬写**：`docs_index.py` 的「专利地图 · 12 件专利」曾是字面量，改成 `len(linked)`；
   清单/判据里凡固定件数都要现算，专利一增就静默错。
9. **`defaults/config/patents/patent_registry.json` 是仓库里唯一带版本的真源副本**（`data/` 被 .gitignore），
   改完 registry 必须 cp 同步 defaults，否则新机/换机回落旧件数。
10. **真源引用要能落地**：registry 里 `fn_ids` 引用已从工程库删掉的功能（如 FN-PLAT-62/63/64）、
   `impl_refs` 指向已删除模块（`src/lerobot/engineering/nodes/library.py`、`by_level.py`），
   `verify_patent_channel.py` 判孤儿/判引用不存在。交底书对外脱敏 ≠ 内部 registry 可空引用，
   脱敏件的真实落点由脚本 `impl_hint` 人工给。

11. **纯查看器节点不写专利, 挂「关联」而不是编主张**：如「前馈激活直方图」只读上游写出的
    `_SS_STATE[probe]` 画分布图, 无独立方法; 环境物理世界与引擎真物理同一条 env.step。
    这类按真实代码邻接挂到已写好的那件专利的 `fn_ids_related`, 并在清单/回复里说清「关联≠主挂」,
    渠道可以 100%, 但不得新增未经实测的权利要求。

12. **功能级交底书 (reports/patents, `export_patent_draft.py`) 是另一条线**: 源头是
    `function_notes.json` + `config_meta.json`, 不是 patent_registry。功能增删后要
    ㉑ `fix_function_notes_align.py` (按节点名重挂描述, 缺失的写 function_notes_new.json) →
    ㉒ `engineering_db.py build` (库 note_work/pain/state 才跟上) → ㉓ 重出交底书 → ㉔ 清旧名残留。
    三个必踩坑: `--apply` 原来不重建 `notes_by_name` (库优先按名取, 会整列错位); 旧名文件不清会
    让 `verify_patent_export` 的「证据清单≥5 行」与 INDEX 计数双失败 (产物 125 份 vs 79); 快照里
    判活时 `engineering_db.py stale` 报源文件「没了」要先看是不是该文件已迁走（指纹恒空 = 误报）。

## 专利 ↔ 工程节点的连接键（汇总「这件专利落在哪」时必用）

**不要用 registry 的 `impl_refs` 去碰节点 `source`**。`impl_refs` 是粗粒度的目录/文件级路径，
常含 `policy.py` 这类被多件专利共用的通用文件 —— 实测 12 件只命中十来处，且多件专利撞到同一批节点，是误配。

真链路（每一段都在真源里，可现算，不需要人去维护对照表）：
```
patent_registry.patents[].fn_ids
  → data/database/zmax/config_meta.json 的 functions[fn_id].code_file
  → 画布工程库 mw_node.source（同值 → 该节点）
  → 节点 module / impl_key → 源码 source:symbol
```
实测覆盖 58/79 节点，每件专利挂 1–12 个节点，语义都对得上（如数学内核那件恰好挂到全部流形类节点）。

两个副产物必须单独汇报，它们才是汇总的真正价值：
- **没有被任何专利覆盖的节点** —— 要么补专利，要么承认它只是支撑件，二选一，不能没有说法。
- **`fn_ids` 在 `config_meta.json` 里查不到的** —— 说明专利挂载的功能条目与功能真源之间脱节，
  这类缺口在多件专利上会同时出现，是系统性对齐问题，不是个别笔误。

## 节点源码路径是四处同源, 少改一处就静默掉覆盖 (2026-11-11 实测)

源码从 `engineering/nodes/*.py` 迁到 `middleware/nodes/impl/*.py` 之后, **四处都要改**, 否则专利→节点覆盖静默下降:

| 位置 | 角色 | 改法 |
|---|---|---|
| 各契约 `middleware/nodes/n_*.py` 的 `SOURCE` | 真源 | 手改 (7 个 library.py·func 按函数名映射到同名 impl 文件) |
| `engineering/node_map.json` | 生成物 | 改完契约跑 `tools/gen_node_map.py` (末行 `三层都齐 78 · 缺 0`; `--check` 应 SAME) |
| 画布库 `mw_node.source` (sqlite) | 工程库 | `update mw_node set source=? where node_id=?`, 改前 cp 备份 db |
| `config_meta.json` `functions[].code_file` | 功能真源 | 同样路径替换 (data/ 下, 不进 git) |

判据: 跑 `tools/docs_index.py`, 看 `nodes_covered`。**掉数 = 断链**, 涨回上限才算修好 (本次 78→71→78)。
`tools/verify_patent_channel.py` 改完必须仍 24/24 PASS。

### link() 必须归一化匹配 (真 bug)
`docs_index.link()` 原来 `by_src.get(cf)` 精确字符串相等: 一边 `path`、一边 `path · sym` / `path::sym` / `path:12` / `path --flag` 就断链。
更隐蔽: 一个不带 symbol 的 `library.py` 命中 7 个节点, 把 7 个节点全挂给同一件专利 = **过度覆盖**。
正解: 建 `by_norm`, 取纯路径 (按 ` · `/`::`/`:`/` --` 切) 再比, 精确匹配优先。

### 全量重生成前必 diff
`--no-docx --out /tmp/xxx` 先出一份临时, 与现有 md 逐份 `diff`。本次 001-012 差异只有 2-5 行 (件数分母 12→20 + 已被删的孤儿 fn 行), 确认无手写内容才全量覆盖。
清单标题的「(12 件)」是脚本里字面量, 已改 `len(pats)` —— 件数一律现算。

## 专利→代码落实体检 (交底/收窄前必做一次)

把交底书里的每个步骤拿去对**生产函数**，逐条标 3 态，再决定独权怎么写:

| 态 | 判据 |
|---|---|
| ✅ 生产 | 真链路每帧/每周期调用 (grep 调用点在 src/, 不在 tools/) |
| △ 实验 | 只有 tools/ 下验证或训练脚本调用 |
| ❌ 无 | 只有函数定义(def) 或只在离线模块 |

经验规律: 独权只写 ✅ 的那几条, △ 与 ❌ 全部降到从权 —— 独权写进未上线特征,
一是说明书没真实实施例(审查员问公开充分性), 二是对方只要不做那条特征就自由实施,
而我们真正落地的恰好是剩下那一半, 等于把可维权的那半写成了不保护。

### 三个让"真链路形同未实现"的隐形 bug (实测 2026-11-11)

1. **`x or 默认值` 遇到 numpy 数组直接抛 ValueError(ambiguous)**，外层 `try/except` 把它吞成
   `injected: False, reason: "注入异常"` ⇒ 功能**从未生效**而日志看着正常。判据: 任何来自
   流形/节点输出的量都可能是 ndarray，用 `if x is None` 而不是 `or`。
2. **`isinstance(v, (list, tuple))` 会把 ndarray 排除掉**。生产端写 `np.asarray(...).reshape(4)`，
   消费端只认 list ⇒ 整条触觉通道恒为 None。改为 `np.asarray(v).reshape(-1)` + size 判断。
3. **`json.dump(..., default=float)` 遇数组抛 "only 0-dimensional arrays"** ⇒ 每次落盘失败。
   改 `default=lambda o: o.tolist() if hasattr(o,'tolist') else float(o)`。

### 判据必须分"正常跳过"和"故障"
引入公差带/门限后，正常跳过也返回 `injected=False`，与故障同形。必须在 info 里写
`project.action = "in_tolerance_skip" | "inject"`、`reason` 带具体数值，探针才能区分
"带内不修" 与 "链路断了"。验证脚本按这两个 action 分别立判据。

## 汇总成 PPT 时
专利组合页推荐一张表：编号 / 代号 / 层 / 名称 / **在本技术框架里的位置**，核心件打星并上色；
再配一张「技术主张—权利要求号—实测证据—它保证了什么」的三向映射表 —— 评审和客户能逐条核对，比形容词有说服力。
