---
name: zmax-scene-engineering
description: Use when Z-MAX 场景工程化/原子技能/合作闭环. 场景JSON、3D链接、POST、row_bg坑。
---

# Z-MAX 场景工程化 (2026-08-09)

## 触发条件
- Simulink 场景 node / 原子技能场景 / 合作数据闭环画布
- scene-api.php POST / scene-3d.html 链接
- row_bg 背景布局问题

## 核心文件
- `flows/scene_skills_3scenarios.json` — 三场景权威数据源 (SCN-01插拔/SCN-02搬运/SCN-03检测, id/scene_id 双兼容, process_steps+performance)
- `flows/cooperation_closed_loop.json` — 合作合规闭环画布 (19节点14连线)
- `flows/scene-3d.html` — ECS 3D 场景页 (部署 datadrive.world)
- `flows/scene-api.php` — POST 接收端点 (保存 scenes/scene_{type}.json)
- `tools/gui/simulink_module.py` — open_scene_link / _open_scene / open_atomic_skill_flow

## 关键链路
1. 场景 node 双击 → `_open_scene` → JSON 上传窗口 (预览/链接/上传按钮/结果)
2. 上传 → POST `scene-api.php/<insert|handle|aoi>` (web 格式: name/skills/specs/kpi, success_rate 小数 0.995)
3. 打开链接 → `cmd.exe start` (WSL 无浏览器, QDesktopServices 报 "Unable to detect a web browser")
4. 原子按钮 → 一键建三场景全链 (3场景+20技能+3结构条件+1SYS1+11action = 38节点)

## 坑 (已踩)
- **row_bg 名字区**: 背景名画在左侧 8-134px 竖排居中, 长名截断 → 名字 ≤8 字, 节点 x ≥ 背景x+160
- **load_flow_file 连线字段是 f/t** (不是 src/dst), 节点 id 任意字符串, 类型必须在 NODE_TYPES
- **NODE_TYPES 缺 data 类型** → add_node KeyError 加载中断 → 已补 data (icon 📊 color #58a6ff)
- **scene-api.php 500 = scenes 目录权限** → chown www:www (php-fpm 用户)
- **技能间距**: 56px 重叠 → 90px (节点高50); 场景行距 680 (7技能×90=630)
- **SYS1 共用**: 三场景结构条件汇聚 1 个 SYS1, 后接 A001~A010 action 节点群 + 📤汇总

## 场景 ID 映射
- SCN-01 → insert (插拔/老化箱/QSFP28)
- SCN-02 → handle (搬运/料盘/12槽)
- SCN-03 → aoi (检测/7位/2μm)

## L4 抗干扰 90° 演示场景 (gen_l4_demo_*, 2026-09-10 全链打通)
- **GUI 档位语义 v5.5.5**: 档位三档 L2/L3/L4; L4 = 90° 演示全链 (点 L4 ▶运行 = RealStateSpaceSim demo_l4 → L4Demo ①转台90°→②绕z抓横→③治具回正→④标准抓取→⑤插入49mm→⑥拔出→⑦AOI→⑧光耦合η=1.0, success 3/3 ~5600步~3min); 旧 L4D 档并入 L4 (cap_level "L4D" 归一 "L4"); 真实 L4 自主恢复(±15°干扰重试) CLI/测试可达
- **Sawyer 臂可达区坑 (4段全败根因)**: metaworld 场景设备坐标必须实测可达 (servo 残差法: 探针 palm 至目标, 残差>几mm=不可达); (0.30,0.30) 不可达 (palm 卡 y≈0.40, 残差100mm → ④试抓全败/peg钉穿盘 Δz-0.011); 转台用 (0.42,0.60) 可达(3mm) 且避 AOI 视觉区(0.12,0.62); 改动 gen_l4_demo_scene.py turntable body pos + gen_l4_demo_video.py TURNTABLE_XY 必须同改
- **指垫中心 ≠ 手掌原点** (垫在掌 +Y≈0.105): 抓取伺服目标 = 抓握点 − 指缝偏置 (pc−pad_mid−palm), 否则指缝落模块外 10.5cm; 闭夹后用 d.contact 查 pad↔peg 真接触 (防钉夹假"成功")
- **钉夹 pin 必须世界系偏移**: rel_pos 在世界系测得 → 钉回 = hand_xpos + rel_pos; hx@rel 遇手基座 −90°Y 旋转把 z 搅进水平 → peg 钉穿盘面; ②③ 历史路径(hx@rel)勿动, 新段用 self._pin_world=True
- **ensure_scene() 前置**: GUI 引擎委托 (_run_demo) 与 gen main 出片前必须重生成场景 XML (真实 peg 惯量), 旧/缺 XML → ④确定性失败
- **3D 呈现**: tr 通道 peg_yaw/hand_yaw/tt_yaw (0→90→0 旋转可见) + meta.demo_geom {turntable pos/r, coupler pos} → ss_dreamview 按此画转台/压电台
- **夹爪角度通道轴坑 (2026-09-10)**: hand_yaw 必须取手局部 **Z 轴** (col2, yaw0≈世界+X, 随绕z指令线性); 取局部 X 轴 (col0≈世界−Z=旋转轴自身) → XY 投影≈0 → atan2 噪声 ±180° 单帧跳变 (用户"夹爪乱动"实锤, 143 处 169°→−176°, 物理无此运动) — 旋转体朝向角永远别用与旋转轴平行的轴投影

## 场景库 + 页内 3D 场景编辑器 (2026-10-10, 老倪要"多个场景管理/一个编辑器/大窗口")

- **多场景管理**: `tools/scene_registry.py --build|--list|--check` 把真源落成**可编辑**场景目录
  `data/scene/scenes/<ID>/{objects3d,overlay_spec}.json` 并登记 `data/scene/scenes/index.json` 的 named_scenes:
  源 = `flows/scenes_5jobs.json` 6 作业场景 + 在役现场机位派生副本 (SCN-01-PEG 插拔场景)。
  现场场景只读 (派生副本才可编辑, 写后自检现场 sha 未变); 自带生成器的场景 (SCN-07-UP ← scene_build_updown.py)
  列 PROTECTED, --force 也不覆盖。轨迹航点从 steps 描述的显式坐标派生 (只给单轴 X=1.0 的写法: 缺轴沿用前一点并标 partial)。
- **元素 schema 必须过 scene_edit 的 NORM, 否则一编辑就报错**: 围栏 = `kind: box|polygon` + `shape{center,size}`
  (**不是** center/size_m — 写成后者 validate_fence 直接拒); 轨迹 `kind` 只认 `自定义/示教/规划` ("规划轨迹"无效);
  标记要有 `name`+`type`(工位/危险区/检查点/自定义)+pos。`scene_registry --check` 会拿 scene_edit.NORM 逐个元素验
  ⇒ 这才是"真可编辑性"判据 (本次就靠它抓出 5 个场景的围栏 schema 错 + 轨迹 kind 错)。
- **页内 3D 场景编辑器** `tools/gui/updown_scene_view.py` (QPainter 正交投影自绘, **不开第二个 GL 窗口**):
  四类元素通用选中模型 `sel = {"kind","i","wp"}`, 拖动改位置 (轨迹拖单个航点方块), 双击改数值/航点表,
  类型过滤 + 元素列表 ↔ 3D 双向联动 + 新增/复制/删除。**一个页面只挂一个编辑器** ——
  Sim&Real 页只挂它, 旧表格编辑器 `sim_real_page.build_body` 不再挂载 (该文件保留: dreamview_scene_edit 与测试
  仍复用它的 `_run`/`_EditDialog`)。
- **窗口要大 + 边沿可拖**: 视图与元素面板之间 `QSplitter(Qt.Vertical)` (handleWidth 9, 悬停变绿) —— 拖分隔条放大/缩小;
  视图 min 高 560 + Expanding; 另配「⛶ 视图全屏 / ⤡ 还原」。页内自绘视图字体/线宽: 选中 2px + 金 #ffc857 高亮。
- 🔴 **写回必须显式传 kind**: `view._write(patch, what, kind)` 默认 `kind="objects"` ⇒ 标记/围栏/轨迹的写入会**静默打到对象上**
  (回读"成功"但值没变)。回归测试里就吃过这个假绿, 已修。
- 🔴 在役 `data/scene/overlay_spec.json` 有**实时发布器**每轮刷 `ts/updated_at/l5live` ⇒ "在役场景未被改动"
  的判据**不能比文件 sha** (会假红), 要比语义内容 (排除这三个易变字段)。

## 仿真场景进场景管理 (画布 3D 视图那条「插拔光模块」, 2026-10-10)

- **仿真场景几何原本散在三处**、靠人工同步 (改一处不同步=物理与视觉不一致): ① `tools/gen_l4_demo_video.py` 的
  `TURNTABLE_XY/TURNTABLE_Z/COUPLER_XY/AOI_FOCUS` ② `tools/gen_l4_demo_scene.py` 注入 XML 的
  `<body turntable/coupler/cp_stage_b>` 坐标 ③ metaworld XML 的台面/光模块/夹具尺寸。
  ⇒ 收成真源 `data/scene/sim/sim_scenes.json` (工具 `tools/sim_scene_def.py`; 场景 id `SIM-PEG-L4`),
  两个生成器都改读它 (读不到回退老常量), 场景管理编辑 = 改这份真源 ⇒ 物理与 3D 同时变。
- ⚠️ 语义容易搞混的两个量: `TURNTABLE_Z` = "peg 坐盘面"(= 标记「来料位」z, 不是盘顶 z);
  XML 里 `cp_stage_b` 的 Z 是 **body 原点** (= 台面中心 − 局部偏移 0.004), 真源记的是台面中心。
- **判据 `sim_scene_def.py --check`**: 真源 ↔ 两个生成器 ↔ XML 注入**四处一致**; 已接真源后字面常量只作回退值
  (只提示不报错)。坑: 同一进程内多次校验必须 `importlib.reload(gen_l4_demo_scene)`, 否则拿缓存旧 EXTRA 假报错。
- **运行入口与环境必须与画布同一条** (否则 headless 渲染起不来或行为不同):
  `python tools/gen_l4_demo_video.py --also-latest`, **cwd = tools/**, env `MUJOCO_GL=egl` + `MUJOCO_EGL_DEVICE=0`
  + `PYTHONIOENCODING=utf-8` + `ZMAX_L4_ROOT=<repo root>`; 约 180s, 产物 `reports/ss_episode_latest.mp4`
  (+ 带时间戳的 `l4_demo_*.mp4` 与 `.npz` trace)。GUI 里跑要用 QThread, 否则卡界面。
- 实测已知结果 (2026-10-10): ①~⑥ 全过 (插入 48.7mm 真推入 / 拔出 54mm), ⑦ AOI 悬停时 **peg 滑脱** ⇒ success=False;
  这是 2026-09-10 已记的**旧问题** (悬停 60 帧 `step(zeros)` act[3]=0 不维持闭合力, 见
  `zmax-state-space-architecture/references/l4-demo-chain-debug-2026-09-10.md`), 不是新回归。
- 场景库 (tools/scene_registry.py) 现应含 8 个: 5 作业场景 + SCN-07-UP 上下料 + SCN-01-PEG 插拔副本 + SIM-PEG-L4 仿真场景;
  带 `run` 元数据的场景在下拉里标「▶可运行」。

## 场景管理只做两条 + 几何对齐 metaworld 真模型 (2026-10-10)

老倪: 「现在已有的场景是插拔场景，和上下料场景；其它场景先不用搞」+「需要对齐 metaworld 的场景渲染」。

- **手写几何必然跟模型跑偏 — 一律从 MuJoCo 模型导出** (`sim_scene_def.export_mujoco_truth`):
  载入 ▶运行 用的同一份 `sawyer_peg_insertion_side_l4.xml` → `mj_forward` → 遍历 geom 取
  **世界系** AABB (`d.geom_xpos` + `d.geom_xmat`; mesh 用 `m.mesh_vert` 顶点算), 滤掉机械臂/底座/屏/地面,
  每个对象标 `source=MuJoCo 模型实测 (body=.. geom=..)`。
  ⚠️ 两个实测真错 (手写版): 台面写成 0.8×0.8 实为 **1.4×0.8×0.054, 中心在 y=0.6**;
  光模块按 stock 写方截面实为 **侧插平放 长 0.24 沿 x · 截面 0.04×0.016**。
  site 真值 (`d.site_xpos`) 才是孔口/抓取点/目标点 (site:hole/pegGrasp/goal) —— 不要用推算值。
- **geom_size 语义**: sphere=[r]; capsule/cylinder=[r, half-length] (全长得×2, 别只拿来当长度); box=[hx,hy,hz]。
- **两种写路径别搞混**: 类方法 (`SceneView3D._write`) 用 `self.scene_id`; 页内闭包 (build_card 里的 add/del/toggle)
  用 `view.scene_id`。写成 `view.scene_id` 放在类方法里 ⇒ 拖动即 NameError, 启动阶段直接 core dump
  (实测把控制台崩掉一次; 判据盲区: 判据当时没直调类方法写路径)。
  判据要同时有「源码断言 (类方法不得出现 view.scene_id)」+「行为断言 (真建视图直调 _write 不崩)」。
- 场景清单白名单 `SCENE_WHITELIST = ("SIM-PEG-L4", "SCN-07-UP")` + `SCENE_LABEL` 中文名;
  其余场景的定义/文件都留着, 只是不露脸 ⇒ 要恢复只是改白名单, 不是重构。
- `data/` 在 .gitignore 里 ⇒ 真源/场景库 (data/scene/**) 不进仓库; 出厂能力由代码里的 `default()` / `ensure_episode_scene()`
  兜底, 提交只 `git add -A tools/ VERSION.md`。

## 把"正在跑的那条 episode"一模一样复制进场景 (2026-10-10)

老倪: 「你先把当前我运行的场景，先复制过来，一模一样的」「为什么没有机器人? metaworld 的场景都是有机器人」。

- **"一模一样"只能是同一帧, 不能是同一个 seed**。metaworld 的随机化布局吃**全局 np.random**
  ⇒ 另起进程 `make_env(seed)` 得到的是**另一个布局** (实测同一 seed 下 peg 差 5~7cm, 肉眼看像同一个场景但物理不是)。
  正确做法: episode 生成器把**首帧 `d.qpos`** 写进 npz `meta`; 复刻时 `d.qpos[:]=meta['qpos']; d.qvel[:]=0; mj_forward` 再导出。
  判据: `site pegGrasp == meta.peg0` 且 `body hand == tr['x'][0]` (1e-3 内) —— 两者都得核, 只核一个会漏。
- **机器人本体别过滤**。导出 metaworld 场景时只滤 `world/floor/mocap`; `pedestal/base/right_l0..l6/hand/rightclaw/rightpad/leftclaw/leftpad`
  全部保留, 给中文构件名 (机器人·大臂/小臂/腕1..3/夹爪垫左…) + `color` 浅灰 + `part="robot"`, 3D 视图里按 `obj["color"]` 上色。
  老倪会直接看画面问"怎么没有机器人" —— 元数据里 `objects3d.json` 必须真的带这些对象 (透传 `color`/`part`, 否则丢了白做)。
- **对象名必须唯一** (按**名字**计数打 `#2/#3` 后缀): 编辑器按 name 查找, 重名会让拖动改到别的构件身上。
- 导出时跳掉 `max(size)>1.0 且 z<-0.1` 的台体大块 (台面以下), 场景里看不见且压得视图发黑。
- 页内视图看小 = 三个数都不够: 最小高度 (现 780)、`fit_view()` 自适应缩放 (别写死 px/m)、以及"独立窗口"按钮 (直接最大化)。

## 页内"3D 场景"必须是真视图, 不能仿画 (2026-10-10)

老倪: 「sim real场景的页面，与 3D场景的页面不一样，要改成一模一样，就是同一个东西」
      「Sim&Real 改成 3D场景，就是一个程序」。

- "像"不是"是": QPainter 自绘就算几何全对, 老倪一眼看出是两套东西。**把同一个类 (DreamView3D) 嵌进页里**,
  再把编辑能力挂到它身上 (`dreamview_scene_edit.attach_scene_edit(dv)`: 场景下拉+对象列表+编辑/显隐/新增+右键+叠加层)。
- 🔴 **全进程只允许一个 GL 视图** (qt-gl 坑 1): 页里内嵌一个 DreamView3D 后, 任何"再开一个 3D 窗口"的入口
  (画布 `open_ss_3d`) 必须**复用**它 (拎成独立窗口 / setParent(None)+Qt.Window), 新建 = 第二个 GL 上下文 = 空白。
  实现: `ss_dreamview._LIVE/live_dreamview()/get_or_create_dreamview()`; 先查 `live_dreamview()` 再决定是否 new。
  先清点 `grep -rn "GLViewWidget(" tools/gui/*.py` 保证只有一处 GL 视图。
- 嵌入式验证要**带 DISPLAY 真渲染**抓帧 (offscreen 下 GL 可能空白 ⇒ 假绿/假红):
  `DISPLAY=:0 python 建页 → page.grab()` 数机器人浅灰/网格青绿像素; 结构判据 (实例数=1、is live_dreamview()) 可 offscreen 跑。

## 场景"看着没区别"排查顺序 + 单位/着色/叠加层三条铁律 (2026-10-10)

老倪: 「现在的插拔场景，和 摆盘场景，也没有啥区别，为什么一个是42对象，一个是47对象？」

排查顺序 (别先怀疑数据): ① 先在同一机位渲染两个场景, 量**帧差异像素** (真变了 → 差异百分比明显);
② 差异百分比很小或只差一块颜色 → 查**叠加层 (overlay) 到底画没画**; ③ 最后才怀疑数据。

- 🔴 **单位混用 (mm vs m) — 这次真祸根**: 同一套 `data/scene/scenes/<ID>/objects3d.json` 里,
  仿真/派生场景 (SS-EPI-CORNER / SS-TRAY-PLACE / SIM-PEG-L4) 的 size 是**米** (台面 1.4×0.8),
  而老的 SCN-* 场景是**毫米** (台面 140×140)。任何按尺寸画的地方若写死 `/1000.0`, 米制场景的对象
  就被缩 1000 倍 = **数据/列表在变, 画面完全不变** (肉眼看就是"两个场景一样")。
  正解: 按文件量纲自动判定 `_scale = 1/1000 if max(size) > 10 else 1`, 别写死一种单位。
- 🔴 **叠加层别与实体同几何**: 3D 视图自己已经画的实体 (台面/护栏/机器人/摆盘两只盘) 再叠一层实心盒
  → z-fighting + 糊色 (实测台面绿 114k px 被压到 5k), 颜色全认不出来。
  正解: 叠加层 = **12 条棱的线框** (`_bbox_lines` + `GLLinePlotItem` + `setGLOptions("additive")`, 不参与遮挡),
  且**跳过视图已画的那些对象**, 只标视图没画的对象 (夹具/孔座等)。
- 🔴 **颜色要认得出就别用有光照着色**: `shader='shaded'` 下乳白 0.96 实测渲成中位色 (49,48,46) 深灰
  ⇒ "乳白色桌面"根本看不出来。要按定义呈现颜色 (防静电胶皮绿 / 办公桌乳白) 就用 `shader=None` 平涂。
- **桌面按场景配色**: `ss_dreamview.table_color(scene_id)` — 插拔系 (SS-EPI-CORNER / SIM-PEG-L4) = 防静电胶皮绿
  (0.20,0.52,0.30); 摆盘 (SS-TRAY-PLACE) = 办公桌乳白 (0.96,0.94,0.90)。切场景时 `_table_item.setColor(...)` 即时换色。
- **场景形态分叉用 `scene_mode(scene_id)`** (tray / plug), 而不是到处 `if "TRAY" in name`:
  摆盘场景不画插拔几何 (带孔盒/孔口/插入终点/AOI 相机/动态光模块), 盘件按真源实体渲染。
- **盘件几何单一真源** = `sim_scene_def._tray_layout()` (料盘 = 黑塑料托盘无盖无槽位 + 里面 3 个光模块;
  tray盘 = 同外廓 + 2 块隔板分出 3 个固定槽位); 渲染侧只 import 它来画, 绝不各写一份坐标。
- **数据存档**: `tools/scene_data_snapshot.py` 把 `data/scene` 打成带逐文件 sha256 的归档到
  `zmax_data/snapshots/scene_<时间戳>.tar.gz` + `MANIFEST_*.json`, `--verify` 回读校验 (data/ 不入库,
  现场编辑过的场景必须有可校验存档)。

## 盘件在深色背景上认不出 / 盘件要完整入画 (2026-10-10 扑实)

老倪：把AOI相机换成料盘…插孔换成另一个 tray盘。做完了但**他/视觉核对认不出**:
「只辨得出一处深色承载面」「隔板与 3 个空槽位都不可辨认」「右侧被看成一条扁平棕色长条」。

- 🔴 **黑塑料盘放在近黑背景前 = 看不出形状**。小盘 (外廓 86×102mm / 壁厚 6mm) 更是只剩一坨。
  正解: 外廓 → ≥100×110mm、壁厚 10mm、壁高 24mm；并**加一块中灰内底** (0.30,0.30,0.33)，
  黑壁+灰底才能看出"盘是凹的"。只改壁厚不改内底 → 仍然一坨黑。
- 🔴 **盘件位置必须用投影实测定"入画"，不能靠眼睛看图**: 目标对象 8 角投屏，要求
  `0≤min(x)` 且 `max(x)≤W` 且 `0≤min(y)` 且 `max(y)≤H` (当前机位视口 714×804)；两个盘还要
  **屏幕框不重叠**。实测原 (0.12,0.62) 左缘 -287px 画外、(0.2645,0.4623) 被台沿遮→ 两个都不可见。
- 盘件与工件的坐标要对得上: tray盘 隔板分出的 3 槽中心 (0.5275/0.560/0.5925) 应与 3 个光模块
  (0.53/0.56/0.59) 重合 —— 摆盘语义就是"正好落进槽里”，差几毫米就会看着像碦在隔板上。
- ✖ 2 轮调几何还认不出就**别再调** (老倪规矩: 迭代不超 2 轮): 改加**编号标签/条纹**这类语义标记。
- 同时查一下**叠加层是不是压在实体上** (同几何 → 糊色): 视觉把 tray 盘看成"带绿色描边的深棕色长条"，
  高度疑似光模块 peg 的叠层线框盖在盘上。

## 3D 视口 ↔ 清单 双向点选联动 (2026-10-10)

老倪: 「对象与场景的元素很难用眼睛区分对应上，增加功能，用鼠标点选场景的元素后，能对应场景编辑的
文字条目，或者选择场景的文字，场景的对应元素也高亮显示」

- 🔴 **pyqtgraph 0.14 不能直接调 `GLViewWidget.projectionMatrix()`** —— 签名是
  `projectionMatrix(region, viewport)` (带参), 旧版无参写法一律 TypeError。正解: 按 GLViewWidget 本体公式**自建**:
  `near=dist*0.001, far=dist*1000, r=near*tan(fov/2), t=r*h/w` 拼 P; V 用 `QMatrix4x4` 依次
  `translate(0,0,-dist)` → `rotate(elev-90,1,0,0)` → `rotate(azim+90,0,0,-1)` → `translate(-center)`, 再
  `np.array(tr.copyDataTo()).reshape((4,4))` (**copyDataTo 是行主序**, 别用 order='F'); `M = P @ V`; 屏幕 = NDC 映射。
- **命中判定用"投影中心离点击最近"而不是"投影面积最小"**: 面积最小的直觉对"大件上叠小件"成立, 但
  相邻同类件 (3 个并排光模块) 面积完全相同 → 会选错。得分 = (中心距, 深度, 面积) 字典序; 框内都没命中时
  才用 30px 内的最近中心兑底 (兑底太大反而"点空白也选中隔壁")。
- **点选与转视角必须分开**: 只在 `MouseButtonPress/Release` 位移 ≤3px 时才算点选, 否则放行给相机
  (否则一拖就选)。同一个 eventFilter 里已有右键 ContextMenu 分支, 直接扩展。
- **高亮框要自己画一个**: 叠层线框只含"视图没自己画的对象" (夹具等), 而盘件/机器人/台面是视图画的 →
  只改叠层颜色的话点机器人没有任何反应。正解: 维护一个专用亮黄 `GLLinePlotItem` (additive), 按对象 8 角画框;
  连同叠层线框一起点亮 (先存原色, `clear_highlight()` 还原)。
- 清单侧回写要 `blockSignals(True/False)` 防回声; 两侧走**同一条** `highlight()` 路径, 保证永远一致。
- 回归: `tools/tests/test_scene_pick_link.py` (需 `DISPLAY=:0` 真渲染) —— 点选命中 (允许世界距 ≤40mm 的
  紧邻/上层件) + 双向高亮 + 点空白不崩, 两场景各跑一遍 (实测 26 过/0 败)。
  注: 同一进程连建两个场景 = 两个 GL 视图 → 会刷 "Error while drawing item", 属单 GL 视图约束, 不是缺陷。

## 高亮框与渲染"对不上"的根因: 视图自绘对象用的是**遗留硬编码** (2026-10-10)

老倪: 「为什么场景的高亮显示跟渲染出来的图像对不上? 例如选择了 工作台面, 高亮的方框比实际的绿色桌子大很多」

- 根因不是偏移也不是单位, 是**两个来源**: 高亮框读场景真源 `objects3d.json`(metaworld/MuJoCo 实测,
  台面 1.4×0.8×0.054 @ y=0.6), 而 3D 视图的桌面是 `ss_dreamview._TABLE_SIZE=(0.92,0.62,0.024)`
  (当年为插拔场景手搓) ⇒ 框比桌子**宽 52% / 深 29%**; 两者的**顶面同高 (z=0)**, 所以看着就是"框比桌子大一圈"。
  旁证: 台面护栏(真源 1.4 长)本来就探出那块 0.92 桌子的边 —— 桌子偏小是长期存在的。
- 修法 = 收成单源: 新增 `ss_dreamview.scene_table_truth(scene_id)`, 读 `$ZMAX_SCENE_DIR/objects3d.json`
  里"工作台面"的 center/size, 画桌子时优先用它 (无/毫米制 ⇒ 回退老常量)。
  🔴 **只对米制场景生效**: 老 SCN-* 现场机位场景的台面是**毫米**深度数据且与真实机位投影对齐 (SCN-01-PEG
  台面 428.7×653mm), 直接套用会把桌子挪位/缩小 ⇒ 判据沿用 `_unit_scale` 的思路: `max(size)>10 ⇒ 毫米 ⇒ 不动`。
  改完复采: 绘制盒 = center[0,0.6,-0.027] size[1.4,0.8,0.054] == 真源; 真渲染抓帧绿桌像素 25970 → 53330。
- 取证坑: ①`GLMeshItem` 在 pyqtgraph 0.14 **没有 `meshData()`** ⇒ 别想从 item 反量几何,
  用 **spy 包 `_box_mesh`** 抓"真正喂给几何生成器的 center/size" (最直接);
  ②抓帧数像素要**多等几帧 processEvents** 再 grab, 同一份代码两次跑能差一倍 (25970 vs 53330, 首帧未渲染完) ⇒
  像素数只能当佐证, **判据用几何数值**;
  ③`attach_scene_edit` 的 `_project` 对**宽盒/近相机平面**会给出画外数字 (实测 10k px 的假值) ⇒ 别拿它量尺寸。
- 同类未收口 (视图仍自绘常量, 选中时框与实体仍会有差): 红色带孔盒 (`_BOX_SIZE` 0.19/0.2/0.19, 真源 peg_block
  0.2×0.2×0.2 @(-0.3,0.6,0.1)) 与**机器人手臂** (视图是 `_ARM_L1/_ARM_L2` 简化杆, 真源是 MuJoCo 各连杆 AABB)。

## 侧栏 / 视图内面板折叠 (3D 场景要"别挡视线")

老倪 2026-10-10: 「动作调制器 八阶段状态机这个窗口影响观察, 要做成可以向左折叠缩小的窗口;
场景编辑·图层这两个侧面栏也要能向左侧折叠隐藏, 不要遮挡视线」

- **通用折叠外壳 `ss_dreamview.CollapsibleSide(name, body)`**: 左侧一条 22px 折叠条 (◂/▶ 按钮 + 竖排标题)
  + 内容框=原面板。折叠 = `body.setVisible(False)`; 展开标签/宽度不变, 只是收掉内容。
  用法: `panel` 照旧建 (它自己 `setFixedWidth(230)`), 外面套 `CollapsibleSide("图层", panel)`, 把**外壳**加进布局。
- 🔴 **只 `setVisible(False)` 不会把宽度还给 3D 视图** (实测折叠后外壳仍占 255px)。
  必须在 `apply()` 里显式钉宽: 折叠 → `setFixedWidth(22+3)`; 展开 → `22+3+内容框固定宽`。
- 🔴 **展开宽不能用 `body.sizeHint().width()`** —— 那是内容想要的宽 (实测 374px), 会把侧栏撑得比原来还宽。
  取**内容框自己的固定宽** (`minimumWidth()==maximumWidth()` 时用它, 否则 sizeHint)。
- **视图内面板 (八阶段状态机阶梯) 折叠**: `LabelOverlay` 记录每帧画的 `_panel_rect`, 展开时右上角画 ◂
  (命中区 20×20), 折叠时整条都是命中区 (点哪都能展开); `DreamView3D.fsm_panel_toggle_at(x,y)` 翻转
  `_fsm_folded` 并在下一帧把完整行压成一行「🧭 动作调制器 6/8 转移 ██░░ 13% 预计 0.64s」。
  实测 14 行/306px → 1 行/33px。
- 🔴 **点这个按钮不能同时触发点选/转视角**: ①`DreamView3D.eventFilter` 里命中就 `return True` (不转视角);
  ②`SceneEditAttacher.eventFilter` 的 MouseButtonPress 分支**先**问 `dv.fsm_panel_toggle_at(...)`, 命中就消费
  (它后安装、先收到事件 —— 不在那里拦就会顺手把一个对象选上)。
- 面板折叠状态落 `QSettings("ZMAX","studio")` 的 `ui/pane_<名>_folded` (收起一次, 下次开控制台还是收起的)。

## 回归测试的口径会烂: 改口径必须同改判据 (2026-10-10 实採)

`tools/tests/test_sim_real_3d_scene_view.py` 从 v5.39.6/5.39.7 (场景下拉收敛成两条) 起就**一直是红的**:
它还在断言"下拉三条 (3D场景/插拔/上下料)"、"下拉含 SIM-PEG-L4", 而 `_opts` 只剩 2 条 ⇒
第 297 行 `_opts[2][0]` 直接 IndexError **崩在测试自己身上**, 后面的 90 多条判据根本没跑 ——
表现是"这条测试没人跑得完", 而不是"红在哪一条"。
- 定式: 改下拉/白名单/命名这类**口径**时, 顺手 `grep -n "旧名字" tools/tests/*.py` 把断言一起改; 否则几轮之后没人知道这条测试还算不算数。
- 排查时先看**测试是不是自己崩**(traceback 行号在 test 文件里) → 是则先修断言再谈被测代码。
- 实测修完: 92 过/0 败 (另有 `test_scene_pick_link.py` 26 过/0 败)。

## 🔴 切场景"只换数据源" ⇒ 画面几何冻在启动那一刻 (2026-10-10 实採)

老倪: 「原来的插拔场景, 你怎么给搞没了? 现在跟摆盘场景都一样了」

- **现象**: 点「🧩 插拔」/「🧩 摆盘」只看到桌面颜色换了, 桌面上的几何 (带孔盒/AOI vs 料盘/tray盘)
  一点没变 ⇒ 看着"两个场景一模一样"。
- **根因**: 场景专属几何在 `_build_scene()` 里按 `scene_mode()` 分叉建一次, 而 `_switch_scene()` 当时只做了
  ①设 `ZMAX_SCENE_DIR` ②换桌面色 ③刷对象叠加层 —— **没有重建几何** (作者的假设错: 以为叠加层就是场景)。
- **修法**: 切场景后显式 `self.scene_id = scene_id; self._build_scene()` —— `_build_scene()` 本来就是
  **幂等全量重建** (开头按 id 去重 removeItem 全部 + `_gl_items.clear()`, 尾部重贴图层开关),
  也正是「🔁 重建 3D 视图」按钮调的钩子 (`dreamview_scene_edit.rebuild_view` → `dv._build_scene`);
  重建后再 `_update_frame(slider.value())` 把当前帧重画一遍。
- 🔴 **`self.scene_id` 从来没有赋值过** (类里只有 `getattr(self, "scene_id", None)`) ⇒ `scene_mode()`/
  `table_color()`/`scene_table_truth()` 实际上全靠 `ZMAX_SCENE_DIR` 环境变量判定。切场景只改环境变量而不
  刷新 `self.scene_id` 时, 任何"按场景分叉"的东西都会拿到旧值 —— 切场景时两者要一起改。
- **取证要到真渲染级** (先例): ①场景层 item 数/颜色 (插拔 8 项含红盒 `(0.95,0.22,0.14)`; 摆盘 18 项含内底灰
  `(0.30,0.30,0.33)`) ②**可见性差分**: 把目标 item `setVisible(False)` 前后各抓一帧, 数变化的采样点
  (实测摆盘 1806 / 插拔红盒 3871 ⇒ 真画在屏幕上; 切回后红盒差分 0) ③重建不堆叠: 切换后的项数 ==
  新建一个同场景视图的项数。
- ⚠️ **别按颜色数像素当判据**: "环境接触"橙红球 `(1.0,0.45,0.10)` 与红盒一样是"红高、绿蓝低",
  实测两个场景都能数出 ~970 个"红"像素 (球本体) ⇒ 颜色阈值分不出"哪个场景"。

## 验证
- offscreen: `load_flow_file` 后断言节点/连线数 + data×2 + row_bg×4
- 公网: `urllib` POST scene-api.php 3 端点 HTTP 200 + 保存文件可读
- base64 JSON 参数: b64u 可逆 + 页面含 renderJsonDesc
