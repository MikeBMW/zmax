# 8802 MuJoCo 工位渲染场景 (ar_mujoco_env.py / ar_mujoco_urdf.py / ar_scene_render_server.py)

服务: `zmax-ar-render.service` (Linux) / 计划任务 `ZMAX_8802_RENDER` (Windows)。路由: `/video`(HTML 外壳,
带 `Accept: text/html` 才返回 HTML; 不带则返回 multipart MJPEG), `/frame.png?cam=<preset>`, `/live`(永远 HTML), `/status.json`。

## 一、几何为什么“建了却看不见” (按排查顺序)

1. **geomgroup 默认是关的**。`mujoco.MjvOption()` 默认 `geomgroup=[1,1,1,0,0,0]` —— group 3 天生 OFF。
   写 `op.geomgroup[3]=0` 是空操作; 要显示必须显式 `=1`。正确写法:
   `op.geomgroup[3] = 0 if (顶视 or elevation <= -70) else 1`, 预设循环和 `render_free` 两个渲染入口都要改。
2. **两处 builder 同时画同一物体**。`fence_geoms()` 会把非主料盘的料盘再画成 0.10~0.14m 实心 slab,
   `build_mjcf()` 的 `pan_*` 循环画薄底+四壁+槽片 (z 0.105~0.109)。slab 把槽片整个盖死 ⇒ 顶视里“纯平板没槽”。
   一个物体只能在一处画。
3. **过滤条件筛过头**。`"槽" not in name` 会把 `下料盘(第三·14槽)` / `废料盘(不良品·无槽位)` 一起筛掉。
   槽本体是以 `槽` 开头的条目, 只排除这种: `"料盘" in name and not name.startswith("槽")`。
4. **灯只照到一个盘**。一盏点光对着主盘 ⇒ 主盘 250/255 过曝、侧盘 77~115, 槽与盘面同亮度看不出。
   补光要按料盘逐个放 (0.45), 不要一盏打全场。
5. **物体太小/被臂挡**。96mm 方块在 2.3m/fov69 下只有 22px, 而且正好压在臂后 —— 用户会说“还是没有”。
   先算投影尺寸再谈建没建。

## 二、诊断手法 (比目测快且不靠猜)

- **染色法**: 把待查几何的 rgba 临时改成 `1 0.1 0.1`, 渲一帧数红像素及 u 范围。修前 5335px 集中在一个盘,
  修后 16371px 跨三盘 —— 一次定案“到底是没建还是被盖”。
- **射线法**: `mj_ray(m,d,[x,y,0.6],[0,0,-1],...,geomgroup=1,...)` 返回第一个命中的 geom 名,
  直接看出是谁盖住了目标 (实测一眼看出 `eq0` 和 `equip4`)。
- **坐标投影法**: 把真源坐标 (place_cells 的 42 个槽) 按同一 az/el/dist/fov 投影到像素, 统计 in-frame 数量。
  目测“看起来没有”经常只是被截在画外 (1.42m/46° 时左盘整个出了上边界)。
- 相机几何四元数用 `mju_mat2Quat(q, np.asfortranarray(R).flatten())` —— **列主序**, 直接 `R.flatten()` 会得到
  旋转差几十度的姿态。

## 三、相机 / 机位

- `VIEWS` 里 `top`、`topmid` 走**现场渲染** (`render_free`), 不吃缓存 `views[name]` —— 缓存帧曾与实际取景差 74.5 灰度。
- 顶视 (elevation ≤ -70) 关掉 group3: 上横梁 1.6m 悬在料盘正上方 0.55m, 不关任何正俯视都被盖死。
- 顶视取景要按**真源坐标跨度**定, 不是按感觉: 4 个料盘沿 y 从 −0.50 到 0.97 ⇒ 1.55m/50°/lookat y 0.235 才能全进框。
- 直播页 `<img>` 不能每拍直接改 `src`: 6fps + 200ms 加载 ⇒ 图片一直停在 loading 态 (naturalWidth 0),
  看着“没有画面”。正解 `fetch → blob → URL.createObjectURL → 换 src → revoke 旧 blob`。
- 改直播页脚本时别把 `setInterval(function(){...},500)` 的包裹删掉: 剩下裸语句 = SyntaxError, 整段脚本不执行,
  `<img>` 一帧都不加载 —— 症状与服务端 503 很像, 实为前端语法错。

## 四、夹爪 / tool1 (URDF 末端)

真源: `joint_tool0` = link6 零偏移; `joint_tool1` 相对 tool0 为
`xyz=(-0.0159, 0.0183, 0.2587)` m、`rpy=(2.12, 38.68, 136.09)` deg。即模块头在法兰前方 258.7mm。

- **tool1 的 Z 轴与腕轴夹角 33.6°** (不是沿着腕轴)。所以:
  - 夹爪/法兰盘/指头这类**沿腕轴伸出的结构**必须建在**法兰坐标系** (link6 原点, +Z 伸出);
  - 只有**光模块**挂在 tool1 的旋转系里 (它本来就是歪的, 那是真值)。
  - 把夹爪画进 tool1 系 ⇒ 整套组件歪出腕部、看着“悬空脱开, 中间一道黑缝”。
- 光模块尺寸取页面 `MODSPEC`: **长 56.5 × 宽 13.4 × 厚 8.5 mm** (X=厚, Y=宽, Z=长), 原点 = 模块头,
  本体朝法兰方向长 56.5mm ⇒ 在 tool1 系里中心 z = −28.3mm。方向符号由 `dot(tool0-tool1, Z_tool1)` 定, 不预设。
- 各件到腕心 (link6) 的距离必须连续相接: 法兰盘 12mm / 执行器 75mm / 指尖 205mm (±32mm) / 模块中心 237mm。
  改完先打印这些距离和 `geom_xpos`, 不要只看图。

## 五、两台机器都要落地

Windows 侧改完必须重启并**验证服务返回内容**, 不是磁盘文件 (详见 `windows-plant-host-operations` §10.17:
要杀 `cap_render.py` 包装层 + `ar_scene_render_server`, 只杀后者等于没重启)。首次取帧 20~90s 预热,
超时要重试一次再判失败。
