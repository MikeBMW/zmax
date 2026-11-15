---
name: real-handeye-calibration
description: "Use when 真机手眼标定(相机在臂上)采集或解算失败/精度不合格。"
version: 1.0.0
author: Hermes Agent
tags: [zmax, handeye, calibration, eye-in-hand, rokae, orin]
platforms: [linux]
---

# 真机眼在手 手眼标定 — 一次跑通的配方 (2026-09-21 实测通过)

## When to Use
- 要标定"相机装在协作臂上"的外参 T_cam2tool（画布/感知要 像素↔基座 换算）
- 解出来的外参**物理上不可能**（平移几百米/几十米）、或重投影上百 px
- 老倪摆好标定板说"你开始吧"

## 硬件/口径前提
- 板: **CGB-020，白点黑底圆点阵列 5×4 = 20 点，间距 20mm** → `cv2.findCirclesGrid(gray, (4,5), CALIB_CB_ASYMMETRIC_GRID, blobDetector=<SimpleBlobDetector>)`
  ⚠️ **必须自带 SimpleBlobDetector**（见下节），默认 detector 对这块板恒检不出，“必须反色”的旧结论不准确
- 内参 K/畸变: `models/real_cam_calib.json`（来自 `/realsense/color/camera_info`，fx≈394/fy≈393/cx≈318.4/cy≈238.7）
- 位姿真值: `/robot/tcp_pose`（≡ SDK 的 `CoordinateType.endInRef` 工具系，与示教点同源）

## 三步配方
```bash
# ① 采集(只读, 不发指令): 每位姿要求 6s 位姿极差 ≤1.5mm/0.5° 且画面差异 ≤2.0灰阶/位移 ≤0.3px
gui-venv311/bin/python tools/handeye_collect.py --target 16 --seconds 1800   # 后台跑, 用 process poll 看心跳
# ② 走位(需要动臂, 每步三查): 平移走 L2 注册表技能, 旋转走 /move_pose(不掉电)
gui-venv311/bin/python tools/l2_pose_rot.py --axis z --deg 10 --send          # 绕工具自身轴; x/y 是倾侧
# ③ 解算 + 独立验证
gui-venv311/bin/python tools/handeye_diag_solve.py --session ~/zmax_data/handeye/<ts>
gui-venv311/bin/python tools/handeye_verify.py     --session ~/zmax_data/handeye/<ts>
```
**走位设计**：≥12 个位姿；必须包含**绕工具三个轴**的旋转（只平移或只绕一个轴 → 旋转分量解不出）；平移 ±30~60mm；每步 10° 旋转（见坑 2）。

## 判据（宁缺勿假）
- 板在基座系一致性：平移 RMS ≤3mm 且姿态 RMS ≤0.5° → 2026-09-21 实测 **0.06mm / 0.005°**
- **全链路重投影**（板→基座→每帧相机→投影像素，比真实检出点）：中位 ≤1.5px → 实测 **0.117px**（最差 0.267px，14 视图）
- 通过才写 `models/handeye_state.json`（含 T_cam2tool/板位姿/残差/视图清单）

## 附: 更强的正向验收 — 正投影 vs 图上实检
旋转残差（板面法向检验）**灵敏但不可靠**（斜视角 PnP 本身差）。要评判外参能不能用，
用**正投影**：把已知 base 位置的点逐位姿投回**该位姿自己的图**，与图上实检质心比。
实测 8 位姿 **中位 5.2px ≈ 3.1mm**（同一套外参，法向检验却说 9~15°）⇒ **位置精度与旋转精度必须分开报**，
不能因为法向那项大就说“标定不能用”。口径要同源：解算器闭环用 `OBJ.mean(0)` 质心，
比对面也得取实检点云质心（不是图案原点，否则差 68/40mm 常量偏移）。
详见技能 `sim-real-scene-overlay`。

## ⚠️ 检出坑(2026-11-15 实测, 推翻旧结论)

**`findCirclesGrid` 默认 detector 对 CGB-020 恒检不出** — 原图/反色 × (4,5)/(5,4) × 对称/非对称
全部试过都是 **0 点**, 而画面里板明明在(老倪肉眼可见)。会误判成"板不在视野"。

**真因**: 必须自带 `SimpleBlobDetector`, 默认 detector 把这些点按面积/圆度滤掉了。

```python
p = cv2.SimpleBlobDetector_Params()
p.filterByArea = True; p.minArea = 50; p.maxArea = 1500
p.filterByCircularity = True; p.minCircularity = 0.55
p.filterByConvexity = True; p.minConvexity = 0.7
p.filterByInertia = True; p.minInertiaRatio = 0.15
p.filterByColor = True; p.blobColor = 255          # 原图白点=255; 反色图里白点变黑=0
det = cv2.SimpleBlobDetector_create(p)
ok, cs = cv2.findCirclesGrid(gray, (4,5), flags=cv2.CALIB_CB_ASYMMETRIC_GRID, blobDetector=det)
```

加上后 20 点稳定检出, PnP 残差 0.10~0.18px。
**辅助判据**: Hough 圆 (param2=26, r=4~14) 能先看到 12~18 个规整圆点(最近邻间距变异系数≈0.05),
说明板在视野里; 此时 findCirclesGrid 仍为 0 → 就是缺 blobDetector, 不是板不在。

## 走位通道: 用 Orin SDK 桥 39061, 不要用 ROS2 /move_pose (2026-11-15 实测)

本机 ROS2 这条路当天两处坏: `ros2 topic echo /robot/tcp_pose` 报
`sequence size exceeds remaining buffer`; `tools/l2_pose_rot.py` 读位姿同样失败;
且 `~/.ssh/config` 里 `Host orin` 的 `HostName` 被写成热点 43.19(有线时超时), 正确是 `192.168.23.66`(User tashan)。

**能用的路**: Orin SDK HTTP 桥 `http://192.168.23.66:39061`
- `GET /health` 要 `sdk:true`(sdk:false ⇒ 单元 ZMAX_SDK_PATH 指到废弃工作区)
- `GET /status` → `status.endInRef = [x,y,z(m), rx,ry,rz(rad)]`, 与 `/robot/tcp_pose` 同口径
- `POST /reset`(SDK 接管前置) → `POST /move_pose {p:[x,y,z], q:[x,y,z,w], speed, dry}` → `POST /stop`

跑通的采集器: `tools/handeye_bridge_collect.py --dry|--go`, 12 位姿(3 轴各 ±10° + 四向 30mm),
逐点 到位校验(≤1mm/≤0.5°) → 力矩闸 → 抓 8791/snapshot/arm.jpg → 同刻读 /status → 20 点检测 → 落 pairs。

**到位超时要给足**: 20mm/s 走 60mm 要 3s+, 8s 超时曾在最后一组停在距目标 6.5mm 被 /stop
(保护对, 但少一组)。要 12 组齐就给 12~15s。

**力矩闸写基线增量, 不要写绝对值**: 该姿态悬停 J2≈-24.4Nm、J3≈+22.4Nm 是**正常重力矩**,
拿 23Nm 当阈值第一点就误 /stop。正确: 相对启动基线的**增量** > 10Nm 或绝对 > 40Nm 才停。

**8 组就够解**: 3 轴各 ±10° 旋转组合(位置只 X 30mm)已解出平移 RMS 0.36mm / 姿态 0.019°,
全链路重投影中位 0.804px(判据 ≤1.5px)。旧标定 12.53°/92.44mm → 差 660 倍/257 倍。
说明手眼解算主要靠**姿态多样性**, 位置激励只影响鲁棒性余量。
自洽性验证很灵: 纯平移组的板姿态变化应≈0(实测 0.21°), 每条旋转组的板转角应≈工具转角(实测 9.81~10.23°)。

## 坑（都踩过）
1. **物点单位必须是米**。传 `--square-mm 20` 而物点直接用 `20`（=20 米）→ 解出的"板距相机"是
   **448m**（真实 0.448m 的 1000 倍），外参平移 267 米。**任何"距离 ×1000"先查单位**（09-19 那次 256m 同因）。
2. **`/target_relative_joint` 动作后驱动会把伺服下电**（老倪："怎么又下电了"）→ 要反复走位的场景用
   **`/move_pose`**（TargetPose，与 `/move_line` 同族）：实测 power_state 一直 on。
   但大角度（20°）会报 `ROBOT_IDLE_TIMEOUT`（驱动等"空闲"30s）—— **动作其实已完成**（比对目标四元数即可），
   该标志在**下一次成功动作后自动清掉**。单步压到 **≤10°** 可完全避开。
3. **旧脚本 `board_handeye_solve.py` 的"留出复核"是循环论证**：它用 PnP 自己的位姿投回自己 → 永远 ~0.03px，
   267 米的外参也"通过"。真判据只能是全链路（`handeye_verify.py`）或板在基座系一致性。
4. `cv2.calibrateHandEye` 在 `gui-venv311` 的 opencv 里没有 → 用 `/home/ubuntu/lerobot-venv/bin/python`（4.13）或本仓自研解算（`handeye_diag_solve.py`，scipy 最小二乘，多起点）。
5. **标定完先把板从台面拿走再动臂**（2026-09-21 教训）：板留着时把臂往低处回，工具扎到板面
   （板面 z≈0.2526，TCP 到 z=0.2296 = 低 23mm）→ 腕部 J5 力矩 22.01Nm > 22Nm 限值 → 报警+断电。
   信号: 相机到板距离骤降（0.45m→0.364m）+ 该关节力矩顶到限值。
6. 控制器 `tool_load` 全 0（末端质量/质心未设）→ 动力学不带负载，腕部力矩长期贴着限值；方便的化设上工具负载。
