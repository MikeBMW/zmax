---
name: pyqt-gui-auto-verification
description: Use when PyQt5 GUI 自动取证测试 — 驱动真实窗口截图作证据入报告。
---

# PyQt5 GUI 自动取证测试 (真人测试工程师自动化)

触发: 让 GUI 自动化"操作所有图表/窗口"做验证、每个用例要截图证据、报告要嵌图。
Z-MAX 仓库具体入口/机制见 `references/zmax-studio-automation.md`;
断言写法 / 证据采集 / 禁词类判据的坑见 `references/assertion-and-evidence-pitfalls.md`。

## 通用工作流
1. 环境: PyQt5 venv; 有 DISPLAY 用 X (3D/GL 窗口才能渲染), 无则 `QT_QPA_PLATFORM=offscreen` (3D/GL 项会失败 — 诚实记录 FAIL, 别假装)
2. 构造应用: `app = QApplication.instance() or QApplication([])` (模块可被 import 复用, 顶层建 app 也无妨; 无 widget 前可后建)
3. 实例化被测主窗口模块 (无参构造常见, 如 `SimulinkModule()`), 调其"打开目标画布/场景"方法 (替代人工点按钮)
4. 驱动数据准备: 引擎/仿真先真实跑一次 (轨迹缓存), 数据源若有独立缓存属性则留存引用 (`_ss_last_sim` 模式: 引擎对象留存供窗口取末帧)
5. 打开每个观察窗口: 优先调 UI 自身的统一打开入口 (`_open_viz_node(kind)` 式分派), 而不是每个窗口手写
6. 截图: `widget.grab().save(png)` + `app.processEvents()`; 查找顶层窗口按 `__class__.__name__` 过滤 `app.topLevelWidgets()` (等 0.1s×N 轮询出现)
7. 内容断言: PIL 读灰图算"非背景像素占比" (`(a>40).mean()`), 每类窗口给独立阈值 (直方图>0.002, 波形>0.005, 3D/视频>0.01); 另断言结构字段 (buffer 长度、投影 shape (512,2) 等) — 截图非空 + 结构字段双保险
8. 汇总: 逐项 {case, desc, pass, evidence, detail} → JSON; PDF 嵌图 (reportlab platypus Image, 中文用 wqy 字体); Excel 加 sheet
9. 多帧数据: 窗口若累积 N 帧才出图 (堆叠/散点), 测试脚本先开窗再逐帧喂真实数据 (如从训练 parquet 回放真实帧跑模型 forward → push 窗口), 别只喂末帧

## 点得中吗？—— 事件级验证 (比 handler 单测、比截图都硬)

控件"点了没反应"有三种完全不同的原因: **事件根本没派发到它** / 命中几何不对 / handler 没接线。
只有事件级验证能一次分开这三层:

1. 离屏真建**真实容器**(如 `SimCanvas(stub_module)`) + 把被测控件加进去。stub 只需在被调用时记一笔
   (`calls.append((名, 参数))`), 并用 `__getattr__` 兜住其他属性。
2. `QApplication.sendEvent(view.viewport(), QMouseEvent(QEvent.MouseButtonPress, view.mapFromScene(点),
   Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))` —— 走完整 `viewport → view.mousePressEvent → itemAt → 命中 → handler`。
3. 断三件: 点控件本体/边缘 → handler 调用一次; 点**不该触发**的区域(控件上方的标题) → 不调用(证明没抢走拖动/选中);
   连点两次 → 状态翻转两次。

- 只测 handler(把方法绑到 stub 上)会漏掉"事件没到"; 只截图会漏掉"位置错/被别的层拦"。
- **自绘控件渲染证据**: 直接 `it.paint(QPainter(QImage), QStyleOptionGraphicsItem(), None)` 渲成 PNG, 再用像素颜色计数
  (开/关两态各数一种描边色的像素, 并核它们落在预期矩形内) + `tesseract -l chi_sim+eng --psm 7` 认状态文字。
  只数"非背景像素"不够 —— 得数**预期颜色**并核**位置范围**, 否则控件没画对也照样"非空"。
- 🔴 **stub 容器要给全它 require 的属性**: 自绘控件常遍历 `scene_ref.links` / `nodes` / `_items` / `_flow_path`,
  缺一个就是 `TypeError: 'NoneType' object is not iterable`, 看着像"控件画不出来"。
- 🔴 **命中代码写在哪一层要按容器的拦截行为定**: 若容器对"子项上的左键"先拦并 `return`(拖拽/选中/端口拖线这类),
  子件自己的 `mousePressEvent` 永远收不到 ⇒ 命中必须写在**容器层**且排在拖拽分支之前。
  旁证法: 找一个**已有的、确认能点**的同型控件(如 radio 档位), 看它做在哪一层 —— 跟它同层就对了。

## 文字/能力类判据 (可选中 · 可复制 · 可编辑) —— 只读 flags 不算验过
- QLabel 默认 `NoTextInteraction`（只能看不能框选）。批量开放: 扫 `root.findChildren(QLabel)` 后
  `flags |= TextSelectableByMouse | TextSelectableByKeyboard`。**跳过条件写 `if want == f: continue`** ——
  写成 `if f & (A|B): continue` 会把"只开了 A"的标签整体跳过，B 永远补不上 (项目里自定义 `_CopyLabel` 只设
  `TextSelectableByMouse`)，结果是鼠标能选、判据 (要 A+B) 却红。
- 动态新建的控件靠 **app 级 eventFilter** 兜底: `QApplication.installEventFilter(page)` +
  `ev.type() == QEvent.Polish and isinstance(obj, QLabel) and self.isAncestorOf(obj)` → 同样 OR flags。
  刷新/换页/重读真源时新建的行才不会落空 (建页末尾的一次性扫描管不到它们)。
- **真验选中**: `QTest.mouseMove` 不带按键状态 ⇒ 拖选后 `selectedText()` 永远空 (假红)。手工发
  `QMouseEvent(MouseButtonPress, pos, LeftButton, LeftButton, NoModifier)` → 多次
  `QMouseEvent(MouseMove, pos, NoButton, LeftButton, …)` → `MouseButtonRelease`，再读 `QLabel.selectedText()`。
- **真验快捷键**: `page.activateWindow()` + `w.setFocus()` + `processEvents()` 后
  `QTest.keyClick(w, Qt.Key_C, Qt.ControlModifier)`，比对 `QApplication.clipboard().text()`。
  树/表格不是 QLabel: page 级 `QShortcut(QKeySequence.Copy, self)` + `Qt.WidgetWithChildrenShortcut`，
  焦点在 QTextEdit/QLineEdit 时转调它自己的 `copy()`；另写一条判据证明没把信息窗的 Ctrl+C 抢走。
- 原生限制如实说: 按钮 / 单选钮 / 页签标题的文字 Qt 不支持框选 —— 只说"标签文字全可选", 别承诺所有控件。

## 已有判据变红: 先取基线, 再断定是谁的锅
改完跑判据看到红，先 `git stash push -q -- <改动文件> <判据文件>` 用同一脚本跑一遍基线，再 `git stash pop`。
改前条数 == 改后条数 ⇒ 零回退 (旧红如实标注"改动前就红"); 只有差异才是本次引入。别把旧红当自己的回归，
也别悄悄把旧红算成通过。

## 判据卫生 (自己别假绿/假红)
- **前提要摆好并还原**: 判据常依赖「全层都启用」这类前提, 而用户的当前档位/开关可能不是全开。用临时改写真源
  (`ui_run.json` 的 `cap_level` 等) + `finally` 逐字还原, 让「全开」判据与「单层」判据各自成立; 别让用户此刻的开关
  决定判据颜色。同一个文件被多个判据文件需要时, `_cap_enter(level)` / `_cap_exit(old_text)` 一对函数最省事。
- **状态覆盖要发生在构造被测控件之前**: 先 `show()` 再 monkeypatch 运行态/真源, 第一帧已按旧状态画过, 残留的输出清单
  (`self._last_arrows` 之类) 会被当成本次证据 ⇒ 假红/假绿。双保险: 渲染函数入口先清空输出清单再判 `return`。
- **通过数在所有判据追加完之后再数**: `npass` 写在追加新判据之前 ⇒ 40 条报成 39/40, 每行都是 ✅ 而摘要说「未通过」,
  最容易被自己骗过去。改完**整脚本跑一遍数条数**。
- **「两次采样必须变」要跨过一个刷新周期**: 刷新是 500ms 时 `sleep(0)` 采样当然一样; 取 1.05s 以上, 并对真源静止的
  情况显式标「本拍不适用」, 不判假绿。

## 坑 (已踩)
- **cv2 自带 Qt 平台插件污染**: 先 import cv2 (ultralytics 等) 后建 QApplication → Qt 从 `cv2/qt/plugins` 找 xcb → "Could not load the Qt platform plugin xcb" (缺系统依赖)。修复: 建 QApplication **之前**设 `QT_QPA_PLATFORM_PLUGIN_PATH=<site-packages>/PyQt5/Qt5/plugins` (遍历 sys.path 找含 platforms/ 的目录)。别只删 cv2 路径 — 显式指定 PyQt5 真实目录即可
- QApplication 只能在 import 任何 Qt widget 前创建一次; 被报告侧 import 时 (cv2 已加载) 也要先设插件 env 再建 app
- offscreen 平台弹窗 API (raise_/activateWindow) 报 "does not support raise()" — 无害, 忽略
- 窗口单例: 挂被测模块实例属性 (`module._xxx_win`), 让"双击打开"与"脚本驱动"共用同一窗口, 避免双窗口
- 引擎跑完只有末帧 probe: 若可视化要过程帧, 从数据文件回放真实帧 (诚实: 模型在真实历史 obs 上真实 forward), 别伪造中间帧
- 有 X 时后台跑脚本会短暂弹窗到桌面 — 可接受; 别用 nohup/后台静默跑 Qt 脚本 (信号/退出问题), 前台超时或 background+notify
- **建页时抛异常 ⇒ 遗留线程 ⇒ `Fatal Python error: Aborted` (core dumped)**: 用了布局没有的 API（`QFormLayout` 只有 `addRow`，没有 `addLayout`/`addWidget`）会 AttributeError，崩栈里赫然是 DDS/mujoco/PyQt 线程在陪葬 —— **先读 `Aborted` 上面那段 Python 异常**，别去怀疑那些线程。挂控件按布局类型自适应: `if hasattr(layout, "addRow"): layout.addRow(w) else: layout.addWidget(w)`。
- 离屏探针退出时可能因残留后台线程 abort（与结论无关）⇒ 探针结尾用 `os._exit(0)`，别让 teardown 崩掉掩盖前面打印的结论。

## 判据必须跟着「界面结构」和「真实交互路径」走
- **取列按列头名, 不按硬编码下标**。表格加/删一列 (`Value` 后插 `Rate`) ⇒ 所有 `item(r, c).text()` 往右错位,
  判据会把 Type 当 Tx 读, 输出成"不一致 398 处"的**假故障**, 白白排一小时。改列结构时: 判据先找 `headerItem().text(i)`
  定位再取值; 顺手把列宽记忆键换代 (`sig/tree_cols_v2` → `v3`), 否则旧宽度错位。
- **判据要量"用户看的那张表的行", 不是底层数据函数**。同一个面板常有两套取数路径 (数据函数已按层/类别过滤,
  表格却走另一条缓存或静态快照), 判据量函数 ⇒ 报"只有 45 行", 用户屏幕上却是 157 行且混着不该出现的层。
  定式: `[w.tb.item(r, c).text() for r in range(w.tb.rowCount())]` 取控件真行再断言; 偏差如实报给用户。
- **往渲染循环里插"补丁遍历"绝不能复用循环变量**。在 `for r, x in enumerate(rows)` 体内再写 `for x in rows:`,
  内层结束后外层 `x` 已指向最后一行 ⇒ **整表每行都显示最后一行的内容** (实测 413 行全变成同一个值),
  肉眼像"数据源坏了"。补丁遍历一律另起名 (`_row2`) 并放在渲染循环**之前**一次跑完;
  探针要额外断言"各行内容互异" (`len({(sig, value)}) > 行数/2`), 只断言行数/非空完全抓不到这类塌陷。
- **判据要走用户真正走的那条分支**。窗口内部常有 "增量刷新" 与 "强制重建/刷新按钮" 两条: 用 force 分支测
  "行序稳不稳"测不到增量路径的保行逻辑 (实测 force 每拍重排 ⇒ 永远报跳位), 反之只测增量又会放过"点刷新就乱"。
  一条判据 = 一条真实路径, 并在注释里写明它测的是哪条。
- **判据注入错误输入才算验过**。只断言"函数返回了列表/字段存在"等于没验: 对报警/一致性类判据, deepcopy 一份真数据、
  把某个值改到越界, 断言拿到预期级别的报警, 再去控件里读回那几行证明真的上屏。
- **判据的期望值必须来自真源, 不许抄当前实现**。曾有一条判据写死"某列的取值是进程名(非节点)", 把假数据固化成契约,
  代码改对后反而判红, 下一个人会照着它把 bug 改回去。同理别硬编码行数/条目数 (89 个 → 加到 90 就假红):
  断言"不少于基线"或直接从真源取期望。词表/口径变了就同步改判据, 并在注释里写明口径出处。
- **按"原始身份"定位, 不按显示文本**。表格显示的是友好名 + 4 位有效数字 (`0.424242` 显示成 `0.4242`), 原始字段名常在
  单元格 tooltip 第一行; 树的 key 常放在 `data(0, Qt.UserRole)`。匹配显示文本会在格式化后失配; 数值比对要留容差
  (`abs(a-b) < 5e-5` 而非 `==`)。
- **懒填控件必须先 `show()` 再读**。树/表常"可见才填充": offscreen 不 show 时 `topLevelItemCount()==0`、表格 0 行,
  很容易被误读成"数据源坏了"。读前: `w.show()` → pump 3s `processEvents()` → 调一次刷新入口
  (`_fill_trace_fixed(force=True)` / `_update_tree_values()`)。
- **递归遍历树要分 QTreeWidget 与 QTreeWidgetItem**: `topLevelItemCount()` 只存在于 widget, 对 item 调直接
  `AttributeError`。递归函数先 `hasattr(node, "topLevelItemCount")` 分支, item 侧用 `childCount()/child(j)`。

- **判据的前提跟着「数据语义」变, 不是把阈值放松**。换了某层/某块的数据来源后, 旧判据里"四层都有值"
  "某个对象这拍不该动"这类前提本身就失效了(那层真源可能现在根本不存在, 或反过来变得每拍都新鲜)。
  处理: 把断言改写成**诚实的析取**——“该层有值 **或** 明确标缺/未调用”, 对照组**从真源里挑**
  (选一个此刻真的没数据的对象), 不要写死名字。只把数字阈值放小 ≠ 修口径: 前者会把真 bug 一起放过,
  后者才能既保持红线的力度又不假红。改完把旧判据的**注释也改成新口径**, 否则下一个人会照旧断言改回去。
- **同一物理量在两个视图上显示 ⇒ 判据要证"同源", 光相等不算**。两处角度/数值一致只说明这一拍;
  两边都写死同一个常数、或各算一套公式碰巧相等, 也会"通过"。加一箭**扰动**: 改视角/偏航/输入参数后重画,
  断言两边**同步**变化且仍相等(实测转 25° 两边各动 8.1°, 差 0.00°)。前提是渲染与判据共用同一个投影/
  取数函数(见上"渲染与判据必须同源") —— 两个面板各自复制一份投影代码, 迟早分叉且很难看出来。
- **两个消费者各读一次同一份实时文件 ⇒ 逐位比较必假红**。10Hz 真源 + 500ms 重载, 两次采样天然差一拍。
  要么让两边读同一份缓存快照, 要么给与采样周期相称的容差(方向余弦 0.06 ≈ 7°)并在注释里写明理由;
  别为了变绿把容差一路放大。

## 截图读屏复核 → 当场固化成判据
自己看不到像素时, 把 PNG 交给**一个专门的读屏子代理**, 并给它逐字清单 (别问“这图有问题吗”):
标题/页顶行 · 表头 · 每行每列文字 · 按钮文字 · **每一处省略号的位置与被截文字** · 裁边/重叠/空白块。要求它
"只说你真看到的, 看不清就说看不清", 并做一次 OCR 交叉校验。实测它报出了目检看不出的东西: 1360 宽的窗口里
**四行长路径全被省略号截断**、"版本"列只剩 1~3px 余量 (再长一点就硬切)。
* 读屏结论**不许只留在报告里**: 每条缺陷当场写成自检断言 (字宽 `fontMetrics().horizontalAdvance(t)+20 ≤ 列宽`;
  同一界面两处实例互比列名/按钮 list 相等), 然后重跑判据确认修好 —— 下次靠机检, 不靠再请一次读屏。
* 多轮迭代时这条就是主回路: 出图(含在役实拍) → 读屏逐条报事实 → **每条要么修、要么写成一条卡住它的判据** → 重跑 → 下一轮。每轮判据条数只增不减，上一轮修好的不会回退。
* 读屏报告一律当**待办清单**逐条落；但**结论要按它的量测数字自己复核**——它对成因的归因会反（本色≈线色、两个候选都合法、两条共线看成一条），拿数不对时先查几何再做结论。
* 断言要卡**余量**不能只卡"没超出": `ElideNone` 下贴边不报错、下一版文字一变就硬切。

## 证据必须绑定"产出它的那个进程/构建"（否则会追幻影 bug）
改了 GUI 代码后拍的截图，如果跑的还是**旧进程**，读屏会报出**已经修好**的问题（本类任务里连着三份读屏报告都在描述改动前的界面，白改一轮）。
- 重启包装脚本会**拒绝重启但返回 exit 0**（本项目 `studio_ctl.sh` 有 300s 冷却，打"⛔ 拒绝"后 status 仍是旧 pid）⇒ 判据：`pgrep -f '<pattern>'` 的 pid **变了且存活**（或比 `ps -o lstart` 与源码 mtime）。
- 必须加载新代码时用**一次** `--force`，别反复刷（窗口闪来闪去会被用户投诉）。
- 证据里同时记下 build 时间/pid；读屏结论与你的最新改动冲突时**先核构建，再核控件**。
- 交给读屏子代理的问题要带**预期清单**并声明"这是改动后的构建"；它说某块不存在时，先用离屏探针确认控件/行是否真在（探针说有、图里没有 ⇒ 是图的构建旧了）。

## 判断"被裁"先量几何，别靠目检（可重用探针 `scripts/qt_fit_probe.py`）
离屏建窗口 → `findChild(QWidget, "<objectName>")` → 量四个数：`tbl.rowAt(0)`（首可见行 >0 ⇒ 顶部被裁）· `verticalScrollBar().maximum()`（>0 ⇒ 内容超高）· `Σ行高+表头` vs **控件高**（内容总高 > 控件高 ⇒ 底部行看不见）· `mapTo(窗口)`（控件是否被外层推离可视区）。
- **隐藏滚动条 + 内容超高 = 最坑的形态**：行被裁却没有任何"还能滚"的提示。修法 = 控件高按内容定死 `setFixedHeight(表头+Σ行高+边框)`，整页滚动交给外层 QScrollArea。
- **自绘画布挂在侧栏页里**同样吃这条，而且更隐蔽：画布控件给 `setMinimumHeight`，整页套 `QScrollArea(widgetResizable=True)`；否则窗口一小，父布局把画布压成一条——现象是“文字块都在、图形一个都看不见”（用户第一眼就看到）。
- **离屏大尺寸渲染全绿 ≠ 在役可用**：判据里按 682×1391 离屏渲染全过，真窗口小的时候画布依旧被裁。判据/取证必须包含**在役窗口那一张实拍**（真进程内 `grab()`），并专门核“小窗口下能不能看全”。
- **跨屏几何判据不能用离屏数字**: `QT_QPA_PLATFORM=offscreen` 的 `fontMetrics()` 跑在默认 DPI 上, 真屏 192DPI 下同一串字宽可能**翻倍** (实测同一条目 128px → 246px, 所需宽度 184 → 302)。凡按字宽/"内容需求宽度"设阈值的判据, 要么整体在真屏 (`DISPLAY=:0`, 构造即可量, 要量落定后的实际宽度则 `show()` + `processEvents()`) 跑, 要么两边各一套阈值并标明口径 —— 拿离屏数字当真屏结论会全盘偏小。
- **字是否被硬切**用字宽判定，且要把跨列/换行算对：跨列行按**跨列总宽**（`columnSpan`）；开了 wordWrap 时按 `ceil(需要宽度/列宽) * 行高 <= 实际行高` 判"没丢字"。不算 span 会得到假阳性（实测 6 处报警里 1 处是假的）。
- 列头/短标签别用 `name[:N]` 硬切（切在词中间且无省略号）⇒ 按**词边界**取短名，超长才加 `…`；尾部才是身份信息的值（路径）显示 `…`+尾部 N 字并把完整值放 tooltip（明示省略，不静默截断）。

## 像素级判据自己会错（量之前先核这几条）
- **渲染与判据必须同源**: 渲染里只要做了共线错开 / 避让挪位 / 边界夹紧，判据拿原始坐标重算就会量到**改前**的几何 ⇒ 假红。把“实际画出来的几何”抽成视图方法（`drawn_segments()` / `label_texts()`），渲染与判据调**同一个**，判据只读它的输出。
- **先触发再读账**: 布局过程中累加的清单（哪些块要拉引线 / 哪些被打回空槽）在调布局方法前是空的 ⇒ 判据先调 `label_texts()`/`grab()` 再读。
- **采样尺度别用错**: 形状半径 = `S·RAD`（形状尺度），不是 `R·RAD`（轨道尺度）—— 差一倍 ⇒ 采样点落进形状内部，结论全错。
- **本色≈线色 = 假阳性**: 用“形状内部有多少线色像素”验“线不穿形状”时，金球 vs 金线会双计 ⇒ 选与该形状色距**最大**的线色，容差收到 ≤45。
- **背景辅助几何（井/环/网格）要与线色拉开色距（≥60）**: 同色时 1× 下根本数不出圈数，也会被当成线。
- **占空类阈值按实测给**: 虚线占空 ≈55% ⇒ 逐线阈值取 45%，不要写 80%。
- **像素判据连跑两次才算稳**；阈值要留余量（避让/间距类至少留 2px），否则元素一动就时红时绿。
- **判据“时红时绿”多半是布局兜底分支漏约束**: 布局里只要存在“没找到干净候选就退回最后一个候选 / 改放页边栏空槽”的分支，那一支就会漏掉某类约束（块↔块 · 块↔球 · 距画布边距），判据在**换一帧真源数据**时就红、下一帧又绿。收尾那一遍要同时对三类约束全查，命中就改放空槽——别把它当成“判据太敏感”。
- **候选可用性用矩形膨胀判，不要只判 `intersected().isEmpty()`**: 只判真重叠时两块隔 1px 也算合法。空槽的 y 步进必须 ≥ 块高+间隙（8px 步进而块高 15px ⇒ 相邻槽位自身重叠，第二块放进去就只隔 1px）。
- 源码里的 `p.save()`（QPainter）会被“无反写文件口”的 `.save(` 静态检查误判 ⇒ 检查前先剔除。
- **判"有没有上色/上底色"要用 brush 的 style，不要读 `color().alpha()`**: 默认 `QTableWidgetItem` 的 background 是 `NoBrush`，但 `color()` 照样返回不透明的黑 (alpha=255) ⇒ 每一格都被判成"上色了"，"全表只有一格高亮"这类判据忽假忽真。改成 `it.background().style() == Qt.SolidPattern`（或比 foreground 的具名色）才只数真实心刷。
- **验"刷新/联动"要挑必然随源变的观测点**: 表里各行的取值来源不同（非当前行常取自"各阶段末帧"，天然不动），拿它当"变没变"的证据会假阴性。选汇总格或当前在跑那一行；同理，只验"冻结"或只验"实时"都会放过反面的 bug（冻死的界面/跟着回放跑的假实时），两分支都要写一条。
- **控件级检查块必须落在 `QApplication` 建好之后**: 往判据脚本插新检查时锤点若落在建 app 之前 ⇒ `QWidget: Must construct a QApplication before a QWidget`，**整套判据一条不跑**（只看到异常栈）。插完**整脚本跑一遍数条数**（本轮应 36 条），别只单独跑新增那一条。

## 现场要「把某窗口的截图发我」时的定式 (按需单张, 不是跑整套取证)
1. **先按标题找窗口, 不要猜**: `DISPLAY=:0 wmctrl -l`（给窗口 id + 所在桌面, `-1` = 不在当前桌面）
   → 用标题关键词定位。窗口没开就别硬截：走 UI 自己的打开入口调一次（见工作流 5），别反复重启 GUI。
2. **截指定窗口**: `wmctrl -i -a <winid>` 聚焦 → `DISPLAY=:0 scrot -u -o <png>`（当前聚焦窗口）。
   `$DISPLAY` 常为空 ⇒ **每条命令都显式带 `DISPLAY=:0`**；机器上没 `import`(ImageMagick) 时 `scrot` 是首选。
   **被遮挡的窗口先 `wmctrl -i -a <winid>` 抬到最前再 `scrot -u`**；别用 `xwd -id` 截图、也别拿 `xwininfo` 的几何去裁全屏图 ——
   遮挡时拿到的是压在上面的那个窗口（实测截到自己的终端，OCR 出来全是终端文字），而且 PIL 打不开 `.xwd`。
   用户问「你能看到我这里保留的两个信号么 / 界面现在显示什么」时走这条：抬窗 → 截 → OCR → 按**真读到的**表头、逐行内容、
   状态条回答；顺便把 OCR 里看到的异常（别的层还在、告警是 fail 级）如实报出来，别只回答他问的那一句。
3. **截完先自证不是空白/不是旧构建再发**: 用 cv2/PIL 量三个数（尺寸 · 均值 · 非黑像素占比）+
   `xdotool getwindowgeometry <winid>` 核窗口几何；均值个位数且非黑占比≈0 = 黑/空图。
4. **写文字说明前先 OCR 一遍**（`tesseract <png> out -l chi_sim+eng --psm 6`），按**真读到的内容**写 caption，
   不要按界面代码猜它显示什么 —— 截图里的实时读数(利用率/温度/进度/当前任务)恰恰是用户会核的地方。
5. 图里有**实时数据**时，说明里给数值 + 时间口径（帧龄/生成时刻、当前任务/层名）；哪怕发现图内存在不理想状态（某层空闲/报错横幅），
   照原样发并 **如实点出**，不要换一张好看的（用户会把画面当结果读）。

## 报告集成
- 纯 CLI 测试报告生成器 (无 Qt) 集成 GUI 取证: import 取证模块前先设插件 env (见上), 调其 `run_viz()` 返回 results list
- PDF 结构: 摘要/环境/用例汇总/…/可视化证据章 (每图带 case+desc+PASS/FAIL)
- Excel: 原 sheet 外追加"可视化验证" sheet (用例ID/验证内容/结果/实测证据/证据文件)
- 一键重跑保持单一入口脚本 (CLI 用例 + GUI 取证 + PDF + Excel 一条命令)

## 相关文件 (Z-MAX 仓库实例)
- `tools/gen_viz_evidence.py` — GUI 取证参考实现 (构造 SimulinkModule → 画布 → 引擎 → 5 类窗口截图断言 → JSON)
- `tools/gen_verif_auto_report.py` — 报告集成参考 (PDF 8 章含可视化证据 + Excel sheet)
- `tools/gui/ff_hist_view.py` / `ff_attrib_view.py` — QPainter 自绘数据窗口带公开 push() API 的可测模式
