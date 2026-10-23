# 无人值守: 臂一动就采图 + 攒够自己送训 (autocap 守护进程)

需求形态: 「建个守护进程, 只要有图像和机械臂操作就自动记录图像和位姿, 自主决定训练 3DGS」。
人不在场, 所以"什么时候算采够、什么时候该训"必须写进代码, 不能靠人点。

## 落点(两台机器)
- **采集+判定端**: `tools/gs_autocap_daemon.py` + systemd `zmax-gs-autocap` (`:8806`, `Restart=always`)。
  跑在能同时摸到相机帧和位姿源的那台机上(纯 HTTP 拉取, 无 GPU 需求)。
- **训练端**: `tools/gs_train_service.py` + systemd `zmax-gs-train` (`:8804`), 跑在有 CUDA 的机器上。
  端点 `/health` `/pose` `/job` `/splat`。
- 采集机拿不到位姿真源(真值文件在另一台)时, 把 `/pose` 也代理到训练服务, **必须带超时** ——
  一次拉取卡住会把整个采集循环拖死。

## 四个开训判据 (任一不满足就不训, 否则自己产出废资产)
| 判据 | 起手值 | 为什么 |
|---|---|---|
| 累计帧数 ≥ N | 120 | 太少学不出结构 |
| **位姿跨度 ≥ 阈值** | 5cm | 相机没动够 = 视差不足, 必糊; 这是真正的门 |
| 图像亮度 ≥ 阈值 | 12 | 全黑/过暗 = 相机没出图 |
| 冷却 | 180s | 别把训练机堵死 |

帧数够但跨度小的场子, 训出来只是一张浅浮雕 —— 跨度单独一门, 别用帧数代替。

## 三个实测踩出来的 bug (症状都是「一张不采」或「采满不训」)
1. 🔴 **运动基准取「上一次采到帧」的位姿, 不是「上一次轮询」的位姿**。
   4Hz 轮询 + 慢速扫场时每次轮询只动 0.4mm, 永远够不到阈值 ⇒ `frames_total` 恒为 0,
   而健康页只有 `skipped_static` 在涨, 看着像"机器没动"。判据: 位姿 ptp 明明非零却 `frames_total=0`。
2. 🔴 **首次没有基准时必须当作「动了」**。`moved(None, pose)` 返回 False 会让第一帧永远采不到,
   之后也永远没有基准可比 = 死锁。首帧强制放行, 采到后再建立基准。
3. 🔴 **帧被拒时不要推进基准**。过暗/过曝/拉图失败的帧不算"这个视角看过了",
   否则慢速扫场会连续跳过一串根本没采到的视角。

## 其它坑
- 落盘前按内容去重 + 亮度过滤: 重复视角对重建零贡献, 却照样拉长训练与显存。
- 提交训练要看**回执字节数**(`bytes`), 用它核"整包真到了", 不要只看 HTTP 200。
- 健康页必须同时给 `frames_total / skipped_static / skipped_stale / skipped_dark /
  sessions / trains_submitted / last_error`, 否则"没采到"和"采了但没送训"分不开。
- **`last_error` 成功之后要清空**: 不清会长期留着一条早已过去的老错误, 把排查引向完全错误的方向
  (实测训练服务重启过一次, 健康页此后几小时一直写着 `Connection refused` 而实际早已连通)。
- 拿假位姿/假图(本地 mock 服务)先把回环跑通, 再上真机 —— 在真机上调试"为什么不采帧"的代价是现场时间。

## 已有真机实测(可作基线)
338 帧 / 位姿跨度 0.54m / 21.6 分钟连续扫场 → 自动打包 12.5MB → 1000 步 → 留出 PSNR **14.17dB** ·
10 万高斯 · 3.2MB splat · 训练 18.7s。全链路无需人工介入。

⚠️ **但这个 PSNR 不能当"成了"报**: 1000 步只是"铺完颜色就走人"。实测同一场的渲染图 std 只有真值的一半
(27.6 vs 65.2 / 14.1 vs 54.1), 视觉上就是糊。标准 3DGS 要 30k 步 ⇒ **自动闭环给的步数必须够**,
否则每次自训都稳定产出一版废资产, 而且是无人值守地反复产出。
⚠️ **位姿来源决定上限**: 用单目 SfM(`mono_sfm`)估的位姿 + 猜的内参(默认 focal 768)训, 加步数也上不去。
臂上相机就该走 TCP 真值 + 手眼 + 真内参(见 SKILL.md「核心取舍」与 `models/real_cam_calib.json`)。
报效果时给标准差对比与 PSNR 一起, 别只给 PSNR 一个数让人以为还差一点。

## 变体: 在训练机上直接吃 ROS2 话题 (免工位机 JPEG 中继)

采集与训练都在同一台 GPU 机上时(相机流、臂真值都在同一个 ROS2 域), 不必绕工位机中继: 订阅话题少一跳,
也不受中继帧率上限约束。实测可用话题: `/realsense/color/image_raw`(bgr8) · `/realsense/depth/image_rect_raw` ·
`/robot/tcp_pose`(PoseStamped, base_link)。

- 🔴 **位姿话题是 BEST_EFFORT**: 用默认 RELIABLE 订阅会打印 `offering incompatible QoS. No messages will be received`,
  **一条都不进**(位姿恒 None ⇒ 采集器一帧不存, 看着像"相机没出图")。两个话题都显式
  `QoSProfile(depth=2, reliability=BEST_EFFORT)`; 判据 = 启动日志里没有那条 incompatible 警告。
- 存帧门 = **位姿变化**(位移 ≥6mm 或四元数夹角 ≥1.5° 才落盘), 与 md5 去重互补: 臂不动时 24 帧只存 1 张是正确行为。
- 每帧记 `mono_ts` / `pose_mono_ts` / `pose_age_ms` / `wall_ts` + 位姿(x,y,z,qx..qw); 帧龄 >600ms 或 <−20ms 直接拒。
- **schema 必须与 `tools/gs_dataset.py` 对齐**: 它读 `t_mono_fetch1` 与 `pose_after`/`pose_before` ⇒ 写记录时这几个键一并写
  (自己另加 `mono_ts`/`pose` 不影响), 否则建库时帧被静默丢掉、表现为"采了但数据集里没有"。

## 🔴 Intel 侧「默认一动就采」为什么一张都不采 (实测 2026-10-23)

守护 `zmax-gs-autocap.service` 在 Intel 是 **enabled+running、GS_AUTOTRAIN=1**, 但 17.5 小时只积到
`frames_total=1 / sessions=0 / trains_submitted=0 / skipped_dark=68233`, `last_error=位姿拉取失败 urlopen timed out`。
根因不是守护逻辑, 是 **两个源都指向从 Intel 根本不可达的地址**:

| 配置 | 值 | 为什么拉不到 |
|---|---|---|
| `GS_FRAME_URL` | `http://192.168.23.66:8792/frame.jpg` | Orin 上这个端点绑 **127.0.0.1**, 别的机器一律拉不到 (且 Intel 实测 6s 超时) |
| `GS_POSE_URL` | `http://192.168.23.50:8804/pose` | 工位机不在产线网段时(例: 只在 WiFi 10.163.x) 整台不可达 ⇒ 6s 超时 |
| `GS_TRAIN_URL` | `http://192.168.23.50:8804` | 同上; 攒够了也送不出去 |

真源其实 **Intel 本地就有**(不用绕中继、不依赖工位机在线):
`/realsense/color/image_raw`(bgr8 640x480, 实测亮度 119, ~1.6~1.75fps) + `/robot/tcp_pose`
(PoseStamped, `base_link`, header 带时间戳; 两者都是 **BEST_EFFORT** QoS)。

定式 = 本地桥, 契约与 8804 逐字段一致: `tools/gs_ros_bridge.py` + `zmax-gs-ros-bridge.service`
(127.0.0.1:**8811**; 8810 已被 evolve 服务占) 提供 `/frame.jpg` `/pose` `/health`, 然后把 autocap 的
`GS_FRAME_URL`/`GS_POSE_URL` 指向它。
- 🔴 **四元数→rpy 必须是 ZYX**, 才与 rokae `endInRef` 的 rx/ry/rz 同口径(实测同一时刻与 SDK 直读吻合到 1e-5);
  换一套欧拉约定会把整份数据的姿态拧掉, 且 `_moved` 门看不出来(它只比差值)。
- 判据(修好后 20 秒内可见): `last_error` 清空 · `skipped_dark` 不再涨 · `skipped_static` 上涨(臂没动就该涨) ·
  `images/f_0000.jpg` 落盘。
- 采集落盘是 **逐帧 JPEG + 每帧位姿 + 时间戳**(`images/f_NNNN.jpg`), 不是 mp4 视频; 问“有视频么”要按这个口径答。
- 还剩的两道门(采集通了也不等于能自训): ①`GS_TRAIN_URL` 仍要一台可达的 CUDA 机(Intel 上 3DGS 只验证到 SYCL
  栅格化, 完整训练循环未通) ②`GS_TRAIN_STEPS` 默认 **1000** = 铺色阶段, 留出 PSNR ~14dB / 渲染 std 只有真值一半,
  要像样得 30000 步(4060 上 15~20 分钟/版), 无人值守自训要么提步数要么在门上加"步数不足"标记。

## 550C(Intel Arc B390) 本地训 3DGS: 已跑通完整循环, 但慢 70~80 倍 (实测 2026-10-23)

`gs_train.py` 已自带后端选择(cuda→xpu 自动), `gsxpu-venv` 里 `torch 2.10.0+xpu` +
`gsplat 1.5.3+pt210xpu`(SYCL)。实测同一个 338 帧数据集在 Intel 上跑完整个循环(不是只栅格化):

| 项 | 实测 |
|---|---|
| 端到端 | ✅ 200 步跑完, 落 `gs.ply` + `gs.splat`(502.4s 训练 + 首次 SYCL 编译 ~90s) |
| 步速 | **~2.5 s/步**(进程 99.9% CPU, 瓶颈在宿主侧而非 Arc) |
| 30000 步折算 | **≈21 小时**(4060 CUDA 同配置 15~20 分钟 ⇒ 慢 ~70~80×) |
| 启动特征 | 前 2~4 分钟日志只有 `gsplat: Using SYCL XPU backend.`, 不要当卡死(首次编译) |

定式: **采集/建数据集/质检放 Intel(不占 GPU), 30000 步正式训练送 4060**。要在 Intel 上出东西只有"预览版"
(3000 步≈2 小时), 必须标明不是交付资产。判据: 先报步速再谈方案, 不要拿"能跑"当"能用到闭环里"。

### 一轮跑不起来时的两个真故障 (实测, 按这个顺序查)

1. **建库步 `ModuleNotFoundError: No module named 'cv2'`** —— XPU venv 里只有 torch/gsplat。
   别软链系统 `cv2*.so`: 系统 cv2 是 numpy1.x 编的, venv 是 numpy 2.x ⇒ `ImportError: numpy.core.multiarray failed to import`。
   也别指望 `pip install opencv-python-headless`: 产线机常常**没有外网 DNS**(`Failed to resolve 'pypi.org'`)。
   定式 = **建库用系统 `python3`**(系统 py3.12 自带 cv2 + numpy1.26), 训练用 `gsxpu-venv`;
   编排器里 `SYS_PY` / `PY` 两个变量分开。实测建库 3 秒过: 871 帧 → 300 帧(6D 最远点贪心)、去畸变后 fx=387.33。
2. **训练第一步崩 `IndexError: shapes [0], [0, 2]`**(`gsplat/rendering.py` 的 `opacities.view(B,N)[batch_ids, gaussian_ids]`)
   —— SYCL 后端在**空 tile 交集 (nnz=0)** 时退化, CUDA 后端不报。先证明后端本身没问题(10 万高斯 + `sh_degree=2`
   直接 `rasterization` 应出非零唯一色), 再证明几何没问题(把初值点投到每台相机, 统计"z>0 且落在画面内"的台数)。
   两者都正常 ⇒ 就该视角**重抽**: `try: render(c) except IndexError: 换一台相机重抽`, 连续 20 次才抛错。
   判据 = `--smoke 200` 跑完并落 `gs.ply/gs.splat`(别拿"能 import gsplat"当"能训")。

## 🔴 采集端没做「内容 md5 去重」= 自训稳定产出废资产 (实测 2026-10-23 第一版自动资产)

第一版全自动跑通（机器人动 → 采 124 帧 → 自动送 4060 → 30000 步 → 763k 高斯）但质检 **FAIL**:

| 判据 | 实测 | 结论 |
|---|---|---|
| unique_images | 唯一图 **47/124 (重复 62.1%)** | 同图配多位姿 = 矛盾监督 |
| distinct_views / parallax | 122 个 / 1.46×1.36×1.28 m | 视差与视点都是够的 |
| beats_trivial | 留出 **10.90 dB** vs 平凡基线 **12.18 dB**（−1.28） | 连拟合都没做到 |
| fits_training_views | 训练视角 21.36 dB（+9.18） | 只记住训练帧 |

根因 = 相机只有 ~1.2fps，而臂快速移动时**同一张画面被反复落盘并配上不同位姿**。守扤的
`_moved` 门（位移 ≥2mm）只看位姿看不画面，于是同一个 pose 变一下就存一张同一张图。
定式: 抓到图后算 **md5，与上一张真正落盘的图相同就不落盘、也不推进基准**（计数器单独一个
`frames_skipped_dup`，否则“重复太多”与“臂没动”在健康页上分不开）。
配套把门抬高: `GS_MIN_FRAMES 120→160`、`GS_MIN_SPAN_M 0.05→0.10`（5cm 跨度只能保证“不是同一位姿”，
不保证视差）。

## 训练编排器 (视点攒够自动开训, 不重复训)

- 视点判据与质检门同口径: 平移 **5mm** + 姿态 **0.57°(0.01rad)** 量化成簇; 触发 = **视点 ≥30 且 ≥90s 没有新帧**
  (后者说明这一段走完了)。单独看帧数会误判 —— 同一视角连拍能让帧数上万而视点仍是 1。
- 用 `会话名:帧数` 做指纹, 训过就跳过; **失败也写进指纹**(`TRAIN_FAILED`), 否则每轮轮询都重试一次、把机器堵死。
  🔴 **反过来也成立: 修好故障后必须把对应的 `*_FAILED` 指纹清掉**(先备份 `state.json`)。不清 ⇒ 同一指纹永不重试,
  现场看到的是"故障已经修了但一动不动", 很容易再去找一个不存在的第二个 bug。
  🔴 **判活只看成功标志数**: `grep -l '训练完成\|gs.ply' gs_assets/train_*.log | wc -l`, 结果为 **0** 就是"一版都没成过",
  哪怕守护 active、日志一天十几个。再配合 `grep -c DATASET_FAILED state.json` 与"两份日志报错是否逐字相同"定案。
  🔴 多个 `gs_auto_train.py` 实例并存时按**显式 pid** 清到一个(它们会互相覆盖同名日志、时间线无法还原)。
- 产物目录带 `status.json`(`ready` / `sent`), 推送端只按这两个标志取件、推完置 `sent=true` 保持幂等(不重发)。
- `state.json` 要给 `views / need_views / pose_span_mm / idle_s` —— 现场问"还差多少"时直接念数。

## 从外网推资产到飞书 (两跳, 不把密钥搬到 GPU 机)

- 链路 = 笔记本 → 公网跳板(如 `39.102.211.79:22022`) → 内网 GPU 机; paramiko 的 `direct-tcpip` 通道两跳即可, 不必开 VPN。
- 🔴 **飞书密钥不要复制到 GPU 机**: 密钥在本机 `~/.hermes/.env`(不在 `zmax_data/secrets/zmax.env`), 所以推送在笔记本上做、只把产物拉回来(SFTP 读字节写本地文件)。
- 定时推送挂 no_agent cron, 脚本**无产物时静默**(空 stdout 不打扰), 有产物才出声。
- 🔴 **部署远端脚本别用嵌套 heredoc**: `ssh host 'cat > x.sh <<EOF … $V/bin/python … EOF'` 里的 `$V`/`$(date)`
  会在**外层**先展开(实测写成 `/bin/python`, 起来就报 `No such file or directory`, 而外层命令 exit=0 看着像成功)
  ⇒ 远端脚本一律走 SFTP(`sftp.put` / `scp`) 写文件, 或 heredoc 定界符加引号 (`<<'EOF'`);
  起完必须回读一次脚本前几行 + 目标进程 `pgrep` 真在。
- 🔴 **paramiko `exec_command('… &')` 会把通道挂住**(读输出超时): 后台起进程要么先 `open_session()` 发完就 `close()` 再另开连接读日志, 要么把 stdout/stderr 全重定向到文件。
- 🔴 **`pkill -f "[g]s_auto_train"` 会把包装它的那个 shell 一起杀掉**: 方括号技巧只防"匹配到自己这条", 而 `bash -c "… [g]s_auto_train …"` 的**命令行本身就含这段字面量** ⇒ 整个 shell 被杀, 表现为"命令发了但什么都没起"(`tail` 那个日志文件都不存在)。停进程写脚本 / 用 pidfile, 别在 exec 里内联 pkill。
