# 边走边建图(深度+位姿累积) —— 与 3DGS 是两条产物, 别混着交付

用途: 现场「我动, 你同时建图」时, 用**臂上深度相机 + TCP 真值**实时累积一张 base 系地图。
零 GPU、零训练, 秒级出图; 但它是**点云地图**, 不是 3DGS 高斯资产。

## 1. 什么时候用这条, 什么时候必须走 3DGS

| 需求 | 走哪条 | 理由 |
|---|---|---|
| 现场想边动边看地图在长 / 判覆盖够不够 | 本条(深度+位姿累积) | 每帧 0.1s 级, 不动 GPU, 不占 4060 |
| 要仿真底图 / 新视角渲染 / 手机拖转着看 | 3DGS(gs_capture → gs_dataset → gs_train) | 需要 RGB 逐帧 + 位姿, 训 30000 步 |
| 只采了深度、磁盘上没有 RGB 帧 | **只能交付点云** | 3DGS 无 RGB 训不出来, 别承诺 |

判据(10 秒): `ls -d ~/zmax_data/gs_scan/* ~/zmax_data/gs_map/*` 有没有会话目录。
没有会话、只有深度扫掠帧 ⇒ 只能给点云, 交付时**必须写明"点云地图, 不是 3DGS"**。

## 2. 累积器的最小口径(踩过的三条)

- **位姿唯一依据只认一套**: `/robot/tcp_pose`(手眼同源)或 `tcp_out/latest.json`, 别混用两个源做同一张图。
- **关键帧触发 = 位移 ≥25mm 或转角 ≥8°**。按时间记帧会堆一堆同视角重复点(只涨点数不涨覆盖)。
- **深度双端截断**: 只收 `50mm < z < 2000mm`(D405 无效值是 65535×0.1mm=6553.5mm), 否则包络被撑到米级。
- 体素去重(8~15mm)+ 每次 dump 写 `points.pcd` + `map_meta.json`(kf/points/bbox/tcp/ts/src)。
- 守护进程用 `setsid nohup ... </dev/null >/dev/null 2>&1 &` 起 —— 普通 `nohup ... &` 在 ssh 会话结束时会被带走。

## 3. 「点够了么」怎么答(不要凭感觉)

三个数一起报, 缺一个都说明不了覆盖:

1. **关键帧数 kf**: 停在 1 说明位姿没变(人没动)或位姿源冻了。
2. **累计体素**: 从起图到现在涨了几倍(每帧新增体素的量级应稳定)。
3. **包络是否在扩张**: bbox 某一轴持续变大 = 新视角在补盲区; 一直不变 = 在原地重复叠同一块。

实测参考量级(同一台臂、同一工位): 起图 2.7 万体素 → 走 250mm 级横移后 30 万体素,
每次关键帧新增 3k~15k 体素; 包络从 `y[-872,1071]` 扩到 `y[-872,1507]` 才说明真的补到了新区域。

## 4. 交付件与飞书

- 点云 → PLY(二进制, 质心归零, 按高度着色) · 俯视投影 PNG · 原始 `points.pcd`。
- 发飞书用 `tools/feishu_send_file.py --text "<说明>" a.ply b.png`, 回执里有每条 `message_id` 才算发成功。
- **说明里必须写清产物类型、点数、包络尺度**, 以及"这是点云, 3DGS 还需 RGB 采集 + 训练(约 15~20 分钟)"。
  拿点云冒充 3DGS 会在下一次会话被追着问"高斯的图呢"。

## 5. 常见误判

- "建图在跑但臂不动" ⇒ 先看是不是**人没动**(kf 不涨), 再看位姿源帧龄, 别先怀疑建图代码。
- "地图一直不长" ⇒ 若深度那一路断了(发布者 0), 帧照收但全无效 ⇒ 看每关键帧新增体素是否突然掉到个位数。
- "在 intel 上建图"指的是**建库/点云累积/质检**这类 CPU 活。3DGS 训练在 intel(Arc) 上有官方 SYCL 轮(`gsplat-1.5.3+pt210xpu` 必须配 `torch==2.10.0+xpu`, 见 SKILL.md pitfall);
  端到端已实测跑完(3000 步落 `gs.ply`/`gs.splat`/`train_report.json`, 112529 高斯 / 1302.6s) ——
  **但"训得完"不等于"资产可用"**: 数据集没有 `depth/` 时初始化是随机盒, 留出 PSNR 只有 10.6~13dB,
  所以 intel 上要出资产必须先接深度初始化(见 §7)。

## 6. 取深度: 一台 D405 只能被一个进程独占, 且深度必须对齐到彩色

- **别两个进程各取一路**: 彩色走 UVC(v4l2)、深度走 vendor 接口, 但它们抢同一个 USB 设备 ⇒ 第二个进程
  `pipe.start()` 直接 `RuntimeError: xioctl(VIDIOC_S_FMT) failed, errno=5 Last Error: Input/output error`
  (EIO **不是**"相机坏了")。定式 = **一个进程同时开 color+depth**
  (`enable_stream(rs.stream.color,640,480,rs.format.bgr8,30)` + `enable_stream(rs.stream.depth,640,480,rs.format.z16,30)`),
  逐帧 `rs.align(rs.stream.color)` 后再发布。
- **为什么必须 align**: 未对齐时 depth 内参与 color 不同(D405 实测 fx 392.08 vs 394.06, cx 315.9 vs 318.4),
  而 `cameras.json` 只存一套 K(color) ⇒ 拿未对齐的 depth 反投影会整体偏 2~3 像素当量。对齐后共用 color 的网格/K。
- **换发布者前必须先放设备**: 停原服务后等 **≥20s** 再起新进程, 否则仍是 EIO(实测等 8s 还会 EIO, 等 20s 稳定);
  查占用用 `sudo fuser -v /dev/video*`。
  只 `kill` 进程没用 —— `Restart=always` 会把旧 unit 的进程再拉起来抢设备, 必须 `systemctl stop`。
  ⚠️ **不要靠 `echo 0/1 > .../authorized` 去"重置设备"**: 对相机那个端口做会把设备从总线
  摘掉(它从 `lsusb` 和 sysfs 里直接消失, 连 `idVendor` 都读不到, 只剩父 hub)。真潦了就在**父 hub**
  (`/sys/bus/usb/devices/2-1/authorized`) 上 0 → 3s → 1, 子设备会重新枚举回来;
  判据 = `lsusb \| grep -i 8086` 恢复 + `/sys/bus/usb/devices/2-1.1` 重新出现且带 4 个接口(uvcvideo)。
- **代价如实报(旧口径已纠正)**: 彩色从 5.4Hz 掉到 3.1~3.3Hz **不是 `rs.align` 的锅** —— 实测只取帧+对齐
  **26.5fps**(对齐只花 33ms, 几乎免费); 真正的开销是**把 0.9MB 图像塞进 ROS 消息**(实测 3.0fps, 0 订阅者也一样),
  定式 = 同一个进程持相机, **图像走 HTTP 全速**(25fps)+ ROS 低频保订阅方,
  见 `low-latency-camera-streaming` 的 `references/frame-rate-ceiling-diagnosis.md` §3.8。
- 深度单位: D405 `depth_scale` 实测 **0.0001 m(0.1mm)** ⇒ 16bit PNG 原样存计数即可(消费端按 `unit=0.0001` 解析);
  别存 8bit/JPEG(精度不够, `gs_depth_to_ply` 直接拒)。

## 7. 训练侧深度初始化(init.ply)的接线与验收

- **三处都要接, 缺一处就静默退回随机盒**(最难查的是第二处):
  ① 采集: 存 `<stem>.jpg` 的同时存 `depth/<stem>.png`(从桥的 `/depth.png` 取, 失败不阻塞彩色);
  ② 打包: `_submit_train` 的 tar **必须一起打 `depth/`**(原来只打 `cameras.json`+`images/` ⇒ 训练侧永远 `init_source=random_box`);
  ③ 训练服务: 有 `depth/` 时先 `gs_depth_to_ply.py --src <ds> --out init.ply` 再 `gs_train.py ... --init-ply init.ply`。
- **验收看 job, 不看日志猜**: `init_source=depth` + `init_ply_mb` 非空 + `init.ply` 合理
  (实测 1 视角 24.4 万有效像素 → 20 万点 / 10.68MB)。仍是 `random_box` ⇒ 回 ①②③ 逐处核。
- **几何自检(真数据, 不必等训练)**:
  * 手眼方向: `|T_base2cam[:3,3] - T_base2tcp[:3,3]|` 必须逐帧恒等于手眼模长(本机 **244.1mm**);
  * 单位/尺度: 点云到**相机位置**的距离分布必须与深度图吻合(实测 min 0.112 / p50 0.221m vs 深度 p50 0.203m);
  * 🔴 **相机位置 = `inv(T_base2cam)[:3,3]`, 不是 `T_base2cam[:3,3]`** —— 后者是"基座原点在相机系里的坐标",
    拿它算距离会得到 0.58~4.1m 的荒谬分布, 很容易误判成"反投影写错了"。
- **A/B 才算证明**: 同一份带深度数据跑两遍(默认随机盒 vs `--init-ply`), 报留出 PSNR 差 + 耗时。
  脚本 `tools/gs_ab_test.py <session> [steps] [tag]` 出 `ab.json`(两边 report + `delta_holdout_db`);
  交付口径仍是"有提升而非仅不回退"。实测参考(216 帧/视差 0.31m/3000 步): 深度初始化 **14.0dB**
  vs 随机盒 **13.35dB**(@1400 步同步骤对照) ⇒ 涨了但**仍不可交付**(行业可用 20dB+), 下一步该修的是采集
  (帧率/去畸变/视点覆盖), 不是再调步数。
- 单视角数据集训练会在留出划分处崩(`randint` 越界: 留出 20 > 视角数) —— 这是"数据不够"的正常拒绝, 不是深度链坏了;
  只验接线时提交 60 步, 看 `init_source`/`init.ply` 就够。
