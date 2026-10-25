# 把另一台机器的 USB 相机接成工位页的一格（中央相机）

适用于：工位总览页某一格要显示**不在本机**的摄像头（典型：Intel 工控机上的 USB2 UVC），
本机又不在这台机器的网段上（只有 WiFi，没有 192.168.23.x 网卡）。

## 三段链路，每段一个 unit

```
[源机器]  zmax-usb-cam-http     127.0.0.1:8812   /snap.jpg + /health
[本机]    zmax-xxx-cam-tunnel  127.0.0.1:8812 → 经跳板 ssh -L → 源机器:8812
[本机]    zmax-cam-live-stream :8791/:8793      推流服务把这一路当 local2
```

- 源端服务形状：**单进程独占相机** + 一个采集线程只留最新帧；给 `GET /snap.jpg` 回最新 JPEG 并带
  `X-Frame-Age-S`（源端自报帧龄，消费端 `url_cam_worker` 认这个头）；
  **超过 STALE_S（3s）就回 503 + 原因，绝不拿旧帧冒充新鲜** —— 否则页面上是一格“看着有图、其实是定格”的画面。
- 隧道 unit 要点：`ExitOnForwardFailure=yes` + `ServerAliveInterval=15` + `Restart=always` +
  `BatchMode=yes`（key 免密，别把密码写进 unit 正文）；`User=` 要能读到跳板的 key 与 known_hosts。
- 消费端：`cam_live_stream.py --local2-url http://127.0.0.1:8812/snap.jpg`
  （`url_cam_worker` 对 http(s) 是**原样转发字节**，不重压；rtsp/rtmp 才走 cv2 解码）。

## 名字要改两处，改一处不够

1. 页面静态标题：`tools/web/station.html` 里那格的 `<span class="ttl">`（热读，改完刷新即生效）。
2. **服务端运行名**：`_CAM_LABEL[<通道>]` 决定 `/station/status` 的 `label`，页面右上那行小字读它。
   `--local2-url` 分支默认把 label 写成 `"📺 " + URL`（很难看）⇒ 用 **`--local2-label "🎥 中央相机"`** 覆盖。
   不加这个参数，标题换了、小字还是网址，看起来像没改干净。

## 别追 fps —— 先算清“页面多久刷一次”

实测三段各自的代价（640×480 YUYV，43KB/帧）：

| 段 | 单次取帧 | 上限 |
|---|---|---|
| 源机器本机 `curl /snap.jpg` | **0.6 ms** | 9.3 fps（相机 10fps 跑满） |
| 经 ssh 隧道到本机 | **250~450 ms** | 有效 ~4.2 fps |
| 页面显示 | 该格 `data-every="400"` | 2.5 fps |

⇒ 有效帧率被**隧道每请求一个来回**顶住（`Compression=no` 不改善，说明是路径 RTT + 每连接一个 channel，
不是压缩 CPU）。而页面对这一格本来就 400ms 刷一次，**源端 4fps 已经够**，不要去为这个改代码或换协议。
真要提：让消费端复用一条 keep-alive 连接（`http.client`）或改推 MJPEG（一连接长流），而不是加机器。

## 验收（只报 label 变了等于没验）

1. `/station/status` 该路：`online=true` · `label` 是中文名 · `age_s` 秒级 · `src_age_s` 更小 · `stalled=false`。
2. `/snapshot/<通道>.jpg` 200、几十 KB、`cv2.imread` 出 640×480、均值不是黑。
3. 🔴 **两处取帧互证**：同一时刻取「源机器直取」与「页面这格」两张，算灰度相关系数
   —— 实测 **0.9974**（亮度同为 159.0）才算“这格真的是那台相机”，而不是某处缓存的旧图、
   或另一个相机的画面。比“label 对了”“有 200”都硬。
4. 三/四个 unit 全 `is-active` **且 `is-enabled`**（重启后要自己回来）。

## 坑

- 🔴 **cv2 对只有 YUYV 的 UVC 设 `CAP_PROP_FOURCC=MJPG` 会把格式协商搞崩**：
  `VideoCapture` 打得开但 `CAP_PROP_FRAME_WIDTH/HEIGHT` 报 **0×0**、`read()` 全失败。
  修法：`cv2.VideoCapture(dev, cv2.CAP_V4L2)`（失败再回退默认），**只设尺寸/帧率、不碰 FOURCC**，
  用 `v4l2-ctl --list-formats-ext` 确认它本来就是 YUYV。
- 🔴 **相机名/节点别写死**：同一台 UVC 常暴露两个节点（一真图一 metadata），先按卡名+有无像素格式解析。
- **源机器如果只有产线网口**，本机无法直连 HTTP ⇒ 走 ssh -L 隧道，目标写 `源机器:127.0.0.1:8812`
  （在源侧解析，不需要它监听 0.0.0.0）。
- **通道名有别人在用就要提前说耦合**：`local2` 原先指 MAXHUB 顶摄，现指这台中央相机；同名字段在
  其它页面/服务（AR 页、安全层）可能有各自的 local2，别以为改一处全站都变了。
- **该相机没有深度、没有内参**：当“全景看一眼”够用，当判据图不够（640×480 下丝印/标签全糊）。
