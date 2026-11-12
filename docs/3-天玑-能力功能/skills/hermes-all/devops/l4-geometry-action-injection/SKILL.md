---
name: l4-geometry-action-injection
description: Use when 上层几何量进不了下层动作(l4_cond_injected=false)。
version: 1.0.0
author: 静静 (Hermes)
license: MIT
metadata:
  hermes:
    tags: [manifold, action-injection, lyapunov, precision-assembly]
    related_skills: [l2-node-signal-linkage, manifold-potential-field-design, se3-impedance-control]
---

# L4 几何量 → L3 动作的解析注入

## When to Use

- 画布或日志里 `l4_cond_injected=false` / `l4_in` 有值但动作不变
- 分层架构里上层几何量拼进网络输入端，但该通道未训练（等价随机投影）
- 需要证明「上层推理真的作用于动作」而不只是端口有值
- 亚毫米插配要径向纠偏而不想重训


## 问题模式

分层系统里「上层几何量拼进下层网络输入端」而该通道训练时未被覆盖 ⇒ 权重是随机初始化的小尺度投影 ⇒ **注入等价于加噪声**。工程上必须诚实标 `l4_cond_injected=false`，这也解释了为什么「链路通但效果不出」。

**解法不是重新训网络，而是解析注入**：用装配公差构造度规，让几何量直接改动作方向。

## 算法 (可直接搬)

```
M = σt²·Pt + σn²·Pn          # Pt=I−nnᵀ, Pn=nnᵀ, σt=径向单边间隙, σn=推进行程
Δξ_dir = −M⁻¹∇V              # 黎曼自然梯度(度规下最速下降)
α = α₀·η·exp(−V/V₀)         # 越不确定越不敢动; 离目标越远越不敢大步
cap = min( max(β‖ξ_d‖, c_min)+ε , 0.95‖δ‖+ε )   # 双重限幅
Δξ = (Δξ_dir/‖Δξ_dir‖)·min(α‖ξ_d‖, cap)
ξ* = ξ_d + Δξ
```

关键不变量: M 正定 ⇒ ∇VᵀΔξ ≤ 0 ⇒ V 单调不增（Lyapunov）。

## 三个必踩的坑

1. **只有比例限幅会被压死**：对位阶段名义步长常仅 0.05mm，`cap=0.6‖ξ_d‖` ⇒ 修正量 0.03mm，等于没修。必须加**绝对下限 c_min**(0.3mm)。
2. **有下限就会过冲**：偏差小到 0.04mm 时 cap 仍放 0.3mm ⇒ 冲过零点反复。必须加**第二重偏差限幅** `0.95‖δ‖`，δ 由 `W⁻¹∇V` 从梯度反解。加完后收敛严格单调。
3. **V 的量级决定门控死活**：V=½δᵀWδ 若 δ 用米，V 是 m²(≈0.15)；σ²=16mm² 是 mm² ⇒ `exp(−V/σ²)` 下溢为 0 ⇒ 修正恒为 0。**单位必须与参数同源**（都用 mm），或 V₀ 按实测 V 的中位数取。

## 验证四件套 (缺一不可)

- **A 收敛性**：受控横向偏差 1.0/0.5/0.2mm，逐拍修正，要求单调 + 3 拍内 <0.05mm。
- **B 各向异性**：纯径向/纯轴向/45° 三组，径向:轴向 修正比应精确等于 (σn/σt)²（不是「大概」）。
- **C 一致性**：拿真实段表位移，检查方向余弦 = 1.000000、Lyapunov 成立率 100%、限幅越界 0。
- **D 端到端**：真跑节点，读 `out1.l4_cond_injected`。远离孔时 η→0 ⇒ 修正被门控抑制是**正确行为**，别当失效；另做一个近孔受控场景证明正常工况下真出非零修正。

## 轨迹数据的陷阱

`ss_traj_last.json` 的 `obs` 里 `11:14`(peg_head) 在这条轨迹里**是常量**（未跟踪），真实运动在 `0:3`(hand)。直接拿 peg_head 算偏差会得到 0 修正还以为算法坏了。先统计每列唯一值个数再选列。

## 接入位置

- 算法：`src/lerobot/policies/manifold/geodesic_inject.py`（`anisotropic_metric`/`correct`/`split_components`/`lyapunov_check`）
- 接入：`middleware/nodes/impl/flow_matching_impl.py` 在 ff 之后、输出之前叠加，**不动 PURE**
- 几何量来源：性能流形 `_SS_STATE['perf_mani']` 的 `grad`/`eta`/`V_p` + 接触流形 `axis`
- 开关：画布参数 `l4_inject=off` 或 `ZMAX_L4_INJECT=0` 一键退回原行为

## 视触觉融合 (v2, 2026-11-11) — 六个会静默搞坏系统的坑

纯视觉在盲插区「接触即盲」：进孔后相机分不出 0.1mm 级径向偏差，∇V 方向已不可信。解法是把力接进梯度。

**坑1 ─ 符号：∇V_tac = +P_t·F，不是 −F**
接触力是**排斥力** ⇒ 力方向 = 势能上升方向 ⇒ ∇V 与力**同向**。
写成 −F 会得到「修正方向与孔心相反」，把模块**推出孔**，比不修更糟。
自检断言：δ=−0.4mm(偏 −X)、F=(−2.4,0,0) ⇒ Δξ 必须 >0 (+X 朝孔心)。写进测试，符号错立刻红。

**坑2 ─ 触觉路径的绝对限幅必须 δ=‖F‖/K**
∇V 在触觉路径量纲是**力(N)**，`W⁻¹∇V` 得到 1/K 倍假偏差 ⇒ 限幅失效 ⇒ **极限环**（实测 0.08↔0.24 振荡 12 拍）。除以接触刚度 K(N/mm) 后 2 拍收敛到 0.004mm。
另：防除零的 eps **不得加进 cap 上限**，否则单拍越过真实偏差造成过冲。

**坑3 ─ 嵌套函数 + 宽 except = 静默失效**
`_proj_radial` 定义在 `tactile_to_gradient()` 内，`correct()` 调用必 NameError，而 `except Exception: pass` 把错吞了 —— 表现为「限幅没生效但不报错」。规则：算法层被多处复用的辅助函数一律提到模块级；限幅/限流处的 except 必须写进输出（`info["cap_err"]`）。

**坑4 ─ 融合必须先各自归一化再加权**
力(N) 与视觉代价梯度量纲差几个数量级，直接相加 = 只信大的那一路，融合形同虚设。

**坑5 ─ 参数真源的键名必须与 DEFAULTS 完全一致**
`inject_cfg.geometry()` 曾输出 `sigma_t`，而 DEFAULTS 用 `sigma_t_mm` ⇒ 真源**从未生效**，只因默认值恰好等于真源值才没暴露。
验证法：改真源值（σt 0.30→0.50）后重载，看 `correct()` 实际用量是否跟着变；不变就是假真源。

**坑6 ─ 触觉方向别用 peg−hole**
`gen_tactile.synth_tactile` 的方向就是 `(peg−hole)/d`，与视觉**同源同向** ⇒ 融了等于没融。降级代理要用**闭环残差**，并在输出标 `src=*_proxy`。
真力到位前，`src="force"` 只用受控输入验证算法正确性，**不能**宣称真机有效。

另：`tactile4[2]` 是沿插入轴的**轴向**分量、`tactile4[3]` 才是径向 —— 传反了会被 `_radial_part` 全部剔除，表现为「触觉接了但径向幅恒为 0」。

## 判据脚本

| 脚本 | 判什么 |
|---|---|
| `tools/verify_visuo_tactile.py` | 26 项：力→梯度方向/权重切换/盲插死区/力保护/收敛/降级/各向异性 |
| `tools/probe_l4_inject.py` | 真帧端到端：注入 `_SS_STATE['tactile4']` 看 `w_tac` 真变（0.003→0.900） |
| `tools/verify_l4_injection.py` | 纯视觉回归：三档收敛 / 400× 各向异性 / 257 段 Lyapunov |

## 验收口径

改完必须回归全图 `verify_l2_linkage.py --engine --all`，联通率**不变**才算纯增量；若数字变了先查是不是注入改了下游 payload 类型。
