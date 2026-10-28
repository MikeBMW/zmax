# 配置中心 UI 改动定式 (tools/gui/veh6_config_page.py)

## 0. 改前定位
- 页面类 = `ConfigCenterPage`。主控制台侧栏页与 simulink 的「🗂 配置中心」独立窗口**复用同一个类** ⇒
  改一处两边同时生效，别只改一边。
- 运行中的控制台实例 cwd 就是 `tools/gui`（`readlink -f /proc/<pid>/cwd`），改这个文件 = 改用户正在看的那份；
  改完**重启一次**才生效。
- 平台/产品描述与计数走单一唯一依据口 `tools/gui/zmax_platform_info.py`（数据来自 `config/platform/*.json` +
  `zmax_engineering.db`），页面不许自己硬写数字。

## 1. 删"与主控制台重复"的块
- 用户指着某块说"与主控制台左侧同源…删掉" = 删**配置中心这一份**，主控制台那份保留。整块删（连同它的
  构造/刷新方法），不留死代码；同页其它块（平台描述 + 产品特性清单）不动。
- 判据必须同改：`tools/verify_config_center_seven_stars.py` 里原先那条是"页上文字 == 唯一依据模块文字"，
  删块后翻成"页面不再有这个块 + 主控制台仍接线 + 保留块还在"；判据**条数不变**，别顺手删条目。

## 1b. 删「配置项整行 / 整字段」
- 行通常由类级元组驱动（`_PROD_ROWS = ("产品", "版本段", …)`）。删一个键要同时清三处，否则 `KeyError` 或界面残留：
  ① 元组项；② 刷新函数里 `vals["键"].set_value(...)` 的取数与格式化（含日志行里拼的该值）；
  ③ 只服务这一行的模块级 helper（如 `_cut_big` / `_vmark`）与「唯一依据: … sha …」状态行 `setText`。
- 判据会被删键卡死：`verify_product_ui.py` 这类按元组逐键取值、且把「📋/双击/右键复制」用例挂在某个被删字段上
  ⇒ 字段数改 `len(fields)`、复制用例换到一个**还在**的字段（没有截断字段时，判据从"显示是截断形式"改成"复制的 == full_value"），
  并新增一条正面判据「已删的 N 个键真不在界面 + 说明行/唯一依据行也不在」。
- 不为"以后可能还要"留空控件或复活分支：用户要界面极简，死代码下次会被当活功能误读。
- 交付时逐项对账「删了哪几处（行 / 说明行 / 唯一依据行 / helper）」，比一句"删完了"有用。

## 1c. 只改某条指标文案 = 改唯一依据，不是改界面
- 界面上的指标串（如「插入成功率 ≥99% · 头到孔底 <4mm」）不许在 GUI 硬写：唯一依据是
  `config/platform/*.json` → 工程库 → 页面。改完必须 `engineering_db.py build` 并核 `product_features` 与 `params`
  两处（链路口径与验法见 `references/truth-to-db-sync.md`）。

## 2. 全页文字可选中 / 可复制
- 根因: QLabel 默认 `NoTextInteraction`，说明性文字只能看不能框选。
- 建页末尾全量扫一遍:
  ```python
  for lb in root.findChildren(QLabel):
      f = lb.textInteractionFlags()
      want = f | Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
      if want == f:            # 🔴 必须比 want，不能写 if f & (A|B)
          continue
      lb.setTextInteractionFlags(want)
      lb.setCursor(Qt.IBeamCursor)
  ```
- 再装 **app 级 eventFilter**（`QApplication.installEventFilter(self)`，幂等）:
  `ev.type() == QEvent.Polish and isinstance(obj, QLabel) and self.isAncestorOf(obj)` → 同样 OR。
  刷新/重读唯一依据/换页时新建的标签自动带上，不靠逐个改。
- 🔴 跳过条件写错 (`if f & (A|B): continue`) 会让"只开鼠标选中"的标签（本文件的 `_CopyLabel` 就只设
  `TextSelectableByMouse`）把键盘标志永远挡住 —— 鼠标能用，但要求 A+B 的判据全红。
- 树/表格不是 QLabel：page 级 `QShortcut(QKeySequence.Copy, self)` + `Qt.WidgetWithChildrenShortcut`；
  树 → 当前条目全文（去掉 ⛔/✅ 判态标记），表 → 选中单元格 TSV（Excel 直接粘）；焦点在 QTextEdit/QLineEdit
  时转调它自己的 `copy()`，别抢。左树再挂右键「复制条目文字 / 复制全部条目」，条目被省略号截断也能拷全文。
- 按钮 / 单选钮 / 页签标题 Qt 原生不支持框选 —— 交付时如实说明，别承诺"所有控件文字都能选"。

## 3. 判据与验证
- 专用判据: `tools/verify_config_center_text_copy.py`（离屏真渲染，写法同 `verify_config_center_seven_stars.py`）。
  覆盖: 每页 QLabel 不可选中数=0 · 真发拖选事件取 `selectedText()` · 左树/表格 Ctrl+C 取剪贴板 · 后建 QLabel
  自动可选中 · 信息窗 QTextEdit 的 Ctrl+C 没被抢走。
- 跑法: `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_center_text_copy.py`
- 判据变红先取基线: `git stash push -q -- <改动文件> <判据文件>` → 跑同一脚本 → `git stash pop`。
  改前改后同条数 = 零回退；只有差异才是本次引入，旧红要如实说"改动前就红"。
- LSP/Pyright 报 PyQt5 无法解析是环境噪声（它不用 `gui-venv311`），别当错误去修。

## 4. 上线
- 一次重启: `cd tools/gui && bash restart_studio.sh`，判据 = 输出里有**新 pid** 且 `'XSpace ZMAX'` 窗口数 >0。
  反复重启会让用户窗口闪，禁。
- 重启后窗口可能开得比屏大（重启脚本只告警、不夹窗口）⇒ 用 `wmctrl -b remove,maximized_*` + `wmctrl -e 0,x,y,w,h`
  收到屏内，再 `xdotool getwindowgeometry` 核 `x+w` / `y+h`；WM 只认 w/h，要迭代一次并实测尺寸（本次最终 3020×1740）。
  完整口径见 `pyqt5-gui-development` §17。
