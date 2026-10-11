# 📈 CANoe-Graphic 式信号分析页 (tools/gui/canoe_graphic.py)

老倪要求: 「参考 Vector CANoe 的 Analysis→Graphic, 能显示任意 topic 的数值, 用波形显示 x y z a b c 等实时数据,
重构实时监控页」。实现: `CanoeGraphicWidget`, 在 studio.py 的 MonitorModule 里作为**首屏页签**, 旧内容
(同源实采表/Orin 部署状态/Rerun·RViz) 进第二页签。

## 双数据源 (都是真链路, 不造假)

1. **本机真值流** `HostJsonSource`: 轮询 `zmax_data/**.json` (默认 pose/state/safety/yolo/space),
   数值叶子自动扇平; 帧龄 = 文件 mtime 龄。实测位姿 `latest.json` 当前写入率 ~**5 Hz** (臂高速运动时才高)。
2. **Orin ROS2 话题** `RosTopicSource`: ssh 调 `tools/zmax_topic_sampler.py watch`, rclpy 订阅**任意话题任意数值字段**。

时间基: 横轴统一用**本机 monotonic**, 跨源可对齐; 每信号另带源侧帧龄 (本机=文件写龄, ROS=Orin 侧收包龄)。

## 踩过的坑 (都已在代码里修)

* **ROOT 路径算错一层** (`tools` 而非 `zmax`) ⇒ 本机真值流一个都采不到; `__file__` 要三次 dirname。
* **ROS 源 key 必须与信号栏一致**: 采样器给的是 `/gripper_pos.data`, 信号栏是 `ros.gripper_pos.data` ⇒
  推数据前统一成 `"ros." + k.lstrip("/")`, 否则"状态显示采样中但曲线无数据"。
* **帧龄按 key 取**: 原来按 `k.split('.')[0]` 取龄, 加了 `ros.` 前缀后永远取不到 ⇒ 改成按完整 key 查表。
* **glw.clear() 会把测量光标对象一起删** ⇒ 光标归 WaveArea 持有并在每次重建图形后重建 (`_make_cursors`)。
* **pyqtgraph 只有 left/right 两根内置轴**: 第 3 条信号起要自建 `pg.AxisItem('right')` 并 `p.layout.addItem(ax, 2, 3+n)`
  (官方 MultiplePlotAxes 做法); 直接 `showAxis("right1")` 报 `Scale 'right1' not found`。
* **数值序列话题**: ROS 里 `sequence<double>` (JointState.position) 发现阶段只能标成 `position[*]`, 运行时按实际长度展开
  ⇒ 信号栏要把 `[*]` 展开成 0..15 的下标行, 否则勾了也收不到值。
* 采样器 QoS 用 **BEST_EFFORT** (最宽松, RELIABLE/BEST_EFFORT 发布者都能收); 每路单独 `timeout`, 分段用
  `echo '##名字'` 标签切 (按位置切会错位)。
* 本体真值只有 x/y/z (臂静止时是水平直线, 不是画错); 要证明"画面真有变化"用 `pose.ts` 这类每帧推进的字段。
* **子线程里 `QTimer.singleShot(0, fn)` 不会触发** (该线程没有事件循环) ⇒ 首次建树根本没跑, 左侧信号目录永远空白。
  改法两条一起上: ① 目录拉取回调走 `pyqtSignal` 回主线程; ② 主线程定时器里比"信号集合+目录"指纹, 一变就重建 (1.5s 节流)。
  另: 话题目录落缓存 `zmax_data/graphic_logs/topic_catalog.json`, 一进页面就有名字, 不等 ssh。
* **多轴模式的 ViewBox 必须自己从 scene 里摘掉**: `glw.clear()` 只清 layout 里的 PlotItem, 用 `scene().addItem(vb)`
  加进去的副轴 ViewBox 会留下来继续画 ⇒ 切到"每信号独立图"后曲线跨子图溢出 (子代理视觉取证才发现)。
  重建前 `vb.scene().removeItem(vb)` + `axis.scene().removeItem(axis)` + `main_plot.layout.removeItem(axis)`。
* **MODE_SINGLE 里 `glw.clear()` 会把 `self.main_plot` 删掉** ⇒ 光标/缩放打在已删对象上; 循环里第一个建好的图要回写给 `main_plot`。
* 波形测试要数**面**不要数点: 判据 = "信号颜色像素出现在子图矩形之外"(用 `glw.mapFromScene(pane.sceneBoundingRect())` 映射到截图坐标),
  干净时 <300px (余量是抗锯齿); 另加"多轴往返后与干净重进一致 + 每条副轴量程覆盖自身数据"。
* 信号名口径 (老倪明确要求): 左侧显示**话题.字段全路径** (`/robot/tcp_pose.pose.position.x` / `pose.x`),
  话题行 `/robot/tcp_pose (PoseStamped)`; 本机源没数据也先把 `pose (latest.json) 等数据…` 列出来。
* 调色板按"缓冲区创建顺序"分配, 窗口里信号多了 (joint[0..11] 先建) 颜色会整体后移 ⇒
  取颜色**从控件读** (`store.get(k).color`), 别在测试里写死十六进制色值。
* **选时间窗不要强行打开「跟随最新」**: 原 `_on_window_changed` 无条件 `follow=True` ⇒ 把用户手动平移的位置顶掉,
  且按钮勾选状态与实际行为不符。跟随应由「⇥ 跟随最新」独立控制。
* **波形像素数回归必须先"定格"** (停数据源 + 关跟随 + 时间窗=全部), 否则脉冲型信号随窗口漂移, 前后两次抓图天然差几百 px,
  会把"数据漂移"误判成"串色回归"。定格后逐色像素数应完全相等。

## 离线取证模板2 (名字/模式)

## 📡 状态空间实况快照 = 3D 面板 / 波形页 / 外部核对 的单一真源 (2026-10-11)

老倪: 「3D 场景左下角这些实时变化的数据 topic 是什么? 对应实时监控哪个波形? 当前状态空间工程的所有数据要同步」。

* **3D 左下角面板的每个数 = 引擎轨迹 tr 的字段** (`ss_dreamview.py` 面板块 `self.lbl_num.setText(...)`),
  数据源标签 `self._src` (默认「状态空间 numpy 引擎」/ 「L4 演示·视频 episode」) — **不是 ROS 话题**, 是引擎内存里的轨迹。
* **出口**: 面板每帧调 `publish_trace_live(payload)` → `zmax_data/ss_live/trace_live.json`
  (tmp + `os.replace` 原子替换; **换帧必写**, 同帧才节流 0.05s)。
  契约铁律: **快照 == 屏幕上正在显示的那一帧**; 节流只允许对"同一帧重复写"生效。
* **消费**: `canoe_graphic.HOST_SOURCES` 加 `("sstrace", "zmax_data/ss_live/trace_live.json")` ⇒ 29 条可勾选信号, 同名同值。
* 面板行 → tr 键: 末端 `tr["x"]` · 光模块 `tr["peg"]`(抓握点) · 光模块头 `tr["peg_head"]` · 估计x̂ `tr["latent"]`(lat_pts[-1]) ·
  夹爪 `tr["gripper"]` · 头→孔 `|peg_head[:2]-_mouth[:2]|` · 环境接触 `tr["force"]` · 夹持 `tr["force_grasp"]` ·
  残差 `tr["residual_vec"]` · 接触概率 `tr["contact_p"]` · 前馈 `tr["u_ff_vec"]` · 动作调制 `tr["u_fuse_vec"]` · 安全边界 `tr["u_limit_vec"]`。
  上游测量量(真实链): 末端=/robot/tcp_pose(镜像 latest.json) · 夹爪=/gripper_pos · 力=/robot/force_torque · 光模块位置=3D 检测 yolo_detections.json; 其余为引擎计算。
* 判据 (`verify_trace_sync.py`): 真跑引擎 → `set_frame(k)` 定格 → 面板文本数值 == 快照 == 波形页 `buf.last_val` (逐字); 快照字段数 ≥20; 波形页真出 29 条 sstrace 信号。

## 🎬 信号窗口三件套 (2026-10-11 老倪: 「从 3D 场景显示的实时数据开始, 这些数据要对应实际的 topic;
## 这些 topic 的数据要在实时监控的 graphic 窗口被看到; 先只是显示 3D 场景的数据; 但也要有增加信号 topic 的功能」)

* **默认只显示 3D 场景数据**: `scope_combo` 默认 `3d` ⇒ 左侧只有一组「🎬 3D 场景实时数据 (引擎轨迹)」
  (`sstrace.*`, 来自 trace_live.json), ROS/数据空间/本机其他源全部隐藏; 切「🌐 全部来源」才列出来。
  首屏自动勾 6 条 (`DEFAULT_3D`: 末端.0/1/2 · 光模块头到孔_mm · 接触概率 · 安全边界_mps) + Y 轴模式切「每信号独立图」。
* **➕ 增加信号话题**: 一个对话框列三类真话题 —— 全局数据空间(DDS, 真名 `zmax/ss_state` 等) · Orin ROS2 · 本机真值流;
  加入后自动勾上该话题全部数值字段; ROS 话题会**重起订阅** (start() 会停旧 ros_src 再按新 selected 重订);
  加了非 3D 话题会自动切到「全部来源」; 此刻无帧的话题挂 `_watch_prefixes` 监视, 出帧即自动画。
  可测路径: 逻辑抽在 `_apply_topic_pick(picked, remove=False)` (不弹框也能回归)。
* **全局数据空间 (DDS) 信号源** `DataSpaceTraceSource`: 尾读 `zmax_data/dataspace/trace.jsonl` (总线帧),
  键 = `ds.<真话题名>.<字段>`。**digest 有三种形态必须都吃**: ① JSON 对象 (zmax/heartbeat)
  ② **被源侧定长截断的 JSON** (zmax/ss_diag, 缺右括号) → 补 `}` 后再 json.loads
  ③ 人读文本 (`tcp=(-1.0,-1.0,-1.0) frame_age=0.07s`) → 正则抠 `name=数字` / `name=(数字,...)`。
  三种都走 `parse_ds_digest()`; 解析不出的部分不产出 (不编造)。值 -1.0 = 源侧未提供 (DDS 约定), 照实画。
  实测: `ds.zmax/ss_diag.count` 271 点实时在流; 数据空间各话题出帧慢 (ss_diag ~3Hz / ss_state 0.5Hz)。
* **独立窗口**: `tools/gui/open_graphic_window.sh` (setsid nohup + DISPLAY=:0, 已有实例不重开);
  `python tools/gui/canoe_graphic.py` 自带 `__main__` 开单窗。控制台内同一控件在「📈 实时监控」首屏页签。
* ⚠️ 改默认范围会连带把老用例弄挂: `verify_graphic/verify_names/verify_wave_modes` 必须开头
  `w._default_done=True; w.scope_combo.setCurrentIndex(1); selected.clear()` 才能测通用能力
  (新默认断言归 `verify_signal_window.py`)。

### topic 在哪 / 名字与「数据空间」对不对得上 (高频追问, 先说位置再谈对应)
* **topic 就在左栏第 4 列「来源话题」** (表头 `["信号名称","当前值","帧龄","来源话题"]`, 内容由 `_src_hint(key)` 生成);
  名称列是 `_disp_name(key)`: `ros.*` 保留话题全路径, `sstrace.`/`ds.` 前缀剥掉; tooltip 给完整 key + 来源 + 点数。
* 四类来源列写法: `ros.*` → `Orin ROS2 · <话题>` · `ds.*` → `DDS · zmax/<话题名>` · `sstrace.*` → `SS_TRACE_SRC` 血缘表
  (末端=`/robot/tcp_pose (Orin 50Hz)` · 夹爪=`/gripper_pos (Orin)` · 环境接触/夹持=`/robot/force_torque (Orin)` ·
  光模块/光模块头=`YOLO 3D 检测 (旁路 JSON)` · 光模块头到孔=`L2 引擎 (孔口 objects3d.json)` · 其余=`L2 状态空间引擎 (无话题)`) ·
  其余 → `本机真值流 (JSON)`。
* **DDS 名字与「数据空间」页同源**: 键 = `ds.<登记话题名>.<字段>`, 名称列渲染成 `zmax/<话题名>.<字段>`,
  来源列 `DDS · zmax/<话题名>` (真源同为 `zmax_data/dataspace/{trace.jsonl,live.json,busdb.json}`)。
  实测 9/9 登记名都能命中; 但**有名字 ≠ 有帧** —— live.json 口径 `registered=24 / allowed=9 / alive=5`,
  没在发的话题 0 条是如实为空, 不是 bug。DDS 行「帧龄」列是 `-` (未算话题级帧龄), 值 `-1` = DDS 未提供约定。
* ⚠️ **「找不到 topic」先看数据范围下拉**: 默认 `3d` 只列 3D 场景数据 (`sstrace.*`); ROS/DDS/本机真值流要切
  「🌐 数据范围: 全部来源」才出现 ⇒ 答这类问题前先 `scope_combo.setCurrentIndex(1)` 再 dump 树。
* 取证: `probe_topic_names.py` —— 切全部来源 → 打印每行四列 + live.json 登记话题 → 逐条比对命中数
  (`ds.<话题>.` 前缀)。比看截图快, 还能给出"对应上 N/M"的数。

## ▶ 播放游标: 3D 进度条 ⇄ 波形竖线 (2026-10-11 老倪: 「3D 场景播放状态条的实际点要和实时监控的时间戳一致;
## 我在 3D 场景调整播放时间进度条, 实时监控的时间轴竖线也要在屏幕上同步左右移动」)

* **分水岭: 波形 x 轴必须是「场景时刻」(回放进度秒), 不能用到达时刻(epoch)**。用到达时刻时拖回退只会往右跳、
  永远不可能左移 ⇒ "同步左右移动"根本不成立。
  - `SignalBuffer.scene = True` 标场景时刻源; `push()` 时 `t` 直接存载荷里的 `时间_s`;
    `arrays()` 对 scene 源**按 x 排序** (乱序拖回退不成锯齿)。
  - 取 x 必须两处都分口径: 出波形处 与 `_tick` 里算 x_range 处 —— `x = t[-1] if b.scene else t[-1] - store.t0`。
* **竖线由共享播放状态驱动**, 不靠样本到达: 每帧读 `zmax_data/ss_live/trace_live.json`
  (3D 面板 `publish_trace_live` 发布的 `帧/总帧/时间_s/ts`), `fresh = age < 2.0s`。
  fresh ⇒ `x = 时间_s`; 不 fresh ⇒ 退回"最新样本 x"但**仍按源口径**(scene 源不得减 t0)。
* 绝对时刻反算: 场景时刻轴 `epoch = (ts - 时间_s) + x` (**不是** `store.t0 + x`)。
  `ClockAxis.epoch_base` 与 `pin_at`/`_epoch_of` 必须同一偏移, 否则竖线时刻与 3D HUD 对不上。
* 轴标签由"可见曲线是否 scene 源"决定, **不能由播放新鲜度决定** (否则 3D 一停就把「场景时刻 (s)」错退回「时间 (s)」)。
* 状态行写 `▶ 3D 播放 i/n @ 场景 t`; 停住写「3D 进度条已停」+ 最后时刻, 不假装还在放。

两个真踩到的坑 (都已写成断言):
1. `SignalBuffer` 有 `__slots__` —— 加字段必须先加进 `__slots__`, 否则 `AttributeError` 在 `__init__` 里炸。
2. 回退分支漏判源口径 ⇒ 竖线飞到 `x≈-1.79e9` (屏幕外)、标签显示假时钟。凡"按源分口径"的算式, 每个分支都要过一遍。

取证 (别只看截图):
* 确定性: `verify_playback_cursor.py` —— `PLAYBACK_FILE` 指到临时文件, 依次写 `t_s=8.0/45.5/3.2`,
  断言竖线 x 随之 `8.000/45.500/3.200` (右移后**左移**)、标签与轴同步、x 反算时刻 == 3D 那一刻、停止后仍在场景量级。
* 真机: `GRAPHIC_SELFCHECK` 加 2s 周期 `SELFCHECK` 行 (打 `pb帧/场景t/age/竖线x/标签/轴`), 播放中 grep 即可看到
  竖线随进度推进 (实测 12.325→12.750→12.938 对应帧 986→1020→1035), 比 OCR 稳。

## 🗂 独立功能页四件套 + 加载后归一 (2026-10-11 老倪: 「状态空间 工位总览 3D场景 数据空间 这些按钮,
## 实际上都是打开独立的功能页面」+「增加 实时监控 按钮, 打开实时监控的独立的功能页」)

* **⚠️ 已推翻 (同日)**: 「🧮 状态空间」的独立功能页老倪否掉 («做得太差, 删除, 恢复成原来的样子»), `ss_page_window.py` 已删,
  按钮回到 `open_state_space` (装进主画布)。**保留的教训**: (a) 「跟文件打开的工程保持一致」靠 `normalize_after_load()` 而不是新页;
  (b) 按钮只改名/只换实现时, 先确认他到底要"独立页"还是"原样"——他会直接说"恢复原来的样子";
  (c) 拉 Qt 子进程的 env 坑与归一按 name 配对的坑仍然成立 (见下)。
  当前按钮口径: `🧮 状态空间`→open_state_space(主画布) · `🖥 产品大屏`(原「工位总览」, 服务一字不动)→open_station_page ·
  `🧭 3D场景`→open_ss_3d · `🌐 数据空间`→open_dataspace_window · `📈 实时监控`→open_monitor_window(独立功能页)。
* 新页只读渲染 **同一份画布真源** (`flows.canvas_path()`), 纯 QGraphicsScene (无 GL ⇒ 不踩"第二个 GL 视图"坑),
  右侧点节点看参数。`flows.load_canvas()` 返回 **(data, errors) 2 元组** (不是 4 元组; 4 元组在 `project_file.canvas_status()`)。
* 🔴 **拉 Qt 子进程必须清平台/插件变量**: 控制台进程 env 带 `QT_QPA_PLATFORM=xcb`, 子进程会去
  `gui-venv311/.../cv2/qt/plugins` 找 xcb 插件 ⇒ 打印 "Could not load the Qt platform plugin xcb ... failed to start"
  然后**整进程退出** (观感 = "点了实时监控没反应")。手动从干净 shell 跑同一脚本却正常 ⇒ 差别仅在 env。
  修: 子进程 env 去掉 `QT_QPA_PLATFORM` / `QT_QPA_PLATFORM_PLUGIN_PATH` / `QT_PLUGIN_PATH` (+ 用 `_zmax_sane_env()`),
  启动脚本里也 `unset` 一遍 (双保险)。
* **加载后归一 `normalize_after_load(persist=True)`**: 两个入口 (状态空间按钮 / 文件→加载工程文件) 共用
  加载 → 节点尺寸规则(280×110) → `_relayout_row_gaps()` → **几何落盘回真源** ⇒ 真源==屏幕, 收敛后幂等。
  ⚠️ **必须按 `name` 配对节点**: `load_flow_file` 给画布节点分的是**新 id** (id_map), 按 id 与文件配对会全部落空
  ⇒ `fields` 恒 0、归一形同虚设 (实测踩到)。
  ⚠️ 改完画布真源后要跑 `tools/engineering_db.py build`, 否则 `check` 报漂移 `['project','canvas']` (库跟着真源走)。
* **自测通道**: `/tmp/zmax_nav_cmd` 新增 `ss_page` / `monitor` ⇒ 能从控制台内部触发按钮本体自测, 不必盲点坐标。
* 判据: `tools/probe_canvas_menu.py` 已更新 (10 项菜单真触发 · 5 个工具栏按钮 `isVisibleTo` ·
  🚀Z700 断言"没挂进任何布局"(`_z.btn.parent() is None`) · 4 个按钮点击真转发到方法);
  `verify_load_normalize.py` 9 项 (含"搅乱真源→归一→回读复原"+幂等+真源==屏幕)。
  **Z700 从工具栏撤下, 能力不丢**: `open_z700_flow` 保留 + 画布(C)菜单固定入口。

## ⏹ 3D 一停竖线就"不见了" (2026-10-11 老倪: 「同步时间轴不要消失 —— 我移动 3D 场景的播放按钮, 刚停止, 你的时间轴就不见了」)

* **根因 (旧代码)**: `_poll_playback()` 把 `trace_live.json` 的**文件新鲜度**当播放状态 (`fresh = st_mtime < 2s`)。
  3D 一停, 快照不再刷新 ⇒ 2s 后 `fresh=False` ⇒ `_refresh_marks()` 直接落到"最新样本"分支, 把竖线从
  **他停下的那一刻** 跳回最新样本处 (拖动时往往已滚到别处 ⇒ 看着就是"时间轴不见了")。
* **修法**: 加 `self._pb_last` —— 播放/拖动期间每次记录 `{t_s, ts, frame, total}`;
  `fresh=False` **且** 当前是场景时刻源时, 竖线 **留在 `_pb_last`** 那一刻, 标签继续写
  `▶ 场景 t=…s · 帧 x/y (3D 已停在这一帧) · 🕒 …`; **任何路径都 `setVisible(True)`** (绝不隐藏)。
  另加一层兵: 若那一刻被跟随/缩放挤到可视范围外, 把 x 范围撑到含它 (m = max(0.5, 5% 跨度))。
* 两条分支口径区别: **正在播放/拖动** → `▶ 场景 t=…s · 帧 x/y · 🕒`; **已停在这一帧** → 同上 + `(3D 已停在这一帧)`;
  **无播放历史** (进程起动时 3D 本就停着) → 回旧"最新样本"行为 (仍可见)。
* **判据**: `verify_pin_persist.py` (10 项): 播放中 x==7.500 ⇒ `fresh=False` 后 **仍 7.500 且可见**、
  停止后连刷 5 次不变、标签 🕒 == 停前最后一帧 ts、反向拖动 (12.000) 保护、无播放历史也不隐藏;
  真机取证件 `probe_pin_stop.py` (观测现场) + `sim_pb.py`+`start_gw.sh` (写 `trace_live.json` 模拟播放→突然停,
  再读 watch 日志看 `竖线x` 是否原地不动; **用完必把真源 cp 回去**)。
* ⚠️ 用真实在役 `trace_live.json` 做测试时, 3D **正在播放** ⇒ TIME-CORR 这类"快照 vs 最新样本"同刻断言会
  **假失败** (文件在测中还在跑): 先把 3D 跑到尾/停下 (帧==总帧 且 mtime 变老) 再跑。
* 命名口径: 窗口标题只写「📈 实时监控 · Graphic 信号分析」—— 老倪明确要求删掉“(CANoe 式)”那几个字
  (console 内嵌 tab 同步改成「📈 实时监控 · 信号分析」)。

## 🚫 画布"点了闪烁好几下" (2026-10-11 老倪: 「已加载 proj 再点画布的状态空间按钮, 屏幕又闪烁了好几下 —— 不是同一个源头么? 不要闪烁」)

* **根因**: 按钮那条腿**无条件** `self.clear()` → `load_flow_file()` 逐个重建 89 节点 → `_relayout_row_gaps()`
  ⇒ 每一步都重绘一次 (**整屏空 → 半成品 → 节点挪位**) = 观感"闪烁好几下"。**源头相同并不保证不闪** ——
  闪烁来自"重建过程"本身, 不是内容不一致。
* **修法 (两条一起上, 缺一不可)**:
  ① **记账 + 早退**: `load_flow_file()` 末尾记 `_loaded_src/_loaded_src_md5/_loaded_fp`; `normalize_after_load()` 末尾记
     `_norm_md5`(写回后的真源 md5) + `_norm_fp`(`_canvas_fingerprint()`); 点按钮时若
     `真源 md5 == _norm_md5 且 画布指纹 == _norm_fp` ⇒ **直接 return, 零重绘** (只落一行日志) ——
     这就是"已在显示该文件内容的归一后状态"的机器判据。
  ② **真要重建就冻结**: `self._frozen(True)` → `clear()+load+normalize` → `finally: self._frozen(False)`;
     `_frozen` 对 `canvas` + `scene.views()` 调 `setUpdatesEnabled(not on)`, 解冻后 `scene.update()` 刷一帧
     ⇒ 从"闪好几下"变成"最多一次到位置"。**重建必须仍在做** (换了文件/几何确实要归一时不能为了不闪就不干活)。
  ③ 画布内容指纹口径: 非 `type=='row_bg'` 节点的 `(name, x, y, w, h)` 排序元组 —— 与文件同口径可直接比。
* **判据**:
  · `verify_no_flicker.py` (12 项, offscreen): 首开真加载+记账 · 同一份再点**没触发 clear() 且 item 对象同一批** ·
    画布指纹==真源指纹 · 换内容必须真重建(之后又回到不重建) · 重建被 `_frozen` 包住 · 真源 md5 前后一致。
  · `shutter_flicker_probe.py` (真机): 写 `ss_canvas` 到 `/tmp/zmax_nav_cmd` 后连拍 8 帧, 逐帧有效像素占比 + 相邻帧像素差
    (近拍 0.12s), 判无空帧/半成品帧/首末一致。
  · 测试别写错期望: 复制同一份文件≠"换了文件" (内容指纹相同 ⇒ 本就不该重建); `load_flow_file` 内部自己会
    `clear()` 一次 ⇒ 换内容后 clear 计数 +2 而非 +1。

## 🖥 产品大屏链: 工位总览服务 → 单一数据源 → 飞书 → web → APP (2026-10-11)

* **同源做法**: `tools/dashboard_source.py` 新增 `screen` 段 —— 直接拉工位总览服务 `http://127.0.0.1:8793/station/status`
  (+`/ctl/status`) 的在役状态: 逐通道 online/fps/age_s/stalled/frames_served/kbps · `channels_online/total` ·
  `frame_age_max_s` · `motion_armed` · `robot{power,operation,mode,estop}` · `station_url`。不通就如实记 `err`, **不编造字段**。
* **一个只读端口给 web/手机**: `tools/dashboard_server.py` :8799 → `/`(unified_app.html, 手机优先) ·
  `/dashboard.json` · `/dl/<file>`(APK 等交付件)。**单独开端口不动在役 8793** (改在役服务要重启会打断正在看的画面)。
* **APK 地址口径必须是"候选列表"** (`tools/web/state3d_app/dash/src/main/java/com/zmax/dash/MainActivity.java`):
  `① 产线 LAN 192.168.23.50:8799 → ② 办公室 WiFi 10.163.146.78:8799 → ③ 公网 datadrive.world → ④ 包内离线页`。
  只烧一个 IP 的包换个网就白屏 (实测原包只烧了 WiFi IP)。改完 `./build_dash_apk.sh` 会打印"烧进包里的地址"+sha256,
  发布 = `cp` 到 `tools/web/dl/`, **下载件 sha256 必须与构建件逐字符相同**才算发布成功。
* **通知 web**: `tools/feishu_dashboard_push.py --notify-web --send [--base-url http://192.168.23.50:8799]`
  → 真发飞书卡 (回 `code=0` + `message_id` 才算成功); 发前跑 `assert_no_secrets` 脱敏断言。
* 公网缺口: `datadrive.world/factory-dashboard.html` 存在(200), 但 `dashboard.json` 与 `/dl/*.apk` 仍 404
  ⇒ 公网推流/APP 分发需 web 侧 (ECS nginx) 接管, 已在卡片里把链接与任务讲清。

## 🕒 时间戳一一对应 (2026-10-11 老倪: 「这些信号的波形跟 3D 场景是一一对应么? 场景里显示时间戳,
## 实时监控也要有个时间戳标记线, 我看看是否一一对应」)

* **口径**: 波长页分两类源 —— ① **场景时刻源** (`sstrace.*`, x = 回放进度秒, 见上节) ——
  绝对时刻用 `(ts - 时间_s) + x` 换算; ② **到达时刻源** (ROS / 本机真值流 / DDS, 统一 epoch `SignalStore.t0`,
  x = `t - t0` 相对秒; 真机同口径才比得上 (曾出现曲线 x=1.79e9 而标记线 x=-190 的错位)。
  标记线/光标/导出/时间轴必须同口径, 否则线会画在数据之外。
  宿主 JSON 源 **优先用负载自带的 `ts`** (`trace_live.json` 就是 3D 面板那一帧的时刻) ⇒
  波形最新样本时刻 == 3D HUD 时刻 (**实测差 0.000000s**)。标记线/光标/导出/时间轴必须同口径,
  否则线会画在数据之外 (曾出现曲线 x=1.79e9 而标记线 x=-190 的错位)。
* **3D 场景侧**: `set_fsm_panel` 里 `_rows.insert(0, self._clock_row())` 把 `🕒 快照时刻 HH:MM:SS.mmm
  · 帧 i/n · 场景时刻 t` 固定放面板第一行 (与 `publish_trace_live` 的 ts 同一个值: 一帧只取一次
  `self._frame_ts = time.time()`), 播放条 `lbl_frame` 也带上。
* **波形页侧**: `🕒 最新` 虚线标记线 (每张子图一根, 文字只画第一张) + `📌 打标记`(或直接点波形) +
  `🕒 绝对时刻轴` 可勾选按钮 (`ClockAxis.tickStrings` 把 x 换算成 `t0+x` 的时钟) +
  状态行加 `🕒 数据时刻`。`clock_str()` 在 `canoe_graphic` 与 `ss_dreamview` 各一份, **必须一字不差**
  (回归 `verify_time_corr.py` 会比对)。
* ⚠️ 快照只在 3D 面板渲染时写 ⇒ 3D 页被盖住/播完暂停时波形会定格 (帧龄会涨) —— 这是真实行为,
  不要把定格当故障; 要同时看两边就**另开独立窗口** (`tools/gui/open_graphic_window.sh`) 和 3D 场景窗并排。

## ⚠️ Qt 列表/列宽三个坑 (信号目录栏「白条、名字看不见」的真根因, 2026-10-11)

1. `setAlternatingRowColors(True)` + 深色样式表: 交替行用**调色板默认浅色** (#f7f7f7),
   而 `QTreeWidget{color:#fff}` 把文字刷白 ⇒ 白底白字 = 老倪说的"白条"。
   修: 样式表里加 `alternate-background-color:#11161d;` + `QTreeWidget::item{color:#c9d1d9;}`。
2. `header().minimumSectionSize()` 会被样式表抬到 **80**: 之后 `setColumnWidth(i,54)` / `resizeSection`
   全被静默夹到 80 ⇒ 5 列均分, 名字列只剩 80px 再被缩进吃掉 = 名字画不出来。
   修: `h.setMinimumSectionSize(28)` (再设窄列宽), 并 `h.setStretchLastSection(False)`
   (否则最后一列把名字列的空间又吃掉), `setIndentation(16)`, 数值列固定窄宽, 名字列 Stretch,
   长名字 `setTextElideMode(Qt.ElideMiddle)`。
3. 列宽要在 **显示后** 再设一遍 (`QTimer.singleShot(0/1200)` + `showEvent`): 离屏平台不重置、
   xcb 真机 polished 后会重置。

### 取证姿势 (省时间)

* 别靠猜屏幕坐标去裁图。在 `__main__` 里挂 env 门控钩子 (`GRAPHIC_SELFCHECK=/tmp/x.png`):
  打印 `tree.mapToGlobal` + `columnWidth` + 前几行 `text(0)`/`visualItemRect`, 并 `w.tree.grab().save()`
  —— 直接把控件自己的图拿去做 OCR (`ImageOps.invert` + 4x 放大, tesseract 才认深底亮字)。
* 离线可跑的列宽/可读性判据: `verify_tree_contrast.py` (浅色像素占比 <2% + 每行"深底+笔画"可读行数) ──
  比"看截图”靠谱。

## 复刻了哪些 CANoe Graphic 能力

信号目录(名/当前值/Min/Max/帧龄列) · 多信号波形 · Y轴三模式(共用/每信号独立Y轴/每信号独立图) ·
单测量光标 + 差分光标(Δt/Δv 读数) · 暂停(只停打印仍记录) · Fit · X缩放/上下左右平移 · 时间窗(5~120s/全部) ·
自动跟随 · 网格/采样点 · 高亮加粗 · 信号栏显示隐藏 · 手动 Y 轴范围 · 右键(加入/移除/加粗/换色/用作X轴) ·
Signal Logging 落 CSV · 导入 CSV 回放 · 导出 CSV/PNG (落 `zmax_data/graphic_logs/`)。

未做(说清楚, 不冒充): CANoe 的 返回/前进、拖动缩放模式、Create Common Axis 信号组、诊断命令信号、Hex 列。

## 离线取证模板

`verify_graphic.py`: offscreen 起 QApplication → `CanoeGraphicWidget()` → 等 10s 真实数据 → 勾 pose.x/y/z →
断言样本在**持续增长**、pose.ts 的 std>0、三种 Y 轴模式各抓图算非背景像素(>0.004)、光标 Δt 读数、
导出 CSV 行数、记录/导出落盘 → 再勾 `ros.gripper_pos.data` 断言真收到 174.0 (证明任意 topic 通道)。

`verify_names.py` (左侧名字): 构造后只等 1.2s (不等 ssh) 断言左侧 ≥3 行、含 `等数据…` 来源名与缓存话题名;
等 8s 断言 `pose.x` 与 `/robot/...` 全路径名存在、可勾选信号 >100、目录指纹已记、勾 `/gripper_pos.data` 真收到值、重建目录后勾选不丢。

`verify_wave_modes.py` (模式互切不串色): 勾 5 条 → 每模式抓图数每种信号颜色像素 (>100);
数子图矩形之外的该色像素 (<300); 多轴模式→独立图往返后再数一次; 读 `extra_vbs` 断言每条副轴量程覆盖自身数据。
