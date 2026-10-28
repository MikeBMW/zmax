---
name: ar-multicam-scene-tagging
description: Use when AR 换底图源/多相机/L5理解/信号场景色标与排序。
version: 1.0.0
author: Hermes (Z-MAX)
license: proprietary
metadata:
  hermes:
    tags: [ar, camera, vlm, signal-analysis, zmax]
    related_skills: [fixed-camera-ar-overlay, zmax-console, state-space-canvas-engineering]
---

# AR 场景多相机底图 + 信号场景色标

## When to Use
老倪要换 AR/3D 场景的**底图数据源**、把多台相机接进 AR、让 **L5(VLM) 理解**当前画面,
或要给**信号分析**的信号打场景色标/按色排序时, 用本技能。

## 触发
- 「AR/3D 场景的背景真实图像应该是 XX 数据源」/「这几台相机都照同一个场景」/「L5 的 VLM 能理解么」。
- 「信号分析里的信号属于哪个场景, 要标记出来」/「按 绿/蓝/紫/白 排序, 白=全部显示」。

## 1. 底图源 = **已有视频源, 不要另起相机**
Z-MAX 的「视频数据源」单一真源是 `tools/cam_live_stream.py`(8791 推流 / 8793 工位总览同源)，
AR 服务 `tools/tcp_ar_server.py`(8797) 只**订阅**: `CAMS[key] = {w,h,label,mjpg:'/<name>.mjpg',src:'sstate'|'usb',stats_key}`。
- 每台必须登记**实际分辨率**(标定点是像素量纲, 混用必错); AOI 路在 8791 `/stats` 里的键是 `aoi_*` ⇒ 用 `stats_key` 映射。
- 端点: `GET /api/cams`(来源/分辨率/在线/帧龄/fps/标定) · `GET /api/ss_stats` · `GET /snap/<key>.jpg`(rs 走本机 pipeline, 其余走 8791 快照) · `/cam.mjpg?c=<key>`(MJPEG 透传)。
- 帧龄/在线**只从真源读**(8791 `/stats`), 不在 AR 侧重算; 哪路停就照实显示(实测遇过 USB 内置相机停 10h)。
- 3D 场景「🥽 AR」按钮开 `?cam=<default>`, 别写死某一台; 开关前先探 `/api/cams` 并报「在线 N/M」。

### 1.1 AR 入口必须**非阻塞**, 且画布工具栏直接给入口 (2026-10-19 实测)
老倪: 「3D场景里点 AR, 半天没反应 —— 把 AR 做到画布上边的按钮直接打开」。
根因不是服务坏, 而是 **整条流程跑在 GUI 主线程**: 切场景(子进程 30s) → `ar_ensure_service`(12s)
→ `ar_open_url` 逐个浏览器候选**各等窗口 6s** ⇒ 界面冻住, 用户看不到任何反馈。
定式 (已落地 `tools/gui/ss_dreamview.py::ar_launch`):
- **统一后台入口** `ar_launch()`: 加锁防连点; 返回 <10ms; 界面只负责显示状态。
- 顺序要按「用户多久看到东西」排: ① 快探 8797(0.8s) 在跑就**立刻 spawn 浏览器**
  (只 `Popen`, **不等窗口** —— 等窗口就是那 6s) ② 没起才先报「正在启动服务」再拉起
  ③ 切场景(数据源是「真机」时不抢用户设置) ④ 读 `/api/cams` 报在线/帧龄。
- 跨线程回贴用 `pyqtSignal` (`ar_status_bus()`), **绝不在后台线程直接改控件**。
- 入口两处同源: 画布工具栏 `🥽 AR` (`simulink_module.open_ar_page`) 与 3D 场景按钮都调同一个 `ar_launch`,
  否则两处行为会漂 (一个快一个卡)。
- 判据必须量**耗时**而不是“能打开”: `open_ar_page`/`ar_launch` <300ms + 2s 内出现「页面已送出」
  + 防连点第二次返回 False + 场景映射用 `ss_scene_switch --check`(**只算不动**, 别改用户当前数据源)。

### 1.2 多屏：AR 窗口默认开在**另一块屏**，用户看到的就是“没反应”
实测（老倪工位，2026-10-19）：`xrandr` 是 eDP 主屏 `0+0 1920x1200` + HDMI `1920+0 1920x1080`；
控制台在**左屏**（x=66），spawn 的 AR 窗口却在**右屏**（x=1934）——窗口 0.4s 就出来了,
但他盯着左屏，所以“点了半天没反应”。
定式（`ar_place_near_console`，已落地）：
- 开完**必须**搬：用 `xrandr --query` 取屏原点、`wmctrl -lG` 取控制台(“XSpace ZMAX”)几何，
  窗口中心不在控制台那块屏 ⇒ `wmctrl -i -r <id> -e 0,x,y,w,h` 搬过去（屏原点+60,+70，
  尺寸 min(屏宽-120,1500) x min(屏高-140,980)），再 `wmctrl -i -a` 抬到最前。
- **复用不叠窗**：已有 AR 窗口就直接搬+抬（顺手相当于“再点一次置前”），不再 spawn；
  否则连点几下会向右屏叠出一堆窗口。
- 别信 spawn 的返回码：`ar_window_seen()` 查真窗口表才算数；抬完再查一次位置写入判据。
- 判断环境别用 `\$DISPLAY` 猜：判据要用 `DISPLAY=:0` 真跑 `xrandr`/`wmctrl`，否则 RPAREN。

### 1.3 「AR 按钮打不开」= 浏览器**静默退出**, 不是服务/页面坏 (2026-10-20 实测)
老倪: 「ar按钮 打不开 http://10.163.146.78:8797/ar」。取证顺序(照这个顺序查, 一步都不能少):
- 先证服务与页面是好的: `ss -ltnp | grep 8797` + `curl -o /dev/null -w '%{http_code}' :8797/ar` (200) +
  `:8793/ar` (302→8797)。**页面 97KB 正常返回 ⇒ 别再动服务**。
- 再查 `zmax_data/logs/ar_launch.log`: 若 `spawn pid=…` 有、后面 `窗口 没出现`, 就是**浏览器层**问题。
- 决定性判据 = 浏览器 History 里有没有这一次访问: 拷 `Default/History` 出来查 `urls.last_visit_time`。
  实测 5 次点击 **History 里 0 次访问** ⇒ 进程起来了但页面根本没加载(不是窗口跑到别的屏, 也不是标题没解析)。

两个真根因(都已落地修法, `tools/gui/ss_dreamview.py`):
1. **失效单例锁 ⇒ chromium 静默 exit 0**: profile 里 `SingletonLock -> ubuntu-<pid>` 的 pid 已死或被复用,
   chromium 以为"已有实例", 把 URL 转发给不存在的实例后**直接退出**(无窗口、无 stderr、History 无访问)。
   修法 `ar_clean_profile_locks(prof)`: 只在锁里的 pid **不是浏览器进程**(`/proc/<pid>/cmdline` 无 chrom)时
   删 `SingletonLock/SingletonSocket/SingletonCookie`; 活着的浏览器锁一律不动。
2. **只按窗口标题判"没出现"会漏**: 页面还在加载时标题就是 URL, 标题里没有「TCP 轨迹/AR/VR」⇒ 判失败。
   修法 `ar_window_ids()` 取 spawn **前后快照** + `ar_wait_new_window(before, t)`: 先认标题, 再退一步认
   "任何新窗口(标题含 chrom/8797/8793)"。
- 兜底三级(顺序不能变): 快路径(共享实例, 0.38s) → 独立 profile(`zmax_data/ar_browser`) →
  **全新带时间戳 profile**(`ar_browser_MMDD_HHMMSS`, 必无锁) —— 最后一级保证窗口一定开出来。
- chromium stderr 必须落 `zmax_data/logs/ar_browser.log`(原来 DEVNULL ⇒ "为什么没出窗"全靠猜)。
- 打不开之后别急着重启服务: 服务侧 200 就与它无关; 真改的是控制台进程里的代码 ⇒ **控制台要重启一次**才生效
  (`tools/restart_studio.sh`, 单次, 别反复重启)。
- 判据脚本 `tools/verify_ar_button.py` 里那条页面地址断言要跟 `AR_PAGE_URL` 同步(现为 8793/ar 或 127.0.0.1:8797/ar),
  否则改了地址就假失败。

## 2. L5(VLM) 理解 = **子进程桥**, 别在常驻服务里 import 引擎
引擎 `src/lerobot/policies/left_right/state_space/scene_vlm.py :: SceneVLM.ask(jpg, prompt, max_tokens)` 会拉 torch(GB 级);
AR 服务是常驻轻进程 ⇒ 进程内 import 会顶内存红线(本机同刻只允许一个模型进程)。
做法: `tools/ar_l5_understand.py --jpg <f> --w --h [--hint]` 打印单行 JSON, 服务侧 `subprocess.run(..., timeout=380)` 解析;
提示词/解析复用 `tools/gen_overlay_from_vlm.py` 的 `PROMPT/parse_json`(口径一致)。
- 引擎路径是 `src/lerobot/**policies**/left_right/state_space/scene_vlm.py`(漏 `policies` 会 "找不到 scene_vlm.py")。
- key 走 `DEEPSEEK_API_KEY`(env 或 `~/.hermes/.env`)→ 默认 `https://api.deepseek.com`, model `deepseek-flash`。
- **400 "unsupported image" = 喂进去的不是真 JPEG**。上游报错时 `/snap/<k>.jpg` 会返回 JSON 错误体; 服务侧必须校验魔数 `\xff\xd8` 再调模型。

### 2.1 判小目标先裁区域放大 + 采信纪律 (2026-10-14 实测)

- **小目标(槽内工件/局部缺陷)必须先把该区域裁出来放大再判**。同一帧 640x480:
  全图判「托盘槽内光模块」只报 **1 颗 / conf 0.6**; 把托盘区 `crop((400,200,640,410))`
  放大 3x 后报 **2 颗 / conf 0.82, 0.80**, 且延迟从 **64.7s 掉到 4.6s**(图小 ⇒ 更省时也更准)。
  ⇒ 别拿全图问「有几颗」, 裁到 200~700px 见方再问。置信度低不等于不确定, 常常只是目标太小。
- **VLM 的颜色/材质描述必须像素复核后才能进结论**。并行的独立子代理称槽内是
  「亮绿色扁片带银色条」——像素复核直接否掉: 全图绿色像素仅 62~100 个(0.02%),
  右侧区主色清一色灰阶(48/96/144/192)。光模块是**银色金属壳**, 本来就不绿。
  判据手段: HSV 按色带统计 + 连通域计数(几行代码定案), 别用形容词对形容词。
- **不采信 VLM 对「机位/视角」的推断**。它把本机 **USB 相机**帧说成「机械臂末端视角」——
  机位是外部事实(哪路 = 哪个 URL/哪个 key), 只在桥侧登记, 不由模型猜。
- **多源交叉 = L5 全图 + L5 特写 + 像素统计 + 独立子代理**; 四者一致才写进交付结论,
  不一致的逐条标「不采信」并给出否定依据, 连图带数字存证进 manifest 供回看。
- 引擎依赖: `tools/ar_l5_understand.py` 要 `huggingface_hub`; 系统 `python3` 与 `venvs/gs-venv`
  都**没有** ⇒ 用 `gui-venv311/bin/python` 跑(实测 OK)。报错长相:
  `引擎不可用(import 失败): ModuleNotFoundError: No module named 'huggingface_hub'`。

## 3. 信号 → 场景 标签(色标 + 排序)
- 颜色/任务映射**只能有一份**: `tools/ss_scene_switch.py`(插拔 `#2e8b57` / 摆盘 `#1f6feb` / AR `#8957e5`), 3D 按钮、配置中心场景列、信号分析全从它取。
- 标签真源 `tools/sig_scene_tags.py` → `config/topics/scene_tags.json`; 打标证据: AR/AOI 注册表 + **任务启用节点的名字前缀**(信号名约定 `节点名.字段`, 节点名要剥 emoji/括号)+ 运行产物 + 人工 overrides。
- UI(`tools/gui/canoe_graphic.py`): 目录项加 `● `(场景色)/`○ `(未分类白); 排序行四钮 ⚪全部/🟢/🔵/🟣, 选色=该色置顶(其余压暗仍显示), 白=不排序全显示; 标题行报当前数据源场景 + 各色计数。
- **没证据的分类就不要编**: 宁可留在白色(未分类)并在标题行报数, 也别猜。
- 统计实时 store 时要 `list(bufs.keys())` 快照 —— 源线程同时在加键, 直接迭代会 `RuntimeError: dictionary changed size during iteration`。

## 3.1 造修过的三个真坑 (2026-10-12 老倪目检发现的)
- **整组信号看不到**: 信号目录里某一段被套在 `if not only3d:` 里, 而窗口默认「数据范围」=3D 场景实时数据
  ⇒ 那一整组(AOI/AR 176 条)被挡在门外。用户只会说「那些信号也没有啊」。
  教训: 用户点名的信号组 **不要与“数据范围”开关耦合** —— 一律列出。加组前先问: 默认开关下他能不能看到?
- **颜色不生效**: 标签真源里只打上了一部分场景(AR 176 条, 插拔/摆盘 0 条), 其余 UI 再对也是白。
  开工前先 `SST.summary()` 看各场景条数, 0 条就说明“分类依据”还没拿到。
- **`_walk_keys(obj, acc, ...)` 收的是 dict(`acc.setdefault`), 传 set 会被 except 吞掉**
  ⇒ universe 静默为空, 打标 0 条却看不到任何报错。收集键时用 `dict` 再 `set(acc)`。

## 3.2b 真机量(位姿/力)进 AR 紫组的硬口径 (2026-10-20 实测)
老倪: 「AR 场景的末端执行器 x y z 和 插拔的侧向力, 显示出来, 来自于真实的机器人; 现在没有接」。

- **真机六维力走 xCoreSDK, 不必等 Orin**: `robot.forceControl().getEndTorque(FrameType.world,
  jtm, etm, ctq, cfo, ec)`, 4 个输出参数是 `PyTypeVectorDouble`(用 `.get()` 取 list), `cfo` = 笛卡尔力 [N]。
  采样器 `tools/rokae/ft_direct_sampler.py`(cpython-310 ⇒ ros:humble-ros-base 容器, 与 `tcp_direct_sampler.py`
  同套连接/落盘), 只读、不调 fcStart。
- **侧向力只在基座系算**: 插入轴 = base +x ⇒ 侧向力 = `hypot(fy, fz)`。工具系下算侧向力是错量 ⇒ 采样器拒绝
  `--frame tool`, 总线侧再拒一次(`frame not in world/base → 不写键`)。
- **名字里不许出现「插入/插拔」**: `sig_scene_tags` 关键词表会染成插拔绿; 用 `轴向力`/`侧向力`。
  注册表键在 `build()` 里**后置写入** ⇒ 注册表内的信号一定 AR 紫(关键词抢不走)。
- **`network: network connection` = 网卡不在位**, 不是 API 错: 先 `ip -br addr` + `ping 192.168.23.160`。
  控制器 SDK 会话是共享资源(动作链 agent / 位姿采样器都在连) ⇒ 开力采样器前先 `--probe` 一次。
- **取不到就不写键**: live 里没有 fx/fy/fz 这一帧 ⇒ 五条力通道一条都不写, meta 里留「未接 + 采样器最后错误」。

### 3.2c 信号目录必须同时显示「声明」与「在跑」
- 树原只按 `store.bufs` 建行 ⇒ **真机没接时那一路通道在窗口里整行都不存在**, 用户看不出"有这个信号只是没数据"。
  定式: `注册表(config/topics/ar_aoi_signals.json) − live = 未接占位行`(紫淡显 alpha150 · 不可勾选 ·
  值列写「未接」· tooltip 给来源), 组标题带 `声明 N · 在跑 M · 未接 K`。**绝不用 0 冒充**。
- 占位行只给**核心信号**(SPEC); 台账点位(金手指点/侧面点/准备点/安全点/空间点/GUI测试点)不铺 —— 几十行淡字会塞满窗口。
- `live["groups"]` 必须对**每个真在发的键**用 `group_of(k)` 算, 不能只写 `KEYMAP`(SPEC) ⇒ 否则台账点位
  (光模块插入口.x 等)没有组名, 窗口只能丢进「AR 场景 · 其它信号」, 与注册表组名对不上。
- 验收脚本 `tools/verify_ar_force_signals.py`: 真起 CanoeGraphicWidget(offscreen) 真建树, 核 ①根节点 #8957e5
  ②末端 x/y/z 有真值 ③力四行在组内 ④未接时值列 = 「未接」而非 0; 另带 `--selftest`(合成 3-4-5 直角验
  hypot/闸门, 明确标"非真机数据", 跑完删文件) —— 无硬件也能证换算对。还核 ⑤默认只有 1 个场景根、树上行数 ≤10
  ⑥取消「主要信号」后回到全量(431 行) 且全量里能看到 y/z 分量/切向力。

### 3.2d 信号目录默认收口到 ≤10 条「主要信号」 (2026-10-20)
老倪: 「不要打开那么多信号, 没有用, 还看不清; 只要有位姿等主要信号, 不要超过 10 个」。
- 定式: 模块级 `CORE_SIGNALS`(10 条) + `CORE_GROUP`; 顶部可勾选按钮 `🎯 主要信号 (10 条)` **默认勾上**,
  取消勾选 = 全量(56 条 AR + 台账点位 + ROS/DDS) —— **不是删数据, 只是显示口径**。
- 选的 10 条必须**全是真机量**: 末端 x/y/z + vx/vy/vz(真值差分) + 轴向力/侧向力(六维力) + 两条帧龄。
  ❌ 不要把平台自算的 `末端.切向力_N`(DDS ss_force_l2 前馈)混在“主要力”里 —— 与真机力放一起会被当成同一个量。
- 核心模式要同时收三处, 漏一处就“树清靜了但波形还是几十条”: ①树只建 CORE(其余场景根 takeTopLevelItem 移除)
  ②`self.selected` 剪到 CORE ③`_apply_default_selection` 只补勾 CORE(有数据的)。
- 全部视图的入口必须可见可点(勾选框本身), 否则就变成“以前能看到的东西没了”。

### 3.2e 场景一选, 波形必须**马上**跟着切 (2026-10-20)
老倪: 「我都选择 AR 场景了, 怎么右侧还是显示绿色的插拔场景信号? 应该马上切换到 AR 场景」
根因三条叠在一起, 少改一条都不行:
- 原来的场景四色按钮**只排序**(该色置顶/其余压暗), 从不改"画哪几条" ⇒ 勾着的一堆 sstrace(绿)永远在右侧。
- 波形颜色 = `SST.tag(key)` 给的场景色 ⇒ 不换曲线就永远绿。
- 树重建的触发条件只有「键集合指纹变」+1.5s; **切场景不产生新键** ⇒ 目录/默认勾选根本不会重建。
落地定式(三处收口):
- `_prune_to_scene(scene)`: 把 `self.selected` 里标签**不属于该场景**的键立即撤掉(只动曲线, 不动数据)。
- `_set_scene_sort(val)`: 点了具体场景 ⇒ 先 prune 再 `_fill_tree()`。
- `_tick()` 里单独 **0.5Hz 探场景**(`_active_scene()` 要读画布数据源, 别每帧读文件): 变了就 `_fill_tree()`;
  这样“在画布/3D 切了数据源”也自动跟, 不需要用户再来点信号窗口。
- `core_only` 下切场景必须**清掉 `_auto_checked` 记忆**, 否则切走再切回该场景时那几条已被记作"自动勾过"
  ⇒ 波形是空的(比切错更糟)。
- 核心模式只留**当前场景**那个根; 非 AR 场景没有手写核心清单 ⇒ 按场景秩取前 10 条(≤10 的承诺对所有场景成立)。

### 3.2f 机器人状态机接进 AR 场景 + 「是否在插拔」判定 (2026-10-20 实测)
老倪: 「AR 场景, 是需要接上机器人的, 你把机器人的状态机接上, 可以直接看到是否在插拔」
- 单一真源 `tools/robot_state.py`(可 `--text`/`--json`/`--watch`), 三个消费方共用: 信号总线(机器人.* 硬组)、
  AR 页面 `/api/robot_state`(顶部 chip, 1s 刷, 插拔中置绿/急停置红)、任何要“机器人现在什么状态”的脚本。
- 真源表(一个不新造): 控制器三查+位姿 `tcp_out/state.json|latest.json`(>5s 陈旧⇒未连接); 当前阶段
  `ss_live/skill_dispatch.json`(chunk_pipeline 每拍写, >3s 陈旧⇒阶段未知, 备路 `skill_gate.json`);
  执行技能 `ss_live/exec_state.json`; 任务 `ss_live/engine_latest.json`(task_id/task_name)。
- 状态码: 0 未连接 / 1 急停报警 / 2 未上电 / 3 手动 / 4 自动待机 / 5 自动运行。**改含义要同步改 unit 说明**。
- 是否插拔 = 当前阶段 ∈ {插入,拔出,插拔} 或 执行技能名含 insert/pull/插入。阶段是**任务流水线真值**,
  与控制器连不连上是两件事 ⇒ 未连接时也能看出在不在插拔；**阶段都拿不到才写“未知”, 不能用 0 冒充“非插拔”**。
- 运动中 = TCP 真值差分实测速度 >1mm/s(缓存上帧, dt 用真实 Δt), 差分不可用才退回控制器 op;
  未连接时**不写** `机器人.运动中`(键不存在 ≠ 0)。
- 坑: `tcp_ar_server.py` 里根变量叫 `REPO`/`HERE`, **没有 ROOT** ⇒ 写 importlib 加载时用 REPO;
  信号总线加载 robot_state 用模块级缓存, 别每次 pull 重新 exec_module。
- 主要信号 10 条定稿: 末端 x/y/z + 帧龄 + 轴向力 + 侧向力 + 力帧龄 + 机器人.插拔中/状态_码/运动中
  (速度 vx/vy/vz 让位给状态机 —— 老倪要的是“直接看到是否在插拔”)。

### 3.2g 「数据空间」↔「信号分析」数据源同步口径 + 字号 (2026-10-20)
老倪: 「数据空间和信号分析的数据源, 同步了么? 信号分析的窗口字体, 再大一些」
- DDS 那一半**本来就同源**: 两边都读 `zmax_data/dataspace/{live.json, trace.jsonl, busdb.json}`,
  信号分析里叫 `ds.*` 组, 数据空间叫报文/信号树。
- 不同源的是**文件通道**: 本机真值(tcp_out) / AR 总线(ar_aoi_live.json) / sstrace / ROS 影子 只进信号分析;
  AR 的 `末端.*`、`机器人.*` 不在 DDS 上 ⇒ 数据空间原本根本看不到 (老倪会当成“两个窗口在骗人”)。
- 修法(不发新 DDS 话题, 不造第二真源): `dds_canoe.BusView` 里加 `_fill_ar_group()` / `_update_ar_group()`,
  在报文树尾挂一个顶层组「🥽 AR 场景 · 文件通道 N 条」+ 三行汇总(位姿/力/状态机), 值取 `ar_aoi_live.json`。
  hook 点在 `reload()`: `_fill_tree()` 后面挂组、`_update_values()` 后面刷值 (树被 clear 时要重挂)。
- 判据 `tools/verify_sig_space_sync.py`: 真起 BusView + CanoeGraphicWidget, 核 ①数据空间有 AR 组
  ②位姿行与 ar_aoi_live.json 同值 ③状态机行看得出插拔 ④树字 16px/行高≥19px ⑤DDS live.json 同一文件。
- 字号: 信号分析这窗 QSS 里 13px→16px(树/按钮/日志)、12px→14px(表头/小标), 名字列 minWidth 460→560
  (字大了不把信号名挤没); 改完要核 `fontMetrics().height()` 真变高, 光改 QSS 不改宽度会截断。

### 3.2h 现场约定: 光模块夹在夹爪上, 绿色边框别动 (2026-10-20 老倪口述)
- 光模块就是**夹在机器人手臂末端(夹爪)**上的那个工件 —— 它跟手臂一起动, 所以任何基于"模坧在台面上固定位置"
  的坐标假设/固定叠加都会错位; 看它的位置就看 TCP 位姿。
- AR 画面上的**绿色边框不用动**: 它不是待调参数, 别因为"看着不对位"去重标定/改围栏/改偏移。
  老倪的原话就是这条口径 —— 动手前先记住, 否则会把本来对的东西调歪。

## 3.2 场景专属关键词表(当节点集分不开两场景时)
先查两任务的 `enabled_nodes`: 本项目 TASK-01-FW / TASK-06-TRAY **都是同一套 52 个节点**
(同一管线), 所以「按节点名分场景」必然 0 条 —— 别在这条路上浪费时间。
改用 **场景定义原文(scenes_5jobs.json 的 name/desc/objects/steps)** 里的专属词建表:
插拔=孔/插入/力控/夹持/接触/对位/固件; 摆盘=真空/吸盘/周转盘/料盘/槽位/放置/取件; AR=光学/判决/金手指/表面/缺陷/取像。
- 只命中**一个**场景才上色; 两边都沾的(夹爪/光模块)留白。**别把“光模块”当一票否决** ——「光模块头到孔_mm」
  是插拔专属(孔), 一否决就被错留白。
- 共用词清单要小且明确; 宁可白也不要错色(老倪零容忍)。
- UI 键常带来源前缀(`ar.`/`sstrace.`/`host.`) ⇒ `tag()` 要**逐层剥前缀**再查表。
- 表建好后 `--build` 生成真源, 并把各场景条数打印出来(「插拔 4 / 摆盘 3 / AR 176」这种数字就是交付证据)。

## 4. 活跃配置 → 场景/数据源 联动
- 真源 `tools/ss_scene_switch.py`: 写画布数据源节点(`ssdata`).`params.src_state`(经 `flows.load_canvas/save_canvas`, 不手改 .db), 并回读校验。
- 新增一态(如「AR场景」)必须同时: `SRC_CYCLE/SRC_DESC/SRC_SCENE_ID` + `_src_norm` + **把所有 `== "真机"` 收口到一个判据**(如 `_src_is_real()`), 否则新态会悄悄走仿真算路。
- 挂钩点选**唯一激活路径**(`tools/ss_task_bind.py --activate`)并用 try/except 包住: 切场景失败只提示, 不能拦激活。
- 改画布后的顺序: `ss_task_bind` → `project_archive space-save` → `engineering_db build` → 两 check(顺序反了会报 drift)。

## 5. HTML/JS 页面的隐形杀手
一张内联 JS 的页面, **一行孤立残片**(如 `$('x').textContent='…'; });`)就让整段 script 解析失败 —— 页面上**所有**按钮失效,
浏览器只留一条空 exception。改完必须 `node --check`(抽出 `<script>` 内容): 若 HEAD 与新版报同一个错, 那就是历史遗留的真 bug, 顺手修掉。

## 6. 进程控制脚本
按**端口/pid**找进程(`ss -ltnp`), 绝不 `ps|grep <脚本名>` —— 脚本名出现在你自己的命令行里就会自杀(实测 exit -15)。
起服务前等端口真释放, 否则 `Address already in use`。参考 `tools/ar_server_ctl.sh`。
