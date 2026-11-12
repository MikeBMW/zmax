---
name: mujoco-workcell-scene-and-live-view
description: "Use when 改 MuJoCo 工位场景(料盘/槽/设备盒/相机)或 8802 直播页取图与机位切换。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [mujoco, render, 8802, scene, live-view, geomgroup, blob-image]
    related_skills: [ar-render-perception-plan-dualarm, sim-real-scene-overlay, low-latency-camera-streaming]
---

# MuJoCo 工位场景 + 8802 直播页

`tools/ar_mujoco_env.py::build_mjcf()` 造场景, `tools/ar_scene_render_server.py` 出帧/出页,
`/video` 就是用户天天看的那一页。本技能管**“场景里有什么、看到的是什么、页面上怎么取图”**;
感知/规划/执行闭环另见 `ar-render-perception-plan-dualarm`。

## When to Use

- 用户说「8802/video 少东西 / 没有顶视相机 / 料盘里没有槽 / 画面什么都没有」
- 要往场景里加设备盒、料盘、槽位、相机壳体或新机位
- 要改 `/video` 页(按钮、角标、机位切换、取图方式)
- 改完场景后发现画面发灰、料盘被盖、帧突然只有十几 KB
- 用户说「手臂不动 / 夹爪位置不对 / 夹爪悬空脱开 / 末端应该到 tool1」

## 铁律

1. **几何只从真源取, 不手写常数**: 设备盒/料盘来自 `fence_store`(`/api/fence` 同一份);
   槽位真源是 `zmax_data/staging_zmax_repo/data/skills/l2_atomic/place_cells.json`
   (`cells` 里 `kind=='slot'`, 42 个, 带 `pos_mm/size_mm/parent`, SAM3 实测 base mm)。
   AR 页里没有的条目不要自己造 —— 先说“库里没有这台相机”, 让用户先把它标成盒体。
2. **名称过滤是脆的, 按 kind/id 判**: `"槽" not in name` 会把「下料盘(第三·14槽)」
   「废料盘(不良品·无槽位)」一起筛掉 ⇒ 4 个盘只建出 2 个, 另外 28 个槽悬在空中。
   建完必须数一遍: `x.count('name="pan_bot') == 4`、`x.count('name="slot') == 42`。
3. **遮挡用 geomgroup 分层, 不用半透明**: 设备盒/相机壳体统一 `group="3"`, 俯角 ≤ −70°
   (或 `cam=top`) 时 `opt.geomgroup[3]=0`。实测 alpha=0.45 把整帧压成灰度:
   料盘槽 187 vs 台面 185(差 2 灰阶)、金手指全帧只剩 5 个暖色像素。
4. **亮度/取景一律给数**: `mean / 暗像素% / 暖色像素数 / 行亮度`。判定“看不见”之前先看
   帧字节数: 正常 130~330KB; 17KB = 整幅单色(被墙/被板包住), 不是“没渲染”。
5. **直播页取图不能直接改 `<img>.src`**: 6fps + 单帧 ~200ms 时元素长期停在 loading 态
   (`naturalWidth=0 complete=false`), 页面就是空白而 `/frame.png` 仍 200。用
   `fetch(url,{cache:'no-store'})` → `URL.createObjectURL(blob)` 换 src, 换完 revoke 旧的。
   **双缓冲用同一个 URL 也无效**(重新赋值会再触发加载)。
6. **删/改几何体前先查谁按名字找它**: `ik_solve()` 认 **geom** `<side>_tcp`、FK 认 **site** `<side>_tcp`。
   重写夹爪时把这两个删掉, IK 每拍返回「找不到 R_tcp」, `_ar_cmd_ctrl` 返回 None ⇒ **驱动链断在第一步,
   双臂静止而料盘/工件照常渲染**(看起来像“画面正常、只是手不动”)。锚点必须留在**真 TCP** 上
   (本工位 = URDF `joint_tool1`, 法兰前方 258.7mm), geom 放 `group="5"` 永不渲染。
7. **改写场景/生成器源码只用锚点替换, 不用整段 `str.replace`**: 一个大文件上做子串替换会把文件写成几万行
   (实测 186 行 → 63304 行)。改完 `wc -l` 对数; 文件若未进 git, 用 GitHub contents API 从最后一次提交拉回原文再改。

## Procedure: 加场景元素

1. 读真源: `./gui-venv311/bin/python -c "import sys;sys.path.insert(0,'tools');import fence_store as FS;print([b['name'] for b in FS.listing()['items'] if b.get('type')=='box'])"`
   和 `place_cells.json` 的 kind 计数。
2. 在 `build_mjcf()` 里循环生成 geom, 只给 `type="box"`/`frustum` 这类有 `p1/p2` 的条目建, 厚度 <4mm 的参考面跳过。
   设备/相机 → `group="3" contype="0" conaffinity="0"`; 料盘走「薄底 + 四壁 + 垫块」; 槽片落盘面 −6mm。
3. 槽片颜色: 深盘底(0.10)上 `0.05` 等于隐形 ⇒ 用 `0.30 0.31 0.33`。
4. 自检: 重建 XML 数 geom 数量; 起服务后取 `/status.json`(`ok/n/mean`) + 一帧图量 `mean/暗像素`。
5. 想让用户“看见”就要**视觉复检**: 把帧交给视觉子代理问“能不能看到 X、几个、有没有被盖”, 不要自己看数就交。

## Procedure: 加机位与相机实体

- 新机位加进 `VIEWS`(lookat/distance/elevation/azimuth/fovy), 并在 `/video` 的按钮表里加一项
  (`data-v=<名>`, 角标文案表同步)。
- **预设机位不要读缓存**: 若非 `close/ar3d`, 走现场渲染(FREE_Q) —— 缓存帧可能还是旧机位,
  用户会说“加了顶视没生效”(实测缓存与真顶视差 74.5 灰度)。
- 场景里要一台**真实体相机**就在 worldbody 里加 `<body><geom box/cylinder…><camera name="cam_xxx" pos=… euler=…/></body>`:
  `euler=0` 即沿自身 **−z** 看(= 正下视); 壳体放 `group="3"`, 否则顶视时它自己挡镜头。
  ⚠ `m.cam_pos` 是 body 局部, 世界位置用 `d.cam_xpos[cid]`(mj_forward 之后)。
- 取景按被看物算: 4 个料盘 y 跨 −0.50..0.97 ⇒ lookat y≈0.33 / dist 1.5~1.6 / fovy 46~50;
  用过 1.85m/55°, 工位只占中间一条横带、上下 60% 是棋盘地板。
- **免猜的 free-camera 换算**(要在服务外写投影器时直接用):
  `fwd = (cos az·cos el, sin az·cos el, sin el)`、`pos = lookat − dist·fwd`;
  az=0 时相机在 **−x 朝 +x** 看(`az=0,el=0,dist=1` 实测 `pos=(-1,0,0)`, `fwd=(1,0,0)`)。
  写完先跟 `mjv_updateScene` 后的 `scn.camera[0].pos/forward/up` 对账, 再拿去投影 —— 自己推的符号错一眼看不出来。

## Procedure: 给外部消费者提供相机真值与深度

- 服务端**自己算出来的**机位(`track`/`face` 跟物、`live` 页面同步)**必须把这一帧真正用的相机一起交出去**:
  `/cam.json` 回 lookat/az/el/dist/fovy/w/h + `ts`/`age_s`。外部只能从 URL 猜参数, 猜不到 ⇒ 用页面参数
  去反投影, 件被投到画面外、深度读到远平面(实测 127m), 看着像“感知坏了”。
  自检: 把 lookat 投回画面必须正好落在 `(w/2, h/2)`, 偏差 0px 才算同一台相机。
- 深度通道 `/depth.png`: `r.enable_depth_rendering()` 必须在 `update_scene()` **之前**, 渲完 `disable`;
  返回单位是**米**, 出口编 16bit 毫米 PNG(`>0` 才有效, 127.49m 就是“这条光线什么都没打到”)。
- RGB 与深度同机位同画幅; 分两次渲染中间位姿会动 ⇒ 反投影时用件中心附近 3px 窗口的**中值深度**, 单像素噪声甩不飞。
- **平面假设只对躺在那平面上的件成立**: 腕部特写里件在 0.56m 高, 按料盘面 z=0.109 反投影实测差 **452mm**。
  要么给深度, 要么别报 3D。
- 画幅按消费方画布给: 4:3 帧塞进 1.7:1 画布, 同一 fovy 下横向视场窄三成(左侧料盘/台面被压实), 两幅图对不上参照物。
  ⚠ 先算比例再限幅 —— 把 w 夹到 1280 而 h 不动, 会把 1500×882 的 1.70 变成 1.45。

## Procedure: 换末端执行器 (夹爪 / 光模块)

1. **取真值, 不猜**: `config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf` 里 `joint_tool0`/`joint_tool1` 给出
   法兰→TCP 的 `xyz/rpy`(本工位 `(-0.0159, 0.0183, 0.2587)`, rpy `(0.037, 0.675, 2.375)` rad);
   工件尺寸取 AR 页 MODSPEC(光模块 56.5×13.4×8.5mm, 原点=模块头)。没有夹爪 URDF 就按
   「法兰盘 → 执行器 → 两指 → 工件」自建, 尺寸写进代码注释, 别在报告里编。
2. **夹爪画在法兰系, 工件挂在 tool1 系**: `joint_tool1` 的 Z 轴与腕轴差 **33.6°**, 把夹爪整组放进 tool1
   系会歪出腕口(看着“悬空脱开”)。法兰系里排 `z`: 法兰盘 0–24 / 执行器 24–126 / 指 123–265 / 工件 208–265 mm。
3. **指的内侧面按工件在法兰系的投影包围盒定**, 不按工件自身宽的一半: 工件转了 33.6° 后
   AABB y = −14.7…+25.3mm。用 `mujoco.mj_geomDistance(model,data,g1,g2,1.0,None)` 判贴合:
   要 `≈0.000`, 负值=插进工件, >20mm=断手。
4. 改完三段都量: 到腕心距离成单增序列且首尾相接、`mj_geomDistance` 全 0、服务 `/frame.png` 字节数正常。
   然后再交视觉子代理问「法兰→执行器→两指→工件 是否连续、有没有黑缝/穿模」。

> 细节数值与排查脚本见 `references/tcp-gripper-and-camera-entity.md`。

## 诊断: 手臂不动

按序判, 每步都能把范围砍一半:

1. **服务在出帧吗**: `/status.json` 的 `n` 是否在涨、`mode` 是什么。`mode="idle"` 持续 = 外部驱动没进来。
2. **骨骼动了没**: 连抓两次 `/bones.json` 算 `L/R` 最大差; `0.0` = 模型没被驱动(不是相机/浏览器问题)。
3. **驱动源新鲜吗**: `zmax_data/ss_live/ar_cmd.json` 的 `t` 与 `time.time()` 差(<2.5s)、`a/b/u/seq` 在变;
   `ar_mj_q.json` 只由 AR 页推(`_armq_read` 自带 1.5s 过期), 页面没开时它是旧的, 正常。
4. **为什么没生效**: `/status.json` 的 `ac_err`/`ac_tgt`。`ac_err` 有值(IK 失败) → 查锚点几何是否还在;
   `ac_tgt` 空 → `_ar_cmd_ctrl` 根本没被调用(取数/路径问题, 不是 IK)。
5. **页面还是画面**: 浏览器 console 连续 5 次采样 `<img>.src` 的 blob URL, 每次都在变 ⇒ 页面在刷新,
   问题在模型; URL 不变 ⇒ 页面侧停了。
6. **Windows 端先怀疑旧进程**: 只 scp 文件不重启 = 跑的还是内存里的旧代码。必须杀
   `cap_render.py` 与 `ar_scene_render_server.py` 两种命令行, 再 `Start-ScheduledTask`, 然后用
   `mode=sim` + `bones` 差值确认, 不要只看“服务 200”。

## Procedure: 改 `/video` 页

1. 改动都在 `ar_scene_render_server.py` 的内联 HTML 字符串里, 它是压扁的一行 JS ——
   替换时容易吃掉相邻 token。改完 **curl 回读服务返回的 HTML** 数关键 token(`var FPS`、`setInterval(`、新按钮的 `data-v`)。
2. 起服务后浏览器实测: `document.getElementById('v').naturalWidth` 连续 8 次应全为 960、`complete=true`;
   点每个按钮后读 `VIEW` 与角标文本。
3. 只看到 HTTP 200 **不算过** —— 脚本语法错时页面照样 200, 只是整段 JS 不跑。

## 🧩 槽位缺失的真因: place_cells.json 路径 (2026-11-10 实测)

现象: 顶视里只有中间料盘有几个槽片 (5~6 个), 左右两个盘是纯黑面板; 另一台机器 (.7) 同样是三个盘、每个盘两排槽。
根因不是代码: `ar_mujoco_env.py::build_mjcf()` 读的是**相对 __file__ 的 staging 路径**
`<_internal>/zmax_data/staging_zmax_repo/data/skills/l2_atomic/place_cells.json` ——
本机只把真源放在 `~/zmax/data/skills/l2_atomic/place_cells.json`, `_exists` 失败 ⇒ `except: _pc=[]`
⇒ 静默退回 fences 里的 6 个 fslot。判据: 顶视数可见槽片; 修法 = 建目录并拷真源:
```bash
mkdir -p ~/zmax_console/app9/_internal/zmax_data/staging_zmax_repo/data/skills/l2_atomic
cp ~/zmax/data/skills/l2_atomic/place_cells.json $_/
```
然后**必须重启 8802** (改文件不重启 = 跑内存里的旧场景): 8802 由计划任务 `ZMAX_8802_RENDER` 托管
(`app9\Z-MAX_Console.exe app9\cap_render.py`, 注意不是 `run_8802.bat` —— 那个指向 app8)。
杀端口 8802 的 pid 再 `Start-ScheduledTask ZMAX_8802_RENDER`, 启动后要 30~40s 才出帧
(三路标定跑完), 期间 /frame.png 503 是正常的, 别当崩。

## 📷 /cam.json + /depth.png (2026-11-10 补到本机)

外部反投影/深度不能拿 URL 里的参数猜机位 (实测会投到画面外/深度读到远平面)。做法:
- 渲染线程处理 `FREE_Q` 请求时, 把 **实际用的** `lookat/az/el/dist/fovy` 写回 `req["cam_used"]`
  (track/face 跟物后的值才算数); `render_free()` 拿到后连同 `ts/ w/h` 存进模块级 `_LASTCAM`。
- `GET /cam.json` → `{"ok":true,"cam":{lookat,az,el,dist,fovy,ts,w,h,age_s}}` (与外部场景同形状)。
- `GET /depth.png?cam=close|top|topmid|free` → 16bit **毫米** PNG: `enable_depth_rendering()` 必须在
  `update_scene()` 之前, 渲完 `disable`; `np.clip(dep*1000,0,65535).astype(uint16)`。
  实测: top 中位 2393mm、close 中位 355mm、远平面饱和成 65535 (而 0 才是真的没打到)。
  坑: 不能只靠 depth 分支的 png 字段过 wait —— `render_free` 要加 `depth=True` 开关并按 `depth_png` 判空。

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 每拍直接换 `img.src` | 页面空白, 帧接口 200/200KB | fetch→blob URL 换图; 同 URL 双缓冲无效 |
| 内联 JS 替换吃 token | 页面全停(HTTP 200) / 定时器每帧连发 | 回读服务返回的 HTML 数 `var FPS`、`setInterval(` |
| 预设机位读缓存帧 | “加了顶视没生效”, 帧是旧机位 | `close/ar3d` 外一律现场渲染 |
| 背景墙放错侧 | 整幅平灰, 帧 13~17KB | 方位 0° 相机在 −x 朝 +x 看 ⇒ 背板必须在 +x; 挡画面就整段删 |
| 半透明设备盒 | 全帧降饱和(槽 vs 台面差 2 灰阶) | 用 `geomgroup[3]=0` 分层, 不用 alpha |
| `"槽" not in name` 过滤料盘 | 4 个盘只有 2 个有盘体, 槽悬空 | 只排除以“槽”开头的条目; 建完数 `pan_bot` |
| 槽片用 0.05 近黑 | 深盘底上看不见槽 | 提到 0.30 灰 |
| 场景加真相机后顶视被自己挡 | 顶视画面一块板 | 相机壳体进 `group="3"` |
| 只给 `pans[0]` 建盘体 | 其余盘是“纯色板/没槽” | 遍历所有盘, 盘体/四壁/垫块带索引后缀 |
| `m.cam_pos` 当世界坐标 | 位置全 0 | 用 `d.cam_xpos[cam_id]` |
| body euler 与 camera euler 叠乘 | 期望俯 35° 实际水平朝 +X, 中央射线打到 0.57m 外的横梁 | 视角方向**算出来**再渲: `d.cam_xmat` 第三行取反即视轴, 并 `mj_ray` 打中央射线看命中体与距离 |
| 相机贴着自己顶盖 | 画面下半六成是自家盖子(命中 32–53mm), 不是黑屏 | 镜头探出盖外(实测盖半径 72→62mm、机身外移 72mm), 或顶视时把壳体 group 关掉 |
| 只改文件不重启(Windows) | 页面照常, 手臂/新几何不生效 | 杀 `cap_render.py` + `ar_scene_render_server.py` 两种命令行再起, 用 `mode=sim`+`bones` 差值验收 |
| 外部拿页面参数反投影服务端算的机位 | 3D 点跑到画面外、深度读 127m | 同帧发布 `/cam.json`, 消费方以它为准 |
| `enable_depth_rendering()` 放在 `update_scene()` 之后 | 深度整幅是远平面(127.49m) | 先 enable 再 update_scene, 渲完 disable |
| 渲染/请求处理里直接用 `np`/`cv2` | 接口 503 文本 `name 'np' is not defined`, 没有 traceback | 这个大文件每个函数作用域独立, 用时局部 `import` |
| 空帧检查挡在深度分支前 | `/depth.png` 回 `depth: 空帧` | 深度分支先判 `depth_arr`, 再判 `png` |

## Verification

- 场景: `build_mjcf()` 里 `pan_bot`=4、`slot`=42、`equip`≥4; 缺 STL 时自动退回旧臂要能看到
- 帧: `/frame.png?cam=close` mean 80~95 且暖色像素 ~1000; `cam=top` mean ~100 且暗像素 ~0; 字节 130~330KB
- 页: 连续 8 次 `naturalWidth=960`; 每个机位按钮点了 `VIEW` 与角标同步
- 交叉机位: 同一时刻 `close / top / topmid` 三张 md5 必须互不相同
- 视觉: 交给视觉子代理确认“要看的东西在不在、几件、有没有被盖住”, 不只报数值
