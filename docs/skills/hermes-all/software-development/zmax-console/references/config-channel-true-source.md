# 「配置通道」/配置中心模型配置 —— 必须唯一依据现算, 不许留手写实验表

## 老倪口径 (2026-10-14)
> 「你看下面的配置通道，都是之前的模型配置了。现在要与状态空间工程实际数据一致。
>   最开始配置中心的模型配置，就是配置模型的。也没对应上啊」
> 「还有个 SAM3 呢，怎么搞？」

⇒ 界面上任何"模型/参数"表象 (配置通道大表、配置中心模型配置域、模型引擎窗口) 都必须是
**同一份唯一依据现算**, 且必须能回答"这层到底在跑哪个模型", 而不是残留某次实验的对比表。

## 落点: `tools/model_config_matrix.py` (单一唯一依据)
- 列 = 真实层 L2/L3/L4/L5 (不是旧 Model Zoo 的实验名 ACT/SmolVLA/AWE/官方专家…)。
- 行 = 四组 + 一组候选:
  🏗 模型身份(在役模型/版本/权重路径/权重体积/状态) · 🧠 结构与训练(架构/参数量/微调方式/训练入口/最近训练/最近一次结果)
  · 🔗 状态空间接入(状态空间节点/输出话题/节点源码) · 🔎 候选(未在役)(候选模型/候选判据)
- 读的唯一依据: `tools/model_inventory.py --json` + `8796 /status/all` + `state_space_obs.json`(画布节点 id) +
  `config/mcd/param_registry.json` + `reports/joint_train_*/summary.json`(真训 rc/秒)。
- 输出三用: `--json`(GUI) / `--write`(缓存 `reports/model_config_matrix.json`, GUI 冷启动读它不阻塞) / `--check`(判据: 四层 × N 项无空值)。
- **取不到一律写 "唯一依据未登记"，不编数字**; 唯一依据全取不到时界面**明写"取不到"并拒绝退回旧表** (拿旧数据当现状=骗人)。
- `extras` 键 (如 `SAM3|基座路径`) 供配置中心模型配置域做单项参数 (在役/候选之外的独立能力)。

## 层的"好几个模型"要如实并列 (本次教训)
每层往往不止一个模型: **在役 1 个 + 候选 N 个** (L2 就有 YOLO 在役 + SAM3 开放词汇分割 候选)。
- 只取 active 那个 ⇒ 界面上 SAM3 直接"不存在" ⇒ 老倪一句「还有个SAM3呢」就穿。
- 做法: matrix 多出一组 `🔎 候选 (未在役)` → 列该层所有非在役产物 + **为什么没切**的判据
  (判据唯一依据 = 8796 的 `note_short`; 有产物但没做过 A/B ⇒ 写"产物未评估(尚无 A/B 判据)"。
- 候选被整个漏掉的**根因常在清单侧**: `model_inventory.py::_layer_candidates()` 按层 glob 固定目录,
  别的能力 (SAM3) 不在那些目录 ⇒ 清单没有 ⇒ 三个界面一起漏。**修在清单, 不在界面**。

## 配置中心: 参数注册用 `matrix` 类唯一依据 (`tools/mcd_build.py`)
- `_model_matrix()` 把 `groups[].rows[].vals` 拍平为 `"<层>|<行名>"` 键, 并把 `extras` 一并拍平。
- 参数写成 `read=("matrix", "L2|候选判据")` 即可 (与界面同一份缓存, 「改一次三处同步」)。
- `_cur()` 支持的 kind: `calib/manifold/dbc/cfgspec/perf_spec/model/matrix`; **`file` 这种 kind 不存在**
  (写了会静默 None ⇒ 就绪度缺口里冒出一片未接线)。路径类唯一依据要走 `matrix`/`model`。
- 判据: 跑完 `mcd_build.py` 看就绪度缺口列表里**不该出现本轮新增的 id**。

## 长格被 Qt **静默右截**（连省略号都没有）—— 实测一轮
症状: 读屏报“表头 L4 变 `INTACT-JEPA 意图-动`、L5 变 `(L`，后面空白无省略号”；权重路径 86 字绝对路径在 581px 列里只看见左半截。
- **列头写法**: 别用 `name[:16]` 硬切（切在词中间且无提示）⇒ 按**词边界**取短名（split 空格/括号）+ 超长才加 `…`。
- **长值格**: ① 全部值格 `setWordWrap(True)` + 按 `QFontMetrics.horizontalAdvance(text)+12` 与列宽算出**需要几行**，
  给每行 `setRowHeight(lh*行数)`（末尾再按行高总和 `setFixedHeight` 定表高，顺序不能反）；
  ② 路径这类“尾部才是身份信息”的值，显示 `…`+尾部 N 字（**明示省略，不静默**）+ 完整值进 tooltip —— 与模型引擎窗口同一口径。
- **可复用的判据（代替目检）**: 逐格量 `字宽 vs 列宽`；跨列行（`columnSpan>1`）按**跨列总宽**算；开了 wordWrap 时按
  `ceil(需要宽度/列宽) * 行高 <= 实际行高` 判“没丢字”。实测判到 6 处分歧（权重路径4格 + 节点1格 + 分组行1格），
  修完为“全部放得下”；其中分组行那格是**假阳性**（未算 span）。

## 表"只显示前几行"的真因可能是**父链上的内层 QScrollArea**（实测一整轮）
症状: 表自己尺寸/行数/行高都对(2866×1522、 21 行、 首可见行 0、 表内 max=0), 但真机画面只看得到前 5 行,
紧跟着就是下一个区(容器管理)——看着像表被“固定高度容器”裁了。
- 取证方式 (别猜): 离屏建窗 → 拿 `findChild(QTableWidget, "<objectName>")` → 打印**父链**每级的
  `类名/几何/min-max 高/sizePolicy/布局类型/外层滚动 max`。实测父链: `QGroupBox(1687) → qt_scrollarea_viewport(600)
  → QScrollArea(min=600, max=1087) → ...` ⇒ 就是**内层滚动区最小高 600px** 在切。
- 修法: 把内层 QScrollArea 的 `setMinimumHeight(内容 sizeHint 高)`（整页滚动交给**外层** QScrollArea）。**只能改最小高，
  不能改表高**（表高已经是按内容定的）。
- ⚠️ **时序**: 建页那一刻表还没挂进页面的 QScrollArea（父链没接完）⇒ 建页时改不到；`showEvent` 在
  "页面已可见后才建内容"的时序下也不触发 ⇒ **用 `QTimer.singleShot(800/2500/6000, …)` 补几拍**兜住。

## 两个“编译通过但静默不生效”的坑（各浪费一轮）
1. **模块别名**: studio.py 里模块级是 `QTimer`，`_QTimer` 只是个别函数内的**局部**别名 ⇒ 写成 `_QTimer.singleShot`
   会 NameError，被 `except Exception: pass` **吞掉**，整段形同不存在（debug 时才看出来）。写完带 try/except 的修正代码，
   一定加一条 `ZMAX_*_DEBUG` 环境变量下的 print 确认它真的跑了。
2. **patch 掉的 `def` 行没补回**: 替换 `old_string` 时若旧串里包含 `def xxx(self):`，新串必须**原样补回**，
   否则下一个方法体会被并入上一块（Python 仍能编译！）⇒ 运行期 `AttributeError: 'X' object has no attribute 'xxx'`
   → 建页异常 → 遗留线程 → `Fatal Python error: Aborted (core dumped)`。判据: 改完先
   `python -c "import ast,sys;ast.parse(open(f).read())"` 不够，要**真建一次页面**（或用
   `grep -n 'def <方法名>'` 确认每个被改文件的方法都在）。

## 旧表下线: 删代码, 不是不调用
「都是之前的模型配置了」⇒ 旧的 `ZOO_SPEC/ZOO_MODELS/_build_zoo_table`（114 行）**直接删**：留着就有被重新接上的风险。
- 删后必须清扫引用: `hasattr(self, "zoo_table")` 这类守卫会静默变 False ⇒ 把控件坐标注册 `_holo_coord_register("P03",…)` 改指向新表 `cfg_matrix_table`。
- 回归判据写进 `tools/verify_model_engine_unified.py`（⑧配置通道唯一依据现算 ⑨表高按内容定 ⑩列头不硬切 ⑪矩阵唯一依据 --check PASS）⇒ 现 11/11。

## PyQt 布局崩溃坑 (实测 core dumped, 一整轮)
`layout.addLayout(x)` / `layout.addWidget(x)` 在 **QFormLayout** 上不存在 ⇒ 建页时 AttributeError ⇒
遗留后台线程 ⇒ `QThread: Destroyed while thread is still running` ⇒ `Fatal Python error: Aborted` (core dumped)。
- 症状: `studio_ctl.sh restart` 打印 `Aborted (core dumped)`, status=stopped。
- 修法: 按类型自适应 + 把 bar 包成 QWidget:
  `if hasattr(layout, "addRow"): layout.addRow(w) else: layout.addWidget(w)`。
- **排查顺序**: 先在启动日志里找 `Aborted` 上面那几行 Python 异常 (这次就是 `_build_config_matrix` 的 AttributeError),
  不要先去怀疑 DDS/mujoco 线程 (崩溃栈里那些线程只是陪葬)。

## 反复重启 GUI 会被守卫拒（不是故障）
`tools/studio_ctl.sh restart` 在**距上次启动 <300s** 时会打「⛔ 拒绝: 控制台才起了 179s（<300s）」并
**返回 exit 0、status 仍是旧的 pid** —— 看着像“重启成功”，实际跑的还是旧代码。必须改代码后验证界面时:
`bash tools/studio_ctl.sh restart --force`（一次到位，别反复刷 —— 老倪已投诉窗口闪来闪去）。
判据: `pgrep -f 'tools/gui/studio[.]py'` 的 pid 必须变，且新 pid 存活。

## 相关
- 模型引擎窗口 (L2~L5 四层表 + ▶训练) 见 `references/status-panel-and-model-engine-window.md`。
- SAM3 能力本身 (权重/适配器/A-B 判据/掩膜绑帧) 见技能 `open-vocab-segmentation-sam3`。
