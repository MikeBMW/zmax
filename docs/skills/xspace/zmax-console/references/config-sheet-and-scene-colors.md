# 配置单导出 · 场景色上屏 · 实时监控看配置 (2026-10-12 老倪)

## 老倪三条原话与对应唯一依据

> 「你要发布一个配置单，可以从配置清单导出。带出所有的配置参数。」
> 「现在的实时监控，要能看出配置。」
> 「之前说的，绿色topic是插拔任务，你怎么没有将topic设置成绿色的？」

## ① 配置单(全参数) —— tools/config_sheet.py + `config_center.py sheet <TASK>`

- 8 段: 任务/场景/站点 · 工艺步骤 · 适用段 · 六档位(run_cfg) · 参数覆盖(overrides) ·
  画布(工程/节点/连线/md5 + 该任务启用节点的节点参数) · 参数注册表(全量, 带值/范围/单位/状态/唯一依据) · 标定+点位台账。
- 唯一依据: `config/ss_task_binding.json` · `config/tasks/tasks.json` · `flows/state_space_obs.json` ·
  `config/mcd/param_registry.json` · `config/calib/*.json` · `data/skills/l2_atomic/*.json`。
- 落盘: `outputs/config_sheets/配置单_<TASK>_<ts>.md/.json` + `_latest` 副本。GUI 按钮 = 「📋 配置单(全参数导出)」
  (走 `veh6_config_page._run('sheet', arg=TID)`, 与 CLI 同一条代码路径)。
- 缺口要照实进表(例: `calib:T_base_cam.value = null · 未标定(缺口)`) —— 老倪工程真实性零容忍。

## ② 逐条场景色失效的**真因**: 样式表压掉 setForeground

- 症状: 树里条目数据是 `#2e8b57`, 离屏全分辨率渲染**绿色像素 = 0**(全灰) ⇒ 老倪看到的"没设成绿色"。
- 真因: `canoe_graphic.py` 里 `QTreeWidget::item{color:#c9d1d9;}` 让逐条 `setForeground(场景色)` 失效。
- 修: 条目默认色交回 palette/条目数据, 样式表只留 `padding`; 判据里的**负对照**(把旧样式贴回去 ⇒ 绿像素必须 = 0)
  就是钉这个坑的。
- 教训(通用): Qt 样式表里的 `QTreeWidget::item{color:...}` / `QTableWidget::item{color:...}` 会**压掉**
  item 级前景色 —— 想逐条上色就别在样式表里写 item color, 用 palette 或 item 数据。
  **判据必须数渲染像素**(`QWidget.render` → 数颜色), 只断言 `foreground().color()` 会假绿。

## ③ 来源族 → 场景 (sig_scene_tags._source_scenes)

- `sstrace.*` = 状态空间引擎轨迹快照 → **画布数据源那一场场景**(唯一依据 `ss_scene_switch.now()['src_state']`)。
- `ros./robot/force_torque.*` · `ros./gripper_pos.*` = 力控插入/夹持专用 → 插拔场景。
- `ros./robot/tcp_pose.*` = 三场景共用的真机位姿 ⇒ **留白**(要绿就写进 `overrides`)。
- 标签文件 `config/topics/scene_tags.json` 的 `source_scenes` 段落 = 规则的落地; `tag()` 先查逐信号, 再查前缀族。

## ④ 实时监控「当前配置」横幅

- `canoe_graphic.py` 树上方一行 QLabel(5s 自刷新, 读 `outputs/config_sheets/配置单_*_latest.json`):
  任务ID + 名称 · 场景(场景色上色) · 配方 · 工艺步数 · 启用节点 · 档位 · 参数覆盖 · 配置单文件名/导出时刻。
- 没有配置单时退回 `ss_task_bind.build()` 现算(不编数字)。

## 判据与跑法

```
gui-venv311/bin/python tools/verify_scene_topic_colors.py     # 17/17 PASS, 需 DISPLAY
```
离屏渲染口径: `w.setAttribute(Qt.WA_DontShowOnScreen=True)` + `w.render(QPainter(QImage))` 数指定矩形内的颜色像素;
数像素要**限定在树控件矩形内** —— 顶部场景按钮/分组标题本身也带场景色, 全窗数会误判(负对照曾因此假过 80px)。

## ⑤ 目录按四场景分组 + 折叠/窗口/反映慢 (2026-10-12 同日追加)

老倪: 「窗口无法拖放调整大小 · 下三角不能折叠隐藏, 点了也没反应 · 感觉就是反映慢 · 绿色场景标题该叫插拔场景 ·
AR 下面是白色? · 摆盘呢? · 其它无法分类的定义为基础场景, 白字显示 topic」。四条真因与修法:

1. **目录分组**: `canoe_graphic.SCENE_GROUPS` = 🟢 插拔场景 / 🔵 摆盘场景 / 🥽 AR 场景 / ⚪ 基础场景(白);
   归组一律走 `sig_scene_tags.tag(key)`, 没打标 ⇒ 基础场景。组标题写场景名+数据来源, 别再叫「3D 场景实时数据」。
   摆盘链未接时给一行灰字说明(不编数据), 数据到了自动变蓝。
2. **折叠没反应**: `_fill_tree` 结尾硬编码 `setExpanded(True)` ⇒ 用户折叠被下一次重建顶开。
   修法: 维护 `_collapsed` 集合, 重建时用户折叠优先(同时保留 `_expanded`); 组节点用 `UserRole+1` 存稳定 sid
   (如 `scene:插拔场景` / `ar:<组名>`), 别用显示文案当 key(文案会变)。
3. **窗口拖不动**: 真因不是布局, 是**开窗尺寸超出屏幕**(实测 2017x1131 @ (1934,118), 桌面 3840x1200 ⇒
   右下两个边在屏外抓不到)。修法: 开窗按 `availableGeometry()` 收口留 40px + `setMinimumSize(900,600)` +
   `GRAPHIC_WIN_GEOM=x,y,w,h` 环境变量覆盖。诊断第一步永远是 `wmctrl -lG` 看右/下边是否出屏。
4. **反映慢**: `_tick` 在 UI_FPS=20 下无条件重画 N 条曲线 ⇒ GUI 线程一直忙, 输入事件排队。
   修法: `_wave_dirty(xr)` 判据(新样本/播放游标/跟随滚动/暂停切换才重画)。

判据扩展(同一脚本): ⑦ 四组组名+组色(插拔#2e8b57/摆盘#1f6feb/AR#8957e5/基础#ffffff) · ⑧ 折叠后重建仍折叠。
判据要等 2~3s 再断言行数 —— 本机源线程推第一帧前先建树会得到“只有组没有行”的假红。
末尾用 `os._exit(code)` 硬退: Qt+线程退出期偶发 segfault, 别让它污染判据退出码。

## 信号→场景颜色: 摆盘(蓝)为什么一条真信号都没有 (2026-10-12 实测根因)

老倪问「摆盘场景的实时监控蓝色信号一个都没有么? 你是真正运行了么」—— 四条真因, 一查就见:
1. **打标唯一依据空着**: `tools/sig_scene_tags.py::_run_signals()` 只扫 `zmax_data/task_runs/<TASK>/**` 里的
   json/jsonl 键名; 两条 episode 链真跑完只落 `reports/*.npz/mp4` ⇒ 该目录空 ⇒ 摆盘只剩 3 条历史夹具名。
   ⇒ 跑完必须把运行产物落 `zmax_data/task_runs/<TASK>/` (逐步 jsonl + 汇总 json)。
2. **运行证据优先权反了**: `build()` 原为 `if k not in sig`(只补空缺) ⇒ 真跑过的信号被 node/关键词启发式先占位,
   一条也标不上。已改为运行证据**覆盖**启发式(不动 `ar./sstrace./ds.` 前缀与人工 overrides)。
3. **`--from-runs` 单独跑不重建**: `main()` 里只有 `--build --from-runs` 才写盘; 只给 `--from-runs` 只打印汇总。
   摆盘还多一道: 链侧从不写 `zmax_data/ss_live/trace_live.json`(窗里 `sstrace.*` 的唯一源) ⇒ 需要自己的重放
   发布器 `tools/tray_live_publish.py` (读 npz → 落运行产物 → 重建标签 → 按 episode 时间轴 20Hz 重放写 trace_live)。
4. **二维数组取值坑**: `_f(z["x"], i, k)` 这种助手(第3参是 default)会把 k 当 default 吃掉, 异常时返回 default
   ⇒ 末端/光模块整列变 0,1,2。必须 `_f(z["x"][i], k)`。

## 工程列的唯一依据 = data/database/zmax (不是 reports/)
老倪 10-12 现场纠正: 「配置中心 状态空间的主工程, 路径不是 reports/, 一个都不对」
「/home/ubuntu/zmax/data/database/zmax 主工程路径是这」
- **唯一依据**: `data/database/zmax/zmax_space.proj` (总工程; 代码唯一依据 `tools/gui/project_file.space_path()`,
  其余 9 个工具同源) + `data/database/zmax/zmax_engineering.db` (工程库, 单一唯一依据: 库内 `projects` 表存工程名/路径)。
- **坑**: `tools/proj_state.DEFAULT_PROJ` 指向 `reports/projects/SS_主工程_任务配置.zmaxproj` —— 那是 5.21 的
  **老导出件**; 照它显示工程列 = 全错(文件虽存在, 但已不是工程的落地处)。旧文件还在被某段代码引用 ≠ 它还是唯一依据。
- 修法: `veh6_config_page._proj_paths()` 候选序 = ① `project_file.find_space()` ② 工程库 projects 表 path
  ③ `data/database/zmax/zmax_space.proj`; 工程名取总工程文件自带 `name`; tooltip 补「工程目录」「工程库(单一唯一依据)」。
- 判据: `tools/verify_zmax_open_flow.py` 里工程列断言必须指向 `data/database/zmax` + `zmax_space.proj`
  (否则判据本身在给错路径背书)。

验收口径 (真看图, 不要看代码就说好了): `xdotool windowactivate --sync <信号窗>` + `scrot -u`(抓**焦点窗自身**,
不受层序影响; 全屏裁剪会量到压在它上面的配置中心 ⇒ 它的表也有绿/蓝/紫格子 = 假绿) + 数蓝色像素(`#1f6feb`):
只有组标题 ≈365px, 真信号上屏后 **6263px**; 再 OCR 左栏能看到真信号名与实时值(例: 单颗CT 10.64)。

## 3D 场景几何/材质 四个真坑 (2026-10-12 老倪两问实测)

老倪: 「插拔的 夹具/孔座 与插入的孔口 横向有偏差」·「摆盘 光模块不能是透明的, tray盘太小放不下」
1. **盒心用错口径**: `meta["box_center"]` 是**环境系原点**(实测 z=-0.0008), 被当网格中心画 ⇒ 盒顶比孔口低 35mm,
   盒子一半埋进桌面(盒跨 -0.096~+0.094, 桌面顶≈0.024)。修 = 盒心由孔口反推(+X 面与孔口面齐平、z=孔口高)。
   取证口径: 数值(z 差) + 逐像素复核两层都要 —— 独立复核同时确认「孔口标签浮在盒顶上方 90~130px」。
2. **“透明”不是图层叠加, 是 shader**: 盘件用 `shader=None`(无光照平涂) ⇒ 单一色 (235,189,61) +
   亮黄线框穿面 + 内底灰面透出 ⇒ 被看成玻璃/贴图块。修 = 金属件改 `shader='shaded'`(盘壁/内底保持平涂)。
   判据可量化: 单色平涂像素(±6) 72 → 宽色域(±45) 15893 ⇒ **明暗占比≈100%** = 真的有面明暗。
3. **“太小放不下”要对准比的是谁**: 实测金件全在盘内、桌上 0 金色像素 ⇒ 不是超盘外廓, 而是**件比自己的槽位线框大**
   (标记 r=0.012=24mm < 件长 52mm)。修 = 槽位半径按件半长取 (r=件半长+1mm)。
4. **同一物体网格别跨场景硬用**: 光模块网格曾一直硬用插拔 `_PEG_SIZE`(200mm), 而摆盘槽位 52×20×12mm;
   摆盘盘件尺寸的唯一依据 = `sim_scene_def._tray_layout`。切场景时要重算尺寸并重建网格。

取证脚手架(现成脚本, 别每次现写): `tools/qa_3d_pixels.py`(颜色反查物体) · `tools/cmp_3d_fix.py`(修前后对比) ·
`tools/qa_3d_pixels.py` 必须带 `export DISPLAY=:0`(`DISP="DISPLAY=:0"` 这种变量前缀会 command not found ⇒ 抓到别的窗口);
颜色掩膜按物体常量 + 连通块, 不排掉窗口背景色会被背景吞掉。
看不见图时: 派一个能看图的子代理逐像素描述(本次就是它推翻了“透明=图层叠加”的猜测)。

## 3D 场景「残留上一个场景的轨迹线」——两条真因 (2026-10-12 实测)

老倪: 「摆盘的场景, 为什么还残留着插拔场景的轨迹线?」两条都修真了, 都很容易再犯:
1. **切场景不换 episode 唯一依据**: `ss_dreamview._switch_scene` 原来只 `_build_scene()`(重建几何), `self.tr` 一直是
   构造时读的 `reports/ss_episode_latest.npz`(插拔 752 帧) ⇒ 摆盘里那条「📡 末端实测轨迹」还是插拔的。
   修法 = `scene_episode_path()/load_scene_episode()` 每场景认自己的 episode(**摆盘=`reports/tray_place_latest.npz`
   2708 帧 · 插拔=`reports/ss_episode_latest.npz` 752 帧**), 切场景先 `set_trajectory()` 再重建。
2. **单独切场景窗口不跟**: 3D 窗原来只在按「🚀 启动工程·信号·场景」(`studio._ss3d_push_scene`) 时被推场景;
   直接改画布 `ssdata.src_state` 窗口无感 ⇒ 现场看就是“残留”。修法 = `_watch_canvas_scene()` 看门狗
   (2s 比对 `canvas_src_scene_id()` 与 `self.scene_id`, 变了就切)。
3. **看门狗不能吃掉手动按钮** (同日回归, 必修): 场景按钮只切窗口、**不写画布 `ssdata.src_state`** ⇒ 上面那个 2s
   看门狗又把窗口扳回旧场景 —— 现场看到的竟是「点击插拔, 却自动跳到了摆盘场景」(= 按钮像失灵)。
   修法 = 按钮走 `_switch_scene_manual()`: **先** `write_canvas_scene()` (复用 `tools/ss_scene_switch.py::switch`,
   与配置中心同一条路) **再**切窗口, 并给手动动作 8s 独占期 (`self._manual_scene_ts`, 看门狗期间不抢)。
   通用规则: 任何“自动跟随单一唯一依据”的看门狗, 都要给手动入口留独占窗口, 且手动入口必须先写唯一依据。
   验证: 写画布后 **10s 与 24s 各看一次** `wmctrl -l | grep 3D场景` 仍停在目标场景才算修好
   (只看一次会把“还没来得扳回去”当成功)。
证据只看日志一行(别靠截图: 视图在动画, 任意两张图必有差): `🧩 [3D场景] 跟随画布数据源 → SS-TRAY-PLACE`
+ `已装载 摆盘 episode · tray_place_latest.npz · 2708 帧`。
附: 脚本里 `DISP="DISPLAY=:0"` 这种**变量前缀写法无效**(报 `DISPLAY=:0: command not found`), 要 `export DISPLAY=:0`。

## 三颗光模块轨迹 · MoveIt 口径 (2026-10-12)
- `tools/tray_plan_3parts.py` 从**真跑 episode 抽 3 颗各自轨迹** → `reports/tray_plan_3parts.json`
  (按 `stage` 回退切颗: 每颗 10 段, 段名取 episode 真 stage; 路点 >2mm 抽稀, 上限 1500)。
  文件里 `source` 预先固定「真跑 episode 真值 · NOT MoveIt 输出」—— **不许冒充规划产物**。
- **MoveIt 没为摆盘出过轨迹**: 画布 `n_moveit` 只是规格节点; 真链是容器 `zmax-moveit`(plan-only),
  最后一次成功规划 10-09 21:04 且目标是 slot7 类插拔目标, `live_plan.jsonl` 至今未更新, 容器默认没起
  (只有写请求的 `zmax-moveit-plan-req.service` 常驻)。要跑: `bash tools/moveit_live_up.sh up` +
  `python3 tools/moveit_plan_req.py --goal-xyz … --goal-quat … --once`(目标取 plan JSON 各颗 TCP 终点),
  且必须先过同源闸 ≤5mm/2° —— 无真机链路时过不了 ⇒ 如实说“出不来”, 别说成规划结果。
- 轨迹/状态信号: `tray_live_publish.py` 每帧发 轨迹_当前颗/已规划颗数/段/进度_pct/路点数/累计距离_mm/来源
  (jsonl 与 trace_live **双写** —— 只写 trace_live 打标扫不到, 进不了蓝组)。

## 3D 场景后续追加 (偏移默认值 / 拿起的件 / 放下留件 / 像素口径)

> 📄 完整口径与判据已整理成专题: `references/3d-scene-rendering-geometry.md` (先读它再改 `ss_dreamview.py`)。
> ⚠️ `SKILL.md` 已撞 100KB 上限, 新专题**只能**从本文件或其它 references 转一层链过去。
1. **`meta.get("peg_head_off", [-0.13,0,-0.01])` 静默套用插拔默认值** ⇒ 摆盘 episode (无该字段) 上的抓握偏移
   变成 -30mm ⇒ 画出的件横向偏 30mm (用户: “拿起来的和渲染的光模块有位置偏差”)。缺字段 ⇒ 偏移 0 + 打日志。
2. **“拿起来就变长/消失”**: 摆盘臂上件曾被整件隐藏(理由: 料盘里已有 3 个) ⇒ 拿起时露出插拔的 200mm 那根。
   该画就画, 只换尺寸 (`_peg_size` 按场景取)。
3. **放下后件不见**: 只画“当前这一颗” ⇒ 放完就没了。用 episode `stage` 进入“完成”的次数点亮 tray 槽位
   (真值帧 798/1723/2654), 不另造数。
4. **像素对比要同分辨率**: 3068×1862 与 1300×900 直比像素数会得假结论 —— 换算 px↔mm 或重抓同尺寸;
   抓“事件那一刻”要轮询 live trace 字段(如 阶段/轨迹_段 含 抬起) 命中后再 `scrot -u`。
