# 配置单导出 + 场景色上屏 + 实时监控看配置 (2026-10-12 老倪)

> 老倪原话：「现在已经开始运行了，你要发布一个配置单，可以从配置清单导出。带出所有的配置参数。先给出当前插拔项目的所有配置参数。而且现在的实时监控，要能看出配置。之前说的，绿色topic是插拔任务，你怎么没有将topic设置成绿色的？」

三件事，三处真源，逐条可复核。

## ① 配置单（全参数导出）—— `tools/config_sheet.py` + `config_center.py sheet`

从**配置清单**导出该任务在当前状态空间工程里的全套配置参数，8 段：

| 段 | 内容 | 真源 |
| --- | --- | --- |
| ① 任务/场景/站点 | 任务ID/名称/配方类型/场景+色/站点/触发/循环/判据/安全/ss_mode/工单规则/适用段 | `config/ss_task_binding.json` + `config/tasks/tasks.json` |
| ② 工艺步骤 | 9 步（名称/时长/描述/力） | 同上 |
| ③ 适用段/不适用段 | 8 段 + 排除段 | 同上 |
| ④ 六档位 | run_cfg 六路开关（label/checked） | 同上 |
| ⑤ 参数覆盖 | overrides（该任务对工程默认值的覆盖） | 同上 |
| ⑥ 画布 | 工程名/89 节点/184 连线/md5 + **该任务启用 52 节点的逐节点参数** | `flows/state_space_obs.json` |
| ⑦ 参数注册表 | **710 项**（calib 45 · canvas 79 · code 25 · platform 24 · scene 48 · space 56 · switch 6 · teach 427），每项带 值/范围/单位/状态/真源 | `config/mcd/param_registry.json` |
| ⑧ 标定真源 + 点位台账 | 标定文件 sha256/时间；示教点/空间点/AOI 点条数 | `config/calib/*.json` · `data/skills/l2_atomic/*.json` · `reports/aoi_points/` |

用法（GUI 按钮「📋 配置单(全参数导出)」= 同一条命令，选中任务那一行）：

```
gui-venv311/bin/python tools/config_center.py sheet TASK-01-FW
# → outputs/config_sheets/配置单_TASK-01-FW_<ts>.md / .json
#   另有 latest 副本: 配置单_TASK-01-FW_latest.md / .json
```

**插拔项目（TASK-01-FW）实导**：场景 插拔场景 #2e8b57 · 站点 SITE-A.ST11 · 配方 插拔+固件校验 · 工艺 9 步 · 适用段 8 · 启用节点 52 · 六档位 6 · 参数覆盖 6 · 参数注册表 710 项 · 标定 2 文件 · 点位 3 份。
已知缺口（照实写进配置单）：`calib:T_base_cam.value = null · 未标定(缺口)`（站点几何未定 ⇒ 坐标类参数不可信）。

## ② 绿色 topic = 插拔任务 —— 真因不在"没打标"，在"打了标没上屏"

两个独立缺陷，实测都成立：

1. **样式表压掉条目色（真因）**：`canoe_graphic.py` 里
   `QTreeWidget::item{color:#c9d1d9}` 让 `setForeground(场景色)` 失效 —— 树里 34 行条目数据上是
   `#2e8b57`，**离屏全分辨率渲染绿色像素 = 0**（全灰）。修法：条目默认色交回 palette/条目数据，
   样式表只留 padding；改后同一渲染绿色像素 **2938 px**，负对照（贴回旧样式）**= 0 px**。
2. **来源族没进标签层**：标签真源 `config/topics/scene_tags.json` 原来只认"运行产物里出现过的信号名"，
   而引擎轨迹快照的键（`sstrace.估计值/末端/光模块头到孔_mm/接触概率/前馈速度/安全边界…`）不在其中。
   新增**来源族 → 场景**层（`tools/sig_scene_tags.py::_source_scenes`）：
   * `sstrace.*`（3D 引擎轨迹快照）→ **画布数据源那一场场景**（真源 `tools/ss_scene_switch.now()['src_state']`）
   * `ros./robot/force_torque.*` · `ros./gripper_pos.*`（力控插入/夹持专用）→ 插拔场景
   * `ros./robot/tcp_pose.*`（三场景共用的真机位姿）→ **留白**（要绿就写进 overrides）

改后实测：`sstrace.末端.0 / 接触概率 / …` → `插拔场景 #2e8b57`；真机现场窗口内绿色像素 **5794**。

## ③ 实时监控"能看出配置" —— 顶部常显「当前配置」横幅

`canoe_graphic.py` 树上方一行（5s 自刷新，真源 = 配置单 latest json）：

```
⚙️ 当前配置 TASK-01-FW FW Loading + EEPROM 写/读校验 · 场景 插拔场景 · 配方 插拔+固件校验 ·
   工艺 9 步 · 启用节点 52 · 档位 6 · 参数覆盖 6 · 配置单 配置单_TASK-01-FW_latest.json ·
   导出 2026-10-12 18:06:07 · 真源 任务/绑定/画布/参数注册表
```

现场窗口 OCR 实读（`/tmp/ssv/left_top.png`）与该文本一致。

## 判据

```
gui-venv311/bin/python tools/verify_scene_topic_colors.py     # 17/17 PASS (需 DISPLAY)
```
含 6 条独立断言：静态回归闸（样式表不许再压条目色）· 标签层（sstrace/force_torque→场景色，tcp_pose 留白）·
离屏真渲染（真数据拷贝 fixture：29 行全绿、绿像素 ≥500、仍有白行）· **负对照**（贴回旧样式 ⇒ 绿像素=0，
真因可复现）· 顶部横幅含 任务ID/场景/配置单文件名 · AR 紫色映射。

## 追加 (同日): 目录改成四场景组 + 折叠不再被顶开 + 窗口能拖

老倪: 「实时监控窗口无法拖放调整大小，信号名称旁边的下三角符号也不能折叠隐藏，点了也没反应」
      「感觉就是反映慢」 → 「绿色场景，你的标题是 3D 场景实时数据，应该改成 插拔场景；AR 下面是白色？还有摆盘场景呢？摆盘应该是蓝色信号」
      → 「其它的无法分类的信号，定义为基础场景，用白色显示信号 topic」

四处真因/修法：

1. **信号目录按场景分组**（`SCENE_GROUPS`）：🟢 插拔场景 / 🔵 摆盘场景 / 🥽 AR 场景 / ⚪ 基础场景(白)。
   组名直接写场景名 + 数据来源（不再叫「3D 场景实时数据」）；归组 = `sig_scene_tags.tag(key)` 打标真源，
   没打标一律进「基础场景」白 ○。AR 组保留二级分组（AOI/相机/空间点位…），二级标题也用场景色。
   摆盘组此刻无数据 ⇒ 一行灰字说明「真空/吸盘/料盘/槽位话题未接」，数据到了自动变蓝。
2. **折叠点了没反应** = 真因：`_fill_tree` 结尾硬编码 `setExpanded(True)`，用户一折叠，下一次重建（键集变化触发的）
   又把它顶开。修法：`_collapsed` 集合记录用户折叠，重建时「用户点过的折叠优先」，并同时保留 `_expanded`。
3. **窗口拖不动** = 真因：开窗尺寸超过屏幕（实测 2017x1131 @ (1934,118)，桌面 3840x1200 ⇒ 右边 111px、下边 49px
   在屏幕外，**右下两个边根本抓不到**）。修法：开窗按当前屏幕可用区收口（留 40px）+ `setMinimumSize(900,600)`
   + `GRAPHIC_WIN_GEOM=x,y,w,h` 覆盖。修后实测 1720x1010 @ (114,181)（右 1834 / 下 1191，都在屏内）。
4. **反映慢** = 真因：`_tick` 在 UI_FPS=20 下**无条件**重画 250 条曲线 ⇒ GUI 线程一直忙，输入事件排队。
   修法：`_wave_dirty()` 判据（新样本 / 播放游标动 / 跟随滚动 / 暂停切换才重画）。

判据：`tools/verify_scene_topic_colors.py` **24/24 PASS**（新增 ⑦ 四组组名+组色、⑧ 折叠后重建仍折叠）。
现场屏幕实测：左栏绿 8075 px / 蓝 387 / 紫 768 / 白 234（四种场景色都在屏上）。


## 留痕

- `tools/config_sheet.py`（新）· `tools/config_center.py`（+`sheet` 命令）· `tools/gui/veh6_config_page.py`（+按钮）
- `tools/sig_scene_tags.py`（+来源族规则）· `config/topics/scene_tags.json`（重建）
- `tools/gui/canoe_graphic.py`（条目色修复 + 配置横幅）
- `tools/verify_scene_topic_colors.py`（新判据）
