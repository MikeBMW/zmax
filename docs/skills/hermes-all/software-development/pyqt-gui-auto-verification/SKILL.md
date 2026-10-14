---
name: pyqt-gui-auto-verification
description: Use when PyQt5 GUI 自动取证测试 — 驱动真实窗口截图作证据入报告。
---

# PyQt5 GUI 自动取证测试 (真人测试工程师自动化)

触发: 让 GUI 自动化"操作所有图表/窗口"做验证、每个用例要截图证据、报告要嵌图。
Z-MAX 仓库具体入口/机制见 `references/zmax-studio-automation.md`。

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

## 坑 (已踩)
- **cv2 自带 Qt 平台插件污染**: 先 import cv2 (ultralytics 等) 后建 QApplication → Qt 从 `cv2/qt/plugins` 找 xcb → "Could not load the Qt platform plugin xcb" (缺系统依赖)。修复: 建 QApplication **之前**设 `QT_QPA_PLATFORM_PLUGIN_PATH=<site-packages>/PyQt5/Qt5/plugins` (遍历 sys.path 找含 platforms/ 的目录)。别只删 cv2 路径 — 显式指定 PyQt5 真实目录即可
- QApplication 只能在 import 任何 Qt widget 前创建一次; 被报告侧 import 时 (cv2 已加载) 也要先设插件 env 再建 app
- offscreen 平台弹窗 API (raise_/activateWindow) 报 "does not support raise()" — 无害, 忽略
- 窗口单例: 挂被测模块实例属性 (`module._xxx_win`), 让"双击打开"与"脚本驱动"共用同一窗口, 避免双窗口
- 引擎跑完只有末帧 probe: 若可视化要过程帧, 从数据文件回放真实帧 (诚实: 模型在真实历史 obs 上真实 forward), 别伪造中间帧
- 有 X 时后台跑脚本会短暂弹窗到桌面 — 可接受; 别用 nohup/后台静默跑 Qt 脚本 (信号/退出问题), 前台超时或 background+notify
- **建页时抛异常 ⇒ 遗留线程 ⇒ `Fatal Python error: Aborted` (core dumped)**: 用了布局没有的 API（`QFormLayout` 只有 `addRow`，没有 `addLayout`/`addWidget`）会 AttributeError，崩栈里赫然是 DDS/mujoco/PyQt 线程在陪葬 —— **先读 `Aborted` 上面那段 Python 异常**，别去怀疑那些线程。挂控件按布局类型自适应: `if hasattr(layout, "addRow"): layout.addRow(w) else: layout.addWidget(w)`。
- 离屏探针退出时可能因残留后台线程 abort（与结论无关）⇒ 探针结尾用 `os._exit(0)`，别让 teardown 崩掉掩盖前面打印的结论。

## 截图读屏复核 → 当场固化成判据
自己看不到像素时, 把 PNG 交给**一个专门的读屏子代理**, 并给它逐字清单 (别问“这图有问题吗”):
标题/页顶行 · 表头 · 每行每列文字 · 按钮文字 · **每一处省略号的位置与被截文字** · 裁边/重叠/空白块。要求它
"只说你真看到的, 看不清就说看不清", 并做一次 OCR 交叉校验。实测它报出了目检看不出的东西: 1360 宽的窗口里
**四行长路径全被省略号截断**、"版本"列只剩 1~3px 余量 (再长一点就硬切)。
* 读屏结论**不许只留在报告里**: 每条缺陷当场写成自检断言 (字宽 `fontMetrics().horizontalAdvance(t)+20 ≤ 列宽`;
  同一界面两处实例互比列名/按钮 list 相等), 然后重跑判据确认修好 —— 下次靠机检, 不靠再请一次读屏。
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
- **字是否被硬切**用字宽判定，且要把跨列/换行算对：跨列行按**跨列总宽**（`columnSpan`）；开了 wordWrap 时按 `ceil(需要宽度/列宽) * 行高 <= 实际行高` 判"没丢字"。不算 span 会得到假阳性（实测 6 处报警里 1 处是假的）。
- 列头/短标签别用 `name[:N]` 硬切（切在词中间且无省略号）⇒ 按**词边界**取短名，超长才加 `…`；尾部才是身份信息的值（路径）显示 `…`+尾部 N 字并把完整值放 tooltip（明示省略，不静默截断）。

## 现场要「把某窗口的截图发我」时的定式 (按需单张, 不是跑整套取证)
1. **先按标题找窗口, 不要猜**: `DISPLAY=:0 wmctrl -l`（给窗口 id + 所在桌面, `-1` = 不在当前桌面）
   → 用标题关键词定位。窗口没开就别硬截：走 UI 自己的打开入口调一次（见工作流 5），别反复重启 GUI。
2. **截指定窗口**: `wmctrl -i -a <winid>` 聚焦 → `DISPLAY=:0 scrot -u -o <png>`（当前聚焦窗口）。
   `$DISPLAY` 常为空 ⇒ **每条命令都显式带 `DISPLAY=:0`**；机器上没 `import`(ImageMagick) 时 `scrot` 是首选。
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
