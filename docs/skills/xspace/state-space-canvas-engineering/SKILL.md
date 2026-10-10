---
name: state-space-canvas-engineering
description: "Use when 改 Z-MAX 状态空间画布(加节点/改接线/重排/清节点)且要保证不把画布改坏。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [canvas, topology, state-space, zmax, verification, links, layout]
    related_skills: [web-agent-canvas-bridge, zmax-state-space-architecture, zmax-console]
---

# 状态空间画布工程 (改节点/连线/拓扑的安全做法)

## When to Use
- 用户要求"加一个节点""把它接到 X 后面""所有 Y 都要进 Z 节点""整理连线/不要交叉/删掉不相关节点"。
- 任何要写 `flows/state_space_obs.json`（画布真源）的改动 —— 包括只加 1 个节点。
- 画布出问题要定位（"连线都没了""节点不显示""控制台起不来"）。

## 铁律: 验收是有层级的, 上一级通过**不代表**下一级通过
| 层级 | 手段 | 只查这一层会漏什么 |
|---|---|---|
| ① 语法 | `ast.parse` | 常量未定义 (`_REPO` 不存在) → 导入即炸 |
| ② **导入** | 真 `import` 一次模块 | 节点 type/端口不合法 → 加载循环中断 |
| ③ **渲染** | 离屏真加载, 数 item | 连线静默全丢 (见下) |
| ④ **字段契约** | 实测服务返回键名 | 闸门读空值 → 静默拒绝执行 |
| ⑤ 运行 | 真跑一次 + 看 Traceback | "改完就好" 的假成功 |
| ⑥ **交互** | 真点一下按钮/双击一次节点, 看目标界面到底变没变 | 日志写了"成功"、画布纹丝不动（handler 里根本没有回画布的代码路径，或副作用静默失败）；**反馈落在节点小字/底部日志栏 ⇒ 用户仍然报"没反应"**（见下节"长任务触发器"） |

**改画布最低要求 = ②+③+⑤**；动到按钮或节点交互的改动必须再加 ⑥。`tools/verify_canvas_render.py`（离屏真加载 → 打印 node items / link items）是标准工具。

## 三类"看起来对"的致命坑 (2026-09-26 实测)
1. **节点 `type` 必须是注册表里的合法值**
   写成 `"node"` → `add_node` 抛 `KeyError` → **`load_flow_file` 的节点循环当场中断 ⇒ 该节点之后的所有连线一条都不建**。
   现场表现极具误导性: **节点 88→87 而连线 167→0**（用户只会看到"画布连线怎么都没了"），异常被吞成一行 `⚠️ 工作流加载部分失败`。
   构图工具里加 type 白名单断言；合法例: `model` / `data` / `hardware` / `condition`（背景行条是 `bg`/`row_bg`）。
2. **端口必须是字符串列表** `["in1","in2"]`
   历史节点里混着 `[{'id':'out1','label':...}]` **字典格式**（本次归一了 ssff/sssched/ssdec 三个）→ 断言/渲染都可能踩。
   归一后把原标签存进 `params._port_labels`，不丢信息。
3. **接线用的常量先 grep 确认存在**
   本次在 `node_logic.py` 的新 `_EXTERNAL_LOC` 条目里用了**不存在的 `_REPO`** → `NameError` 阻塞整个 GUI 导入 → **控制台起不来**（语法校验完全看不出）。
   对照既有写法（如 `_YOLO_DIR`）先确认常量；改完**重启控制台并确认 `Traceback=0`**。

## 加节点标准流程 (六断言 + 备份)
`tools/canvas_add_*_node.py` 的既有范式，逐条断言后才写盘：
1. id 唯一 2. 坐标 int 3. **零重叠**（`bg`/`row_bg` 整行矩形**必须排除**在重叠判定外）4. 落在正确行带
5. 端口存在且**前向**（`f.x + f.w <= t.x`）6. 无重复连线
写盘前 `shutil.copy2` 到 `flows/_archive/state_space_obs_before_<事由>_<ts>.json` 并**打印还原命令**。

**只加一条连线的改动, 验收 = 证明"现有连线一条没动"** (用户最在意这个, 说"现在的连线还很整齐"):
把 `_archive/` 改前快照的 links 与当前 links **剔除新增那条后**逐条比对 —— 各自 `json.dumps(l, sort_keys=True)` 排序后
判相等 + 节点 id 集合不变。**别拿两边的汇总 md5 直接比**: 各人 canonical 形式不同, md5 值本来就不一样,
结论是"逐条相等"这个布尔量(子代理报的 md5 和你复算的对不上 ≠ 它改坏了)。
渲染级连线项比 JSON 少 1 是**既有重复 (f,t) 对被 add_link 去重**(改前同样少 1) —— 别去找那条不存在的线, 也别当成本次丢线。
新线要落成"左进右出": 选源在它所在行带的**左端**、目标在另一行带**右段**, 天然满足 `f.x+f.w <= t.x`,
不许为了接线去挪任何现有节点(挪节点才是把画布搞乱的主因)。

## 新增连线的约定 (端口 + 连线, 2026-10-09 沉淀)
- **端口一律字符串列表** (`["in1","out1"]`); 历史遗留的 `[{'id':'out1','label':...}]` 字典格式要先归一(原标签存 `params._port_labels`)。
- **新线必须前向**: `f.x + f.w <= t.x`(源节点右边界 ≤ 目标节点左边界), 否则渲染成交叉/反向线, 被断言拦下。
- **新增线不得改动任何已有连线**: 写盘前后把 `links` 各自 `json.dumps(l, sort_keys=True)` 排序, 剔除新增那条后**逐条比对相等** + 节点 id 集合不变(别只比汇总 md5)。
- **写盘只走 `flows.save_canvas()`**(自带校验 + 备份); 手工改 JSON 前先 `shutil.copy2` 到 `flows/_archive/state_space_obs_before_<事由>_<ts>.json` 并打印还原命令。
- **范例**: `ssbypv:bypass_out → ssact:in1`(线 id=`lkbypv_net`, 2026-10-09, label「上网通道状态 → 执行器 (借道 proxy 回显)」) —— 源在旁路可视化行左端、目标在自主体行, 前向 `980 <= 15666` 成立;
  加后 **89 节点 / 184 连线(JSON)**(渲染级 183, 少 1 是既有重复 (f,t) 对去重)。剔除该线后与改前**逐条完全一致**(canonical md5 `d6ec2c763de1dac2cef1b543ffaa728f`)。
- 🔴 **跨行接线前先看两端的 x 极值**: 可视化行(`ssbypv`)在整图**最左端**(x≈700), 而 L4/L2 行的业务节点在 x=1500~19000 ⇒
  任何"业务节点 → 旁路可视化"的线**必是反向**, 一定被断言拦下(别花时间试)。要交互就走**数据面**:
  节点写状态(`_SS_STATE[...]` + `reports/*.jsonl`), `SSBypassView` 里加一个**区块**去读它
  (照「🛰 上网通道」区块的既有范式: 同款 `CurveWidget` + 一个 `*_status_line()` 汇报函数);
  若用户要"画布上看得到这条线", 就在**可视化行右端另开一个轻节点**接住(前向成立) ——
  **绝不为了连线去挪 ssbypv 或任何既有节点**(挪节点才是交叉变多的主因)。
- 🔴 **接线 ≠ 被消费 (上一条的镜像)**: 加完线要分清它是**状态线**(只回显)还是**控制线**(真驱动下游) ——
  大多数新加的线是前者, 而用户默认理解成后者。落法:
  ① **上游那个函数真被调用**才有内容输出: 若节点逻辑里只有 ports 声明、没人取那个值写日志/回传, 输出口就是空口
  (应像 `library.py` 的旁路可视化节点那样, 汇报函数里加一行取 `net_channel_status_line()` → 写日志行);
  ② **查下游有没有从该口读值** —— 执行器不读, 就不是控制线;
  ③ 交付时**直说**"这条线目前是状态回显, 不驱动动作", 并把数据真源给出(状态 JSON 绝对路径 + 节点日志行前缀),
  别让它听起来像"已经接通控制了"。

## 拓扑重连纪律 (改执行链 / 加汇聚节点)
- 断言: 端口存在 · 无重复 · 不许反向 · 零重叠 · 删完后 **孤立节点 = 0**（用入/出度统计，排除背景）。
- **交叉必须量化**: 节点中心连线的两两线段交点计数（`tools/rewire_cross_check.py` 可复用），报前/后数字，不要凭感觉说"清晰了"。
- **布局原理（实测有效）**: 斜阶梯（每级 x+320/y+124）的汇聚点若放在阶梯**右上**，扇入必然两两交叉；挪到阶梯**末端右下**则成嵌套式无交叉
  （本次把 MoveIt 从右上挪到阶梯末端: 全图交叉 1175→1136）。
- 行内 barycenter 重排**无效甚至更差**（实测 +9.2% 交叉）—— 交叉由**跨行超长连线**主导（如 `ssdata→swds` 61 对，跨距 8000~17000px）。
  真要清零只有一条路: **渲染层正交折线布线**（沿行间走廊走线），不要靠搬节点硬凑。
- 移动节点会连带产生反向线: 挪"接收方"之前先想清楚它的上游在哪（本次为满足"安全边界 → 原子技能 → MoveIt"的走向，把整条链
  `动作调制器 → 安全执行边界 → 原子技能阶梯` 一起左移，否则 `sslimit(13666) → sssk2(10219)` 就是右→左反向线，被断言拦住）。

## 清理节点 (删"不相关节点") 的客观判据
先用 `tools/canvas_level_audit.py` 与入/出度统计拿事实，**别凭感觉删**:
- 本次实测: 无执行注册 **0** · 真缺口 **0** · 完全孤立 **0** ⇒ 画布本来就是接线完整的, 没有"死节点"可删。
- 可删的只有**有文档依据**的: 属于已关闭任务线的节点（例: 参数寻优线关闭 → 通用算子 A/B/C 节点）。
- 删前跑安全判据: **删除后每个邻居仍 ≥1 入且 ≥1 出**（不许产生断链）；删后复扫孤立=0 + 渲染复核 + 控制台重启。

## 工程架构 (2026-09-28 迁移后): 逻辑在包内, GUI 只显示

节点逻辑与画布 JSON 已从 GUI 目录搬到工程包里 (lerobot 哲学: 能力有注册表、实现有归属、GUI 只是调用方):

| 东西 | 真源 (改这里) | 说明 |
|---|---|---|
| 节点逻辑 (148 个注册 key) | `src/lerobot/engineering/nodes/library.py` | 原来在 `tools/gui/node_logic.py` (5129 行) |
| 注册表/匹配 | `.../engineering/registry.py` | `register(key,[关键字],doc,fn)` · `match_node(name)` |
| 执行派发 | `.../engineering/runtime.py` | `execute_node_logic(module,node,...)` · trace · 演示 |
| 源码视图/编辑 | `.../engineering/sourceview.py` | 双击看源码/改逻辑/恢复默认的后端 |
| 画布 JSON | `.../engineering/flows/state_space_obs.json` | 仓库根 `flows/` 是指向它的**软链**, 老脚本零改动可用 |
| 路径 | `.../engineering/paths.py` | 别再 `dirname(__file__)/../..` 上溯 |
| 档位契约 | `.../engineering/levels.py` | L2/L3/L4/L5 「必须还能干的事」+ `check()` |
| 档位索引 | `.../engineering/nodes/by_level.py` | 节点↔key↔函数 (自动生成) |

`tools/gui/node_logic.py` 现在只有 33 行**兼容壳**(转发包命名空间) —— 老写法 `import node_logic` 照旧可用,
但**不要再往里写逻辑**。

三条硬规矩:
1. 改节点逻辑 → 只改 `nodes/library.py` (关键字要和画布节点名对得上, 否则双击落兜底/不可执行)。
2. 画布 JSON → 只经 `flows.save_canvas()` 写 (自动备份 + 校验不过拒写); 写 `flows/` 软链也通。
3. 改完必跑 (数字必须与迁移基线一致):
   `gui-venv311/bin/python tools/verify_engineering.py` (架构自检 6 项: 逻辑住包里/JSON 真源/档位契约/壳一致)
   `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_canvas_render.py` (应仍 **87 节点项 / 172 连线项**)
   `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/canvas_level_audit.py` (应仍 R1 15·R2 34·R3 13·R4 7·R5 3·真缺口 0)

⚠️ **注册 key 重名会静默覆盖**: 同一个 key 注两次 ⇒ 后一条把前一条的 fn+关键字一起换掉,
画布上那个节点就**永远 match 不到逻辑** (实测 `ss_pred` 被「先验动力学」与「流形专家」重复注册,
导致「📈 先验动力学预测器」长期不可执行)。每加节点/改关键字后跑 `levels.check()` 或
`match_node(<画布节点名>)` 验证返回非 None。

## 执行派发链本身会"静默死" (迁移后必查 runtime.py)
- 2026-09-28 `node_logic.py` → 包 的迁移**漏搬两处依赖**: `runtime.py` 用了 `os.environ` 却没有 `import os`(NameError),
  `_demo_node_output` 还引用着留在 `nodes/library.py` 的 `_YOLO_CACHE`(**悬空引用**)。
- ⇒ **任何节点经文档化入口都跑不起来**, 而 GUI 单步外层是 `try/except` ⇒ 异常被**静默吞掉**。
  症状与"接线没接好"**完全一样**(节点看得见、双击没反应) ⇒ 会把人骗去改画布(本次差点白改一版)。
- 判据/修法: 用**真入口**跑一次, 别靠 GUI 点击 ——
  `gui-venv311/bin/python -c "from lerobot.engineering import runtime; runtime.execute_node_logic(<节点>)"` 报 `NameError` 即命中;
  修完**两条路径各验一次**(`engineering.runtime` 与 `tools/gui/node_logic.py` 兼容壳), 再重启控制台确认 `Traceback=0`。
- 排查顺序: **"节点不执行"先查派发层(runtime) → 再查注册/关键字匹配 → 最后才怀疑画布接线**。

## 按钮/节点"点了没反应"的分层取证 (别猜, 证据链三级)
1. **handler 跑了没有** —— GUI 日志**始终**落盘: `_log` 无条件写 `/tmp/simulink_log.txt`(与底部日志区是否展开无关);
   studio 的 stdout/stderr 在 `/tmp/studio_launch.log`。日志里出现该按钮自己的行 ⇒ 点击确实到达了代码。
2. **handler 里有没有"回画布"的路径** —— 看它是否碰 `self._items` / 节点属性 / `update()` / scene。
   只做 `subprocess.Popen(...)` + `QDesktopServices.openUrl(...)` 的 handler **结构上不可能**让画布动 —— 那不是故障, 是没接线。
   工具栏按钮的验收口径: 点击结果必须落在**用户正看的那个界面**上(画布节点上画帧/状态小字/横幅),
   只弹外链/只写日志 = 用户眼里"没反应"。
3. **外部副作用真发生了吗** —— 报"已打开"不算: 查进程 (`ps -o lstart`) 与浏览器 `History` 库里搜 URL。
   自报的成功日志 ≠ 副作用发生（实测: 日志连打三次"页已打开", 但点击时刻无浏览器进程、History 里 0 条该 URL）。

   外部副作用的两个常设坑（都是"点了没反应"的真因）:
   - **地址别缓存**: 开页 URL 里含 LAN IP 时, 每次开页前重取并 `curl -s -o /dev/null -w '%{http_code}'` 实测可达。
     工位机 WiFi 走 DHCP, 重新租约**一分钟内**就换 IP ⇒ 打印出去/存下来的地址当场作废。
   - **要给另一个界面送画面就拉单帧快照**, 别在其中嵌 MJPEG: 视频流侧已有 `/snapshot/overlay_local.jpg` ·
     `/snapshot/overlay_arm.jpg` 等端点(实测 200 / 80KB / 0.8ms 本机), 定时器拉帧 → QPixmap → 节点 `video_pixmap` 即可。

## 长任务触发器的反馈必须"不可能看不见"(按钮起后台流水线)
- **节点上画状态小字 = 等于没有**: 87 个节点的画布里, 即使 `paint` 真画了 `L5 · annotate 3/6`,
  用户读不出来、自己看截图也读不出来 ⇒ 他连报三轮"点击运行没反应", 而功能其实每次都真启动了。
- **合格形态(2026-10-01 用户定稿, 以此条为准)**: **画布上不铺任何状态文字** —— 用户看到画布上的大字后要求
  「simulink画布 `L5运行中` 这几个字太丑了, 在下面终端显示信息就可以了, **赶紧删掉**」。三条交付口径:
  ① **下面终端日志** 承载全部文字, 且**只在内容变化时写一行**(1s 轮询无脑 `_log` 会刷屏 ⇒ 用 `_last_log` 去重);
  ② **他刚点的那个控件上的文字**(`⏳ 运行中 · <阶段>`); ③ **节点边框状态色**(黄=运行/绿=完成/红=失败) ——
  一眼看得出在跑, 又不占地方。落法: 显示函数**保留名字与签名**(调用点一处不用改), 内部改成只 `_log` +
  `hide()` 旧标签, 旧实现改名 `*_canvas_disabled` 留在文件里(可回溯, 比删段安全); 节点上的进度行函数直接 `return []`。
  （更早的形态, 只在用户明确要求恢复时用: 画布 viewport 通栏横幅 —— 必须用 **viewport 坐标**画(场景坐标会随缩放/平移跑掉),
  运行中=黄/橙, 完成=绿, 失败=红, **未运行时不画**; 以及主窗口标题栏 / 右侧栏固定区块。）
- **标题栏是最省事又最稳的一条**: 它永远可见(画布被遮挡/最小化/缩放到看不清也还在), 实现只要在轮询里
  `_w = self.window()`(**不能用 self**: 画布常是子 widget, 标题设错对象 ⇒ 屏幕毫无变化) →
  `_w.setWindowTitle("%s   ⟪ %s ⟫" % (base, banner))`。**首次先把原标题缓存进 `_win_title_base` 再拼**,
  否则会把版本号/项目号那段前缀冲掉; 任务结束时还原。
- **反馈要挂在用户刚点的那个控件上**: 他盯的是自己点的地方 —— 运行按钮的文字变成 `⏳ 运行中 · <阶段>`,
  比在他没看的角落画任何东西都有效。
- **代码改了 ≠ 用户看得到**: 说"改好了"时必须同时说清 **要重启控制台才生效**; 他没重启就继续报"没反应"时,
  不要重复解释"功能其实在跑", 先让他重启一次再看标题栏/横幅。
- **"已在运行 → 不重复启动"这类静默分支也必须显示**(`⏳ 已在运行: <阶段> <进度>`): 用户重复点击时,
  这是最常命中的分支, 只写一行日志 ⇒ 在他看来还是"没反应"。
- **轮询要在打开画布时就自动起**(1~2s 定时器读状态文件 → 写节点 → `update()`), 不能只在"从 GUI 点运行"之后才起:
  否则他开着画布、任务在别处跑时看不到任何东西。状态文件读失败要**静默降级**, 不许抛异常/卡 GUI 线程。
- **验收判据 = 截图**: 启动 → 点运行 → 截图 → 自问"不看底部日志栏, 一眼能不能读出当前阶段?" **读不出就是没过**。
  配套: 状态真源用 `state.json`(status/stage/updated/pid/stage_detail/results/stages_done), 汇报时给"进程 pid + 状态文件 + 产物路径+时间戳"三处, 不要只说"已在跑"。

## 横幅的生命周期: 运行态常显, 终态"闪一下"(否则用户会要求关掉)
- 横幅若**每次轮询都重铺**, 那么只要状态文件停在 `failed`, 它就会永久顶在画布上 —— 用户会直接说"这个提示无法关掉"。
- 规则: `running` 常显(要一直看到阶段) · `ok` 常显 · **`error` 只闪 ~15s 后自动隐藏**。
  实现: 首次展示时记时间戳(`_err_seen = time.time()`), 到点调 hide;_banner 显示前用**局部变量**取时间戳再算差
  (写成 `time.time() - self._err_seen` 会被类型检查/None 分支咬到)。
  **新一轮 running/ok 时把标记清空(`= None`)**, 否则下次失败再也不提示。
- **历史终态不是"当下故障"**: 启动后读到的是上一轮的 `failed`, 文案要写"**上次** … 失败: <原因>",
  不要常驻一条红色"失败"—— 用户会以为现在崩了。
- 失败文案要**带原因**: 从状态文件 `results` 里找第一个 `ok=False` 的阶段, 拼成 `<阶段>: <reason>`;
  只显示"失败: slots"他看不懂, 显示"尚无已记录槽位(等演示)"他才知道下一步做什么。
- **别在终态 `timer.stop()`**: 老实现跑完就停轮询 ⇒ 画布/标题永久冻结, 之后在别处起的任务再也不上屏。
  轮询保持常驻(1s), 用"**内容不变则不重绘**"(`if key == self._last_key: 跳过 update`)控开销 ——
  常驻 1s 轮询 + 无脑重绘会一直烧 GPU。
- 进度分母**从状态文件读**, 不许写死: 写死 `n/7` 而实际 9 阶段 ⇒ 一开跑就显示 `9/9`, 用户以为已经跑完了。

## 点击瞬间的反馈: 三个必踩的实现坑
- **同一次同步调用里被自己回写**: handler 先 `btn.setText("⏳ 运行中…") + setEnabled(False)`, 同一函数的后面分支
  又把它设回 `"▶ 运行"` ⇒ 按钮**视觉上永远不变**(用户照旧报"没反应")。修法: 设完再 grep 本函数内该控件的**所有**写点;
  更稳的是把按钮文字交给 1s 轮询驱动(轮询读状态文件 → 写按钮), handler 只负责启动。
- **坐标混口径**: 画布上弹气泡/浮层时把 `scenePos()`(场景坐标)直接喂给要**屏幕全局坐标**的函数 ⇒ 气泡飘到窗口外/被盖住。
  正解 `canvas.mapToGlobal(canvas.mapFromScene(...))`; 气泡内容要用**真实状态**, 不能写死"已启动"(已在运行时会谎报)。
- **"改好了"的判定**: 反馈面必须同时满足 ①他一开机就看得见(打开画布即起轮询) ②不阻塞(鼠标穿透/非 modal)
  ③能走(终态会自己消失)。三条缺一条就会被下一轮投诉。

## 用户正在操作控制台时的改写纪律
- 他在现场演示 / 准备重启控制台时, **冻结** `tools/gui/*.py` 的写操作 —— 你改一半他就起不来或按钮坏掉。
  改前先看 `pgrep -af studio.py` 与 `/tmp/simulink_log.txt` 最近 30 秒有无新增点击; 没写完的改动
  **隔离在独立 draft 文件**(`tools/*_patch.py.draft`)里, 等他演示完再并入 —— 冻结期间照常做不碰 GUI 的活(数据/训练/脚本)。
  **冻结是临时的**: 演示/重启一结束就立刻显式解冻(或自己接手), 并说清剩余工作归谁 ——
  冻结忘了撤, 按钮链就停在他抱怨的那半成品上(他下一次投诉的正是缺的那一半)。
- 冻结前**必须确认文件处于可用状态并说出来**(`ast.parse` + `QT_QPA_PLATFORM=offscreen` 真 import 双过), 否则他重启就是白等;
  同时回读一次"按钮链在不在盘上"(如 `grep -c <闭环脚本名> tools/gui/studio.py`) —— 只写日志的"已冻结"不算证据。
- **不要同时让两个子代理改同一批 GUI 文件**, 也不要在没读上一个交付报告前重复派活:
  先读上一个的报告/产物清单, 确认哪些已完成再派新的(本次"假训练闸门"上一个代理已实现并实测, 重复派了一次, 靠 steer 才拦下)。
- **自己接手改同一批文件前, 先把还在跑的兄弟子代理 stop 掉**: `patch` 工具报
  "modified by sibling subagent … but this agent never read it"(**或 `stat -c %y` 显示的 mtime 不是自己写的**)就是"两个写者"信号
  ⇒ 先 stop + 复核(ast + 真导入 + 关键方法/常量都在)再动, 别直接覆盖 —— 否则你俩各写一半, 用户重启后是坏文件。
- **导入探针的假阴性**: `import` 报 `ModuleNotFoundError: No module named 'version_sync'` 这种**兄弟模块**缺失, 多半是探针 cwd/sys.path 不对
  (不是代码坏)。用 `cd <repo>` + `QT_QPA_PLATFORM=offscreen` + `sys.path.insert(0,'tools/gui')` 重跑一次再下结论, 别据此回滚。
- 用户重启后**先看控制台是否加载完**: 画布离屏加载要几十秒, 期间点按钮什么都不会发生 —— 报"点了没反应"时要先排除这个空窗(`grep -c "已加载工作流" /tmp/simulink_log.txt` + 比对进程 `lstart`)。

## 画布节点的"能力"要先验真 (声明 ≠ 接线)
- **节点画视频的分支是死代码**: `SimNodeItem.video_pixmap` 全仓库只有赋 `None` 那一处、配套信号 `_mlp_frames_ready`
  声明后从未 emit/connect ⇒ `paint` 里那段永远不执行。要给节点送帧得自己接定时器拉单帧 → 赋 `video_pixmap` → `update()`。
- **双击靠节点名关键字匹配** `node_logic.match_node`(最长匹配, 表在 `NODE_LOGIC`): 名字没命中任何关键字就落兜底 ⇒
  节点"看得见、点不动"。加节点时名字与关键字**一起**设计, 并真双击一次。
- 通用判据: 接入前先查目标字段的**写点**(`search_files`)。只有声明、只在 paint 里读 = 没接线; 别把"代码里有这个字段"当既有能力。

## 关键数字基线 (每次改画布前后都要对)
| 指标 | 基线 | 怎么查 |
|---|---|---|
| 画布节点项 / 连线项 | **89 / 183** (2026-10-09 实测; 2026-10-08 为 89/182 · 迁移时 87/172) | `verify_canvas_render.py` |
| 节点数 / 连线数 (JSON) | **89 / 184** (2026-10-09 实测; 2026-10-08 为 89/183) | 直接数 `state_space_obs.json` |
| 档位审计 | R1 15 · R2 **36** · R3 13 · R4 7 · R5 3 · 真缺口 0 · 无执行注册 0 | `canvas_level_audit.py` |
| 档位测试 | L2 275/275 · L3 94/94 · L4 178/178 | `xvfb-run -a ./gui-venv311/bin/python tools/ss_level_tests.py --level Lx` |

加 L4 节点的落位判据: 别用"全域最大空档"硬套 —— 语义节点应在它的**上下游之间**的区间里取空档
(如标定节点必须落在 `标定层(sscalib)` 与 `被标定引擎(ss_mani_eng)` 之间), 否则为凑空档会接出反向线被断言拦住。

## 单步跟随 / 定位 / 逐节点实现审计 (2026-10-09, v5.22.0)
老倪: 「我要全面检查状态空间工程的每个节点的实现; 单步运行, 运行到哪个节点哪个节点高亮,
**而且画布要跳到这个节点** —— 画布太大了, 我找不到单步节点到底在哪里」。

**高亮本来就有** (`node["status"]="step_active"` → 金框 2.8px, 或 `node["hl"]`), 缺的是**跳转**。落法:
- `SimCanvas.focus_node(node_id, min_scale=0.45, max_scale=1.6)`: 缩放夹到看得清区间 → `centerOn(节点包围盒中心)` →
  `viewport().update()`。**必须夹缩放**: 用户在全览缩放(0.05)时直接 centerOn 依然看不到东西。
- `SimCanvas.fit_all(margin=240)`: 所有节点 `united` → `fitInView` → **回来同步 `self._scale`** (Ctrl+滚轮的 `_scale` 是真源)。
- 挂钩点选在 `_highlight_node(node, ms, follow=True)` (它是所有节点级高亮的公共入口) ⇒ 单步/右键运行节点/全局运行
  都自动获得跳转; 开关用工具栏 `☑ 🎯 跟随单步` (默认开), 关掉时**仍要在终端报一行位置**。
- **同一节点 2 秒内只跳一次**: 一次单步会经 `step_sim → _run_node_single → _highlight_node` 两条路进来,
  不去重就跳两次、终端刷两行。
- 反馈口径不变: **画布上不铺文字**, 位置/进度只进下面终端; 画布留给金框与状态色。

**逐节点实现审计** (`tools/ss_node_impl_audit.py`, 只读): 每行 = 序号/id/名称/层级/实现 key/是否在单步序/**文件:行**。
- 实现真源: `registry.match_node(名) → key → fn`; 位置用 `sourceview.get_node_location(key)`
  (自动处理 `_EXTERNAL_LOC`, 真实现在 `left_right/state_space/*.py` 等外部文件, 并按符号名现搜行号)。
- 单步序判据 **直接调用 GUI 的 `_ss_node_cap_level` / `_ss_is_observer`** (不是抄一份), 再用内联副本**逐节点交叉核对**
  —— 两份不同步时立刻暴露。实测 89 节点(功能 74/背景 15) · **实现命中 74/74** · 判据核对 74/74 ✅。

配套验证: `tools/verify_step_follow.py` (离屏真建 SimulinkModule + 真加载画布, 9 组交互级断言:
渲染回归 / 控件在位 / 实现位置 / 真跳偏差 / 跟随开-关 / 定位 / 全览 / 金框)。

### 两个必踩的坑
1. 🔴 **`load_flow_file` 会给每个节点重新 `gen_id()`** ⇒ 文件里的 id (`sssensor`/`n_calib_mani`) 在 GUI 内存里**查不到**,
   只有运行时生成的 id 有效。**任何"按 id 找画布节点"的代码必须带名字/语义标记兜底**
   (既有 `_ov_live_target_item` 就是这么写的)。写盘的 `ss_node_sync.py` 之类也要补兜底,
   否则用户从控制台「另存为」重写过 id 后就再也找不到节点。
2. `_follow_to` / `_highlight_node` 必须能吃 `node is None` (画布为空/名字没匹配) —— 否则点一下就 Traceback。

## 画布右侧「参数标定」侧边页 = 工程的 测量/诊断/标定/配置 (2026-10-09, v5.23.0)
老倪: 「将①~⑥ 这 6 个运行开关整合进画布右侧的参数标定侧边页面, 这个页面对应工程的 测量 诊断 标定 配置;
这个侧边页面, 你检查一下其它功能, 没有用的都删掉」。

**面板是 `model_tree.py` 的 `ModelTreeDock`** (2026-08-14 起嵌在 SimulinkModule 右侧 split 列, 不是 dock widget),
顶部一个 `cmb_view` 下拉切视图。四轴分组 (11 视图, 标签直接带轴名):
📏测量 数据字典(tree)/状态空间变量(ss_tree)/性能指标(perf)/数据总线(bus) ·
🔍诊断 运行汇总(run_summary)/场景状态(scene_state) ·
🎛标定 参数标定(pole_place+tree同屏)/现场标定(stage_calib)/数学分析(lbl_math+plot+response) ·
🔧配置 工程需求(eng_req)/运行开关(run_cfg)。

> ⚠️ 2026-10-09 晚 (v5.24.0) 已**收紧为 5 视图** —— 上表里 perf/scene_state/run_summary/
> pole_place/stage_calib/math/eng_req 已停用 (挪 `_model_tree_ffpd_legacy.py`), 见下面 «v5.24.0 收紧»。

### 把工具栏开关「归位」到侧边页: 搬, 不是复制
- 做法: `attach_run_switches({...})` 把 6 个 `QCheckBox` 从工具栏布局 `removeWidget` 后再 `addWidget` 进右页
  —— Qt 控件**只有一个父**, re-parent 后**是同一个对象** ⇒ 所有运行路径读 `self.chk_*` / `getattr(self,'chk_*')` **一字不改**。
  这比"新做一套控件再信号同步"好: 不存在两份状态, 天然零回退。
- 工具栏留一个入口按钮 → `_show_run_cfg()` 把下拉切到该页 (`cmb_view.setCurrentIndex(len(VIEW_KEYS)-1)`) 并 `refresh()`。
- 页面每行给: 开关本体 · 适用档位 chip · 作用 · **生效位置(文件:行)** · 实测代价(风险行橙色);
  档位 chip 按画布「能力档位」节点 `params.cap_level` 判定命中, 本档无效的开关显示 `(本档无效)` —— 一眼看出这个勾现在管不管用。
- `_switch_view` 要**表驱动** (`VIEW_KEYS` 一处定义索引→控件), 否则每次重排视图都要改 10 个索引 if, 必错。
  重排时注意保留老行为 (例: 参数标定视图 = 极点配置器 **+ 数据字典树同屏**)。

### v5.24.0 收紧: 11 视图 → 5, 右侧栏重点 = 配置 + 标定 + 主参数 M
老倪: 「右边侧边栏, 重点是 配置 和 标定, 以及主参数 M; 其它功能要精简, 没联系的**全注释掉**, 确定没用的删掉」。

**【核心判据】「这个页跟状态空间工程有没有真联系」= 画布真源里有没有它读的键** (不是"点了有没有反应"):
```bash
C=src/lerobot/engineering/flows/state_space_obs.json
for k in z700_internal gain_schedule; do echo -n "$k="; grep -c "$k" $C; done   # 都是 0
```
状态空间画布没这两个键 ⇒ `analyze_system()` 走 else 分支填**硬编码默认**(m=1.0/b=2.0/k=5.0),
极点配置 `_write_back` 直接弹「当前画布无 Z700 内部模块」, 现场标定找不到状态机节点
⇒ 性能指标/场景状态/运行汇总/数学分析/参数标定/现场标定/工程需求 7 页**看着有数、与画布无关**
(= 工程师最恨的假数)。它们属于另一套「前馈 PD 顶层」画布 (带 `z700_internal`)。

处置手法 (满足"注释掉"且让 4300 行文件瘦一半): **8 个部件类 + 5 个分析函数整体挪到
`tools/gui/_model_tree_ffpd_legacy.py`** (带复活说明), 原位置留注记注释;
面板侧: `cmb_view` 5 项 + `VIEW_KEYS` 表。留下的 5 项全有真连接:
🧮 主参数 M(画布 M 节点 params) · 🔧 运行开关(`self.chk_*`→引擎分支) · 📏 数据字典(画布 params+feature.dbc) ·
📏 状态空间变量/数据总线(引擎 `_ss_tr` io_trace)。

**新页「🧮 主参数 M · 测量/标定/诊断/配置」** (`MasterParamMView`, 默认页): 数据源 = 画布 M 节点
(`n_calib_mani`) 的 `cfg_entries/cfg_snapshot/measure_view/calib_view/diagnose_view/task_layer`
(由 `ss_node_sync.py` 从真源同步进节点) ⇒ 页 ↔ 节点 ↔ 文件 同源。按钮: ✏️ 写 M (走
`zmax_params.write_manifold_M`: 范围校验+只改 `manifold_engine` 键+回读) / 📥 同步 / 🔁 刷新 / 📋 复制;
无节点时诚实空态 + 给补救命令。

### 三个必踩的坑 (v5.24.0 实测)
1. 🔴 **`load_flow_file` 给节点重编 id** (`n_calib_mani`→`n1791534…acq`) ⇒ 取节点必须
   「语义标记 `params.manifold_calib` + 名字关键词」兜底; 按 id 写判据的 verifier 必假红。
2. 🔴 **往方法里插代码块, `ast.parse` 抓不到插错位置**: 本次把懒刷新钩子插到**两个方法之间**
   (8 空格缩进紧贴上一个方法体尾, 语法合法) ⇒ 钩子挂到了上一个方法, 现象=不生效。
   定位法: 找 `    def X(self):` 后, 再找**下一个** `^    def ` 之前的一行插; 插完务必复核
   「新块行号落在 [defX, 下一个 def) 区间」(脚本里 `assert`)。
3. **刷新钩子别用 `isVisible()` 判据** (窗口隐藏/离屏恒 False ⇒ 静默跳过): 用「当前页索引 →
   `VIEW_KEYS[idx]` 名」判断。

### v5.24.1: 测量三行合一 + 新增「标定」页 (老倪「测量类三行太多只留一行 + 增加一个标定类」)
下拉 4 行: 🧮 主参数 M (默认) / 📏 测量 / 🎛 标定 / 🔧 配置·运行开关。
- **📏 测量 = `MeasureHub`**: 原 `tree`/`ss_tree`/`bus` 三个控件 `attach()` re-parent 进 3 个页签
  (又是「搬不是复制」: 外部读 `dock.tree` / `_show_state_space()` 一字不改); 切签只刷当前签。
- **🎛 标定 = `CalibTruthView`**: 逐行读真源 `config/calib/zmax_calib.json` (9 段同序同值), 未标定 3 项
  (`T_base_cam`/`plane_z`/`cell_geometry`) 高亮 + 给**可执行**现场标定命令 (`ss_geom_calib.py` 零运动示教 /
  `board_handeye_solve.py` 采板 / 夹爪量台面高度); **只读无写按钮** —— 唯一写口留给主参数 M 页。

### 坑 4 🔴: 仓库根路径少一层 `dirname` + 判据打在「测试自己调脚本」上 = 假证据
`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 在 `tools/gui/xxx.py` 里只到 `tools/`,
要**三层**才到仓根 ⇒ 拼出 `tools/tools/ss_node_sync.py`、`tools/config/calib/...`,
按钮静默走空路径。**更坑的是上一轮判据没抳到**: 测试自己 `subprocess` 跑脚本“通过”了,
而那只是脚本能跑, **按钮那条路根本没验**。
=> 铁律: 凡是面板按钮背后的路径 (子进程/写文件/调脚本), 判据必须**真点按钮 + 抳按钮自己的日志**
(`v._log = lambda m: logs.append(m)`, 再断言日志里有成功句), 不能直接调脚本冒充。

### v5.24.2 再收紧: 「测量」只挂数据总线 (老倪同日改主意)
面板里 `📏 测量` 行只挂 `bus`; 数据字典 `tree` / 状态空间变量 `ss_tree` **对象与刷新逻辑没动**(不删),
只是不 `addWidget` 进面板; `MeasureHub` 类保留停用 (`self.measure = None`), 一会话里就能复活。
**副作用要如实报**: 「双击节点参数直接标定/调节」入口随树一块从面板消失 (编辑器代码还在)。
→ 教训: 用户说「只保留 X」时, 把**同时失去的能力**(而不只是行数) 一并报出来, 别让人事后才发现。

### 面板 "没有用的都删掉" 怎么答才站得住
1. **逐个视图切换实测** (offscreen 真建窗口 + `setCurrentIndex` + `processEvents` + 读 `isVisible()`/标签/树/表行数),
   不要凭代码猜: 面板里很多视图是 `paintEvent` 自绘 (无 QLabel) 或"未跑仿真=诚实空态", 看着空其实有数据源。
2. 判"有没有用"的证据链 = **数据源 (文件/`module._ss_tr`) 是否真实 + 是否被消费**。全是活的时候,
   老实报"无空壳可删", 然后去删**全仓零引用的死函数** (`grep -rn '<name>'` 只有定义行) —— 这才是能落地的"删掉没用的"。
3. 遇到"接了但没人消费"的 (例: `工程需求` 8 个输入框写 `module._eng_req`, 全仓只有本面板自己读) ——
   **不要默默删**, 删了会丢需求基线; 在界面上**如实标注**"这些值暂只喂本面板验收口径, 引擎不读"。

## 工程文件: 保存/加载整个「状态空间工程」(2026-10-08 老倪: 文件菜单)
老倪: 「在控制台，文件下拉菜单，增加一个保存工程文件的功能，这样，我下次进入控制台，直接加载这个工程文件，就可以继续调试状态空间工程了。」
- 实现: `tools/gui/project_file.py`(逻辑, 可命令行自检) + `studio.py` 文件菜单两项
  (`💾 保存工程文件…` Ctrl+S · `📂 加载工程文件…` Ctrl+Shift+O)。
  **默认目录 = `data/database/`**(`project_dir()`; 2026-10-09 从 `reports/projects/` 迁来, 与工程库同目录), 扩展名 `.zmaxproj`;
  另有 v2「**总工程**」`data/database/zmax_space.proj`(七段: canvas/calibration/master_param/measure/tasks/panel/meta),
  对应控制台「文件 → 🗂 打开/保存总工程」—— 集成式回填(画布+标定+主参数+任务+面板), 见下方写盘铁律。
- 工程文件是**自包含** JSON 四段: `meta`(schema/时间/控制台版本/画布指纹 md5+统计) · `canvas`(画布真源全文) ·
  `run_cfg`(画布页 6 个运行档位勾选: chk_engine_demo/chk_l3_full/chk_mani_yaw/chk_intact_exec/chk_l4_dit/chk_l2_compat) ·
  `ui`(画布栈索引 —— 加载后自动切回画布页)。
- 🔴 加载 = **写画布真源**, 所以三道闸: ①先 `read_summary()` 把"这文件里是什么"摆给用户看, 他点确定才动;
  ②写盘只走 `flows.save_canvas()`(自带校验 + 备份到 `flows/_archive/`); ③坏文件(schema 不对/画布校验不过)拒载, 当前画布不动。
- 🔴 **「打开总工程」= 真写盘(集成式回填), 会把改动回滚**: 它按存档把 画布/标定/主参数/任务/面板 **写回现场**。
  改过画布后**必须先刷新快照 `python3 tools/project_archive.py space-save`**, 否则下一次打开(包括 `tools/probe_open_space.py` 这种离屏探针)
  就把你的改动**回滚**到存档那一份(实测: 改完画布跑一次打开探针, 改的注释被冲掉、库/绑定双双报漂移)。
  收尾跑 `probe_open_space.py` 验"打开后画布 md5 不变"= 幂等, 再交。
- 🔴 **改画布后的下游同步顺序 (不能换)**: ① 改画布 → ② `ss_node_sync.py`(节点配置段要同步时)
  → ③ `ss_task_bind.py --activate <task>` → ④ `project_archive.py space-save`(刷新总工程快照)
  → ⑤ `engineering_db.py build` → ⑥ `ss_task_bind.py --check` + `engineering_db.py check`(+ 工程库服务 restart)。
  为什么卡这个序: ⑤必须在④之后 —— 先 build 再 save, 库就比总工程旧, `check` 每次都报 `drift ['project']`(实测反复中招);
  ④必须在③之后 —— 快照里落的是任务绑定指纹, 早了存的是旧的。画布 md5 一变, `ss_task_bind --check` 就会报"需重绑定"。
- 保存前也要校验: 把有问题的画布存成"工程"比存不上更糟(下次加载会把它们写回来)。
- 命令行自检 `gui-venv311/bin/python tools/gui/project_file.py`; 端到端自检(存→读摘要→载→画布 md5 不变 +
  备份生成 + 软链未被替换 + 坏文件被拒)见 `/tmp/verify_project_feature.py`, 加 `--studio` 再验 studio.py 离屏 import。
- ⚠️ `QFileDialog` 在 `studio.py` 里是**函数内局部导入**(不在顶部 import 块) —— 新写的 handler 里要自己 `from PyQt5.QtWidgets import QFileDialog`。

## 画布全图 PDF 导出 + 一条命令发布 (2026-10-01 起, 用户要"手机随时下载最新版全图")
| 东西 | 位置 | 说明 |
|---|---|---|
| 渲图 (矢量, 不吃 GUI/截图) | `tools/canvas_pdf_export.py` | 读真源 JSON 直画: 封面/图例页 + 全图总览 1 页 + 分层详图 (3 行带组 × 自适应分列)。页脚**逐页**写"累计已画 节点 N/89 · 连线 M/182"自查 + 版本 + 生成时间 |
| 发布/路由逻辑 | `src/lerobot/engineering/canvas_publish.py` | 真源 realpath · 版本号 `v<YYYYMMDD 真源 mtime>-<md5:8>` · 产物目录 `reports/canvas_pdf/` · `serve_route()` (8796 只读路由) · ECS 推/回读 |
| 一条命令 | `tools/publish_canvas.py` | 渲图→算版本→推 8796→推 ECS; `--if-changed` 幂等; `--shots DIR` 出首屏/总览截图 |
| 手机固定 URL | `https://datadrive.world/canvas_latest.pdf` (+ 留档 `canvas_<version>.pdf`) | 走 `ss3d_push.php` (token + 文件名白名单, 已加 `canvas_*.pdf`) |
| 自动更新 | crontab `7 * * * * … publish_canvas.py --if-changed` | 真源 md5 或**渲染器指纹**变了才重渲重推 |

布局 / 自查要点 (都实测过, 别走回头路):
- **PDF 字体必须同时有 Latin + CJK**: `DroidSansFallbackFull.ttf` 只有 CJK ⇒ 版本号/机位/数字**整段消失**(截图里看着像"排版空了"), 用 `wqy-zenhei.ttc` (subfontIndex=0)。emoji 无字形 ⇒ 用 `sanitize_label()` 去掉, 否则黑框。
- **页数不是靠"好看的固定比例": 列/行切点必须落在空白里**。行带组切点 = 相邻行带之间空档中点 (选 2 个使 3 组节点数均衡); 列切点 = 节点 x 空档中点, 列数与边界用"列宽 + 节点数"代价函数选 ⇒ 自动避免"某页只有 1 个节点"的废页, 且**不切断任何节点**。写死坐标的下场是画布一改版就切穿节点。
- 连线走**正交折线**: 跨行带走两行带之间的走廊 (不穿节点行), 同带走带内下轨; 跨距 >8000px 弱化为细线+低透明度。画序: 行带底 → 连线 → 节点 (交叉被节点盖住)。
- 自查口径: 页脚写"累计已画"(总览页一画完就是满值) + 每页另算窗口内数量; 收尾断言 `drawn_nodes/drawn_links == 真值`, 不通过就 `exit 3`, 发布脚本据此拒绝上传。
- **发布后必须自己把产物拉回来验, 不采信子代理/发布脚本的自述**(它们报的 md5、状态码、页数可能只是自己想象的):
  `curl -sI <公网 URL>`(200 + `application/pdf` + 字节数) → `curl -s <URL> | md5sum` 与**本地产物 md5 逐位比** →
  再用**独立引擎**复算页数与页脚自查数(`pdfinfo` 看 Pages / `pdftotext … - | grep 页脚`), 不读导出器自己 print 的那行。
- **`--if-changed` 不能只看画布 md5**: 改了布局/字体的"渲染器改动"不会被重推 ⇒ 把导出器+发布模块源码 md5 也当指纹比 (本项目曾因此漏推)。
- 8796 是 stdlib `BaseHTTPRequestHandler`: 想让 `curl -I` 可用必须补 `do_HEAD`(= 转 `do_GET` 但**不写 body**); 否则 501。
- ECS 白名单只加不改: `$ALLOW` 保留原两条, 新增 `$ALLOW_GLOB=['canvas_*.pdf']` + `fnmatch`; 上线前 `cp .bak_<ts>`, 改完远端 `php -l`。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| PDF 用只含 CJK 的字体 | 数字/英文/版本号整段不见 | 换 `wqy-zenhei.ttc` 等 Latin+CJK 字体 |
| 只做语法校验就交付 | 语法过、控制台起不来 | 必须走 ②导入 ③渲染 ⑤运行 三层 |
| 把"节点数对了"当成功 | 节点 88→87 但**连线 167→0** | 渲染级数字双看: node items **与** link items |
| 端口字典格式 | 断言/渲染随机踩坑 | 统一归一为字符串列表 |
| 长命令内联被拦 | heredoc/巨型单行触发 hardline 拦截 | 写成 `/tmp/*.sh` 再 `bash` 执行（本环境惯例） |
| 想靠重排消除交叉 | 改完交叉更多 | 量化后再判; 跨行长线只能靠正交布线 |
| 对画布文件做 `tmp`+`os.replace` 原子写 | 仓库根 `flows/state_space_obs.json` **和** `src/lerobot/engineering/flows/state_space_obs.json` 都是**软链** ⇒ 被换成普通文件, 工程结构破坏 (`verify_platform_spec` ⑦ / `instance_init.py --check` 立刻变红) | 写前 `os.path.realpath()` 取真源路径再 replace; 备份放仓库根 `flows/_archive/` (既有约定) |
| 以为画布真源只有一份 | 改了一份、GUI 读的是另一份 ⇒ 改了看不见 | **真源 = `data/database/<产品>/sources/canvas/state_space_obs.json`**; `src/lerobot/engineering/flows/state_space_obs.json` 是指向它的**软链** (GUI 经仓库根 `flows/` 软链读同一份)。判据: `bash`→`realpath flows/state_space_obs.json` 必须落在实例包内 + `tools/instance_init.py --check` ①全绿 |
| 改完画布没重存总工程 | `verify_project_archive` 报「集成式打开后 diff: 总工程 == 现场」❌ | 改画布后按序: 画布 → `ss_node_sync.py`(需要时) → `ss_task_bind --activate` → **`project_archive.py space-save`** → `engineering_db.py build` → 两个 `--check` |
| 画布真源被 GUI 保存**悄悄回滚** | 改了真源, 过几分钟内容又变回旧的 (实测 mtime 变、`params.core` 消失) | 控制台退出/另存为会把内存里的画布写回真源 ⇒ **① 改完立刻回读 + 记 mtime; ② 尽量在控制台没加载该画布时改; ③ 交付前再回读一次**, 别只看第一次写成功 |
| 加节点后忘了同步 `_EXTERNAL_LOC` 行号 | `t_auto_srcmap`(L2/L4 在跑) 报「Lx无符号」 | 改真源后重算 `class X`/常量的行号并更新映射 (±3 行容错但别赌) |
| 以为改 `capability_levels.py` 会改变断言数 | 只在 `groups` 里报真实 `t_*` 前缀才影响计数; 加 `groups: []` 的功能条目 (如 L4-C16) 计数不变 | 加能力条目用空 groups; 别写错前缀 |
| 标定参数写盘顺手 `sync_calib(write=True)` | `calib.json` 其他域 (内参/几何/TCP) 被一起刷新成"当前源", 意外改变在役读值 | 只读写自己那一节 (读-改-写单键), 别整表重合并 |
| 忘了重启控制台 | 用户看到旧拓扑 | 改完必重启 + 确认 `Traceback=0` |
| 拿自报日志当副作用发生 | "页已打开"其实浏览器没起 | 查外部痕迹: 进程 lstart / 浏览器 History, 不信自报 |
| **用自己的临时脚本判"孤岛/断线"** | 连线字段名猜错 ⇒ 误报 `ss_seg` "入度=0 出度=0", 差点"为改而改"去接一条**本来就存在**的线 | 判拓扑只用**工程自带**手段: `canvas_node_audit.py`(孤立/断头/悬空) + `match_node(节点名)` + 渲染级 link items; 自写脚本必须先用一条**已知存在**的连线做正例自检 |
| 按钮反馈只写日志/节点小字 | 用户连报"点了没反应" | 反馈落在**他刚点的那个控件**(按钮文字)+ **节点边框状态色** + 下面终端日志(变化时才写); 画布上不铺字(见"长任务触发器") |
| 把状态文字铺在画布上(横幅/节点进度行) | 用户嫌丑: 「这几个字太丑了…赶紧删掉」 | 文本只进下面终端(内容变化才写一行); 画布留边框状态色即可 |
| 用"它其实在跑"回答"没反应" | 用户继续报没反应 | 先把功能启动做成看得见, 再解释; 见"长任务触发器"节 |
| 以为节点能显示画面 | 赋了 pixmap 也没画面 | 先 grep 该字段写点; 死代码分支要自己接定时器 + update() |
| 新节点只有名字没关键字 | 双击无反应(落兜底) | 在 `node_logic.NODE_LOGIC` 补关键字 + 真双击一次 |
| 用 `stage_detail.pid` 判后台任务在不在跑 | 阶段切换间隙误判成"没在跑" ⇒ 徽章停更 / 重复启动 | 判活看**编排自身 pid**(状态文件顶层 `pid`) + state 文件 mtime 新鲜度兜底 |
| 只把状态写在画布节点小字 | 用户连报三轮"没反应" | 状态写到下面终端(变化才写)+ 按钮文字 + 边框色(见"长任务触发器"), 并把"需重启才生效"说在前面 |
| 横幅每次轮询重铺 | 状态停在 failed ⇒ 提示永久顶在画布上, 用户要求"怎么关不掉" | error 只闪 ~15s 自隐 + 新一轮启动时清标记; 历史终态文案写"上次…"; 别在终态 `timer.stop()` |
| 点击瞬间设的反馈被同函数后续分支回写 | 按钮文字永远不变(用户照旧报没反应) | 按钮文字交给轮询驱动, 或设完后 grep 本函数内该控件的所有写点 |
| 气泡/浮层用场景坐标当屏幕坐标 | 气泡飘到窗口外、被盖住 | `mapToGlobal(mapFromScene(...))`; 内容用真实状态, 不写死"已启动" |
| 进度写死分母 (n/7) | 实际 9 阶段 ⇒ 一开跑就显示 9/9, 像已跑完 | 分母从状态文件读 |
| 手工拼命令重启控制台 | GUI 起不来 / 窗口不出现（缺 `XAUTHORITY`/`XDG_RUNTIME_DIR`/DBUS） | 用仓库启动器 `tools/gui/launch_studio.sh`（自带环境 + 防重复实例）；或从旧进程复用环境：`cat /proc/<pid>/cmdline` + `tr '\0' '\n' < /proc/<pid>/environ \| grep -E '^(DISPLAY\|XAUTHORITY\|XDG_RUNTIME_DIR)='` 后再启 |
| 子代理起的控制台随它退出而死 | 交付验收时 GUI 是死的（用户那边"打不开"） | 常驻进程必须**脱离**启动（`setsid nohup … </dev/null &`，或 terminal `background=true, persist_on_release=true`）；父会话在子代理交付后**重验进程还在**，不在就自己重起 |
| 用 `pgrep -f "tools/gui/studio.py"` 判活 | 会命中**自己的 shell 命令行**（命令串里就含这个模式）⇒ 假"在跑" | 用脚本自带的精确模式 `pgrep -f "gui-venv311/bin/python studio.py"`，或 `ps -eo pid,cmd \| grep "[s]tudio.py"` |
| 用 `pkill -f <模式>` 杀进程（内联在命令里） | **连自己的 shell 一起杀**：模式匹配到当前命令行 ⇒ 命令输出戛然而止、后续步骤全没跑（比误判"在跑"更狠，本次实测把自己 shell 杀了，两条 `set -e` 脚本都断在半路） | 杀进程用 `pgrep -x <精确进程名> \| xargs -r sudo kill`（`-x` 只匹配进程名），或整段写成 `/tmp/*.sh` 再 `bash` 执行，别内联 `pkill -f` |

## 工具栏按钮「建了没挂」类 bug (2026-10-10 老倪: 3D 视图按钮哪里去了)
- 症状: 用户说按钮不见了; 代码里 `self.btn_xxx = mk_btn(...)` 明明在, 且 clicked 也接好了。
- 真因: 按钮对象建了但 **`tl.addWidget(self.btn_xxx)` 被删**(工具栏精简/重构时只删了 addWidget 行)
  ⇒ 对象在、信号在、**永远不会显示**。
- 判据必须双重: ① 对象在 ② `.text()` 对 ③ **`isVisibleTo(m)` 真挂进布局**(删 addWidget 只有第③条能抓到)。
  `tools/probe_canvas_menu.py` 的工具栏循环就是这条判据 — 新按钮一律加进去。
- 入口丢失要先查 addWidget 所在层: `grep -n "addWidget(self.btn_" tools/gui/simulink_module.py`。
- 恢复习惯: 工具条常驻 + 「画布(C)」菜单双入口(菜单项 `triggered` 接到**同一按钮**的 click,
  不要把常驻按钮 `setattr` 成 QAction — `attach_canvas_actions` 里 6 个替身项是那个用法, 新按钮不是)。

## 两个 Python 级陷阱 (都在 simulink_module.py 真踩过, 2026-10-10)
1. **函数内某分支 `import sys` ⇒ `sys` 变局部名** ⇒ 同函数别处的 `sys.path` 抛
   `UnboundLocalError: cannot access local variable 'sys'`。open_ss_3d 里就是这句 —— 后果是
   `attach_scene_edit` 从来没执行, 被 `except Exception: print(...)` 吞成一行日志 ⇒ 界面看起来正常,
   功能其实没接上。**规矩**: 同函数内要用就用 `import sys as _sys`; 更狠的是这类 except 只 print ⇒
   判据必须**断言功能真挂上**(如 `getattr(win, "_scene_edit_attacher", None) is not None`), 不信日志。
2. **`QPushButton.clicked` 会把 `checked=False` 当第一个位置参数** ⇒ `btn.clicked.connect(fn)` 里
   若 `fn(level=None)` 就变成 `level=False` (静默错误参数)。一律 `lambda: fn()` 包一层。

## 打开工程即居中 + 核心节点色 (v5.37.1)
老倪: 「每次打开状态空间工程, 屏幕中心就是这个节点; 改变这个节点的背景颜色, 让人一下子就认出流形引擎是系统的核心」。
- **配色 (已定稿)**: 核心 = 全画布**唯一暖色**「琥珀金 #FFC53D」—— 双层光晕 (`255,197,61` α17/38) + 金渐变体 (`#6B4A00`→`#2A1C00`) + 3px 金框 + 右上「◉ 核心」金底徽章。
  其余节点一律冷色 (蓝灰/青/紫/绿) ⇒ 暖色即核心。**不要用金/橙做别的节点**, 否则标识失效。
- **判据数据驱动**: `SimNodeItem.paint` 里 `is_core = params.core or params.manifold_engine or type/id=='ss_mani_eng'`。
  ⚠️ 必须带 `params.manifold_engine` 兜底 —— `load_flow_file` 会**重编 id**, `type` 是 `model`, 只认 id/core 会在 GUI 里失效。
- **打开工程即居中**: `load_flow_file` 成功后 `QTimer.singleShot(0/450, self.center_on_core_node)` (两次, 防被后续 fit 覆盖) +
  工具栏「🧮 核心居中」开关 (默认勾选) + `Ctrl+Shift+C` 手动居中 + `showEvent` 兜底 (**只在 `canvas.viewport().width()>200` 即真布局时才算数**, 否则 centerOn 算到错位置)。
  `core_node_id()` 找不到核心要**如实报缺**, 不假装居中过。
- **取证 (无视觉工具时的口径)**: `tools/tests/test_core_node_ui.py` 真渲染成 QImage 数**暖色/纯金像素** (核心 975 采样值 vs 普通 0) +
  真 `SimulinkModule` 加载真工程后量「视口中心 vs 核心中心」偏差 (实测 dx=dy=1.0); 已并入 `run_gui_verifiers.sh` (core_node_ui)。
  活体复核: `DISPLAY=:0 scrot -o /tmp/x.png` + 像素统计 (画布不在前台时数不到暖色, 不要误判成"没生效")。

## 验证清单
```bash
# 架构自检 (迁移后新增, 6 项: 逻辑在包里/JSON 真源/档位契约/GUI 壳一致/档位索引)
./gui-venv311/bin/python tools/verify_engineering.py
./gui-venv311/bin/python tools/gen_by_level_index.py       # 重生成档位索引 by_level.py
./gui-venv311/bin/python tools/verify_canvas_render.py     # 渲染: node items / link items
./gui-venv311/bin/python tools/canvas_level_audit.py       # 档位级真接 / 无执行注册 / 真缺口
./gui-venv311/bin/python tools/rewire_cross_check.py       # 交叉前/后 + 每条线贡献
./gui-venv311/bin/python tools/canvas_cleanup.py           # 删节点(带安全判据, --apply 才写盘)
pgrep -f "gui-venv311/bin/python studio.py"                # 控制台在跑; 并确认 Traceback=0
```
参考实证: `docs/TASK_LEDGER_20260925.md`（会话七/十一/二十一: 连线失踪、清理、执行链重连）。
L5「能力档位 → 点运行 → 自动标注 → 自动训练 → 重启自动加载」这条链的机制、状态文件字段、
反假训练三道闸门与槽位标注工具: `references/l5-annotate-train-loop.md`。
画布上「配置/标定/诊断」接口节点(参数注册表 → 描述文件 → 面板/远程/诊断)的设计约定与 ASAM-MCD 类比:
`references/mcd-param-node-design.md`(完整方案: 仓库 `docs/design/manifold_mcd_master_param_M_20261009.md`)。
