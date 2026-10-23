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

## 训练编排器 (视点攒够自动开训, 不重复训)

- 视点判据与质检门同口径: 平移 **5mm** + 姿态 **0.57°(0.01rad)** 量化成簇; 触发 = **视点 ≥30 且 ≥90s 没有新帧**
  (后者说明这一段走完了)。单独看帧数会误判 —— 同一视角连拍能让帧数上万而视点仍是 1。
- 用 `会话名:帧数` 做指纹, 训过就跳过; **失败也写进指纹**(`TRAIN_FAILED`), 否则每轮轮询都重试一次、把机器堵死。
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
