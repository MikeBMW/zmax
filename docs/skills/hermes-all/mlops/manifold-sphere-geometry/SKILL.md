---
name: manifold-sphere-geometry
description: Use when 给流形引擎加/改球面 S^n·SU(2) 几何算子。
---

# 流形球面几何算子落地 (S^n · SU(2))

## 何时用
- 老倪给出一份几何/流形方案文档, 要落成真代码与判据。
- 要给 `manifold_engine` 的球面/sphere/su2 档加算子 (投影·度量·exp/log·测地线·平行移动·损失·正则)。
- 要验证“归一化球面/单位向量约束”在引擎里是否真成立。

## 1. 单真源, 引擎只复用不重写
公式全部写进 `src/lerobot/manifold/sphere.py` (numpy + 惰性 torch)。`manifold_engine.py` 只 import 复用 (顶部 `try: from lerobot.manifold import sphere as sphere_mod`), 引擎里**不再写第二份公式** —— 两处实现必然漂移。
未实现的档位必须 `raise ValueError` 明确报错, 不许静默返回假值 (仓库铁律)。

## 2. 改活代码前先冻结行为指纹 (零回归证据)
固定种子跑一遍「投影 / 距离 / 步进 / 测地线」→ `json.dumps(..., sort_keys=True)` → sha256 存成常量。
改完重跑对指纹: 相等 = 逐位零回归。把该 sha256 常量写进判据脚本, 成为可重复的门。
在役档位 (su2) 不要顺手改默认值; 切档要按门槛「有提升非仅不回退」先出同口径 A/B。

## 3. 判据按**真数学**写, 别照抄方案文字
方案文档里的几何描述常有想当然处, 判据要实测把它们挑出来:

- **温度参数**: `normalize(x/τ) ∥ normalize(x)` ⇒ 单向量投影方向对 τ **恒等** (差仅浮点舍入)。
  τ 的真效果在 `⟨p,q⟩/τ` 的 softmax 集中度 (或 vMF κ=1/τ²) 与「输出量级目标」上。判据用软分配熵随 τ 非降来核。
- **单射半径 π**: `log_p(exp_p(v)) = v` 只在 `‖v‖ ≤ π` 成立。越域 exp 折回并反向: `log∘exp(v) = −(2π−‖v‖)·û`, 且 exp 对 2π 严格周期。这是球的固有几何, 不是 bug。
- **双覆盖 (SU(2))**: ±U 是同一旋转。取 log 前先取同叶 (`⟨p,q⟩<0 ⇒ q=−q`); 对径输入满足 `log(−U,−V) = −log(U,V)` (模长相同), **不是**相等。
- **退化点别用 arccos+clamp**: `arccos(c.clamp(1e-6, 1-1e-6))` 在 c=1 给出 ~1.4e-3 的**假距离**。用稳定式 `θ = 2·arcsin(√((1−c)/2))`, c=1 ⇒ 逐位 0; vMF/FS 口径用 `arccos|c|` 的同一稳定式。
- **零向量 / 极小向量**: `eps` + `clamp_min`, 零向量给固定基向量并回 `zero=True` 标记, 不产 NaN; torch 侧反传也要核梯度有限。
- **平行移动真公式**: `v' = v + ⟨v,e⟩((c−1)e − s·p0)`, `c=⟨p0,p1⟩`, `s=√(1−c²)`, `e=(p1−c·p0)/s`。判据: 保长度 / 保内积 / `⟨v',p1⟩=0`。
- **切片/维度坑**: 造候选集时 `rng.normal(size=(k,dim))` 不是 `size=k` —— 后者在错误维度上做点积, 熵等统计看着合理但几何不对。
- **夹紧方向别搞反**: τ↑ ⇒ 集中度↓ ⇒ 熵↑ (非降), 单调性断言要写对。

## 4. 判据脚本形态
`tools/verify_*.py`: 每条约 `chk(id, claim, got, ok, expect, note)` → 落 `zmax_data/eval/*.json` (判据/实测/阈值/结论) → 非全 PASS 时 `exit 1`。
必带: ① 与引擎单真源一致 (逐项数值等价, 容差 1e-12, 说明浮点表达式顺序不同) ② 零回归指纹 ③ 非实现档报错 ④ **真数据段** (现场真源, 如 `zmax_data/ss_live/engine_latest*.json::z_latent`)。
最后跑一遍 `manifold_engine.py --selftest`, 确认所有 ready 档仍全通过。

## 5. 训练侧与现场口径要对齐
现场 `Encoder` 是 PCA/SVD 闭式拟合, 不是 SGD 网络 ⇒ 「反向传播/优化器」方案条款要落到可选的可微投影层 (`SphereProjection`) 上, 并让新能力**默认关** (`L4LatentSpace.project_sphere` 显式调用), 不动在役链路。
