# 金手指检测链路: 谁在检测、模型吃什么、判据图给不给模型 (2026-10-12 实测口径)

> 老倪问: 「现在的金手指检测, 在光学质量检测节点代码实现么? 和工控机实现么? 这个判据图, 给到 YOLO 模型了么? 用的什么接口.」
> 本文是**实测口径**（字段/文件都从在役服务现读, 不是从文档抄的）。

## 一、两条实现并存, 不是同一条链

| | 工控机产线 (真判缺陷那条) | 画布节点 🔍 光学质量检测 (本机) |
|---|---|---|
| 代码 | `cam_finger_10082_work_v36…py`(在役, 工控机 `D:\xspace\ultralytics_AOI\`) | `src/lerobot/policies/yolo_3d/quality_check.py::AOIQualityChecker.check()` |
| 实现 | **ultralytics YOLO 检测器**（`gf: bestgf05088.pt.enc`, `imgsz=960`） | **纯 numpy/cv2 几何阈值体检**（无训练权重） |
| 吃什么图 | **同帧派生的 960×960 方图**（`%TEMP%\zmax_main_960_*.png`, 检测完即删） | 画布当前帧（AR/仿真源） |
| 出什么 | 判决 PASS/FAIL + 缺陷数 + 矩形/倾角/侧边修正 | 判决 + 划伤数 + 污点数 + 清晰度 + 灰度偏差 + 边缘占比 + **取像体检** |
| 怎么取 | `POST /capture_detect` → `GET /last_result` | 节点运行时真调 `check()`; 经 `tools/ar_aoi_bus.py publish` 发话题 |
| 定位 | 产线级缺陷判决（对得上 HMI/PLC 口径） | **取像健康 + 本机同口径体检** + 汇总工控机判决（外部真源 `pull()`） |

⇒ **画布节点不是"另一个 YOLO"**：它不含训练权重, 做的是取像健康度与几何体检;
真正的缺陷判决与模型都在**工控机**那条链上。信号分析页/AR 上同时能看到两组（`AOI.*` = 工控机真值, `光学质量检测.*` = 节点自算）。

## 二、判据图给 YOLO 了吗？——主口径不给, 另有一条影子通道

在役实测 `GET http://192.168.23.23:10082/crop_info` / `/last_result`:

| 字段 | 值 | 含义 |
|---|---|---|
| `model_input_file` | `zmax_main_960_No_4.png` | **模型真正吃的那张** |
| `model_input_kind` | `960x960 方图(同帧派生, 检测完即删)` | 由同帧模板法规整图派生, 与 v6/v7 同口径 |
| `model_input_full` | `C:\Windows\TEMP\zmax_main_960_No_4.png` | 落在工控机 TEMP, 检测完删 |
| `judge_file` / `crop_file` | `Finger_TopView_W900_H332_No_4.png` | **判据图 = 给人看/存档**, 900×332 |
| `canonical` | `[960, 960]` | 规范化画布尺寸（=模型输入尺寸, 与 `imgsz=960` 1:1） |
| `shadow.input` | `判据图压 960x960` (`zmax_ab_judge960_No_4.png`) | **影子通道**: 判据图另压成 960 喂一遍, 判决取并集（防漏判） |
| `verdict` / `verdict_shadow` | `OK` / `OK` | 两条口径的判决 |

**结论**:
1. **主口径不给判据图** —— 模型吃的是同帧派生的 960×960 方图; 判据图只给人看/存档（这条是 v7/v10 起就定的铁律: 改"人看的图"绝不动"模型吃的图"）。
2. **但有一条影子通道**把判据图压成 960×960 又喂了一遍（`shadow.*`）, 两份判决取并集。所以"判据图进过模型"只在影子这一路成立, 且不是主判据。
3. 本机 8793/8791 页面显示的那张判据图（现 914×348 等比口径）**只是显示/存档**, **不进任何模型**; 工控机自己的 900×332 判据图与模型输入也**没有被本轮改动碰过**（在役仍是 `judge_ver=v36-gold19-cxwin-20261009`、`fix_hw=[900,332]`、模型吃 960）。

## 三、接口清单（就这些, 没有别的口）

| 用途 | 接口 |
|---|---|
| 触发拍照+检测（真判） | `POST /capture_detect` → 200 仅代表**受理**, 判决要轮询 `/last_result` |
| 判决 + 模型输入字段 | `GET /last_result`（`verdict`/`count`/`defects`/`model_input*`/`judge`/`shadow`/`ms`） |
| 判据图/原图/原比例 | `GET /picture?kind=crop|origin|natural` |
| **只看画面(快)** | `GET /preview.jpg?q=88`（实测 130ms/帧 · 旧口 2166ms） |
| 区域/矩形/倾角 | `GET /region`（`bbox`/`quad`/`focus`） |
| 裁剪台账 | `GET /crop_info`（`judge.*` 含 `n_keys`/`pitch`/`band`/`gate`/`ver`） |
| 取像参数 | `POST /param?exposure=&gain=`（按点位切曝光: `profile=pt1|pt2`） |
| 落盘/清理 | `GET /storage` · `POST /prune` |

## 四、本机显示侧（8791/8793/8797）在这条链里的位置

- 8791 `cam_live_stream.py` 金手指格: 默认口径 `canonical` = 取工控机 `kind=origin` 原图 → 本机裁切/矫正（现 `gold_roi()` 真实金手指 ROI + 等比 + 尺寸恒定）→ 页面/AR 显示。**只读工控机, 不写**。
- 一键回退: `ZMAX_AOI_GOLD_RECT=0`（回旧口径）; 要直接看工控机自己画的那张: `ZMAX_AOI_GOLD_CALIBER=same`。
- 实测判据: `tools/verify_aoi_gold_display.py`（PASS 17/FAIL 0）· 模型输入未被影响（`model_input_file` 仍是 `zmax_main_960_*`）。

## 五、点位"全局一致"链路（2026-10-12 收口）

一个物理点在四处必须同值, 现在由工具链保证:

```
8793 页面标记/清除 → /ctl/record_point | /ctl/clear_point
   ├─ AOI 点(金手指点1/2 · 侧面点0~3 · 准备点 · 安全点N) → tools/record_point_sdk.py
   │     ├─ L2 技能库   data/skills/l2_atomic/taught_points.json   (L2.goto_* 回的点)
   │     └─ AOI 台账    reports/aoi_points/<点名>.json (+.history.jsonl)  ← 配置中心的真源
   └─ 空间点 spaceN → tools/record_l2_point.py --store space → data/skills/l2_atomic/space_points.json
之后立刻重跑 tools/task_build.py → config/tasks/tasks.json 的 overrides.pt.*
   → 配置中心点位表(QTimer 2s 盯 mtime, 一变就静默刷新, 不用点按钮/不用重启)
体检: gui-venv311/bin/python tools/verify_points_consistency.py   (四处同值, 差 ≤1e-5 m)
```
