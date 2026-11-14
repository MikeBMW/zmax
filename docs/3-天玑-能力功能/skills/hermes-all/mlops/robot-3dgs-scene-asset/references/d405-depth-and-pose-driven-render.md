# D405 彩色+深度 与 位姿驱动 3DGS 推流（550C + Orin 实测）

## 1. D405 一个设备只能有一个持有者
- 彩色走 UVC（`/dev/videoN` + cv2）时，深度走 vendor（pyrealsense2）会直接失败：
  `xioctl(VIDIOC_S_FMT) failed, errno=5 (Input/output error)`。
- 正确架构：**单进程 librealsense 同时取 color+depth**，并 `rs.align(rs.stream.color)` 把 depth 对齐到 color
  （同一像素网格/K，建图初始化点云才对得上）。
- 落地：`d405_cd_pub.py` + `d405-cd-pub.service`（Orin）；停掉 `d405-color-pub.service` 释放 UVC。
- 判据：`ros2` 话题 `/realsense/color/image_raw` + `/realsense/depth/image_rect_raw` 同时在，
  `depth_meta.json` 的 `valid_pct` 有值（实测 86~88%）。

## 2. 深度源断了，页面会“假装正常”
- 页面读 `~/zmax/zmax_data/ss_live/zmax_scene/depth_raw.npy` + `depth_meta.json`；
  源断时只是**旧帧一直显示**，不报错 ⇒ 先 `ls -l` 看 meta 文件龄（踩过：18 天没更新）。
- `cam_live_stream.py` 里的 `_depth_worker` 只在**服务启动那一刻**起线程：老进程跑着新代码 ⇒ 线程根本不存在。
  判据：`py-spy dump -p <8793 pid> | grep '"depth"'`，没有就是没起，必须重启 8793。

## 3. 跨机别拿两边时钟相减当帧龄
- Orin 与 4060 都可能有时钟偏差（NTP 回拨遗留），`meta.t` 直接相减会得出“深度图 170s”这种假陈旧。
- 拉取侧（`zmax-depth-pull.service`，1.5s 一轮）把 `meta.t` 改写为**本机时间**、`src_stamp_age_s=0`，
  真实延迟就等于拉取周期；两边钟差单独记 `clock_skew_s` 留档。
- `scp`（SFTP 模式）会把源 mtime 带过来 ⇒ 不能用 mtime 判断“有没有更新”，直接改写即可。

## 4. “手臂相机为什么那么黑” 的量化诊断
- 分层量：**裸设备帧均值**（关服务后 cv2 直读）vs **发布帧均值**。实测 101 → 63：
  白平衡那级 `(f - 黑电平) × 增益(0.885~1.267)` 把均值压掉 4 成，中央相机是 143 ⇒ 肉眼就是“黑”。
- 相机侧旋钮没用：gain 已顶（cv2 设 240 不生效，读回 16），曝光 100/166/300/500 反而更暗 ⇒ 只能软件补。
- 正解：WB 之后加**带限幅的自动增益 AGC**（`AGC_TARGET=112`、k∈[0.75,2.6]、指数平滑防闪烁）⇒ 均值 111。
- 验收口径：`R/G≈1.00`、`B/G≈1.01`（不许偏青）+ 均值接近中央相机 + 饱和度正常（~36）。

## 5. 3DGS 要跟着机器人实际位姿（不是环绕路径）
- 渲染端 `gs_render_stream_intel.py` 已经支持位姿驱动：读 `/tmp/arm_tcp_pose.json`（`--pose-max-age 0.8s`）。
- 该文件由 `gs_arm_pose_pub.py` 订阅 `/robot/tcp_pose`（50Hz）写盘，用 ROS 侧解释器跑（渲染侧是 gsxpu-venv，不能混装）。
- 文件缺失/过期 ⇒ **静默退回 `src=tour` 环绕路径**（很糊）⇒ `:8816/health` 里 `src` 就是判据：
  期望 `src=arm · view=手臂相机实时视角 · pose_age_s≈0.02`；出现 `src=tour` 就是没喂上位姿。

## 6. 推流选模型：PSNR 择优 + ds 兜底
- `gs_render_loop.sh` 的 picker 只认真实训练产物：`gs.ply` + `train_report.json` + ds 里有 `cameras.json`。
- 大训练产物的 ds 常常**不在** `gs_rt/ds_*`，而在当初 `--data` 指的会话目录 ⇒ 老逻辑 `continue` 跳过，
  永远只选实时那份 400 步 / 10 万高斯（PSNR 15.1）⇒ 画面糊。
- 修法：`cameras.json` 的存在性放到读完 report 之后判，缺了就回退 `report['data']`；谁 PSNR 高用谁。
- 实测：445,521 高斯 / 17.22dB 那份 vs 100k / 15.10dB，清晰度（Laplacian 方差）1.4 → 11.0。
