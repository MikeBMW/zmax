---
name: zmax-console
title: "Z-MAX Console"
description: "Maintain PyQt5 GUI studio.py: version, Docker, backup, docs sync, PPT engine, auto-update."
trigger: "Use when the user mentions '控制台', 'Console', '远程GUI', '迭代控制台', or 'studio.py' — PyQt5 desktop, NOT web console.html."
---

# Z-MAX Console — 维护指南

> 🔴 **GUI 里任何「打开浏览器页面」的地址都不得硬编码 IP。** 实测: `ss_dreamview.py` 的
> `AR_PAGE_URL_LOOPBACK` 预先固定了旧 WiFi IP `10.163.146.78:8793/ar`(变量名还叫 LOOPBACK), 本机改连热点后
> 按钮和状态栏把地址指向一个不存在的 IP ⇒ 用户报「AR 按钮无法打开 ar 网页」, 而 8797 服务一直 200。
> 定式四条: ① 提供 `ar_page_url()` —— **点击时**按默认路由网卡现算
> (`socket(AF_INET,SOCK_DGRAM).connect(("10.255.255.255",1)).getsockname()`), `ZMAX_AR_URL` 仍可覆盖;
> ② **函数默认参数不能写 `url: str = ar_page_url()`** —— 默认值在 `def` 执行时求值, 等于又冻死一次;
> 要写 `url: str = ""` 再在体内 `url = url or ar_page_url()`(ar_open_url / ar_spawn_browser 两处都中过);
> ③ 同源位置一起改, 否则下一个按钮还是无法打开: 工具栏「光纤」(`8797/autoLight`)、旁路视图的
> `zmax_data/ss_bypass/station_url.json`(用 `retarget_local_hosts()` 在读取时校验 host 是否仍是本机地址,
> 不是就换成现算 IP —— **改代码不改用户配置**, 配置里保留他自己的意图);
> ④ 判据 `tools/verify_ar_button.py` 断言「地址里不许出现旧 IP」, 再 `AR_REAL_OPEN=1` 真开一次,
> 认窗口表(`win=0x…`)+ 落在控制台同屏, 不认 `webbrowser.open()` 的返回值。
> 换网后先量: `ip -4 -br a` 里到底有没有那个 IP —— 没有就别在服务端查日志, 问题在地址本身。

> 🧊 **「画布/控制台用鼠标关不掉了」** ⇒ 别先怀疑鼠标和窗口管理器：`py-spy dump` 看主线程是
> `idle`（事件没送到）还是 `active+gil` 卡在 `paintEvent/setData`（绘制占死事件循环，WM_DELETE/Ctrl+Q/SIGTERM
> 全不处理，只有 SIGKILL 能收）。僵尸窗口 id、`IsUnMapped` 窗口、`closeEvent ev.accept()` +
> `SIGTERM→app.quit()` 两处修法、曲线降采样/标签缓存、以及“用户正在编辑时别重启”的纪律：
> 见 `references/gui-freeze-and-close.md`。

> ⚖ **重力表/太阳系「主力」必须与格子数值同源**: `tools/gui/gravity_table.py` 的 `_main_layer()` 曾在 layer_forces
> 开着时取 `layer_forces()` 里加权后的 argmax, 而格子 `mag` 又过了一遍 `|F|=G·M/r²` 重算 ⇒ 高亮落在 L3、
> 数字最大却 L2 (用户一句「高亮跟数对不上」就穿)。修法: 在**最终 cells** 上 argmax, α/权重等构造意图只留痕不覆盖数值。
> 判据 `tools/verify_orbital_state.py` 的 `chk(tag, name, ok, detail)` 注意参数序 (写成 title/got 会被静默错位);
> 同一文件两条同名 `W1` 必须改名 (`W1b`), 否则报告里认错对象。

> 📐 **太阳系右栏「不乱动」= 整列固定宽度**, 不是逐行自适应: 右缘固定 + 每行宽按当前文字算 ⇒ 数字换位数时左缘横移
> (实测单次 13px)。改成 `col_w(W)` 整列定宽、左缘 `W-14-colw+4` 恒定; 行数用滞回值, 避免缺源时整列上下跳。
> 判据 `tools/verify_orbital_rightcol_frozen.py` 用两套量宽不同的数据比较左/右缘, 要求 `max|Δx|=0`。
>
> 🧭 **箭头与表盘同向 = 先归一化再投影**: `_proj` 的近大远小因子 `sc=R·zoom·(1+0.10·z4)` 对长矢量会变负 ⇒ 箭头 180° 翻转
> (实测同一帧箭头 83.7° vs 表盘 263.7°)。两处都走同一个 `_force_dir_screen(vec)` (单位矢量投影, 因子恒 0.9~1.1),
> 避免"两个来源恰好一致"的隐性耦合; 判据 `tools/verify_orbital_force_dir.py` 跨阶段×视角×尺度要求角差 0°。

> 🅱 **550B 标定档「文件→打开工程」自动起 VSCode (省资源 + 单线程 debug)**: `references/vscode-autostart-550b.md`
> —— 启动参数集中在 `tools/gui/vscode_launch.py`(只放 `code --help` 里真有的参数)、pylance 单进程 920MB 必须关、
> `launch.json` 走 JSONC ⇒ 解析前剥 `//` 注释。

> 🧹 **主界面收整三件套 (底部状态栏行 / 画布勾选框 / 日志区拖不动)**: `references/main-window-cleanup.md`
> —— 状态栏要换 `_QuietStatusBar`(单点 hide 会被 showMessage 复活); 日志区拖不动先查 `setMaximumHeight==setMinimumHeight`。

> 📐 **底部硬件状态带：放大字号 / 整条看不见 / 槽位画「—」**: `references/status-strip-scaling.md`
> —— 放大用单一 `SCALE` + `painter.scale`（改完 `fillRect` 必须走 QRectF，否则整帧静默不画）；
> 看不见先查 `availableGeometry()` 越界/帧外延 74px；画「—」是隧道 3s vs 1.5s 超时，不是 NPU 没跑。

> 🧠 **模型引擎四列 (运行位置/运行权重/转换工具/推理还是训练)**: `references/model-engine-runtime-columns.md`
> —— 唯一依据 `tools/model_runtime_map.py`(Intel /models 的 sha16 + /pipeline 的设备占空 + CONVERTERS 表), 界面不自猜;
> 只看 `/status/all.inferring` 会把 96% 占空的端侧渲染成「空闲」。

> 🎴 **产品档三张自绘卡片 + 三档运行位置 (A 本地 / B VSCode / C Intel 端侧)**: `references/product-card-ui.md`
> —— 版式常量只看 `_ProductCard.*`, 底行 = 系统总版本号 · `runtime.label`。

> 📄 **配置中心文案增删 / 判据跟着改 / 改完在跑窗口看不到**: `references/config-center-ui-edits.md` ——
> 配置中心文案由 `_star_facts()` + `StarBanner.set_tab(facts=…)` 现算拼出, grep 原句改不到;
> 删一句要在**渲染入口**过滤(`BANNER_FACT_HIDDEN`), **不动数据源**(tooltip/底部信息窗/判据都读它);
> 同版内把判据 ⑪ 从“必须有”改成“该页必须没有 + 其余页仍有”, 名单从实现模块 getattr 读;
> `studio.py` 只在启动时建一次 `cfg_page` ⇒ 在跑窗口看不到, 不许为看效果反复重启, 如实说“重开一次才生效”;
> **他说"你重启"时**: 先 TERM 旧 pid 再 `systemctl --user start zmax-studio.service`(`launch_studio.sh` 有"已在跑只激活"守卫会用 exit 0 让你以为重启了), 就绪靠 `xdotool search --onlyvisible --name "XSpace ZMAX"`, 改完再用 scrot+OCR 对照页取证。
>
> ❗ **「配置中心 打开先显示 产品配置」+ 左树小对号 = 当前打开的那一页 (常驻口径)**:
> 初始页固定 `_tab_index_by_title("产品配置")`; `zmax_data/cc_last_tab.txt` **只写不读**(回放会让它落回上一页,
> 现场验证: 文件里写着别的页, 打开仍落在产品配置); 左树行首 ✅ = 当前页(并加粗)、○ = 其余页,
> 唯一依据就绪 ✅/⛔ 挪进条目 tooltip; `_mark_tree_current()` 要在 `_fill_tree` 末尾、`_on_tab_changed`、
> 以及**设完初始页之后**都显式调一次(`setCurrentIndex` 索引没变时不发 `currentChanged`, 联动不会自己刷)。
> 「版本号」= 全系统一个号, 读 `update_checker.CURRENT_VERSION`(现 v5.50.751), 不手抄; 550A/B/C 只是配置标识。

> 📄 **控件交互与布局陷阱 (某行一直在闪 / 分隔条拖不动 / 停进程把自己也杀了 / 独立进程组像“自动运行”)**:
> `references/pyqt-interaction-pitfalls.md` —— 闪=悬停提示条每移一次重弹(setToolTip 去重 + 未击中图元不弹);
> 拖不动=两侧 `setMinimumWidth` 之和顶死 QSplitter(大值只作首选宽, 离屏 `setSizes()` 后回读验证);
> 杀进程要写进脚本(内联 `pgrep -f` 会匹配到调用它的 shell 自己), 判活要按 argv 分词不能子串匹配。
>
> 📄 **产品档位卡 (VEH.6.01/02/03 · 550A/B/C) 调档位 UI /「内敛不刺眼」**: `references/product-card-ui.md` ——
> 自绘 `_ProductCard(QRadioButton)`, **必须仍是 QRadioButton 子类**(判据读 text/isChecked/objectName);
> 取证 `setChecked` 会**真写唯一依据** ⇒ 每张卡 `blockSignals(True)` + 判据断言 sha256 不变;
> 互斥组不能 `setChecked(False)`(换另一张当基线); 像素判据用**区域均值**(单点会落在字形抗锯齿上);
> 选中/未选只能同卡比亮度 (≥60%), 排版用 paintEvent 同口径常量复算。

> 📄 **启动慢 / 点快捷方式等半天 / 刚改成延迟建页后判据全红**: `references/startup-latency.md` ——
> 用 **Xvfb :99 冷启**量「点击→窗口可见」(离屏 offscreen 建主窗口会 core dump, 别当回归)；
> 真瓶颈是 **建全部页 + win.show() 首次 polish**(本机 8.7s→3.2s: 首屏只建首页+配置中心, 其余占位后台泵)；
> ⚠ **后台泵不许用固定节拍**: 每 120ms 建一个 ⇒ 主线程一段段被堵, 用户看到"窗口出来了但滚轮十几秒没反应"。
> 用 `start_idle_build()`: `aboutToBlock` 判空闲 + **最近 2s 有输入就一个都不建** + 间隔 ≥0.8s
> + 按 `zmax_data/page_build_ms.json` 实测耗时"轻的先生、重的最后" + YOLO 预热放最后。
> 改完必查三条: `_on_nav` 先 realize 占位页 · 后插入的画布 page 要用 `stack.indexOf` 重算 `self.modules` ·
> 所有 `StudioMainWindow()` 判据/探针加 `win.materialize_all()`。
> **开机第一眼 = 主控制台 home**, 不是配置中心: `launch_studio.sh` 默认 `ZMAX_BOOT_PAGE=home`,
> studio.py 落 home 时**不排跳页**(home 就是 stack[0]); 配置中心由首页「⚙️ 配置中心」卡片单独打开,
> 再从配置中心「🚀 启动工程 · 信号 · 场景」开状态空间工程。只有非 home 的落点才排 3.2s 跳页。

> 📄 **力场可视化 (没运行为什么有力 / 运行后合力不跟着变 / 字太小)**: `references/force-field-visualization.md`
> —— 运行态闸门四条(不重算·不画·写未运行·相位停)、档位门控(只跑 L2 时 L3/L4/L5 写“未调用”, 切档就落盘)、“太阳系不见了”先查 `mparam/viz_view` 落盘、`trace_live.json` 唯一发布者=3D 面板(无窗口必须控制台直发),
> `GravityField` 每次 build 必须 reload 一次、u_ff 加权与主力语义、20px/380/无边框/五个独立表盘/左侧走廊、
> 判据跟着构造改 + 派子代理看图做视觉复核。

> 📄 **观察窗口 (太阳系/3D/信号) 的数与模型实际状态对不上 / 要设计"能反映 L2~L5"的交互 / 字体太小 / 文字飘来飘去要固定靠右 / 文字与球体的连线太乱(改颜色对应) / 画面里有跳跃 / 窗口太小要能拖拽放大 / 每个模型推理要有高亮闪烁 / 要把四元数显示在太阳系 / 地球合力箭头要粗大明显、太阳行星力算分力 / 给 u_ff 加权让主力真压倒分力 / 力箭头忽长忽短(尺度)**:
> `references/observation-window-live-state.md` —— 视图数据必须每拍 `reload()`(只在 __init__ 建 = 死值);
> **所有显示 (球/连线/文字块) 必须连续**: 相位积分 + 线透明度缓变 + 块位低通 (见铁律 8/8b, `tools/verify_orbital_nojump.py`);
> **“在跑”只看控制台发布的 `zmax_data/ss_live/ui_run.json` (+pid 存活)**: 后台常驻 `ss_engine_loop` 一直写 engine_latest，
> 拿文件新鲜度判在跑 ⇒ 没点 ▶ 运行也显示力/在转 (用户一问就穿)；没在跑就不画力线/不画自转弧/相位冻结/太阳标签不写 T。
> 公转相位必须**积分** (`_ph += ω·dt`, ω 平滑向目标)，禁 `相位 = f(实测量)` (数据一跳就来回跳)；`_geom()` 图注行数加滞回防“呼吸”; 结构映射 (黄道面↔S³ · 太阳=中心 · 行星=DiT · 地球=MLP · 引力=度量) 的落点、
> 以及画布「画了但没画出来」三种静默失败 (坐标单位/低 α/亮度跟实时量) 也在这份里;
> 状态按**每个实体自己的唯一依据 mtime** 上色 (●≤2.5s ◐≤60s ○离线), 层状态取 `layer_calls.jsonl` 末行;
> 口径写屏上 (τ 是解析势场还是模型张量 · 是否限幅); 加信息前先算遮挡代价 (贴球标签压球、右上角状态带压虚线)。

> 📄 **「改完用户看不到」/ 数据空间缺 Tx 节点 / 速度 mm/s 口径 / v_ff 能否算位姿**:
> `references/dual-instance-and-trace-tx-gates.md` —— 先查是不是**两个控制台并存**（裸 `studio.py` 启动的实例不被
> `gui/studio.py` 模式匹配 ⇒ 用户一直在看旧进程）；Trace 上屏要过**三道门**（层索引 → Rx → 信号白名单），
> 任一不过整行静默消失；速度键 `_mms` 只在生产端 ×1000 一次。

> 📄 **控制台发涩 / CPU 吃满 / 内存增长**: `references/gui-cpu-and-memory-forensics.md` ——
> `/proc` 差分采 CPU(不用 `ps %CPU`) · **窗口在后台不算数**(Qt 不重绘, 必须同可见页面前后对比) ·
> py-spy raw 要**按 count 加权** · 3D 面板每帧新建 QFont/QFontMetrics(缓存后 13.7→4.5us, 缓存必须设上限) ·
> `HOST_POLL_HZ` 50→20 · anon 64MB 段 = glibc arena(`MALLOC_ARENA_MAX=4` 只有走 restart 脚本才带上) ·
> 段差分报 `RSS 0MB/负值` = pid 被换掉了。
> 「阻塞了 / 点不动」先 `py-spy dump --pid` 抓主线程栈(dump 一次就够, 不必先 record): 栈里同一链反复出现
> (`_tick → … → _trim_selected`)就是周期 tick 死循环。定式: **周期性 tick 里"裁到 N 条"必须同时回写控件状态**
> (只裁内存列表、不取消勾选 ⇒ itemChanged 每拍把行塞回 ⇒ 裁/塞 4Hz 循环, 主线程 100%),
> 并给裁裁日志加 10s 节流、所有入径走同一收口; 修完报 `/proc` 差分前后数 + MainThread 回 `idle`(§9)。

> 📄 VEH.6 配置中心 `references/veh6-config-center-mcd.md`(参数表/四层配置/CLI/写后回读) · 全链路演练+功能描述+专利导出 `references/full-drill-and-patent.md`
> 📄 **配置中心「💰 成本/报价」+「🧩 商业模式」**: `references/config-center-cost-page.md` · `references/config-center-business-model.md`
> —— 成本只存输入(BOM/软件/人力/产线), 派生值现算不落盘; 商业模式从成本+性能+任务推 分层口径/成交区间/三阶段/模式,
> 区间不成立就改配置不降价; 加页必连带改 `_TAB_ORDER` 与既有判据里的页签计数。
> 📄 **唯一依据改了 → 工程库/参数中心同步 (ensure-fresh · 三表对账 · param auto 行)**: `references/truth-to-db-sync.md`
📄 **配置中心页面改 UI (删重复块 / 文字全可选可复制 / 判据同步 / 一次重启)**: `references/config-center-ui-changes.md` ——
> `ConfigCenterPage` 被主控制台与独立窗口共用 ⇒ 改一处两边同时生效; 删块必须同改判据并翻成"不该再有这个块";
> 全页文字可选中 = QLabel OR flags + app 级 Polish 过滤器 (跳过条件别写成 `if f & (A|B)`); 判据变红先 stash 取基线。
> 📄 **控制台内存 / 看门狗 / 重启**: `references/studio-memory-and-watchdog.md` —— 信号页五处内存结构(预分配环形缓冲 ·
> `arrays()` 零分配 · 元数据被当曲线画 · 高频 json 解析) + 看门狗必须“杀掉后自动拉起” + 重启脚本按 `comm` 取 pid(否则自杀) +
> IDE `launch.json` 的 env 也要跟。判据只认“增速掉下来”(5/10/20 分钟三点 GB/h), 单点 RSS 不算数。
> 📄 **发版/保存数据**: `references/version-bump-and-release-archive.md` —— 版本号只按用户指定升 · `bump_version.py` 一次改齐 9 处
> (归位后 docs_sync 路径变了, 不改就静默漏改) · tag 已推后同版本内修 bug 用 `git tag -f` 移动而不是自主 bump ·
> 归档两份 (`docs/data_snapshots` + `zmax_data/release_<ver>_<date>`) 并用 `sha256sum -c` 回读 · 跨平台只说"配置已验, 产物由 CI 出"。

> 📄 **两窗口同源 (信号分析 ⇄ 数据空间 Trace)**: 同文件 **§11 / §13③~⑦ / §14 / §15 只留 L2 收口 / §16 统一信号库** —— Tx/Rx/Layer/单位/数值/变化率
> 只许一份唯一依据 `middleware/attribution.py`；固定行不许按帧龄等衍生量重排（行会跳）；
> §15: Tx/Rx 只认工程节点名（禁进程名·数据空间禁横杠行）；§16: 两窗口读 `signals.db` 而不是各读 JSON。
> 场景组默认勾满全部动态信号，波形同时只画 24 条（278 条实测一次刷新 14.5s）。
> 📄 同文件 **§14** = 固定行的最后一公里：字段一拍有一拍没 ⇒ 老行保序 + 缺键保留上拍 ≤60s，
> 判据必须走增量路径（`force=True` 会掩盖问题）；同源只认冻结快照逐字比对（面板每个前缀都要走
> 同一 `live_signals` 快照，否则快变量差一拍）；位姿无真值就写 -1 + QoS 告警，禁止按动画推角度。
> 📄 **表格类 UI 硬规矩**: `references/dataspace-message-signal.md` §7 —— 用户手拖过列宽后，
> 刷新心跳里的 `_fit_columns()` 必须停手（它就是“拖完又自动还原”的真根因），复位只给 `↺` 按钮；
> 列宽按 `ensurePolished()` 后的表头字宽 + **该列最长文本**算；**不许省略号**（`ElideNone`，放不下就横向滚动）；Tx/Rx 只放 `middleware/naming.py` 归一后的节点本名（无 emoji/层号/序号/箭头）；右侧详情与表格必须同一个类型唯一依据；
> 表头一列一个英文短词，不加中文/括号/解释（解释进 tooltip），面板标题就一个词。
> 同文件的 **§8** = Tx/Rx 只放 `naming.py` 归一后的本名 + 表格与详情必须同一个类型唯一依据；
> **§9** = 质量告警必须判物理值（超上限/低于下限/NaN/无单位/跳变），Trace 一行一个信号带 `Unit`+`Phys`，
> 顶部工具条只留一个搜索（放在 Trace 按钮区）且**删控件前先 grep 引用**（否则暂停键联动已删按钮 → AttributeError）。
> 同文件的 **§11** = 信号分析窗口(canoe_graphic) 与数据空间同口径: 7 列 `Name|Layer|Signal|Value|Type|Tx|Rx`（Layer 必须在第2列，放最后窄栏就看不见）、
> 全列 `Interactive` + QSettings 拖宽记忆（原来第0列 Stretch 所以拖不动）、三路真值走 `live_signals` **同一份缓存**才叫同源同值、
> 值缓存键 `(id(item), key)`、按帧龄排序置顶、中文键正则、时间列用 wall-clock−帧龄；**§13** = Tx 必须是真 node_id（无节点就写进程名，不许拿"像节点的名字"顶上）+ 列头按值过滤 Layer/Type；
> **§12** = 面板瘦身（按钮并一行 / 只留八阶段一行文字；隐藏控件用 `setParent+hide`，不许删除构造）。
> Qt 样式表告警定位（message handler + `sip.unwrapinstance` 地址反查）、隐藏控件不漂浮、终端噪声开关 → `references/qt-ui-forensics.md`。
> Trace 列口径 = `Time | Layer | Name(中文≤5) | Signal(程序真实变量) | Value | Unit | Phys | Type | Tx | Rx | QoS | Hz`，
> Layer 只有 `L2~L5` + `SYS`(meta / 注册表类话题)；本工程没有 L1，**不许为了凑 L1~L5 编层**；
> Trace 必须遍历**工程库全部话题**(含入口, 实测 273 个)，不能只显示 live.json 里有流量的那几个(24)；
> QoS 必须显示 DDS 标准策略名（不是内部 beat/state），空值直接 `—` 不要 `❌ 未知: —`；改列前先 grep 旧列名（表头在构造 + 两处 setter 共三处预先固定），并同步 `QTableWidget(0, N)` 的列数与所有按列号取值的代码（选中行取 Name、`_fit_name_col` 的目标列）。

> 📄 画布节点右键「打开代码」落点 / “点了没反应” 分诊: `references/gui-rightclick-and-code-jump.md` ——
> 先读 `~/.cache/zmax/rightclick.log` 的 `kind=`/`loc=`/`err=`，再谈改代码；落点解析不许依赖 import
> (直查 `middleware/nodes/n_<单词>.py` 的 `PORTS_IN` 行 —— 单词来自 `middleware/node_names.json`,
> 文件名**不用 id 也不用中文**，见同文件 §2.6)；没模块就**现场生成**再打开 (绝不允许“打开 node 却给了别的文件”)；
> 两入口 target=`impl`/`node` 别搞反；起窗后 xdotool 抢前台。

> 📄 控制台生命周期 (`references/console-lifecycle-and-exit.md`): **别自作主张重启用户的控制台** (改完给命令/问他);
> 关窗不能崩 (`sys.exit(app.exec_())` → `os._exit()`, 否则 QThread Destroyed → Aborted/-6), 判据用
> `wmctrl -ic` 真关窗比 `Fatal Python error` 计数, 离屏验不了; 配置窗口是复用的 ⇒ 改 json 后必须在 showEvent 重读。

> 📄 全局数据空间 / 报文·信号 (`references/dataspace-message-signal.md`): 数据空间只读**工程库**
> (mw_project/node/port/link/topic/signal), 话题=报文、payload 字段=信号; 画布保存同一口落库;
> 报文按 **L5→L1→系统** 分层分组 (不造空组), 信号表带 **Tx / Rx** (由 mw_link 派生, 没连线写 —);
> 未声明信号不许假装存在, 单位/量程只从参数中心取。

> 📄 UI 宽度/几何: `references/ui-width-and-geometry.md` —— 「某栏太宽/拖不动/字被挡」的固定口径:
> 宽度**必须在真屏 (DISPLAY=:0) 量**, 离屏 fontMetrics 与 192DPI 真屏差一倍; 打开宽度 =
> pin > 更窄的记忆 > 内容需求 (记忆只许更窄, 配树指纹); 最小宽度别拿内容需求当地板 (否则拖不窄);
> 画布加显示元素要包在 `paint()` 外层 (`_paint_internal` 只覆盖 Z700 分支); 宽到压不下去时先瘦行内冗余文本
> (全文存 item data 供分派, 并 grep 所有 `setText(0)` 处一并改), 再谈省略号。

> 📄 相关: `references/live-value-freshness.md`(显示诚实性: 任何标"当前"的值必须过源新鲜度判据, 源停更要标失效+勿据此判安全) · 右上角三色状态灯唯一依据+控制台重启(禁 systemctl restart) `references/status-lights-and-restart.md` · 首页 hero 按钮基线 `references/ui-hero-buttons-slimming.md`。

> 📄 Roadmap Phase 卡(描述由工程库生成·点开可编辑·主指标整齐 + 真窗几何取证 + 整页横向溢出陷阱 + **卡面不许写解释性横幅文字: 状态用图标/说明进 tooltip**): `references/roadmap-phase-cards.md`

> 📄 其它: `canoe-graphic-signal-analysis.md` · `monitor-live-source.md` · `standard-open-flow.md` · `3d-scene-render-forensics.md` · `config-import-node.md` · `console-title-and-debug-parity.md`(标题·调试同源) · `console-child-processes-and-crash-forensics.md`(子进程 cgroup 连带·崩溃现场取证·VSCode SIGTRAP) · `vscode-debug-breakpoints.md`(断点空心三类根因: 惰性import / 路径少一层 dirname / 引擎加载方式 + 必停四前提 + 取证命令) · `vscode-workspace-and-source-control.md`(多根工作区根名要带路径·不许截断 · Source Control 面板认不到仓库/✓灰掉/凭证与推送核对 · 起停 VSCode 进程纪律)
> 📄 球心引力架构视图(天体↔节点映射·只画主体↔主体·全虚线·颜色=信号·有信号才画·标签带天体名·改完四步): `orbital-arch-view.md`
> 📐 「显示不全/增大高度」的高度账 (先量后改·子控件 setMinimumHeight 顶死布局的坑·自动配平公式·窗口几何会吃高度): `page-height-budget.md`
> 🧠 `status-panel-and-model-engine-window.md` = 底栏面板一行 · 模型引擎窗口 L2~L5 (训练状态+控制+执行任务工程) · 模型配置接线 · GUI 硬约束判据 (不截断/一屏放得下)

## 🖥 界面文案 = 工程真值 (侧栏卡 / 首页架构图 / 模块卡)

* **描述性文字必须来自单一工程库真值, 不是印象**: 侧栏 System 2/1/0 卡的层级·角色·功能条数、首页架构框、
  模块卡副标题, 一律取自 `data/database/zmax_engineering.db` —— 先跑
  `SELECT system_id,name,level,role,hardware,kpi FROM subsystems` + 按 system_id 数 functions, 再写文案。
  老倪的口径: 「总结成当前的实际状态」「上面的文字之前可能有些出入」= 文案要对齐库, 不是对齐旧稿。
* **旧编号一律换成当前层号**: 画布里遗留的 `SYS11 VLA-T / SYS12 Z-Flow`、`Sys-0 / L2基石` 只在画布条目名里保留;
  侧栏/首页文案统一写 `System 1 · L3 动作执行 (VLA-T + Z-Flow)`、`System 0 · L2 基石执行`。
  **画布条目名不要顺手改** —— 改它等于改工程画布, 必须走 `flows.save_canvas`(校验+备份) 写口, 并单独确认。
* **卡片里固定不变的数字会过期**: 把「功能 30 / 162 个可改数字」这类库计数印进文案时, 交付时明说这是当前快照,
  或改成开机从库读一次再填。
* 左侧分组标题带用法提示 (如「平台产品 · 点开 = 产品与功能清单」) —— 老倪要点开才知道那卡去哪。

## ⚙️ 启停 / 重启纪律 (studio_ctl.sh)

* 一律走 `bash tools/studio_ctl.sh {status|stop|start|restart} [--force]`；**禁止** `pkill -f studio.py`（会杀到自己 shell）。
* 起不到 300s 的实例 stop/restart 被硬闸拒（防窗口闪），确实要换代码才加 `--force`；每次动作记 `/tmp/studio_ctl.log`。
* 🔴 **启动偶发 Aborted (core dumped)**（v5.39.0 / v5.39.9 各中一次，根因未挖）。现每次启动日志按时间戳留档
  `/tmp/studio_launch_<ts>.log`（`/tmp/studio_launch.log` 是软链指向最新），起后 25s 自检 pids，没成活就打印
  QThread/Aborted/Fatal/Segmentation 关键行 + 自动重试一次。**查崩溃现场只看时间戳日志** —— 旧写法固定写
  同一个文件会被下次成功启动覆盖，两个崩溃现场都因此丢了。
* 重启后除了 `status`，还要实核**窗口标题里的版本号**：
  `DISPLAY=:0 xdotool search --onlyvisible --name "XSpace Studio" getwindowname %@` —— 只看 pid 会漏“起的是旧版本”。
* 版本号同时散在 `VERSION.md` 与 `tools/gui/{docs_sync,studio,update_checker,version_sync}.py`、`tools/ci/integrity_check.py`，
  升版要一并改（否则标题/自检不一致）；改完必须 restart 才会在标题生效。

## 🖼 实机取证纪律 (截图 / OCR / 真交互)

* **截图前先把目标窗口置顶**: `wmctrl -i -a $(wmctrl -lGx | grep 'XSpace Studio' | awk '{print $1}')` → sleep 2~3 → `scrot`。
  否则抓到的是最上层那个窗口 (实测抓到别的聊天窗口), 拿错图当证据。
* 先看窗口标题里的版本号 (`XSpace Studio — Z-MAX vX.Y.Z`) 确认重启真的生效, 再截内容。
* 离屏判据里的"点卡"等价写法: `win.sidebar.layer_clicked.emit(target)`; 真机再用 xdotool 点一次复核坐标。

## 🧰 批量改同一个文件的纪律 (studio.py / 参数注册表这类大文件)

* **先把所有锚点断言一遍, 再统一写盘**: 一批编辑里, 靠前的 replace 会改掉后面锚点赖以匹配的文本 (同一个词
  出现在多处时尤其致命)。做法 = 每个锚点 `assert s.count(a)==1`, 全部通过后才 `write_text`。
  断言失败 ⇒ **整批没写**, 回头核对"到底哪几处生效了", 不要默认部分生效。
* **`str.replace(a, b, 1)` 命中的是文件里的第一处**, 不是你心里那一处: 重命名词条时第一处常在 dict/CURATED 定义里,
  真正要改的调用点没动。用带上下文的锚点或 `count(a)==1` 断言。
* 写完必 `py_compile` 再跑该面判据; **判据口径要跟着改**: 改了状态词表/枚举/表名, 检查端必须同步,
  否则旧口径判据红成"新 bug", 白白回头查一轮。
* **GUI 改动攒批一次重启** (`tools/studio_ctl.sh restart --force`): 老倪投诉过反复重启。文案类改动尤其要
  侧栏 + 首页 + 模块卡一次改完再重启。

## 🗂 工程存档 (.zmaxproj v2) + 总工程 zmax_space (2026-10-09)

老倪: 「保存状态空间工程所有配置(画布/右侧栏/标定/测量/主参数)…都要有相应的文件」+「定义一个
zmax_space 总工程, 通过 文件→打开/加载工程 集成式打开, 不像现在还得手动加载」。

* 格式 = 一个自包含 JSON, **7 段**: ①canvas ②panel(视图/页签+6 运行开关+画布栈索引)
  ③calibration(唯一依据全文+sha256/mtime+未标定项+现场标定命令) ④master_param(M/inertia/范围+M 节点快照)
  ⑤measure(measure_view/diagnose_view+总线配置) ⑥tasks ⑦fingerprints(每个唯一依据 sha256)。
  代码: `tools/gui/project_file.py`(采集/比对/写入) + `tools/project_archive.py`(CLI: space-save/
  space-open/space-show/save/inspect/diff/verify/restore/explode/list/upgrade)。
* 🔴 **唯一依据唯一**: 存档=快照+指纹; 写盘只走各自写口 —— 画布 `flows.save_canvas()`(校验+备份到
  `flows/_archive/`)、标定 逐文件 `*.bak_<ts>`→写→**回读 sha256**、任务 `ss_task_bind.py --activate`。
  普通存档默认**只回填画布+面板**; 标定/主参数只看不动 (要覆盖: `--with-calib --yes`)。
* **总工程** = 同一格式 + `kind="zmax_space"` (固定 `reports/projects/zmax_space.zmaxproj`);
  打开语义=**集成式**: 标定→主参数(回读)→任务→画布→面板 一次全回填, 每步先备份再写, 给一页报告。
  入口: 主窗口 文件→ `🗂 保存/打开总工程` (Ctrl+Alt+S/O); 老的 `📂 加载工程文件` 选到总工程时
  **自动识别 kind** 走集成式 (同一个菜单, 不用记两条路)。
* 坑 1: **漂移比对必须先剥时间戳** (`_meta`/`generated_at`/`updated_at`) —— 否则每次写都会假报
  「tasks 漂移」(值一样, 只因 generated_at 变了)。
* 坑 2: 集成式打开**顺序**: 内容(标定/主参数/任务)先写, **画布最后** (画布里的 M 节点快照与标定同源);
  面板态要由调用方回填 (`apply_run_cfg` + 切视图), 不在库里写。
* 坑 3: 命令行存档读不到界面态 (运行开关/视图) —— 要如实标注「控制台没打开」, 别静默存空。
* 交付配套: `verify_project_archive.py` ⑨ 段判据 (含: 现场摸乱三处后 space-open 全量回填、
  restore 默认不动标定、主窗口菜单两项、v1 老存档兼容+升级)。

## 🧹 UI 精简三招 + 工具栏→菜单 迁移 (2026-10-09)

老倪: 「按钮都删掉」「侧边栏字数太多, 精简」「不常用的按钮迁到菜单栏, 你来设计UI」。

**一、删按钮不改行为 (能力换入口, 别直接删功能)**
* 删前逐个列“能力去哪了”: 定位/全览/审计/闭环台 → 快捷键 (Ctrl+L / Ctrl+0 / Ctrl+Shift+A / Ctrl+Alt+P);
  INTACT机器人 → 画布节点双击; 另存为/加载/保存模型/录制/停止/浮动 → 新菜单「画布(C)」。
* 快捷键注册: `QShortcut(QKeySequence(k), canvas)` + `setContext(Qt.WidgetWithChildrenShortcut)`。

**二、菜单设计模式 (单一唯一依据)**
* 菜单表放模块类属性 `SimulinkModule.CANVAS_MENU = [(key,文字,快捷键,tip,sep), …]`; 主窗口按表建 QAction,
  画布模块建好后 `attach_canvas_actions(acts)` 接管, 并**把属性名沿用 btn_save/btn_record/…** ⇒ 旧代码零改动。
  (主窗口菜单在 `_build_menubar()` 建, 早于懒创建的画布模块 → 点击转发里必须 `sim is None` 时给实话提示。)
* 主窗口**没有** `_log()` (那是别的类)! 加 `_ui_msg()` 保障: model_engine._log → self._log → print。

**三、QAction 替换 QPushButton 的两个必遇到问题**
* `QAction` 无 `rect()` → 气泡定位 `mapToGlobal(btn.rect().center())` 直接炸; 用 `_action_anchor(act)`
  (act.associatedWidgets() → mapToGlobal, 拿不到就用窗口中心)。
* `QAction` 无 `setStyleSheet()` → 录制中的按钮变色/呼吸会炸; 改**画布横幅报进度** (set_banner)。
* 0 点击高亮类代码 (教程/新手引导) 接到菜单项时必须 `isinstance(w, QWidget)` 保障退到画布。

**四、侧边栏“字数太多”的四招 (数据一条不删)**
1. 长文案→短句卡面, **全文进 tooltip** (含引擎行号/实测代价), 判据改为“卡面短 + tooltip 含全文”。
2. 表格单元格截断 (`_cut(t, n)` + `setToolTip(全文)`), **📋复制/导出仍给全文** (老倪要可复制)。
3. 重复文案合并 (同一句写两遍 85 字→39); 显示层压掉 `python3 tools/` 前缀 (唯一依据原串不动)。
4. 长值紧凑格式化: 列表/字典嵌套也要走 `_fmt` (只格式化顶层 → 嵌套 list 会把 384 字完整 K/dist 呼出来)。
* 共用小工具要放**模块级** (`_cut`/`_fmt`), 多个视图各自 `@staticmethod` 会 `self._cut` 直接 AttributeError。

**五、离屏建主窗口的取证套路 (必用)**
* 离屏 `StudioMainWindow()` 退出时 DDS 线程 core dump (已知) ⇒ 把“建主窗口”的判据写成**子进程**
  (`tools/probe_canvas_menu.py`), 每行 `flush=True`, 父进程只读 stdout 的 ✅/❌ 行 ⇒ 崩了也不丢结果。
* 未抱异常会 “QThread: Destroyed while thread is still running → Aborted” 假崩: 先看 traceback 第一行,
  别当环境问题 (真例: `QAction.title()` 不是 `text()`)。

## 🏭 工程数据库 (单一文件) + GUI↔工程解耦 (2026-10-09)

老倪的硬要求: **一个数据库文件 = 一套工程**, GUI 不绑死工程, 换库 = 换工程。落地形态:

```
唯一依据 (人可编·进 git)                       库 (生成物, 可随时重建)
  config/platform/zmax_platform.json   ─┐
  reports/projects/*.proj (7 段)        │
  flows/state_space_obs.json            ├─→ data/database/zmax_engineering.db (0.82 MB SQLite)
  config/calib/*.json + feature.dbc     │      tools/engineering_db.py build
  verification_layer FEATURES + NODE_LOGIC ─┘     check 判据 11 项全绿才算同步
```

* **GUI 只认 .db**: `tools/gui/platform_spec.py` 的「📋 功能清单」页走 `engineering_db.load(db)` (纯 sqlite,
  不 import 工程文件)。侧栏 System 2 之上是 🏭 Z-MAX 卡; 点 Z-MAX/System2/1/0 → 切页 + `select_system(sid)`。
* **服务**: `systemd zmax-engdb.service` → 127.0.0.1:8798 只读 JSON (`/summary /system/<id> /product/<id> /graph /project` …)。
  改库后 `systemctl restart zmax-engdb.service`; 手工起的服务会占端口把 systemd 卡在 activating。
* **判据口径 (踩过的坑)**:
  * 画布行带归属必须**全局唯一** —— 用「行名前缀」匹配会把 6 条同前缀的 L2 行都命中同一带 ⇒ 同一批节点数 6 遍
    (85 功能 ≠ 74 节点)。正确做法: 行名按「`·` 后缀」唯一解析 + 节点按**中心**落在带内取最具体的行带。
  * 行带**缝隙**里的节点(`🛡 安全执行边界`/`① 接近 SK01` 就落在两条带之间)要按**最近行**归属 + 标
    `kind=行外节点(就近归属)`, 不能丢。
  * `.proj` 真实键名 ≠ 7 段语义名 (canvas/panel/calibration/master_param/measure/tasks);
    入库时**全量顶层键都存** + 另存一份 7 段语义别名, 判据按语义名校验。
* **懒加载页导致下标漂移**: 画布页 400ms 后才插进 stack(index 10) ⇒ 之后所有页下标 +1;
  `self.modules[页]` 记死的下标会指错页。切页一律 `self.stack.setCurrentWidget(w)` + 现场 `indexOf`。
* **data/ 瘦身口径**: 只删「代码不读、可重跑重现」的大件 (实测: handeye 79 张标定采集截图 333 MB,
  代码只读同目录 7 个 json)。动手前先写清单到 `docs/notes/cleanup_manifest_*.txt` (含重现命令), 再删。

## 🧭 左侧栏排版口径: 产品 / 系统 / 功能 三级 + MCD 单色数字行

老倪定的三级定义, **左侧栏每组标题就是定义本身**, 卡片只说一件事:

```
① 产品 · 面向客户的完整交付物      → 🏭 Z-MAX 平台 (Z700/Z100) + 🎛 参数中心(MCD 数据面)
② 系统 · 支撑产品运行的架构        → System 2 / System 1 / System 0  (平台支撑卡不进侧栏)
③ 功能 · 系统里最小可执行能力单元   → 📋 功能清单
```

* **MCD = 测量 Measurement · 标定 Calibration · 诊断 Diagnosis**, 卡片上是 MCD 单色数字行 (彩条已废 — 老倪要求不五颜六色)
  (🟦M / 🟨C / 🟩D)。数字**一律从单一工程库 `mcd` 表读** (`_mcd_from_db()`), 不预先固定; 库不在就自动省略该行。读库发生在窗口构造时 ⇒ 改完库/标定后要重启控制台卡片数字才刷新(交付时先说清这一点)。
  当前: 产品 M9/C45/D57 · sys0 M9/C41/D38 · sys2 C4/D11 · sys1 D8 · 平台支撑 M9/C45/D57。
  M=工程 measure 视图测量量(帧龄<2s) · C=zmax_calib.json 标定叶子 · D=FEATURES 断言+故障码 MCD-E0x+站点缺口。
* **卡片只留 4 样**: 标题 · 副标题(哪一层/多少功能) · MCD 单色数字行 (说明行已删, 改挂 tooltip)。**不要**三行长描述
  (老倪原话: 「很挤」)。旧编号(SYS11/SYS12)与 500M/15M 这类细节从卡片撤走, 放到功能清单页里看。
* 字号按窗口适配: 标题 12pt 白粗 · 副标题 11pt · MCD 11pt 等宽 · 卡最小高 70px · 边距 11/6 · 行距 3。
删掉说明行后腾出的空间要还给字号 —— 不要靠缩字号去塞内容。

### 侧栏最终形态 (6 卡 · 上→下) 与铁律

```
① 产品        🏭 Z-MAX 平台
② 系统        System 2 / System 1 / System 0      (🧩 平台支撑不进侧栏)
③ 产品配置    📋 功能清单      ← 改配置面 (每条功能 = 配置/标定/诊断 三轴)
④ 数据配置    🎛 参数中心      ← 改数字面, layout.addStretch() 钉在最下面
```

* **黑色/深灰说明行一律不留** (C_DIM 小字): 卡片说明改挂 `setToolTip()`, 需要时悬停看。
  实测回放: 两次投诉「很挤」「字太多」都是它 —— 删字优先于缩字号。
* **全侧栏彩色 ≤2 种**: 统一 `C_SIDE = "#58a6ff"`(卡边框/副标题/MCD/分组标题/页脚/logo) + `C_WHITE "#e6edf3"`(卡标题)。
  禁每卡一主色 + MCD 三轴三色 (实测 7 色被否)。
* **每卡三行**: 标题(12pt 白粗) · 副标题(11pt, 如「L4/L5 认知决策 · 30 功能」) · MCD 单色数字行
  (11pt 等宽, 如「M 9 · C 41 · D 38」, 只列非零轴)。
* **分组标题极简**「① 产品」「② 系统」「③ 产品配置」「④ 数据配置」, 三级定义放 tooltip:
  产品=面向客户的完整交付物(解决某业务问题) · 系统=支撑产品运行的整体架构(模块/子系统) · 功能=系统里最小可执行能力单元。
* **UI 约束必须固化成判据**, 否则下一轮手写回答又跑偏: `verify_platform_spec.py` ⑦ 每卡 ≤2 色且卡内 QLabel ≤4 个
  (说明行被加回来就红) · ⑧ 侧栏整体(卡+分组标题+页脚+logo)配色 ≤2 种; `verify_param_center.py` 断言参数中心卡在**最下面**
  且侧栏无平台支撑卡。改完两件都跑, 不要只看其中一个。
* 改完后真机复核 (顺序不能反): `env -u QT_QPA_PLATFORM bash tools/studio_ctl.sh restart --force` →
  `wmctrl -i -a <窗口id>` 先激活(否则截到别的窗口) → `scrot` → 裁剪左栏 → `tesseract -l chi_sim+eng` 读回文字。
* **改文案先离屏单控件取证**: 不起主窗口, 直接 `QApplication([sys.argv[0]])` + 实例化那个子控件
  (`ProductRoadmapWidget()` / 侧栏卡), `findChildren(PhaseCardButton)` 后打印每个卡的文字/数字 —— 秒级拿到
  真实渲染文本, 比截图 OCR 快且不易错; 最后再用实机 OCR 做一次外观复核。
* **补丁脚本纪律**: 全部 anchor 先 `assert count==1` 再 `q.write_text()` 最后写盘 —— 中途断言失败 = 文件根本没改,
  可以放心重跑修正版; 用字符串切片替换整段时, 切片终点要写成显式常量 (`SEP = "self.setLayout(layout)..."`),
  并把尾巴原样拼回, 否则会把 `setLayout`/`def` 头部一起切掉。

> 📄 左右分栏页「拖不动/字被截」= 右栏单行 QLabel 顶死最小宽: `references/config-leftcol-width.md`

## 🎛 全局可改数字 (参数注册表 / 改数即链动, 2026-10-09)

老倪的硬要求: **改任意一个数字都要能说清它动了什么** (功能·性能·代码), 且数字只有一份唯一依据。

```
tools/param_registry.py  scan→registry()  162 个数字五类:
  calib(45) JSON 叶子 / canvas(78) 节点 params / code(25) 常量+函数默认参数
  platform(8) KPI 文本里的数 / switch(6) 档位
set_param(id, v, write=False) 校验→预览链 ;  write=True 备份→写唯一依据→回读核对
  写口五路: calib JSON 路径 / canvas params / KPI 文本原地替换 / 代码常量行 / 函数默认参数行
effect_chain(id) → 子系统·功能·模块·代码 file:line·KPI
```

**踩过的坑 (改注册表/加数字前必读)**:
* **路径解析要支持列表下标**: `camera.K[0][0]`; 平面 split('.') 会取不到 → `_path_tokens/_get_path/_set_path`。
* **null ≠ 读不到**: `plane_z.value: null` 是现场缺口(未标定), 判据必须区分「路径不存在」与「值就是空」,
  否则要么误报要么把缺口洗成正常值。
* **范围口径分三态**: `已定义(人工)` / `范围自动推断(未确认)` / `未标定(缺口)`。自动推断的界**不许**冒充人工定义,
  否则用户以为 0..1 是权威界 (实测 w_ff=0.3 推成 0..1, 改 1.3 被拦是**对的**, 但界本身是猜的)。
* **负值要能推范围** (畸变系数是负的), 预先固定 `0..max` 会让自校验全红。
* **画布 params 大多是元数据**: `state_space/row_bg/bg/status` 不是旋钮, 过滤后 149 → 78。
* **代码数字不只在模块级**: `insert_depth=0.0005` 在函数默认参数里 → `ast` 要扫签名 default (3 → 25 条)。
* **顶层 KPI 的数字也在唯一依据里**: 正则从 KPI 文本抽量化目标(≥99% / <4mm), 写回原地替换数字、保留比较符与单位。
* 写代码类数字**必过 ast 语法校验, 坏则从备份回滚**; 所有改数直接写唯一工程库 `param_events` 表留痕 (没有 jsonl; build 不清空该表)。
* 判据: `tools/param_registry.py verify` + `tools/verify_param_center.py`(8 项, 含真改数→回读→还原/越界必拒/非法档位必拒)
  + `engineering_db.py check` ⑧ 参数面。

## 📚 模块库 ↔ 画布: 同步 / 拖入 / 删除 / 存为新工程 (2026-10-09)

左侧栏 `LibraryPanel` 的条目**不是**手写清单 —— 它 = 静态组 + 两个**生成组** + 一张**删除名单**。
改这块前先记住这个合成公式, 否则会去改错地方:

```
LIBRARY = LIBRARY_STATIC(源码里的手写组)
        + _load_skill_library_groups()          # flows/atomic_skill_tokens.json (原子技能注册表)
        + _load_state_space_library_group(nodes) # 画布节点: 给 nodes 就用内存(刚拖进来也算), 同 JSON 保障
        − _apply_library_curation(LIBRARY)        # config/library_curation.json 的 removed 名单
```

* **同步是活的**: `SimulinkModule.refresh_library(force=False)` → `_rebuild_library_globals(nodes)` +
  `LibraryPanel._rebuild()`; 用「画布节点名集合 + curation mtime」签名做快路, 没变不重建 (495 个按钮
  全建要几百 ms)。`load_flow_file()` 收尾自动调一次 → 换画布 = 库跟着换。
* **拖进画布**: `LibButton`(库按钮子类) 拖 ≥8px → `QDrag` + MIME `LIB_MIME="application/x-zmax-lib-item"`
  (载荷 `{type,name,params,group}`); 画布侧 `SimCanvas.setAcceptDrops(True)` + `dragEnter/dragMove/dropEvent`
  → `add_node_from_lib(payload, mapToScene(落点))`。拖 = 落鼠标处, 单击 = 老行为 (画布中心)。
  * **坑**: `QDropEvent` **不接管** `QMimeData` 所有权 —— `QDropEvent(pos,act,btn.drag_mime(),...)`
    这种内联写法 Python 侧无引用 → GC → **段错误**。先 `mime = btn.drag_mime()` 接住再传。
* **删除条目**: 库按钮右键 → `_remove_entry` → `remove_library_entry()` 写 curation 名单 → `refresh_library(force=True)`。
  删条目**不动画布节点**; `lib_sync.py restore` 整表还原。别再把删/改写成直接改源码。
* **判据口径**: `lib_sync.py verify` 的「画布节点都得在库里」**只认状态空间画布**
  (`state_space_obs.json`) —— 库不是所有 flow 的并集 (别的 side canvas 只报覆盖率)。
  判据 `tools/verify_library_sync.py` 已入 `run_gui_verifiers.sh`; 体检/清理走 `tools/lib_sync.py check|dead|prune|restore`。
* **离屏测保存类功能**: 代码里若真建 `QFileDialog(...)+dlg.exec_()` (如 `export_flow`), 替身要替 `QFileDialog.exec_`
  → `Accepted` + `QFileDialog.selectedFiles` → 临时路径 (替 `getSaveFileName` 没用, 代码根本没调它)。

## 🔴 GUI「点了没反应」实机取证三步 (2026-10-09)

### ⛔ 重启控制台前必查 (我自己踩过, 比 bug 更致命)
本会话跑过离屏判据后, shell 里会残留 **`QT_QPA_PLATFORM=offscreen`**; 接着 `studio_ctl.sh restart`
就把它**继承**进 GUI ⇒ 进程活着、日志正常、窗口 `visible=True` 、可用区 800x600, **但根本没有窗口**
(无 X 连接, `xdotool search --pid` 空, `/proc/PID/fd` 无 X11 socket)。
⇒ 重启前 `unset QT_QPA_PLATFORM`; `launch_studio.sh` 已强制 `export QT_QPA_PLATFORM=xcb`。
排查一个正在跑的 GUI 是不是真的在 X 上: `xdotool search --pid <pid>` + `ls /proc/<pid>/fd | grep X11`。

老倪报「点击 open 没反应」时, **别只看代码**: 他跑的就是本机窗口, 取证要直接上 :0。

1. **先看应用自己的 stderr 日志** (`/tmp/studio_launch.log` 这类启动重定向文件; 它运行期也在写)。
   实例: 里面赫然是 `QAction::event: Ambiguous shortcut overload: Ctrl+Shift+O`
   ⇒ **两个 QAction 注册了同一个快捷键 = 两个都不触发** (按钮迁菜单/新加菜单最容易撞)。
   全窗口扫一遍: `for a in win.findChildren(QAction): a.shortcut().toString()` 建桶找重复。
2. **确认框默认按钮 / 初始焦点**: 本项目 `_msg/yes_no` 原本一律 `setDefaultButton(No)` + 按钮写「是/否」
   ⇒ 用户回车/点默认按钮 = **静默取消**, 只剩 2.5s 状态栏一行字 = “没反应”。
   **光 `setDefaultButton(Yes)` 还不够**: 实机初始焦点仍会落在「取消」上, 回车/空格打的是**有焦点的按钮**
   ⇒ 必须 `default + focus + escape` 三个一起钉 (`_yes.setDefault(True); _yes.setFocus(); setEscapeButton(_no)`)。
   Qt 在 Linux 把肯定按钮放**右边** (与 GTK 同), 靠边框色 `#00d4aa` 能定位默认按钮 (PIL 抽像素比 OCR 准)。
3. **一步到位比确认框强**: 打开工程类操作**直接去掉二次确认** —— 在文件对话框选中文件即确认
   (写盘前已全量备份, 漂移对照搬到完成后的报告里)。少一道模态框 = 少一类“静默取消”的坑。
3. **驱动实机看真相**: `xdotool` 可用 (`DISPLAY=:0`, scrot 截图 + tesseract -l chi_sim OCR;
   多显示器时 `wmctrl -lG` 拿窗口几何再 PIL 裁右半屏)。已验证: 点击/按键能进 app (对比截图差异/日得确认),
   `Ctrl+Alt+O` 这类**唯一**快捷键一按就弹文件框 —— 用它区分“接线坏了”vs“快捷键撞了”。
   **写盘类操作看文件时间戳就算成功**: 打开总工程成功 ⇒ `flows/_archive/*_before_space_open_<ts>.json`
   与 `config/calib/*.bak_<ts>` 必然新生; 没新文件 = 压根没走到写盘 (卡在确认那步)。
4. **留痕保障**: 打开/加载工程全链写 `zmax_data/logs/open_project.log` (入口/选了哪个文件/确认结果/
   写盘异常/界面回填+画布场景项数) —— 以后“没反应”直接看文件, 不用再猜。
5. 守门: `tools/verify_shortcuts.py` (枚举全 QAction, **任何重复快捷键判失败** + 默认按钮/动作名/留痕可写)
   已入 `run_gui_verifiers.sh`。

## 🗂 工程文件 (.proj) + 「打开」必须看得见画布 (2026-10-09)

老倪: 「工程文件后缀应该是 proj」、「我点击 open 怎么没反应? 应该打开 simulink 的画布啊」。

* 后缀 **`.proj`** (不是 .zmaxproj); 唯一依据位置 `reports/projects/zmax_space.proj`;
  读档**按内容识别**(schema/kind)不看后缀 — 老 .zmaxproj 照样能读; 对话框列 `*.proj *.zmaxproj`;
  `find_space()`: 新名在就用它, 不在退回旧名。改名/换后缀**只动文件名, 不动格式**。
* 🔴 **“点了没反应”的头号真因 = 打开后跑去别的页**: 原代码把存档里的 `canvas_stack_index`
  当“切到哪一页” (`setCurrentIndex(idx)`) ⇒ 存档存在第 5 页就停在第 5 页, 画布没前置,
  用户看着就是“没反应”(实际唯一依据已写好、备份也做了)。
  **规矩: 打开工程后一律切到 Simulink 画布 tab (`setCurrentWidget(sim)`); 存档里的页索引只当信息不当指令。**
  画布是懒创建的 (启动 400ms) ⇒ `sim is None` 时先 `_init_simulink()` 建出来再切;
  `_init_simulink` 必带幂等闸 (不然重复调用会往 stack 插第二份画布)。
  状态栏/日志明写「已切到 🧮 Simulink 画布」—— 用户看不到变化就等于没干活。
* 取证 `tools/probe_open_space.py` (真建主窗口 + 替身对话框): 判“当前页==画布” 且 “画布场景项 ≥ 250”
  (SimCanvas **不存 self.nodes**: 节点体现在场景 items 上, 89 节点+184 连线 ≈ 272 项;
  别用 `sim.canvas.nodes` 当判据, 永远是 0)。已入 `run_gui_verifiers.sh` 的 open_space 项。

## 📦 小版本迭代清单 (老倪: 「保存数据，小版本迭代」)

> ⚠️ **桌面版出包三个硬教训 (2026-10-08, 坏包连发四版, 判据见 skill `pyqt5-distribution`「冻结包必须验 GUI 启动链」)**:
> ① `.github/` 在 .gitignore 里 ⇒ 改 workflow 必须 `git add -f`(否则 add 整条失败, tag 触发旧打包参数)
> ② `node_logic.py` 是兼容壳(import 仓库外 `src/`) ⇒ 漏带即**双击崩**, 冻结核验只 import 引擎 ⇒ 假绿
> ③ `gui-venv311` 是软链, 内部 CLI shebang 是老家目录路径 ⇒ 直接执行报 cannot execute; 修 `tools/fix_venv_shebangs.py`

细节与命令见 `references/version-iteration-checklist.md`; 一句话版:
①现场数据(`data/` 被 gitignore)先拷进 `docs/data_snapshots/<日期>_<主题>/` + README →
②**六处**版本号同步(`studio.py` · `tools/gui/update_checker.py` · `tools/gui/version_sync.py` · `docs_sync.py` ·
**`tools/ci/integrity_check.py` 的 `EXPECTED_VERSION`**(硬编码常量, 漏改 = 下一版假报警) · `VERSION.md` 表行 + git tag),
且**逐处定点替换、禁全文替换**(实测全文替换会把 `studio.py` 里历史 changelog 行一起改掉) →
③`studio.py` changelog 注释置顶(**行首必须 `#`**, 漏了 = 非法 Python,
`integrity_check` 的 `ast.parse` 会当场拦住) →④`VERSION.md` 表(**无分隔行**, 插在表头正下方) →
⑤`integrity_check`+`repo_guard`+`secret_scan` →⑥`commit -F 消息文件` + `tag` + push + `ls-remote` 核远端。
⚠️ 先自己提交再跑 6h 同步 job —— 它会 `git add -A` 把你的改动卷进 `sync:` 消息。
⚠️ **改版本号前留下的 `*.bak_*` 会被一起提交**(版本迭代的固定回流): 提交前 `git status --short | grep -c '\.bak'` 必须为 0。
护栏是 `.gitignore` 里的 `*.bak*` 规则, 而**加规则时必须用 `git check-ignore -v <一个真实文件名>` 实测**,
不能只 `grep -q` 判"文件里已有这个模式"就跳过追加 —— 实测该模式可能只存在于另一条路径下(`flows/*.bak_*`),
grep 一命中就跳过追加 ⇒ 规则从未生效, 而后面的 `.bak` 照旧进仓。

## 🧷 8793 页左栏新增面板(老倪 2026-10-01「大小、宽度一点都不一样」)

**左栏是 CSS 网格(`.grid{grid-template-columns:repeat(3,minmax(0,1fr))}`)**, 面板默认只占 **1/3 宽**。
要和整行面板一样宽/一样大, CSS 里必须**照抄**这一行: `#p_<id>{grid-column:1 / -1}`
(例: `#p_slots` 有, 新增的 `#p_spaces` 漏了 ⇒ 按钮 166px vs 55px, 老倪一眼看出)。

**验收口径(不靠目测)**: 用浏览器实测两排的 `getBoundingClientRect()` + `getComputedStyle()` **逐项对比**:
面板宽 / 网格容器宽 / 按钮 w×h / 每列宽数组 / fontSize / padding / fontWeight / lineHeight / gap,
全部相等才算改好。实测合格样例: 面板 1241=1241 · 按钮 166×68=166×68 · 7 列 [166×7]=[166×7] ·
字号 17px · padding `12px 4px` · 字重 700 · 行高 22.1px · gap 10px。

**配色按系列分**: 号位=绿(`#0f3d22`底/`#2ea043`边/`#7ee787`字), 空间1~7=黄(`#d29922`底/`#e3b341`边/
`#241c00`字; 未记用暗黄 `#2b2410`/`#6b5a1e`/`#d9b64a` —— **不要用灰**, 老倪要整排黄色系)。

- 🧭 **空间1~7 独立空间点(2026-10-01)**: 页面左下角、号位面板正下方; 与号位**互不影响**的另一套点,
  存 `data/skills/l2_atomic/space_points.json`(号位是 `taught_points.json`)。记录: 页面选号 +
  「✅ 记为该空间点」→ `POST /ctl/record_point {name:'spaceN'}` → `record_l2_point.py --store space`
  (号位走默认 `--store taught`)。服务端 `/ctl/points` 同时带出 `slots` 与 `spaces`(绿=`ready`, 
  空间绿=`recorded`, 空间点**没有下发技能**, 只显示/记录)。新增点位白名单在 `_POINT_RECORD_ALLOW`。
- 🔴 **VL 慢层的"关"是带到期时间的**: `~/zmax_data/vl_guard_off.json {enabled,until,by,note}`,
  `until` 到点**自动恢复**安全闸(常被忽略 ⇒ "昨天明明关了")。现场表现: 每段动作都要等视觉大模型
  裁决 ~25~30s, 日志一行行慢慢走、**不报错** ⇒ 现场看到的是"不动也不报错"。
  老倪现场指令「别等VL」⇒ 改 `until`(如 now+4h)即可**热生效, 不用重启执行器**;
  日志会出现「🛡 VL 安全闸: 已关闭 ⇒ 本条直接放行」。**快层 0.2s 遮挡反射保留, 任何授权都越不过它**。
- 🔴 **技能级速度上限会静默压掉页面设置**: 页面送 speed=200, 但 registry 里 `L2.slotN` 写着
  `speed_max=150` ⇒ 实际下发 150(实测 ROS 请求 `speed=150.0`)。改 registry `speed_max` **热生效**
  (执行器每轮热读 registry, 不用重启)。排查链: 页面 speed 参数 → 技能 `speed_max` → ROS 请求里的数字。
- ⚡ **记点必须本地直读真值文件, 不能每次 SSH 出去采样(2026-10-01)**: 原 `record_l2_point.py` 连采 6 帧
  是 6 次 `ssh tashan@192.168.23.66 "ros2 topic echo --once /robot/tcp_pose"` ⇒ 一次 1~2s ⇒ 记一个点
  十几秒(老倪: 「局域网, 点完 500ms 内要有反应」)。改成读**同源**的本地文件
  `~/zmax_data/rokae_sdk/tcp_out/tcp_direct_<日期>.jsonl`(5Hz, 由 rokae_tcp_sampler 订阅
  `/robot/tcp_pose` 后写盘) + `latest.json`: 读末尾 ~1s 窗口算均值/极差 ⇒ **端到端 21~28ms**。
  守据必留(不满足就退回 SSH 慢路, 绝不猜): 最新帧龄 >2s(采样器卡死) · xyzw/pos ≈0(会话陈旧坏值) ·
  窗口帧数 <4。**旧路只能当 fallback**, 不当默认。
- 🔴 **现场报"点了半天没反应"先查页是否刷新**: 页面 JS 是内联在 HTML 里的, `/station` 虽然 `_send` 已带
  `Cache-Control: no-store`, 但**早已打开的标签页仍跑旧 JS**(旧版点未记按钮只弹提示、不发请求)。
  判据: 服务端日志里没有对应的 `[记录点]`/请求行 ⇒ 请求根本没到 ⇒ 教他 Ctrl+F5 一次, 而不是改后端。

- 🔴 **"MoveIt 规划起点与实时位姿对不上"的根因: tap 的 `jpos` 是冻住的(2026-10-01)**
  现象: 数据空间 `ss_plan` 的 `tcp_path[0]`/起点 xyz 与 8793 实时位姿卡差几百 mm(实测 343.9 / 366.8mm),
  但两者时间戳同一刻。取证(同一刻读两路真值源, 只读):
  · tap `~/zmax_ss_remote/state_*.jsonl` : `tcp` (605.8, -107.5, 190.8)mm ↔ tcp_out `latest.json` `xyz` 完全一致(差 0.0mm) ⇒ **位姿链路没问题**;
  · 但**关节不一致**: tap `jpos` = (-0.1695, 0.4354, -1.8779, 1.9238, 1.9359, -2.4137)(多次读取**一字不变** ⇒ 冻住)
    vs tcp_out `joint` = (-0.3788, 0.0561, -2.2648, 5.0707, 0.2159, -4.51)(在变);
  · `moveit_plan_req.py` 把 tap 的 `jpos` 直接当 `start_joints` 提供给 MoveIt ⇒ 规划起点不是真机姿态
    ⇒ 规划器**自己就在报** `fk_start_pos_err_mm`(366.8mm) — 这个字段就是这条同源闸, 现场用它判。
  待办(未定论, 别猜): 用容器 FK 判哪个关节源对 —— 关节名带前缀 `XMS5-R800-W4G3B4C_joint_N`,
  FK link 名 = `tool0`, 规划器自己就是在域 42 调的 `/compute_fk`; 注意 `bash -lc` 里传 JSON 参数必须
  `shlex.quote`(空格会拆参 ⇒ JSONDecodeError), 且 **ROS_DOMAIN_ID 必须显式 export**。
- 🔎 同源闸字段速查: `fk_start_pos_err_mm`(规划起点 vs 请求时刻真 TCP, 越大越说明起点不是真机姿态) ·
  `end_err_mm`(规划终点 vs goal_xyz, 规划器收敛误差, 几 mm 正常) · `gate_same_source`(0=未过闸)。

## 🔎 数据空间视图(dds_canoe.BusView)顶部搜索

> 全文（位置 / 三个坑 / 无 GUI 环境验证 / 名字对照表 / 判据）见 `references/dds-canoe-busview-search.md`。
> 要点：顶栏 `ed_find` + `lb_find` 按名筛**信号表三组**（报文/信号/节点，不是 Trace）；清空搜索要**递归**取消 hidden
> （`_unhide_all`，根+叶子一起）；`reload(force_tree=True)` 会整棵重建 ⇒ 重建函数末尾必须再跑一次筛选；
> 可搜文本 = 各列文字 + tooltip + column0 的 `Qt.UserRole`；无 GUI 验证用 `QT_QPA_PLATFORM=offscreen`
> + `build_view(None, standalone=True)` + 显式 reload + 跑 1.8s 事件循环（只 processEvents() 得 0 条）。

## 🖵 工具栏按钮 → 开浏览器页 (studio.py / simulink_module.py)
- 开浏览器**必须用独立 profile**, 且 profile 要放 **snap 可写**目录 `~/snap/chromium/common/<用途名>`
  (无 snap 目录才回落 `~/.cache/...`), 配 `--no-first-run --no-default-browser-check`。两条实测原因:
  · 不带独立 profile ⇒ `--new-window` 被**已经在跑的 chromium 实例吞掉**: 页面变成别的窗口里的
    后台标签, `wmctrl -l` 12s 内一个窗都不出现 = 用户说"网页还是没打开";
  · profile 放 `~/.cache` ⇒ **snap(受限)拒写**(浏览器自报 `Failed to create .../SingletonLock` +
    `Failed to create a ProcessSingleton for your profile directory`) ⇒ 进程起来又静默退出。
  · 两个页面要能同开就各给一份 profile(同一 profile 再请求新窗可能只是复用它那一个窗, 实测顶掉前一页)。
- 浏览器 stdout/stderr **落文件**(如 `/tmp/zmax_page_browser.log`); 认窗超时把它最后两行打进日志 —— 
  丢 DEVNULL 的话, "进程起来了但没窗口"这种故障两眼一抹黑。
- **点了先出声**: 主线程立刻回执 → 进程起来报"页面加载中(最多 12s)" → 最后报几何 + 可复制地址;
  任一段静默别超 ~3s —— 用户判"没反应"看的是**日志不出声**, 不是页面的真实状态。
- 已有同类窗口 ⇒ **复用(搬屏+最大化+置前)就返回**, 不关不重开: 关掉重开要白付一次 chromium 冷启(8~15s)。
- 页面**要能从控制台一步打开**: 只能从另一个页面里点链接跳过去 = 用户眼里的"这个网页搞丢了" ⇒ 给工具栏按钮。
- 验收不许靠自报日志: 离屏直调 handler + `wmctrl -lG` 几何断言(`tools/verify_station_button.py` 是模板)。
  两个坑: `self._log()` 的行**到不了** `log_signal`(断言要匹配 `log_signal.emit` 那几条);
  控制台日志面板的内容**不在** `/tmp/studio_launch.log` 里(要留证得自己写文件, 或让用户贴面板原文, 先按它定因)。
- `simulink_module.py` **无模块级** `subprocess`/`urllib`/`socket`(LSP 报错 + 运行时 `hasattr` 双证)
  ⇒ 用到就在函数里显式 import; 这类 NameError 会被周围 `except Exception: pass` 吞掉,
  表现就是"按钮点了什么都不做"—— 找不到原因时先怀疑 NameError。
精确参数 / 失败串原话 / 取证脚本形状 / 拉流漏参丢页见 `references/button-opens-browser-page.md`。

## 🏷 画布节点**改名/移位**必同步清单 (2026-09-24 融合定位实测, 漏一处即静默失效)
画布节点名 = **数据总线通道名** = `node_logic` 注册匹配键, 改名不是改 JSON 一件事。逐处清单:
| # | 位置 | 漏了会怎样 |
|---|---|---|
| 1 | `flows/state_space_obs.json` (node.name/x/y/inputs/outputs + links) | — |
| 2 | `tools/gui/data_world.py` `MODULE_ORDER` | 数据总线/3D/面板排序丢该模块 |
| 3 | `tools/gui/simulink_module.py` `SS_MODULE_TO_NAME` (键+值) | 变量监控高亮不到连线 |
| 4 | `tools/gui/simulink_module.py` 双击面板 `elif "<名>" in nm:` 分支 | 双击弹空白/错面板 |
| 5 | `tools/gui/state_space_sim_real.py` io 发布 dict 键 | **引擎每帧 io 挂不上 → 画布播放无该节点信号** |
| 6 | `tools/gui/state_space_sim.py` (非真实引擎) io 发布键 | 同上 (两引擎必须同源) |
| 7 | `tools/gui/node_logic.py` `_reg(key, [匹配名…], desc)` | 右键/双击「查看节点逻辑」→ match_node=None → 显示"定位中…" |
| 8 | `tools/gui/auto_test_suite.py` 用例判据 (如 TC09 `any("传感器" in n …)`) | **验收用例假失败** (改名后特征字串消失) |
| 9 | `src/lerobot/verification/node_func_tree.py` 显示名 (+ `ss_dreamview` 注释) | 网页功能清单显示旧名 |
验证四件套 (改完必跑): ① `python -c "import node_logic; node_logic.match_node('<新名>')"` 非 None
② `tools/canvas_level_audit.py` → **⚠无执行注册 0 · 真缺口 0** ③ 几何体检: 区内 反向/重叠/交叉 = 0 (新增线也不能引入)
④ `tools/studio_ctl.sh restart` (GUI 无 autosave, 改码+改画布必须重启) 后 `/tmp/studio_launch.log` 的 `Traceback|Error` 计数 = 0。
**备份纪律**: 改前 `cp flows/state_space_obs.json flows/…bak_pre_<改动>_<ts>` (回滚靠它, 不用 git 历史);
过期快照别留在工作树 → 移 `~/zmax_data/canvas_baks_archive_<日期>` + `.gitignore` 覆盖 `.bak_/.bak./.bak-` 三种命名。

## 🧰 画布工具栏: 只移不删, 重要功能必须留可见按钮 (2026-10-09 老倪)

老倪: 「simulink 画布上边的 **状态空间 / 工位总览** 这么重要的功能, 怎么给删除了? 找回来 —— 这两个按钮」。
根因: v5.26.0 那轮「工具栏 11 个按钮全撤到菜单/快捷键」时把这两个也一起撤了 —— **方法都还在**
(`open_state_space` / `open_station_page`), 但画布上没了可见入口 ⇒ 在现场就等于功能没了。

* 纪律: 老倪说「按钮删掉, 需要就在代码里加」时, 把入口分两档 ——
  **① 重要功能 (必须留工具栏按钮)**: ▶运行/⏭单步/⏹停止/🔄重启 · 🧮状态空间 · 🛰工位总览;
  **② 工具类 (可撤到菜单/快捷键)**: 另存为/加载/保存模型/录制/浮动/定位节点/全览/审计/Model Zoo…。
  撤之前逐条问自己「现场找不找得到」; 撤完在报告里**明说撤了什么、现在去哪找**。
* 找回来的正确写法 (只加不减): 在 `SimulinkModule` 工具栏 `tl.addWidget(self.btn_stop)` 之后
  插 `tl.addWidget(self.btn_state_space)` + 新建 `btn_station = mk_btn("🛰 工位总览", …, self.open_station_page, "#58a6ff")`;
  实测工具栏顺序 = 🎯跟随单步 | ▶运行 | 🔄重启 | ⏭单步 | ⏹停止 | 🧮状态空间 | 🛰工位总览 | 🌐数据空间窗口 | ─ | 🔬Model Zoo | 🚀Z700 | 🧩原子 | ⬅返回总系统。
* 判据模板 (tools/probe_canvas_menu.py ④ 段, 6 条, 这套写法可复用到任何按钮):
  ① 按钮对象存在且文本含关键词 ② `isVisibleTo(parent)` 为真 (证明**真挂进布局**、没被 setVisible(False) 藏掉)
  ③ **在类上**替换目标方法 → 新建实例 → `btn.click()` ⇒ 证明「点击真转发到该方法」
  (实例上替换方法无效: `clicked` 在构造时就绑定了旧 bound method, 实测 hit={} = 假绿)
  ④ `btn.receivers(btn.clicked) >= 1` (不是摆设按钮) ⑤ `toolbar.grab().save(png)` 出工具栏渲染图作视觉证据。

## 🚦 发布/出包 (2026-10-01 实测: tag 打了却一个 CI 都没起)
- **GitHub 只跑「被推 ref 那一棵树里」的 workflow**。唯一依据 `MikeBMW/zmax` 的 `.gitignore` 封了 `.github/`
  ⇒ 打 tag 推上去**一个 run 都不会起**。判据: `git ls-tree -r --name-only <tag> | grep .github/workflows`
  必须非空(空 = 那个 tag 永远不会出包); 佐证: `workflow_dispatch` 指定 `ref=tag` 会 422
  "Workflow does not have 'workflow_dispatch' trigger"。修法: 把 `build-win-exe.yml` `git add -f` 入库,
  或把 tag 推到**带 CI 的仓库** `MikeBMW/lerobot-smolvla-lew`(历史 Releases 的 `Z-MAX_Console.exe` /
  `Z-MAX_Console-macOS.zip` 都在那儿)。
- 本机**没有 `gh`**: 盯 CI 从 `~/.git-credentials` 取 token 后打 REST `/repos/<o>/<r>/actions/runs` 与
  `/repos/<o>/<r>/actions/runs/<id>/jobs`(读 `jobs[].steps[].conclusion` 才有"哪一步挂了"的证据)。
  **报告口径: "推送成功" ≠ "发布完成"** —— 必须报 Release URL + 资产文件名/大小, 或失败 step 名原文。
- ⛔ 不用 `workflow_dispatch` 试探 API 通不通: 它**立刻起一次真构建**(按默认分支旧代码 + 产物挂到
  你随手写的 tag 名上)。要探测只碰只读端点。

## 🕳 三条当天踩到并已固化的坑
1. **看板/面板空态不许留白** —— 没在训练时进度条留空 = 现场读不出"上一次是什么时候"。空态必须显示
   **上次训练**(时间 + 结果/步数), 值来自状态唯一依据, 不许前端自造。
2. **重启控制台用独立方式; 判活不许 `pgrep` 自匹配** —— 正路
   `systemctl --user restart zmax-studio.service`(ExecStart 指 worktree 的 launch_studio.sh);
   自查式脚本里 `pgrep -f "<模式>"` 会命中**脚本自己的命令行文本** ⇒ 误判"已有实例"而 33ms 静默退出(假成功)。
   判活用 `ps -eo pid,cmd | grep "[s]tudio.py"` 或剔除自身 pid; 判断训练在跑同理用
   `ps -eo pid,cmd | grep "[j]oint_train_all"` / `nvidia-smi`, 别用 `pgrep -f`。
3. **诊断/探针脚本本身必须先自验** —— 两次因探针写错下错结论: ①连线字段名靠猜 ⇒ 把好节点报成"孤岛"
   (先看真 JSON 的键名); ②`grep -E "a\|b"` 里的 `\|` 被当**字面量** ⇒ 页面明明改了却报"没改"。
   纪律: 探针先在**已知答案**的样本上验证再对目标跑, 结论前换第二种口径交叉核对。

## 📊 状态看板 / 版本唯一依据 (显示口径: 用户要"扫一眼就知道现在在役哪个模型")
出现"给硬件/模型/训练状态做个看板""每个模型要有版本标记"这类需求时, 按这套口径落 (本机面板与手机页**同一套**):
- **版本徽章必须带模型名** —— 只显示 `v20261001-r6` 用户读不出是哪个模型(他的原话: 「现在的 v1001 也不知道是哪个模型」)。
  字段 = `层 + 短名 + 版本`; 短名**从真 `name` 字段派生**(不许手预先固定表), 且**同层多个模型必须互相可区分**
  (两个 INTACT ⇒ `INTACT` / `INTACT-WM`; 两个 SmolVLA ⇒ `SmolVLA` / `SmolVLA-L`), 否则等于没写名字。
  屏幕省面积: 短名 ≤9 字符 + 完整名/完整版本/step/eta **放 tooltip 或点按展开**(手机无 hover ⇒ 用点按)。
- **颜色语义全局统一**: 绿=在役 · 黄=**候选** · 红=异常/未训练 · 灰=未知。**黄灯必须能说出原因**
  (manifest 里每模型带一句 ≤16 字原因, 如「候选: 未证明提升」「候选: 未接入链路」) —— 用户必然问"为什么是黄灯",
  让界面自己答, 别让他来问。
- **`candidate` 是挣来的, 不许为了好看改标签**: 未做**同口径提升证明**(多 seed/留出集/平凡基线) 或适配器还没接进
  在役服务 ⇒ 永远保持 candidate。**灯色的诚实性 > 界面好看**; 训完 ≠ 够格。
- **未知就写 `unknown`, 不许编版本号**: 系统里没有版本证据的模型(画布上无 source/无产物的裸节点)一律标 unknown,
  等它真有了训练版本再改。
- **版本唯一依据 = 一个 manifest 文件**(`src/lerobot/engineering/models_manifest.json`: 层/名/版本/state/产物路径/训练时间),
  面板与页面**都从它派生**, 不许各自在代码里预先固定版本号。**契约只增不改**(多个看板/页面并行读它, 加字段别动老字段)。
- **空态与"最近一次"**: 没有活任务时不留白(见上一条), 显示"上次训练: L4·L3·L2 <版本> ✓ <时间>"; 进行中才给进度条 + %
  + eta。数据取自训练编排写的 `reports/<编排>_*/summary.json` 最新一个。
- 数据源分档标注: 直接探针(有调用计数/帧龄)才能宣称"在推理/在训练"; 拿不到独立计数的层要标为**代理信号**,
  不许把"引擎节拍在动"当成"这一层在推理"。

## 🐛 版本号迭代 (bump_version.py) — 6 处同步 + 1 行历史
`gui-venv311/bin/python tools/bump_version.py --to X.Y.Z --summary-file /tmp/v.txt [--dry]` 自动改:
studio.py 品牌 QLabel + 2 处窗口标题 + changelog 注释行 + `update_checker.CURRENT_VERSION` +
`docs_sync` 两键 + **`version_sync.py` 的 `zmax_ver`** + VERSION.md 表首插一行。
- ⚠️ **`version_sync.py` 的 `zmax_ver` 值不带 v 前缀** (`zmax_ver = "5.13.0"`), 而工具里的 ov/nv 带 v →
  原正则**永远 0 命中 = 静默漏同步** (版本面板长期停在旧号)。2026-09-24 已修 (`ov.lstrip("v")`) —— 若再见到
  `version_sync zmax_ver 旧命中 0`, 就是又被改回去了, 手工补完再修工具。
- 工具**只改不提交**: 先 `--dry` 看逐处命中再去掉 --dry; 之后由调用方 `git add/commit` (打 tag 会触发
  Windows/macOS 桌面包 CI —— 小版本默认只 commit+push, 要出包再单独 tag)。
- 归档照 `tools/archive_release_5_13_1.sh` 模式: 只放真实产物+改动文件+审计证据, 生成 MANIFEST(sha256)。
- **别把 changelog 注释锚点当成版本号**: 版本检索会命中历史行(如 changelog 里的 `# v5.16.35:` 前缀、
  注释里引用旧版的字符串)。"版本号混乱"的真身通常是**同一版本的三种记法不一致**(品牌 QLabel / 窗口标题 / git tag),
  例如品牌位多写一个 `v` 变成 `vv5.x` ⇒ 先去 `grep -rn` 出**全部**出现处 + 列 tag, 再判谁是真的不一致, 别改历史注释。
- **记法统一为单 `v`**(`v5.17.0`); `bump_version.py` 的匹配正则要能吃下老的双 `v`(`v{1,2}`)才能平滑升级存量。
  bump 完必跑 `tools/ci/integrity_check.py`, 要看到"版本号/功能卡/页面字典/导航/类 五处一致"。
- **界面上不许留第二处旧号**: 状态栏/关于框这类角落常有独立硬编码的陈旧版本(如仍写 `v1.0.4`/`v1.0.1`),
  顺手一起对齐 —— 留一处就会出现"他截图问你这儿怎么还是旧版本"。
- 版本号是**启动时读代码字面量**的 ⇒ 已跑的实例不会自更新: bump 完必须重启控制台, 验收看**窗口标题**里是否带新号
  (不带 = 起的是旧码/旧 worktree)。

## 🧹 哨兵/任务清理判据 (2026-09-24: 18→9 条)
删之前**逐条查终态证据**, 只删"目标已终态"的 (脚本留在 `~/.hermes/scripts/`, 需要时一行重建):
`ls <flags>` 已报过 (`.four_tasks_reported`/`zmax_release_watch_<tag>.done`) · 流水线 `status.txt=DONE`+`RC=0` ·
被监视目录 >24h 无新文件且**无相关进程** (`ps aux|grep`) · 远端口令失效(permission denied) · 一次性公告已过期(旧版本号)。
保留三类: 基础设施 (sys-watchdog/数据链路/磁盘红线/技能记忆同步) · 活跃项目哨兵 · 现场工具 (仍 pause 待现场的不删)。

## 🧰 汇总终端: curl 可复制 + 终端页 + 图片右键复制 (2026-09-24 实测)

老倪四条要求对应的做法 (已落在 `tools/gui/aoi_inspect_console.py`, 可照抄):

1. **"curl 命令显示在窗口, 我复制后在终端执行"** → 让客户端把**等价命令**带出来: 在统一出口
   `_curl()` 里按同一组参数拼 `curl -s -m {timeout} -X {method} '{url}'` (+ binary 时 ` -o frame.png`),
   via=orin 时拼 `sshpass -p <pw> ssh <orin> "…"` → 放进 `info["cmd"]`, 再透传到 meta/dict (`_cmd`)。
   ⚠️ 别在窗口里手写命令字符串 —— 会与真实请求参数漂移, 必须同源生成。
2. **"要有个终端看 JSON 反馈"** → 独立 Tab〔终端〕: 上=命令框(只读等宽, 最多 400 行) 下=JSON 原文
   (带 `[HH:MM:SS]` 时间戳, 800 行); 每行都可选中复制, 配 [📋复制命令][📋复制反馈][📋复制命令+反馈][🗑清空]。
   本地图像处理 (如过曝切除) 也往同一页打, cmd 传空串即可。
3. **"每个技能点击即可执行得到结果"** → 技能 = 真函数 + 结果落可见位置: 推理类写判决表/缺陷表,
   服务类写终端 JSON + 日志; 验证时**逐个 `.click()` 断言产出** (不许只看按钮存在)。
4. **"图片右键即可复制, 可粘贴到别处"** → 画面控件换子类 `CopyImageView(YoloLabelWidget)`, 复写
   `contextMenuEvent`: **编辑态且命中框时不弹菜单** (保住"右键删框"既有行为), 否则弹
   复制图片/复制图片路径/另存为/画面信息。
   ```python
   md = QtCore.QMimeData(); md.setImageData(img.copy())
   if path: md.setText(path)                 # 粘到文本处=路径, 粘到图处=图片
   QtWidgets.QApplication.clipboard().setMimeData(md)      # ✅ 一次性
   ```
   ⚠️ **实测坑**: 先 `clipboard.setImage()` 再 `clipboard.setText()` → **图片被冲掉** (剪贴板只保留一份 mime
   载荷), 表现为"复制成功但剪贴板 0x0"。另外 **offscreen 后端的 `clipboard.image()` 恒 0x0** →
   剪贴板类断言必须放**真桌面**(DISPLAY=:0)跑, offscreen 里只能验 mimeData/逻辑。
   ⚠️ 同族坑: 在 DISPLAY=:0 下**先 import cv2 再 import PyQt5** 会抢走 xcb 插件 (报 "Could not load the
   Qt platform plugin xcb") → 测试脚本里 PyQt5 必须最先导入。

## 📋 画布节点「右键打开新窗口」标准做法 + 汇总终端 (2026-09-24 外观质量检测实测)

**三处接线 (缺一处点了没反应/无菜单项)**:
1. `simulink_module.py` `SimCanvas._show_node_menu`(RightButton 分支) 加菜单项, 触发条件用**节点名子串**
   (`"外观质量检测" in item.node.get("name","")` 或 `params.<flag>`; 同 YOLO 的 `"YOLO" in name`)
2. 同函数下方**动作分派链**加 `elif a_xx is not None and chosen == a_xx:` 分支, 帧源跟随画布:
   `_src = "sim" if _canvas_src_state(self.module) == "仿真" else "real"`
3. 新窗口模块 `tools/gui/<name>_widget.py` 暴露 `open_xxx(parent, module=..., source=...)` (单实例复用:
   类属性 `_cur` 存实例, 再开先 close)
4. ⚠️ 改完 GUI **必须重启** (`bash tools/studio_ctl.sh restart`) 入口才活; 日志 `Traceback|Error` 计数=0 才算通过

**汇总终端窗口骨架 (质量检测汇总终端为样板)**: 三行头 (①技能行 ②标定行 ③数据/训练行, 全常显) +
QSplitter(左画面 `YoloLabelWidget` / 右面板 判决表→定位→缺陷清单→训练日志) + 状态栏 (链路/判决/导出);
快捷键 `Enter/N/F/G` 且**焦点在输入框时不抢键**。

**复用既有件 (别重写)**: 标定控件 `yolo_label_widget.YoloLabelWidget`(拖框/缩放/右键删/撤销) ·
数据层 `yolo_annot_dataset`(`save_sample/build_dataset/check_dataset/iter_samples/add_class`) ·
训练 `yolo_annot_train.py`(体检不过退出 2, 训练后真推理验证)。

**四个实测坑**:
1. **`save_sample` 的 boxes 契约是 5 元组 `(x1,y1,x2,y2, cls_id|cls_name)`**, 不是 `(box, cls)` —
   传错在 `float(b[2])` 处炸, 被 try/except 吞成"保存失败"(静默), 排查时先看落盘数没涨。
2. **QProcess 信号里别引用 `self._proc`**: 进程结束时 C++ 对象已删 → `RuntimeError: wrapped C/C++ object
   has been deleted`。用默认参数绑进闭包 `lambda pr=_p: ...`。
3. **关窗必须收口**: `closeEvent` 里 `disconnect()` 三个信号 + 若在跑则 `kill()`; 否则进程收尾信号打到已销毁
   控件 → RuntimeError → **进程 abort (core dumped)**。`log()` 也加 try/except 保障。
4. **`load_frame_file` 要分支视频**: `cv2.imread` 读不了 mp4 → 走 `cv2.VideoCapture` 取首帧。

**验证套路 (两层, 记取"offscreen 全绿≠人能用")**:
`tools/verify_aoi_console.py` (offscreen: 入口可达性 `isVisible() and isEnabled() and width()>20` · 四技能判决表 · ROI 拉伸尺寸 ·
标定落盘计数 · 体检 · 构建数据集 · 导出 · **真训练 smoke 产出 best.pt**) +
`tools/verify_aoi_console_real.py` (真桌面: 窗口在 availableGeometry 内 · 按钮 `width() ≥ sizeHint().width()` · 截图)。

## 🌐 功能清单/测试用例 → 网页 (datadrive.world, 2026-09-24 新增 L2 专项页)

**唯一依据三处 (改功能/用例只改这三处, 网页全部自动带出)**:
| 内容 | 文件 | 关键点 |
|---|---|---|
| 功能定义 | `src/lerobot/verification/capability_levels.py` | `CAPABILITY_LEVELS[层]["funcs"]` = {fid,name,desc,groups} |
| 测试用例 | `src/lerobot/verification/verification_layer.py` | `FEATURES` 元组 `(id,域,名称,源,方式,方法,层)` + `FEATURE_META[id]=(kind,role,spec)` + `def t_F_B12(self, np)` 真断言 (返回 `(bool, 详情str)`) |
| 分层功能树 | `src/lerobot/verification/node_func_tree.py` | `NODE_TREE[节点key]["funcs"]` 每 func 带 `tests:[(名称,auto/semi/manual,方法名,备注)]` |

**生成 + 部署 (深色主题 #0d1520/#00d4aa, 打印友好)**:
- 功能清单总表 + 需求规格书: `tools/gen_web_feature_pages.py` → `reports/web/{function-list,requirements-spec}.html`
- 专项页 (L2 3D视觉引导/触觉反馈闭环, 含 Markdown 导出): `tools/gen_l2_guide_tactile_page.py`
  → `reports/web/l2-guidance-tactile.{html,md}`, 顶部按钮「⬇下载 Markdown / 📋复制 Markdown」,
  **现场真跑**两条用例把 PASS+实测明细写进页面 (`--no-run` 跳过)
- 上传: `ZMAX_ECS_PW=<密码> python <工具>` 或 `sshpass -p <pw> scp 文件 root@39.102.211.79:/www/wwwroot/datadrive.world/` + `chmod 644`
  (**22 端口**; 23 端口连不上) → 复核 `https://datadrive.world/<页>.html`
- ⚠️ **主页 `index.html` 只在 ECS 上, 仓库里没有源**: 改导航要 `scp` 拉回本地 → 本地 patch (锚点断言 count==1) → `scp` 回传 → HTTP 复核
- 计数类文案别手写: `tools/canvas_update_verif_nodes.py` 从唯一依据重算并刷新画布 `ssfeat`/`sstest` 的 `desc`
  (加用例后 "B六层 11" 这类数字会过期; 该脚本幂等, 改画布前先 `bash tools/studio_ctl.sh stop`)

**测试用例写法纪律**: 阈值必须**先实测再写** (`tools/measure_l2_guide_tactile.py` 这类量测脚本先行),
断言里带上"判据 + 实测值"字符串; 口径不确定时先核对唯一依据 (实例: 触觉通道 0 = 原始开度, 轨迹 gripper = 夹紧度 = 1−开度
→ 必须用**互补一致率**断言, 按"相等"比会得 0%); 未实现/占位通道要**如实标注**不得冒充。

## 架构速查

```
tools/gui/
├── studio.py              # 主程序 (PyQt5) — 入口
├── docs_sync.py          # 文档同步系统 (GitHub API + 分类 + 版本追踪)
├── ppt_engine.py         # PPT 指令引擎 (PPT作为控制台指令源)
├── update_checker.py     # 自动更新检查 + 下载升级
├── Dockerfile             # 轻量 X11 挂载容器化
├── Dockerfile.win         # Wine 交叉编译 (备选)
├── docker-run*.sh
├── version_sync.py        # 版本信息面板
├── training_backend.py    # 训练后端
├── hardware_simulator.py  # 硬件仿真
├── inference_client/server.py
├── dataset_viewer.py
├── le_robot_studio.py     # 简化版
└── le_robot_home.py

.github/workflows/
├── docker-console.yml     # CI: tag v* → build → push 阿里云 ACR
└── build-win-exe.yml      # CI: tag v* → PyInstaller .exe → Release
```

**三层解耦架构**: Sys-0 ← Sys-11+12 ← System 2

**9 大模块**: 系统架构 / 数据集 / 训练 / 推理服务 / 硬件仿真 / 评估 / 配置中心 / 实时监控 / 插拔场景

## 常见操作

> 📄 全部常见操作 (训练/评估/视频/报告/飞书/配置表/画布节点/数据集 等) 见
> `references/common-operations.md` — 2026-08-25 从本文件拆出 (SKILL.md 曾撞 10 万字符上限)。
> UI 尺寸适配 (按钮太小/字挤/面板太窄/高分屏) 见 `references/ui-sizing-hidpi.md`
> (含实测探针 `tools/probe_ui_metrics.py`)。

## 陷阱

> 📌 **systemctl 反复弹「需要验证」授权框**: 根因是 `/etc/polkit-1/rules.d/` 为空 ⇒ 普通用户
> `systemctl start|stop|restart` 一律要求授权, 而 `restart_traj_ar.sh` / `start_station_stream.sh` /
> `cam_stream_guard.py` / `simulink_module.py` 都是**不带 sudo** 直调 systemctl ⇒ 每动一次 `zmax-*` 服务就弹一次。
> 修法: 装 `/etc/polkit-1/rules.d/49-zmax-units.rules`, 只对 `unit.indexOf("zmax-")===0` 且
> `subject.user==="ubuntu" && subject.local && subject.active` 返回 `polkit.Result.YES`, 再 `systemctl restart polkit`。
> **别全局放开** —— 其它服务要保留授权边界。验证 = 不带 sudo 重启后不弹框且 `is-active` 为 active。
> 📌 **Orin 生产设备红线 (2026-09-16 老倪: 「不要在orin上增加新程序…你先只是转发orin的感知信号」)**:
> Orin 侧**零自研程序零自启** (我此前放的 ss_edge/ss_shadow/ss_infer + crontab `@reboot` 已全清);
> 采集改走 **4060 侧 Docker 远程只读订阅** (`ros:humble --network host` + `ROS_DOMAIN_ID=0` 可直读 Orin 生产话题,
> 实测 tcp_pose 49.79 Hz / real_joint_states 100.43 Hz); 采集节点 `enable_rosout=False` **零发布** (self_publishers 自证,
> `/parameter_events` 关不掉要如实说明); 标定桥 z7 缺现场几何 → **拒算不编造**。细节 + 两坑
> (`ssh` 上 `pkill -f` 模式串出现在自己命令行会自杀 → 锚定 `^python3` 或按 PID; `/tmp` 备份会被清理 → 写 `~/zmax_data`)
> 见 `references/orin-zero-program-remote-read-2026-09-16.md`。
> 📚 历史细节(2026-08-05~09-14: 三模型对比下半场 · CrossAttn/子系统 · auto_loop 闭环守护 ·
> 多分身共享 git · 画布边与代码通路一致性 · 记忆层集成阶梯) 已搬到
> `references/history-2026-08-and-09-details.md` —— 需要过程/实测数字时按需读。
> ⚠️ **2026-09-14 追加 (v5.5.48, 这条把上面两条都盖住了)**: 记忆层当时**被喂错了坐标系** ——
> 桥传 `s.peg_head()`, 而冠军轨迹/引擎肌肉记忆用**夹爪真实位置** (引擎 `self.x = obs[0:3]`,
> state_space_sim_real.py:634)。同一 seed 下两者差 (0.017,0.054,0.176)m ⇒ 势场在**自己坐标系之外**求梯度,
> 意图=噪声。所以"记忆层没效果"主要是这个 bug, 不是(只是)权重问题。
> **判据/自查**: 用 `tools/mem_field_probe.py` 打坐标系对照 —— 同源时 `d_perp` 应 ≈ 0 (~1e-4),
> 异构时 ~0.13m; 同源时相位会正常 SK01→SK07 推进。**任何"记忆层没效果"的结论, 先查这一条**。

---

## 🧠 v6: 让 L4 的 INTACT **看到并复用 L2 原子技能** (2026-09-14 老倪下令, 已落地)

**契约 (改顺序=换版本)**: `skill_ctx` 24 维 = `[引擎相位 one-hot(13) | L2 势场技能软权重 w(8) |
d_perp(1) | arc_frac(1) | grip(1)]`, 单一事实来源 `src/lerobot/policies/intact/skill_ctx.py`
(采集器 `tools/intact_insert_dataset_v5.py` 与闭环桥 `tools/intact_sw_optical_bridge.py` **共用同一函数** →
训练/推理同口径; 有 `tools/skill_ctx_consistency_check.py` 做同口径回归)。

**模型侧零回退构造 (关键)**: `IntentActionActor(skill_dim=24)` 新增 `E(s)` 分支, 但
①`skill_dim: 0` 是默认值 → 参数形状与老配置逐字节相同, 老 ckpt 仍能 `strict` 加载;
②打开时 `skill_enc` 末层**零初始化** 且 入口层 `net.0.weight` **老列逐位复制 + 新列置零** (缺后者
暖启动会差 0.43 — 入口层形状变了被部分加载跳过, 随机初始化污染全网络, 自检检查 C 抓出来的);
③`get_action` 里 skill_dim>0 却缺 skill_ctx → **直接报错, 不许静默降级**。
自检: `INTACT-JEPA/tools/intact_skill_channel_check.py` 五条闸全过才算接上。

**"有提升"判据 (老倪 09-12 口径)**: 同一权重同一批真帧跑 `--skill on` vs `--skill zero` (全零消融)
→ 判三条: 赢常数基线 ∧ `MAE(on) < MAE(zero)` ∧ 预测std/教师std ≥ 0.30。
哨兵 `/home/ubuntu/.hermes/scripts/v6_judge_watch.py` (cron, 静默无新 ckpt)。

**坑 (踩过的)**:
- `project_polyline()` 返回 **(最近点, 距离, 弧长, 段号) = 4 元组**。按 3 元组解包 → 每帧 ValueError
  → 被引擎 `_frame_sink` **静默吞掉** → part npz 里**整列 skill_ctx 都没有**, 而日志一切正常 ✗✗
  (老倪红线: 静默降级 = 白做)。教训: sink/回调里的构造失败要显式 raise 或至少记 `_SKERR` 进 meta。
- 采集器 flush 时 `np.savez_compressed(p, **kw, ...)` —— `kw` 忘了 `**` → pixels/action/observation
  全不落盘, 文件只有几 KB 而日志说"窗口 18" ✓ 假成功。**落盘后必须验 keys + 帧std>5**。
1. **场权预先固定太低**: `blend_action` 里 `w = w_max·max(conf, w_floor)`, 桥用 `w_max=0.5`, `w_floor=0.2`,
   而现场 `conf ≡ 0` (离最近轨迹管 207mm) ⇒ w̄ 恒 = **0.1** → 10% 的场权扳不动 600mm 模型误差。
   已修 (增益调度): `far = clip((d_perp−d_near)/(d_far−d_near),0,1)`, `w = max(w_max·max(conf,w_floor), w_far·far)`,
   默认 `w_far=0.85, d_near=30mm, d_far=150mm` —— **在管内维持原公式 (不回退), 远场让场主导**。
2. **模型动作塌缩**: `IntentActionActor` 输入 = 潜槽 (z_t, m_t, z_t·m_t) + a_{t-1} 嵌入, **没有本体/几何输入**;
   而数据集 `optical_insert_v4.h5` 里明明有 `observation` (39D) —— 但 `grep observation train.py jepa.py module.py`
   **零命中 = 这个状态通道从来没人消费**。亚毫米插入能从 224²/patch14 的潜空间补出来吗? 补不出来 →
   动作头预测条件均值 → 幅度只有教师 7~22% (v3/v4/v5 全如此) → 输给常数基线。
   → 这是"模型直驱"这条路的天花板, 也是**记忆层势场存在的意义** (Φ 用引擎真几何/冠军轨迹建)。

**其它落地铁律**:

老倪口径: "集成 L2肌肉/L3流程/L4工作/总装记忆… 稳步推进… 要看到最终成功抗干扰的插拔… 能力要稳步提升不要波动,
数据一致性最重要"。落地三条铁律:

1. **抗干扰必须真注入** (本次查出的关键缺口): 桥原来 `sim.run(max_steps=…)` **不传 cap** → 引擎 `_jitter_on=False`
   ⇒ L4 链从来没被注入过干扰 (引擎里只有 `cap=='l4'` 才注入来料移位/转向 ±3.5cm/±15°物理/90°转台视觉 + 恢复预算×2)。
   现在桥有 `--cap {l2,l3,l4}` 并透传 → **解析链与模型直驱同吃一份干扰** (同口径); 每格结果必须记真实干扰元数据。
2. **同口径阶梯台** `tools/mem_ladder_integration.py`: 每次跑先冻结 manifest (权重 sha256+epoch · 反归一化 stats
   sha256+action_space · 记忆开关快照 · 引擎/桥/势场源码 sha256 + git rev) → manifest_hash 不同就是不同历史行;
   矩阵 = 5 臂 (off/L2/L23/L234/assy) × 2 干扰档 (none=cap l3 / disturb=cap l4) × N seed, **每格跑完 append**
   → 断点续跑; 6 道闸: N1 L2 准确性 / N2 L23≥L2 / N3 抗干扰 (干扰档 ≥ 自身无干扰 −1/n 且 ≥ off 干扰档) /
   N4 总装 ≥ 任一臂 / N5 零搜索 (candidate_sequences=0 且 调用/步≤1.05) / N6 稳定 (跨 seed 深度 std≤25mm)。
   历史 append-only `reports/mem_ladder/ladder_history.csv` → 跨 ckpt 同一格直接对比 = 能力提升可追溯。
3. **无人值守**: `~/.hermes/scripts/mem_ladder_watch.py` (no_agent cron 每 20min, 静默=无变化): 崩溃格报告 /
   进程死且格未跑完**自动重启**(阶梯可续跑, 所以重启安全) / 新汇总结论推飞书。
   ⚠️ cron 建任务时 schedule 必须写 `every 20m` (只写 `20m` = 一次性!)。
4. **语义提醒**: 引擎在干扰轮会**主动旁路 L2 肌肉记忆** (标杆按摆放固化, 布局变了标杆失效 → 正确降级全精算伺服)。
   即"抗干扰"这档本来就主要靠 L3/L4, 阶梯表里干扰档 L2 介入下降是**预期**而非回退 —— 但要在报告里说明, 不能当卖点。

## 🚀 L4 INTACT 策略化 + 连线 (v5.5.40, 2026-09-13 — metaworld → INTACT → decoder → L3)
老倪: 「将 INTACT 接入 L4 层, 把 L4 节点的 INTACT 代码迁移到 src/lerobot 的 policies 文件夹, 做好连线;
数据源直接接入 metaworld, 输出接一个 decoder 再进 L3; **不能让原有 L2 L3 能力下降**」。
- **代码落位**: `src/lerobot/policies/intact/` = `configuration_intact.py` (注册名 `intact`) +
  `modeling_intact.py` (`IntactPolicy`: select_action / predict_action_chunk / predict_intent;
  `forward()` 显式 NotImplementedError = 不假装本仓能训) + `decoder.py` (`IntactIntentDecoder`) +
  `runtime/` (**原 `src/lerobot/manifold/intact_node/` 整体 git mv 进来**, 实现一字未改)。
  旧路径 `manifold/intact_node/__init__.py` 只剩兼容转发 → 桥/自检/引擎/工具零改动。
  注册三处: `policies/__init__.py` · `factory.get_policy_class("intact")` · `PreTrainedConfig.register_subclass`。
- **数据源直连 metaworld**: `runtime/metaworld_source.py` → `MetaWorldSource` (MT1 peg-insert-side-v3 ·
  camera corner2 · `env.render()` 224² 真渲染 + `_get_obs()[:39]` 现场读 + 本域真实目标帧
  `reports/intact_goal_frame_optical.npy`), 注册名 `metaworld` (与 `l4_episode`/`official` 并列)。
- **解码器两路** (`decoder.py`): ① `u_ff` 先验 4D = `act×K_ACT` (K_ACT **现读引擎源码**, 量纲逆运算,
  **无需标定**) ② L3 流形条件 = 需 `models/intact_l3_map.json` (闸值 R²>0.3 且 null<0.1);
  未标定 → **拒绝返回并计数** (`cond_src="拒绝(未标定)"`), 绝不预先固定映射。
- **画布连线** (77 节点/83 连线): `ssdata →💾→ ssintact`(🎯 INTACT 策略, L4 行) `→ ssintact_dec`(🎯 INTACT
  意图解码器, L4 行) `→ ssdec`(L3 DiT)。**两节点都在 L4 行内 (cap=4) → L2/L3 档根本不执行** = 结构性零回退。
  改 flows/state_space_obs.json 用**文本级替换脚本**(正则锚点 + 断言其它节点逐字段不变), 别 json.load+dump。
- **引擎三档** (`state_space_sim_real.py`, 与既有 `SS_INTACT` 同纪律): 不设 `SS_L4_INTACT` = 逐位零变化 /
  `_SHADOW=1` = 影子(真渲染帧→真推理→真解码→记录, 不接管) / `=1` = 按 w 融合
  `u_ff=(1−w)·analytic+w·L4` (w=0 恒等)。取证: `sim.l4_intact_summary()` (calls/reuse/refused/blend/
  w_zero/frame_std/shift/goal_src/u_ff_src/l3_cond_src/err)。
- **工具**: `tools/l4_intact_ab.py` (A 关 / B 影子 / C 接管, **逐臂子进程**隔离 env, 同 seed 同 cap) +
  `tools/l4_intact_arm.py` (单臂) + `tools/verify_l4_zero_regression.py` (画布执行集按档位对比 git HEAD)。
- **实测**: 节点级真跑 (真权重 trained=True · chunk(8,8) · `candidate_sequences=0` 零搜索 · 1396ms/步 CPU ·
  动作维自动对齐 4→8); 三臂 seed0/1 700 步: A `dist 0.0186/0.3891` · B **逐位相同** + 真推理 78 次 ·
  C `0.126/0.1221` + blend 700/700 步 → **无提升证据** (只证明通路真在跑, 提升待 v5 权重配对复验)。
  零回退: L2 档 55 / L3 档 60 节点逐 id 不变, 原有 80 连线全在。
- **两个必修的坑** (A/B 首轮抓到): ① 未设 `STABLEWM_HOME` 时桥退回 `<repo>/.cache` → 权重全找不到
  (`FileNotFoundError: Checkpoint not found`) → adapter 改为优先共享缓存 `stable-wm-cache`;
  ② 引擎"直喂帧"路径没人设 goal → `goal_displacement` 每帧 `ValueError` (**影子臂 60/60 次"真推理"实为空转,
  计数照涨**) → 节点加 `ensure_goal()` 三级保障 (已 set_goal > 数据源自报 > 默认目标帧文件), 兜不到才显式报错。
  **教训: `calls>0` 不能单独当"真接入"证据, 必须同看 `err`/`reuse`/`u_ff_src`/`goal_src`。**
- 复现: `INTACT_RUNTIME=root INTACT_DEVICE=cpu INTACT_POLICY=intact_goal_optical_insert_v4_s3072/weights_epoch_2.pt
  gui-venv311/bin/python tools/l4_intact_ab.py --seeds 0,1 --max-steps 700 --cap l4`
  · 设计 `docs/design/zmax_l4_intact_policy.md`

### 🎨 画布排版硬规则 (v5.5.41 — 改 flows 坐标前必读, 否则算出来的摆位全废)
画布**加载时会自己重排**, JSON 里的 x/w 只是输入:
- 普通节点最小 **w≥280 / h≥110** (`simulink_module.py:5146/5147`) + `autofit_node_width` 撑宽到不裁字(≤380)
- `_relayout_row_gaps(min_gap=56)` (12044 行): 按 **`round(y/60)` 分桶**, 桶内按 x 排序, 后一个节点必须
  `x ≥ 前一个.x + 前一个.w + 56` (**行首 x 不变**) → 想让某节点 x 自由, 就把它放到**不同的 y 桶**里
  (差 ≥60 即可分桶; 但 110 高的框要差 ≥110 才不重叠)
- 连线端口: 起点 `ax = src.x + src.w`(源右缘), 终点 `bx = dst.x`(目标左缘) (`SimLinkItem._path:3298-3305`)
  ⇒ **"右出线连到左入线" 判据 = ax > bx**; 要竖直线 ⇒ `src.x+src.w == dst.x`
- row_bg 行带加载时会被统一左移到 `minx-266` 并右界不变 (5174-5190)
- 所以: 布局要**按规则反推坐标**; 改完必须用真画布取证 ——
  `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l4_layout.py`
  (加载真画布逐条量 ax/bx + 渲染 PNG) 而不是只算 JSON 里的 x/w
- 教训 (本次踩到): 我先按"配置坐标 = 渲染坐标"排了一版 → 画布把同行节点右推 36px, 那条线照样倒退。
  量出来是 `240+300+56=596` 的规则在起作用。
- **端口 slot 只认 link 数组先后, 与 `in1/in2` 命名无关** (`SimLinkItem._path:3289`):
  `ay = src.y + h·(i+1)/(n+1)`, `i` = 该连线在该节点**出/入线里的序号**, `n` = 总条数。
  所以"让连线整体不乱穿"的正解 = 把 `flows/*.json` 的 **`links` 数组按 `(src.y, src.x, dst.y, dst.x)` 全局排序**
  (同一节点的出线/入线 slot 就单调于来向 → 两两不交叉), 排序对逻辑零影响; 想改端口几何就调 link 在数组里的位置。
- **用户视角加载路径 = `open_state_space()`** → `load_flow_file()` **+ `_relayout_row_gaps()`** (11140 行)。
  取证脚本必须显式补调一次 `m._relayout_row_gaps()` —— 少这一次, 量到的就不是用户看到的画布
  (本工具早期版本踩过: 反向线少报 1 条、方框重叠多报 15 对)。
- 工具: `tools/relayout_canvas_l4_row.py` (可复跑摆位: 备份 + 坐标表 + 全局连线排序) ·
  `tools/verify_l4_layout.py` (真画布体检: ①反向 ②重叠 ③穿框 ④交叉 ⑤关键链 ax/bx ⑥L4 区+全画布 PNG)。
- **"变成一层"的代价要诚实说**: 老倪要 L4 一层 ⇒ 5 个节点同行 ≈1660px 宽 ⇒ 下游 (DiT/前馈/状态机/执行器/
  物理世界/验证/可视化) 必须依次右移 (本版画布右界 +1300px); 且两个**语义闭环回流**线
  (物理世界→状态校正器 `↩观测反馈`, 引擎→渲染源 `↩渲染回流`) 天生反向, 消不掉, 只能标 `↩`。
- L2 技能行 11 节点 (通用算子 A/B/C + SK01-08) = 3640px 行宽 > 执行器 x ⇒ SK04-08→执行器 5 条反向;
  正解是**把执行器挪到该行尾右侧** (不是拆成两行 —— 老倪明确要一层), 顺带 +185px 让 L4→通用算子的出线也前向。

## 🧲 分层记忆势场 (v5.5.38, 2026-09-13 — L2/L3/L4 + 总装机记忆联络, 与 L4 INTACT 链对接)
老倪: 「把势场逻辑实现到 L2肌肉记忆 / L3工艺流程记忆 / L4物理工作空间记忆 / 总装机记忆的联络策略,
然后逐步打开每层记忆提高 L4 INTACT 性能」。
- **统一接口 = 标量势场 Φ(x)**, **−∇Φ = 意图** (不传技能标签)。L2 `Φ_SK` (谷底=冠军轨迹真末点, σ=谷宽,
  λ=4·k_att·σ², 锥形项 k_lin=3·k_att·σ) → L3 `Φ_process=Σw_k(t)Φ_SK` (Σw≡1, raised-cosine 交叉淡入) →
  L4 `Φ_global = Φ_process + Φ_obstacle(孔壁/台面现场几何) + Φ_world(世界模型预测项, 未接恒 0 且标记)`。
  代码 `src/lerobot/memory/potential_field.py`, 画布节点 `🧲 总装机记忆 · 势场联络` (mem_nodes::node_ss_mem_field)。
- **逐层开关 = data/memory_layers.json** (`L2/L3/L4/assembly`, **默认全关**): 全关 → compose=None /
  blend_action **恒等** (零回退, 可断言); 开层后 L4 INTACT 链按 `u=(1−w)u_model+w·u_field`,
  `w=w_max·max(conf,w_floor)` 混入 −∇Φ 意图; **相位按状态判** (时钟进度与模型直驱不同步)。
  台账 data/assembly_memory.json; 仲裁: 接触段 L2 优先 / 自由段 L3 优先。
- **实测 26/26** (真数据: muscle_memory 7 条冠军轨迹 + 引擎真几何): 梯度误差 1e-9 · 横向势单调 ·
  收敛 98~127 步到 <1mm 且 Φ 严格降 · Σw≡1 · 孔壁斥力双向正确 · 逐层开关逐项生效。桥 e2e: 全关 0 介入 / 开 L2 介入 120/120。
- **⚠️ 三个必须记住的设计约束 (都踩过)**: ① 谷底只能取 champ_x 末点 — muscle_memory 的 io.entry/exit
  **锚点不同源** (差 15~145mm, SK06/07≈PEG_HEAD_OFF_XY=0.13), 用 io.exit 当谷底会导致场的最小值不在谷底 → 不收敛;
  ② λ 必须按 λ=4·k_att·σ² 归一 + 加锥形项 k_lin, 否则短轨迹会出现离谷底 3~5mm 的次极小 (流量停住);
  ③ muscle_memory.json 是**活数据** (rollout 会更新), 判据数字会漂移, 别预先固定。
- 📄 详见 `references/memory-potential-fields-2026-09-13.md`

## 🌍 L4 · 光模块插拔链 (v5.5.37, 2026-09-13 — 红方块抓取 → 光模块抓取插拔)
老倪: 「把红色小方块的抓取实验, 改造成光模块的抓取插拔实验」。
四节点与 cube 链**同构**, 只换任务: 🧪 环境渲染图像源 → 🎯 INTACT 插拔策略 (本域微调) →
🌍 Z-MAX 引擎 RealStateSpaceSim (metaworld 真物理) → 🎬 插拔渲染视频。
- **切任务** = `data/intact_sw_task.json` (`optical_insert` 默认 / `cube` 保留), **不埋代码分支**;
  `data/intact_sw_policy.json` 可指定 policy/stats/mode/seeds/device。cube 旧桥不删。
- **两个 venv 分工**: 引擎跑 `gui-venv311` (只有它有 metaworld), 模型由 `IntactRuntime` 起
  **INTACT venv 子进程** (gui venv 无 torch 链)。cube 链相反 (env 在 INTACT venv 里)。
- **动作口径**: v4 数据集动作列 = `sim._u_vec` (m/s) → 闭环必须按引擎自有约定还原
  (`act[:3]=clip(u/K_ACT)` · `act[3]=CLOSE if u[3]>0.5`) 再给 `env.step`; 统计用
  `tools/action_stats_from_h5.py` **现算** (权重/统计同源, 不许手写)。
- **⚠️ 最坑: stale status 竞态** — 上一轮 status.json 还是 `stage=done` 时, 节点等待循环首轮即
  判"本轮跑完" (实测光模块链读到 cube 终态: env=OGBCube / 52 帧 / cube 视频, 校验全红却查不出因)。
  修法: `_sw_start` 在 Popen **之前**先写 `{"stage":"starting"}` 作废旧状态。
  判定法: 报错里出现"上一轮的任务名/帧数" = 读到旧 status。
- **验收**: `tools/verify_l4_optical_chain.py` 节点级 11/11 (真跑整链): 1800 帧 · 1800 次真推理 ·
  frame_std 56.5 · 解析链 2/2=100% (插入 65.13/64.78mm · 全链插→拔→AOI=True) ‖ 模型直驱 0/2 (过冲) —
  与离线判闸一致 (预测std 仅教师 7~16% = 塌均值), **模型能力问题非接线问题**, 日志/status 诚实标注。
- **判闸根因 (配置级, 非训练量)**: ① `loss.intent.local_weight=0.1/goal=0.05` 而 `forward=1.0`
  → actor 几乎不发声; ② `min_log_std=-5.0` → std 可缩到 0.007, "输出均值+极小方差"就是 NLL 最优解
  ⇒ 塌缩是最优解。对策 = `intact_goal_optical_insert_v5.yaml` (权重 1.0/1.0 + min_log_std -2.0)。
- **训练接力**: `train.py` 预先固定 `timeout 14400` (4h) 而 12 epoch 要 ~9.2h → 必被 SIGTERM (v3 死因 rc=124);
  `l4_ab/train_intact_optical_chain.sh` 从最新 ckpt 换名续训到累计 TARGET epoch (CFG/FAMILY_V/TARGET/PER_RUN/DEADLINE)。
- 📄 全部细节 (桥执行流/坑清单/命令) 见 `references/l4-optical-insert-chain.md`

## 🌍 L4 · SW 仿真世界引擎链 (v5.5.28, 2026-09-13 — INTACT cube 集成进状态空间)
老倪: "把独立的 INTACT 运行环境集成到状态空间中, 点击运行就能跑 INTACT, 触发开关是 L4"
- **链条 (独立, 只增不改)**: 🧪 SW环境渲染图像源(数据源) → 🎯 INTACT策略·cube(中间) →
  🌍 SW仿真世界引擎(硬件层) → 🎬 SW渲染视频(可视化) = 4 节点 + 1 个 row_bg + 4 连线
  (flows/state_space_obs.json 文本级插入, 保持原缩进; 原有 70 节点/72 连线一字未动)
- **L4 触发开关 = 复用既有档位机制**: 节点落在名字含 "L4" 的 row_bg 色带内 →
  `_ss_node_cap_level()` 直接返回 4 → 只有 L4 档的单步/播放链执行它。**不需要新代码分支**,
  L2/L3 档零影响 (offscreen 实测 L2/L3 节点全在)
- **桥 = tools/intact_sw_bridge.py (跑在 INTACT venv, 跨 venv 子进程)**: 与 paper_runtime
  eval 逐行同源 (同 World / load_pretrained / PriorOnlySolver 零搜索 / _extract_init_goal +
  _apply_callables / img_transform + StandardScaler); 唯一区别 = **逐帧流式**
  (spool/*.jpg + status.json) + 末尾官方 `save_panel_videos` 出 3 面板 (agent|dataset|goal) mp4
  + concat 合集 = 「从 stable world 取出的 3D 视频」
- **⚠️ 三个实测坑 (都踩过)**:
  ① 桥**必须**用 INTACT venv 解释器 (`/home/ubuntu/INTACT-JEPA/.venv/bin/python`); 仓库 `.venv`
     没有 numpy/torch → `ModuleNotFoundError: No module named 'numpy'` (症状: bridge.log 尾部报错,
     status.json 永不出现)
  ② `_sw_paths()` 返回序是 **(dir, frames, status, video)**; 解包错位 (`_, st, fr, vd = ...`)
     会静默把 frames 当 status → 三个节点同时报 "桥进程已退出, stage=None" 却查不出原因
  ③ 桥跑完会**退出进程**, 此刻 status 可能正处 `os.replace` 瞬间 → 读到 `{}`。正确姿势:
     节点顺序链里**第一个节点负责启动桥并等到 `stage=='done'`**, 后续节点只读终态;
     `_sw_wait` 里加"进程死亡 → 再读一次终态 → 才判定失败"并打印 bridge.log 尾部
- **验证脚本**: offscreen 画布载入必须**按节点名匹配** (载入器会重生成 node id,
  用插入时的 id 查不到); 端到端真跑实测 13.6s / 52 帧 / frame_std 30.26 (>5 真图) /
  模型真调用 52 次 / candidate_action_steps=0 / 4 个视频文件

## simulink 工程完整性检查 (2026-08-28 v3.3.1, 老倪: 全面检查)
新增 `tools/ci/zmax_integrity_check.py` 一键检查器, 五项全绿:
1. **NODE_TYPES 三处同步** (simulink_module 15种 = validate_flow = simulink_ci) —
   曾不同步 (主15/验证6/CI8) → 画布 type=data/scene/row_bg 被验证器误判"非法"。
   新增节点类型必须三处同步 (老规矩, 检查器自动验证)。
2. **状态空间/业务闭环豁免**: flow_x.json/cooperation_closed_loop 的环是架构反馈
   (卡尔曼校正/感知-决策-执行/供应商区-实验室-现场), 非错误 — validate_flow 和
   simulink_ci 均降级警告。普通模板有环仍 FAIL。
3. **check_params 语义级校验**: 原只有类型白名单 → "pos":"not-a-list" 误判通过。
   PARAM_SCHEMA 只收确定类型的控制参数 (Kp/K_ff/Kd 数值; limit 兼容单值/区间;
   force_res="0.1N"/grid="7x9" 是文本; encoding 是 dict; in_dim/frames 可能是
   描述文本 '39D obs+4D action' — 实测校准, 不可统一处理)。
4. **check_ports 隐式端口兼容**: 真实画布节点无 outputs/inputs 字段 → 原代码
   p["id"] 对字符串索引 TypeError → 无端口列表的画布跳过。
5. **check_format 降级**: 合作闭环 (zmax-cooperation-closed-loop)/旧格式
   (hermes-flow) 模板硬判 FAIL 误伤 → warn 尽力校验。
模板加载验证: offscreen 下 SimulinkModule 构造后 monkeypatch `_qmsg_yes/_qmsg_info`
(否则第二个模板弹确认框 exec_ 卡死), 逐个 load_reference_app 断言 nodes==items。
**共享节点设计**: Model Zoo 的「🧩 结构条件」(无·后缀) 在 load_reference_app
4685 行被显式跳过 (已下放各模型行), 不进 layout 是正确设计 — 检查器要豁免它。

## VSCode 断点调试 node_logic 坑 (2026-08-31 老倪: "点运行进不了这个函数的断点")
- **症状**: 节点逻辑真实执行了(终端出现该函数日志如 "📦 数据源:")但 VSCode 断点不命中。
- **根因 ①(最常): node_logic 可修改区动态 exec** — 在 GUI「查看/编辑节点逻辑」里保存过 → `save_node_logic` 把 `NODE_LOGIC[key]["fn"]` 替换为 `exec(compile(new_code, "<node:key>"))` 出的函数, co_filename=`<node:data>` **无真实行号 → VSCode 磁盘文件断点永不命中**(函数照常执行)。判定: 断点红点空心/灰 = 未绑定。
- **根因 ④(2026-09-01 实测, py-spy 铁证): 引擎内部断点堵死播放 — ▶运行 = 先同步跑引擎 sim.run()(500步, 含传感器融合 fuse_sensors 等真实源码) → 引擎返回后才 _ss_tick 逐节点播放(80ms/节点)**。在 src/lerobot/policies/left_right/state_space/*.py (或 yolo_3d) 设的断点会**先于任何节点逻辑命中**, 主线程冻结在引擎里 (debugpy do_wait_suspend) → run() 不返回 → _ss_tick 永不启动 → 数据源等节点断点"永远进不去" (GUI 日志停在引擎阶段, 无"⏩ 数据源节点优先"/"▶ 仿真开始")。判定: `sudo py-spy dump --pid <gui>` 主线程栈 do_wait_suspend ← fuse_sensors ← _build_obs ← run ← _start_state_space_sim。解法: 删引擎内部断点 (只想调试节点逻辑时); 想调试引擎就接受每步都停 (500 步)。
- **根因 ⑤(2026-09-02 实测): spec_from_file_location 动态加载的模块断点不绑定 — 函数真实执行 (日志有输出) 但 VSCode 断点不停**。debugpy/pydevd 对"断点设置时文件未加载"的模块断点不生效 (import hook 捕获不到 spec_from_file_location 绕过 meta_path 的加载; 预加载到 sys.modules 也无用 — 同样绕过)。**解法: `exec(compile(src, 真实文件绝对路径, "exec"))` 加载 → 函数 co_filename 指向真实文件, debugpy 按路径查表必命中 (与引擎 perception/cognition 断点同行为)**; exec 的命名空间必须注入 `{"__file__": 路径, "__name__": ...}` (数据层 _repo_root 引用 __file__ 会 NameError)。
- **根因 ⑥(2026-09-02): 断点设在 def 行/docstring 不命中 — 函数第一条语句是 docstring, def 行无可命中字节码**。**_EXTERNAL_LOC 的 line 参数必须指向第一行实际代码** (不是 def 行); 指引用户断点设在 for 循环/return 等实际执行行, **别设 return None 行** (本机有数据时提前 return, 永不执行)。
- **根因 ⑦(2026-09-02, py-spy 铁证): 疑似"整机卡死" = 引擎断点挂起 ⇒ 先 py-spy dump GUI 主线程再动手** (do_wait_suspend = 断点冻结, 删断点即恢复; freeze 在 paint 等栈 = 真死循环; 系统级正常 = 不是整机问题) — 别急着重启机器; 删 VSCode 引擎内部断点 (src/lerobot/policies/left_right/state_space/*.py) 立即恢复。LiveUSB 0 swap 顶满也会冻结(无 OOM 日志) ⇒ 加 swapfile, 但 overlay 上 swapon 直挂 /swapfile 报 Invalid argument ⇒ 必须 loop 设备方案。**详文: `references/fake-freeze-breakpoint-triage-2026-09-02.md`**。
- **YOLO 首次加载卡主线程弹 not responding (2026-09-02 老倪: "studio.py is not responding 不要跳出来")**: 状态空间播放 YOLO 节点真实执行 → _yolo_ensure_aligner 首次加载模型 10-40s (主线程同步) → 系统弹 not responding。解法: studio.py main() 启动即后台线程预热 `node_logic._yolo_ensure_aligner(None)` (YoloStateAligner 构造纯计算不碰 Qt, 线程安全), 播放时 _YOLO_ALIGNER 已缓存不卡。
- **数据源节点架构 (2026-09-02 老倪: "数据源应该在 lerobot 框架, 至少 datasets 文件夹")**: ss_* 节点 (传感器融合/前馈等) 全部 _EXTERNAL_LOC 映射到 src/lerobot/policies/left_right/state_space/*.py 真实源码, **唯独 data (📦 metaworld 数据源) 曾无映射** — 只是 node_logic.py 的切换开关模板, 右键/断点进的是 tools/gui 控制台文件, 与感知/决策节点不同构。整改: 新建 src/lerobot/datasets/metaworld_data_source.py (probe_data_source 按 DATA_ROOTS 优先级真实探测本机训练仓库 info.json 帧/集/特征; resolve_source 数据源策略; 无 GUI/torch 依赖), node_metaworld_data 可修改区 **exec(compile(真实路径)) 加载真实调用** (co_filename 真实 → 断点命中), _EXTERNAL_LOC["data"]=(datasets 文件, 第一行实际代码, "def probe_data_source")。**新增节点接真实源码的三件套: ①框架层真实实现文件 (policies/datasets) ②node_logic 节点函数加载真实调用 (exec(compile(真实路径)) 保证断点命中) ③_EXTERNAL_LOC 映射 (右键/断点进真实文件, line 指第一行实际代码)**。v3.4.0 落地 (老倪验收: "进到断点了")。
- **右键「打开源代码 / 打开 VSCode」定位优先级 (v5.5.44)**: ① 节点 `params.source` (+ `params.source_symbol` 按符号**现搜**行号) →
  ② `node_logic._EXTERNAL_LOC[key]` 映射 → ③ 都没命中就退回 `node_logic.py` 自身 co_filename (= **GUI 文件**)。
  **坑 (必踩): 代码搬到 src/ 后忘了改 `params.source` / 忘登记映射 → 右键永远停在 GUI 文件**
  (老倪 2026-09-13: 「VEH.5.022 INTACT意图解码器 右键打开 vscode 源代码, 还是原来的 GUI, 你怎么没有跳到
  src/lerobot/policies 文件夹里呢?」—— 这次两条一起犯: INTACT 家族没登记映射 **且** `open_in_vscode()` 当时只认映射不看 `params.source`)。
- **右键「打开 VSCode」必须投"工作区文件", 不能投文件夹** (2026-10-17 老倪「怎么又打开一个 vscode? 应该进入 zmax 工作空间的 vscode」):
  `cmd=[code, root]` 里的 root 是**文件夹根**, 与 `ZMAX.code-workspace`(4 根)在 VSCode 眼里不是同一个项目 ⇒
  判定为新工程、**再开一个窗**(且只有 1 根, 没有 框架/控制台/文档/工程 四根)。改法: `cmd=[code, ZMAX.code-workspace] -g 文件:行`,
  已开的工作区窗会被**直接复用**(实测窗口数 2→2 且文件落在 5 根那个窗、行号命中)。
  - 不要靠 `code -r`(复用"最后活动窗")或 `wmctrl -a` 先激活: 实测 `wmctrl` 聚焦后 `-r` 仍投到**别的**窗(焦点事件没进 VSCode 的窗口列表)。
  - 取证用 `code --status`: 它按窗口列 `Window (...)` + 其下 `Folder (...)` ⇒ **多根工作区窗 = 标题里没有 " - <目录> - " 段、Folder 有 4~5 条**;
    只按窗口标题猜类型会判错(标题只反映活动文件)。
  **一律给符号名, 不预先固定行号** (行号随重构漂移, 上次就跳到了 import 区看起来"没跳")。
  自查: `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_vscode_source_loc.py [节点id ...]`
  (打桩 Popen 捕获 `code -g` 真命令, 断言路径含 `src/lerobot/policies` 且不含 `node_logic.py`)。
- **解法三选一**: ① 右键节点→查看/编辑节点逻辑→「恢复出厂逻辑」(restore_default 从文件重新 exec, 行号真实) ② 重启 GUI(_SOURCE_CACHE 是内存, 重启即清) ③ `ZMAX_DEBUG_BREAK=1` 启动 GUI — execute_node_logic 开头(node_logic.py:124) `debugpy.breakpoint()` 任何节点逻辑执行前强制停, **不依赖断点绑定**, 调试动态 exec 函数唯一办法。
- **执行证据判定法**: 状态空间画布点运行 → 终端出现 "📦 数据源:" = node_metaworld_data 执行了; 有日志但断点没停 = 断点绑定问题(不是代码路径问题); 没日志 = 没执行到(画布/路径不对)。
- **F5 调试端口冲突**: 「🚀 全新调试进程」启动时 debugpy adapter 占 5678(--port 5678 --for-server), studio.py main 里 `debugpy.listen(5678)` 失败被 try/except 吞 → 想用「🔌 Attach 现有控制台(5678)」必须没有 F5 会话; GUI 启动即 listen 5678(main 内, 不阻塞)。
- **GNOME/Xorg 黑屏 (2026-08-31)**: studio.py main 的 `AA_UseSoftwareOpenGL` 软件 GL 在 Mutter 合成器下窗口内容渲染全黑(该行是 WSLg 假死修复, 已注释) — WSLg 环境才需要, 本机 GNOME 桌面不要开; 症状=窗口在但全黑, 关窗后事件循环 quitOnLastWindowClosed 退出(exit 0)。

## 本机推理/仿真环境 (2026-08-30 实测)
- **推理/评估/出视频的 python = ~/lerobot-venv**(项目无 .venv;GUI 用 gui-venv311 无 torch)。
  on_infer_rollout/on_eval_state_space 已改多候选探测: `.venv → ~/lerobot-venv → gui-venv311`。
- **metaworld 3.1.1 + mujoco 3.3.0 + glfw + PyOpenGL + scipy** 已装进 ~/lerobot-venv(2026-08-30)。
  requirements-macos.txt 锁 metaworld==3.0.0(3.0.0 wheel 从 files.pythonhosted.org 下载不稳/中断,未装成)。
- **⚠️ pip/uv 装 metaworld 系列会僵死**(resolver 卡,0% CPU 无网络,杀不掉会一直挂着):
  正解 = `pip download`/curl 拿 wheel → 校验 `unzip -t` → `--no-deps` 安装或直接 unzip 解包进 site-packages → 逐个补缺的 import(glfw/imageio/scipy/PyOpenGL, aliyun 源快)。
- **gen_insert_video 12/12 seed 卡"转移/下降"诊断**: full_pipeline.pt(08-24 fallback)与新 metaworld 3.1.1 物理不匹配 —
  contact_head 预测 0.30-0.41 徘徊达不到 0.5 阈值, 降阈值 0.35 会误进转移但 peg 抓空(peg z 不变)。
  **本机可用 left_right 模型被磁盘红线清光** → 要出视频需训练新模型或从 4090 拉。
- 历史: left_right_20260813_164959(曾验证成功 seed2)已被磁盘清理删除, 勿再引用。

## ⚠️ Windows/macOS exe 3D 无法渲染 = AA_UseSoftwareOpenGL 平台条件 (2026-09-07 v5.0.0, 老倪: "3.2.4 能启动并渲染3D, 之后版本不能")
- **症状**: Windows exe (及 macOS app) 从 v3.3.4 起 3D 视图 (GLViewWidget/pyqtgraph) 无法渲染;
  v3.2.4 及之前 (全平台无条件 `AA_UseSoftwareOpenGL, True`) 正常。
- **根因**: v3.3.4 为修 Linux GNOME/Mutter 黑屏 (软件 GL 在合成器下全黑) 把
  `AA_UseSoftwareOpenGL` **整行注释** → Windows/macOS 无硬件 GL 环境 (虚拟机/远程/无独显驱动)
  3D 无保障 → 渲染失败。软件 GL 对 Linux GNOME 是毒药, 对 Windows/macOS 打包版是救生圈 —
  平台 GL 策略不同, 不能统一处理。
- **修 (v5.0.0)**: 平台条件启用 — `if sys.platform in ("win32", "darwin"): setAttribute(AA_UseSoftwareOpenGL, True)`;
  Linux 源码版不启用 (GNOME 黑屏修复保留)。studio.py main() QApplication 创建前。
- **铁律**: 跨平台 GL/渲染设置改动 (AA_UseSoftwareOpenGL/AA_UseDesktopOpenGL 等) 必须按
  sys.platform 分叉, 禁止无条件开/关; 打包版 (win/darwin) 优先可用性 (软件 GL 保障),
  源码 Linux 版优先合成器兼容。老倪验收口径 = 每个发布版都要在**无独显 Windows 环境**
  实测 3D 渲染, 不能只在 Linux 源码版验证。回归判据: 3.2.4 (正常基线) vs 新版本 diff
  里找平台性设置变化。

## Windows exe 画布无法打开 = /tmp 打点无保护 (2026-08-28 v3.3.2, 老倪: "3.3.1 3.3.0 无法打开画布, 3.2.4 可以")- **症状**: Windows exe 上 simulink 画布 tab 无法打开/空白, 状态栏 "⚠️ Simulink 初始化失败: [Errno 2] No such file or directory: '/tmp/...'"; 源码版 Linux 正常 (有 /tmp)。
- **根因**: 3.3.0 为排查 Mac 黑屏加的 SimulinkModule 构造打点直接 `open("/tmp/zmax_simulink_init.log", "a")` — studio.py `_init_simulink` 里 `_mk` lambda **无 try/except** → Windows 无 /tmp 目录 → FileNotFoundError 抛在 `SimulinkModule()` 之前 → 画布从未创建。simulink_module.py 里同款打点有 try/except 所以不崩 (静默失效)。
- **铁律**: ①跨平台诊断打点/临时文件一律 `os.path.join(tempfile.gettempdir(), name)` + try/except, 禁止裸 `/tmp` (Windows 没有); ②`_init_simulink` 这类"建画布"路径里任何语句抛异常都会让画布整体消失 — 打点类语句必须自身容错, 不能依赖外层 try 保障 (外层 catch 后画布也没了); ③验证必须模拟 Windows: monkeypatch `tempfile.gettempdir` → 不存在目录, 再跑 `SimulinkModule()` + `load_flow_file`, 断言 nodes>0。
- **排查流程**: 3.2.4 正常 → 3.3.0 坏 = 二分 diff `git diff <v3.2.4>..<v3.3.0>`, 找新增的 IO/路径类语句; 用户报"Windows 打包的版本"时优先怀疑平台差异 (路径/权限/编码), 不是 UI 逻辑。

## QDialog 最大化按钮点了没反应 (2026-08-28, 节点逻辑/参数/源码窗口)
老倪「最大化按钮不好使, 不是让你禁用, 修复它」— 第一轮误把"不好使"理解成"禁用"
加了 `~WindowMaximizeButtonHint` (方向错误, 被纠正)。**根因**: QDialog 默认 Qt.Dialog
窗口类型在 X11 WM 下标题栏最大化按钮点击无效 → 显式转普通窗口类型:
```python
self.setWindowFlags(Qt.Window | Qt.WindowMaximizeButtonHint
                    | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
```
验证 (真实 DISPLAY, offscreen 会误判): showMaximized → isMaximized=True + 尺寸≈屏宽
(本机 3068x1862)。**教训: 老倪说"XX按钮不好使"= 修复功能, 绝不是禁用**;
窗口类型/按钮 hint 类问题先确认 Qt.Window vs Qt.Dialog 类型再动手。

## 状态空间画布连线因果检查 (2026-08-28, 触觉感知孤立节点)
老倪「触觉感知的数据源, 也应该是metaworld啊」— 画布上 🖐 触觉感知节点入度=0 (孤立),
但引擎真实数据 (state_space_sim._build_obs) 的 tactile4=[gripper, contact] 就是 metaworld
夹爪开度+物理接触检测。**画布连线必须如实反映引擎数据流**: 感知类节点 (传感器融合/YOLO/
触觉感知) 都应有 📦 metaworld 数据源 入边。排查法: 遍历 flows/*.json 入度=0 的非 row_bg
节点, 对照 state_space_sim/源码确认是否真有上游。修法: 补 link {f:ssdata, t:sstactile,
label:触觉数据} + 节点 desc 注明数据来源。拓扑验证: 单步第一节点应变为数据源 (因果正确)。
铁律: 画布每个节点要有真实的数据源连线, 不许有"引擎内部取数但画布孤立"的节点。

## 3D 视图↔程序执行状态映射 (2026-09-02 v3.4.3, 老倪: "3D视图的显示状态要与debug程序代码的执行状态保持一致")
- **需求**: 点 ▶运行 时 3D 视图要跟程序执行走, 不是独立播离线 episode; 断点停在哪一步 3D 显示哪一步。
- **实现三件套**: ①`open_ss_3d` 数据源优先 `self._ss_tr`(sim.run() 程序轨迹), 没运行过才退回 episode npz(保持与操作视频同源能力); ②`_ss_tick` 每帧把引擎步 `idx` 推给 3D 窗口: 窗口 tr 不是当前 tr 先 `set_trajectory(tr)` 再 `w.set_frame(idx)`(sip.isdeleted 判活); ③`DreamView3D.set_frame(i)`: `_pause()` 停自播防双驱动 + `_update_frame(i)` + slider/lbl 同步。
- **断点天然同步**: 引擎断点挂起主线程 → 推送停 → 3D 同步停; F5 放行 → 继续。无需额外逻辑。
- **配套 (fe2c82af)**: 打开即自动播放 — set_trajectory 末尾 `_timer.start(60)`(原默认静态第 0 帧, 用户以为"无法打开")。
- 验证: sim.run() 322 步 set_frame 0→321 跟随, 0.5s 不被自播抢动。
- **🐛 real sim.run 轨迹喂 3D 缺 residual_vec KeyError → 窗口无法打开 (2026-09-07 v4.4.0 实锤, 老倪"3D视图无法打开")**: open_ss_3d 优先用 _ss_tr (真实化 sim.run 轨迹) 时, ss_dreamview._update_frame 直读 `tr["residual_vec"]` (无 .get 容错, 引擎轨迹才有该 key) → KeyError 崩在 10774 构造行, 日志停在"3D 视图数据源: 程序执行轨迹"无后续。修: sim_real run() 补 latent_vec/prior_vec/corrected_vec/residual_vec 四个顶层向量通道 (对齐引擎 tr 格式, 数据每帧已有: prior/latent/corrected/residual)。排查: GUI stderr (studio_launch.log) 见 KeyError; 3D 打开后日志缺"✅ 已打开 3D 分层视图"行。**铁律: 任何新轨迹源 (sim_real/gen/episode) 喂 DreamView3D 前, 对照 ss_dreamview 引用的 18 个 tr key 全量补齐**。

## _EXTERNAL_LOC 行号铁律 (2026-09-02 v3.4.3, 老倪连续 3 轮 "源码不是这个")
- **症状**: 双击画布节点编辑器显示正确类, 但「VSCode 打开/复制位置」跳到错误代码 → 用户反复看到"自适应状态估计器源码=forward"(ss_est 映射行号 34, 类实际 45, 34 行正好是 FeedforwardAccelerator.forward 的代码)。
- **根因**: _EXTERNAL_LOC 的 line 是"保障行号", 符号名匹配成功时行号不参与截取, 但 VSCode 打开用行号 → 行号错位 = 定位到错代码。文件头加注释/改行 → 全部错位 +1。
- **铁律**: 新增/修改 _EXTERNAL_LOC 后跑符号名+行号双查脚本(逐行 strip 匹配 `sym`/`sym(`/`sym:` 找真实行), 全量 29 条 0 错位才算完。symbol 必须是真实定义(`def synth_tactile` 不是 `gen_tactile`; 类行号含 `class X:` 冒号)。
- **配套修复**: ss_est→AdaptiveStateEstimator(45), ss_sched→def decide(167, 动作调制器双击直接看核心决策), ss_aoi→AOIQualityChecker(40), ss_bg5 符号误写路径字符串"planner.py"→class TaskPlanner。

## debugpy 僵尸占 5678 → SystemExit:1 (2026-09-02 v3.4.3)
- **症状**: VSCode 弹 "Exception has occurred: SystemExit / 1" (debugpy adapter __main__.py sys.exit(1)); F5 调试启动失败/attach 失败。
- **根因**: F5 会话主进程退出后 pydevd 子进程残留, 一直占着 5678(studio.py main 里 debugpy.listen(5678) 的 attach 端口)。`pkill -f "[s]tudio.py"` 杀不到 — pydevd 命令行是 `pydevd.py --port ...` 不含 studio.py。
- **清理**: `ss -tlnp | grep 5678` 看谁占 → `kill <pid>`; 反复 F5 会反复留僵尸, 每次调试会话结束都查一次。attach(5678) 必须无 F5 会话 + 5678 空闲。

## 标定层 (2026-09-02 v3.4.4 → 2026-09-03 v3.4.5 闭环, 老倪: Drifting Models 引力/斥力二分 + 平衡点)
- **需求**: 参考 arXiv:2602.04770 反称场思想 (Vp,q(x)=−Vq,p(x), q=p⇒V=0), 第一性原理把引擎全部超参数二分: **引力=快速动作** (Kp+STAGE_V_CAP/STAGE_V_MIN 各阶段速度上限/下限), **斥力=状态预测** (K_kalman+残差EMA+接触增益+否决阈值+反馈增益+先验A), 平衡偏差 = 引力势−斥力势 (V≈0 无漂移)。状态/阶段=明确标定量。
- **代码位置铁律**: 标定层在 `src/lerobot/calibration/`(与 datasets/、policies/ **同级别**), 不在 tools/gui。CalibrationLayer: attr/rep 标定表 + attraction_potential/repulsion_potential/equilibrium_gap + export(json) + **apply_to_engine/apply_to_file (v3.4.5)**。
- **🎯 标定闭环 (v3.4.5, 老倪: "标定值直通引擎, 不再手动同步")**: 💾保存 = `layer.apply_to_engine(root)` **精确写回引擎源码字面量** (值无关正则, 只认代码上下文, 锚点命中数 != 预期 → ValueError 不静默):
  | 标定参数 | 引擎落点 (tools/gui/state_space_sim.py 每次 ▶运行 importlib 重载源码 → 下次运行即生效, 无需重启 GUI) |
  |---|---|
  | Kp | parallel.py `Kp = 1.2` |
  | u_clip | parallel.py forward 两处 `np.clip(..., ±u_clip)` (值无关整行模式) |
  | stage_v_cap/min | cognition.py `STAGE_V_CAP/MIN = {...}` 类 dict (**整块内逐 key** — 引擎无参实例化 ActionModulator 吃类默认) |
  | veto_th / k_fb | cognition.py `__init__(..., veto_th=2.0, k_fb=1.0, ...)` 默认参 |
  | K_kalman / contact_gain / safety_limit / prior_A | state_space_sim.py run() 内联点: `state_correction(prior, z_k, K=)` / `contact_probability(r_scalar, gain=)` / `saturate(u, limit=)` / `PriorDynamicsPredictor(A=)` |
  | res_ema | state_space_sim.py 系数对 `(0.85 * self.res_ema + 0.15 * ...)` → (1−α, α) **同步写** |
  `apply_to_file(calib_path)` 写 calibration_layer.py 镜像 (下次打开表格的默认值源)。
- **⚠️ 镜像/引擎写回必须块内替换**: V_MIN 的 key (接近/对位/抬起/转移) 在 V_CAP 也出现 — 裸 key 正则会把 V_MIN 值**串写进靠前的 V_CAP** (v3.4.5 实测 bug)。stage dict 一律 `re.search(rf'"{dname}": \{{(.*?)\}}')` 块内逐 key。
- **⚠️ 数值格式**: stage dict 用 `.2f` (引擎 0.30/0.10 带尾零); 标量用 `%.6g` + 整数补 `.0` (2.0/1.0/8.0 引擎风格) — 否则默认值 apply 也会产生 diff。
- **⚠️ 标定表默认必须 = 引擎真值**: prior_A 曾抄 parallel.py 默认 0.95, 但引擎 est/dyn **显式 A=1.0** (物理自洽: 位置保持 + dt 积分) — v3.4.5 校准为 1.0。改引擎参数时同步校准此表。
- **生效证明验证法**: apply 后 **importlib 重载引擎** (`spec_from_file_location('tools/gui/state_space_sim.py')` + `StateSpaceSim()`) 断言 `sched.v_cap/veto_th/k_fb/v_min` 吃到新值; 默认值 apply 后 `git diff` 引擎文件必须为空 (表默认=引擎默认的零副作用检查)。
- **画布**: flows/state_space_obs.json **append** ssbg6(row_bg 🧮标定层) + sscalib 节点(params.calib_layer=true) + link ssworld→sscalib(状态标定量)。只增不改 — 不动任何现有节点/连线/流程。
- **UI 三入口**: ①双击/右键查看逻辑 → CalibrationDialog(引力组8阶段速度上限表当前阶段高亮+斥力组+平衡条; **v3.4.5 起 💾应用标定按钮也走 apply_to_engine**, 构造传 calib_path); ②**右键菜单专属项「标定表格 (引力/斥力参数编辑)」→ CalibrationTableDialog**(21 行全参数表, 双击单元格编辑, 保存 = apply_to_engine + apply_to_file + export); ③节点执行 node_ss_calib 读 module._ss_tr 当前步 stage/speed/residual/contact_p 算势。
- **右键菜单加专属项套路**: `if item.node.get("params",{}).get("calib_layer"): a_calib = menu.addAction("标定表格 ...")` + `elif chosen == a_calib: self.module.on_open_calib_table(item.node)`。菜单项去 emoji(VcXsrv 黑块坑)。
- **QMessageBox 深色**: calibration_dialog 里静态 QMessageBox.information/warning 会黑字 → 手动构造 mb + setStyleSheet(_DARK) + exec_(AA_DontUseNativeDialogs 下生效)。
- 验证 (v3.4.5 13/13): 默认值 apply 引擎零 diff / V_MIN 改值不串 V_CAP (引擎+镜像) / UI 全链路表格改3值 → 引擎文件+实例吃新值, run 正常 / 锚点破坏 → ValueError。

## 🧩 功能清单网页统稿 (v4.2.0, 2026-09-04 老倪: VIS-01 编号 + 场景 + HDM 几何分类)
- **node_func_tree.py 三组新注册表 (全 110 功能向后兼容注入, 旧消费端无感)**:
  - `FUNC_DOMAINS` 21 域三字母编号 → 每功能注入 `code` (VIS-01 格式: 域码-域内序)
    + `dom`; VIS 域 = ssyolo(01-05)+ss2d3d(06-10), VIS-01=YOLO 目标检出 (老倪锚点)。
    校验 check_codes() 全绿 (110 唯一)。
  - `SCENES` 5 大客户场景 (SC-01 FW Loading 金手指插拔/SC-02 ATS 光纤连接/
    SC-03 老化墙批量插拔/SC-04 上下料流转/SC-05 光耦合主动对准): 每场景
    story 作业故事线 + object/env/targets(量化目标**必须取自 RFP/TECH 真值**,
    禁造数字)/status(诚实标 ✅/🔶)/funcs。校验 scene_funcs_ref()。
  - `GEOM_CLASSES` 几何三分类 (纤维丛): LFP 局部精细感知(30, 本体无关仅重标定外参)
    /LFO 局部精细操作(35, 绑定运动学换本体旧联络失效)/HDM 全局高维流形泛化
    (45, 跨本体微调即新截面)。每功能注入 geom; hdm_funcs_of_scene 汇总跨本体泛化。
    校验 check_geoms()。
- **gen_web_feature_pages.py 五章节**: 几何总纲+HDM 汇总 → 场景详述(功能表) →
  编号图例 → 组合链 → 三层总表 (110 主行 + 550 用例子行 code-T1~T5 全展开,
  验证方法列 = VerificationLayer.<ref>() 原样去重, 手动用例子行带步骤全文)。
- **上传通道 (实测)**: datadrive.world = ECS 39.102.211.79 nginx,
  **站点根 = /www/wwwroot/datadrive.world/** (宝塔路径, /var/www/html 是默认页不算);
  zmax-website 仓库在 ECS /root/zmax-website。上传:
  `sshpass -p '${ZMAX_ECS_PW}' scp reports/web/*.html root@39.102.211.79:/www/wwwroot/datadrive.world/`
  → curl https://datadrive.world/function-list.html 验证 (grep 新章节锚点)。
- 版本中迭代 v4.2.0 同步点同 v4.1.0 五处 + VERSION.md 历史表两行 (v4.2.0+v4.1.0 补录)。

## 📋 技术规格书 TECH_SPECS + RFP (v4.1.0, 2026-09-04 老倪: 供应商规格全写入清单)
- node_func_tree.py TECH_SPECS 3组12项规格 → 量化映射产品作业+功能 fid:
  组1 核心本体·运动控制 (Gauge Covariant Operations, 光耦合/光纤·模块插拔工位):
  极致定位±0.02mm+单模50nm多模100nm · 六维力亚牛顿0.5% 1-2N拖拽 · EtherCAT
  1kHz无抖 · 紧凑高刚性1.6T OSFP多角度安装
  组2 复合移动·柔性流转 (Locomotion & Flexibility, 上下料/跨工位/分拣): 全向底盘
  ±10mm蟹行 · 移动-操作解耦驻停毫米级 · 双臂10kg 0-2.5m 双孔0.3° · 多模态避障
  组3 智能认知·系统集成 (Gauge Symmetry & Invariance): VLA自进化 · UPH400不停机
  换料 · CPK1.67 良率99% AOI 0漏杀 · EtherCAT/Profinet/Modbus TCP + ESD/IP65
- RFP_SPEC (客户需求) 与 TECH_SPECS (供应商规格) 双注册表并存, 均 → 产品作业 →
  功能 fid 同源映射; GUI 对话框 Tab3 RFP / Tab4 技术规格书, Excel Sheet6/7。
- 版本中迭代 v4.1.0 同步五处: studio.py(窗口标题/QLabel/changelog注释前缀) +
  update_checker.py CURRENT_VERSION + version_sync.py zmax_ver + docs_sync.py
  ("version" + "zmax_version" 两键)。漏一处 → exe 标题旧版。changelog 巨长注释
  用 Python 脚本前缀插入 (锚点 '# v4.0.2:' 现为 '# v4.1.0:')。

## 📊 产品作业分级 PRODUCT_TREE + RFP + 一键自动测试 (v4.0.3/v4.0.4, 2026-09-04)
- **PRODUCT_TREE** (node_func_tree.py 尾部): 客户视角作业分级, 物理判据 刚体→柔性→
  性能极值: L1 基础功能·刚体接触插拔类 (光模块插拔/刚体取放/视觉定位, 全已实现,
  路线=分段式解析控制+状态机) · L2 高级功能·柔性物体插拔类 (光纤接头插拔/线缆整理/
  微力控, 规划中, 路线=端到端 VLA 插拔头/柔顺导纳 — 解析难建柔性模型) · L3 扩展功能·
  性能调节类 (光耦合主动对准/耦合质量闭环, 路线=世界模型+优化搜索, 端到端模仿难学
  搜索行为)。每 job: funcs 引用技术树 fid + model_route + gen 泛化指标 + detect + status。
- **泛化指标 G 组** (VerificationLayer t_g*_ 断言, 全真实引擎跑): G_data 数据外推
  (引擎 X0 初始扰动 ±10/±15mm 真跑), G_pose 位姿外推 (模块级 HOLE_POS monkeypatch
  偏移 2~10mm 真跑, **跑完 finally 恢复原常量**), G_skill 技能复用 (FUNC_CHAINS 引用
  校验 + L1∩L2 共享子技能 ≥3)。引擎模块 monkeypatch 法: importlib.import_module +
  改 m.HOLE_POS/m.X0 再 StateSpaceSim().run(), 引擎控制器自洽跟随观测真值 (偏移
  10mm 终态误差仍 ~3mm = 自洽收敛)。
- **RFP_SPEC**: 光模块 RFP 9 量化指标 (★否决 5 项: ±0.02mm 重复定位/50nm 耦合/亚牛
  顿力控/UPH400·CPK1.67·良率99%/…) → 关联产品作业 + 支撑功能 fid。
- **一键自动测试** tools/gen_verif_auto_report.py (gui-venv311, reportlab 5.0.1 已装):
  环境自检 5 项 → run_tree 全部 auto → PDF 7 章报告 (摘要/环境/按节点 PASS 表/
  产品分级/RFP 映射/G 组实测/结论) + Excel 6 sheet。GUI: ss_test 节点右键
  「⚡ 一键自动测试」→ _run_auto_test 子进程跑 (reportlab 在子进程防卡 GUI) →
  解析 stdout REPORT_PDF=/EXCEL= → scp 上传 datadrive.world 弹 URL。
- **⚠️ reportlab 中文**: 本机无 wqy 字体! 回退链 wqy-microhei→wqy-zenhei→
  arphic/uming.ttc→DroidSansFallbackFull.ttf; Noto CJK 是 CFF reportlab 不认。
- **GUI 对话框深色坑**: 全局 app.setStyleSheet (studio _build_global_qss) 存在时,
  子 QDialog 靠级联 QSS 不可靠 — 每个 QTreeWidget 必须**控件级显式 setStyleSheet**
  (QTreeWidget{background:#161b22; color:#e6edf3...}), 否则树区白底灰字。
- **QDialog 最大化坑**: QDialog 默认 flags 无 MaximizeButtonHint → 右上角最大化
  按钮点了没反应; 需 setWindowFlags(flags | Qt.WindowMaximizeButtonHint |
  Qt.WindowMinimizeButtonHint), 在 _show_nonmodal (simulink_module.py) 统一补。
- VerificationDialog 3 Tab: ①技术树(G1/G2/G3→节点→功能→用例) ②产品分级
  (L1/L2/L3+泛化+选型+检测) ③需求规格书 RFP (★否决项分组→作业→功能);
  右键 a_verif/a_rfp/a_auto 三分支; _open_verif_dialog(node, tab="rfp") 初始切 Tab3。

## 🧩 验证层 = 规范场三层三级树 (v4.0.2, 2026-09-04 老倪 Gauge Theory 重构)
- **主唯一依据 = src/lerobot/verification/node_func_tree.py** (新注册表 550 用例):
  规范场三层 → 节点 → 功能 → 用例: G1 场感知 (9节点/45功能/225用例) · G2 协变操作
  (10/50/250) · G3 对称认知 (3/15/75); 22 节点 × 5 功能 (名 5~10 字, check_contract 强制)
  × 5 用例 (auto 339 / semi 16 / manual 195); FUNC_CHAINS 模块化组合链 (截面合成)。
- **VerificationLayer.run_tree(skip_slow, only_node, log_fn)** 三级执行器: auto 全真实断言
  (引擎/六层源码/标定/流形/planner 规则/源码审计 _audit); semi 需真机/DISPLAY 默认跳过;
  manual 永不自动跑 (清单展示)。**零空转铁律**: 自动用例禁止 `return True, "说明"` —
  纯文字断言一律改 _audit(文件, needles) 真实读源码, 或真算数值/委托 t_F_*。
- CLI tools/ss_feature_tests.py: --list 三级清单 / --only-node <key> / 全量 auto (semi 跳过)。
- GUI verification_dialog.py: 树按三层分组 → 节点 → 功能 → 用例, ▶运行自动用例后台线程
  → 结果 ✅/❌/⏭ 注入树; 导出 Excel 4sheet (功能清单含规范场列/功能用例/分类统计/测试明细)。
- ⚠️ CLI 直接执行坑: `python tools/ss_feature_tests.py` 时 sys.path 无仓库根 →
  `import tools.*` ModuleNotFoundError → VerificationLayer.__init__ 已把 root+tools/gui 入 path。
- 旧 45 项 FEATURES/FEATURE_META (v4.0.1) 保留兼容 (旧入口/run_all 不破坏), 不双轨展示。
- 规范场映射: G1=底空间观测(YOLO/2D3D/触觉/融合/obs/data/world/AOI/lat), G2=联络动作+流形
  (ff/est/pred/innov/sched/limit/act/calib/mani_c/mani_p), G3=规划编排诊断 (llm/reason/skill)。
- 画布 ssfeat/sstest 双击/右键 → _open_verif_dialog (0.0 分支最前, 防 source 字段抢先)。

## 断点挂起"卡死" = debugpy 暂停全进程 (v4.0.1, 2026-09-04 老倪两次"只能鼠标动,其它程序都不动")
- **认知修正**: 之前 real-run-gui-integration reference 写"断点命中在后台线程 → GUI 不冻"是**错的** —
  pydevd/debugpy 断点命中默认挂起**整个进程所有线程** (VSCode 线程面板全变暂停)。真实化 run() 虽在
  daemon 线程, detect_3d/fuse_sensors 断点命中一样冻 GUI 主线程 → 表现"只能鼠标动"(X server 画的
  鼠标还在动), 窗口/日志全停。F5 调试 + 引擎/感知源码断点 + ▶运行 是四次同款卡死的共同组合。
- **防御 (v4.0.1 代码)**: `_start_real_sim` 开头检测 `debugpy.is_client_connected()` (listen 未附加不算,
  比 sys.gettrace 可靠) → 日志+气泡醒目提示: 断点命中=GUI 暂停非故障, 处理 = ①F5 放行(逐次)
  ②删引擎断点只留目标行 ③取消 F5 直接跑。**判定法不变**: 卡死先 `sudo py-spy dump --pid <gui>`
  主线程栈 `do_wait_suspend` = 断点冻结 (删断点即恢复, 无需重启)。
- **真实化运行进度可见 (v4.0.1)**: RealStateSpaceSim.run() 每 25 步 self.log 周期进度
  ([step] 阶段/残差/接触p/grp/YOLO检出率) + simulink `_real_logs/_real_log_ix` 共享引用 →
  `_on_real_poll` 每 400ms 增量 flush 到 GUI 日志 — 修 5-9 分钟静默 = 用户误判"卡死" (两次报告背景)。
  新改动后重启 GUI 必给日志三连证据。

## 🧩 验证层 Feature/Test 节点 = VerificationDialog (v4.0.1, 2026-09-04 老倪: 按钮导出 Excel + 分类)
- 画布 ssfeat/sstest 双击/右键 → `_open_verif_dialog` → tools/gui/verification_dialog.py:
  45 项表格 (ID/域/类别/模型角色/功能名称/模型特点/层/验证方式) + 分类统计行; feature 模式有
  「▶ 运行全部测试」后台跑 (skip_slow, 结果列 ✅/❌/⏭); 「导出 Excel」= openpyxl 3 sheet
  (功能清单/分类统计/测试明细) → scp 上传 datadrive.world → URL。
- **数据源**: FEATURES 6 元组不动, 新增并行 `FEATURE_META {fid: (基本功能|泛化功能, 角色, 特点)}`
  45 条 (基本29/泛化16; 角色: 感知模型6/世界模型7/决策4/规划3/安全2/引擎8/平台5/标定3/GUI7) —
  加在文件末尾 main() 前 (放 FEATURES 后会错位 _EXTERNAL_LOC 行号锚点 47/97!)。list_features 返回
  dict 列表 (GUI/导出复用), 打印带分类统计。基本=确定性规则(引擎/状态机/安全/画布), 泛化=模型驱动
  (感知/世界模型/规划) — 感知模型=把传感器变状态(YOLO/触觉/AOI/融合), 世界模型=预测演化
  (估计器/动力学/校正/潜空间/流形)。
- **⚠️ 分支顺序坑**: ssfeat/sstest 节点带 `source` 字段 → 双击会被更早的"数据源切换"分支拦截,
  verif 分支必须放 on_node_activated **最顶部** (0.0), 不能放 state_space 分支附近。

## DataWorld 逐帧同步 — 3D 与画布信号同帧 (2026-09-03 v3.4.6, 老倪: 参考百度 Apollo Dreamview)- **架构语义**: 每个画布节点 = 一个算法模块 (channel, io key = 画布节点名); 引擎每步把
  各模块 in/out 发布到数据世界 → 画布播放 / 3D 视图 / 数据总线消费**同一 DataWorld +
  单一帧游标** → 点 ▶运行 后 3D 渲染数据与画布实际信号严格同帧 (Dreamview:
  "模块输出 → 主视图渲染", Layer Menu = 通道显示开关)。
- **数据源**: `state_space_sim.run()` 的 `tr["io_trace"]` **逐帧全量** (v3.4.6 起每步
  append — 原来每 25 步抽稀是 3D/总线跳帧的根因)。帧 = `_io_snapshot()` 产物:
  9 引擎模块/23 画布节点 key, value={"in"/"out": [(label, value)...]}。
- **tools/gui/data_world.py — DataWorld 类**: 由 tr 构建, frames=io_trace;
  cursor (set_cursor) = 单一游标; frame(step)/module(name, step)/module_out_values/
  stage/diff_modules; **module() 前缀匹配回退** (画布节点名带 [W-01] 后缀时按
  MODULE_ORDER 找包含匹配)。
- **_ss_tick 播放游标铁律**: 播放按**引擎步线性推进** — `stride = (n-1)//_ss_ticks`,
  `idx = round*stride`, _ss_ticks = max(60, min(120, n*0.006)) (≈5-7s 播完)。
  **禁止再按 io 快照数均匀抽样** (n 快照≈25 时 idx 每 80ms 跳 25 步 = 3D 大步跳变,
  用户感知"3D 与画布信号不同步")。每 tick: dw.set_cursor(idx) → 节点动画轮转 +
  execute_node_logic → log 该步数值 → 3D set_frame(idx) + set_active_node(节点名, dw)
  → 总线 feed 当前帧。
- **3D「▶ 画布信号」面板行** (ss_dreamview.lbl_mod): set_active_node(node_name, dw)
  显示画布正在执行的节点 + 该模块本帧 out 摘要 (from data_world import _fmt)。
- **播放结束对齐**: _ss_finish 把 dw cursor + 3D set_frame 精确推到引擎末帧 (stride
  余数可能差几步, 不补 3D 终态停在末帧前 = 显示不一致)。
- **数据总线静态视图防卡**: model_tree.refresh 时间序全量铺会 500×60 行卡死 →
  抽稀 ≤150 帧 (`_trc[::_stp]` + 补末帧); 运行中动态 feed 不受影响 (90 tick × 60 行
  ≈ 5400 行动态追加可接受)。
- 验证: 引擎 305 步/305 帧 0.05s 零开销 (io 帧 dict 每步本就构造, 只多 append);
  端到端 offscreen: SimulinkModule() + load_flow_file(state_space_obs.json) +
  _start_state_space_sim() → processEvents 推进 → 播放完成游标=末帧; 假 3D 探针
  (set_trajectory/set_frame/set_active_node 记录) 验证收到连续帧 + 节点广播。
- ⚠️ _ss_tick 内 execute_node_logic 用 `_ss_order[min(_ss_round, len-1)]` 保底防越界;
  播放完成判定 = `idx >= n-1 or round >= max(_ss_ticks, len(_ss_order))`。

## 3D 世界操作按钮 (2026-09-03 v3.4.7, 老倪: "3D 上也要有运行按钮, 与画布统一; 一点画布运行 3D 就被覆盖")- **DreamView3D 绑定画布 module**: 构造签名 `(tr, parent, on_top, module=None)`; open_ss_3d
  传 module=self, 复用窗口分支也补 `w.module = self`。无 module (命令行自测 __main__) 不建控制区。
- **左侧「🕹 3D 世界操作」区** (图层列表上方): ▶运行 = module.start_sim() (**画布统一入口**,
  状态空间画布 → 引擎+逐帧同步 3D), ⏹停止 = module.stop_sim(), 📌窗口置顶 toggle
  (setWindowFlag(Qt.WindowStaysOnTopHint) + show() 重生效; 手动开置顶 → 画布运行/弹窗不再盖 3D),
  引擎状态行; **300ms QTimer 轮询** (module._ss_timer.isActive / _sim_running / btn_run.text) →
  ▶运行/⏹停止 禁用启用联动 (同一引擎同一状态)。
- **画布 ▶运行开始 raise 可见 3D 窗口** (raise_ + activateWindow) — 修"点画布运行 3D 被画布覆盖";
  只 raise 不置顶 (置顶会盖画布 = 2026-08-26 黑屏投诉重演), 用户可点 📌 手动置顶。
- **坑**: PyQt5 枚举比较 `w.windowFlags() & Qt.WindowStaysOnTopHint == 0` 断言挂 (枚举 == int 语义),
  必须 `int(...)` 包裹; DEBUG bool() 会掩盖该问题 (bool 与 ==0 不等价)。
- 验证 7/7 offscreen: 控制区创建/▶运行→start_sim/⏹停止→stop_sim/置顶 flag 随 toggle/
  busy→▶禁用⏹启用/就绪恢复/无 module 不建控制区。

## 播放"阻塞"根因 = execute 冷加载 + 平滑播放 (2026-09-03 v3.4.8, 老倪: "运行后没有连续动作, 好像阻塞了")
- **真机计时铁证**: 播放 tick 间隔中位 81.6ms 正常但**最大 1632ms** = 📡传感器融合节点
  execute_node_logic 真跑 → `_yolo_ensure_aligner` **冷加载 1.6s+** (metaworld MT1 env +
  YOLO 模型构造) 冻结主线程 → GUI "阻塞"。判定法: 包 execute 打点计时
  (`_slow_exec` 包 execute_node_logic, dt>30ms 打印) — 别猜。
- **execute_node_logic 加 demo 参数 (v3.4.8)**: ▶运行 播放演示 = demo=True 轻量路径
  `_demo_node_output` — 读 module._dw 当前帧该节点 out (引擎真实算的, 同源不伪造) 打印,
  **不重跑节点真实函数** (YOLO 采样/LLM/传感器融合重执行又慢又重复 — 引擎 run() 已真执行过)。
  ⏭单步/右键运行/双击 = demo=False 仍走真实 fn (VSCode 断点可进, 调试链路不变)。
  **铁律: 播放动画循环里禁止同步执行可能慢的真实节点函数** (YOLO/LLM/env 构造类)。
- **播放节奏 (v3.4.8)**: 80ms×60tick 大步跳 (60 tick 播 305 步 = 每 80ms 跳 5 引擎步 →
  视觉一顿一顿"不连续") → **30ms/tick 逐引擎步**: `_ss_tick_ms=30`,
  `_ss_ticks = max(n_order, min(n_steps, 267))`, idx = round*stride, 结束 idx>=n-1。
  3D set_frame **每 tick** (连续); 节点动画轮转/execute(demo)/日志(~40行)/总线 feed
  按抽稀散布 (exec_every = ticks//n_order 等), 不再每 tick 全量刷。
- **resize 自动取景**: 窗口尺寸变化 >6% 且未手动转视角 (`_user_cam` eventFilter 鼠标旋转
  标记) → 250ms 防抖后 `_fit_view("fit")` 场景撑满放大视口。诊断结论: 布局本身正常
  (view 926→2814px = 3 倍, GL 视口自动放大), 用户"没放大"多为最大化错窗口/旧版未重启。
- 验证: 卡点 1632→70ms (传感器融合节点 0.23ms), e2e 305 tick 播放完成游标=末帧,
  _update_frame 0.9ms/帧渲染零压力 (真机)。

## pyqtgraph GL 跨上下文 shader 失效 (2026-08-28, 3D 视图二次打开背景丢)
**症状**: 老倪「3D 视图第二次打开, 场景背景没了」— 首次打开正常, 关窗再开只剩纯背景色。
**根因**: pyqtgraph `opengl/shaders.py:420 initShaders()` 模块导入时编译一次、全局缓存
ShaderProgram, 句柄绑定**第一个** GL 上下文。窗口 close 后再开 = 新建 GLViewWidget =
新 GL 上下文 → 旧句柄失效 → 绘制报 `GLError 1281 glUseProgram(3) invalid value`
(debug.printExc 打 RuntimeWarning, 界面无弹窗)→ 所有 GL item 静默失败。
**验证方法** (tools/gui 下跑, DISPLAY=:0): `view.grabFramebuffer()` 统计非背景像素,
实测 531589→0 px 复现; 同一窗口 close→show 像素不变 (531589→531589) → 只复用不新建。
**修法**: open_ss_3d 窗口复用逻辑从 `if w.isVisible()` 改为 `if w is not None` —
close 只是隐藏 (无 WA_DeleteOnClose), 对象+GL 上下文都在; 数据源变了再
`w.set_trajectory(tr)` 重建场景; close 停掉的 `_cam_watch` 定时器要重启。
`_ss_3d_windows` 清理用 `sip.isdeleted` 判断, 别用 `isVisible` 过滤 (会误删可复用窗口)。
**连带坑**: `_build_scene` 重建时同一 item 被多 key 引用 (yolo 列表 ↔ yolo_hand/peg/hole),
重复 `view.removeItem(x)` 抛 `ValueError: x not in list` → 重建中断。修: 按 `id(x)` 去重 +
`except (ValueError, RuntimeError)` 容忍。**铁律: pyqtgraph GL 窗口一律复用不新建;
重建 GL item 树必须去重 removeItem。**

## simulink 字体大挤调小 (2026-08-28, 192DPI)
老倪「终端字体/画布方框字体/工具栏按钮字体都大, 很挤」。真机 `logicalDotsPerInch=192`
(X 上报 96, 但 Qt 用 192) → 12pt 渲染成 **32px**。调小一档: 工具栏 mk_btn 12pt→10pt
(minHeight 34→30, padding 7x14→6x12); 终端 log_box 12pt→10pt; 画布节点标题
12/11/10→10/9/8; 节点内部文字/徽章/ID/背景行模型名 11→10、10→9; 连线数据流标签 10→9。
**⚠️ offscreen 是 96 DPI (10pt=14px), 真机 192 DPI (10pt=27px)** — offscreen 只能验
布局逻辑/文字放不放得下, 像素尺寸验证必须真实 DISPLAY=:0。验证:
`QFontInfo(QFont('Arial', pt)).pixelSize()` 打真机 px。

- **🗂 模板多行展开布局 (2026-08-05, commit ada65fb1, 老倪: \"你每次都是从一条直线上开始给出, 你需要把所有节点展开, 不要重叠成一条线; 类似的功能, 例如 Action Head, 应该垂直对齐\")**: **用户偏好 — 模板加载节点禁止单行横排 (13+ 节点一条直线出画布外)**。REFERENCE_APPS 条目支持可选**第4元素 layout** (3元组模板兼容, 4元组才启用): `layout = [[节点名...]每行]` 网格 — **行 = 模型分支 (y 递进 230), 列 = 功能角色 (x 递进 260), 空串 \"\" 占位跳过**。同名节点多行出现 → 取各自候选坐标 → **同列垂直对齐** (三模型 Action Head 都落第5列 x=1420, y=80/310/540)。load_reference_app 加 layout 分支: 先 `pos.setdefault(nm, []).append((x,y))` 收集同名多行坐标 → 每节点取 `next(p for p in cands if p not in used)` (used 去重保证共享节点只画一次, 如 metaworld 三行共用顶部一个) → 保障单行。**⚠️ REFERENCE_APPS 改 4 元组后全仓库 3 处 `for nm, nodes, links in REFERENCE_APPS` 解包全崩 (ValueError) — 必须逐个改 `for item in ...: nm=item[0]`** (参考应用按钮 1758 / _act_build_link_existing / _act_build_finish)。验证 (offscreen): 三模型模板 18节点 / Action Head `len(set(x))==1` 且 `ys == [80,310,540]` / metaworld 只画一次 / 双模型+ACT-Meta 回归 (3元组) 不崩。
## 控制台两个高频故障 (2026-09-18 实测, 都已修)

### ① 模式下拉切「🔌 本地连接 (Local)」→ 整个控制台 SIGABRT (无弹窗, 直接消失)
根因: `_on_mode_changed` 里 `modes=["sim","local","real"]` 但 `Z700_ROS2_NODES` 只有 sim/real 两个键
→ `KeyError: 'local'` 抛在 Qt 槽里没人接 = **Qt 槽内未捕获异常 → qFatal → 整进程中止**
(日志 /tmp/studio_launch.log: `Fatal Python error: Aborted` + traceback 到 studio.py:7317)。
同一类坑 2026-09-14 出现过一次 (`Z700_ROS2_NODES["real"]` 被当 dict 调 `.get()`)。
**纪律: 任何 Qt 槽体都要包 try/except 保障 (异常只记日志, 绝不冒泡) — 这是"点一下就崩"的通式。**
修法: 未知/越界模式键一律退回 sim 表 + 如实打日志; 槽体总保障。
排查证据: `journalctl --user -u zmax-studio --since "…"` 找 `Fatal Python error`, 看 `Current thread` 那几行。

### ② 「输入图像」真机源"永远无画面", 但 L2 实际一直在吃帧
`yolo_input_viewer.py` 的真机源原来**只认 srv 落盘** `live_frame.jpg/.json`
(Orin `/zmax/live_frame` → 本机 Docker `ss_frame_srv_client.py`)。
Orin 侧服务不可达时 (容器日志 `❌ 服务 /zmax/live_frame 不存在 → 退出`) 该文件冻结在旧时间戳
→ 窗口按"不上旧帧"纪律显示空/占位, **而真机图像实际一直在流**: Docker tap 落盘 `cam_rs.png`
(0.x 秒龄, 只读订阅生产话题), **L2 侧 (`ss_yolo_on_real.py` CAND) 吃的就是这条**。
口径: 窗口显示的真机源必须 = L2 实际消费的那条流 → 加同源回退链
`cam_rs.png → cam_fp.png → cam_latest.png → srv_cam.png/.jpg`, 逐文件 mtime 新鲜度 (≤10s),
有新鲜帧就上屏并在状态栏标「来源 / 帧龄 / srv 为何回退」; 全不新鲜 → 占位逐条列候选状态。
**不要改回"只认 srv"**: Orin 红线=零自研程序, 话题落盘才是常驻正解。

## 输入图像窗口「三路源」+ 引擎实况取证 (2026-09-17/18, commit 6ef836a7)
**窗口 = tools/gui/yolo_input_viewer.py, 输入源下拉 3 项: 🎥 真机 RealSense / 🧪 仿真 metaworld / 💻 本机摄像头。**
- 数据根按源分开 (tools/yolo_annot_dataset.py): `data/yolo_annot`(真机) · `yolo_annot_sim`(仿真) ·
  `yolo_annot_usbcam`(本机摄像头) — 三路口径不混, 会话 tag 分别 d405/sim_corner2/usbcam。
- 💻 本机摄像头: `/dev/video0` = Luxvisions Integrated RGB Camera (内置 UVC, uvcvideo 内核自带), 1280x720 MJPG 30fps 可跑满。
  **坑1 (cv2 V4L2)**: `cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)` 报
  "backend generally available but can't be used to capture by name" → **必须换算成索引**(`cv2.VideoCapture(0, CAP_V4L2)`)。
  **坑2 (UVC 独占)**: `_start_source` 非幂等时 (`__init__` 的 singleShot(200ms) + 手切下拉各起一次) 旧采集线程成孤儿 →
  **设备被永久占用**, 之后任何一路都"无法打开摄像头" → 修: start 前先收旧线程 + `join(1.5)` 等 release。
**仿唯一依据语义**: 引擎没在跑时窗口渲染的是 `node_logic._YOLO_ALIGNER.env` (只 reset、**从不 step**) = 静止初始帧
(老倪两次误读成"光模块没插进槽"!). 点 ▶运行 后窗口自动跟随引擎实况帧 (SS_LIVE_FRAME 共享槽, 与 detect_3d 同一帧);
无实况 → 画面顶部压橙字横幅"引擎未运行 · 静态初始帧", 不假动。
**引擎实况取证 (1Hz)**: `/tmp/ss_live_frame.json` = 步号/阶段/**沿孔轴进深 mm**/**横向偏差 mm**/夹持/窗口消费计数,
每轮收尾强制落一次 → 这类"看起来没插进去"的问题直接用数据说话, 不用截图目测。
**窗口通用修复 (同批)**: ①`_clamp_to_screen` 必须按**所有屏幕**判可见性 (只认 primaryScreen → 拖到扩展屏 5s 被拽回,
  实测 t=5.0s 跳回 x=572); ②切源必须**清画面+清框** (只切链路 → 上一路画面残留, 真机源看起来在放仿真视频);
  ③真机源只让**新鲜**帧上屏 (meta.ok ∧ age≤5s), 超 10s 换占位画面写原因; ④标定冻结时不动画面。

## 插销/插槽"没插进槽/横向偏差" — 口径问题, 非控制偏差 (2026-09-18 实测)
**结论**: metaworld peg-insert-side 官方判据 = **杆头(pegHead 站点)到 goal 点** ≤7cm 算成功
(`metaworld/envs/sawyer_peg_insertion_side_v3.py:115`); 引擎把杆头推到 0.6mm 内、横向 2.1~2.5mm → 判据上是"完成"。
但光模块是 **24cm 长杆**(geom box 0.015/0.015/0.12, euler 0 1.57 0 使长轴沿世界 x), 只入槽 6~7cm、约 17cm 横在盒外
→ 老倪肉眼判"没插到槽里、和插槽横向差一截"。**槽道几何**: 盒内两根 3cm 立柱(碰撞 geom size[0]=0.03, world y=box_y±0.06)
形成 y 向 6cm 宽、z 向 6cm 高、x 向 19.2cm 长的通槽; 孔口 site(0,-0.096,0.13) 在盒 +x 面, goal=mouth+66mm(x 向)。
**待老倪定**: 是否改"光模块体坐进插槽"口径 (杆头推到槽道尽头 → 杆体 19cm 进槽) — 动 L2/L3/L4 共用插入段, 须同口径 A/B。
**取证脚本** (tools/): diag_insert_offset_truth / diag_insert_geom_truth / diag_scene_bodies /
diag_pixel_align_peg_slot (corner2 投影: 孔口到杆轴 0.3px) / diag_which_state_on_screen /
diag_compare_window_render (抓窗口与渲染帧逐像素比对) / ascii_render / zoom_insert_region。
**留档**: ~/zmax_data/20260918_0616_evidence/ (MANIFEST.md + 窗口抓图 + 候选帧 + 轮次日志) 与
~/zmax_data/ss_remote/20260918_0615/ (state/proposal jsonl.gz + MANIFEST)。

> 🗣 日志文案 = 完整句子 / 朴素白话（禁止「标题: 名词短语 · 名词短语」堆砌） → `references/log-writing-style.md` (2026-10-17 老倪定规; 存量 ~1800 处按此口径收敛)

## 屏幕"卡死"取证: 先分层, 别乱杀窗口管理器 (2026-10-18 实测)
- 症状组合: 控制台窗不上屏 + 桌面整体无响应 + 只能按电源键。本次实测 **不是内核死机**: journal 连续到底,
  logind 记 `Power key pressed short` ×2 → `The system will power off now!`, 属干净关机。
- 查证顺序: ①`journalctl -b -1 | grep -iE "oom-kill|Killed process|Xid|fence expiration"`
  (本次 `Fence expiration time out i915...chrome` = Intel 显示 fence 超时, 桌面停止重绘);
  ②`systemd[1]: user@1000.service ... memory peak` (本次 26.5G/30G, swap 峰值 13.1G);
  ③控制台日志 `grep "Fatal Python error"` — 本次多次 `Segmentation fault`/`Aborted`:
  **窗不上屏多半是 studio.py 自己崩了, 不是 Mutter 不映射**。
- **禁止** `killall -3 gnome-shell` 救窗口: 会把会话一起带走 (本次 12:26:27 `gnome-session-manager` 停止 →
  掉到登录界面, 外观就是"死机")。要救就按 pid 只杀 studio.py, 再起一个实例。
- 同刻只留一个控制台实例 (每个 ~1.4GB RSS + Qt/3D episode 装载); 重启前先
  `pkill -f "gui-venv311/bin/python studio.py"` 并确认 `pgrep -fc ...` = 0, 再起新的。

## 内存增速取证 (量出来再说泄漏)
- 增速 = 两次读 `/proc/<pid>/status` 的 VmRSS, 间隔 ≥120s 再换算 GB/h; 单点 RSS 什么都不说明。
- **先确认两次采样是同一个 pid**: 控制台会被 systemd/dbus 拉起, 崩一次就换新 pid 并把 RSS 掉回 ~1.3GB ⇒ 跨 pid 的
  "曲线"会把振荡当泄漏 (实测同一 pid 稳定 4.9GB/h, 跨 pid 会算出 0 甚至负增速)。核法: `pgrep -f "tools/gui/studio.py"`
  两次拿到同一 pid, 且 `ps -o lstart= -p <pid>` 一致。
- 按段定位 (涨在哪): `sudo cat /proc/<pid>/smaps` 两次按 (起址, 权限, 名字) 对齐差分 —— `[heap]` 涨 = Python/Qt 对象;
  单个大 anon 段涨 = numpy 数组; 大量小段涨 = 频繁小分配。
- 采样要 root: `py-spy record/dump` 打别人的 uid 进程直接 Permission Denied, 用 `sudo env "PATH=$PATH" py-spy ...`
  (sudo 会重置 PATH, 不带 env 就找不到 py-spy)。py-spy 给的是 **CPU 热点, 不等于分配点**, 必须和 smaps 差分合看。
- 已知结构性底座 (已修, 别再当泄漏): 信号页 `SignalBuffer` 曾对每个信号 `np.zeros(CAP)` = 3.05MB × 1013 信号 ≈ 3.1GB,
  话题注册越多底座越大 (8h53m 可到 20GB); 现为惰性 `CAP_MIN=4096`(64KB) 写满才翻倍。
  **新增任何"每信号/每话题一份"的缓存, 必须惰性分配 + 硬上限**, 否则底座随注册量线性膨胀。

## pgrep -f 会命中自己的包装 shell
- `pgrep -f "<pattern>"` / `pkill -f` 会匹配到 Hermes 自己的 `bash -c "...<pattern>..."` 包装命令行 ⇒ 自杀
  (实测把桥接 shell SIGTERM, 目标反而没杀成)。
- 拿 pid 优先走 `ss -ltnp` 或 pid 文件; 必须按名匹配时锚定解释器路径 (`pgrep -f -- "^[^ ]*python .*studio\.py"`) 并排除 `$$`,
  杀之前 `cat /proc/<pid>/cmdline` 核一眼; 多步 pgrep/kill 写进脚本再跑, 别内联一条命令。
