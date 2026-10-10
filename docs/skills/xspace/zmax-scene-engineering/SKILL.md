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

## 验证
- offscreen: `load_flow_file` 后断言节点/连线数 + data×2 + row_bg×4
- 公网: `urllib` POST scene-api.php 3 端点 HTTP 200 + 保存文件可读
- base64 JSON 参数: b64u 可逆 + 页面含 renderJsonDesc
