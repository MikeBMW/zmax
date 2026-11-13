# 550C 读臂相机 + 3DGS 建图落地 (Intel 主机实做)

## 550C 为什么曾经看不到臂相机
- 4060 的 8793 是 `--arm-http http://<orin>:8794/frame.jpg` 直拉 Orin 中继 ⇒ 一直有画面。
- 550C 两条路都断：
  1. 采集守护指 `8792` —— 那条中继彩色口被 `d405_color_pub` 独占，线程崩在 `set(CAP_PROP_FRAME_HEIGHT, None)` ⇒ 永远 `no frame yet n=0`。
  2. `8811` ROS 桥只认 `/realsense/color/image_raw`，跨机 DDS 发现被网络隔断 ⇒ `Publisher count: 0`，桥永远空图。

## 修法(已落地)
- `gs_ros_bridge.py` 增 HTTP 帧源：`GS_FRAME_URL=http://<orin>:8794/frame.jpg`、`GS_FRAME_FPS=15`；ROS 帧到了照样覆盖，谁新用谁。drop-in: `/etc/systemd/system/zmax-gs-ros-bridge.service.d/zz-http-frame.conf`。
- `zmax-gs-autocap` drop-in `zz-local-src.conf`：`GS_FRAME_URL=8794`、位姿 `8811/pose`(ROS)、深度关(`8794` 不供深度，8793 的 depth 是旧图)。
- 验收口径：`8811/health` 要 `ok=true, enc=http/jpeg, fps>10`；抓回的帧与 8794 实时帧 **NCC=1.000** 才算同源。

## 色彩会直接烘进训练集
- 臂相机走 UVC 裸流(`d405_color_pub` 直接开 `/dev/video*`, 只设 gain), 绕过 RealSense SDK 的自动白平衡 ⇒ 实测 R79/G103/B120(蓝高 41)、饱和度 93 —— **彩色但发蓝**，不是灰度。判「黑白/偏色」先做像素取证(见 `camera-frame-forensics`)。
- 定色彩要在**本轮采集开始前**做；设备被独占时 `VIDIOC_ENUM_FMT`/`QUERYCTRL` 全返回空，跑着改不了；中途重启 pub 会让一轮数据前后白平衡不一致。

## 采集守护会「跳变死锁」——臂被开走后永久不采
- 症状：`8806/health` 的 `frames_skipped_jump` 涨到几万、`frames_total` 冻住、`last_error` 为空。
- 机制：跳变判据的基准是「最后一次**采到帧**的位姿」。臂被开走超过 `GS_MAX_STEP_M`(5cm) 后每帧都判太远 ⇒ 基准永不更新 ⇒ 再也不采。
- 修法：连续 `GS_JUMP_RESET_N`(默认 15) 次跳变即把基准挪到当前位姿继续采，计数落 `_jump_realign`；改完重启 `zmax-gs-autocap`。
- 判活口径：臂在动时 `frames_total`/`cur.frames` 应该在涨(实测约 1.6 帧/s)；只涨 `skipped_static` = 臂没动，只涨 `skipped_jump` = 基准死了。

## 数据从哪来(按优先级)
1. 右臂跑真实轨迹(8797 逐点回放)—— 视差最好(215 点实测路径 7.9m、累计转角 952°)；一轮约 23 分钟采到 **1352 帧**、自动提交 2 个训练作业、`_jump_realign` 91 次(回放一直在推基准，属正常)。
2. 历史采集会话 → `gs_map_from_history.py`(零运动，不需要真动授权)。
3. `gs_map_run.py --manual` 人工走点 —— **臂不动时它会假装在跑**：每轮因「唯一图像 0 张 / 重复率 100%」失败但 `running` 仍 true。判据看 `run.log` 的「唯一图像」，不要看 running。

## `gs_map_from_history.py`(零运动建图)
- `--session <会话>` / `--ds <已有数据集>` / `--latest`；`--dry` 只体检+打包；不带 `--dry` 就 tar 后 POST 本机 `8814/train` 排队，写 `~/zmax_data/gs_map/status.json`。
- `gs_dataset.py` 的 HANDEYE 已改成多路径探测(`GS_HANDEYE` → `~/zmax/zmax_data/` → `~/zmax_map/models/` → `~/zmax_data/`)，因为 550C 没有 `~/zmax` 这棵树。
- **采集会话有两种形态，构建器只认一种就炸**：
  - 采集守护新会话 = `images/ + cameras.json + session_meta.json` ⇒ **本身就是数据集**，按窗口裁最后 N 帧即可(`os.link` 硬链接零拷贝，改 `cameras.json.frames`)；
  - 老会话只有帧+位姿 ⇒ 才走 `gs_dataset.py`(内部读 `frames.jsonl`)。把新会话喂给旧构建器会报 `FileNotFoundError: frames.jsonl`。

## 实时建图 = 节点执行体 (不是另开一条链路)
- 三件套与四个坑(节点块必须前置 metaworld 解耦、常驻循环不读 `ZMAX_CANVAS_ONLY`、两种会话形态、守护 flock 单实例)见 `state-space-canvas-engineering/references/realtime-mapping-node.md`。
- 实时默认预算 `RT_TRIGGER=80` 帧 / `RT_WINDOW=400` 帧 / `RT_STEPS=400`，systemd `zmax-gs-realtime-map` 常驻；与 8814 批量队列共卡用 `RT_IGNORE_BUSY=1`（实时是产品要求，不因排队饿死）。

## 训练预算 ↔ 质量(同一套 550C 数据实测，别夸大)
| 步数 | 用时 | 高斯 | PSNR holdout |
|---|---|---|---|
| 3000 | 1557s | 109193 | **15.07** (train 15.96) |
| 400 (共卡) | 334s | 100000 | **10.55** |
| 400 (第2轮热启动) | 92s | 100000 | **13.22** (train 14.25) |
| 400 (第3轮热启动, 900帧窗口) | 174s | 100000 | **13.61** |
| 600 (单会话 900 帧, 外圈叫 1500 步) | 140s | 100000 | **13.38** |
| 150 | 155s | 100000 | **8.73** |
- 热启动把同 400 步的质量从 10.55 抬到 13.2~13.6 dB、耗时 334s→92~174s(3.6× 收敛)；同一个 PSNR 平台说明**再加轮次收益递减**, 要往上只能扩视角/加步数。
- ⚠️ **外圈要求的步数不一定生效**: 实测 `HERO_STEPS=1500` 外层日志照打, 报告里 `steps=600` ⇒ 报数/ETA/比质量一律取 `train_report.json`。
- 结论口径：≤10 dB 是「能出图」，≥18 dB 才算可用重建；质量只能靠**多轮 warm start(`--init-ply 上轮 gs.ply`) + 臂持续走动扩覆盖**。历史 859 帧那版只有 12.08 dB(帧多但视角集中)，历史最佳 17.48 dB。
- 报数必须写清 holdout 还是 train；两者差 ~1 dB 时优先信 holdout。

## 设备/性质(被问过多次，直接答)
- **GPU 不是 NPU**：`gs_train.py` 设备顺序 `cuda → xpu → else`，无 NPU/OpenVINO 分支；运行时 `torch 2.10.0+xpu`、`xpu_available True`、`Intel Arc(TM) B390 GPU`、`cuda_available False`；`gsplat` 走 SYCL。
- **不是 SLAM**：位姿来自 `/pose`(ROS 臂 TCP 真值) + 手眼 `T_cam2tool` + D405 内参；源码搜 `odometry/loop_close/feature_match/pnp/icp/orb` 全空。精度上限由臂真值+手眼决定(实测残差 0.06mm/0.0046°)，代价是必须动臂。
- 产物：`gs.ply`(含 `f_dc`/`f_rest` 球谐) + `gs.splat` + `renders/`；`sh_degree=2`。

## 发布与查看(跨机同步方向别搞反)
- 资产落 `~/zmax_data/gs_assets/<name>/`；8793 的 `/gs/list`、`/gsview`、`/gs/latest.splat` **只读本机(4060)** 的 `gs_assets`。
- 550C 到 4060 **没有 ssh 免密** ⇒ 不要设计「550C 推送」；在 4060 侧挂 5 分钟 rsync 拉取(`*/5 * * * * rsync -a -e "ssh -o BatchMode=yes" intel:.../gs_assets/rt_live/ ...`)，拉完 `/gs/list` 的 `latest` 就是 `rt_live`。
