---
name: pyqt5-gui-development
description: Use when developing/debugging PyQt5 GUIs on WSL/WSLg.
---

# PyQt5 GUI 开发 (WSL/WSLg 环境)

PyQt5 桌面控制台/画布类 GUI 的开发和调试通用指南。覆盖 WSLg 下的窗口行为、QSS 陷阱、验证模式与安全改代码方法。

## 触发条件
- 修改/调试 PyQt5 应用（QMainWindow/QDialog/QWidget 类、QSS 样式、QGraphicsScene 画布）
- WSL (WSLg) 下运行 GUI、offscreen 验证、打开外部链接
- 对大型 GUI 单文件做批量改动（studio.py 类 8k 行单文件）

## 核心陷阱 (都是实测踩过的)

### 1. Qt QSS 8 位 hex 颜色 = #AARRGGBB (alpha 在前!)
- `#00d4aa88` 会被 Qt 解析为 **alpha=0x00（全透明）** → 边框/背景完全不可见
- 症状: 某层边框"默认看不到、hover 才出现"；其他层"有边框但颜色错乱"（实际是 alpha 高字节当颜色用了）
- 修复: 用 `rgba(r,g,b,0.40)` 或 6 位全色 hex；**绝不用 8 位 hex 做半透明**
- 排查: 检查 styleSheet 里的 `#RRGGBBAA` 写法（Qt 只认 `#AARRGGBB`）

### 1b. QSS 报错刷屏两种典型写法 (2026-10-17 实测, 控制台启动刷 14~18 条)
- **`Could not parse stylesheet of object QPushButton(0x…)`**: 样式表里**裸声明后面直接跟选择器** ——
  `f"background:{c};padding:4px 12px;" + "QPushButton:checked{…}"`。裸声明（无 `QPushButton{}` 包裹）本身合法,
  但拼上规则块后整串解析失败; 每次 repolish 打一条。修法: 基础样式一律包成 `QPushButton{…}`, 再拼 `:checked{…}`。
- **`Unknown property cursor`**: Qt QSS **不支持 `cursor:`**（那是网页 CSS）。指针形状用控件方法
  `btn.setCursor(Qt.PointingHandCursor)`, 不写进样式表。
- **定位手法（比读代码快）**: `qInstallMessageHandler` 抓消息里的 `(0x…)` 地址 → 遍历 `findChildren(QPushButton)`
  用 `int(sip.unwrapinstance(b))` 比对 → 直接打 `b.text()` + `b.styleSheet()` 就是罪魁; 再用
  monkeypatch 包 `QWidget.setStyleSheet` 记录“调用期间是否出告警”可定位到行。
- **兜底**: 主程序 `main()` 里装消息过滤器只吞这两类（`Could not parse stylesheet` / `Unknown property *` /
  `propagateSizeHints`）, 其他 Qt 消息照常打印; 中文消息写 `sys.stderr.buffer.write(msg.encode("utf-8","replace"))`,
  否则 GUI 的 ascii stderr 会抛 UnicodeEncodeError。

### 2. WSLg 弹窗: exec_() 模态假死
- WSLg 下 `QDialog.exec_()` 模态窗口不显示/假死 → 一律非模态 (`show()`)
- 小窗口/气泡也禁用；反馈用 按钮+日志框+气泡，不用弹窗

### 3. WSL 打开外部链接/文件: QDesktopServices 失效 + cmd.exe UNC 坑
- WSL 通常无 xdg-open → `QDesktopServices.openUrl()` 返回 False 静默失败
- **cmd.exe start 必须带 `cwd="/mnt/c/Windows"`** (2026-08-12 实测: WSL 里 Popen cmd.exe 的当前目录是 UNC `\\wsl.localhost\...`, cmd 报"UNC 路径不受支持" → start 静默不执行, 用户反馈"链接没打开"; 诊断/复现也要从 /mnt/c/Windows 目录跑 cmd.exe)
- 打开 URL: `subprocess.Popen(["cmd.exe", "/c", "start", "", url], cwd="/mnt/c/Windows")`（Windows 默认浏览器，可靠）
- **打开有默认关联程序的文件（视频 mp4/图片/PDF）用 cmd start + cwd 修正**（2026-08-12 实测: explorer.exe 从 WSL 启动受 UNC cwd 影响**静默失败**——用户反馈"点视频节点播放器没弹出"; 改 `cmd.exe /c start "" "C:\...mp4"` + `cwd="/mnt/c/Windows"` 后正常弹 Windows 默认播放器; 测试也要 cd /mnt/c/Windows 再跑 cmd）
- **打开目录/无关联文件（.py/.md/文件夹）用 explorer.exe + Windows 反斜杠路径** (cmd start 打开无关联程序的 .py/.md/目录 会静默失败 → explorer.exe 目录型弹资源管理器; 无需 cwd hack)
- **反复弹出型动作（弹播放器/打开窗口）必须防抖**（2026-08-12 老倪"怎么弹出好几次视频" — 双击重复触发/多次点击会弹多个播放器）: 记 `self._last_xxx_pop` 时间戳, 15s 内重复调用直接 return + 日志提示; 用户多次点击只弹一次
- **Windows 路径 `C:\...` 在 Linux 是相对路径**: shutil 复制/读写目标一律用 `/mnt/c/...`(WSL 路径), 只有 explorer/cmd 展示参数才用 `C:\...`(os.path.join 后 `.replace("/", "\\")` 统一反斜杠); 混用会在仓库 cwd 留下 `C:\zmax_src_view` 之类残留目录(需 find+rm 清理)

### 8. VcXsrv 下 QMenu 深色 QSS = 黑屏无字 (2026-08-12 实测)
- 症状: 右键菜单弹出来只有小黑块, 没有菜单文字
- 排查: ①去掉 `border-radius`(圆角触发半透明合成失败)仍黑 → ②**完全去掉 `menu.setStyleSheet`, 用系统默认菜单最稳**
- 规律: VcXsrv 对 QMenu 自定义深色样式整体渲染失败 — 主窗口/弹窗的深色 QSS 正常, 但菜单是独立 popup X window 容易黑; 别再给 QMenu 上深色 QSS; 验证用 regex 提取 setStyleSheet 实际内容断言(注释里提到 border-radius 会让 naive grep 误报)
- **★ 全局 QSS 也会黑**: studio.py 的 `app.setStyleSheet` 里若有 `QMenu { background:... }` 规则, 同样作用所有 QMenu(删了局部 QSS 仍黑) — 搜全部文件里 `QMenu {{`/`QMenu::item`, 两处都删干净(保留 QMenuBar); 删 QSS 块时注意三引号字符串边界别截断(闭合 `"""` 放错位置 = SyntaxError)
- **★ 系统默认菜单下 emoji 渲染成黑块** (2026-08-12 老倪"有的是白色背景,有的有个黑条"): 菜单项文本带 emoji(📖⚙️📂▶)在系统默认字体缺字形 → 黑色方块条; 菜单项一律纯文本(去 emoji), 画布/按钮上的 emoji 不受影响

### 9. QGraphicsView/QGraphicsItem 悬停事件 (2026-08-12 实测)
- QGraphicsItem 的 hoverEnterEvent 触发需两个前提, 缺一不触发: ①view 要 `setMouseTracking(True)`(QGraphicsView 默认无按键时不分发 hover 给 items) ②item 要 `setAcceptHoverEvents(True)` + 实现 hoverEnterEvent/hoverLeaveEvent(内部 `self._hover=True/False; self.update()`)
- 排查"悬停不生效": 先 grep item 类是否有 setAcceptHoverEvents + hover 事件(本会话 SimNodeItem 完全没有 hover 事件, 只有连线类 SimLinkItem 有 — _hover 恒 False), 再查 view 是否 setMouseTracking; 两处都补才生效
- **VcXsrv 下 hover 事件流仍迟钝 → 终版: view 的 mouseMoveEvent 里 `itemAt(e.pos())` 直接驱动** (2026-08-12 用户报"ID就第一次显示,感觉反应很迟钝"): 每次鼠标移动算 itemAt, 目标 item 设 `_hover=True+update()`, 移出(或移到其他 item/空白)对旧 hover item 设 `_hover=False+update()`; 用 `self._hover_items` 集合跟踪当前 hover 项 — 鼠标位置即状态, 移出即消失, 完全绕开 hover 事件分发; 适合悬停提示(显示 ID/tooltip)类需求
- offscreen 验证 hover 渲染用**像素 diff**(_hover False vs True 两图差异像素>15), 别用绝对颜色计数(节点固有元素会误命中); 模拟 mouseMove 驱动: 构造 QMouseEvent(MouseMove, viewport 坐标) 调 view.mouseMoveEvent, viewport 坐标用 `view.mapFromScene(item.scenePos()+offset)`
- **VcXsrv 下无按键 mouseMove 事件根本不达画布** (2026-08-12 终版, 老倪"你怎么非得用鼠标点击一下呢,改成悬停显示" — 点击按下才有 mouseMove): mouseMove 驱动仍会"头两次显示然后不显示" → **终版 = QCursor 轮询兜底**: `_hover_timer = QTimer(self)` 150ms + `_poll_hover()`: `QCursor.pos()` 与 `_last_hover_pos` 相同则直接 return(**鼠标不动不重绘, 防狂闪** — 初版 80ms 轮询无守卫导致"屏幕狂闪"被否), `isVisible()/underMouse()` 检查 + `mapFromGlobal` → `_update_hover_at`; `_clear_hover()/_update_hover_at` 遍历 `_hover_items` 必须 `it.scene() is not None` 才 update(**删节点后旧 item 引用 update() 会崩溃闪退**), 全部 try/except 兜底; mouseMove 即时 + 轮询兜底共用 `_update_hover_at(vp_pos)`
- **悬停提示类 UI 的用户偏好 (2026-08-12 老倪多轮纠正, 最终形态)**: 仅悬停显示(常显被否)、白色粗体 9px(`#e6edf3`, 蓝色被否)、放节点**右下角**(右上角与标题重叠被否、上方浮动被否)、不遮挡节点内容、背景行(row_bg)不显示 ID; 改 UI 视觉前先确认最终形态, 别按中间猜测迭代 6 轮

### 10. VcXsrv 崩溃/守护 + 窗口验证 (2026-08-12 实测)
- **"屏幕狂闪 + 闪退" = VcXsrv(X 服务器)挂了, 不是代码 bug**: Qt 崩溃日志特征 `qt.qpa.xcb: could not connect to display <ip>:0` + exit 134 — 连接断开 Qt 起不来/崩; **狂闪是 VcXsrv 假死的前兆**; 诊断三连: ①`ps aux | grep "python3 studio.py" | grep -v grep | grep -v bash`(pgrep -f 会连 hermes bash 包装一起数, 误导) ②`tasklist.exe | grep -i vcxsrv`(进程没了 = 挂了) ③`timeout 3 bash -c 'echo > /dev/tcp/<GW>/6000'`(端口不通 = X 挂了); 修复 = PowerShell 重启 VcXsrv, 端口通后重起 GUI; 别在代码上反复排查(轮询/timer 都背过锅, 实为 X 服务器死)
- **VcXsrv 启动参数只有原配方有效**: `-ArgumentList ':0','-ac','-multiwindow','-clipboard','-wgl'`; **`-softgl`/`-nowgl` 不被支持**(进程起来但内存 ~13MB = 初始化失败, 6000 端口不通) → 保持 -wgl
- **守护脚本**: `/home/xspace/scripts/vcxsrv_watch.sh`(检测 6000 端口, 挂自动 taskkill + PowerShell 重启) + cron `*/2 * * * *` — 挂了自己拉起, 不用手动救
- **WSLg 可能未启动**: 查 `ps aux | grep -iE "weston|Xwayland"` 无进程 + `/mnt/wslg/runtime-dir` 有 socket 但图形栈没跑 → 启用需 `wsl --shutdown`(会中断当前会话, 别在会话中做); 选显示方案前先确认 WSLg 进程在不在
- **xdotool 在 VcXsrv 重启后查询失效**(search 返回 0 但窗口实际显示) → 验证窗口用 **Windows 侧**: `powershell.exe -NoProfile -Command "Get-Process | Where-Object { \$_.MainWindowTitle -match 'XSpace' }"`(vcxsrv 持有窗口标题)

### 11. 启动卡顿/闪烁: 延迟创建重量级组件 (2026-08-12 实测)
- 症状: "打开前屏幕使劲闪 + 卡死好几秒" — 主线程构造里同步建重量级组件(200+ 按钮的模块库面板/画布) → VcXsrv 每次窗口映射全屏合成一次 → 闪 + 卡
- `win.hide() + QTimer.singleShot(80, win.show)` **无效且加重**(更闪+卡死, 已 revert) → **正解: 构造期不建重量级组件, `QTimer.singleShot(400, self._init_heavy)` 后置创建**(记录 `self._stack_index = stack.count()` + 完成后 `insertWidget(index, widget)` 插回原 tab 位, try/except 兜底 statusBar 提示); 实测启动 27s→8s
- 规律: VcXsrv 下启动慢 = 主线程同步构造重组件; **延迟创建(QTimer 后置)比 show 时机 hack 有效**; 延迟回调里访问延迟组件时它已就绪(400ms < 2.5s 等); Pyright 对 `self.attr = None` 后访问报 OptionalMemberAccess 是静态误报

### 12. QGraphicsScene 节点双击: canvas 拦截 press 是隐性杀手 (2026-08-12 实测)
- 症状: 用户反复报"双击节点没反应" — 双击 ▶生成视频/数据源切换全不生效, 只有右键菜单"运行节点"能用
- **坑①: item 类可能从未实现 mouseDoubleClickEvent** (SimNodeItem 只有连线类 SimLinkItem 有 — 加之前双击完全不处理)
- **坑② (更隐蔽): canvas 的 mousePressEvent 左键分支拦截了 press** — 节点主体分支(选择/手动拖动) `item.setSelected(...); return` **不调 `super().mousePressEvent(e)`** → QGraphicsScene 收不到 press → **Qt 双击事件(发给接受 press 的 item)也不发** → 就算给 item 加了 mouseDoubleClickEvent 也永不触发!
- 正解: **canvas 手动检测双击** — mousePressEvent 节点主体分支开头:
  ```python
  import time as _t
  _now = _t.time()
  if (getattr(self, "_last_dbl", None) and _now - self._last_dbl[0] < 0.4
          and self._last_dbl[1] is item):
      self._last_dbl = None
      self.module.on_node_activated(item.node)   # 双击语义
      return
  self._last_dbl = (_now, item)
  ```
  0.4s 内同节点二次 press → 触发; 单次 press 只记录; 超时自动失效
- 验证: offscreen 构造两次 QMouseEvent(MouseButtonPress, 同 viewport 坐标, 间隔 0.1s) 调 view.mousePressEvent → 断言 on_node_activated 收到节点名; 单次 press → 不触发; 间隔 0.5s → 不触发
- 排查顺序: ①item 类有 mouseDoubleClickEvent 吗 ②canvas press 对节点分支是否 return 拦截了 super() — **凡自定义 canvas 吞了 press 的, item 事件(含双击/hover 按压)都不可信, 一律在 canvas 层手动实现**


- 大段 patch（>8K tokens）或 execute_code 字符串切片 → 流超时/误截文件（曾把 8k 行文件截到 1.2k 行）
- 修复: 小 patch 多次提交；整段删除用 `sed -i '<a,b>d'`（先 cp 备份）；**绝不用 execute_code 大段字符串操作改大文件**
- **★ 含 shell 命令的 f-string 行绝不用 patch 工具改（2026-08-09 实测 6+ 轮浪费）**：patch 的反斜杠转义层层加倍
  （`"` → `\\"` → `\\\\\\"`），`awk '{print \$2, \$4}'` 一行修了 6 轮。**正解：execute_code 行级重建**——
  Python 读行→定位（先 `grep -n` 精确行号，条件匹配会误中多处）→ `chr(92)` 拼反斜杠构造新行→写回；
  改完三验：`ast.parse` + `eval` 该 f-string 看渲染 + **真实执行命令断言 exit 0**（repr 里 `\\`=1 个反斜杠，别被双重转义显示骗）。
  其他坑：f-string 里嵌 `{cfg.replace('.yaml','')}` 引号冲突 → 预计算变量或 `{cfg[:-5]}` 切片；
  行级重建循环**绝不 break**（截断文件后半）；拼接列表中间行必须以 `,` 结尾（丢逗号 = "forgot a comma" 语法错）；
  改坏直接 `git checkout -- <file>`。详见 zmax-console `references/fstring-patch-escaping.md`

### 5. 跨线程 GUI 操作 = 崩溃（后台线程碰控件/日志区）
- 症状（2026-08-08 容器管理实测）: 点上传/轮询按钮后 GUI 整体崩/窗口消失（守护拉起新进程）。根因: 后台线程里直接 `self.log_text.append()` 或 `btn.setEnabled()`——Qt 控件非线程安全
- 修复模式（两处都要）:
  - **日志方法线程安全化**: `_log()` 里检测 `threading.current_thread() is threading.main_thread()` → 主线程直接追加；非主线程入队，主线程 QTimer flush（见下）
  - **控件状态恢复回主线程**: 线程 finally 里 `QTimer.singleShot(0, lambda: self._btn.setEnabled(True))`，绝不跨线程 setEnabled/setText
- **★ 2026-08-09 实测: `QTimer.singleShot(0, fn)` 跨线程在 PyQt5 下丢消息**（症状: 按钮点击只出主线程第一条日志，线程里后续日志全丢 → 用户以为功能没反应；`QMetaObject.invokeMethod(字符串槽)` 也只认 C++ 原生槽，Python @pyqtSlot 不一定调到）
  - **正解: 线程安全队列 + 主线程 QTimer flush**:
    ```python
    # __init__:
    self._log_queue = []
    self._log_flush_timer = QTimer(self)
    self._log_flush_timer.timeout.connect(self._flush_log_queue)
    self._log_flush_timer.start(200)
    # _log():
    if _th.current_thread() is _th.main_thread():
        self._append_log(text)
    else:
        self._log_queue.append(text)   # 非主线程只入队, 不碰控件
    # _flush_log_queue(): 交换队列 + 遍历 self._append_log(t)
    ```
  - 验证: offscreen + monkeypatch `_append_log` 计数, 调线程函数, 断言全部子线程日志出现（修复前只有 1 条, 修复后全出）
- 排查: GUI 崩但无 Traceback（守护静默拉起）→ 先查后台线程里的所有 GUI 属性访问

### 6. 老倪 UI 极简偏好：复杂状态机 → 几个点选控件
- 2026-08-08 实测纠偏: 容器管理先做"状态机单选 UI"（QButtonGroup + 点击到达状态 + ▶ 执行当前模式按钮 + 状态标签），老倪直接否:"逻辑太复杂，简单点，就做成几个点选控件"
- **正确做法**: 一行 QRadioButton（同 parent 自动互斥，不需要 QButtonGroup）+ 状态标签 + 一个操作按钮，`toggled` 里记 `self._ct_mode = key` 即可
- 规律（印证记忆铁律）: 老倪要的是"点一下即选中"的极简控件，不要执行流程/状态切换/多按钮组合——功能块越简单越好，逻辑藏内部

### 7. QTextEdit QSS padding 上下留白 → 光标/行距视觉两倍 (2026-08-09 实测)
- 症状: 日志区"光标太大了，相当于两倍行高" — 实际是 QSS `padding: 8px` 的上下留白把 QTextEdit 内每行的视觉间距撑成两倍（光标高度=行高）
- 修复: `padding: 8px` → `padding: 2px 4px`（上下 2px 左右 4px，保留左右舒适度、消掉上下虚高）
- 排查: 用户报"光标/行高两倍"先查 QSS padding 和 font-size，别先怀疑字体设置

## node_logic 节点逻辑面板源码映射 (2026-08-12 实测)
「📖 查看/编辑节点逻辑」面板显示代码的机制与坑 (node_logic.py + node_logic_dialog.py):
- 流程: `NodeLogicDialog._key = node_logic.match_node(node_name)`(最长关键字匹配) → `get_external_source(key)`(_EXTERNAL_LOC 映射外部真实源码) → 无则显示自身注册函数源码
- **_EXTERNAL_LOC 映射 = (绝对路径, 行号, 符号名)**: 定位用**符号名搜索**(`ln.strip() == sym or startswith(sym + "(")`), 行号仅兜底 — 行号错位时(映射写 59 实际 60)源码截取从空行开始 → 面板只有"源码结束"标记行(用户报"没有字")
- **sym 必须是真实符号名** (`class RightBrainWM` / `def pixel_to_ray`): 描述文字("grasp 阈值参数")定位失败 → 空白
- **无独立实现的融合/参数节点(State Adapter)不挂 _EXTERNAL_LOC** → 显示自身注册函数(可编辑区); 误指到别的源码(如指向 YoloStateAligner)会被用户发现"两个节点代码一样"
- **逻辑函数开头必须 `log = ctx["log"]`**: execute_node_logic 把 `module._log` 注入 ctx, 函数内是局部变量不是全局 — 新注册函数漏了这行 → 双击执行 NameError; 批量补插时用正则 `(def fn\(ctx\):.*?\n)(    )` 插入, **heredoc 里 `ctx[\"log\"]` 的反斜杠转义会写坏文件**(`\\"` 残留在代码里 → SyntaxError), 用 python 脚本处理时避免字符串里写反斜杠字面
- **用户铁律: 每个节点都得有代码** — Z700 全部 20 个功能节点都注册 `_reg(key, [匹配关键字], doc, fn)`, 无独立逻辑的节点也给描述型逻辑函数(数据源/状态机阶段/方案介绍等); 数据源节点逻辑里写"源码 tools/gen_metaworld_data.py"引导
- 验证: `match_node` 对画布全部节点名遍历 → 无 None + `execute_node_logic(FakeMod(_log), node)` 全部可执行(21/21 PASS)

## 训练产物权限 600 崩 GUI (2026-08-12 实测)
- docker(root)训练产物默认 `-rw------- root root` → 当前用户 xspace 读不了 → **GUI 启动崩溃**(DatasetModule 遍历 outputs/train/ 时 `os.path.getsize` 抛 PermissionError, exit 1)
- 修复双层: ① `sudo find outputs/train/ -type d -exec chmod 755 {} + && sudo find outputs/train/ -type f -exec chmod 644 {} +`(全量! 历史产物同样 600, 只改本次目录不够) ② GUI 遍历加 try/except 容错(sz 回退 0) — 权限问题不再崩启动
- ls 显示 `-?????????`(元数据读不到)= 父目录权限问题, chmod 目录后正常

### 13. 「断点进不去」先分两半: 进程里没调试器 / 追踪器被自己代码顶掉
- **进程侧**: 很多控制台把调试端口做成 env 开关(如只在 `ZMAX_DEBUG=1` 时 `debugpy.listen(("127.0.0.1",5678))` —— 默认不开是因为无 attach 时 listen 会阻塞 Qt 主线程 map 窗口)。
  于是直接跑起来的实例**根本没有调试器**, 编辑器里的断点只是"画"在那儿。判据: `ss -ltnp | grep 5678` 无监听 + 窗口标题/状态栏应有"非调试模式"提示。
  解法: F5 launch 一个带调试器的新实例(justMyCode=false), 或让实例带 `ZMAX_DEBUG=1` 起再 attach 到该端口。
- **代码侧**: 应用自己的"逐行执行/变量数值变化"功能常用 `sys.settrace()` 实现 ⇒ 它会**覆盖 debugpy 的 tracer**, 断点静默不命中。
  这类代码多半在 `finally: sys.settrace(None)` 清理 ⇒ **函数返回后再读 `sys.gettrace()` 永远是 None**(最易把排查带偏)。
  判据必须在**被追踪函数体内部**记录 `sys.gettrace()`: 未 attach = 有 tracer 对象; 已 attach = None(把断点交还调试器)。
- **装载方式侧**: 按路径 `spec_from_file_location` + `module_from_spec` + `exec_module` 且**不注册 `sys.modules`** 的模块, debugpy 解析不到 ⇒ **断点不绑定**(函数真跑、编辑器不停), 且同一份文件被 canonical import 过的另一处断点看起来正常, 最容易把人带偏。
  修法(已实测): `exec(compile(src, os.path.abspath(path), "exec"), m.__dict__)` + `types.ModuleType(mod_name)` + `sys.modules[mod_name] = m` + 注入 `__file__/__name__`, 失败再退回 spec 装载。
  判据三条一起看: `m.__name__` 对 · `mod_name in sys.modules` 为 True · 目标方法的 `__code__.co_filename` == `realpath(该文件)`(先 `readlink -f` 核对路径里有没软链成分)。这类模块每次调用都重新从磁盘 exec ⇒ **改文件不必重启进程**。
- **实例属性顶掉方法 (第四成因, 最不像 bug)**: 装配期常有 `self.obj.method = self.obj.analytic_forward` 这类替换,
  多见于"降级/旁路档"开关(例: 环境变量未设 `SS_USE_MLP` 时 `accel.forward` 被换成解析律) ⇒ 类里那个函数体
  **一次都不会执行**, 断点当然不命中, 而调试器本身完全正常。
  判据: `getattr(obj.method, "__qualname__")` 与 `obj.method.__func__ is type(obj).method` —— 不是就说明被替换;
  或在目标函数首行加"每 N 次打一行"的 print, 那行不出现即证明是路径/替换问题, 不是断点绑定问题。
- **第五成因: 代码跑在另一个进程** —— GUI 里的 F5 只调 GUI 进程; 常驻引擎/服务(如 `ss_engine_loop.py`)是另一 pid,
  在编辑器里设的断点对它零作用。判据: `pgrep -af "<脚本>"` 看被调试 pid 与真正干活的 pid 是否同一个
  (另一个 pid 的 `/proc/<pid>/task/*/comm` 里没有 pydevd/GUI 线程)。解决: attach 那个 pid, 或让引擎在 GUI 进程内跑(▶运行 路径)。
- 触发路径: 只在"▶运行/单步/右键运行"里执行的代码跑在 Qt **主线程**(不是 worker 线程) ⇒ attach 后主线程断点正常命中; 光改文件不点运行, 永远不会经过断点.

### 14. `Destroyed while ... is still running` + `Fatal Python error: Aborted` (QThread / QProcess 同族)
- 典型成因: `QThread`(子类)实例只活在局部变量里 —— `.start()` 返回后 Python 包装对象被 GC, 而 C++ 侧线程还在跑 ⇒ Qt 直接 abort, **窗口整体消失**(应用日志里没有 Traceback)。
- 纪律: 每个 QThread 实例都要有长期归属(`self._workers.append(w)` / `self._w = w`); 自查 `grep -n "Worker(" <file>.py`, 逐个确认实例被持有。
- **★ 反查顺序: `Aborted` 上面那条 Python 异常才是根因** —— 建页/构造中途抛异常 ⇒ 已经起的后台线程没人停 ⇒ `QThread: Destroyed while thread is still running` ⇒ `Fatal Python error: Aborted` + core dump。
  所以崩溃栈里的 DDS/mujoco/torch/其它 C++ 线程**只是陪葬**, 别先怀疑它们; 判据 = 启动日志里 `Aborted` 之前那段 traceback 定到哪个函数抛的, 不是末尾的线程列表。
- **收到别人传进来的 layout 必须按类型自适应**: builder 拿到的可能是 `QFormLayout`/`QVBoxLayout`/`QHBoxLayout` 任一 —— `QFormLayout` **没有 `addLayout`/`addWidget`, 只有 `addRow`** ⇒ 误用抛 AttributeError(建页即崩, 且崩在启动期不好定位)。写法: 控件包一层 QWidget 后 `if hasattr(layout, "addRow"): layout.addRow(w) else: layout.addWidget(w)`。
- **同一个坑在 `QProcess` 上以另一副面孔出现: 把 QProcess 挂 `parent=控件`**(`QProcess(self)`)—— 换页/关窗时父控件先析构, 而子进程还在跑 ⇒ `QProcess: Destroyed while process is still running` ⇒ **abort / core dump (控制台整体消失)**。它只在"离屏验证脚本跑完析构"或"用户换页/关窗"时触发, 平时看不出来 ⇒ 必须显式测: 起采集后立刻 `w.close(); w.deleteLater()`, 不断言到无崩溃就别算完。
  - 正确写法(实测): ① **不挂 parent** —— `p = QProcess()` 并把引用存成 `self._proc`(谁持有谁负责); ② 槽里用 `self.sender()` 取回对象, 不要 `lambda: self._on(p)` 闭包捕获(闭包持的是已删 C++ 包装对象, 报 `wrapped C/C++ object of type QProcess has been deleted`); ③ 槽内 `readAllStandardOutput()` 用 try/except RuntimeError 兜; ④ 提供 `stop()`: disconnect → 未停则 `kill()+waitForFinished(300)` → `deleteLater()`, 并在 `closeEvent` 里调它 + 停掉自己那个刷新 QTimer; ⑤ 收到 `finished` 后 `deleteLater()` 并清 `self._proc = None`(防重入叠进程)。
- **用 QProcess 定时跑只读工具取实时数据是可行模式**(数据条/明细表): 子进程跑 `工具 --json` → 主线程解析 → 贴到 QLabel/表。纪律: 显示**采集时间**(没有时间戳的数字等于没说) · 工具失败显红字并保留上一次的值(绝不假装正常) · 上一轮没回不叠新进程 · 按真源 mtime 或定时器缓存。
- 取证口径: faulthandler 全线程栈 · 有没收到过信号(没信号也会出现同一签名, 别默认归因 kill/关机) · 谁把进程拉回来的(桌面图标的 `GIO_LAUNCHED_DESKTOP_FILE` / user unit 的 Restart 策略) ——
  清单见 zmax-console `references/gui-debug-and-crash-forensics.md`。dump 只给各线程**当前**状态, 不记录是哪个点击触发 ⇒ 不要凭"崩溃前点过什么"归因, 要归因就加崩溃记录器(faulthandler 全栈 + 最近 N 条界面操作落 `~/zmax_data/*_crash_*.log`)。

### 15. 小尺寸自绘面板: 字体必须 setPixelSize (本机字体 DPI 放大 ~1.5 倍)
- 本机 studio 是给 3200x2000/192DPI 屏适配的, **QFont(fam, 8)(点) 实际渲染高度 ≈16px, 宽度 ~1.4 倍**
  ⇒ 按"8pt≈11px"设计的 420x68 小面板在真机上字全部溢出/叠字/被裁 (离屏和真机都这样, 不是截图缩放问题)。
- 判据: 真机截图里量**文字行高** (白色像素行范围) 与设计值对不上 ⇒ 就是字体 DPI 缩放, 别去改布局。
- 修法: 小面积控件的字体一律 `f = QFont(fam); f.setPixelSize(px)` (像素尺寸与 DPI 无关),
  先用 `QFontMetrics(f).width("内存"/"100%"/"annot")` **量出真实宽度再定框宽**, 别估。
- 教训: 面板类 UI 先做"量尺寸 → 定框 → 渲染 → 像素级量文字行高"闭环, 别按 pt 猜。

### 16. 常驻角落面板挂载点: 包一层 central 布局, 别用 QStatusBar.addWidget
- **不要用 `QStatusBar.addWidget`**: Qt 的 `showMessage()` 会**隐藏** addWidget 加的常规控件,
  而 studio 到处在调 `showMessage(msg, 3000)` ⇒ 面板会不停闪没。`addPermanentWidget` 只能挂右侧。
- 正解(studio 实测): `_build()` 里把 central 的 `QHBoxLayout` 包进一个 `QVBoxLayout`,
  底部再 `addLayout` 一行 `[面板, addStretch(1)]` ⇒ 面板落在内容区左下角, 与侧栏/堆叠页
  **零重叠**(off 屏断言 `panel.top() >= sidebar.bottom() and panel.top() >= stack.bottom()`),
  也不吃 QStatusBar 的坑; 收起侧栏时面板还在。
- 面板控件自身 `setFixedSize(420, 68)` + 独立文件 (`tools/gui/status_panel.py`),
  `studio.py` 里只留 10 行挂载 + try/except 兜底(导入失败不影响控制台启动)。
- 验收要**真机重启后看**: `kill -9 <显式PID>` → `bash tools/gui/launch_studio.sh`(自带防重复实例) →
  `xdotool search --name "XSpace Studio"` 取几何 → `scrot` 全屏 → 按窗口几何裁左下角 → 放大 3~4 倍读字。

### 17. 「面板太小 / 拖分隔条也拖不大 / 内容看不见」= 子控件最小高度把空间吃光
- 症状: 底部或右侧面板被压成几十像素, 鼠标拖分隔条**也**拖不大; 用户报"窗口太小, 根本看不到"。
- **一句话判据** (先量再改, 别猜): `splitter.widget(0).minimumSizeHint().height()` —— 若已≈分隔条总高,
  就是上方工作区把空间吃光了, **不是"忘了设可拖"**。实测量到 1265px 工作区最小高 / 窗口 1363px ⇒ 另一侧只剩 98px。
- 根因链: 页里的表给了按行数算的 `setMinimumHeight`(如 510px) ⇒ **QTabWidget 最小高 = 各页最大值** ⇒ 上层没有余量可分。
- 修法 (四件一起做, 缺一个症状就还在):
  1. 每个页签包 `QScrollArea` + `setWidgetResizable(True)` ⇒ 页面能压小, 内容靠滚轮/滚动条看全 (原来是硬切)。
  2. 要看表的最小高**封顶**: `min(460, 行高*(行数+2)+8)`; **禁用 `setMaximumHeight` 去压一张要看的表** ("根本看不到"的元凶);
     放不下交给 QScrollArea 滚, 别靠压表; 配一个「📋 复制…(TSV)」按钮让内容能拿走。
  3. 面板用**竖直 QSplitter** + `setHandleWidth(9)` (4px 抓不住); 面板高度**不再 setFixedHeight**;
     用户拖过之后设 flag (`_user_sized=True`) 就不再自动改尺寸(给一个"↕ 自适应高度"按钮重算)。
  4. **先靠最小高度定尺寸, 别指望 `setSizes()`**: 构建期 (或页面还藏在隐藏的 QTabWidget 页里) `height()`=0,
     此时 `setSizes([...])` 会被 Qt 按比例缩回去 —— 实测给 `[552,600]` 结果还是 464px。**两舱各
     `setMinimumHeight(够看高度)` 才是有确定性初值的做法**; 要补算就在 `showEvent` 同步算一次 + 挂 tab
     `currentChanged` 幂等补算 (隐藏页里算不出 ⇒ 别"算一次就置 flag")。
- 可隐藏: 用自己记的 flag (`_on`) + `setVisible()`; **不能拿 `isVisible()` 当判据** (离屏/父未显示时恒 False)。
- 内容"选哪个面显哪个" : 每面给[当前面名 + 该面真源摘要 + 真源在哪] 一行, 挂 tab `currentChanged`; 页面内动作(导出/复制)之后再覆盖它。
- 验收判据: 切到该页量 `table.height()` (行数对但高度被压**不算过**) + 窗口压矮后仍 ≥ 各自最小高 + 每个页签确实是 QScrollArea + 内容超视口时 scrollBar().maximum()>0。
- **"能不能看见"按行数说, 不按像素说**: 判据 = `(表高 − 表头高) / 行高` ⇒ 可见行数; 再加**表内 `scrollBar().maximum()==0`**
  (内容真的全在表里) 与**页面 `verticalScrollBar().maximum()`** (超出视口就得页滚 ⇒ 把 px 数写进汇报)。三样齐了才算量清。
  量测一律离屏 (`QT_QPA_PLATFORM=offscreen` + `page.resize(W,H)` + `show()` + `processEvents()` + `widget.grab().save(png)`),
  并按**用户真实窗口几何**补一档容器尺寸 (`DISPLAY=:0 wmctrl -lG | grep <标题>` 取尺寸); 出图后用 OCR 数条数当"N 条都在画面里"的证据。
- **重启脚本只"告警"越界、不会替你夹窗口** (它刻意不写窗口尺寸, 因为硬 resize 会和应用的 show/fit 抢) ⇒
  起完读 `xdotool getwindowgeometry --shell <wid>`: 若 `X+WIDTH > 屏宽` 或 `Y+HEIGHT > 屏高`, 手工夹:
  `wmctrl -i -r <wid> -b remove,maximized_vert,maximized_horz` → `wmctrl -i -r <wid> -e 0,x,y,w,h`。
  **WM 会坚持自己算的 x/y** (只认 w/h), 所以要**迭代改 w/h** 直到右边界/下边界进屏, 每次都 `xdotool getwindowgeometry` 复核;
  实测一次给 3060x1900 仍越界 98px, 收到 3020x1740 才全在屏内。别只看 `wmctrl` 返回码就宣布搞定。
- **两张表同处一个 QVBoxLayout、谁都没边界 ⇒ 用户"想多看也拉不动"**: 这是结构缺陷, 补一条竖直 `QSplitter`
  (`setChildrenCollapsible(False)` + `setHandleWidth(9)` + 连 `splitterMoved` 记 `_user_sized`) 才算修好 —— 不是把高度调大就完事。
- 🚫 **一个 QLayout 只能有一个父布局**: `l.addLayout(row)` 之后又把同一个 `row` `addLayout` 到新容器,
  Qt 只认第一个 ⇒ 那一行控件高度被挤成 **0** (肉眼=按钮消失, 且**没有任何报错**)。把控件挪进新容器前先删
  **原容器的 add**; 接手别人的布局改动先 `grep -n "addLayout(<row>)\|addWidget(<widget>)"` 查重。
- **最小高度写成 `min(上限, 行高*(行数+2)+8)` 时, 那个"上限"就是天花板**: 用户说"还太矮"时第一件事是找它
  (第一轮封 `300` 就是把表压到只看得见十几行的元凶); 表格行被某列长文本(`" → ".join(...)` 且是唯一 Stretch 列)撑高时,
  单元格改短标签 + `setToolTip` 放全文, 而不是调高度。
- **中文表格列宽**: 打印/对齐要按**显示宽度**补空格 (东亚宽字符算 2: `unicodedata.east_asian_width(ch) in "WF"`),
  直接 `%-7s` 会串列。
- **回归证据 = 和"改动前"逐条比对, 不是只看"全绿"**: `git stash push -- <改动文件>` → 跑既有 verify 套件 → `git stash pop`,
  这样能分清哪条 FAIL 是本来就有的; 用户要的是"没回退"。

### 18. 「反应非常慢 / 点一下要等」= 先 py-spy dump 定主线程栈, 别猜机器慢 (2026-10-17 实测)
- **判据顺序 (30 秒出结论)**: ①`ps -o pid,pcpu,nlwp,etime -p <pid>` 看主进程 %CPU 与 **TIME+ / elapsed 比例** — 接近 1.0 就是"自始就在烧一个核"(与"某次点击后变慢"完全不同的病); ②`top -H -b -n1 -p <pid>` 看哪个线程热(通常 MainThread 99.9%, 其它 sleeping); ③**连打 8 次 `py-spy dump --pid <pid>`(间隔 0.4s) 只取 MainThread 前 6 行** —— 8/8 同一条栈才算定死, 单次采样会被一次偶发回调骗; ④`py-spy record -d 6 -f raw` 的 leaf frame 分布**分散时不要采信**(json/socket/subprocess 各 1~3% = 你在看一堆无关定时器), 递归栈才是热点; ⑤应用日志增速也能量: `wc -c <log>` 隔 5s 再量, 增长 0 = 卡在主线程而非日志刷屏。
- **本机 py-spy 在 Hermes 自带工具目录**(`which py-spy` 指到 `~/.hermes/tools/...`), 读别的进程要 `sudo`; `py-spy top` 需 tty(非交互会 `Not a tty`), 用 `dump` 循环代替。
- 🔴 **QTreeWidget/QTableWidget「刷新显示值」会伪装成用户操作**: `QTreeWidgetItem.setText(col, …)` **和 `setToolTip(col, …)` 都会发 `itemChanged(item, col)`** —— tooltip 走的是 `setData(ToolTipRole)` ⇒ **col=0**, 于是任何"只处理勾选/选中变化"的槽都会**照单全收**: 每拍 × 每行 各跑一次全树递归 + `set_curves()` 重建曲线 ⇒ O(行数²)。实测 460 行 × 4Hz ⇒ 主线程 **99.9%**, GUI 事件全排后面。
  - **修法两层都要**: ①槽里先做**状态相等即返回** (`if checked == (key in self.selected): return`), 不再假设 "走到这个槽 = 真的变了"; ②刷新循环**逐行缓存** (值文本+tooltip 拼好先比对, 相同就一次 Qt 写都不做), 稳态一拍 0 次写入。
  - **量化口径**: 单次全树递归 + 重建 = 0.53ms × 460 行 = **247ms/拍**; 缓存后整拍 **1.84ms** ⇒ 4Hz 下 99% 核 → 0.74%。汇报用"ms/拍 + 折算核占用", 别只说"优化了"。
  - **回归判据**: offscreen 真建该 widget + 造同量级行数(与线上 400+ 同级), 用计数器包住 `_ordered_selected`/`set_curves` 数调用次数(稳态必须 0), 然后**真 `setCheckState`** 验证勾选/取消仍生效 —— 缓存和早退最容易把功能改死, 这条不能省。工具有现成的: `scripts/qt_tree_refresh_cost_probe.py <行数> <Hz>` 一份跑出旧写法/缓存写法的 ms/拍 与每拍 itemChanged 次数 (项目里换成真 widget 就是正式判据)。
- 同类隐形风暴: 一次 tick 里做**文件 JSON 读+解析**(`_chunk_text()`/状态文件)4Hz 也在 json decoder 里烫 CPU ⇒ 不变的内容同样要缓存 (按 mtime 或内容签名), 别每拍重读。
- 汇报口径: 给出"根因栈 + 每秒触发次数 + 折算 CPU"三件, 再说"要重启才生效"; 用户正在操作时**不要擅自杀 GUI**(先看 GUI 日志最近 1~2 分钟的点击/切页留痕判断是否在用)。

### 19. 「表里没数据 / 那一列怎么不见了」先查**可见性**, 再查数据源
- **活数据排在表尾 = 看着像死了**: 表按话题名/字典序排时, 正在跳的那几行常常排在几千行最后,
  第一屏全是 `—`。口径: **按新鲜度排序**(帧龄 <3s 置顶, 没有帧龄的靠后), 并在工具条给一行
  `⚡ 实时 3 话题 · 182 信号 · 帧龄 0.06s`(绿/红) —— 用户判"有没有在动"看这一行, 不用数格子。
  别拿"fields 非空"当活跃判据: 停掉的话题 fields 里还留着 `state=[] count=0`。
- **关键列放最后一列 => 看不见**: 左侧面板窄(实测视口 440~510px)时, 靠后的列被挤出视口,
  用户只会问「XX 列呢?」。重要的分类列(Layer/Type)放第 1~2 列, 权重列放最后。
- **同一份数据两个窗口数值对不上**: 各自 parse 同一文件会差半个采样周期。做法是两边都读
  同一个 provider 的**同一份 TTL 缓存快照**; 判据写成"同一缓存窗口内两次读逐值相等",
  而不是"两个窗口各读一次再比"(后者必然偶发不等)。
- **正则抠 JSON 键只认 `[A-Za-z_]\w*` 会漏掉中文键**: `"末端_x": 1.2` 一个都匹配不到,
  结果整列退化成"全缺测"。改用 `"([^"]{1,40})"\s*:\s*(数值)`。
- **逐行值缓存不能只按业务 key**: 同一条信号在两个分组各有一行时, 第一行写完后第二行永远停在
  `-`。键要带控件身份: `(id(item), key)`。

### 20. 列头按值过滤 (不另加一行下拉) + 可测法
- `header().setSectionsClickable(True)` + `sectionClicked` → 收集该列取值与条数 → `QMenu`
  (`QActionGroup` 单选, 首项「全部」+ 末项「清除所有列的过滤」) → 递归 `setHidden` 不匹配的叶子行;
  子行全被隐藏的分组也一起藏。列头常显 `▾` 提示可点, 生效时显示 `Layer ▾ L2`;
  **重建/刷新树之后要再套一遍过滤**, 否则刷一拍就恢复全量。
- 判据(离屏可跑): 劫持 `QMenu.exec_` 返回 `data == "L2"` 的 action, 调 `_on_header_filter(1)`,
  断言可见行数从 N 降到 M 且该列只剩 `L2`; 再叠第二列过滤只清第一列, 断言第二列过滤仍在。
- 改列序要同步 **QSettings 列宽键换版本**(`...cols` → `...cols_v2`), 旧键按下标记宽, 顺序一变就套错列。

### 21. 「删按钮/删文字行」: 先判能不能真删, 不能才藏
- 别处还在读 `btn.isChecked()` / `btn.toggled` / `label.setText()` 时, 直接删控件就是 AttributeError。
  这类一律 `w.setParent(self); w.hide()`。
- **数据驱动的行可以真删, 但三处必须同一 patch 一起删**: 行集合通常是元组/列表 (`_ROWS = (...)`) 驱动建控件 +
  `dict[行名]` 存控件 + 刷新函数里逐行 `vals[行名].set_value(...)`。只从元组删键 ⇒ 刷新时 `KeyError`;
  只删控件不删元组 ⇒ 建控件时就崩。做法: 元组删键 → 刷新函数删对应 setter → 删只服务这些行的状态标签/
  日志拼接/内部回算块 → 收尾 `grep -n "<行名>" <file>` 必须为 0 (留一行 = 死代码, 用户会追问)。
- **判据同步改成"断言不存在"**: `k not in page._vals` / `not hasattr(pg, "_src_label")` /
  卡片 `findChildren(QLabel)` 文本里不含那段文案。旧判据留在目录里会拿已删的行报 ✗, 被当成回归。
- **同一块 UI 的删减一定是多轮**: 用户先贴一批 ("这些全删掉"), 验收时再追加一行 ("XX 删掉")。
  每轮都要重跑**依赖该行集合**的判据 (行元组 + 取数 setter + 判据里硬写的期望字典三处一起改),
  别以为删一轮就收工 —— 第 N 轮漏改, 界面会 `KeyError` 或判据报 ✗ 被当成回归。
- 🔴 **判据里拿被删行当"载体"的检查要换目标, 不能直接删**: 复制类判据常挑一个**截断显示**的行来验证
  "显示截断 / 复制完整"; 这行被删后"截断"这个前提也消失了 ⇒ 换到仍存在的一行, 并把断言诚实降级为
  `复制值 == full_value` (去掉"显示文本不含完整值"), 同时在汇报里说清降级原因。留着前提已消失的断言 = 假绿。
- **删行后顺手清只服务它的模块级 helper**: 例 `_cut_big()/_vmark()` 的唯一调用点就在被删的 setter 里 ⇒ 连 helper 一起删;
  删前先在**整个仓库** (`grep -rn "_cut_big\\|_vmark" --include=*.py`) 确认零消费者 —— 工具/判据脚本也会 import 它们,
  只删确实没人用的, 否则界面干净了、别的脚本 ImportError。
- **用户指着 A 说"删掉"因为它与 B 重复时, 删副本、留单一真源**: 删之前先 `grep` 那段文案/路径确认它是
  B 的同源副本 (同一 provider 函数), 删完 B 仍要能独立工作; 副本的构造函数/刷新方法/判据断言一起下架, 别只移出布局。
- 🔴 未上布局又没 `setParent` 的控件会变成**漂浮的顶层窗口**; 探针用
  `[x for x in QApplication.topLevelWidgets() if x is not w and x.isVisible()]` 确认干净。
- 取证三件: 可见按钮/标签列表 · 按 `mapTo(w, rect().topLeft()).y()//10*10` 分行(只应剩一行) ·
  最右 `mapTo(w, rect().topRight()).x()` < 窗口宽(不溢出/不折行)。

### 22. 断点已停住, Call Stack 还在不断变化 = 别的线程在抢焦点
- 机制: 命中断点只冻结**命中那个线程**; VSCode 的 Call Stack 面板显示"当前选中线程", 别的线程再命中断点/线程内未捕获异常都会发 stopped 事件 ⇒ 编辑器自动切线程, 面板里整套帧换掉, 看着像"栈一直在变"。
- 先量再改: `ls /proc/<pid>/task | wc -l` + `cat /proc/<pid>/task/*/comm` —— 控制台类 GUI 常态 20~60+ 线程 (Qt 事件队列/QDBus/缓存/每个 2s 轮询器各占几个)。
- 修法三件(应用侧做, 已实测): ① **调试期不启动后台轮询线程** —— `debugpy.is_client_connected()` 或 `sys.gettrace() is not None` 判定, 另留 `ZMAX_DEBUG_QUIET=1` 强制; ② `threading.excepthook` 改成写日志文件、不抛回解释器; ③ 用户侧兜底: 断点右键 → Edit Breakpoint → `Hit Count=1` 或条件表达式, 只停一拍。
- 实测: 同一 GUI 正常 24 线程 → 静默 16 线程, 断点处 Call Stack 定住。
- 反向判据: 代码里周期打印的"真身执行 #N"一行不出现 ⇒ 是路径没走/被替换(见 §13), 不是断点绑定问题。
- 三成因清单 + 逐条取证命令: `references/gui-not-responding-popup-and-debug-blocks.md` §4/§5。

### 23. pyqtgraph `dataRect → np.min` 抛 RecursionError = 栈被信号级联压满, 不是 np.min 递归
- 现象: 波形/曲线面板刷新时抛 `RecursionError: maximum recursion depth exceeded in comparison`, 栈顶在 `PlotDataItem._getDisplayDataset → dataRect → _getArrayBounds → np.min`。别去质数 numpy。
- 机制: 刷新里 `setData` / `setYRange` / `linkedViewChanged` 互相触发, 每个 ViewBox 收到新范围立即重绘, paint 又回头算 dataRect 扫数组; 多子图/叠加模式下叠到 ~1000 层就崩在随手一个 `np.min` 上。
- 修法四件(缺一条就还能复发): ① `setData(..., skipFiniteCheck=True)` —— 数据已知有限, 不让 paint 每帧扫数组(直接去掉报错那行); ② 刷新函数加重入闸 `_in_refresh`(级联不叠栈); ③ 每帧 `setYRange` 只在量程真变时才调(缓存上次量程, 容差 1e-9); ④ `except RecursionError` 里把完整栈写日志再 raise(留证据不吞错)。
- 判据: `sys.setrecursionlimit(250)` 压低后, 全选 1000+ 条缓冲 × 三种模式(同轴/9 子图/叠加) 各跑 25 拍 0 异常; 改前必炸。绘制条数上限(MAX_DRAW 之类)保留, 别为了"全画"把级联放大。

### 24. 自绘 paintEvent 里现造 QFont/QFontMetrics = 主线程 CPU 黑洞；缓存必须带上限
- 症状: 常驻 GUI 烧 100%~200% CPU、界面发涩; py-spy 里 `_block`/`_labels`/`paintEvent` 各占 5~8%(leaf)。
- 机制: 每个文字块**每次重绘**都 `QFont("…")` + `setPixelSize()` + `QFontMetrics(f)` + `horizontalAdvance()`;
  一帧几十块 × 60fps ⇒ 全是构造开销。实测单次量宽 **13.7µs → 复用后 4.5µs**（3 倍）。
- 修法: 模块级 `_FONT_CACHE[(size,bold)]` / `_FM_CACHE[(size,bold)]`, `_block` 里改 `p.setFont(_cached_font(size))`;
  量宽再套一层 `(text,size)→width` 缓存; `_wrap()` 的换行结果按 `(text,width,size,sep)` 缓存。
- 🔴 **这类缓存的键常含实时数值 ⇒ 每帧都是新键，不设上限就是自己造泄漏**:
  回填前 `if len(cache) > 3000: cache.clear()`（宽度缓存可放到 2 万量级）。加缓存必须同时加上限。
- 量法（比"我觉得快了"硬）: 离屏 `QT_QPA_PLATFORM=offscreen`，同一段量宽循环跑 900 次，
  旧写法 vs 复用写法各计时一次，输出 µs/次。

### 25. 「所有这些文字都要能用鼠标选中/复制」= QLabel 默认选不了, 且动态建的会漏
- 机制: QLabel 默认 `textInteractionFlags() == NoTextInteraction` ⇒ 只能看不能框选, 用户会直接问「为什么这段话
  用鼠标选不了」。要能选才设 `Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard` + `setCursor(Qt.IBeamCursor)`
  (I 形光标是"这里能选"的唯一可视信号)。
- **必须两段, 只扫一遍不够**: ① 建页末尾 `for lb in page.findChildren(QLabel)` 全量扫一遍; ② 再装 **app 级
  `installEventFilter(self)`**, 在 `eventFilter` 里认 `ev.type() == QEvent.Polish and isinstance(obj, QLabel) and
  self.isAncestorOf(obj)` 开 flags。刷新/重读真源/换页之后**新建**的标签只有 ② 兜得住 —— 只做 ① 时判据会报
  「52 个标签里 11 个不可选」, 而且这 11 个正是用户盯着的那页。
- 🔴 跳过条件写错等于没改: `if f & (Mouse|Keyboard): continue` 会放过"只有 Mouse 没有 Keyboard"的标签
  (自定义可复制标签常只设 `TextSelectableByMouse`) ⇒ 判据若同时要求两个 flag 就红, 现象像"改了没生效"。
  正确写法 = **逐 flag OR**: `_want = f | Mouse | Keyboard; if _want != f: setTextInteractionFlags(_want)`。
- 树/表格不是 QLabel, 天生不能框选 ⇒ 补页级 `QShortcut(QKeySequence.Copy, page)`
  (`setContext(Qt.WidgetWithChildrenShortcut)`) + `_copy_focus_text()`: 焦点在 QTreeWidget 拷 `currentItem()` 文本、
  QTableWidget 拷选中单元格 **TSV**(可直接粘 Excel)、**QTextEdit/QLineEdit 一律调它自己的 `copy()`** ——
  别自己抄选择, 否则把原有复制行为弄坏。树再挂右键「复制条目文字 / 复制全部条目」(省略号截断的行也能拿全文)。
- **如实划边界: 按钮 / QRadioButton / 页签标题 / QComboBox 条目在 Qt 层面根本不能框选文字** —— 别承诺"所有文字都能选",
  回复里一句话说清这几类要用旁边的值行或 📋 拿; 用户要的是"能拷走", 不是"每个像素都能拖蓝"。
- app 级事件过滤器是**每个页面实例装一次**: 主窗口和独立窗口各建一个同一页面类实例 ⇒ 装之前留
  `if getattr(self, "_copy_filter_on", False): return` 幂等 flag, 否则每开一次窗就多一层 filter (polish 事件重复处理)。
- **判据必须真拖选, 不能只看 flags**: `QTest.mouseMove` **不带按键状态** ⇒ QLabel 不会进入选择态,
  `selectedText()` 恒空(会误判功能没生效)。手工发事件:
  `sendEvent(lb, QMouseEvent(MouseButtonPress, QPointF(x,y), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))`
  → 循环 `MouseMove`(**button=`Qt.NoButton`, buttons=`Qt.LeftButton`**) → `MouseButtonRelease`, 再断言 `selectedText()` 非空。
- 判据套件(离屏一次跑完): 全页 `findChildren(QLabel)` 100% 带两个 flag · 每个页签切过去再查一遍 ·
  后建标签 show 后自动带上 · 树 Ctrl+C 落剪贴板 · 表 Ctrl+C 出 TSV · 信息窗 Ctrl+C 仍走自己的 copy。
  现成探针: `scripts/qt_label_selectable_audit.py --module <模块> --class <页面类> --tabs` (前四条直接跑, 新增控件再补)。

**性能数字的口径纪律（不然会报出假账）**:
- `ps -o pcpu` 是**自启动以来的平均** ⇒ 判"现在多热"要读 `/proc/<pid>/stat` 的 `utime+stime` 两次差分
  （`awk '{print $14+$15}' /proc/<pid>/stat`）再除以采样秒数。
- `py-spy record --format raw` 每行末尾是**采样计数**，统计必须按计数加权；按行数平均会把少量深栈算成热点。
- 🔴 **窗口在后台时 Qt 不重绘** ⇒ 前台/后台两组 CPU 数不可比。A/B 汇报必须写清采样条件
  （"3D 面板在前台/后台"），否则"214% → 23%"其实是页面被切走了。
- 内存段差分（smaps 前后差）若 Δ 出现 **RSS→0** 且速率离谱 ⇒ 目标 pid 已被重启换掉，是假数；
  开工前记 `ps -o lstart= -p <pid>`，跑完再核一次，变了就重测（本类实例很容易被自己的重启脚本换掉）。
- 新增段全是 **64MB 级 anon rw-p** ⇒ glibc malloc arena 签名（每线程一套、只增不还）;
  缓解 = 启动时 `MALLOC_ARENA_MAX=4` + `MALLOC_TRIM_THRESHOLD_=131072`。
  线程数恒定而 RSS 仍按 MB/min 涨 ⇒ 不是 arena，去查按需扩容的环形缓冲/缓存上限。
- 验收"某行到底在不在表里"用 `scripts/offscreen_table_row_probe.py`（离屏造真控件 + 逐行打印 + grab 图）。

## 改动纪律: 只改用户指的那一处 (做多了 = 被退回重做)
- 用户说「增加 X 列 / 改 Y」就**只改那一处**。在同一个控件里顺手塞新模式、波形、附加页 —— 哪怕技术上更好,
  也会被判「你怎么把表格全给改了? 只是让你增加 X 列」并要求改回去: 白做一轮 + 多一次回退版本。
  多余的想法写进**回复**里问, 不要先写进代码。
- **交付前自证范围干净**: 与被改前的 rev 逐行 diff, 除目标改动外不该有别的 hunk ——
  `git show <旧rev>:<file> > /tmp/before.py && diff -u /tmp/before.py <file>`; 连 import 折行这类无关差异也还原成原样。
- **撤功能时判据要同步撤**: 旧判据脚本留在目录/后台跑会拿已删的功能报 ✗, 被当成回归。
  改成「断言该功能不存在」(`not hasattr(w, "trace_stack")`) 或删脚本, 并在回复里点明那条 ✗ 是旧判据。
- **回退不重写历史**: 新出一版并在摘要写清「撤掉 X, 保留 Y」, 让版本表读得出「加了又撤」的来龙去脉。
- **判据手法: 用 stub 真跑控件处理方法, 不建整窗**。有些方法不在你以为的类上 (画布视图 vs 模块控制器) ⇒
  逼历模块属性 `hasattr(cls, name)` 动态找拥有者, 然后用未绑定方法手传 self:
  造一个 stub 只暴露方法用到的属性 (`_items/_data_source/_log/_save_param_to_flow`), 调 `Cls.on_toggle_src(stub, node)`;
  断言副作用真发生 (点击序列/落盘/环境变量/磁盘上实读的对象数), 而不是只看代码里写了什么。

## 验证模式 (ad-hoc fresh 验证)
- 环境: `QT_QPA_PLATFORM=offscreen` + 系统 python3（GUI 依赖 PyQt5/numpy/PIL/cv2 在系统 python，训练依赖在 .venv）
- tempfile 脚本: `hermes-verify-<主题>-*.py` 写 /tmp → 运行 → 删除（不跑正式测试套件）
- 覆盖**每个 changed path** 的语法 + 静态断言 + 运行时构造验证，输出 ✓/✗ + 退出码
- 陷阱:
  - QWidget 子类 `__new__` 免构造会缺信号/属性（module_clicked 等）→ 真实构造或 monkeypatch 依赖
  - 断言别写 f-string 字面（`"_mx 步"` vs `"{_mx} 步"`）；属性名先查（ModuleCard 无 .title/.sys_label 属性——用 findChildren(QLabel) 查文本）
  - 运行时验证用对解释器（torch 类脚本必须 .venv）

### 静默失败陷阱 (try/except 吞异常 = 功能看似没生效)
- **QDockWidget 挂到 QWidget 上 = 侧栏/停靠面板一直没出现 (2026-08-14 实测)**: `self.addDockWidget(Qt.RightDockWidgetArea, dock)` 只有 QMainWindow 才有 — 宿主是 QWidget 时抛 AttributeError, 被集成处 try/except 吞掉(日志一句"加载失败") → 面板静默缺失, 用户反复问"右侧的栏怎么一直没有"且排查多轮都查不到(代码看着都在)。**排查口诀: "右侧/停靠面板一直没出现" → ① 先 grep 宿主类定义是不是 QMainWindow(QWidget 无 addDockWidget) ② 再查 try/except 是否吞了异常(临时 `except Exception as e: print(repr(e))` 暴露)**; QWidget 容器加侧栏 = 水平 QSplitter 加一列 `split.addWidget(panel); split.setStretchFactor(split.indexOf(panel), 0)`(固定宽可拖), 面板基类 QWidget + `setLayout(lay)`(QDockWidget 的 setWidget(root)/setFeatures/setAllowedAreas 全删)
- **QSpinBox 无 `.decimals()`** (QDoubleSpinBox 才有): `spin.setValue(int(val) if spin.decimals()==0 else val)` 对 QSpinBox 抛 AttributeError → 被 except 吞 → 参数永不更新。修复: 先 `try: spin.setValue(val)` (QDoubleSpinBox) `except: spin.setValue(int(val))` (QSpinBox) 双回退。
- **`dict.get(name, {默认}[name])` 默认参数无条件求值**: Python 先算默认参数再调 get → 即使 get 命中, 默认 dict 缺 key 照样 KeyError (实测: tag dict 无"官方专家"→ 切模型时方法在 arch 段前崩, 参数区永远不动)。修复: `a.get(name) or b.get(name, fallback)` 链式, 不用 get 默认参数。
- **正则不锚定缩进**: config 里 `  lr: 1e-4` (optimizer 下缩进) 用 `^lr:` 匹配不到 → 读不到值。用 `^\s*key:`。
- 排查"功能没生效": 临时把 `except Exception: pass` 改成 `except Exception as e: print(repr(e))` 暴露被吞的异常, 定位后再还原 (比猜快)。

## 模块库全节点覆盖模式 (Simulink 式画布 + 左侧可拖库)
- **需求**: 所有模板（模型对比/VLA-Touch/AWE/总系统/CICD 等）的每个节点都要能从左侧模块库拖出，功能一致
- **盘点差集** (关键步骤): 模板节点集 vs LIBRARY 条目集取差集 → 精准补缺，不盲改
  ```python
  # REFERENCE_APPS 模板的 tpl[1](节点定义) + tpl[3](布局行) 收集节点名
  lib_names = {it["name"] for _, _, items in LIBRARY for it in items}
  missing = sorted(tpl_nodes - lib_names)   # 逐个补 LIBRARY 条目
  ```
- **分类**: 补条目按组归类（模型主干/训练/ActionHead/仿真推理视频/硬件别名…）；同构批量条目用列表推导式生成（`for m in [模型列表]`）
- **模板名 vs 库条目名不一致** → 在 LIBRARY 补"别名条目"（同功能不同名，如 H00 Orin Nano vs "Orin Nano"、"🧠 ACT 训练" vs "🚀 ACT 训练"），不改模板
- **改名/删除条目的引用完整性** (老倪铁律"注意数据源别改没了"):
  - `replace_all` 改名后必须验证: 旧名 0 残留 + 新名统一 + **模板加载正常**（load_reference_app_by_name 后数据源节点在）
  - 删条目用 patch 精确删，**删前确认**同类条目/画布数据源仍在
- **主数据注册**: LIBRARY 节点同步注册进全局数据空间（data_space.py `_scan_nodes()` — 节点即主数据，node↔主数据映射）

### 新节点类型三步注册（漏一步就 KeyError/静默缺失）
新增节点类型（如 `coord_overlay`）必须同时改 3 处，少一处就出具体故障:
1. **类型注册表**（NODE_TYPES/COLORS 映射，如 `"coord_overlay": {"cn": "坐标叠加", "color": "#58a6ff"}`）
2. **icon 字典**（`add_node` 里的 `"icon": {...}[ntype]`）→ 漏了报 **`KeyError: '<ntype>'`**（模板加载即崩，症状在 add_node 行）
3. **node_logic 注册**（`_reg("coord_overlay", [...], node_func)`）→ 漏了双击无逻辑
排查顺序: 先 grep 类型名出现在哪几个文件/字典，逐个对照；另一会话可能只加了 1、3 漏了 2。

### 模板同名节点 = 多实例（每定义一个）
- 模板加载机制: 遍历 node_specs 定义 → 每个定义按布局同名位置放一个 → **同名定义 N 次 = N 个独立节点**（各自 params 独立可改）
- 布局（tpl[3] 行网格）引用了节点名但 node_specs 无定义 → 该节点**静默缺失**（不报错）→ 用盘点差集脚本找
- 共享节点（数据源/评估）是同一个定义名出现在多行（shared 参数），区别于多定义
- **共享节点下放/移除模式 (2026-08-08 结构条件)**: 节点从公共感知链移到每模型行 (布局名加后缀如 "🧩 结构条件 · ACT") 时, **保留原共享定义不删** (定义索引=edges 引用索引, 删了全表索引 -1 大改) + **加载器守卫跳过**: 加载循环里 `if not cands and "结构条件" in nm and "·" not in nm: continue` (无布局位置且是共享定义→不创建)。edges 用定义索引引用, 行级新定义追加在 node_specs 末尾 (索引 58-62), 加载时 index→id 映射自动对应。
- 布局列距 = `base_x + c * 200` (120 起); 断言位置先算列: 列4 = 120+4*200=920, 别用 520 猜。

## 多会话协作（飞书端/其他会话改同一文件）— 对账流程
Z-MAX 有多个会话（CLI + 飞书 gateway）会改同一份本地代码，症状: 用户"飞书端说改了，我没看到"。
- **根因**: 另一会话改了本地文件但**未 git 提交 + GUI 未重启**（画布还是旧代码）
- **「代码里明明是 X, 界面还是 Y」= 先证进程比改动旧, 再谈第二遍改代码**: `ps -o lstart= -p <pid>` 与 `stat -c %y <改的文件>` 一比 —— 启动时间早于文件 mtime 就结案 (Python 启动即把源码读进内存, 改文件对活进程零影响)。同时 `grep -n "<符号>" <file>` 把**处理器里的那一行**和**启动默认那一行**分开数清: 用户常把"点按钮时的 `set_collapsed(True)`"误读成"启动默认就是 True", 这两处行号必须都报给他。
- 对账: `git status --short tools/gui/` 查未提交改动 → 检查关键注册（类型表/icon 字典/node_logic）完整性 → 补全后**重启 GUI** 才生效
- 外部会话产物（训练目录 act_peg_overlay 等）先 `ls -t outputs/train/` 确认，别动其进行中的训练

## auto_restart 守护进程（kill -9 后自动复活）
- 场景: studio.py 父进程链指向 Hermes gateway（`hermes_cli.main gateway run`）拉起的 bash 守护（`/bin/bash -lic "set +m; cd ... && python3 studio.py > /tmp/studio_restart*.log"`），检测到 GUI 退出就自动拉起
- **kill -9 GUI 后 2 秒内出现新 PID = 守护在拉**；要彻底停: 先杀守护 bash（`ps -o ppid` 沿父链找），再杀 GUI
- **pkill -f 自杀陷阱**: `pkill -f 'studio.py'` 会匹配**调用 shell 自身的命令行**（ps 参数含该字符串）→ 终端进程被自己杀掉（exit -9）。先 `pgrep -f` 列出 PID 再 `kill -9 <pid>` 逐个杀
- 多实例重复: 旧实例 + 守护拉的新实例并存 → 先全杀再手动起一个干净的（gateway 432 保持存活，别误杀）

## xdotool 窗口操作（WSLg，清理多弹窗/定位窗口）
- 装: `sudo apt-get install -y xdotool`（WSLg 可用）
- 枚举窗口: `DISPLAY=:0 xdotool search "" | while read w; do xdotool getwindowname $w; done`（找标题）
- 关多开的弹窗（2026-08-08 实测 "7 模型 rollout 对比" 开了 8 个）: 按标题匹配 `case "$t" in *"rollout 对比"*) xdotool windowkill $w;; esac`
- **盲点坐标点击不可靠**（找不到控件坐标，点导航/按钮常点空）——老倪要求"操作窗口按钮"时，优先走 GUI 内部触发（`.click()`/信号注入）或让用户点；xdotool 只用于清窗口/激活（`windowactivate`）

## GUI 行为原则
- 小面板/密集控件: 字体用 `setPixelSize`(见 §15), 挂载点选 central 布局而非 QStatusBar(见 §16)
- 打开视图**永远先显示历史数据**（视频/曲线），新 checkpoint 只提示不自动重生成（白屏根治）
- 外部进程（非 GUI 启动的训练）状态监视: `pgrep -f lerobot_train` + 最新输出目录 ckpt 步数 + config steps → 显示 `训练中: <dir> · 步 N/M (P%)`；去重（状态变化才 append）；结束提示一次

## 相关
- 打包分发/Windows exe CI 见 `pyqt5-distribution`；Z-MAX 控制台项目维护见 `zmax-console`（用户技能）
- 会话案例细节: `references/session-cases.md`
