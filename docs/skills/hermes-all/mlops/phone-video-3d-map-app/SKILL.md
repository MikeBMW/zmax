---
name: phone-video-3d-map-app
description: "Use when 手机/手持拍视频要出 3D 点云并做成手机能看的网页 (免安装 Web App + 单目 SfM)."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [sfm, monocular, pointcloud, mobile, web-app, threejs, ffmpeg, mapping, zmax]
    related_skills: [depth-cloud-map-service, zmax-mobile-3d-console, android-webview-shell-apk, robot-3dgs-scene-asset]
---

# 手机拍视频建图 → 手机可看的网页

## When to Use
- 「用手机拍视频建图，做个 app」「手持视频出个点云，手机上能转着看」。
- 只有**一段视频/一组图片**，没有深度图、没有相机位姿真值、没有 LiDAR/底盘。
- 要在**端侧机（无 CUDA / 无 COLMAP）**上出点云并做成手机入口。

分家：有深度图 + 机械臂位姿走 `depth-cloud-map-service`；要真三维高斯重建走 `robot-3dgs-scene-asset`；
手机页的 Three.js/网络硬坑走 `zmax-mobile-3d-console`。本技能只管**从视频到点云再到手机查看器这条链**。

---

## 🔴 律 0: 先定交付形态 —— Web App，不是 APK

手机浏览器原生 `<input type="file" accept="video/*" capture="environment">` 直接调后置摄像头录像，
拿到的是**真视频文件**，不需要任何原生代码。

⇒ 默认做网页。免签名、免商店、安卓/iOS 同一套、改页面刷新即生效。
只有确实要本机硬件/后台常驻/离线包时才做 APK（壳的做法见 `android-webview-shell-apk`）。

页面上要说明拍摄纪律，否则用户第一段视频大概率建不出来：**边走边横向移动、慢一点、画面里同时有近处和远处物体**；
原地转圈或快速晃动建不出东西。

---

## 🔴 律 1: 不要新写 SfM，先搜仓里的单目实现

本仓 `tools/mapping/mono_sfm.py` 就是为端侧机写的：纯 OpenCV（SIFT/ORB 两视图初始化 + `solvePnP`/RANSAC 跟踪 + 三角化），
**不依赖 COLMAP、不依赖 CUDA**（端侧机的 cv2 常没 contrib，`cv2.sfm` 不存在）。自己重写一遍等于重踩它的坑。

```bash
grep -rl 'mono_sfm\|solvePnP\|trajectory.tum' --include='*.py' tools/ | head
```

```bash
python3 tools/mapping/mono_sfm.py --video in.mp4 --out /tmp/map        # 或 --frames <dir>
#   --max-frames 200   --step 1   --focal <px>   (不给 focal 则按 1.2*max(w,h) 估)
```

产物：`trajectory.tum`（位姿）、`points.ply`（稀疏点云 xyz+rgb）、`topview.png`、`summary.json`。

---

## 🔴 律 2: 抽帧再喂，别把图像序列直接丢进去

`ffmpeg -vf fps=2` 抽帧后建图，**明显优于**直接喂原始图像序列（同一批数据实测）：

| 喂法 | 点数 | 重投影中位误差 |
|---|---|---|
| 直接喂 722 张图像 | 101 | 1.32 px |
| 抽帧成 2.3MB 视频再抽 144 帧 | **5,690** | **0.47 px** |

原因不是抽帧本身，是**视差**：机器人扫场的图像序列帧间位移几乎不变（实测 `||t||` 恒在 9.9~10.06），
基线太短 ⇒ 三角化不出点。抽帧+正常手速的横向移动才给到足够视差。

⇒ **先看 `summary.json` 的 `init_disp_px`**：>10px 才有料，个位数就是视差不足（不是算法坏）。
同时看 `reproj_err_med_px`（<1px 为佳）。

抽帧实现要点：
```bash
ffmpeg -hide_banner -loglevel error -i in.mp4 -vf fps=2 -qscale:v 3 <out>/f_%04d.jpg
```
- 超过 `max_frames` 时**按索引均匀抽稀**（保住时间覆盖），别截断前 N 帧。
- 任务结束**删掉 frames 目录**：几百帧 JPEG 会持续吃盘。

---

## 🔴 律 3: 单目没有绝对尺度，交付时必须说

`summary.json` 自己就写着 `scale: 单目无绝对尺度 (首基线=1)`。
正确话术：**能看形状和相对结构，量不出毫米/厘米**；要真尺寸得靠双目、IMU，或画面里放一个已知尺寸的标定板。
不许把归一化单位当毫米报给用户。

---

## 流程

1. **盘资产**：已有 SfM 实现（律 1）、测试视频/图像序列、目标机是否有 `ffmpeg`（Ubuntu 上
   `sudo apt-get install -y ffmpeg`；很多端侧机出厂没装）和 `cv2`。
2. **后端**：stdlib `http.server` 就够，零第三方依赖（换机器不用装环境）。端口与既有服务并列编排
   （推理/建图/旁路 各自占一个，别撞）。端点：
   `/`（页面）· `/upload`（POST multipart）· `/job?id=`（轮询状态）· `/points?id=` · `/trajectory?id=` ·
   `/topview?id=` · `/jobs` · `/health` · `/lib/<静态>`。
3. **前端**：Three.js 点云 + 轨迹线，单指旋转/双指缩放/滚轮缩放。**Three.js 必须同域托管**（产线内网无外网，
   CDN 挂 = 白屏），并在页面里做 `?id=` 分享链接（打开就是别人建好的图）。
4. **常驻**：systemd `Restart=always` + `enable`，路径全部环境变量化。
5. **验收**：真视频走完整链路 + 核验渲染（见下）。

### 后端三个必踩的坑

- 🔴 **别 `import cgi`**（Python 3.13 已移除）。multipart 自己按 boundary 切：
  ```python
  boundary = ctype.split("boundary=")[1].strip().strip('"').encode()
  body   = self.rfile.read(int(self.headers["Content-Length"]))
  for part in body.split(b"--" + boundary):
      if b'name="video"' in part and b"filename=" in part:
          vdata = part[part.find(b"\r\n\r\n") + 4:].rstrip(b"\r\n-")
  ```
- 🔴 **任务状态必须落盘**（`job.json`）。纯内存态的表在服务重启后让历史任务全部"消失"，
  而用户手里的分享链接还在 ⇒ `_load(id)` 要先查内存再回盘读。
- 🔴 **路径可环境变量覆盖**（`ZMAX_MOBILE_MAP_DIR` / `ZMAX_MONO_SFM` / `ZMAX_PY`）。
  写死 `ROOT/...` 拷到布局不同的机器上启动即 `FileNotFoundError`。
- 抽帧 + SfM 丢进 daemon thread，HTTP 只负责读写状态；上传体积设上限（几百 MB 以上直接回 413 并说明）。

---

## 验收口径（不能只看 HTTP 200）

| 层 | 判据 |
|---|---|
| 链路 | `/upload` 返 job id → `/job` 走到 `done`，`frames`/`n_points`/`secs` 有值 |
| 数据 | `/points` 返数组且首点含 `[x,y,z,r,g,b]`；`summary.json` 的 `init_disp_px`>10、`reproj_err_med_px`<1 |
| 产物 | `/trajectory`、`/topview` 均 200 且有字节 |
| **渲染** | **页面上的点数来自 job 接口，不能证明画出来了。** 要 `preserveDrawingBuffer: true` +
  `window.__zmap={scene,points,camera,renderer,n}` 钩子，CDP 里读 `readPixels` 亮点占比与
  `points.geometry.attributes.position.count`（详见 `zmax-mobile-3d-console`） |
| 重启 | `systemctl restart` 后用旧 job id 仍能取到 `/points`（证明落盘恢复有效） |

---

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 直接喂图像序列 | 只出百来个点、误差 1.3px | 抽帧成视频再 2fps 抽（律 2），先看 `init_disp_px` |
| 视差不足还调参数 | 怎么改都稀疏 | 是拍摄/序列问题，让用户横向移动重拍 |
| 把归一化尺度当毫米 | 用户拿去量尺寸全错 | 律 3, 明说单目无绝对尺度 |
| `import cgi` 解析上传 | 新版 Python 直接 ImportError | 按 boundary 手切 |
| 任务表只放内存 | 重启后旧链接 404 | 状态写 `job.json`，读时回盘兜底 |
| Three.js 走 CDN | 内网手机白屏，本机却正常 | 下载到同域 `/lib/` 由后端静态服务 |
| 页面显示点数就当渲染成功 | 数据对但画面黑 | `preserveDrawingBuffer` + 读像素 |
| 抽帧不清理 | 磁盘被几百帧 JPEG 吃掉 | 任务收尾删 frames |
| 做 APK 才觉得是"app" | 多花打包签名时间，iOS 还得重来 | 律 0, 先给网页 |

---

## 落点（本仓）
- `tools/mobile_map_app.py` — 后端（stdlib，零第三方，含 job 落盘与 multipart 手切）
- `tools/mobile_map_page.html` + `tools/three.module.js` — 手机页与同域 Three.js
- `deploy/systemd/zmax-mobile-map.service` — 常驻单元（`Restart=always` + 环境变量化路径）
- `tools/mapping/mono_sfm.py` — 单目 SfM 真源（律 1）
