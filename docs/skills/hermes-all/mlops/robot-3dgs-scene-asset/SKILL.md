---
name: robot-3dgs-scene-asset
description: "Use when 机器人扫场把环境重建成 3DGS 数字资产(仿真用)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [3dgs, nerf, gaussian-splatting, sim-asset, robot-camera, handeye, zmax, capture]
    related_skills: [real-handeye-calibration, real-arm-handeye-calibration, sim-real-scene-overlay, cross-venv-model-canvas-node, zmax-scene-engineering, local-vlm-scene-understanding, zmax-state-space-architecture]
---

# 机器人扫场 → 3DGS 数字资产 (仿真测试底图)

## When to Use
- 老倪说「(L5 自主运行/自主学习阶段) 建立当前环境的 3DGS 数字资产, 用于算法仿真测试」「你来同时生场景」「扫描/重建场景」「建数字资产」。
- 要给检测/策略做**仿真回归底图**, 或要仿真-真机同口径对照而缺场景几何。
- 已有采集数据, 要重建/重训/导出资产, 或采集画质/覆盖不够要重扫。

## 核心取舍: 位姿已知 ⇒ 不走 COLMAP/SfM
臂上相机随臂动 = 白送的多视角 + **每个视角都有真值位姿**(50Hz TCP 真值 + 手眼残差 0.06mm)。
所以: **相机外参 = 算出来的, 不是 SfM 解出来的**。省掉整条最脆的链(SfM 失败/漂移/尺度不明), 快且可复现。
只有“相机不在臂上/无手眼”时才退回 COLMAP(这条腿未验证, 别当推荐)。

## 数据源 (本机实测, 只读, 不动在役链路)
| 用途 | 路径/端点 | 实测 |
|---|---|---|
| 臂上 D405 图 | `http://192.168.23.66:8792/frame.jpg` (Orin `rs_fast_node` 压好的 JPEG) | 200 · ~27KB · **640x480** · 可 8~30Hz |
| TCP 真值位姿 | `~/zmax_data/rokae_sdk/tcp_out/latest.json` | 50Hz; 字段 `x y z rx ry rz qx qy qz qw` + `ts`/`t` + `frame:"base_link"` + `joint[12]` |
| 手眼 | `~/zmax_data/handeye_state.json` | `T_cam2tool`(4x4) + `resid_trans_mm_rms`/`resid_rot_deg_rms` + `views` |
| **内参 K + 畸变** | 仓库 `models/real_cam_calib.json` | `K=[394.0623,393.4724,cx 318.4436,cy 238.6584]` · `dist` 5 参数 · `image_size 640x480` · `K_src`=ROS `camera_info`; ⚠️ 它的 `T_base_cam`/`plane_z` 是 **null**(要自己用 `handeye_state.json` 算) |
| 采集器 | 仓库 `tools/gs_capture.py` (--out/--hz/--secs) | 取图 8.19 次/s · 取图 2.4ms; ⚠️ **这个端点的有效出帧率实测只有 ~0.5fps**(10s/80次取图只出 5 张唯一画面) ⇒ 已加"内容 md5 不变不落盘" + 汇总 `unique_images`/`cam_eff_fps` |
| 落盘 | `~/zmax_data/gs_scan/scan_<时间戳>/` | `frames/*.jpg` + `frames.jsonl` + `session_meta.json` + `capture_summary.json` |

- 另两条慢路: 容器内 raw tap(`ros_arm_tap_raw.py` → /dev/shm, 相机原生 ~1.92Hz, 带 meta) 与 DDS 落盘(`cam_rs.png`)。要实时性就走上面那条高速 JPEG。
- **内参 K 不在采集数据里**: 重建前必须拿到与取流分辨率一致的 D405 内参(Orin 节点 meta / RealSense 出厂标定 / 现场标定)。分辨率与 K 不匹配 = 重建整体错位, 先核这一步。
- 手眼**不要**去 `calib_report_*.json` 拿: 那份的 `解算器.已标定=false`、`手眼=null`(是空报告)。真值在 `handeye_state.json`。

## 流程
1. **先立采集, 再谈重建**。数据错过就没了: 用户说“一会我就动”时, 立刻起采集后台, 再去做环境/训练/接线。
   收工用**会话目录里的 `STOP` 文件**(优雅停, 落 `capture_summary.json`); 别 kill。
   ⚠️ **同一会话目录里多轮采集必须续帧号**: 每轮从 0 起编号会让第 N 轮的文件名覆盖第 N-1 轮
   (`frame_000001.jpg…`) ⇒ 只剩最后一轮的画面(多轮建图尤其致命)。判据 = 两轮文件名不重叠(或会话里唯一图数 ≈
   各轮之和)。
2. **采集期间给操作员动作口径**(直接发给他, 别省略): ~30~80mm/s; 加**高度 + 俯仰/侧移**变化, 别只平移一条基线; 相机主要对着工作台/工件区; D405 最近 ~7cm 别贴死; 停在一处不用停久(重复视角无用)。
3. **配对必须用单调时钟**: 墙钟会被 NTP 回拨(本机差 8h)。每帧在**取图前后各读一次位姿** + 记 `fetch_ms`/`pose_t_gap_ms`, 后处理按单调时刻最近邻取; **负帧龄一律拒**。
4. **重建**: 逐帧算 `T_base_cam`, 导出后训练 3DGS。公式/schema/导出格式见 `references/capture-and-pose-math.md`;
   **用 gsplat 自写训练器的骨架/API/归一化/导出与本次真坑见 `references/trainer-with-gsplat.md`**
   (gsplat 的 pip 包只有库、没有 trainer; 交付物优先出 `.splat` + 网页查看器链接, 用户能自己拖转看)。
   - **必须先量相机位姿跨度再决定要不要训**(`np.ptp(pos)`): 只有几十毫米(操作员原地微调观察点) ⇒ 视差不足,
     只能出一张"浅浮雕", **不是环境资产** —— 当场跟用户说清"这只能做小基线验证", 要资产先要一次大范围扫掠。
   - **先去畸变再训**: 3DGS 是针孔假设, 带畸变直接喂会让边缘几何错位 ⇒
     `Knew,_ = cv2.getOptimalNewCameraMatrix(K,dist,(w,h),0)` → `cv2.undistort(img,K,dist,None,Knew)`, **用返回的新 K**。
   - **坐标系口径只选一套并写进产物**: 自用 `cameras.json` 存 **OpenCV 光学系**(x右 y下 z前) 的 `T_cam2world`(base_link);
     对外兼容再写一份 nerfstudio `transforms.json`(OpenGL: y上 z后 ⇒ `T_cam2world @ diag(1,-1,-1,1)`)。
     两套混用/戆错翻转是 3DGS 的经典错位源，产物里写清 convention 字符串。
5. **训练环境隔离**(`tools/gs_env_setup.sh`): 用 `uv`(在 `~/.hermes/bin`) 建**独立** venv。**绝不往 `lerobot-venv` 装东西** —— 它是训练环境且是 uv 管的(里面**没有 pip**)。
   - 需编译 CUDA 扩展的包(nerfstudio/tiny-cuda-nn、diff-gaussian-rasterization、gsplat 的 JIT 版)在本机走 **gsplat 预编译轮**
     `uv pip install gsplat --index-url https://docs.gsplat.studio/whl/pt27cu128`(配 `torch==2.7.1 torchvision==0.22.1` cu128)。轮子是否命中以脚本末尾自检打印为准。
   - ⚠️ **训练必须走 `tools/run_gs_train.sh`**: 直接 `python tools/gs_train.py` 会报 `AttributeError: 'NoneType' object has no attribute 'CameraModelType'` —— 真因是 gsplat 的 CUDA 扩展 JIT 编不过、报错被吞; 该脚本包上 CUDA shim 环境(`/home/ubuntu/cuda-shim/bin/nvcc`)就好。
   - 停训练用 `tools/stop_gs_train.sh`(先取 pid 再排除自身); **内联 `pkill -f "gs_train.py …"` 会把自己的 shell 一起杀掉**(已踩两次)。
   - 4060 Laptop **8G 显存**: 同刻只跑一个模型进程; 扫场采集很轻, 但训练与在役推理别叠加。
6. **VLM 指导**(L5 视觉那条): ① 逐帧筛(糊/过曝/遮挡/无效视角)并实时提示换角度; ② 认区域/工装/工件打**语义标签**写进资产元数据; ③ 采集后判覆盖缺口 → 给下一轮**主动视角建议**(位姿级)。
7. **增强件**(按需接, 不阻塞主链): 深度监督(D405 深度图当几何约束, 比纯 RGB 稳) · **4DGS**(每帧 TCP 位姿做时间轴, 可做含臂动态的时间维资产) · **diffusion**(新视角/新光照域随机化; 把机械臂 inpainting 抹掉)。
8. **用途**: 从资产渲染任意视角/光照的“真感”图 → 喂检测/策略做离线回归; 与真机画面做同口径对照(见 `sim-real-scene-overlay`)。
9. **接进画布**: 数据层节点「3DGS 环境资产」, 输入=图像流+位姿流+L5 触发, 输出=资产路径+渲染通道; 跨 venv 子进程桥的写法见 `cross-venv-model-canvas-node`。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 用墙钟配对位姿与图像 | 全部错位/重建忽明忽暗 | 一律单调时钟; 取图前后各取一次位姿; 负帧龄拒用 |
| 去 `calib_report_*.json` 拿手眼 | 拿到 null 以为没标定 | 手眼真值在 `handeye_state.json`(`T_cam2tool`) |
| 分辨率与 K 不一致 | 重建整体错位/虚 | 取流分辨率与内参分辨率对齐(高速通道是 640x480) |
| 递归查数据根内容 | 命令跑到超时(200s 都不够) | `~/zmax_data` 是几十GB + 上万文件(还有 HF blobs): **只查定点路径** —— `search_files(pattern=…, path=<具体子目录>)` 或 `ls` 逐层下探 |
| 把包装进训练 venv | 训练环境被污染 / 没 pip 装不动 | 另建 `uv venv`; 用 `uv pip install --python <venv>/bin/python` |
| 想装需编译 CUDA 扩展的包 | 报找不到 nvcc | 用预编译轮(index 见上); 或先补 nvcc 再谈源码编译 |
| 把纯 255 过曝面/强反光金属当训练主材 | 3DGS 高斯糊成一片、看不出结构 | 过曝区无梯度: 降曝光/缩光圈, 或纯 255 区掩掉不参与损失; 必要时加深度监督 |
| 采集时把机械臂自身也拍进画面 | 臂被烤进场景, 资材里有幽灵臂 | 相机在臂上时它只对静态场景 ✓; 若其它相机/臂体入镜, 按帧位姿 mask 或 diffusion inpainting 抹掉 |
| 没先拿 K 就开训 | 跑完才发现不可用, 白烧 GPU | 采集第一天就把 K 存进 `session_meta`; 训练前先校分辨率与 K |
| 把上万帧连拍直接喂进训练 | 训练慢/显存吃紧而视角几乎不增 | **先按 6D 位姿最远点贪心抽帧**(平移 + 0.15×朝向差) 到 ~300 张 ——
同视角连拍对重建零贡献。现成工具 `tools/gs_dataset.py`(去畸变 + 选帧 + 出 `cameras.json`/`transforms.json`/`meta.json`) |
| **采集端每取必存**(老版) | 118586 次取图只对应 5830 张唯一画面(重复 95.1%), 且同一画面被存成多份、每份配**不同** TCP 位姿(最大差 193.7mm) = 矛盾监督 ⇒ 训练视角 PSNR 16.5dB、留出 11~13dB(**低于"填常数"平凡基线**) | 采集端按内容 md5 去重(内容没变不落盘, 重复只在 jsonl 记一行); 建库端再兜一层并把位姿取该图**首现时刻** |
| 渲染把 **log 域尺度**当线性尺度喂 `gsplat.rasterization` | 整帧单一纯色(唯一色=1)、PNG 1.9KB、`0 split/0 duplicate`、PSNR 平在平凡基线附近; 参数看似没动 | 渲染前 `torch.exp(params["scales"])`(官方 simple_trainer 即如此); 导出 `.ply/.splat` 才存 log/logit 域 |
| 位置学习率**不衰减** + 致密化跑满全程 | 后期 loss 回升(0.16→0.29)、高斯爆到 140 万、留出 PSNR 回落 | 指数衰减到 1e-6; **致密化在 40% 步数停**(官方 30k 训练 / 15k 停) |
| 只看 loss 降就以为建出来了 | loss 一直在降但留出 PSNR 低于平凡基线 | **判据必须与平凡基线比**: 留出 PSNR > 平凡基线+3dB 且渲染唯一色 >100 才算建出东西 ⇒ `tools/gs_quality.py` |
| 带着畸变训练 | 画面边缘几何涨开/错位(更像"优化不动") | 先 `cv2.undistort`，用 `getOptimalNewCameraMatrix(alpha=0)` 返回的**新 K** |
| 高速扫场时图像比位姿晚一截 | 运动模糊 + 位姿与像素错配 ⇒ 重影 | 固定延迟(编码+传输)按速度线性放大: ~8mm/s 时 ~20ms≈0.16mm(可忽),
30~80mm/s 时 0.6~1.6mm(占小基线 2~4%) ⇒ 每帧记**位姿龄**并按阈值拒帧, 别拿"取图那一刻"的位姿 |

## 自动闭环(L5 指导选点 → 移动 → 采集 → 建图 → 质检)
老倪 2026-10-01 口径: 「L5 功能运行后, deepseek 给出环境理解, 指导 3DGS 建图, 一边移动机器人, 一边自己学环境, 一边建立场景视图」。
一键: `~/gs-venv/bin/python tools/gs_map_run.py --rounds 7 --targets l5`
(`--dry-run` 不碰臂验链路; `--from-recording <会话>` 用录像重跑建库+质检; `--targets spaces` 兼容旧的固定 1→7 序)。
- **选点** `tools/gs_l5_select.py`: L5 只给**画面语义方向**(画面左/右/上/下/靠近/远离 + mm), 软件按手眼把
  `R_base_cam` 乘上相机系单位向量得到 base 系方向, 再在**已示教可达点**(`space_points.json` + `ctl_abs_skills.json`
  白名单)里挑 `align≥0.30` 且最没拍过的点。原因: 运动白名单目前**只有示教点类技能**, 没有任意笛卡尔原语 ⇒
  "L5 想去哪就去哪"要等开了笛卡尔点动; 到时只换候选目录, 上层契约不变。
  L5 超时/解析失败 ⇒ 自动退**覆盖度兜底**(去离已访问视点最远的可达点)并把原因写进 `l5_err`, 不假装是 L5 选的。
  ⚠️ `gen_overlay_from_vlm.call_vlm` 返回键是 **`txt`**(不是 `text`), 且 200 但 content 空是已知瞬态(内部会重试)。
- **移动**: POST `127.0.0.1:8793/ctl/move {skill:"L2.goto_spaceN"}` —— 与页面按钮同一条授权+收口链;
  到位判据 = TCP 真值 <3mm 且连续 1s 稳定; 真动前先读 `/ctl/status` 的 `motion_armed`, **未授权绝不发动作**(如实停)。
- 🔴 **跑一轮前三件必查(缺一件这轮必废)**:
  ① **授权窗要覆盖整轮**。逐条授权窗通常只有 10 分钟, 而整轮 ≈ 20~40 分钟(单轮 = L5 选点 20~60s +
     移动 ~50s + 采集 8s; 末尾还有一次完整训练) ⇒ 跑一半窗到期, 后面每步都被"真动授权未开"拦下
     (现场看到的就是"走到一半不动了")。定式: 服务端在**点"开始建图"时**(若已在有效窗内)把窗延长到
     覆盖整轮并写审计; **未授权则在按钮层当场拒并说明原因** —— 别起一个必死的后台任务:
     建图任务只在 t=0 读一次 `motion_armed`、fail-closed 一次就退出且**不重试** ⇒
     点"开始"比点"授权"早几秒就是"点了没反应"的全部原因(也不会自己重试)。
  ② **执行腿是谁**。`/ctl/status` 的 `move_transport`: 产线 ROS 栈没在跑时页面/建图这条链一步都走不动
     (臂不动、日志只有"未到位"), 要确认腿 = 本机 SDK 直连才能开跑 ——
     见 `layered-safety-gate-operations` §3g(换执行腿) —— 腿的机械细节(解析/限幅/分片/量纲/姿态口径/只读预检)
     记在该技能的 `execution-leg-swap` reference 里(不在本技能下)。
  ③ **移动速度量纲**。L2 的 `speed` 是相对量 ≈0.09~0.1 mm/s 每单位, **默认 8 只有 0.75mm/s**
     ⇒ 空间点之间 244~576mm 一段要走 ~10 分钟, 一轮都跑不完; 建图用 **120**(≈11mm/s, 仍受技能
     `speed_max=200` 收口, `gs_map_run.py --move-speed` 可调)。
     🔴 **但名义值 ≠ 实测值: 在 SDK 腿上发 120 实测只有 ~1.1mm/s**(比名义 11mm/s 再慢约一个量级;
     50mm 拍升实测 34s) ⇒ **ETA 一律按实测速率算**(先拿真值位姿差分量一段再报数), 一次「拍升+横移+下降」
     的回点实测是分钟级, 别拿名义速度除距离给现场承诺时间。
- **一段"回点"是多段计划, 不是一条直线**: 执行器会把 `L2.goto_spaceN` 展开成「就地抬升 → 保持高度横移 →
  逐段下降」(实测 4 段; 抬升相对计划起点 ≤100mm), 每段各自过闸、各自真值核对 ⇒
  单轮移动耗时 ≈ 各段之和(含段间裁决等待), 报 ETA 按段算, 别拿直线距离除速度估。
- **质检** `tools/gs_quality.py` 三层门(任一 FAIL 即停, 不把废资产当成果):
  ① 采集会话: 同一画面(md5)被存成多份且位姿不一致 ⇒ FAIL;
  ② 数据集: 唯一图 >90% · 真正不同视点 ≥50 · 位姿跨度 ≥150mm · 同一位姿画面差异 <8/255(≥5 对样本才判) · 无黑帧;
  ③ 模型: 留出 PSNR > 平凡基线+3dB · 训练视角 > +5dB · 渲染唯一色 >100。
  报告同时给 `n_gaussians`/`psnr_train_db`/`psnr_holdout_db`/平凡基线, 便于横向比。
- **增量/续训**: `gs_train.py --init-ply <上一轮>/gs.ply [--no-refine]` 从已有资产接着训(闭环里
  `gs_map_run.py --incremental --inc-steps N` 每轮采完就重建数据集+续训, 出中间资产)。
  `.ply` 读回来要自己做归一化换算: `means=S*(m_world-center)`、`scales=logS+log(米)`(归一化是纯缩放无旋转, 故安全);
  文件里 SH 是**通道优先**(f_rest 按 R/G/B 分段)⇒ 读回要 `reshape(N,3,K).transpose(0,2,1)`。
  踩坑: 载入时的临时变量名别用 `K` —— 会覆盖相机内参, 渲染时报 `'int' object has no attribute 'shape'`。
  同口径实测(同数据集/同留出/总步数相同): 增量 3000+续训3000 留出 12.24dB vs 一次性 6000 留出 10.76dB
  ⇒ 增量不劣化且过拟合更轻; 续训首评(500步)就回到上一轮水平 = 确实接着训而不是重训。
- **L5 选点两个必备护栏**(都实测过):
  ① **max_tokens 要 4000**: DeepSeek 是推理型, 2000 时 reasoning 吃光额度 ⇒ content 空或只吐
     半句思考(实测同一批图 3/3 失败); 4000 时 19s 出真 JSON(6000 也能但要 162s)。
     `gs_l5_select.py` 已 `os.environ.setdefault("ZMAX_L5_VLM_MAXTOK","4000")`。
  ② **硬墙钟预算**: 云端耗时会从 19s 摆到 149s, 且端点卡顿时 urllib 会在 connect 里干等
     (实测卡过 5m44s, 连 `timeout 300` 都没兜住) ⇒ 必须"线程 + join(预算)"包一层;
     默认 `--l5-timeout 180`(给太紧会把"慢但会成功"的调用砍掉), 超时退覆盖度并写 l5_err。
- 状态: `~/zmax_data/gs_map/status.json`(页面 /ctl/gs_map 轮询); 文档 `docs/MAPPING-3DGS.md`。

## 手动走位采集(操作员用控制器自己的“运动到点”, 助手只采集)

什么时候用: 长直线转移被控制器以**奇异点**拒发(`50102`/`50120`, 且把同一根直线拆小步也没用) ⇒ 自动走位那条链
一步都走不动, 改成**操作员用控制器自己的“运动到点”逐点走**(它走关节空间, 实测能穿过去), 助手只负责采集 + 真值核对。

- 🔴 **采集必须“全程连续”, 不能“到点停一下再采”**: 采集端按内容 md5 去重(见下), 臂静止时画面不变 ⇒
  一个停驻点只剩 **1 张唯一帧**, 6 个点 = 6 张, 建不出东西。定式: 操作员起步前就把采集挂上(`--secs 0`,
  收工往会话目录放 `STOP`), 走位全程连续出帧(逐帧配真值位姿); 每个点只让他**停 3~5 秒**供位姿核对。
- **点位核对用真值, 不用他说的名字**: 到位后读 `latest.json` 与示教点比 Δmm 并报出; 手动走位跳过了执行器的
  到位判据(<3mm), 这一步是唯一的口径。
- ⚠️ **别站在臂相机正前方**: 人在画面里那几帧是废帧(伪几何), 采集期间要么不入镜, 要么事后按帧位姿/掩膜剔除。
- 走位纪律(现场照念): 速度放慢 · **平移保持高度**(先到横移高度再平移, 别边降边挪) · 尽量不翻腕。
- 手动走位期间助手侧的运动闸门**照旧关着**(不下发), 只留只读采集与真值核对 —— 现场手上有急停, 别抢。

## 验证口径(交付资产前)
- 资产: ply 高斯数、留出视角 PSNR、资产 bbox 与真实工作区尺度比(与 `env_model.json` 的包络交叉核)。
- 采集: `capture_summary.json` 的 `pose_*_range_mm` 必须非零(**全零 = 臂没动/位姿源不对**), 且帧数与位姿样本数对得上。
- 与真机同口径: 渲染出来的图喂回检测/策略, 与真机同帧做对照(别只报“看着像”)。
