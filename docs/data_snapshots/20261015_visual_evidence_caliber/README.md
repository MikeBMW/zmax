# 现场数据快照 · 视觉证据口径 + 链路 (2026-10-15, for v5.50.72)

这一轮**没有改模型、没有改画布**，改的是**取证口径**：现场那句
「在役 YOLO 在活帧和 60 张历史帧上 ndet 全 0 ⇒ 定量视觉证据为空」经实测**结论不成立**，
被阈值 + 分辨率两个口径切掉了真信号。本目录是把这件事的原始证据留档，便于任何人复核。

## 一、结论（带口径，别丢口径看）

在役权重 `models/yolo_peg_live.pt`（类别 peg / OPT_Gold，软链→
`external/lerobot-smolvla-lew/runs/detect/outputs/yolo_annot/annot_0919_1814/weights/best.pt`）
在**同一张真机帧**上，分数对**分辨率口径**高度敏感：

| 帧 | imgsz | best 分 | 阈值响应 | 判定 |
|---|---|---|---|---|
| `frame_local2_best0.219.jpg` (1280×720 工位相机) | **640**（在役链路口径） | **0.2188** | ≥0.01→12 · ≥0.05→2 · ≥0.10→1 · **≥0.15→1** · ≥0.25→0 · ≥0.40→0 | **弱非空**（有目标但低置信） |
| 同一张帧 | 1280 | 0.0881 | ≥0.01→12 · ≥0.05→2 · ≥0.10→0 | 空 |
| 活帧 `8791/local2`（06:26 现取） | 1280 | 0.1046 | ≥0.01→13 · ≥0.05→3 · ≥0.10→1 · ≥0.15→0 | 空 |
| 训练用真机评测帧（640×480，`zmax_data/eval_frames/live_1014_230655`，取 4 张） | 1280 | 0.015~0.062 | ≥0.05 起全 0 | 空（该路确实无目标） |

在役链路口径：`tools/ss_yolo_on_real.py` → `SS_YOLO_IMGSZ=640` · `SS_YOLO_CONF=0.4`；
新预测器 `tools/ss_meta_task_predict.py:123` → `conf=0.25`。
⇒ **0.219 的真检出被 0.4 / 0.25 统一处理光**，于是报「无检出」。这不是"画面里没目标"。

## 二、曝光 vs 现场灯（用同刻另一路相机判别）

| 路 | 均值 | std | max | 非黑占比 | 说明 |
|---|---|---|---|---|---|
| 8791/local2 | **115.8** | 52.6 | 255 | 100% | 曝光正常、有内容 |
| 8791/depth | 31.0 | 32.9 | 235 | 68.7% | 深度伪彩 |
| 8791/local | 5.98 | 1.0 | 11 | 0.02% | 近全黑 |
| 10083（产线 AOI 真帧） | 0.0 | — | — | — | 全黑（本轮链路不可达，取不到新帧） |

⇒ 同一时刻同一工位**有正常画面** ⇒ 不是"现场没光"，是那两路相机自身的曝光/驱动状态
⇒ 处置优先**抬曝光（可逆）**，而不是等现场灯。

## 三、链路状态（本轮的真实约束）

见 `link_status.txt`：网卡无 `192.168.23.x` 地址（`enxeae07a800a2f UNKNOWN`）·
ping `192.168.23.23`(AOI) 与 `192.168.23.66`(Orin) 100% 丢包 · AOI TCP 10082/10083 不通 ⇒
**10083 曝光现在写不了**（不接受"试试看"，网络不可达时不发任何写/动作）。链路恢复后第一件事：
曝光扫描 `80000/40000/30000/16000us` 各取帧算均值 —— 随曝光单调升 ⇒ 曝光问题；都不动 ⇒ 才轮到灯。

## 四、文件清单

| 文件 | 是什么 |
|---|---|
| `link_status.txt` | 网卡/ping/AOI TCP 的原始输出（时间戳见首行） |
| `frames_local.txt` | 本机四路帧的 均值/std/max/非黑占比（只读取帧） |
| `frame_local2_best0.219.jpg` | 参考帧原件（imgsz 640 下 best=0.2188） |
| `yolo_threshold_frame_imgsz640.txt` | 参考帧 · imgsz 640 · 阈值响应表（**在役口径**） |
| `yolo_threshold_frame_0.219.txt` | 参考帧 · imgsz 1280 · 阈值响应表（对比口径） |
| `yolo_threshold_local2.txt` | 现取活帧 · imgsz 1280 · 阈值响应表 |
| `yolo_threshold_evalframes.txt` | 训练用真机评测帧 · imgsz 1280 · 阈值响应表 |
| `dashboard_fullflow.json` | 大屏数据源的 `fullflow` 段（7 任务闭环结果） |
| `signal_analysis_meta_pred.json` | 信号分析唯一依据 live.json 的话题数 + `ss_meta_pred` 现值 |

## 五、关联

- 工具：`tools/yolo_threshold_response.py`（报"无检出"前必跑）· `tools/probe_frames_local.py`（本机帧可用性）
- 本次 7 任务全流程闭环快照：`docs/data_snapshots/20261014_fullflow7/`
- 技能：`live-camera-detector-adaptation` §0·补（阈值口径 + 曝光 vs 灯 判别法）
- 复跑：`bash tools/snapshot_v55072_evidence.sh`（只读取证，约 20 s）
