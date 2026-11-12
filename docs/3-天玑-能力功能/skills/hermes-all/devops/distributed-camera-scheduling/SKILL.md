---
name: distributed-camera-scheduling
description: Use when 多相机要按机器人位姿自动启停感知能力 — 相机注册表/区域表/3D 引导闸门。
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [multi-camera, perception-scheduling, extrinsics, zone, 3d-guidance]
metadata:
  hermes:
    tags: [multi-camera, perception-scheduling, extrinsics, zone, 3d-guidance]
    related_skills: [camera-extrinsics-calibration, robot-vision-3d-localization, integration-level-audit]
trigger: "Use when 现场多台相机 (腕上/顶摄/工位相机) 要按机器人位姿自动切换启用的感知能力, 或要判定某台相机能不能给 3D 引导。"
---

# 位姿驱动的分布式感知调度 (多相机 ≠ 一份配置)

## 何时用
- 现场有多台相机 (腕上 / 顶摄 / 工位检测相机), 用户要求「到了某区域就只开那台相机的感知能力」
- 要把「这台相机能不能给 3D 引导」从口头判断变成代码里的硬闸
- 已有轨迹/路径, 要规划「沿路径的感知切换序列」并报覆盖率

## 三条硬规矩 (先立, 再写代码)

1. **外参决定能力等级, 不是相机型号**: 只有 `extrinsic.mode ∈ {tcp_compose, fixed_matrix}` 的相机准出 3D;
   其余在**代码里直接拒**并返回缺什么 —— 不许运行时才报错, 更不许拿近似外参算毫米。
2. **一个数只有一个真源**: 区域表读工程配置, 相机能力读标定真源; 派生层只许 `setdefault` 补位, 不许覆盖真源。
3. **判定用可算的量**: 用 TCP 坐标 vs 区域 bbox (带滞回) 或场景档位, 不用「到了特定位置」这种描述。

## 步骤

### 1. 建相机注册表 (用生成器, 不手抄)
每台一条: `kind`(eye_in_hand/fixed) · `intrinsic` · `extrinsic{mode, 矩阵, 残差, 来源, 理由}` ·
`depth{unit,max_age_s}` · `role`(localize/guide/quality/overview/debug) · `level`(L2/L1/L0) · `coverage.zones` · `calibrated`。

数据源三处并确实合并: 内参标定文件 · 手眼文件 (残差 + 视图数是可信度证据, 一并写进注册表) ·
相机服务的 `/api/cams` (实测分辨率/在线/有无深度)。

🔴 **生成器进版本库, 产物 JSON 常常进不去**: `config/` 在本仓是软链到 gitignore 的数据盘 ⇒
`git add config/...` 会报 `beyond a symbolic link`。做法 = `tools/gen_camera_registry.py` 进库,
JSON 由它重建; 不许换台机器时手抄数值。

### 2. 区域表 = 工程真源 + 轨迹派生层
- 工程真源 (点位的聚类分区) 权威;
- 从**真实轨迹**派生的作业区是补充层 (`tools/gen_traj_zones.py`), 合并时 `setdefault`, 同名让真源赢;
- bbox 用实测点集 + margin (20~30mm), 不眼估; 派生文件头写「非真源」并记生成器名。

### 3. 验证覆盖率 —— 最容易跳过, 也最容易暴露问题
把**每一条真实轨迹的每一个点**喂进调度, 打印区域切换序列, 再算 `落入命名区点数 / 总点数`。

🔴 点位台账聚类出来的区域覆盖不到工作空间: 实测 96 个 AR 轨迹点只命中 11 个 (11.5%), 其余全进「其它」——
不跑这一步会以为调度做好了, 实际大半程「无区可依」。补派生层后 91/96 (94.8%)。
轨迹取不到点 (台账缺点位) 时如实报 0 点并写缺哪个点名, 绝不用相邻轨迹的点顶替。

### 4. 重叠与滞回
- 多区重叠: 「其它 / 包络外」这类兜底区**不许抢具体区** —— 先剔除兜底再取中心最近;
- 边界抖动: 20mm 滞回 (在盒内→立刻切; 已出盒但距面 ≤ 滞回带→保持), 否则 TCP 抖一下相机反复开关;
- 每次判定返回理由串 (`in_bbox` / `滞回保持(距 X 面 10.0mm)` / `包络外`), 供日志与审计。

### 5. 3D 引导按相机类型分两条公式
```
eye_in_hand : P_base = T_base_tool(TCP 实时真值) · T_cam2tool · (d · K⁻¹ [u,v,1]ᵀ)
fixed 无深度: dir = R_bc · K⁻¹ [u,v,1]ᵀ ;  t = (z_plane − t_bc.z)/dir.z ;  P_base = t_bc + t·dir
```
- `plane_z` 没值就拒 —— 无深度固定相机的 3D 全靠这个平面;
- **姿态不承诺**: AABB 框解不出旋转 (实测 0/24 配置达标, 最好一档 44°), 姿态走示教 quat / 角点 PnP / 深度 6D 配准;
- 交叉校验: 同一工件各相机解出的 base 点两两差 >10mm 就 veto 并点名哪两台冲突, **别加权平均把冲突抹平**。

### 6. 输出契约给下游
```
{level, src_cam, p_base_mm, d_xyz_mm, sigma_mm, conf, frame_age_s, xcheck, veto}
```
给下游的是**增量** `d_xyz_mm` 不是绝对点 (下游只用增量, 不会跑飞); `sigma_mm` 必须随数一起给,
让调制器知道该信几分。

## Pitfalls

- 🔴 **按相机型号判能力 = 错判**: 顶摄有 1280 分辨率却只能出 2D, 腕相机 640 却能出 L2。判据永远是外参状态。
- 🔴 **`calibrated: true` 不等于外参可用**: 有相机只标了内参就被标成 calibrated, `T_base_cam` 仍为 null。
  两个字段分开 (`intrinsic_ok` / `extrinsic.mode`), 并在 `_reason` 里写明缺什么、怎么补 (如「4 非共线示教点 PnP, 零运动」)。
- 🔴 **手眼文件里叫 `T_base_cam` 的键可能是 T_cam2tool**: 判据 = 它的平移值与 stats 里 `X_t_mm` 是否相同,
  相同即相机→末端的手眼 X, 不是 base←cam。用前拿一个已知量对一次, 别信键名。
- 🔴 **单位**: 手眼平移是米、TCP 位姿是毫米, 拼矩阵前先统一。判据 = 相机光心到 TCP 的距离应 ≈ |t|;
  两者重合就是漏了 ×1000。
- 🔴 **派生层覆盖真源 = 工程配置以后改不动**: 一律 `setdefault`; 派生文件 `_doc` 首行标明非真源。
- 🔴 **调度算完 ≠ 接进运行时**: 调度器只读不下发, 真要生效得让推流/检测/节点每拍读 TCP 真值去调它。
  交付话必须写成「算得出来 + 还没接到开关上」, 不许宣称已自动切换。
- 🔴 **别把「区域」当「任务阶段」**: 用户给的轨迹可能一条就跨两个区 (抬升段在区外、平移段在区内),
  报切换序列要给 `i from→to` 与端点坐标, 让用户自己核对哪一段对应哪个物理动作。

## Z-MAX 本机基线 (变了以真源为准)

7 台相机: `arm`(Orin 腕上 D405, 640×480, 有深度, 手眼 t=[214.73,12.48,−115.30]mm / 残差 0.06mm rms / 14 视图, **唯一 L2**) ·
`gold`/`gold_raw`/`surface`(工控机 10082/10083, 无深度无外参, 只做质量判决) ·
`local2`(MAXHUB 顶摄 1280×720, `T_base_cam` 未标) · `local`(调试) · `rs`(本机 D435, 有深度无外参)。

- 区域真源: `zmax_data/env_model.json::zones` (观察位 / 料盘槽位排 / 插入工位夹具 / 标定区 / 其它) + `envelope`
- 轨迹真源: `8797 /api/traj/named?k=xiaohong|square|map|safe|real` (safe/real 因台账缺点位常返 0 点)
- 落点: `src/lerobot/policies/perception/camera_scheduler.py` · `tools/gen_camera_registry.py` ·
  `tools/gen_traj_zones.py` · `tools/verify_camera_scheduler.py`
- 缺口: 补一个 `T_base_cam` (顶摄/D435) 与 `plane_z`, 建图区与顶摄区立刻进引导链; AOI 工位相机定位为 quality 角色, 不进引导链。
