---
name: geometric-latent-branch
description: "Use when 给世界模型/潜空间加 SE(3)/S² 几何分支 — 切空间 head、黎曼测地线损失、零侵入接引擎。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [se3, manifold, jepa, world-model, latent, geodesic, zmax]
    related_skills: [manifold-sphere-geometry, manifold-engine-energy, intact-jepa-integration, su2-unified-state-space]
---

# 给世界模型/潜空间加 SE(3)·S² 几何分支

原生 JEPA 类世界模型的潜空间是**单一欧氏向量**: 姿态误差和纹理语义揉在一起, 预测出的 latent 没有刚体约束,
也直接吐不出可控制量。定式改造 = **共享底层编码器, 上层拆两条互不干扰的分支**:

- **语义分支** (原样不动): 纹理 / 遮挡 / 接触视觉
- **几何分支** (新增): ξ∈se(3) 相对位姿 twist + v_n∈T_nS² 接触法向

目标场景是精细装配的相对位姿 / 接触法向。

## When to Use (何时用)
- 用户给出一份「欧氏语义 + 黎曼几何混合表征」类方案文档, 要落成真代码与判据。
- 要预测相对位姿 / 接触面法向, 而现有模型只输出无几何含义的 latent。
- 要往流形引擎/状态空间里加一条几何通道, 且**不能动在役主干**。
- 现象侧信号: 模型“插斜了但位置对”却完全无反应, 或 PSNR/损失怎么调都不动而几何量从未进过 rec。

## 1. 先查仓里已有的算子, 绝不另造

| 需要 | 现成函数 | 位置 |
|---|---|---|
| SE(3) exp/log/hat | `se3_exp` `se3_log` `so3_exp` `so3_log` `_hat` | `src/lerobot/manifold/lie_intent.py` |
| 接触误差 twist | `contact_twist(T_peg, T_hole)` = `log(T_hole⁻¹T_peg)` | 同上 |
| S² 距离/切映射/测地线/黎曼梯度/三种 loss | `distance` `log_map` `exp_map` `geodesic_slerp` `tangent_project` `sphere_distance_loss` | `src/lerobot/manifold/sphere.py` |
| 法向/切向分解 + 摩擦锥 | `ContactConstraint` | `src/lerobot/manifold/manifold_chain.py` |
| 性能耦合代价 + 帕累托闸 | `PerformanceConstraint` | 同上 |

真正缺的只是「从视觉特征接出的 head + 损失项 + 可拔插开关」。先 `grep -n "def se3_\|def so3_" src/lerobot/manifold/lie_intent.py` 确认,
再决定写什么 —— 造第二份公式必然与既有实现漂移。

## 2. 接入点选共享特征, 不选主干内部

现有 world model 的编码器常是 `Conv + AdaptiveAvgPool(1) + Flatten` —— 空间信息已经压掉了,
所谓"共享 patch token"落地就是那个 256 维向量。几何分支从它接出 ⇒ **主干一层不动**,
原权重 strict load 不破 (新分支用 `strict=False` 单独加载)。

几何分支体量: geo_enc + SE3Head + SphereHead + 方差头 ≈ **10 万参数**,
让它明显小于主分支同等模块 (三层 z_enc ≈100 万) —— 方案要求"轻量"。

引擎侧照现有通道同一模式加三处, 不要发明新接口:
`__init__` 里 `xxx_provider / xxx_note / xxx_w` (env 开关, **默认 0**) · `set_xxx_provider(provider, note)` ·
`_xxx_read()`; `step()` 里 `rec["xxx"]` 与原有通道**并存**。

## 3. 判据 (五组全过才算接进)

1. **未接 provider ⇒ rec 里没有该键** (零回归)
2. **结构完整**: ξ 6 维 / v_n 3 维 / 还原后的 n 是单位向量 / 诊断量齐全, 权重项 `w=0`(只观测不进势)
3. **与原通道并存且不污染**: 原语义通道维数逐位不变
4. **几何算子单调**: 接触流形 `d_SE3` 严格单调且**精确等于平移量** (0→0.001→0.005→0.02→0.05)
5. **开关 = 0 ⇒ 动作逐位相同**: `p_next` `max|Δ| = 0.000e+00`, Φ 逐位相同

## 4. 坑

### 🔴 单调性判据绝不能穿过未训练的网络 (同一个错犯过两次)
几何算子 (`se3_distance` / `decompose_se3`) 的单调性可以直接喂输入测。
但 provider 层的 `d_SE3` 是**「预测 vs 实际」**, 而 ξ 来自**随机初始化的网络** (量级 ~0.109)
⇒ 输入偏移 0→0.05 撼不动这个常数, 测出来反而递减。
定式: **单调性归几何算子, provider 只判「对输入有响应」(跨度 >0)**。
写判据前先问一句 "这个量里有没有未训练的随机项"。

### 🔴 相对位姿的基准必须首步锁定, 不能用单位阵
`T_pred = g_rel0·exp(ξ)` 而 `T_cur` 是**绝对**位姿。把 `g_rel0` 设成 `I` ⇒ 两者坐标系不同
⇒ `d_SE3` 恒带一个固定偏移 (实测 0.109m), 误差怎么变都不收敛。
定式: provider 首次调用时 `self._baseline_T = T_cur.copy()`; 之后 `T_rel = inv(baseline)@T_cur`,
**比较对象用 `T_rel` 而不是 `T_cur`**, 并在 rec 里记 `baseline_locked` 供审计。

### 🔴 欧氏版对纯姿态误差完全失明 —— 这是改造的全部价值, 要钉成判据
纯姿态偏 1°: 黎曼版 `V_p = ½ξᵀW₆ξ = 1.523e-07`, 欧氏版只看 3 维位置差 ⇒ **正好 = 0**。
"插斜了但位置对"在旧实现里不可见。任何声称"黎曼改造有用"的汇报都必须带这一条数字对照,
否则就是没有证据的主观说辞。

### API 口径 (不先看一眼就白跑一轮)
- `sphere.normalize(x)` 返回 **`(array, meta_dict)` 元组**, 不是数组 ⇒ 取 `[0]`。
  同族的 `tangent_project` / `exp_map` 也可能带 meta, 接之前先 `type()` 看一眼。
- `ManifoldEngine.step(state, potential_fn=None, dt=...)` —— **第二个位置参数是 `potential_fn`**, 不是速度。
  传 ndarray 会报 `'ndarray' object is not callable`。
- `PerformanceManifold.evaluate(peg_head)` 的欧氏对照必须喂 `p.hole_pos`, **不能喂原点** ——
  `HOLE_POS` 不是 0, 喂原点会得到一个假的不为零的 `V_p`, 让人误判"欧氏版也看得见姿态误差"。
- 测 `ManifoldEngine` 用 `homeostasis=False`: 否则每步原子写 `zmax_data/ss_live/manifold_homeostasis.json`,
  与常驻引擎回路抢同一文件, `os.replace` 偶发 `FileNotFoundError` (tmp 被对方删掉)。
  这不是引擎 bug, 是测试隔离没做。
- **法线必须开 antipodal 消歧**: `d(a,b)=arccos(aᵀb)` 在 `a=−b` 时给 π, 但接触面法线"反了"与
  "错 90°"不是一回事 ⇒ 用 `sphere.distance(..., antipodal=True)`, 实测法线反向时 risk=0。
- 方差头用**对角 Σ**: 输出 log-std 再 `exp` ⇒ SPD 必然成立, 不需要 Cholesky 约束。
  切空间高斯 NLL 写成 `0.5·Σ[(ξ−μ)²/σ² + 2logσ + log2π]`, 自检要能手算对平。

## 5. 损失与训练节奏

```
L_g = ‖log(g⁻¹·g*)‖²          # 用 lie_intent.se3_log
L_n = arccos(nᵀn*)²           # 小角度可退 ‖n−n*‖²
L_total = L_jepa + λ_g·L_g + λ_n·L_n
```

- **网络永远只输出切空间向量 (欧氏)**, 不输出流形元素 —— 这是避开黎曼层/黎曼 BN 不稳定性的关键,
  也匹配精细操作的"小扰动"假设。
- `λ` 从 `1e-2 ~ 1e-4` 起步 (JEPA loss 量级远大于几何 loss)。
- **分三阶段预热**, 不然几何分支被语义 loss 主导: ①只训主干 (冻结几何分支) ②冻结主干+语义分支,
  只训几何 (先法线后 SE3) ③全放开联合微调。
- 动量 target (EMA, 冻结梯度) 与 JEPA 理念一致: 目标来自动量编码器而非人工标签,
  适配无标注时序视频; 有真值姿态时可切监督版。
- 时序 rollout: `ξ_{t+τ} = f_dyn(c_t, h_g_t, a_t)` → `g_{t+τ} = g_t·exp(ξ̂_{t+τ})`。

## 6. 汇报纪律

仓里现成的 JEPA 权重可能**对画面几乎不敏感** (实测 8 张真帧输出余弦 1.00000、对 state ±0.3 扰动余弦 0.995)
⇒ 那是"欠训练的世界模型通道", 不是看图编码器。几何分支同样只对 state 有响应。
**必须写清"这是结构接通, 不是能力达标"**, 不能暗示模型在学画面。
同理: 用合成数据跑的 e2e (PSNR 5.6) 只证明通路, 不代表质量, 汇报时要标出。
