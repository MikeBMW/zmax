# 数据空间视图 (dds_canoe.BusView) 顶部搜索 —— 全文

- 位置: 顶栏(测量组)最右端 = `ed_find` + `lb_find`, 按名筛**信号表**(报文/信号/节点)三组, 不是 Trace(Trace 另有 `ed_search` 只筛帧)。
- 坑①: 清空搜索时**必须递归取消 hidden**(`_unhide_all`, 根+叶子一起); 只把根 un-hide 会出现“组标题出来了、叶子还藏着”。
- 坑②: 信号表会被 `reload(force_tree=True)`(「只看活报文」勾选/刷新钮)整棵重建 ⇒ 重建函数末尾必须再调一次筛选, 否则用户打了一半的词白打。
- 坑③: 可搜文本 = 各列文字 + tooltip + column0 的 `Qt.UserRole`(话题 key/类型常藏在里面) ⇒ `ss_plan` / `zmax/ss_plan` / `zmax::SSPlan` 三种写法都能命中。
- 无 GUI 环境验证: `QT_QPA_PLATFORM=offscreen` + `gui-venv311/bin/python` 起 `build_view(None, standalone=True)`, 显式 `v.reload(force_tree=True)` 再跑 1.8s 事件循环后树才建出来(只 processEvents() 得 0 条)。
- 数据空间里的名字对照: MoveIt 规划输出 = `ss_plan`(`zmax/ss_plan`, `zmax::SSPlan`); 状态空间引擎动作 = `ss_action`; 搜 `moveit` 还能命中画布节点「🧭 MoveIt 运动规划 · SDK 直驱桥(Orin)」与连线信号。
- 🔴 **两个搜索框必须联动(2026-10-01 现场事故)**: 老倪报「我搜索 plan 了, 什么都没有」——
  子智能体看**现场截图**才发现: 他把关键词打在**顶部全局框**(`ed_find`), Trace 自己的框(`ed_search`)是空的,
  状态栏当时写着「过滤 关」= 铁证。**症状是"没反应", 不是"没数据"**(Trace 10 行满着, `ss_plan` 就在里面)。
  ⇒ 修法: `_apply_find` 里同步 `self._filter` + `_fill_trace(force=True)`(两框等效) + 标签区分
  (「🔎 搜索 (信号表 + Trace 置顶)」vs「📌 Trace 置顶: 输入话题」)。
  **纪律: 用户报"搜了/点了没反应"先抓屏看他真实操作的位置, 别按自己以为的那个入口改;**
  同一界面多处搜索/入口, 要么联动要么标签明确到不会认错。
- 🐛 **`_fill_trace` 的"签名没变就 return"性能优化会吃掉搜索**: 搜索必须 `_fill_trace(force=True)`,
  否则 1 秒内刚填过 ⇒ 打字搜索**根本不重填** (表现就是"搜了没反应")。任何"用户输入驱动"的刷新一律 force。
- 🐛 **值列/固定行自己取数, 不依赖 `self._live` 被喂过**: 冷启动/离屏时 `self._live` 为空 ⇒
  实时值列退化成 digest 的「全缺测(-1)」(digest 是截断 JSON)。新增 `_live_doc()/_live_topics()/_live_fields()`
  直读 `live.json`(1s 缓存)。另: **显示真实数值一律用 `_f3()` 纯格式化**, 别用 `_num()` —— 后者把负值当"缺测"返回 `—`,
  会吃掉 `-0.233` 这种完全正常的坐标。
- 📌 **Trace 默认「固定行」模式(老倪 2026-10-01「滚动看着太累, 默认不滚动」)**: 一行一个话题、位置不动、
  只有 Time(测量时间)+实时值在变; 值刚变化=绿/未变=灰; 列序固定 `Time|Name|实时值|分类|hz 实测/设计|count|帧龄|QoS|lamp|备注`;
  工具条 `📌 固定行 ⇄ ▶ 滚动` 可切(滚动模式=原帧流, 表头随模式切换)。搜索命中话题**置顶+整行高亮**, 搜索框边缘报命中数(绿/红)。

> 📌 refs: veh-id-system,ssh-remote-gpu,config-center-excel,relay-middleware,simulink-id-and-skill-tokens,wsl-display-links,simulink-flow-json,gui-navigation,devflow-panel-pdf-2026-08-15,gui-debug-and-crash-forensics
> 🐛 「断点进不去」不是代码没跑: 先 `ss -ltnp | grep 5678` —— **无监听 = 控制台是非调试模式**(studio.py 只在 `ZMAX_DEBUG=1` 时 listen), 要用 `ZMAX_DEBUG=1` 起或 F5「🚀 全新调试进程」;
> 再确认节点"逐行执行"链 `_trace_exec` 的 `sys.settrace` 没顶掉调试器(`debugpy.is_client_connected()` 为假时它会装 —— 判据必须在**执行过程中**读 `sys.gettrace()`, 返回后再读被 finally 清成 None)。
> 📸 **从整屏截图里裁「某个 CSD 窗口」时, 别信 `wmctrl -lG` 的 y —— 先用 `_NET_FRAME_EXTENTS` 核**:
> 本机 mutter 是 CSD(阴影+标题栏由应用画), 实测 `_NET_FRAME_EXTENTS = 0,0,74,0` —— 拿错误的 y 去裁,
> 会把窗口**顶部一整条(含测量条/标题)切掉、底部却多收一段背景**, 子代理会据此报「窗口没有 Start/Stop、
> 底部是个半成品空盒」这种**不存在的问题**。做法: 裁完先验一下顶部该有的特征物(如 C_YELLOW 的
> Start 按钮像素数 > 0、非背景占比 > 15%), 否则先修裁切偏移再下结论。
>
> 🪟 **独立窗口一律用「无 parent 的 QMainWindow + 显式 MinMaxClose」, 不要用 `QDialog(父窗口)`**:
> `QDialog(父窗口)` 在 mutter 下是**附属窗(transient)** ⇒ 标题栏最大化钮灰着/点不动
> (老倪 2026-09-29「独立打开的全局数据空间的最大化按钮不好用」)。验法: `xprop -id <wid> _NET_WM_ALLOWED_ACTIONS`
> 必须含 `_NET_WM_ACTION_MAXIMIZE_HORZ|VERT`, `_NET_WM_WINDOW_TYPE` 应为 `_NET_WM_WINDOW_TYPE_NORMAL`。
> 深色主题不会丢 —— `app.setStyleSheet` 是**应用级** QSS, 与 parent 无关; 无 parent 窗要自己留引用
> (防 GC) + `app.aboutToQuit.connect(w.close)` 防孤儿窗。
> ⚠️ 本机 fractional scaling 下 `move()/resize()` 与 `screen().geometry()` **不在同一坐标空间**
> (按 0.56×屏宽算出的窗实测大到出屏) ⇒ 摆位一律在 `show()` 后用**真实 frameGeometry** 夹回, 不靠推算。
>
> 💥 崩溃(窗口消失/Aborted)的取证清单、QThread 自查点: 见 `references/gui-debug-and-crash-forensics.md`。
> 🎛️ **仪表盘/图形化表达(圆环·状态条·指示灯)、独立窗口多视图、CANoe 三窗格数据空间、192DPI 自绘取证**: 见 `references/console-dashboard-widgets.md`。
> 🕳 工具栏/面板「中间一大块空白」的**第一诊断 = 量那块矩形的亮像素数**(亮度>90 的像素为 **0** ⇒ 控件在但看不见, 不是缺控件): Qt 给 `QCheckBox`/`QRadioButton` 的默认字色是**黑**, 画在深色工具条上对比度 ≈1.1:1 —— 全局深色 QSS 会覆盖 QPushButton 的背景却常常不碰 QCheckBox 的字色(mk_btn 那套浅色配方看着"没生效"就是这个原因)。修法 = 给每个勾选框显式深色 pill 样式(`background:#14181f;border:1px solid #30363d`, **padding 与按钮一致**才等高, 勾选态绿字 + 绿指示块), 改完复测该区亮像素: 实测 0 → 17258。
> 老倪铁律: 硬件/资源类卡片**少堆文字** —— 数值用 圆环/状态条/指示灯 表达, 原文退到 tooltip + 「📋 复制参数」按钮(他要可复制的纯文本); 缺测显示 "—", 数据源不通必须点红/灰灯, 不能还是绿灯。
> 🐌 **2026-09-29 老倪「全局数据空间怎么阻塞了」= 表格 `ResizeToContents` 逐格量列宽**(v5.16.22):
> ① **根因不在 fill 函数里**: 新页带了 1.5s 自刷新, 逐函数计时只看到 `_fill_trace` 2ms/整轮 11ms, 但进程 `ps` 实测 **81.7% CPU**。真开销是 **`QHeaderView.ResizeToContents`** —— 单元格一变就为**每一列逐格重新测量文字宽度**(192DPI 下 9 列×150 行), 而且算在**事件循环**里(不在调用栈里, 所以计时看不见)。
> ② **定位手法(可复用)**: `resource.getrusage(RUSAGE_SELF)` 量 CPU + **分组停 QTimer 做 bisect**: 基线 83% → 只停该页定时器 **3%**(其余页定时器各 0%) → 确认就是这一处; 再换成显式列宽 → **5%**。停定时器的清单 `widget.findChildren(QTimer)` + `isActive()/stop()`。
> ③ **规矩**: 高频自刷新的表 **一律不用 `ResizeToContents`**, 改 `Interactive` + 显式宽度(名字列才用 `Stretch`); 再加三道闸: `if not self.isVisible(): return`(不在看的页不刷)、文件(体积,mtime)签名没变就整轮跳过、只读文件尾部(不 `readlines()` 整个文件) + 行数封顶。
> ④ **验收要看两件事**: 现场 `/proc/<pid>/stat` 前后采样算实时 CPU(修后 ~0-5%), 且**两帧截图对比像素必须仍在变**(证明不是“不刷了”假好): 实测测量条 1025px/Trace 35847px 在变 = 数据真在走而 CPU 没烧。
> 🌐 2026-09-29 老倪「全局数据空间 参考 portal.vector.com/de/web/help/canoe-demo 重新设计UI」= 该页从「12 个 Tab 堆叠」改成 **CANoe 主窗口范式**(v5.16.16→v5.16.18; 新模块 `tools/gui/dds_canoe.py` 的 `build_view(main_win)`):
> ① **CANoe 的范式是「多窗格同时在线」**(官方截图逐像素实测: 顶部功能区 + 上排左 Scene Window ~41% ｜上排右 Data ~57% + **下 Trace 整宽** + 底部 Configuration|Measurement|Data Window 页签), 不是「把功能切成 Tab」⇒ 照抄骨架比照抄配色重要。
> ② 映射: 测量组(⚡Start 黄 / ⬢Stop 灰 / ↺) ｜ **Data 面板列名照抄** Name|Value|Unit|**Last Value Time [s]**|**Bar**(实心蓝条=实测/设计, 自绘 `BarDelegate` 按 `Qt.UserRole` 比例画在单元格里) ｜ **Trace 整宽** 9 列 Time|Name|Object Type|Classification|Probability [%]|Sender Name|Sender Id|Tracking Id|Group, Time 用「相对测量起点 3 位小数」, Δt 切「与同话题上一帧之差」。
> ③ 数据全真: `busdb.json`(画布导出的 DBC: 74 节点/182 信号/14 报文) + `live.json`(每话题 hz/丢包/jitter/帧龄/rules/灯) + `trace.jsonl` + `loop.json`; 缺测一律 `—`; **旧页面零丢失** = 右上「🗂 经典视图」开关(两套控件都在内存, `main._canoe_classic_cb` 切显隐)。
> ④ vision 质检实测出的 UI 通病: **不要用「整行改灰前景」做斑马纹**(半张表像褪色, 6.7:1 vs 18:1) → 改浅底; Qt 列头默认**居中**而单元格左对齐 ⇒ 列头比内容右移 32-42px, 要 `setDefaultAlignment(Qt.AlignLeft)`; 等宽对齐文本**中文按 2 列宽算**才算得齐(自写 `_pad()`), `%-14s` 对中文无效; 暗灰 `#484f58` 对比度 2.3:1 几乎看不见 → `#6e7681`; 同一规则+同文本的告警会重复渲染 ⇒ 三元组去重。
> ⑤ 验证口径: 离屏 `QT_FONT_DPI=192 QT_QPA_PLATFORM=offscreen` + **先 `cv._timer.stop()` 再测**(1s 自刷新定时器在 processEvents 循环里反复重建 500 行表, 探针表现得像「卡死」); 判据 = 树空文本行 0 / 各填充步骤 ≤0.01s / Trace 变灰列数 0 / 截图出图 / 页面宽==视口宽。
> 🔎 **「某节点的输出是哪个 topic?」(以及「哪个 topic 是 MoveIt 的输出 action」一类问法) = 三件一起查再答**:
> ① 设计态 `busdb.json` 的 `signals[]` —— `src`==该节点的那条连线的 `topic` 字段(全图连线走**同一条** `zmax/link_value`,
> 信号身份 = `(src, port)`; `dds_link_bus.py` 注释里的 `zmax/link/<node_id>` 是旧设计, 别照它答);
> ② 实测态 `live.json` —— **`hz=-1` = 本档没在发**(不是坏了); ③ 内容 `trace.jsonl` 的 `digest`;
> 最后再补一句上游那一级(如 MoveIt 本体)此刻有没有在跑 —— MoveIt2 的输出接口是 ROS2 **服务**
> `/plan_kinematic_path`(非 DDS 话题), `docker ps`/`pgrep -af move_group` 空就是没起。
> 键名坑(`live.json` 短名 vs `trace.jsonl` 全路径 ⇒ 按话题 join 的列全「—」) 与独立窗「🌐 数据空间窗口」(`ds_win`) 见
> `references/dataspace-dds-tab-2026-09-29.md`。
> 🖥 **硬件/状态仪表盘页**: 用户口径 = 「不要用那么多文字来表达, 换成状态条 / 圆环百分比 / 红绿灯指示灯」(参考 CANoe hardware · Vector Hardware Manager 的集中式设备面板) ⇒
> ① **实现形态**: 自绘控件模块 `tools/gui/hw_widgets.py` —— `Ring`(轨道圆 + 12 点顺时针弧 + 环内大号数值 + 环下短标题) · `StatBar`(名称 + 圆角条 + **底槽** + 右对齐数值) · `Lamp`(发光圆点 + 名称 + 一行小字) · `HwVisual`(装配: 设备灯带 → 圆环行 → 状态条行)。`HardwareCard` 的旧文字标签**保留但 `setVisible(False)`** —— 采集线程照旧更新它们, 只用于 tooltip 与「📋 复制参数」; 版面全交给控件。
> ② **数据通道与显示通道必须分开**: 采集线程 `_collect()` 除 HTML 文本字典外再挂一份**数值载荷** `out["_metrics"] = {"local": {...}, "devices": [...], "remote_src"|"remote_src_off": ...}`, GUI 线程 `refresh()` 推给 `HwVisual.set_data()`。**绝不让可视化控件去解析/正则 HTML**。
> ③ **排序本身就是需求**: 「4060/本机」要沉到**灯带最右**, 整卡也移到首页**最底**并加节标题(与「功能模块/项目状态」同规格)。灯带每次 `set_data` 用 `insertWidget(i, lamp)` **重插已有灯**(只插新灯 ⇒ 旧灯卡在旧位次); 同一台机既出现在本机指标又出现在 DDS 节点列表时**合并成一盏灯**(按显卡名认), 否则用户看到"一台机两盏灯"。
> ④ **阈值按物理语义, 不是"越大越红"**: 显存/CPU/内存 <80 绿 · 80-92 黄 · >92 红; 磁盘 <80/80/90; 温度 <70/70/82; **GPU 利用率反着来** —— 空闲(<5%)灰 · 训练中 <50% **判黄**(掉载口径) · 其余绿。
> ⑤ **不许编造量纲**: 状态条的分母必须是真实量 —— 功耗条用 `nvidia-smi --query-gpu=power.limit`; 读不到就**只显数字不画条**(拿"本次观测峰值"当分母会让空载满格, 反而误导); 无训练时吞吐显示 `—`; 缺测一律 `—` 不用 0 冒充; 数据源不可达要亮**"未连通"红灯** —— 否则整卡全绿看不出是占位/过期数据。
> ⑥ **自绘仪表盘做完必过一次 vision 逐像素质检**(两张图: 控件本体 + 整页), 高频真缺陷与修法清单见 `references/ui-visual-qa-defect-classes.md`。
> ⑦ **现场验收口径**: 重启后 `wmctrl -lG` 的窗口标题必须带**新版本号**(不带 = 起的是旧码), 再 `ffmpeg -f x11grab -video_size 3068x1862 -i :0.0+132,212` 抓图, 并用 PIL 抽检**控件特征色像素数**(环轨 #30363d / 条与灯 #3fb950 / Bar #2f81f7 > 0) ⇒ 才算证明"画到屏上了", 不是只存在于离屏脚本里。
> 🛑 2026-09-28 老倪两次问「控制台怎么自己重启呢」——查证: 控制台**本身没有自启机制**
> (systemd 用户单元 zmax-studio.service 是 Restart=no, 退出后一直 dead; crontab 11 条没一条碰它),
> 是 **agent 改完 GUI 代码就重启它** ⇒ 现场只看到窗口闪来闪去。
> 🪟 2026-09-29 夜 「窗口没显示完全」的**出屏判定**(双屏 3200x2000@0,0 + 3840x2160@3200,0 ⇒ X 虚拟屏 7040x2160, 主屏只可见 y<2000):
> ① WM「最大化」按**跨屏工作区**算 ⇒ 窗口可大部落在主屏可见线外(实测 3068x1862@132,212, 底边 2074 ⇒ 最底一行版本提示/跑马灯永久看不见)。
> ② **不能只看 `frameGeometry()`**: mutter 给每个窗口配一个 `mutter-x11-frames` 外框窗口(实测 3124x1994@104,40), **CSD 外框/阴影不计入应用自报几何** ⇒ 应用自报「刚好贴屏底 1992」时真实外框已到 2034。判定交叉核对 `xdotool getwindowgeometry <win>` + `xdotool getwindowpid <win>`(用它认领外框窗, **别当成第二个控制台实例**) + `wmctrl -lG`。
> ③ **主屏可见线以下(y≥2000)的 framebuffer 可能是陈旧的** —— X 不重绘没被任何显示器显示的区域 ⇒ 在那块拍到控制台配色 **≠** 内容被切(重启后重拍才算证)。
> ④ 修法: `_fit_window_to_screen()` 里**最大化也要查越界**(越界先 `showNormal()` 再夹), 纵向预算再留 **48px** 安全边(宁矮不切)。
> ⑤ QLabel + `wordWrap` 在 QVBoxLayout 里会被按 sizeHint 估算**压扁**(实测组件行需 374px 只给 243px ⇒ 尾行整行看不见): 布局跑完后按**实际宽度**复算 `heightForWidth` 并锁最小高, 两遍收敛。
> 🎨🔴 2026-09-29 晚 老倪「(主界面)功能模块太宽了, 不协调; 不要下面的横向拉条。修改, 不要那么宽」= **真实根因在 HardwareCard, 不在模块网格** (v5.16.12→v5.16.13):
> ① **量口径(先量再改)**: 验 UI 宽度只看 `QScrollArea` 的 **`page.width()` vs `viewport.width()`** + `horizontalScrollBar().maximum()`。实测 `page=5542 / viewport=3052` = **1.82×** ⇒ ①底部必有横条 ②网格按 page 宽等分 ⇒ 每张卡 1752~1795px(设计 260), 卡内文字只占左侧 ~320px、右边全空 = 用户说的"太宽/不协调"。
> ② **元凶**: `HardwareCard` 里 24~28px 富文本标签 **没开 wordWrap** ⇒ 单个标签 `minimumSizeHint` 5428px 就把**整页最小宽**顶到 5542(`lb_remote` 最大, 其次 `lb_gpu` 1804 / `lb_nodes` 1051)。**任何超长文本 QLabel 都能把整页撑宽** ⇒ 首页/子页动态标签一律 `setWordWrap(True)` + `setMinimumWidth(1)`。
> ③ 模块侧: `ReflowCardRow(max_card_w=470)`(超上限按上限给宽 + 整行居中留白) + 分组框再套一层 `ReflowCardRow(min_card_w=900, max_cols=2)`; 每次 reflow 先清**历史列**的拉伸/最小宽(`setColumnStretch/MinimumWidth(0)`), 否则留下看不见的空列把卡片推开。
> ④ **别在 offscreen 单测里判 UI 宽度**: 硬件卡是**后台线程 2s 后**才把长文本贴进标签 —— 离屏探针不 `processEvents()+sleep 等到采集落地` 就量, 得到 `最小宽 2459` 是**假的**(现场 5542)。必须 `QT_FONT_DPI=192` + 等采集 + 跑整窗冒烟。
> ⑤ API 坑: **Qt 的 8 位 hex 是 `#AARRGGBB`**(不是 CSS 的 `#RRGGBBAA`) ⇒ `f"{color}55"` 变成"alpha=0x58 + 黄绿"(老倪: "卡片标签怎么是绿底")。半透明一律写 `rgba(r,g,b,a)`(`rgba_of()`)。修前角像素 `#a4ff54` → 修后 `#304e76`(= 0.33×#58a6ff + 0.67×卡底, 逐层色同样吻合)。
> ⑥ 改完必跑(探针已归档 `release_archive/v5.16.13_20260929/src/probes/`): `card_text_check2.py`(按 `TextWordWrap` 复算每个标签需要的宽/高, **溢出 0** 才算过) + `studio_smoke.py`(整窗 + 11 页切换异常 0) + 修后截图量 **`页面宽 == 视口宽` 且 `横条 max==0`**。
> 🎨 2026-09-29 老倪「窗口没显示完全 + 没有横向拖动的拖动条 + 方框里字被遮挡」= **UI 五条真根因与修法** (v5.16.5):
> ① **横向条被永远关掉**(最直接的根因): 三处 `QScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` ⇒ 内容一宽过窗口就既看不到右边、也没有横向拖动条。改 `AsNeeded`(0)。
> ② **滚动条 QSS 必须挂 widget 级**: 只改全局 `app.setStyleSheet(_build_global_qss())` 会被页面级/控件级样式表压掉 —— 实测"改了全局 QSS 但像素一点没变"。用**附加**写法 `scroll.setStyleSheet("QScrollArea{border:none;}" + SCROLLBAR_QSS)`(studio.py 常量), 画布 view 单独 `setStyleSheet(simulink_module.CANVAS_SCROLLBAR_QSS)`。验收判据 = 截图右缘**蓝色列数**: 修前 0(只剩两条灰线) → 修后 16 列(16px 蓝手柄 #4d8fdb)。
> ③ **色带(row_bg, 老倪说的"方框")名字被截 = 名字区宽度算错**: 原取**全画布**最小节点 x(本画布=0) ⇒ 每条色带名字区都被压到下限 80px ⇒ 15/15 全部省略号。必须按**本条色带内**的节点算(节点中心 y 落在本带 y..y+h 内) ⇒ 80px → 284~11070px, 实测 15/15 → 0/15。
> ④ **节点字多 = 换显示名, 不是缩字** (✅ v5.16.6 定稿): 数据名平均 18.7 字(最长 41) ⇒ 两行还挤。改 `node_display_name()` 为**字数预算制**: 预算 **10 字** = 每个中文字 1 字 + 每个西文/数字词 1 字 (`Transformer`/`ACT`/`43D` 各算 1 字), 取值优先级 = 原名≤10字**原样保留(连括号)** → 去括号补充(≥5 字才用) → 人工短名表 `NODE_CORE_LABELS`(43 条, 权威 5~10 字) → 按词裁剪(≥5 字); 另加**单行像素预算 300px** (超了就只能折行) 与**括号保护** `(?<![A-Za-z0-9])[（(【\[〔]` (否则 `SU(2)`/`D064` 这类技术记号里的括号会被当补充说明删掉)。图标(emoji/①②/◉)不计字数, 自动带在标签前。配 `autofit_node_size()` (按最终标签撑宽/长高)。
> 🔴🔴 **“字只显示一半”的第一个该查的东西 = 屏幕 DPI, 不是文字长度** (v5.16.8 实测根因): 本机桌面 `xrdb -query | grep Xft.dpi` = **192** (2x), 而节点排版常量是按 1x 字形设计的 (标题行 20px / 副行 16px / radio 格 48px) ⇒ `QFont(族, pt)` 现场字形是设计值的 **~1.93 倍** (同一句“抗干扰”: 离屏 42px → 现场 81px; 行高 22→40) ⇒ 行叠字、末字被框边切掉。
> • 修法: 画布文字一律 `QFont(fam)` + `setPixelSize(...)` (**不做 pt**), 排版常量不变 ⇒ 现场 = 离屏 = 审计三边一致。字号倍率要**扫**出来: `ZMAX_NODE_PX_SCALE` 1.15 通过 / 1.30 互压 / 1.45 越框。
> • **审计必须在“现场口径”也执行一遍**: `DISPLAY=:0 QT_QPA_PLATFORM=xcb` vs `QT_QPA_PLATFORM=offscreen` (后者不读 Xft.dpi → 永远 1x → **必然假通过**)。只要两种口径结果不一样, 就是这类 DPI 坑。
> • 画布里别再用 `QFont("Arial", 9)`/`QFont("Consolas", 9)`: 本机两个字体**都不存在** (Arial→Liberation 只有西文字形 → 中文逐字回退; Consolas→回退), 用 `_node_font()`/`_node_mono()`。
> • **运行期文本**是第二个病灶 (静态扫不出来): `str(x)[:64]` 只截**字数** —— 64 个中文字 ≈ 850px 塞进 406px 的框, 而 `drawText(QRectF,…)` 的矩形**不裁剪** ⇒ 直画到框外/压邻居。统一走 `_fit_text()` (按框宽 elide + 全串进 tooltip)。自查: `scripts/node_runtime_text_check.py` (把 l5_lines 塞满长中文/报错串后复检)。
> • 🐛 **`QFontMetrics.elidedText` 的宽度必须 `int`**: 传 float 会 `TypeError`, 被 `except Exception` 吞掉 → **静默退回“不省略”**(看上去像没修)。本文件 356 行已记过, 又踩了一次 —— 写完 elide 后一定要 assert 返回值宽度 ≤ 预算。
> ⛔ **别用“按分隔符从前往后取前缀”** (v5.16.5 的做法, 已废): 它把「🏆 L4 · 工作安全 + 物理世界导航」砍成「L4」——**层号是分类不是功能**, 老倪一句「怎么只是剩下 L4」打回。判据 = 标签字数 ≤10 且 ≥5 且不得只剩 `L[1-5]`。
> 🔍 **“字太多/太挤/看不清”是另一个毛病, 用代理画笔查** (v5.16.7): `scripts/node_text_audit.py` —— 包一个 `AuditPainter` 转发 set*/draw*, 只拦 `drawText(qrect, flags, text)`, 逐条判三件事: ①文字宽 > 绘制矩形宽 (=会被裁/挤) ②文字矩形画到方框外 ③两块**贴合文字**的矩形互压(大容器矩形要排除, 否则一团假阳性)。实测全 flow 1025 个节点修前 91 处 → 修后 4 个 0。
> 🐛 该体检抓到的三类**真**毛病 (改文字之外记得顺手查这三处): (a) 小按钮里预先固定长文案 (📥导出 34px 按钮装 43px 字) → 按钮加宽 + `elidedText`; (b) 色带标题绘制矩形按“带内节点最小 x”算会比**色带自身宽**还大 → 绘制矩形必须 `min(_aw, self.w-16)`; (c) 色带 `paint` 用 `node.get("h", 244)` 而 `__init__` 里是 `node.get("h", DH=110)` ⇒ 没写 `h` 的色带画出来高 134px、标题跑到框下面 —— **paint 一律用 `self.w/self.h`**, 不要另取一个默认值。
> 🎛 **带自绘控件的节点** (如“能力档位” radio): 标题别预先固定长句(尤其别用 `QFont("Arial")` —— 本机无该字体, 中文逐字回退→宽窄不一), 走 `node_display_name` 拿短标签 + 统一字体; 详细说明进 tooltip; 每个 radio 子标签先量 `QFontMetrics.horizontalAdvance` 再画 (放不下就不画, 宁少勿挤)。
> 自检命令 (26 个 flow / 1107 个标签, 三个“0”才算过): 超 10 字 = 0 · 超 300px = 0 · 只剩层号 = 0; 同口径看收益用 `scripts/node_text_before_after.py`。
> ⑤ **「窗口没显示完全」先量再改, 别急着改尺寸**: `xwininfo -root -children` **看 frame 那一行**(GNOME mutter 会 reparent, 客户窗几何带偏移会骗人) + `wmctrl -m`; 实测老倪窗口 `_NET_WM_STATE_MAXIMIZED_*`, frame 3068x1936+132+64 = **正好铺满 3200x2000** ⇒ 窗口没出屏, 是**内容**宽过视口 + 条被关掉。仍保留 `_fit_window_to_screen()` 保障(尺寸+位置双夹紧进 availableGeometry, 留 8px 边距; 启动与 show 后各一次; 记 `/tmp/studio_show_diag.log`)+ 菜单「🖥 窗口适配屏幕」。
> ⑥ **改完画布渲染必须逐个跑真 `paint()`**: paint 里抛异常 = Qt **直接 abort 整个 GUI**(不是打印异常)。探针见 `scripts/canvas_node_render_selfcheck.py`(造 nodes/links shim + QImage 逐节点 paint, 断言"异常 0 / 标题截断 0"), 收益对照用 `scripts/node_text_before_after.py`(两边各走自己的 autofit = 同口径)。
> 📌 改完照例: `tools/bump_version.py --to X.Y.Z --summary-file ...`(7 处版本号 + VERSION.md 表首, 工具会回读校验) → `git commit` → `git push origin main`。
>: 单元是 `enabled`(WantedBy=default.target)
> ⇒ **图形会话一进就会自动弹一个控制台**(只是 Restart=no, 所以关了不会自己弹回来)。
> 老倪开机看到的是 **v5.15.13 旧版**, 根因 = 单元里 `WorkingDirectory/ExecStart` 还硬编码在**共享检出**
> `/home/ubuntu/lerobot-smolvla-lew`(被并行线切到 mac-hw ⇒ 那边 GUI 停在 v5.15.13), 唯一依据是 worktree
> `/home/ubuntu/zmax_rel`(v5.16.4)。桌面图标 09-26 已改成按脚本位置推仓库根, **只有这个 systemd 单元没跟上**。
> 纪律: **凡"开机自启/常驻"入口一律指 worktree** —— 现在 `ExecStart=/home/ubuntu/zmax_rel/tools/gui/launch_studio.sh`
> (自带 worktree 优先 / DBUS 会话总线补全 / 已有实例去重激活); 改完必 `systemctl --user daemon-reload` 并回读
> `systemctl --user show zmax-studio.service -p ExecStart -p WorkingDirectory`。
> 排查「界面怎么是旧版」: 两个检出各查一次 `grep -m1 CURRENT_VERSION <检出>/tools/gui/update_checker.py`,
> 再对 `pgrep -af studio.py` 的 cwd (`readlink /proc/<pid>/cwd`) —— 界面版本 = 那个 cwd 的代码版本。
> 纪律: **改 GUI 代码攒成一批, 重启前先问老倪**; 确需重启走 `bash tools/studio_ctl.sh restart --force`
> (起不到 300s 的实例会被硬闸拒, 退出码 3), 每次动作记 /tmp/studio_ctl.log 可追谁在重启。
> 🔁 **老倪授权「你自己重启」时**(他有时就直接这么派), 从**非桌面 shell**手工拉起的正确姿势:
> ① 优先 `bash tools/studio_ctl.sh restart --force`(有硬闸 + 日志);
> ② 手工拉起**必须继承原进程的 DISPLAY/XAUTHORITY/WAYLAND_DISPLAY/XDG_RUNTIME_DIR** ——
>    在无 DISPLAY 的 agent shell 里直接 `python studio.py &` ⇒ 窗口根本不出现(看起来像"重启了但没反应"):
>    `PID=$(pgrep -f "tools/gui/studio.py"|head -1)` → `tr '\0' ' ' </proc/$PID/cmdline >/tmp/studio_cmd.txt` ·
>    `readlink /proc/$PID/cwd` · `tr '\0' '\n' </proc/$PID/environ | grep -E '^(DISPLAY|XAUTHORITY|XDG_RUNTIME_DIR|WAYLAND_DISPLAY)='`
>    → `kill -9 $PID`(**显式 PID**; 绝不 `pkill -f studio.py` —— 会连自己那条同名命令行一起杀)
>    → `cd <原 cwd>` + `set -a; . <env文件>; set +a` + `exec $(cat /tmp/studio_cmd.txt)`
>    (用 `exec` 承接, 父 shell 一退窗口跟着消失)。
> ③ 验收三件(缺一不算重启成功): `pgrep -af "tools/gui/studio.py"` 有进程 ·
>    `/tmp/studio_launch.log` 与 `/tmp/simulink_log.txt` 的 `Traceback` 计数 **0** ·
>    `/tmp/simulink_log.txt` 出现 `已加载工作流: …flows/state_space_obs.json (N节点 M连线)`(N/M 要与唯一依据一致),
>    再 `DISPLAY=<原显示> xdotool search --name "Z-MAX"` 能找到窗口(证明不是后台僵尸)。
> ④ 画布离屏加载要几十秒 ⇒ **重启后先等 60~90s 再判定**, 这期间点按钮什么都不会发生。
> 🔌 另: 关机/kill 走 SIGTERM —— 老版本会 "QThread: Destroyed while thread is still running" → SIGABRT + core dump;
> 现 studio.py main() 用 `signal.set_wakeup_fd` + 看门狗线程 + QTimer → win.close() → os._exit(0) 干净退
> ⚠️ 这句只覆盖 kill/关机路径 —— **无信号时也会出现同一组签名**(实测日志里「收到信号」0 条, 仍 `QThread: Destroyed while thread is still running` + `Fatal Python error: Aborted`)
> ⇒ 见到这组话别默认归因 kill: 按 `references/gui-debug-and-crash-forensics.md` 的清单逐条排除后再定性。
> (⚠️ 用普通 `signal.signal(SIGTERM, py_handler)` **无效**: 主线程在 Qt 的 C++ 循环里, 处理器根本跑不到)。
> ⚠️纪律: 只patch改; kill-9重启(pkill 用 "gui-venv311/bin/python studio" 别用 studio.py, 会打死 Hermes 自己的 shell); --gpus all本地/--runtime nvidia远程; -o Port; 主线程禁网络请求(摄像头坑); 启动/黑屏见 launch-guide.md; 训练入口/状态见 gui-navigation.md; 控件小/字挤/面板窄见 ui-sizing-hidpi.md; refs: gui-discipline, simulink-flow-and-buttons, simulink-flow-authoring, help-menu-doc-open
> 🔖 版本迭代/发布归档 → `references/release-version-bump.md` (**bump 先 `--dry`, 任一行 ❌/`旧命中 0` = 历史漏同步, 先补齐再写盘**; 含「保存数据」现场批次归档目录模式)
> 🔖 重启/启动崩溃排查/无显示离线取证 → `references/gui-restart-and-offscreen-verify.md` (launch_studio.sh 已有实例时 exit 0 不干活; `QT_QPA_PLATFORM=offscreen` 起真类调真方法)
