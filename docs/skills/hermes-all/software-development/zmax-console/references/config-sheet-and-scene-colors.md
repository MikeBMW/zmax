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
