# 代码映射表 · 文档 ↔ 代码

**这张表是唯一的"概念落在哪行代码"的索引。** 每行的 `代码` 必须真实存在、`符号` 必须真在该文件里 ——
`tools/verify_doc_code_map.py` 会逐条核对，任何一条指向不存在的路径或符号就判 FAIL。

用法：想知道"世界模型在哪"，看第 W 节；改了代码，回来更新对应行（这是纪律，不是文档工作）。

---

## W · 世界模型

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 状态空间动作头（DiT） | `4-天权-模型算法/README.md` | `src/lerobot/policies/smolvla_lew/state_space_action_head.py` | `class StateSpaceActionHead` | `models/state_space_action_head` |
| 流形读出（潜→状态） | `4-天权-模型算法/世界模型/L4_latent_space.md` | `src/lerobot/manifold/predictor_layer.py` | `class ManifoldReadout` | — |
| 潜空间预测器 | 同上 | `src/lerobot/manifold/predictor_layer.py` | `class LatentPredictor` | — |
| L5 规划器 | `4-天权-模型算法/README.md` | `src/lerobot/policies/left_right/state_space/planner.py` | `class TaskPlanner` | `config/tasks/tasks.json` |
| 认知/决策（动作调制） | `4-天权-模型算法/left_right_policy.md` | `src/lerobot/policies/left_right/state_space/cognition.py` | `class ActionModulator` | — |
| 安全否决层 | `0-总纲/README.md` | `src/lerobot/policies/left_right/state_space/safety.py` | `def saturate` | — |

## S · 状态空间

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 43D 状态组装 | `4-天权-模型算法/MODEL-THEORY.md` | `src/lerobot/middleware/nodes/impl/shared_runtime.py` | `def _ss_ensure_obs43` | `data/database/zmax/sources/canvas/ss_traj_last.json` |
| 状态帧取数（obs 口径） | 同上 | `src/lerobot/middleware/nodes/impl/shared_runtime.py` | `def _ss_frame` | 同上 |
| 融合定位建图 | `4-天权-模型算法/space_model_nodes_load_map.md` | `src/lerobot/middleware/nodes/impl/ss_sensor.py` | `def node_ss_s1` | — |
| SU(2) 统一映射 | `4-天权-模型算法/MODEL-THEORY.md` | `src/lerobot/policies/left_right/state_space/su2.py` | `def encode_obs43` | — |
| 状态总线（进程内） | `4-天权-模型算法/状态空间/DDS-MASTER-DATA.md` | `src/lerobot/middleware/nodes/impl/shared_runtime.py` | `_SS_STATE` | — |

## F · 流形引擎

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 流形引擎主体 | `4-天权-模型算法/manifold_engine_20260924.md` | `src/lerobot/manifold/manifold_engine.py` | `def project` | `config/calib/zmax_manifold.json` |
| 梯度流 | 同上 | `src/lerobot/manifold/manifold_engine.py` | `def gradient_flow` | 同上 |
| 接触流形 | `4-天权-模型算法/README.md` | `src/lerobot/manifold/manifold_layer.py` | `class ContactManifold` | — |
| 性能流形（装配代价 V_p） | `4-天权-模型算法/README.md` | `src/lerobot/manifold/manifold_layer.py` | `class PerformanceManifold` | — |
| 前馈加速器 | `4-天权-模型算法/README.md` | `src/lerobot/policies/left_right/state_space/parallel.py` | `class FeedforwardAccelerator` | — |

## I · 动作注入（专利 ZMP-2026-013）

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 各向异性度规 + 自然梯度 | `1-天枢-产品边界/patents/ZMP-2026-013_*.md` | `src/lerobot/policies/manifold/geodesic_inject.py` | `def correct` | `config/calib/zmax_manifold.json#inject` |
| 度规构造 | 同上 | `src/lerobot/policies/manifold/geodesic_inject.py` | `def anisotropic_metric` | 同上 |
| 径向/轴向分解 | 同上 | `src/lerobot/policies/manifold/geodesic_inject.py` | `def split_components` | — |
| 李雅普诺夫判据 | 同上 | `src/lerobot/policies/manifold/geodesic_inject.py` | `def lyapunov_check` | — |
| 触觉力→梯度（v2） | `1-天枢-产品边界/patents/ZMP-2026-013_*.md` §4.2 | `src/lerobot/policies/manifold/geodesic_inject.py` | `def tactile_to_gradient` | `config/calib/zmax_manifold.json#inject` |
| 视觉/触觉融合权重 | 同上 §4.2(c) | `src/lerobot/policies/manifold/geodesic_inject.py` | `def fuse_gradient` | 同上 |
| 力阈值保护 | 同上 §4.5 | `src/lerobot/policies/manifold/geodesic_inject.py` | `def force_guard` | 同上 |
| 径向投影（剔轴向） | 同上 §4.2(b) | `src/lerobot/policies/manifold/geodesic_inject.py` | `def _radial_part` | — |
| 触觉离线实测 26 项 | `4-天权-模型算法/README.md` | `tools/verify_visuo_tactile.py` | `def ck` | — |
| 参数读取（真源） | `0-总纲/README.md` | `src/lerobot/policies/manifold/inject_cfg.py` | `def load` | `config/calib/zmax_manifold.json` |
| 接入点（动作头） | `4-天权-模型算法/README.md` | `src/lerobot/middleware/nodes/impl/flow_matching_impl.py` | `def run` | 画布 `ssdec.params.l4_inject` |

## Q · 光学质量检测（专利 ZMP-2026-014）

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 一次完整巡检 | `1-天枢-产品边界/patents/ZMP-2026-014_*.md` | `src/lerobot/policies/aoi/quality.py` | `def inspect_aoi` | — |
| 判定内核 | `2-天璇-作业任务/AOI_GOLD_DETECTION_CHAIN_20261012.md` | `src/lerobot/policies/yolo_3d/quality_check.py` | `class AOIQualityChecker` | `config/topics/scene_tags.json` |
| 金手指搬运判决 | 同上 | `src/lerobot/policies/aoi/gold.py` | `def gold_bypass` | `192.168.23.23:10082` |
| 金手指本机推理 | 同上 | `src/lerobot/policies/aoi/gold_yolo.py` | `def gold_yolo_bypass` | `models/yolo_gold_v2.pt` |
| 表面本机重算 | `2-天璇-作业任务/AOI_SURFACE_V20_1_20261012.md` | `src/lerobot/policies/aoi/surface.py` | `def surface_bypass` | `192.168.23.23:10083` |
| 异步工作者 | `0-总纲/README.md` | `src/lerobot/middleware/nodes/impl/ss_aoi.py` | `def _aoi_worker` | `ZMAX_AOI_MIN_INTERVAL_S` |
| 质量门四态裁决 | `1-天枢-产品边界/patents/ZMP-2026-014_*.md` | `src/lerobot/middleware/nodes/impl/safety_limit_impl.py` | `def _quality_gate` | — |
| 端口契约（PURE） | `0-总纲/README.md` | `src/lerobot/middleware/nodes/n_inspection.py` | `PURE` | — |

## A · 感知与检测

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| YOLO 2D→3D | `4-天权-模型算法/感知与检测/yolo_weights_lineage_20260919.md` | `src/lerobot/policies/yolo_3d/yolo_state_aligner.py` | `class YoloStateAligner` | `models/yolo_peg_live.pt` |
| 开放词汇分割 | `4-天权-模型算法/感知与检测/sam3_open_vocab_seg_L2_20260929.md` | `src/lerobot/policies/sam3_seg/geometry3d.py` | `def mask_3d` | — |
| 触觉合成/融合 | `4-天权-模型算法/README.md` | `src/lerobot/policies/yolo_3d/gen_tactile.py` | `def synth_tactile` | — |

## P · 策略与训练

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 联合训练入口 | `4-天权-模型算法/策略与训练/Z-MAX-SmolVLA训练方案.md` | `tools/joint_train_all.py` | `def build_stages` | `--only L4,L3,L2` |
| LoRA 合并 | `4-天权-模型算法/README.md` | `tools/merge_lora_ckpt.py` | `def merge` | — |
| 左脑快策略 | `4-天权-模型算法/left_right_policy.md` | `src/lerobot/policies/left_right/modeling_left_right.py` | `class LeftBrainMLP` | — |

## E · 执行与安全

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 安全限幅/饱和 | `0-总纲/README.md` | `src/lerobot/middleware/nodes/impl/safety_limit_impl.py` | `def run` | — |
| 物理世界执行 | `2-天璇-作业任务/Z-MAX-插拔状态机.md` | `src/lerobot/middleware/nodes/impl/ss_act.py` | `def node_ss_exec` | `tcp_out/latest.json` |
| 原子技能物理约束 | `4-天权-模型算法/README.md` | `src/lerobot/policies/left_right/state_space/safety.py` | `def saturate` | `config/calib/zmax_skill_physics.json` |

## D · 数据总线

| 概念 | 文档 | 代码 | 符号 | 真源 |
|---|---|---|---|---|
| 信号注册表 | `4-天权-模型算法/状态空间/DDS-MASTER-DATA.md` | `config/topics/scene_tags.json` | — | 305+ 条信号 → 场景着色 |
| 总线写入 | 同上 | `tools/ar_aoi_bus.py` | `def publish` | `zmax_data/ar_live/ar_aoi_live.json` |
| 节点总线桥 | 同上 | `src/lerobot/middleware/nodes/impl/shared_runtime.py` | `def _ar_aoi_publish` | 同上 |
| 场景信号色标 | 同上 | `tools/sig_scene_tags.py` | `def scenes_payload` | `config/topics/scene_tags.json` |

---

## 校验

```bash
gui-venv311/bin/python tools/verify_doc_code_map.py          # 逐条核存在性
gui-venv311/bin/python tools/verify_doc_code_map.py --strict # 符号级(读文件真找符号)
```

**判据**：路径不存在 / 符号找不到 ⇒ FAIL；文件存在但符号是占位 `def`（未细化）⇒ WARN。
