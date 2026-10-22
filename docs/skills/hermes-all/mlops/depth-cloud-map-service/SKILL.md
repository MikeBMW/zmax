---
name: depth-cloud-map-service
description: "Use when 用深度图/点云建一张地图并把它做成服务供远端/页面显示。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [depth, pointcloud, mapping, raster, http-service, handeye, backprojection, zmax]
    related_skills: [robot-vision-3d-localization, robot-3dgs-scene-asset, camera-extrinsics-calibration, status-aggregation-endpoint, user-facing-dashboard-delivery]
---

# 深度点云建图 → 地图服务 → 远端显示

## When to Use
- 被要求「用已有的深度/点云建一张图, 建好的图变成服务, 在另一台机器上显示」。
- 要出环境的**俯视/侧视栅格图 + 点云端点**, 供页面/别的机器拉取。
- 已有 `depth_raw.npy` / rosbag / COLMAP 数据集, 要判断**能建出什么、不能建出什么**。
- 输入是**一段视频/一组图像**(如手机拍的) ⇒ 走律 4 的 SfM 分支, 不是深度反投影。
- 建完还要**给远端/手机看** ⇒ 看律 5 的子路径挂载(两个必踩的 404 + 体积预算)与 `references/video-sfm-app.md`。

配套: 深度→3D 的公式误差与手眼单位坑归 `robot-vision-3d-localization`;
要真三维重建(3DGS 高斯)归 `robot-3dgs-scene-asset`。本技能只管**2.5D 深度点云地图的建、存、服务**。

---

## 🔴 律 0: 先说清这张图到底是不是 3D 地图

| 数据 | 能建出什么 | 不能宣称什么 |
|---|---|---|
| **单帧深度图**反投影 | **单视角深度表面 (2.5D)** —— 俯视投影天然是**一条窄带**(实测像素覆盖仅 **2.55%**) | 不许说「建出了房间/环境的三维结构」「环绕点云」 |
| 多帧深度 + 每帧位姿真值 | 按位姿拼起来的点云, 覆盖随移动距离涨 | 没位姿来源时不许拼 |
| COLMAP 稀疏重建 / 3DGS | 真三维 | 只有 `images/` 没有 `points3D` 时**报错, 不许拿图瞎造点** |

🔴 **「SLAM」这个名在无 LiDAR / 无移动底盘的场合是不准的**: 臂载相机位姿来自**机械臂 TCP 真值**(50Hz),
不靠 SLAM 估位姿 ⇒ 准确叫法是**已知位姿建图**, 精度上限 = 手眼闭环残差(实测 TSAI **1.74mm**),
不是「SLAM 定位精度 X」。对外话术按这个说, 别跟着用户的口头用词把口径抬上去。

---

## 🔴 律 1: 反投影链**不许自造**, 先搜真源

本仓已有实现, 自己重写一遍是纯浪费而且**必错在细节上**(阈值/单位/剔除), 症状是 bbox 离谱但代码「看着对」。

```bash
# 先定位真源: 谁写过这个 stats/bbox, 谁就持有正确链路
grep -rl 'bbox_base_mm\|depth_scale_mm_per_unit' --include='*.py' . | grep -v staging
```

真源链路(本仓 `tools/ros_scene_depth_build.py`)只有一条, 逐字对齐:

```python
z      = dep.astype(np.float32) * DEPTH_SCALE          # DEPTH_SCALE = 0.0001 m/unit
ok     = z > 0.05                                      # 🔴 50mm, 不是 >0
P_cam  = [ (u - cx)/fx * z, (v - cy)/fy * z, z ]
P_tcp  = R_x @ P_cam + t_x                             # 手眼 X (相机→末端)
P_base = R_g @ P_tcp + t_g                             # R_g/t_g = TCP 位姿(四元数 tcp[3:7])
```

- 🔴 **有效阈值必须跟真源一致**。只判 `z > 0` 会把近距飞点一起反投影 ⇒ 实测 bbox 被撑到
  `Z[-3322, 1158]mm`, 而真源是 `Z[-1224, 337]mm`。这个阈值是**几何口径**, 不是随便筛噪。
- 🔴 **手眼矩阵命名有歧义, 用数值反查**: `handeye_result.json` 的键叫 `T_base_cam`, 但它的平移值
  (`217.33, 5.74, -126.94`)与 `stats.json` 的 `X_t_mm` **完全相同** ⇒ 它实际是**相机→末端**的手眼 X,
  **不是** base←cam。名字看着像哪个方向不等于它真的是那个方向, 用「平移值是否等于另一处的 X_t」核。
- 翻译成代码时**逐项对照真源抄**, 别自己推 R 在左还是在右: `X_R @ P + X_t` 与 `(P @ X_R.T) + X_t`
  在 numpy 里等价, 但 `R_g @ P + t` 和 `P @ R_g.T + t` 才对; 三者混写会得到「看起来差不多」的错结果。

---

## 🔴 律 2: 离群点剔除是**必做项**, 不是可选优化

深度图里的飞点(反光/边缘/插值)反投影后会把 bbox 撑得离谱 ⇒ 之后所有「环境多大」「在不在界内」的判断全跟着错。

```python
def remove_outliers(P, k=12, std_ratio=2.0):
    """SOR: 每点到 k 近邻的平均距离 > 全局均值 + std_ratio·std 则剔。"""
    from scipy.spatial import cKDTree
    d, _ = cKDTree(P).query(P, k=min(k + 1, len(P)), workers=-1)
    mean_d = d[:, 1:].mean(axis=1)                 # 去掉自身
    return P[mean_d <= mean_d.mean() + std_ratio * mean_d.std()]
```

实测: 剔除 **4.79%**(257,172 → 244,854), bbox 从 `Z[-3322,1158]` 收到 `Z[-1539,1131]mm`,
`X` 上限从 3137 收到 2450。**没有 scipy 时用 5mm 体素占用法兜底**(邻居 <3 视为孤立点), 别跳过这一步。

🔴 **报 bbox 必须写明口径**, 否则「你的数和官方的差一倍」会来回扯:
本次 `244,854 点 / Z[-1539,1131]` 是**整场景全部有效像素**;
`stats.json` 的 `7,163 点 / Z[-1224,337]` 是**过完滤的主物体**。两者都对, 是两个口径, 不是谁错。

---

## 🔴 律 3: 栅格化的 empty 标记必须在归一化**之前**存

```python
np.add.at(img, (ib, ia), col); np.add.at(cnt, (ib, ia), 1)
empty = (cnt <= 0)                     # 🔴 先存
img = img / np.where(cnt == 0, 1.0, cnt)[:, :, None]
rgb = (np.clip(img, 0, 1) * 255).astype(np.uint8)
rgb[empty] = (18, 21, 26)              # 深灰底, 不是纯黑
```

🔴 **先 `cnt[cnt==0]=1` 再判 `empty` ⇒ `empty` 永远 False ⇒ 背景成纯黑**, 用户读成「没读到数据」。
实测整图亮度只有 **3.1**, 改成先存 mask 后回到 **123.5**。
配 **3×3 膨胀**(沿九个偏移取通道最大值)让稀疏点可见 —— 单像素的点在 900×900 里等于隐身。

坐标轴另一条: 两个轴**不能用同一个 span** 去归一化(`span=max(Δa, Δb)` 会让短轴只用到 45% 画布), 要么各自缩放, 要么接受留白但**在图注写明等比例**。

---

## 🔴 律 4: 输入是**视频**时走 SfM, 质量由视差定, 不由帧数定

数据不是深度图而是**一段视频/一组图像**时, 别硬套律 0~3 —— 那条反投影链要求每帧有位姿真值。
走 `tools/mapping/mono_sfm.py`(纯 OpenCV: 两视图初始化 + PnP 跟踪 + 三角化;
**不需要 COLMAP, 不需要 CUDA** —— 它就是为「cv2 无 contrib、无 ROS」的边缘机写的):

```bash
python3 mono_sfm.py --video cam.mp4 --out /tmp/map
python3 mono_sfm.py --frames <dir> --out /tmp/map --max-frames 200
```
产物 `trajectory.tum` / `points.ply` / `topview.png` / `summary.json`。

🔴 **验收看 `init_disp_px` + `points` + `reproj_err_med_px`, 不看 `frames_used`**:

| 数据 | init_disp_px | points | reproj med |
|---|---|---|---|
| 机械臂小范围扫场(平移几乎不变 9.9→10.06) | 9.21 | **101** | 1.32px |
| 正常移动(手持/大范围) | 18.15 | **5,690** | 0.47px |

帧数多但相机不动 = 匹配多、三角化少 ⇒ **几何退化**, 堆帧救不回来。
只报「建图完成」而不报点数和重投影误差 = 没验收。`init_disp_px` 是个位数就是视差不够,
让拍摄方**平移**而不是原地转。

🔴 **单目没有绝对尺度**(`summary.json` 写着 `scale: "单目无绝对尺度 (首基线=1)"`)。
量不出「这块板子 30cm」; 要真尺寸得双目/IMU, 或画面里放已知尺寸标定板。
对外不许把归一化尺度说成米 —— 与律 0 是同一类诚实性问题。

---

## 🔴 律 5: 挂到公网**子路径**下 —— 两个 404 坑 + 一条体积预算

把 `:880x` 的页面/服务经 ECS 80 端口暴露成 `/map/`, 下面三条至少两条是必踩的:
前两条各自造成 404(少做一件就 404), 第三条是「能通但用户用不了」。

**① 前端一律相对路径。** 绝对路径(`/points`、`/lib/three.module.js`)在 `/map/` 下指向站点根
而不是子应用 ⇒ 全 404。改 `fetch('points')`、importmap `"./lib/three.module.js"`。
nginx 侧配 `location = /map { return 301 /map/; }` 保尾斜杠, 否则相对路径解析错位。

**② location 用 `^~`, 不用普通前缀。** 站点里有 `location ~ .*\.(js|css)?$` 这类正则,
**nginx 正则优先级高于普通前缀 location** ⇒ `/map/lib/x.js` 被它抢去当本地静态文件找 ⇒ 404。
`^~` 命中后停止正则检查。**症状定格**: 直连隧道 `:18794/lib/x.js` 返 200, 经 nginx `/map/lib/x.js` 返 404。

同站点两条必知事实:
- ECS 是**宝塔版 nginx**(`baota-nginx.service`, pid 在 `/www/server/nginx/logs/`):
  `nginx -s reload` 报 `invalid PID number "" in "/run/nginx.pid"`(那文件是空的),
  必须 `systemctl reload baota-nginx`。
- **用 IP 直连会 404**: 不带 `Host: <域名>` 时 nginx 走默认站点, 没有你的 location。
  本地验证加 `-H "Host: datadrive.world"`, 对外验收用**域名**而不是 IP。

**③ 页面体积必须按链路带宽算, 不能按桌面体验算。** 公网走的是 ECS 出口(实测约 **0.57 Mbps**),
换算惯例 **每 100KB ≈ 2 秒**。首屏总重超 100KB 就要问「这东西能不能不引」。

实测三个版本同一条链路: 引 `three.module.js`(1.27MB) 直连隧道 **25s 超时**
→ 本地托管 18.3s → gzip 311KB 仍 5.8s → **改自写原生 WebGL 后整页 11KB / 0.33s**。

🔴 **症状定格: 所有接口都报 `failed to fetch`, 但单个 `curl` 每个端点都 200。**
这不是接口坏。`<script type="module">` 里一句 `import` 超时, **整个模块脚本就崩**,
后面所有 `fetch` 一起失败。定位法: 量**体积最大那个静态资源**的 `time_total`,
不要挨个测业务接口 —— 接口本来就都是好的。
只把库从 CDN 换成本地托管是**缓解不是修复**, 只解决「内网没外网白屏」, 不解决传输时间。

---

## 流程

1. **先清点已有资产, 不要先造数据**(用 `search_files(target='files')` / `read_file` 查**定点**路径,
   别递归扫数据根 —— 几十 GB + 上万文件会超时):
   深度图 + `stats.json` / 点云 npy / COLMAP 组 / 位姿真值文件, 各多新。
2. **找真源实现对链路**(律 1), 把 `DEPTH_SCALE`、有效阈值、手眼方向、四元数顺序**逐项核一遍**再写代码。
3. **反投影 → SOR**(律 2), 落 `points_base_mm.npy` + `meta.json`(带 bbox/点数/口径/剔除率/采集时刻/手眼残差)。
4. **栅格化**俯视(XY) + 侧视(XZ), 高度做伪彩着色(低蓝 中绿 高红), 按律 3 处理背景与稀疏点。
5. **起服务**(端点契约与查看器骨架见 `references/map-service-api.md`):
   `GET /map/status · /map/meta · /map/points.bin · /map/points.json · /map/topdown.png · /map/side.png · /`。
   点云走 `.bin` 而不是 `.json`: 24 万点的 JSON 有几十 MB, 二进制是 `16B 头 + float32 xyz`。
6. **验收不能只看 HTTP 200** —— 200 只说明路由通。必须同时出**图自身的统计**:
   有点像素占比、背景占比、亮度均值; 亮度个位数 = 渲染坏了(律 3), 覆盖极低 = 数据本身是窄带(律 0)。
7. **跨平台部署就绪性**: 只用 `numpy` + 标准库 ⇒ 目标机**不需要装任何运行时**; 但「零依赖」**不等于「零改动」**。
   🔴 **路径必须可由环境变量覆盖, 否则换机器必崩**: 脚本里写死 `ROOT/zmax_data/...` 时, 拷到布局不同的机器上
   一启动就 `FileNotFoundError`。入口处一次性收口成可覆盖常量:

   ```python
   ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
   DEPTH_DIR = os.environ.get("ZMAX_MAP_DEPTH_DIR") or os.path.join(ROOT, "zmax_data", "ss_live", "depth_map")
   OUT_DIR   = os.environ.get("ZMAX_MAP_OUT")       or os.path.join(ROOT, "zmax_data", "slam_map")
   ```

   目标机跑法: `cd ~/zmax_map && ZMAX_MAP_OUT=~/zmax_map/map ZMAX_MAP_DEPTH_DIR=~/zmax_map/data python3 tools/... --port 8801`。
   **只同步代码 + 这一份输入数据, 不要搬整个项目树**(实测项目 206G, 代码只有 93M)。
8. **跨机等价性验收**: 在源机与目标机各跑一次 `--once`, **点数/bbox/耗时逐项对照**。
   实测 4060 `0.88s` vs Intel `0.59s`, 点数 `244,854`、bbox 到 0.1mm **完全一致** —— 这才叫「换机器结果不变」。
   只在一台机器上跑通就报「已部署」是不成立的。

---

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 自己重写反投影链 | bbox 离谱但代码看着对 | 搜到真源逐字对齐(律 1) |
| 有效深度阈值取 `z>0` | bbox 被飞点撑大一倍以上 | 与真源同口径 `z>0.05`(米) |
| 不做 SOR | 少量飞点主导 bbox | k=12, std_ratio=2.0; 报剔除率(律 2) |
| 手眼键名当方向 | 点云整体翻/偏 | 用平移值反查它到底是哪一段变换 |
| 先归一化再判空 → `cnt[cnt==0]=1` | 背景纯黑, 亮度个位数 | empty mask 先存(律 3) |
| 单像素点 | 图看着空 | 3×3 膨胀 + 深灰底 |
| 把单帧深度图当 3D 地图交付 | 用户以为拿到环境几何 | 律 0, 明确「2.5D 单视角表面」 |
| 用「SLAM」命名 | 被追问定位精度时说不清 | 无 LiDAR/无底盘就叫「已知位姿建图」 |
| bbox 与官方数字对不上就改代码 | 越改越偏 | 先问是不是两个口径(全体 vs 主物体) |
| 只有 `images/` 的 COLMAP 组当点云源 | 想凭空造点 | 明确报错并指出该走 3DGS 训练那条路 |
| 路径写死成 `ROOT/zmax_data/...` | 换机器启动即 `FileNotFoundError` | 入口收口成 `ZMAX_MAP_*` 环境变量(流程 7) |
| 只在一台机上跑通就报「已部署」 | 换个布局就崩, 用户白等 | 两机各跑 `--once` 对照点数/bbox(流程 8) |
| 视频硬套深度反投影链 | 没有每帧位姿, 拼不出来 | 走 `mono_sfm.py`(律 4) |
| 只报「建图完成」不报点数/重投影 | 101 点的退化结果被当交付 | 报 `init_disp_px`/`points`/`reproj`(律 4) |
| 把单目归一化尺度说成米 | 用户按厘米量, 全错 | 明写「单目无绝对尺度」(律 4) |
| 子路径下页面写绝对 URL | 挂 `/map/` 后全 404 | 全改相对路径 + `location = /map` 301(律 5) |
| nginx 用普通 `location /map/` | `.js`/`.css` 被正则抢走 404 | 用 `location ^~ /map/`(律 5) |
| `nginx -s reload` 报 invalid PID | 配置没生效, 改了半天没反应 | 宝塔装的是 `baota-nginx`, `systemctl reload baota-nginx`(律 5) |
| 用公网 IP 验收 | 走默认站点, 404 | 用域名或显式 `-H "Host: ..."`(律 5) |
| 页面引 1MB+ 的 3D 库走公网 | 所有接口 `<b>failed to fetch</b>`, 但端点单独测都 200 | 自写原生 WebGL, 首屏压到 ~10KB(律 5 ③) |
| 先只把库从 CDN 换成本地托管 | 白屏没了但打开仍要 20s, 手机上仍像挂死 | 本地托管不解决带宽; 按每 100KB≈2s 压体积(律 5 ③) |
| `readPixels` 全 0 就断定画布黑 | 白排一轮不存在的渲染 bug | 那是 `preserveDrawingBuffer` 没开, 不是没画 |
| 拿状态栏数字当渲染证据 | 「显示 5690 点」但画布空 | 那个数来自 `job` 接口; 要查 `__zmap.n` + 像素亮点占比 |

---

## 支持文件
- `references/map-service-api.md` — 地图服务端点契约(含 `points.bin` 二进制头) / 查看器轮询骨架 / 栅格化与 SOR 可跑代码 / 本次实测数值与三处 bug 的机制
- `references/video-sfm-app.md` — 视频建图的手机 Web App 全链路: 上传→ffmpeg 抽帧→SfM→**原生 WebGL** 渲染的可跑骨架、体积预算、端点表、任务落盘、公网隧道配法
