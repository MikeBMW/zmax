---
name: shadow-mode-real-robot
version: 1.0.0
author: 静静 (Hermes)
description: "Use when 真机在跑、要在旁路开影子模式采集+自标定+建图(只读,零下行)。"
metadata:
  hermes:
    tags: [shadow-mode, handeye, calibration, mapping, zmax, orin, read-only]
    related_skills: [zmax-real-closed-loop, real-handeye-calibration, sim-real-scene-overlay]
---

# 影子模式 (真机旁路) — 采集 / 自标定 / 建图

## When to Use
- 老倪说「开启影子模式 / 自主进化 / 你来自主标定、建图」而**机器人自己正在动**。
- 要在不干扰生产的前提下，用真机自己的运动学做标定自证与工作空间建图。

## 红线 (Orin 是生产设备)
- 只做 HTTP GET；**不订阅控制话题、不调 move/gripper、不往 Orin 装任何东西**。
- 采集/标定失败就如实报 gap，**绝不拿旧帧或全局常量编数**。

## 真值源 (550C 实测, 2026-11)
| 用途 | 端点 | 说明 |
|---|---|---|
| 臂相机彩色 | `http://192.168.23.66:8794/frame.jpg` | 640×480 JPEG, 30fps, `/status` 给 `age_s`(帧龄) |
| TCP 真值 | `http://192.168.23.66:39061/status` | `endInRef`(TCP xyz,rpy) + `flangeInBase` + jointPos/Torque + `powerState`/`operateMode` |
| 深度 | `8792/depth.png` | **常死**: `n=0` ⇒ 说明 D405 被生产进程独占或驱动没起, 别反复重试 |
| 本机门面 | `8791` (cam_live_stream) / `8797` (AR) | `/api/cams` 有每路 age_s/stalled, 可判活 |

`conn_ts` **不是**新鲜度指标 (只在 SDK 会话建立时写)。判活看 `endInRef` 是否在变 (0.5s×40 采样看 change 数)。

## 工具 (本仓库)
```bash
# 常驻影子服务 (systemd, Restart=always, 断链不退出)
sudo systemctl status zmax-shadow-mode      # 单元: deploy/zmax-shadow-mode.service
# 手动跑一段自检
cd ~/zmax && ./gui-venv311/bin/python tools/shadow_mode_550c.py --duration 60 --tag probe
# 自标定引擎单测 (合成数据, 必须 PASS 再信现场结果)
./gui-venv311/bin/python tools/shadow_calib_selftest.py
# 工作空间覆盖图 (可对任意 poses.jsonl / frames.jsonl 重算)
./gui-venv311/bin/python tools/shadow_coverage.py --poses <jsonl> --out <dir> --dedup-time 1.0
# 口径诊断 (rpy 约定 × tcp/flange, 看谁残差最小)
./gui-venv311/bin/python tools/shadow_diag_convention.py <session_dir>
```
产物: `~/zmax_data/shadow/sessions/<tag-stamp>/{frames,poses.jsonl,keyframes.jsonl,status.json,calib_live.json,map.json,shadow_3d.html}`；`~/zmax_data/shadow/latest.json` 供页面/大屏轮询。

## 关键做法 (踩过的坑)
1. **时间对齐**: 抓帧后立刻读 `8794/status.age_s`，把位姿对到「拍照时刻」= `monotonic − age`；不扣帧龄会把 30~150ms 的画面滞后当成运动误差 (10° 级)。
2. **同图多位姿是伪配对**: 判据用**像素变化率** `mean(|Δ|>20) > 5~10%`，不能只看 md5；相机出图慢时同一画面会被反复取到。
3. **essential matrix 只在小角/多纹理时可信**: 相对转角 <2° 或内点率 <0.45 的对应直接丢弃；纯旋转/静止对会返回 R=0° 或 180° 的退化解。
4. **手眼旋转解 = 轴对齐 Kabsch** (`A X = X B`): 取 `axis(A)=X·axis(B)`，只保留两轴转角一致的样本 (|α−β|<3°)，权重用转角；**不要**用 `Σ Rc·dRᵀ` 的朴素 SVD (就是错的，实测反解偏 25°+)。
5. **口径不能混池**: `endInRef` 与 `flangeInBase` 是不同坐标系，dR 必须同口径；混池解出来的标定是垃圾 (实测 delta 179°)。
6. **替换标定要留出集**: 奇数对训练/偶数对验证；`accepted` 只在「现标定 >5° 或反解 <0.7×现残差」时才为真，已标定好的不要动。
7. **断链自持**: 拔 USB 网卡/Orin 掉线时服务**不退出**，state 转 `link_down`，每 30s 用本地已落盘数据重算 `map.json`+HTML；链路回来自动续采 (实测 blackhole 12s→恢复)。
8. **单目无深度的建图只能是「TCP 轨迹覆盖栅格 + 稀疏特征」**，不是点云；报覆盖面积/bbox/z 范围，别说成 3D 重建。

## 判据 (交付要给的数)
- 采样: frames / keyframes / pose_hz (实测只读 8794+39061 可稳定 8Hz 抓帧、~4Hz 落位姿)
- 标定: pairs / `resid_old_deg_median` / 留出集新旧残差 / `delta_from_handeye_deg` / `lag_ms`
- 建图: `cells` × cell (2cm) = 覆盖面积, bbox, z 范围, TCP 路径长度
- 自检: `shadow_calib_selftest.py` 必须 PASS (合成数据残差 <1.5°，反解 vs 真值 <2°)

## 实测结论 (2026-11-04, 550C)
- 只读链路可用: 8794 帧龄 0.02~0.13s，39061 位姿 ~13/40 次变化 (真机在动)。
- 现有 `models/handeye_state.json` (09-21, 残差 0.06mm/0.0046°) 用当前画面**无法验证到 5° 以内**: 3 种 rpy 约定 × tcp/flange 全在 9~14°。
  ⇒ 单目+小转角+平面场景下，essential 的旋转不可观测是该量级的主因; 要毫米/度级标定必须上靶标 (`board_handeye_solve.py`) 或有深度。
- `8792` 深度节点 `n=0` ⇒ 无米制深度，建图只能给覆盖栅格。
