---
name: ar-render-perception-plan-dualarm
description: "Use when 跑渲染帧→L2感知→plan→双臂执行闭环或用 8805 站。"
version: 1.0.0
author: 老倪 (laoni), Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Z-MAX, AR, mujoco, YOLO, 双臂, 闭环, 真值]
    related_skills: [zmax-ar-traj-8797, sim-real-scene-overlay, integration-level-audit]
---

# AR 渲染帧 → L2 感知 → plan → 双臂执行 闭环

在 AR 工位仿真里跑一条**真链路**: `ArMujocoEnv` 渲染帧当输入 → YOLO 真推理出 2D 框 →
像素反解出品台 3D → 几何 plan 节点出双臂步骤 → 动作执行节点逐步骤 IK/下发 → 用仿真真值判到位 →
复测同一目标。不需要真机、不看相机。

不做: 学习型策略规划、抓取搬运(见 Pitfalls 末条)、真机下发。

## When to Use

- 要证明「模型在渲染帧上真跑」而不是 mock/固定答案
- 要一条**双臂都受控**的 plan→act 闭环, 且每步有真值证据
- 换场景/换机位后要重建「像素↔台面」映射 (平面单应自标)
- 排 8802/8805 站点故障: 无帧、n 不涨、gold_px=0、检测忽有忽无

Don't use for: 真机轨迹/8797 AR 页叠加(见 `zmax-ar-traj-8797`)、仿真-真机场景叠加(`sim-real-scene-overlay`)。

## 站点与端口

| 端口 | 服务 | 作用 |
|---|---|---|
| 8802 | `zmax-ar-render.service` (`tools/ar_scene_render_server.py`) | 渲染帧 + 下单应标定 + 双臂控制/真值 |
| 8805 | `zmax-ar-render-station.service` (`tools/ar_render_station.py`) | 页面 + 感知/规划/执行/复测闭环 |
| 8797 | `zmax-traj-ar` | 与本站独立的 AR 轨迹页, 只借 8802 的帧 |

关键文件(仓库根相对): `tools/ar_mujoco_env.py`(场景+双臂) · `tools/dual_arm_plan.py`(plan 节点) ·
`src/lerobot/perception/yolo.py`(L2 模型类) · `tools/det_src.py`(帧源开关 real/render)

## 8802 接口

```
GET  /frame.png?cam=close|ar3d  /status.json  /label.json  /state.json  /calib.json
GET  /ik?side=R&x=&y=&z=        6 轴 IK (m) → deg + err_mm + at_limit
GET  /proj?x=&y=&z=&cam=        世界点 → 该视角像素   GET /unproj?u=&v=&cam=  像素 → 台面 3D
POST /control {"mode":"sim","L":[6deg],"R":[6deg],"gripL":0/1,"gripR":0/1}
POST /reset                     回双臂 home + 模块落位 (mode 回 idle 才有微动)
```

两个机位 (`VIEWS`), **同一拍各渲一张** ⇒ 天生同步: `close`=特写(料盘+模块, L2 训练域, L2 只认这个),
`ar3d`=全景(与 AR 页 3D 视图同参数: `yaw=-0.9rad pitch=0.55rad dist=1.6m tgt=[0.70,0.22,0.14]`
⇒ mujoco `azimuth=-51.6 elevation=-31.5`)。`/status.json#views` 同时给两路 `gold_px/box`。

`/state.json#truth` = tcpL/tcpR/gold/hole/qL/qR/plane_z, 全部取 `model.data`, 不手推 —— 这是判据唯一来源。

## 与 AR 页 (/ar3d) 对齐

「渲染场景要跟 ar3d 一模一样」= 几何、机位、焦距全部照 `tools/web/tcp-ar.html` 的常数, 自己不要另造一个工位。

| 项 | ar3d 常数 (tcp-ar.html) | mujoco 里怎么建 |
|---|---|---|
| 地面 FLR | `z=-0.750` | plane `pos="0 0 -0.75"` |
| 箱体 CHS | `0.600(x)×0.800(y)`, 体 680 + 轮 70, y 中心 0.25, **顶板 z=0** | box `pos="0 0.25 -0.355" size="0.30 0.40 0.325"` + 4 轮 `z=-0.68` |
| 桌 TAB | `x 0.35..0.95`, `y -0.55..1.05`, 厚 0.030, **顶面 z=0** | box `pos="0.65 0.25 -0.015" size="0.30 0.80 0.015"` + 4 腿到 -0.75 |
| 两臂 | 装在顶板, **x=0, y=0 与 y=0.5**, 都朝 +x | `arm(side, 0.0, 0.0 或 0.5, 0.0)`, 无需镜像 |
| 料盘 | 底在 z≈0.10 (fence_store) | 桌面到料盘补 100mm 垫块, 否则悬空看着就“位置不对” |

机位换算 (页面是 `yaw/pitch/dist/tgt` + `F=520px` 的针孔模型):

```
azimuth   = degrees(yaw)              # yaw=-0.9rad  → -51.6
elevation = -degrees(pitch)           # pitch=0.55rad → -31.5
distance  = dist                      # 1.6
lookat    = tgt                       # [0.70,0.22,0.14]
fovy      = 2*atan((h/2)/F)           # 960x720,F=520 → 69.4°
```

自验: 拿 9 个已知 3D 点(箱体/桌面/料盘/地面) 分别用**页面的 pr()** 和 `/proj?cam=ar3d` 投影,
最大差应 <20px (实测 14px; 浏览器画布宽高与 960×720 不同会留几个 px)。差到百 px 级 = 机位/焦距口径不对。

## 过引擎完整链 (8805 → 统一状态空间)

几何短链 (plan → IK → control) **不算**过引擎。要真过引擎, 用 `tools/ss_station_engine.py`
(六层源码同源加载, 与 `runtime.py` 同一顺序):

```
L2 YOLO(8802渲染帧) → /dev/shm/l2_det.json  (① 感知归口, 引擎/画布 n_yolo 读同一份)
  → u_ff  = k·(段目标−末端), 限本段 v_cap          (⚡ 前馈槽位 / 技能口)
  → ActionModulator.decide(u_ff, u_fb, contact, r)   (内含 SK01-08 + InertiaLimiter 五约束)
  → gripper_cmd → safety.saturate(SS_LIMIT=0.6)      (🛡 安全执行边界, 单点削)
  → 增量 = u_sat·dt  → IK(seed, rate) → 8802 /control → 真值回读
  → skill_dispatch.json + /dev/shm/zmax_ss_engine/skill_<stage>.json  (③ 技能归口)
```

装法要点 (都是实测踩过的):
- `load_mod` 按文件加载六层源码 (同 `tools/ss_bypass_run.py`), 不经包 `__init__`;
- `InertiaLimiter()` 不传 dt (传 None 会 `float(None)` 崩); 拿到 `lim.dt` 后再设 `mod.gate_dt`;
  `ActionModulator` 构造函数**没有** `gate_dt` 参数;
- `decide()` 的 `u_fb` 必须是 **4 维** (3 维会 broadcast 报错); 本站没有速度/接触通道 ⇒ 置 0 并如实标注;
- 前馈 MLP (`models/ss_left_brain.npz`) 要吃 **39D obs** (`obs[0:3]`=手, `obs[36:39]`=目标)。
  本站缺 peg/孔/速度通道 ⇒ **不伪造 39D**, 用技能口 u_ff, 并把 `u_ff_src="skill"` 落盘。

## Procedure

1. **起渲染站** — `terminal("sudo systemctl restart zmax-ar-render")`, 再 `terminal("curl -s 127.0.0.1:8802/status.json")`。
   完成判据: `ok:true`、`n` 连续两次递增、`gold_px>300`、`calib.ok:true` 且 `calib.res_mm_med` 有值。
2. **起页面站** — `terminal("sudo systemctl restart zmax-ar-render-station")`, 查 `curl -s 127.0.0.1:8805/api/health`。
   完成判据: `weights: yolo_ar_peg.pt`。
3. **跑一轮闭环** — `terminal("curl -s -X POST 127.0.0.1:8805/api/run")` 后轮询 `/api/live` 直到 `phase=done`
   (整轮 15~50s)。页面同效: 打开 `http://<host>:8805/` 点「▶ 跑一次闭环」。
   完成判据: `err=null`。
4. **验感知** — `/api/live` 里 `l2.conf ≥ 0.8`、`l2.best.box` 与 `label.json#box` 同量级(±10px)、
   `perc.truth_err_mm < 10`。不满足就别看后面的执行结论。
5. **验执行** — `act.steps` 每条 `ok:true` 且 `reached_mm ≤ tol_mm`(默认 8mm), `passes` 反映伺服回补轮数。
   完成判据: `perf.ok_steps == perf.steps`。
6. **验闭环** — `recheck.l2.ok:true` 且 `recheck.perc.xyz` 与步骤 4 的定位差 < 10mm。
7. **留证** — 取证图 `zmax_data/ss_live/render_station_evidence.jpg`(L2 框绿 / 渲染真值框青 / 定位十字黄),
   和对齐过的 `/api/live` JSON。

## Pitfalls

1. **通道口径**: `YoloPerception.detect()` 默认**按 RGB 入参**再内部转 BGR。`cv2.imdecode/imread` 给的已是 BGR,
   直接喂会多转一次。实测同一帧: 正确口径 conf 0.955 / 87×46 框; 多转一次只剩 0.3 且框 70×44 错位。
   规则: BGR 帧一律 `detect(..., already_bgr=True)`, 并加**面积闸**(渲染帧里模块 ~90×50px, <600px 判误检)。
2. **同类多框被折叠**: `detect()` 每类只留一个, 早期实现是「后写覆盖前」⇒ 0.898 的模块框被 0.055 的碎框顶掉,
   下游拿到错位小框。规则: 多实例一律用 `detect_all()`; `detect()` 已改为每类保留最高分。
3. **L 臂朝向**: `ArMujocoEnv.arm(side, base_x, base_y, sign)` 的 `sign` 原本未使用 ⇒ 两臂运动学相同、都朝 -x 伸;
   R 基座在料盘右侧够得到, L 基座在左侧却伸向场外(L 腕 x=-0.09, 对料盘目标只能解出多圈怪解, 执行差 150mm+)。
   规则: L 基座绕 z 转 180°(`<body ... quat="0 0 0 1">`)。**不要**用「关节轴 x 分量取反」做镜像 —— 会把 y 一起反掉,
   L 腕落到 y=-0.147 的场外。
4. **home/停机位挡视野或出画**: 双臂前伸 home 正好压在机位与料盘之间 ⇒ `gold_px=0`, L2 只能检到别的东西(定位差 150mm)。
   规则: 每次拍帧前先 `park_clear`(R `[0.72,0.22,0.32]`, L `[0.15,0.35,0.30]`; 特写 gold_px 2300+);
   L 的 home 用竖直位(全 0)只保证特写干净, **全景里会出画** ⇒ 全景要看到机器人必须显式 park。
   停机位选定前用 `/proj?cam=ar3d` 把 `truth.tcpL/tcpR` 投一遍, 要求两个点都落在 `[0,W]×[0,H]` 内;
   只验 `gold_px` 不够(实测 L 停在 `[0.30,0.35,0.55]` 时特写 1617/全景也偏低, 且竖起的 L 臂全景投到 `v=-190` 画外)。
   视线被挡时**不要**让模型硬凑框 —— `gold_px<300` 就直接如实报「画面里无模块」。
5. **位置执行器有重力静差**: kp=60 的 position actuator 稳在 6~12mm 外。规则: 到位后取 `/state.json` 实测残差回补
   (指令点 += 残差, **限幅 30mm**, 最多 3 轮), 否则永远差 10mm。
6. **判据只认真值**: 步骤完成看 `truth.tcp<side>` 与目标距离, 不看「指令已下发」。每步记录 `reached_mm`/`passes`。
7. **IK 单初值会贴限位**: 会返回 deg=±170 的解而执行端跟不过去(8s 超时)。规则: 多初值重试 + `at_limit` 的解判不可达,
   让调用方如实报 `err_mm`, 不硬发。
8. **复测要清场**: 执行后先让双臂撤离再抓帧, 并等 0.9s 稳定、最多 3 帧重试; 拿被臂挡住的帧复测只会得到「无框」。
9. **别手算 mujoco 相机内参**: `MjvGLCamera.frustum_width` 取到 0, 手写 fovy 投影 u 差 55~70px。
   规则: 启动时**自标**——把模块摆到 3 层 z × 3×3 网格 (27 点) 逐点渲染取金色像素质心:
   ① 27 点解 3×4 全相机矩阵 `P`(DLT) → 给 `/proj` 叠加双腕/模块等**离面点** (实测残差 0.56px);
   ② 只用台面那 9 点解平面单应 `H` → 给 `/unproj` 做 2D→3D (0.12~0.83px)。
   **两者不能混用**: 全 P 用于 2D→3D 会差到 3.9px, 因为模块抬高后露的是顶面, 像素质心 ≠ 体心, 把全 P 拟合带偏;
   平面点用 H 反解才是同口径。`/calib.json` 两套残差都自报。
10. **抓取物理不成立就别演**: 本场景两指沿 x 并列布置, 对 16mm 宽模块不成对夹(实测夹紧后模块仍原地, 只被推 5mm)。
    当前 plan 只做双臂对位/协同 + 撤离。要搬运必须改指几何(沿 y 对夹)+ 重训 AR 权重, 别用假位移糊过去。
11. **端口**: 8804 已被 `gs_train_service.py` 占用, 本站固定 8805。建服务前先 `ss -ltnp` 核。
12. **构造失败要自愈**: 渲染线程若把 env/Renderer 建在 try 外, 开机 X/GL 未就绪就整线程死掉, 端口照样在听、`n=0`、`err=null`(假活)。
    规则: 构造包 try + 3s 重试 + 写 `err`; 诊断用 `py-spy dump` 看线程是否还在。

13. **页面「不动」**: 只在跑闭环时才写一帧 ⇒ 两次拉图 md5 完全一致, 看着像卡死。规则: 站里加常驻取流线程
    (两路视角各 ~6Hz 拉帧 + 0.5Hz 拉 truth/calib), 页面 `setInterval` 换 `?cam=&t=` 拉图;
    同时**停位/复位后要把 `/control` 的 mode 切回 `idle`** —— `sim` 模式没有新指令时物理静止、帧永远一样,
    `idle` 才有模块小漂移 + 机位微抖。诊断口径: 两张图 md5 相同 + `n` 在涨 = 帧恒定, 不是取流坏了。
14. **idle 抖动幅值要小**: 模块漂移 12mm 时, 「感知 vs 真值」的差值主要是**帧与真值的时序差**(实测虚高到 16.4mm);
    降到 3mm 后同一条链路 7.3mm。画面「活」靠机位微抖就够, 别用大幅漂移换观感。
15. **开机摆场必须重试**: 渲染站建 env + 27 点标定约 10s, 页面站早调 `/reset` 会 503 且一次失败就再也不摆。
    规则: 轮询 `/status.json` 直到 `ok` 且两视角 `calibs.ok`, 再 reset+park; 失败 4s 后重试(12 次)。
16. **同步显示的口径**: 两视角因为**同一 tick 出图**而天然同步(`/status.json#n` 同一个), 页面把 `n` 显示成「两视角同帧 #n」;
    与 8797 AR 页只是**同视角参数**(那页的 3D 是独立画的真机/场景数据), 不是同一数据源 —— 别说成「和 AR 页同一路数据」。

17. **标定 fovy 必须与出图 fovy 一致**: `calibrate_camera` 走默认 45°、出图用 55°/69.4° ⇒ 标出来的 P 与画面不是同一个针孔模型,
    与 AR 页同口径点差到 214px。规则: 每个视角带上 `fovy` 字段, 标定和渲染前都设 `model.vis.global_.fovy`; 改完实测 14px、
    标定残差 0.09px。
18. **家具颜色会污染真值键**: 金色判据是 `R>120 & G>85 & R-B>40 & G-B>20`; ar3d 的棕色桌面 (0.48,0.37,0.27) 过 sRGB 后
    正好 R-B=41 / G-B=20 ⇒ 整块桌面被当成模块 (实测 gold_px 25594、框贴画面边, 标定/2D→3D 全废)。
    规则: 家具用中性灰; 新加任何偏暖色材质后先跑一次 `gold_px` 看基线(模块在位时应 1500~3500)。
19. **双臂对位方向跟着基座走**: 两臂改成顶板 x=0、y=0/0.5 并排后, 对位偏移必须改成 **±y**
    (R 从 -y 侧、L 从 +y 侧, 65mm 净空), 不能再沿 ±x。旧偏移在新布局下会让两腕从同一侧挤向模块。
20. **/ar3d “不动” 不是页面坏了**: 看 `curl -s 127.0.0.1:8797/api/tcp` 的 `age_s/stale/fallback_err`。
    实测 `age_s=18693s` + `latest.json` 冻在 5 小时前 + `桥也读不到(Connection refused)` ⇒ 页面 URDF 永远用同一组关节角。
    **不要**把仿真的关节角当 `joint` 喂给页面 —— 仿真是简化 6 轴(0.16/0.18/0.18/0.15/0.12/0.10), 与真机 URDF 运动学不同,
    画出来就是“位置又不对”。要真有运动只能: ① 恢复 Orin 位姿桥; ② 在页面里另画一层仿真骨骼(带 SIM 标记), 不动 URDF 臂。

21. **逐拍 IK 必须带 seed + rate**: 不给 seed 时每拍独立解会**跳分支** (实测 L 臂在一拍内从 z=0.55 折到 z=0.25,
    80 拍都追不回来)。`/ik?seed=<上一条指令 6 角>&rate=14` 后 318mm 行程 4.7s 收敛。
22. **执行器刚度才是真瓶颈, 不是判据**: `kp=60/kv=6` 时远伸位姿静差实测 **34.2mm** (kp=150→13.7, kp=300/kv=20→7.1)。
    判据卡 8mm 永远到不了 ⇒ 该调执行器刚度 (真机重复定位 ±0.02mm), 不要靠放宽 tol 过。
    tol 统一 10mm 时 6/6 到位实测 6.3/3.2/2.0/8.3/4.4/2.5mm。
23. **停摆判据写反会误杀**: 用 `best > min(hist[-30:]) - 0.5` 比 —— best 本就是历史最小值, 该式恒真 ⇒ 第 30 拍必断
    (实测 400mm→70mm 就断)。要比 **30 拍前的最好成绩**: `best > hist[-31] - 0.5`。
24. **每拍总位移要限幅**: 引擎增量 (v_cap·dt, 实测 35mm) + 静差补偿 (≤ 30mm) 相加能到 65mm/拍, IK 跟不过去。
    合计限幅 45mm/拍。
25. **感知归口有两个写入方**: 引擎常驻回路 (每 N 周期) 与站 (每轮) 都写 `/dev/shm/l2_det.json`, **谁后写谁在文件里**;
    写完必须**回读** `n/src` 对账 (实测回读 src=`L2:detect.yolo(8805站)` 后又被回路覆盖, 两边都是真推理, 不是错)。
26. **技能派发也有两个写入方**: 常驻 `tools/ss_skill_dispatch.py` 与本站都写 `zmax_data/ss_live/skill_dispatch.json`;
    本站的 `by="ar_render_station(引擎链)"` 会被覆盖。要永久区分就用各自的 `/dev/shm/zmax_ss_engine/skill_<stage>.json`。

## Verification

- `/status.json`: `ok:true` · `n` 递增 · `gold_px>300` · `calib.res_mm_med` 个位数 mm
- `/api/live`: `l2.conf≥0.8` · `perc.truth_err_mm<10` · `perf.ok_steps==perf.steps` · `recheck.l2.ok:true`
- 双臂都动: `act.steps` 里 L 与 R 都有 `ok:true`, 且 `truth.tcpL/tcpR` 与步骤目标一致
- 取证图存在且为 960×720: `zmax_data/ss_live/render_station_evidence.jpg`
- 过引擎取证: `/api/live.chain.last` 有 `stage/skill/u_ff_src/u_ff/u_sat/gate_why/delta_mm`, `stats.ticks>0` 且 `ff_src` 计数在涨
- 判据真: 每步 `reached_mm ≤ tol_mm` 且 tol ≤10mm (靠调执行器刚度达标, 不是放宽判据)
- 与 AR 页同视角: 9 个已知点的页面投影 vs `/proj?cam=ar3d` 最大差 <20px
- 页面活着: 隔 1s 两次拉同一视角 `/api/frame.png?cam=` 的 md5 **必须不同**, 帧龄 <0.3s, `n` 在涨
- 视角切换: 点「👁 视角」后 `#c1` 标题、`#b4` 文本、`img[src]` 的 `cam=` 三者一致; 浏览器 console 0 error
- 全景有人有桌: `/proj?cam=ar3d` 投 `truth.tcpL/tcpR/gold/hole` 四点**全部 in-frame**
- 反向验伪: 把 `det_src.json#src` 切到 `real`(真机帧不在位)时, 链路必须**报错**而不是出框
