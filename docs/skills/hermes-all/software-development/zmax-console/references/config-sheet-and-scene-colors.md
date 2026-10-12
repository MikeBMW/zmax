# 配置单导出 · 场景色上屏 · 实时监控看配置 (2026-10-12 老倪)

## 老倪三条原话与对应真源

> 「你要发布一个配置单，可以从配置清单导出。带出所有的配置参数。」
> 「现在的实时监控，要能看出配置。」
> 「之前说的，绿色topic是插拔任务，你怎么没有将topic设置成绿色的？」

## ① 配置单(全参数) —— tools/config_sheet.py + `config_center.py sheet <TASK>`

- 8 段: 任务/场景/站点 · 工艺步骤 · 适用段 · 六档位(run_cfg) · 参数覆盖(overrides) ·
  画布(工程/节点/连线/md5 + 该任务启用节点的节点参数) · 参数注册表(全量, 带值/范围/单位/状态/真源) · 标定+点位台账。
- 真源: `config/ss_task_binding.json` · `config/tasks/tasks.json` · `flows/state_space_obs.json` ·
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

- `sstrace.*` = 状态空间引擎轨迹快照 → **画布数据源那一场场景**(真源 `ss_scene_switch.now()['src_state']`)。
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
1. **打标真源空着**: `tools/sig_scene_tags.py::_run_signals()` 只扫 `zmax_data/task_runs/<TASK>/**` 里的
   json/jsonl 键名; 两条 episode 链真跑完只落 `reports/*.npz/mp4` ⇒ 该目录空 ⇒ 摆盘只剩 3 条历史夹具名。
   ⇒ 跑完必须把运行产物落 `zmax_data/task_runs/<TASK>/` (逐步 jsonl + 汇总 json)。
2. **运行证据优先权反了**: `build()` 原为 `if k not in sig`(只补空缺) ⇒ 真跑过的信号被 node/关键词启发式先占位,
   一条也标不上。已改为运行证据**覆盖**启发式(不动 `ar./sstrace./ds.` 前缀与人工 overrides)。
3. **`--from-runs` 单独跑不重建**: `main()` 里只有 `--build --from-runs` 才写盘; 只给 `--from-runs` 只打印汇总。
   摆盘还多一道: 链侧从不写 `zmax_data/ss_live/trace_live.json`(窗里 `sstrace.*` 的唯一源) ⇒ 需要自己的重放
   发布器 `tools/tray_live_publish.py` (读 npz → 落运行产物 → 重建标签 → 按 episode 时间轴 20Hz 重放写 trace_live)。
4. **二维数组取值坑**: `_f(z["x"], i, k)` 这种助手(第3参是 default)会把 k 当 default 吃掉, 异常时返回 default
   ⇒ 末端/光模块整列变 0,1,2。必须 `_f(z["x"][i], k)`。

验收口径 (真看图, 不要看代码就说好了): `xdotool windowactivate --sync <信号窗>` + `scrot -u`(抓**焦点窗自身**,
不受层序影响; 全屏裁剪会量到压在它上面的配置中心 ⇒ 它的表也有绿/蓝/紫格子 = 假绿) + 数蓝色像素(`#1f6feb`):
只有组标题 ≈365px, 真信号上屏后 **6263px**; 再 OCR 左栏能看到真信号名与实时值(例: 单颗CT 10.64)。
