---
name: state-space-55d-upgrade
description: Use when 把统一状态向量升维(43→55)或改手册/PPT.
version: 1.0.0
author: Hermes Agent
license: proprietary
metadata:
  hermes:
    tags: [state-space, 55d, backward-compat, slerp, geodesic, deck]
    related_skills: [se3-pose-prediction-head, manifold-sphere-geometry, deliverable-doc-authoring]
---

# 统一状态空间 43D→55D 升级 (接口升级, 不是改数字)

## When to Use
- 要把 L2 统一状态向量扩维 (多模态传感器接入), 又不能让在役权重/数据/标定失效
- 要改技术手册/PPT 的状态维度章节
- 遇到"升级后引擎空转/形状不匹配", 或测地线/SLERP 训着训着 NaN

## 分段表 (唯一口径, 落地在 `src/lerobot/policies/left_right/state_space/unified_state55.py`)
```
0:39   视觉与本体 39  (tcp_p3|夹爪标量1|工件xyz3|相对位移3|夹爪两维2|关节角6|关节速6|TCP旋转9|目标位3|孔位3)
39:43  触觉力觉 4    grasp|contact|dir_x|dir_y           ← 语义一字不动
43:55  预留扩展 12   多指触觉4|温度1|声学1|电流2|备用4    ← 零初始化, 沉睡→逐步觉醒
```
铁律: **每维有名字/单位/来源**; 消费端一律 `SLICE[name]` 按名取, 不许自己数下标;
`validate_layout()` 断言 19 段首尾相接覆盖 0:55 (断档/重名直接抛)。

## 零扰动升级的三条数学依据 (缺一条就会静默错)
1. **编码器补 0 行**: `(x₅₅ − [μ₄₃,0]) @ [W₄₃; 0ᵀ] = (x₄₃ − μ₄₃) @ W₄₃` ⇒ z 逐位不变 (实测差 0.0)。
   在 `Encoder.load(path, state_dim)` 里做, 并记 `calib_pad={from,to,note}` 供对账。
2. **老数据不重训**: 在役轨迹 43 维 → 读入补 0 到 55, 台账记 `obs_dim_from=43`。
3. **工厂默认口径不动**: `fuse_sensors()` 默认仍 43 (在役 L3/L4 权重吃这个形状);
   新链路显式 `fuse_sensors55()`/`dim=55`。静默改默认形状 = 打挂在役模型。

## 两个必踩的数值坑 (都实测炸过)
- **acos 测地线**: `2·acos(⟨q1,q2⟩)` 在 q1≈q2 处导数 ∞ ⇒ 训练第一步 NaN。改 `2·atan2(‖v‖,|w|)` (r=q1⁻¹⊗q2)。
- **SLERP**: `θ=acos(dot)` 在 dot=±1 两处同样发散; 且**不能用 `where` 掩盖已除零的支路**
  (0×NaN=NaN 照样回传)。正确写法: θ 用 atan2 形式; 双覆盖先取反 q_target 走短弧;
  分母 `clamp_min(1e-7)` 再除; θ<1e-4 时用线性插值极限 (near mask 混两个**有限**值)。

## 上线检查清单
- `python tools/verify_state55.py` → 七组判据 PASS (布局/融合/扩展隔离/43vs55/测地线/SLERP/兼容)
- `engine_latest.json` 里 `state_dim=55`、`calib_pad={from:43,to:55}`、动作非零、`z_latent` 16 维
- 重启引擎前先确认状态源存在: 缺 `data/database/zmax/sources/canvas/ss_traj_last.json` 时引擎只空转不报错
  (日志 `⏸ 无状态唯一依据`) —— 曾因 `arr.shape[1] < STATE_DIM` 判据把 43 维老轨迹直接判成"无源"。

## 手册/PPT 改版 (288→293 页, `tools/deck_55d_revise.py`)
- **克隆正文页, 不要克隆数字卡页**: 6.09 是三块数字卡版式, 复用它会把正文写进整页背景矩形,
  旧卡片(10/10、w=0.3、+17.8%)还留着 ⇒ 版式糊掉。
- `table.rows[-1]` 在 python-pptx 里会 IndexError ⇒ 用 `rows[len(rows)-1]`; 加行 = deepcopy 最后一个 `<a:tr>` 再 append。
- 整段重写文本时保留 `pPr` + 首个 run 的 `rPr` (deepcopy 后重建 `<a:p>/<a:r>/<a:t>`), 否则字体/字号/配色全丢。
- 插页后**必须重排右下列页码** (静态文本, 不是页码域), 封面页数也要改 (版本号与页数常在同一个文本框 ⇒ 一次替换两个, 用 elif 只改一个会漏)。
- **同一锚点插多页必须倒序**: 每页都插在锚点正后方, 正序会得到 g,f,e 倒序页。
- 星号 `**` 不进 PPT (markdown 残留会被老倪一眼看到); 用 `【】`/`「」`。
- 走 `%` 格式化的字符串里字面百分号必须写 `%%`, 否则 `5%` 被当格式符 ⇒ TypeError。
- 验收: `soffice --convert-to pdf` + `pdftotext -layout -f N -l N`, 逐页确认无截断 (文本在但被裁会看不出来)。

## 端侧 (550C Intel) 落地口径
- **550C 没有 torch**: 只有 numpy + OpenVINO。`lerobot` 包 `__init__` 会拉 huggingface_hub ⇒ 端侧按**文件路径 importlib 加载**
  `unified_state55.py`/`perception.py`, 所以 `perception.py` 必须留绝对导入回退:
  `try: from .unified_state55 import X / except ImportError: from unified_state55 import X`。
- `verify_state55.py` 的 ⑤⑥ 两组需要 torch ⇒ 无 torch 的机器标 `skipped` 并在报告里显式列出, **不能静默算 PASS**。
- 550C 的权重是拷贝不是 git clone (`/home/intel/zmax`→`zmax_550c`), 部署走 rsync 单文件, 别指望 git pull。
- 端侧在役 IR: `zmax_data/models/ir/{yolo_peg_live,sam3_enc_static}.xml` + `intact_{enc,pred}.onnx`; NPU 与 iGPU 是两台不同设备, 同一模型延迟差 6 倍 (SAM3: NPU 2872ms vs iGPU 474ms) ⇒ 按模型分设备, 不要全塞 NPU。

## 算力实测 (2026-11 基线, 可复用对照)
| 组件 | 550A 4060 | 550C NPU | 550C iGPU | 550C CPU |
|---|---:|---:|---:|---:|
| YOLO 640 | 9.04 ms | 2.90 ms | 2.19 ms | 98~144 ms |
| INTACT 编码 | — | 2.73 ms | 1.79 ms | 48~116 ms |
| INTACT 预测 | — | 1.19 ms | 1.46 ms | 2.19 ms |
| SAM3 编码 | 733~1141 ms | 2872 ms | 474 ms | >170 s |
| SmolVLM2-500M | 768 ms/frame | — | — | — |
| 流形引擎 1 步 | 0.84 ms | 1.0 ms (CPU) | — | 0.99 ms |

- 入拍链 (YOLO+INTACT+流形+动作头) 在 550C 上合计 **8.33 ms / 100 ms ⇒ 占空 8.3%**; SAM3/VLM 只能异步。
- 550A 8GB 显存: 在役并发实测 **5932/8188 MiB**; Qwen2.5-VL-3B (权重 7.1GB) 与三件大模型**不可能同卡**, 实测 OOM ⇒ 本地只留 SmolVLM, L5 场景理解走 API。
- 测之前先停 `zmax-evolve-ar` / `zmax-ss-engine-loop` / lazy sam3 放显存, 测完原样起回并核对 `engine_latest.json` 新鲜度。
