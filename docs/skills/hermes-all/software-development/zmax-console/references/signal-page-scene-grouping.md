# 信号分析页(实时监控·Graphic 信号分析) 场景分色/目录树/波形 — 踩过的坑

唯一依据: `tools/gui/canoe_graphic.py`(页面类) + `tools/sig_scene_tags.py`(场景打标) + `config/topics/scene_tags.json`(标签+overrides)。
判据: `tools/verify_scene_signal_green.py`(离屏真建同一类, 逐行走树取 层级/文本/前景色/勾选态/可勾选/组展开)。

## 铁律

1. **同一批信号键在两处出现时, 勾选状态会串台。** 目录树里 `self.selected` 按 **key** 记账, 而行是
   按 (区域, key) 铺的。非当前场景那一份若在建树时被 `setCheckState(Unchecked)` 强制取消(为了不让它
   跟着打勾), 这个 Unchecked 会走 `itemChanged` ⇒ **把同名 key 从 self.selected 摘掉** ⇒ 连当前场景的
   曲线也一起消失 ⇒ 主窗口空白“没有波形”。
   · 修法: `_on_item_changed` 开头 `if not (item.flags() & Qt.ItemIsUserCheckable): return`;
     非当前场景的行 `_make_item(..., interactive=False)` 去掉 `ItemIsUserCheckable` + 强制 Unchecked + 灰显。
   · 判据里必须同时查两件事: 当前场景区“可勾选且带勾”, 非当前场景区“不可勾选且不带勾”。

2. **波形有没有, 先看数据源是不是只有 1 个样本。** `sstrace.*` 的唯一发布者是 3D 面板
   (`ss_dreamview.publish_trace_live`): 3D 不播放 ⇒ `zmax_data/ss_live/trace_live.json` 不刷新 ⇒
   每键 1 个样本 + 帧龄几千秒 ⇒ 单点/平线, 看着就是“没有波形”。
   · 修法: `tools/ss_fw_trace_pub.py` + `tools/systemd/zmax-ss-trace-pub.service` —— 把**常驻引擎回路**
     每周期真值(φ/梯度/耗时/置信/内稳态/潜表示/动作调制)搬成 `zmax_data/ss_live/engine_trace.json`
     (schema 同 trace_live: `ts` + `时间_s` ⇒ 页面按场景时刻铺点), 与 3D 是否播放无关。
   · 只搬运不造数 + 发布前校验 `task_id` 前缀(如 TASK-01-FW*)⇒ 场景标签不会说谎。
   · 首屏默认曲线(DEFAULT_3D)要挑**每周期都在动**的量(如 循环耗时_ms/内稳态紧迫度), 否则一屏平线。

3. **场景归属: 前缀族 > 逐信号注册表。** `sig_scene_tags.tag()` 里通用名(帧/总帧/时间_s)会被注册表里
   早先某次运行记下的标签抢走(典型: 摆盘) ⇒ 蓝区冒出插拔的数。新来源族要**在最前面**判定:
   `if k.startswith("新前缀."): return "插拔场景"`, 并在 `_source_scenes()` 里同时登记(否则 --build 会再写错)。

4. **重名信号口径(老倪定的)**: 多场景共写的源, **每个场景区域各自重新加载一份**, 行色=所在区域场景色;
   非当前场景的组**默认折叠隐藏**(用户手动展开过的记在 `_expanded` 里, 别顶掉), 当前场景组自动展开;
   建树/切排序后 `scrollToItem(组, PositionAtTop)` ⇒ 重启后一眼看到当前场景(否则树长, 落点像“信号不在”)。
   当前场景判定: 排序选中优先, 否则 `ss_scene_switch.now()['src_state']`(实测返回 “插拔场景”这种中文场景名)。

5. **页面的 JSON 源解析有 48 键上限**(`flatten_json(..., 48)`, AR 曾因此只进 48 条)。新写一帧流别超;
   数值以外的东西(字符串)不进目录; 元数据键(ts/t/age/meta/groups/schema)要排除。

## 新建「本机文件源」= 五处登记 (少一处就静默少信号)

以「万有引力表力信号」(`gravity.*`, 94 条 = 8 项×L2/L3/L4/L5×(力大小·实部) + 行/列/总合力 + 标量) 为例:
1. `canoe_graphic.HOST_SOURCES` 加 `("前缀", "zmax_data/ss_live/xxx.json")`;
2. `HostJsonSource.run` 里 —— **源条数可能 >48 就必须加「直取 s 键」分支**
   (`if prefix == "xxx" and isinstance(raw.get("s"), dict): vals = {...raw["s"]...}`),
   否则 `flatten_json(..., 48)` 静默截断: 实测 94 条只进 48 条, 页面看着像"一半的项没有信号"。
   元数据 (ts/时间_s/运行/task_id/阶段) 放 `s` 之外 ⇒ 天然不进目录。
3. `CanoeGraphicWidget.OUT_NODE_RULES` 加 `("前缀.", "输出节点名")` (否则"输出节点"列空);
4. `CanoeGraphicWidget.DEFAULT_3D` 加 1~2 条每拍真在动的键 (首屏就有曲线);
5. `sig_scene_tags.tag()` **最前面**加前缀直判 (`if k.startswith("xxx."): return "插拔场景"`) +
   `_source_scenes()` 同步登记; **发布器侧只认 `task_id=TASK-01-FW*` 才发** ⇒ 场景标签不说谎。

判据要卡三件事 (只卡"有信号"会漏 48 截断): 源文件条数 == store 条数 == 目标场景组下命中行数,
且当前场景行**可勾选**。定式脚本 `tools/verify_gravity_signals.py` (9 条)。
⚠️ `HOST_SOURCES`/源分支/OUT_NODE_RULES 都是**进程启动时读的** ⇒ 改完必须重启控制台,
重启前先跑离屏判据 (真建同一个 `CanoeGraphicWidget` 类)。
⚠️ 行匹配别只按文本: 目录里显示的是**去前缀短名**, 标量行 (一致度/主力层号/参考速度) 不含
"力大小/实部" 这类词 ⇒ 判据要拿 `item.data(0, Qt.UserRole)` 的键归一后比 (实测按文本匹配少 4 行)。

## 引擎"在跑"≠"学习在跑": 8799 渲染帧服务是 VLM 编码的前置

实测 (2026-10-16): `zmax-fw-render.service` (8799, RealStateSpaceSim 渲染插拔场景 → `/frame.png`) 不在跑 ⇒
引擎回路 `z_source` 写「成功 0 / 失败 254: URLError Connection refused」⇒ 潜表示**静默回退内建 PCA**;
同时 `_run_pipeline` 的 `_pick_frame()` 拿不到帧就 `return {}` (**不计数**) ⇒ `pipe_calls` 恒 0、
`layer_calls.jsonl` 停更。表面看服务全 active、Φ/∇Φ/M 都在动, 实际"学习"整条空转。

核查三步 (任何"力/潜表示是不是真算的"都先过这三条):
`curl -s 127.0.0.1:8799/status.json` (要 age_s<1 且 std>10 的非黑帧) ·
`engine_latest.z_source` 含「L4 潜空间…成功 N」· `pipe_calls` 在涨且 `layer_calls.jsonl` mtime 新鲜。
`systemctl start zmax-fw-render` 后实测: 编码成功 59、帧龄 0.3s、pipe_calls 0→44,
L5(planner.rules)/MEM(memory.json)/L2(detect.yolo)/L4(vote unified+intact)/L3 全 ok。

## 新话题接入 = 五处登记 (少一处静默收不到)

`dds/ss_types.py`(类型) · `dds/zmax_node.py`(`_SS_TOPICS` + qos) · `src/lerobot/dataspace/topics.py`(`TOPICS` + `MODE_TOPICS`) ·
`tools/gui/zmax_telemetry.py::MODE_TOPICS` · `tools/dds/ss_daemon.py`(`MODE_TOPICS` + `pub_xxx` + 挂线程), 然后**两端都重启**。
细节/遇到问题/digest 400 字上限/`or -1.0` 呑 0.0 见 `references/new-topic-into-signal-page.md`。

## 现场验收话术(老倪看画面, 不看代码)

- 先 `wmctrl -a '实时监控'` 把窗口抬到最前(3D 窗口会盖住波形区, 截图会拍到 3D 的界面 ⇒ 假“没波形”)。
- 证据用两帧差: `scrot -o -u` 隔 5~6 秒各一张, 裁波形区算变化像素(实测 39547 px / 3.84% ⇒ 实时在动),
  比“找曲线颜色像素”可靠(曲线颜色可能被抗锯齿/主题改掉)。
- 状态栏能自证: `本机: 采集中 · 信号 N 点` + 图例列出各曲线当前值。
6. **“只有某一条在动”先查输入是不是冻结的。** 实测症状: 10Hz 回路里只有 `循环耗时_ms`(CPU 抖动)有波形,
   潜表示/φ/梯度/置信 全是直线。根因不是图表: `RealStateSpaceSim.run()` 每次进来都 `_reset(seed)` ⇒
   渲染帧服务每 tick 调 `run(1)` 拿到的**永远是第 0/1 步的同一张图**(连取 4 帧 md5 全同)。
   · 排查手法(30 秒定案): 连取 4~5 帧比对 md5 / `mean,std`, 计数在涨但图不变 = 源没推进;
     再逐个比对源里各字段的(范围, 变化次数)。
   · 修法: 给 run() 加 `resume=True`(跳过 `_reset`, 内部复用 `self.env` ⇒ 不影响原语义), 渲染服务每 tick
     `run(max_steps=4, resume=True)`, 走完/异常才重开一轮; status.json 带 `episode_step` 供核。
   · 改后实测: φ 0.2325→0.3463(32.9%) · 梯度 18.1% · 置信 26.3% · 潜表示 p0..p3 全在动。
   · 判据要卡下限: “非平线曲线 ≥3 条”·否则冻结的链路也能“通过”。
7. **“耗时应该单调递增吧?” —— 先分清是耗时还是计数。** `循环耗时_ms` 是**每周期计算耗时**(0.6~1.7ms, 抖动),
   不是累计计时; 单调递增的是横轴(`时间_s`)和计数(`控制周期/帧`)。回答要把这个口径直接说清, 并把两条都用实测数说。

8. **主窗口“没信号”先查窗口日志里的 RecursionError。** 实测: 日志 5430 次
   `RecursionError: max recursion depth exceeded` (AxisItem.linkedViewChanged → setRange →
   updateAutoSIPrefix → _updateLabel → _adjustSize → _updateHeight …) ⇒ 布局/绘制整块失败,
   连时间轴线都画不出来。扣发条件: “每信号独立图”档下 N 张子图各挂一条自定义 ClockAxis 且
   `p.setXLink(main)` 互相链接, refresh() 又对**每张**子图 `setXRange` ⇒ 范围变化在 N 条轴之间来回通知。
   · 修: ① `ax.enableAutoSIPrefix(False)` ② 只让最下面那张子图 `setStyle(showValues=True)` (整列共用一条
     时间轴, CANoe 观感) ③ X 范围**只设一次**(设主图, 链接自己传), Y 只在各自 ViewBox 内设并 try/except。
   · 验证: 重启后看新日志的 RecursionError 计数(应为 0) + `scrot -o -u` 数曲线色像素
     (改前任何曲线色 0 px ⇒ 改后 #81C784 1073px / #BA68C8 1740px / 标记线 #ffb86c 1260px)。
9. **“与场景同步的时间轴线” 的两个口径不能混**: 竖向标记线跟的是 **3D 播放游标**
   (`pb.t_s`, 老倪定的: 两边必须是同一时刻), 不是“最新样本时刻”; 横轴标签是「场景时刻 (s)」,
   按 `epoch_base = ts - 时间_s` 反算绝对时刻 (按钮「🕒 时间轴」切绝对)。判据要这么卡,
   否则会把正确行为误判失败。
10. **首屏默认曲线要“增量补勾”, 不能一次置位。** 各源文件是 `HostJsonSource` 一轮读一个陆续到齐的 ⇒
   在第一次建树就 `_default_done=True` 会只勾上当时存在的那几条(实测日志“已勾 3 条”, 全是单样本 ⇒ 空白图)。
   口径: 每次建树把“库里已有且从没被自动勾过”的默认信号补齐 (记在 `self._auto_checked`),
   每条只自动勾一次(用户手动取消的不顶回来)。

11. **信号表列 = 信号名称 / 当前值 / 输出节点 / 来源话题** (老倪 2026-10-15 把「帧龄」列换成「输出节点」,
   “要能看到这个信号是哪个节点输出的”)。帧龄/Min/Max 全进 tooltip(信息不丢), 列宽 226。
   节点名必须**有出处**: 画布节点名 = 唯一依据 `flows/state_space_obs.json` 的 node.name;
   `sseng.*` = 常驻引擎回路(流形引擎/VLM编码节点/动作调制器); `sstrace.*` = 3D 面板发布的画布场景快照
   (具体信号按 前馈/动作调制/安全边界/接触概率/末端=真机TCP/光模块=YOLO→2D→3D 分), 其余来源族同理。
   没凭据就写最保守的(画布数据源 / 本机真值流), 别编节点名。
12. **子图自上而下的顺序 = 目录树自上而下的顺序**(不是点击顺序也不是到达顺序)。
   实现: `_ordered_selected()` 走一遍树取“已勾行的 key 序”, 在 `_on_item_changed`/`_apply_default_selection`/
   `_fill_tree` 收尾都重排 `self.selected` (`self.curves` 顺序 = 子图顺序 = 配色顺序)。
   判据直接卡 `wave.curves == 树上已勾行序`, 不要卡“某个信号必须第一”。

13. **动作调制_mps 只是模长, 不是动作** (老倪 2026-10-15「要变成 action, 至少有 x y z a b c, 怎么就一个 mps?」)。
   唯一依据: `state_space_sim_real.py` 的 `u_fuse_vec/u_limit_vec`, `u_prev = np.zeros(4)` ⇒ 动作是
   **4 维** `[vx, vy, vz (m/s), 夹爪 0/1]`; 模长 = `‖u[:3]‖`。姿态 (rx/ry/rz) 不走这条出口。
   面板/发布器都要把 x/y/z/夹爪 分开发, 只发模长就是丢信息。
14. **八阶段状态机 = `src/lerobot/policies/left_right/state_space/cognition.py:31 ActionModulator`**
   STAGES 13 段(接近/对位/下降/抓取/抬起/转移/插入/拔出/AOI转移/AOI检测/回程/放下/完成),
   插拔八阶段 = 前 7 段 + 完成; `STAGE_V_CAP` = 每阶段限速(m/s) —— 调制器限速的唯一依据。
   阶段名原本是**字符串**, 信号页只收数值 ⇒ 波形里看不到; 要看得把 阶段序号/八阶段序号/阶段限速_mps
   发成数值通道。取常量直接从类里 import (`_stage_maps()`), **不要另抄一份**。

15. **sstrace.* 停了 = 3D 面板播完就 `_pause()`** (老倪「末端 x y z 怎么没有信号输出?」)。
   快照 trace_live.json 不更新 ⇒ 每键只剩 1 个样本 ⇒ 画不出线。修: `ss_dreamview._tick`
   末尾停 3s 后从第 0 帧重播 + `_hb_check` 心跳看门狗 (窗口开着/用户没按⏸/快照 5s 未更新 ⇒ 接管);
   `_pause(user=...)` 区分“外部驱动暂停”与“用户手动暂停”。`ZMAX_SS_LOOP=0` 关。
16. **八个状态上真话题 `zmax/ss_stage`** (zmax::SSStage): 改 4 处才能全链通 —— `dds/ss_types.py`
   加类型 · `dds/zmax_node.py` 注册话题+QOS(beat) · `src/lerobot/dataspace/topics.py` +
   `tools/gui/zmax_telemetry.py` 登记话题/档位 · `tools/dds/ss_daemon.py` 读数并发布。
   窗口里看到它走的是“话题 → 探针 trace.jsonl → ds.<话题名>.<字段>”这条道 (ds 源)。
   `ss_state.stage` 是**真机 tap 的 prod_stage**, 别把仿真阶段灌进去 (混源会在现场核对时遇到问题)。
17. **pyqtgraph 递归爆栈要“全轴”断链**: 只关时间轴的 autoSIPrefix 不够 —— 主图每根轴
   (left/right/bottom/top) + 每个副轴都要 `enableAutoSIPrefix(False)`，副轴再
   `setStyle(autoExpandTextSpace=False, tickTextWidth=72)` (宽度不随数值长短变)，
   `_sync_vb_geometry` 加重入闸(setGeometry ⇒ sigResized ⇒ 又调回来)。

18. **“话题在列表里、波形里没有” = 数据空间 digest 被截断** (老倪「没看到 topic 在信号分析里啊」)。
   probe.py 对没专门摘要的话题走 `body[:180]` 保障 ⇒ 残缺 JSON ⇒ `parse_ds_digest` 的 json.loads
   失败、人读正则也抠不到 ⇒ 该话题 0 条信号。修法两处: ① probe 的 `_digest_for` 给该话题一行
   **完整紧凑 JSON**(只留要画的叶子, 同 ss_torque 做法) ② `parse_ds_digest` 加“被切掉的 JSON”
   分支: 逐对抠 `"键": 数值`。**判据要直接调页面的 parse_ds_digest**, 不能只看话题列表。

19. **“信号里有、但看不到状态” ⇒ 状态名是字符串, 永远上不了波形** (老倪「也没有显示状态啊」)。
   数值通道只给 idx/idx8/v_cap; 阶段名要单独**写状态栏**。要点: 写在状态行**最前面** (末尾会被
   窗口宽截掉); 快照停更时整行转橙 + “⚠ 停更 Ns”, 不拿旧阶段冒充现在。
20. **控制台里内嵌了同一个 CanoeGraphicWidget** (studio.py `from canoe_graphic import`)。
   所以信号页的递归爆栈会**连带把 3D 面板定时器堵死** (pyqtgraph AxisItem.setRange→updateAutoSIPrefix
   / ViewBox.linkedXChanged→screenGeometry): 现象是“3D 面板不跑、快照停更、状态不动”, 排查时
   别只看独立信号窗口的日志 —— 必须重启控制台才能带新代码 (判据: 40s 内新增 RecursionError == 0)。

21. **“信号全变白 / 没颜色”两个真因** (老倪 2026-10-15)。
   ① 波形区: `_build_items` 里 `setLabel(left, name, color=b.color)` 下一行又被
      `setTextPen(C_DIM)` 覆盖 ⇒ 每信号独立图的信号名全灰白。统一用 `_kcolor(key)`:
      场景色(插拔绿#2e8b57/摆盘蓝#1f6feb/AR紫#8957e5) > 角色色(位姿青#39c5cf/安全黄#d29922/
      话题灰蓝#8ab4f8) > 调色板色; 标签笔+曲线笔都走它。
   ② 信号目录: 非当前场景那份重名行**不要 setForeground(C_DIM)** (整组摆盘 48 行会灰成一片),
      保留本场景色 + alpha≈165 淡显; “非当前场景”用不可勾选+tooltip 表达。
22. **八阶段要“文字”不只序号**: 3D 面板随快照下发 `八阶段表`(唯一依据 ActionModulator.STAGES 插拔
   八段), 信号页状态行下再铺一行「🎛 八阶段: 接近 › 对位 › 【下降】 › …」当前段粗体绿+【】。
   长富文本 QLabel 会把窗口 minimumSizeHint 顶到 3068x1936 ⇒ 必须 `setSizePolicy(Ignored, …)`。
23. **首屏“一条曲线都没有”的真因**: 自动补勾在 `tree.blockSignals(True)` 里做 ⇒ setCheckState 不触发
   `_on_item_changed` ⇒ `self.selected` 恒空。**离屏跑不复现** (键来得晚反而正常)。修: 建树时直接
   append 进 selected。排查类问题必须在**真窗口日志**里读“已选共 N 条”。
24. **状态/波形“不动”先查 GPU**: 控制台日志 `CUDA error: out of memory` (陈旧 INTACT/gui 进程各占
   420MB~2GB 把 8GB 卡吃满) ⇒ 3D 面板定时器停 ⇒ 快照停更。`nvidia-smi --query-compute-apps`
   按 etime 清陈旧进程, 再重启控制台。

25. **“时间轴不同步 / 各跑各的”真因**: 两个快照的 `时间_s` **不是同一根钟** —— trace_live.json = 3D
   回放进度(重播归零), engine_trace.json = 引擎开机时长(实测差 9650s) ⇒ 同屏两条曲线相差 2.7h。
   唯一同源的是 `ts`(墙钟) ⇒ **一律用 ts 当横轴**(epoch 偏移 0), 游标也画在快照那一刻的 ts 上。
   判据要跟者改 (老口径按 t_s 校标记线会误报)。
26. **共写源 sstrace.* 的曲线色 = 当前场景色** (老倪「接触概率 末端 这几个蓝色的, 怎么也显示呢?
   应该只是绿色的信号」)。坑: wave 控件**没有** `_active_scene()` (那是主控件的方法), 在它里
   直接调会被 except 吞掉 ⇒ 又回落成标签色(摆盘蓝)。修: 主控件每轮把 `scene_now` 同步给 wave。
27. **X 轴名只写最底下一张** (老倪「很多 场景时刻(s), 每个信号都有…不要占地方」): 每信号独立图模式
   不要每张子图都 setLabel(bottom) —— 建图时只给最后一张，其余置空; 同时 `_update_markers` 里的
   轴名刷新循环也必须同样“只最后一张”(否则每 tick 又给全部写回)。

26. **横轴主钟只能是“ 3D 回放进度(场景时刻秒)”**, 不能改成墙钟 ts: 改成 ts ⇒ 刻度/píng光显示 1.79e+09
   且与 3D 进度条脱钩(老倪: “拖进度条时间轴怎么不跟着动? 还显示 1.79e+09”). 其它源用
   “快照那一刻的 (ts, t_s) 对应关系”把 ts 映射到回放钟 ⇒ 同一根钟 + 跟着进度条走. 绝对时刻另设开关
   (epoch = ts − t_s).
27. **单位口径: 速度一律 mm/s 毫米/秒, 禁 mps/m/s** (老倪: “mps 是欧洲用的, 我们是中国”). 键名里 `_mps`
   是数据契约**不改**, 只改显示: 显示名 `xxx_mps` → `xxx (mm/s)`, 值 ×1000 —— 目录当前值/左轴名/图例/
   光标 A·B/状态栏/CSV/3D HUD 全部要改, 否则“0.085 mm/s”就是假数。
28. **`glw.clear()` 之后紧接的代码不能再碰旧标记线/光标**: clear() 销毁了它们的 C++ 实例, Python 还攥着
   旧引用 ⇒ `mk.setPos()` 抛 “wrapped C/C++ object … has been deleted”, 而且**抛在 _build_items 里就把建图打断,
   界面一条波形都没有**(判据⑥ 会报 “曲线对象 0 个”). 定式: clear() 后立即 `self.marks,pins=[],[]; c1=c2=None`,
   重建处 setPos 兜 RuntimeError。
29. **@staticmethod 在同类方法里必须 `self._klab(k)` 调用**: 裸调 `_klab(k)` 会被当成全局名 ⇒ NameError
   ⇒ 被外层 except 吞掉 ⇒ 建图中断、一条曲线都出不来(排查时最容易看不见)。
30. **“每拍都改轴属性”会打爆事件循环 (递归爆栈 22.8 万次)**: 每拍判 `labelText`/写 `epoch_base +
   picture=None` 会让 `AxisItem._updateLabel ↔ ViewBox.linkedViewChanged/screenGeometry` 相互触发;
   轴名在 4 处各写一份口径不一致时 ⇒ 每拍都“文本不等 ⇒ 再 setLabel” ⇒ 永不收敛. 症状=控制台刷
   RecursionError → 事件循环堵死 → **3D 面板 QTimer 停跑 → 快照/话题停更** (看着像信号页死了).
   定式: 轴名收敛成**唯一口径 helper** (4 处共用) + 每拍重入闸 + 相对秒模式**不碰 epoch**。
31. **元任务预测 = 话题 `zmax/ss_meta_pred` (不是 ss_meta_task)**: ss_meta_task = 元任务**清单**派生;
   ss_meta_pred = 预测**得分** + top-k (输入=驱动扭矩). 长串字段 (top_ids/top_scores) 会让 `body[:180]`
   保障把数值叶子全挤掉 ⇒ 探针要给它**完整紧凑 JSON 摘要** (数值在前、名字在后). 现值 frozen=1 (驱动扭矩
   恒定 ⇒ 无区分度) → 必须如实标, 不许写成“有预测力”。
32. **画布接线先 grep 再动手**: 老倪说“X 要连到 Y”时, 先 `grep 两侧节点的出/入线` 列全 ——
   `ssff(out2) → sssched(in6)` 这条线**本来就存在**, 真正的问题是节点 outputs 只声明 out1 而线用 out2
   (端口表与线不一致) + 标签太笼统. 先定“加线”还是“写实已有线”, 直接加会撞重复被拦。
33. **INTACT worker 泄露 = 反复 CUDA OOM 的真因**: engine loop 每建一个 IntactRuntime 就 spawn 一个
   intact_worker (420 MiB) 且旧的不 close ⇒ 实测 5 分钟一个, 7 个吃满 8188 MiB ⇒ 面板/信号页停更.
   应急: `tools/janitor_intact_workers.sh` (只留最新, 幂等) + crontab */5; 真修 = Runtime 走单例
   (`src/lerobot/policies/intact/runtime/model_adapter.py`)。
34. **新话题上线信号页的三件套** (缺一条就是“看得到话题、没波形”): ① 探针 `probe.py::_digest_for` 补
   完整紧凑 JSON 摘要; ② `canoe_graphic.OUT_NODE_RULES` 加“话题→输出节点” (否则“输出节点”列只剩干数据源);
   ③ `DEFAULT_3D` 加 1~2 个代表性键 (top1/spread 类); 再加判据 (话题在发 + digest 可解析 + 页面已建键)。
35. **Fit/适配按钮必须“当拍”生效, 且 X 在“每信号独立图”模式也要拉**: 原 `_fit` 只在
   `main_plot is not None` 时设 X —— 而该模式 `main_plot = None`(指向被 clear() 删掉的图) ⇒ 点 Fit 只有 Y 变,
   X 停在旧窄窗 ⇒ 看着“很多信号没显示”. 定式: X = 已勾选已画信号的并集 ∪ 3D 游标那一刻(游标不许被挤出画面),
   对**每一张子图**都设, 设完 `layout.invalidate() + refresh() + _refresh_marks()` 立刻重绘(不等下一拍);
   X 范围别取“整库所有键”(离得远的陈旧键会把窗口拉废). 实测 Fit 前 X=(27.1,37.1) → 后 (-0.74,37.86), 越界子图 0。
36. **波形“看着像噪声 / 一块面积 / 跳变到 5 6” = 两条真根因, 都是钟的问题, 不是“画法难看”**:
   ① **ds.* (DDS 话题) 信号的 x 曾经用 `time.monotonic()`** (≈25965s), 与场景信号的回放进度 (0~40s) 差 2 万秒;
   取证定式: 直接 dump 缓冲 `(t,v)` 看 x 范围 (实测 25964.99~25980.32, 而 sstrace 在 0~10s), 同一条 x 上
   (25965.03) 叠着 6/7/0/1/2 多个值。后果: 一按 Fit X 拉到 0~25980 ⇒ 场景曲线压成一个点, ds 曲线在原 x 处
   上下跳 ⇒ 看着“一块多出来的绿色面积”。修: 用 3D 快照锚点 `(ts, 时间_s)` 把总线帧 wall 时刻映射成回放秒,
   并标 `scene=True` 与场景信号同轴同画法; 首次尾读的 200KB 历史帧映射成**负回放秒** ⇒ 丢弃 (否则是一条伸到 0
   左边的长尾巴)。
   ② **3D 回放会绕圈**: 每趟从 t_s≈0 重新写 x, 缓冲把历史趟全留着并只按 x 排序 ⇒ 同一 x 叠着两趟的点,
   折线在两趟之间上下跳 ⇒ “不是一条线/噪声”。接触概率/末端_x/环境接触/净接触 都是栽在这条上。
   修: 换趟检测 (回放秒比上一拍**回跳 > 2s**, 含手动拖进度条回看) ⇒ `store.clear_scene()` 清掉所有 scene 缓冲,
   本趟重新铺一条线; 状态栏写「· 第 N 趟回放」+ 日志一行说明 (波形被重置不许静默)。
   **判定“一条线”的可复核口径** (别靠眼睛): 同一信号在同一 x 上的跳变数 (`|Δx|<1e-9 且 |Δv|>0.5` 的对数) 应≈0;
   各曲线末点时刻最大差应 < 5s(同一根钟); 像素侧看“波形区每列绿色最长竖段”, 修后 中位 2px / 最大 14px /
   高竖段(>25px)列数 0 = 没有竖块。脚本: `tools/probe_wave_noise.py [秒数]`, 判据 ⑱。
   ③ 顺带去重: 同一 key 连续 (x, v) 完全相同不再入缓冲 (30Hz 轮询同一快照重复写同一点只会把线画花)。
37. **判“源码里不再出现某用法”必须先去注释行**: 自己写的说明性注释里出现了 `time.monotonic()` 这个词,
   按整段字符串 grep 直接假红。定式: 切出目标函数体 → 丢掉 `#` 开头的行 → 再判 (这类假红踩过多次)。


 + `zmax-ss-engine-loop.service`(引擎回路挂 VLM+多层管线) +
`zmax-ss-trace-pub.service`(真值帧发布) —— 一条命令装/重装: `bash tools/ss_fw_chain_install.sh`;
单独回退引擎两开关: `bash tools/ss_fw_chain_service.sh revert`。
