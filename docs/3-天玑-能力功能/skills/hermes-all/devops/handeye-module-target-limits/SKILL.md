---
name: handeye-module-target-limits
description: "Use when 想拿料盘光模块当手眼靶标, 或要把 tool1/相机坐标系画到画面里。"
version: 1.0.0
author: Hermes Agent
tags: [zmax, handeye, calibration, eye-in-hand, rokae, d405]
platforms: [linux]
---

# 光模块当手眼靶标: 边界与替代方案 (2026-11-22 实测)

## When to Use
- 想省掉标定板, 拿料盘上的光模块(已知 72×18.35×8.5mm)当手眼标定靶标
- 要在相机画面上画 tool1 坐标系 / 把基座点叠到图上, 而 `T_base_cam` 还空着
- 解出来的外参物理上不合理(相机原点跑到桌面下)

先看 `real-handeye-calibration`(CGB-020 圆点板配方, 精度 0.1px 级)。本技能只讲**为什么模块靶不行**和**退化方案怎么做**。

## 三个实测死结
1. **腕相机光轴 ≠ 工具轴**。TCP 摆到槽4 正上方 `647.4,353.9,235` 俯视 → 画面 **0 检出**;
   只有斜视位姿 `339.3,372.2,139.9 (rpy 3.089,-1.015,0.071)` 才看得见料盘。
   ⇒ "TCP 在槽上方"不等于"相机对准槽", 不能用 TCP 位置反推相机构图。
2. **斜视下模块顶面不是等深面**。72mm 长边在深度上跨 ≈38mm, "等深切片 / ±5mm 带"会把模块自己切碎;
   深色阈值连通域同样漏到台面。三次拟合全不收敛: `410.5×65.1mm`、`121×34mm`、`130.9×45.5px`(目标 72×18.35)。
3. **整幅深度主平面只占 14% inliers、高度跨 860mm** ⇒ 靠深度自动找料盘/槽坑也不成立。

硬解的外参三假: 相机原点 `z=−218mm`(桌面以下)、模块顶面 74.5×38.7mm、3D 框投影越界比 0.42~0.50。**这种数不能交付**。

## 退化方案: 单点法(只求"能画出坐标系")
```bash
# 1) 模块放进 3 个不共线槽位(槽2 x=649 + 槽8/槽9 x=517), 每次机械臂位姿不同
# 2) 每个位姿采一个点
./gui-venv311/bin/python tools/handeye_point.py --slot 2
./gui-venv311/bin/python tools/handeye_point.py --slot 8
./gui-venv311/bin/python tools/handeye_point.py --slot 9
# 3) 解
./gui-venv311/bin/python tools/handeye_point.py --solve
```
- `v_i = R_iᵀ(P_base_i − s_i)`, 对 `{(P_cam_i, v_i)}` 做 Kabsch ⇒ `T_tool1→cam`。
- `P_cam` 取"**图像暗区掩膜 ∩ 有效深度**"的 3D 质心; **不要**用 YOLO 框内点云(框实测 59×131px, 外扩后含台面/邻件)。
- 中心 1~2mm 偏差可接受(只画坐标系时); 要毫米级装配精度仍须标定板。
- ⚠️ **同一槽位换多个臂位姿解不出旋转**(退化成 `R·(p_i−p_1)=0`), 必须换槽位。
- 工具位姿直接用 `/api/tcp` 的 `frames.tool1`(origin + x/y/z 三轴, 基座系, 控制器真值), 不要自己从 rpy 反算。

## 分辨率换算(必查)
848×480 深度模式下: 槽1 中心 `x≈623`、步距 `77.2px`;
1280×720 时是 `940 / 116.5`。换分辨率不换算 ⇒ 槽号整体偏 1~2 格(实测差点把槽4 误判成槽5/6)。

## 画 tool1 坐标系
- 相机叠加: 必须先有 `T_tool1→cam`(上面单点法或标定板), 否则不画。
- 没有外参时只能画 3D 真值图(`/api/tcp` 的 `frames.tool1` + `config/points/tray_slots_14.json`),
  和用户说清"这是 3D 场景图, 不是相机叠加", 别混为一谈。
