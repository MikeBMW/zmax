# 子系统配置落地 + 交付包导出 (以 System 1 / 泰国摆盘为例)

## 场景
用户给一份人工写的功能清单(常带口径矛盾), 要求"在配置中心定义某个子系统的配置, 可导出, 可独立发放供应商"。

## 真源链条 (改这里, 不改生成物)
```
config/platform/zmax_platform.json   # 产品/子系统(rows,kpi,axes.cfg/cal/dia)/product_features  ← 子系统配置真源
flows/scenes_5jobs.json              # 场景真源 (+ tools/task_build.py 的 PLAN[scene_type] 计划表)
   ↓ tools/task_build.py             → config/tasks/tasks.json            (任务配置)
   ↓ tools/engineering_db.py build   → data/database/zmax/zmax_engineering.db (单一工程库)
   ↓ tools/mcd_build.py              → config/mcd/*.json (配置中心 MCD 参数表, 5 域)
```
- `subsystems[].axes.cfg/cal/dia` 会按**每个功能节点**复制成 fn_axes (12 项 × 4 节点 = 48 条 cfg), 是"子系统配置项"在配置中心里的可见形态。
- "功能"表 = 画布节点, **不要手工往 functions 加行** (verify_platform_spec 断言 functions 数 == 画布节点数)。
- 产品级功能清单落在 `product_features` (pf_id/product_id/title/capability_ref/subsys/kpi/status/descr/module_refs), capability_ref 必须命中 feature.dbc 的 BO_ id (工程库自检④)。
- **新增真源文件必须同时落一份到 `defaults/config/...`(出厂骨架)**: 全新实例从 defaults 起步, 骨架里没有它 ⇒ 该功能在新机器上直接缺失
  (`verify_platform_spec.py` 会数骨架文件数, 加文件后重跑)。提交走 `git add -A tools/ defaults/`: `config/` 是指向
  `data/database/zmax/sources/config` 的符号链接(数据目录不在代码库), `git add config/` 直接报 `fatal: pathspec 'config/' is beyond a symbolic link`。

## 落地流程 (必须备份→写入→回读核验)
1. 备份: `cp <真源> <真源>.bak_<ts>`; 用 json.load/dump(ensure_ascii=False, indent=1) 保格式, 别整文件重排。
2. 只 append/update 键, 不删; 写完立刻重新 load 回读断言 (行在、轴在、条数对)。
3. 新增场景必须同时在 `tools/task_build.py` 的 `PLAN[scene_type]` 加计划条目, 否则 task_build 会缺该任务。
4. 重算: `task_build.py` → `engineering_db.py build` → `mcd_build.py`。
5. 三闸: `engineering_db.py check`(判据全绿) · `verify_platform_spec.py`(18 项) · `config_center.py check`(阻塞项看是否**改动前就存在**)。

## 导出 (发放供应商)
- 工具: `tools/sys1_delivery.py` (读工程库 + 平台真源, 只读不产生第二份真相), 挂到 `config_center.py sys1 [show]`。
- 产物 `outputs/sys1_delivery/sys1_<ts>/`: `sys1_config.json`(机器可读) · `sys1_供货配置说明.md`(供应商版) · `sys1_功能清单.csv` · `manifest.json`(文件 sha256 + 源库 sha256, 可核验)。
- 包内必须写清**供货边界**(交什么/不交什么) 与**接口契约**(上游给意图不给轨迹; 坐标真值由 Sys-0 提供; 安全红线 Sys-1 只读无否决权) 与**缺口**。

## 导出 SOR (Word)
- `tools/sor_export.py` → `config_center.py sor [json]`; 依赖 **python-docx** (装进 gui-venv311: `./gui-venv311/bin/python -m pip install python-docx`; venv 无 pip 二进制, 必须走 `python -m pip`)。
- 章节 = SOR 模板 1–15 章 + 附录 A(功能配置 cfg/cal/dia)/B(系统组成)/C(待确认)/D(可复现 sha256)。用户点名要的两块: **第 5 章性能参数**(含 EVT/DVT/PVT 阶段与来源条目) · **第 4 章功能需求与功能配置**。
- 真源里没有的项一律写“待确认”并汇总到附录 C, 不编造; 静态采购条款(交付地点/电源/气源)标注需我方填入。
- **fn_axes 有两个来源**: `子系统 cfg/cal/dia 轴`(真正的子系统配置项) 与 `画布节点 params`(引擎实现参数, 会混进 `source = xxx.py`、`class Xxx`)。导供应商文档必须按 `src` 过滤, 节点项单独放“仅供追溯”小节, 否则文档会夹代码路径。
- 文件名用“文件编号+版本”(`SOR-OM-ROBOT-<日期>_V1.0.docx`) 对外稳定; 输出目录带时间戳。

## 数据治理 + 协议导出 (与 SOR 同套路)
- 真源 `config/platform/zmax_data_governance.json` (D0–D4 数据分类/权属/可导出/脱敏/保留期 + 模型转售 + SLA)。
- `tools/data_governance.py` = 把条款变成**可执行的闸**: `plan`(允许/拦截清单) · `manifest`(带权属标签+哈希) · `push`(禁导出类别物理拒发, 逐文件 sha256) · `pull`(回传模型登记台账, 缺指纹/哈希不符拒收) · `ledger` · `audit`。挂 `config_center.py data`。
- `tools/agreement_export.py` → `config_center.py agreement`: 《数据平台合作与模型授权协议》Word(正文 12 章 + 附件 A 数据权属/B 模型与转售/C 同步机制/D 审计)。
- 关键原则: **合同写的和工具强制的必须同一份真相** (协议附件从治理真源渲染, 工具从同一真源取闸门)。否则条款只是纸面。
- 导出 Word 复用 `sor_export.py` 的 `h/para/table/footer_pagenum/_font/sha` —— 别复制一份 docx 工具函数。

## 项目立项文档 (BOM 挂功能 · 成本/ROI 自动算)
- 真源 `config/platform/zmax_project_bom.json`: bom.items(每项 **links** 必挂功能/能力) + costdown + labor + commercial + roi + market。
- `tools/project_doc_export.py` → `config_center.py project`(导出) / `bom`(只算账)。章节 0–6: 文档信息/市场/产品项目/研发/财务/立项评审/附录。
- **BOM 每一行的“关联功能/能力”列是设计要点**: links 同时对 `functions(fn_id)` + `product_features(pf_id)` + `feature.dbc` 的 `BO_` 校验，悬空即报(不静默)；反向列“Sys-1 功能无 BOM 支撑”(纯软件功能如 LoRA 微调属正常，报告不拦)。
- **成本口径要对账不要硬写**: 样机=ΣBOM；生产期=样机×`mass_production_factor`(文档 19/25 反推 0.76)；量产期=生产期×`bulk_discount`(0.9)。降本路径(选型切换) **单列为建议方案**，不叠进 19/17 万口径 —— 否则与文档口径对不上。
- **ROI 由指标驱动**: 年节省=人效比×人工成本×班次 → 减维护 → 回收期=售价/净年节省; 盈亏平衡售价=净年节省×目标回收期。文档自带的“盈亏平衡 33 万”往往有未公开的假设，工具算出后**并列两个值 + 标注差异需确认**，不要改数字去凑。
- 三件套同源: `tools/docs_bundle.py` → `config_center.py docs` 一并导出立项文档/SOR/协议，并断言三份 manifest 记录的工程库 sha256 一致。

## 控制台内置「文档配置 / 文档预览」(在 GUI 里直接看三份文档)
- 页文件 `tools/gui/veh6_config_page.py`: 一个按钮 = 一个 `config_center.py` 函数, 输出抓进底部面板。
- 左树加分组 = 在 `_fill_tree` 的 `doms.append(...)` 加一项; 点击分发在 `_on_tree` 加分支。
- **预览要读回真 `.docx`** (`_render_docx` 按 `doc.element.body.iterchildren()` 走段落+表格), 不是读真源重新拼 —— 老倪拿面板/截图当交付证据, 必须看到实际交付内容。
- **一致性做成硬判据**: manifest 里所有 `*_sha256` 递归拍平, 与当前真源 sha 逐条比; 对不上 = 过期 → 预览顶部红字 + 拒当交付件。未被 manifest 记录的真源(平台配置)用 mtime 兜底判 ⚠️。三份文档记录的工程库 sha 相同 = “数据统一”的可验证口径。
- 按钮跑外部脚本用 `subprocess.run(capture_output=True, text=True)` (子进程 stdout 不被 `redirect_stdout` 抓); 退出码非 0 必须把原因显出来, 不静默失败。

## 项目档案 (配置适配不同项目) 与场景/指标验证 (2026-10-10)

- **项目档案 = 覆盖, 不是复制**: `config/platform/projects/<PID>.json` 逐键深合并到基线 `zmax_project_bom.json`;
  项目特有 BOM 项用 `_append_bom_items` 追加 (别在档案里整份抄 items —— 抄了就会漂移)。
  返回 provenance (base/overlay/merged 三个 sha), 改任一档案 ⇒ merged sha 变 ⇒ 文档一致性判据抓得到。
- **覆盖必须保持基线的结构, 否则导出器 TypeError**: `project.milestones` 是 **list of {no,name,owner,due,metrics}**
  (不是 dict), `project.risks` 是 {risk,action,owner}, `project.team` 是 {role,who}。
  本项目未知的值写成「待确认」字符串而**不是**改结构 —— 老倪零容忍: 不编数字, 缺口要能枚举出来。
- **未定价 BOM 项 (price=None) 要容错**: `sum(qty*price)` 与 `money(qty*price)` 都会炸 →
  加 `line_total()`, `money()` 对非数值原样返回「待确认」, 并把未定价项汇总打印 ⇒ 合计里不按 0 计。
- **新增 BOM 项的 links 必须真存在**: 我第一次随手写了 `BO_ F1 安全` ⇒ 判据当场报悬空 (`B21 → BO_ F1 安全`)。
  feature.dbc 里只有 `BO_ A1..E2`; 安全类真源是 `PF-Z700-09 真机安全与急停` / `FN-SYS1-31` (且**只接受当前 system 的 FN-***,
  写 FN-SYS0-50 也算悬空)。
- **文档编号/文件名要随项目**: 否则两个项目都产出 `PRJ-TH-TRAY-*.docx`。
- **真源在 data/ 下 (config/ 是符号链接!)**: `config -> data/database/zmax/sources/config`。
  ⇒ 改 `config/...` 的文件 git **看不见** (data/ 被忽略), 所以只有**代码 + defaults/ 出厂骨架**能入库;
  新真源要同步一份到 `defaults/config/<...>` 才随代码交付。

### 场景功能区可视化编辑 (命名场景)

- 「场景功能区里能可视化编辑某场景」= 把该场景做成**独立目录** `data/scene/scenes/<SCENE_ID>/`
  (objects3d.json + overlay_spec.json), 登记进 `data/scene/scenes/index.json` 的 `named_scenes`,
  并让 `scene_edit.py --scene <ID>` 把 SCENE_DIR 指向它 —— 目录不同 ⇒ 对它的增删改对在役场景零影响
  (实测在役 objects3d/overlay sha 不变)。GUI 侧 `dreamview_scene_edit.py` 加一个下拉 (在役 + 命名场景),
  切换即 `os.environ["ZMAX_SCENE_DIR"]=...` 后刷新。
- `scene_edit.py` 的子命令是 **`rm` 不是 `remove`** (写测试时踩到: remove 会 invalid choice, 测试会误判成"删除无效")。
- 从父场景派生新场景时, 位姿要**优先取现场示教/实测真源** (taught_points、space_points), 未示教的位姿
  source 明写「推导(待现场示教)」—— 别写成"实测", 老倪会追。

### 性能指标在仿真场景验证 (口径必须分开)

- 引擎 = `tools/gui/state_space_sim.py` 的 StateSpaceSim (与画布 ▶运行 / L5 回路**同一个**)。
  N 轮 (不同 seed + 起始扰动) 跑完可从 tr 量: 流程完成/阶段完整性 · 节拍 t[完成] · 终态 X/Y 残差 ±3σ ·
  姿态倾角 (peg_head−peg 轴) · 力超调 (force_norm 峰值/稳态) · 终到残差。
- 🔴 **仿真口径 ≠ 真机口径**: 仿真残差是模型尺度的量 (0.066), 与真机 mm 级 (≤0.30mm) 不同源。
  报告里逐条标「通道: 仿真 / 真机待验」, 仿真值**不写入**指标实测值, 绝不拿仿真值冒充实测值。
- 场景/验证器引用的 `perf.*` id 必须是真源里存在的 (加 `--check-ids` 判据; 我一开始编了 `perf.face_gap_mm`,
  真源里其实是 `perf.face_gap`)。

### 主参数 M 的能量标定 (「主参数要有值, 类比能量/能级」)

- M 的物理身份是**等效惯量尺度** (进二阶演化 v ← v + (F/M)·dt) ⇒ 用能量定它是有量纲依据的:
  `M = 1 + (½·m_eff·v² + m_eff·g·h)/E_ref`, 归一化到 [0,8]; 能级 E1~E4 是 M 的离散档。
  同一份真源里每个输入标来源或「假设(可标定)」, 推导存进 `_energy_derivation`。
- **不自动开 inertia**: 开二阶须先有 ΔV<0 证据 (零回归), 工具只标 M, 不代开开关。

### 节点快照的幂等铁律

- 🔴 **别往 cfg_snapshot 里塞 tuple**: 存盘经 JSON 往返 tuple→list, `cur == want` 永远不成立 ⇒
  `--check` 永远报「需更新」而写入却"成功" (静默不幂等)。用 `[[gid, n]]` 而不是 `[(gid, n)]`。
  同类: 别把易变字段 (生成时间/回读时间) 放进快照, 否则每次都"需更新"。

### 页内 3D 可编辑视图 (页里嵌第二块 3D 怎么做)

- **页内第二块 3D 一律用 QPainter 正交投影自绘, 不开第二个 GLViewWidget**: pyqtgraph 的 shader
  句柄绑第一个 GL 上下文, 第二窗口全画不出来 (qt-gl-rendering-pitfalls 坑 1)。实现要点:
  正交基 (az/el → fwd/right/upv) · 屏幕↔世界反算 (屏幕位移→地面 XY 平移用 2×2 逆: det = right.x·upv.y − right.y·upv.x) ·
  远→近深度排序后画面+边+标签 · QPen/QBrush/QPolygonF 都要显式 import (QPolygonF 在 QtGui)。
  实测取证: `view.grab().save(png)` → PIL 数非背景像素/对象色/轨迹色 (非背景 4.4 万 = 真画出来了)。
- 编辑写回仍然只走 `scene_edit.py` (备份+原子写+回读): 拖动→`update --kind objects --id <name>`。
  🔴 回读成功的字段名是 **`readback_ok`** (不是 `readback`); 另外写完后**不能把选中清掉**
  (reload 里 reset self.sel ⇒ 连续拖动第二次就 "找不到 id/name=None") — 要按 name 找回选中。
- 在役场景 `overlay_spec.json` 有**实时发布器** (定时刷 ts/updated_at/l5live) ⇒ "在役场景未被改动"
  的判据**不能比文件 sha** (会假红), 要比语义内容 (排除这三个易变字段)。
- QPainter 3D 页内视图的证据图存 `outputs/ui_shots/`。

## Word 文档的表格/版面 (交付件可读性)
- **列宽要真生效必须四件套**: `w:tblLayout=fixed` + `w:tblW(dxa)` + `w:tblGrid` 每个 `gridCol` + 每格 tcW。
  只设 `cell.width`(tcW) 时 Word/LibreOffice 会按**等分**排 ⇒ “五列表一律 20%”“两列表 50:50”“逐行末字孤行”。
  这个症状很像“列宽设错了”，实际是“列宽根本没被采纳”。
- `w:cantSplit` 必须**等数据行都 add 完**再逐行打 (建表时只有表头行, 此时打只保护表头)。
- 表头行加 `w:tblHeader` 跨页自动重复; 留白用 `w:tblCellMar`; 斑马纹用 `w:shd` 逐格填。
- **版面**: python-docx 默认 **Letter** (转 PDF 实测 612x792pt) ⇒ 国内交付件必须显式 `page_width/height = A4` (595x842pt)。
- 列内容重复要查: `module_ref` 常与 `name` 同值 ⇒ 两列一模一样白占宽度 (定列前先比一遍)。
- **把“不许折行/不许孤字”做成硬判据时, 不要用“模拟折行”** —— 我写过一个“优先断在空格/逗号”的
  折行模拟, 它把“填满就断”的真源判成安全, 四轮视觉复核揭出来的孤尾 (`…可行力作` / `业)`)
  它一个都没报: **用错误的排版模型当判据 = 假绿**。改用不可证伪的硬口径:
  `估计单行宽 (CJK 3.35mm + ASCII 1.7mm/字) ≤ 列宽 - 0.60cm` ⇒ 该列**必须单行**。
  代价是要把超宽的单元格收短, 但解释性文字可以整到下方说明行 —— 信息不丢, 只是不在表里挤。
- 各列“吃紧/留白”会**互相搬运**: 把宽度给 A 列就一定从 B 列拿 ⇒ 一次只改一列并把两列都量一遍,
  否则下一轮复核就会打回来 (实测: 单位 1.6→2.0 替走的目标值 0.4cm 直接造成全表折行)。
- 表下面那种“每条指标一行小字说明”的清单, 标签不要同词重复 (“口径 工艺口径”): 有标准才加方括号
  `· id [ISO 9283] · 测法: …`, 没标准就不加。
- 对齐用“**整列都短**才居中”判据, 不要逐格判 —— 同一列有的居中有的左对齐, 多行时更乱。
- **列宽是零和预算, 要量不要感觉**: 定列前先把每列最长一条估出来 (9.5pt 下 CJK ≈ 3.35mm/字, ASCII ≈ 1.7mm/字)
  与目标宽度比 (A4 纵向可用 16.0cm)。给 A 列加的宽度必然从 B 列扣 ⇒ 孤字/折行只会在**邻列复发**,
  “这轮修好了指标列、下轮最刺眼的变成目标值列”就是同一个病灶搬家。一条都不好砍时, 正确解不是继续挪宽度, 而是
  **删/并不含独立信息的列** (与别列重复、或大半是同一个固定值的列, 如“引擎模块”“口径/标准”), 把它的内容并入
  同一行的说明文字 —— 既不动信息量又把宽度还给真正吃紧的列 (实测: 58 条里 36 条超宽 ⇒ 只能靠删列解决)。
- **两个折行判据 (确定性, 不用看图, 写进测试防回退)**:
  ① 关键列不允许折行 — 该列每条估宽 ≤ 列宽 − 0.30cm (单元格边距);
  ② 长文本列折行要“像话” — 模拟 CJK 折行 (可在 ` `/`/`/`;`/`,`/`(` 处优先断) ⇒ 最多 2 行, 且**末行不得短于列宽 30%**
     (小尾巴 `A02)`、`EVT)`、`待确认)` 就是这条抓出来的)。
  改列宽后必须**两条一起过**: 只满足其中一条, 另一列立刻成为下一个病灶。

## 文档出图核验 (老倪把画面当结果)
```
soffice --headless -env:UserInstallation=file:///tmp/lo_profile --convert-to pdf --outdir <dir> <docx>
pdftoppm -png -r 130 -f 2 -l 5 <pdf> sor_page     # 再交给视觉模型逐页挑毛病
```
不带 `-env:UserInstallation` 时 soffice 常直接不产文件。列宽/斑马纹/孤行这类问题**看图才看得出来**。

**“整行有没有被页切开”不用看图, 用文字层判**: `pdftotext <pdf> -` 按 `\f` 分页, 每行抽
「首格文本」与「末格文本」(去空白後子串匹配), 两者必须落在同一页; 配 `cantSplit` 一起用。
注意: 视觉复核看的是**它当时磁盘上那版图** —— 改了写法后必须**重新出图再让它看**, 否则它会报已经修好的毛病。
提问方式决定它是否有用: 要**逐条点名上轮报过的条目**(“这几个名字现在是单行还是仍折行? 逐个说”), 它才会逐条核对而不是重新泛评;
再问一句“现在最刺眼的一处是什么、你会怎么改”。它给的下一处病灶通常是真的, 但可能与我这轮改动**互相抵消**(见上“零和预算”)。
所以: 能**从文本层或 XML 量出来**的结论 (列宽、折行、跨页) 一律先用判据自证, 不要只凭看图结论动手 —— 文本层还能反驳过期的视觉结论
(例: 它报“某行被跨页劈开”, `pdftotext -f N -l N` 显示该行完整落在下一页 ⇒ 是我修完之后它看的仍是旧图)。

## 性能指标定义 (机器人学口径 + 工艺口径, 要“定义”不是“列举”)
- 真源 = 一个新 json (`config/platform/zmax_perf_spec.json`): `standards`(引用的标准及口径) + `groups[]`(A...F
  分组) + 每组 `metrics[]`。每条**至少六个字段**才算定义完: `id` / `cn` / `unit` / `target`(目标值=规格) /
  `how`(怎么测·实测入口) / `std`(引用标准) / `stage`(EVT-DVT-PVT) / `links`(关联功能能力)。只写“精度±1mm”不叫定义。
- 机器人学分组不能少: ISO 9283 位姿可重复性 RP(±3σ·同向·30 次)与准确度 AP、ISO 230-2 反向间隙/升降轴重复定位、
  关节与末端(微动)分辨率、整定时间、静刚度、双臂同步、负载/作业半径。**“可重复定位精度”与“分辨率”是两回事**, 别混着写。
- 工艺分组按**接触对象**切: 电口(金手指: 插深分辨率/终到误差/力分辨率/力超调/接触压力上限不划伤/对位重复性/
  力-位移曲线一致性/插拔寿命) · 光口·光纤(端面非接触安全间隙[触面=判废]/最小弯曲半径/对接力) ·
  光耦合(六轴对准分辨率 µm&µrad/搜索范围/IL/RL/耦合重复性/功率计分辨率/固化前漂移/端面洁净度 IEC 61300-3-35)。
- **目标值(规格) ≠ 实测值**。真源里 `target` 是规格; 配置中心行的 `value` 是实测 (未测 = 缺口, **不拿设计值充实测值**)。
  区分办法: 行的 `kind="spec"`, value 直接取 target 并把状态写成「指标定义(目标值=规格; 实测待验收)」;
  target 以“待”开头(待定/待确认)的才是真缺口。不要因为要“好看”把待定项编个数字。
- 四处必须同一份真源 (每多一处抄写就多一处漂移): 真源 json → **工程库 `params` 表**(kind=spec, 改指标
  ⇒ 工程库 sha 变 ⇒ 文档 manifest 一致性判据才抓得到, 否则改了指标没任何判据响) → 配置中心域 → 供应商文档分章表。
- 上供应商文档时: 表列 = **指标 / 单位 / 目标值(规格) / 阶段** (4 列), 每条指标再跟一行说明
  `· <id> · 口径 <标准> — 测量/实测入口: <how>` (供应商要看得懂怎么测、怎么报)。**口径不单独占一列** ——
  那列大半只写“工艺口径”, 是留白最多的一列; 并进说明行既不丢信息, 又把宽度还给最吃紧的目标值列。
  导出另外给 CSV(Excel 直开) + MD, 入口挂 `config_center.py perf`。
- 判据测试里**不要写死条数**: 从真源算期望值 (`len(metrics)`), 否则指标一长测试就红 (`≥50 条`可作下限断言)。

## 左树点击必须改变右侧工作区 (不只是刷底部面板)
- 病症: 老倪点「性能配置/功能配置/工程配置/模型配置」说“主窗口没有内容”——复现发现 `_on_tree` 对域节点只
  `_run_into("overview")`(只刷底部结果面板), **右侧工作区根本不动** ⇒ 看着像“点了没反应”。
- 规矩: 树节点点击 = ①切到对应页签 ②**筛出该节点的行** (全显等于没筛, 要能量出“3 行/9 行”) ③是具体参数就定位高亮那一行;
  ④找不到的目标要**明说**(不静默); ⑤同时接 `itemClicked` —— 只接 `itemDoubleClicked` 时用户单击一下就以为坏了。
- 每个筛选页配一个「显示全部」按钮, 否则筛完回不去。
- 验证要量数字: “点域后当前页签 != 任务配置” + “该表可见行数 = 3/6/9”(`t.isRowHidden(r)` 数), 不是“看到了”。

## 坑
- 带引号/`#` 的提交信息走 `git commit -F 消息文件`: 把 `"..."` 直接塞进 `-m` 时, 消息里的 ASCII 双引号会提前闭合,
  后面的字被当成 pathspec ⇒ `error: pathspec 'xxx' did not match any file(s)` 且**提交未发生** (`&&` 链断在 push 前)。
- **QLabel 会把同行按钮挤出窗口**: 非换行 `QLabel` 的 minimumSizeHint = 全文宽度 ⇒ 顶栏/工具栏里它不肯缩, 窄窗口下最右侧按钮被窗缘截掉。修法: `label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)` + `setMinimumWidth(0)` + 缩短文案 + 布局尾 `addSpacing(10)`; 并加**几何判据** (`b.mapTo(page, QPoint(b.width(),0)).x() <= page.width()`) 防回退 —— 目测看不出截断。
- 分组里的计数必须写清口径: `文档配置 3/3` 下面列 4 个子项会被读成“数字对不上”; 写 `文档配置 文档 3/3` 才不歧义 (多出来的项是核对视图, 不是文档)。
- `QLabel` 用 `.text()`, 不是 `.toPlainText()` (那是 `QTextEdit`); 探针写错直接 AttributeError。
- 探针里“把真源改成比文档新”要**显式设时间** `os.utime(f, (atime, doc_mtime+60))`: 用 `time.time()` 会因前一个探针刚重生成了文档而翻车(时序竞争); 改真源必须 try/finally 复原。
- `studio_ctl.sh restart` 有 300s 护栏 (反复重启窗口闪, 老倪投诉过), 确实要加载新代码用 `--force`。
- 工具函数签名不要传“半截真源”: `compute(root)` 收整份真源、`check_links(root["bom"])` 收子段 —— 传错就 KeyError('items')/('labor'); 遇到这种报错先确认传的是哪一层。
- 统计“最新导出目录”用 **mtime** (`max(glob, key=os.path.getmtime)`), 不要用 `sorted()[-1]`: 目录名的字母序会把旧目录排在新目录后面。
- 参数表列名 `default` 是 SQL 保留字, 查询要写 `\"default\"`, 否则 OperationalError: near "default"。
- `outputs/` 是指向 external 仓库的符号链接: `git check-ignore outputs/...` 会报 "beyond a symbolic link"; 交付包天然不入代码库 (正好)。
- `config_center.py list <域>` 遇到 dict 值的参数会 TypeError (dunder format) —— 已知缺陷。
- 改动前先跑一次 `config_center.py check` 留基线, 否则分不清哪条阻塞是自己引入的。
