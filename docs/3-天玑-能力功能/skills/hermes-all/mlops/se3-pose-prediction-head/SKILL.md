---
name: se3-pose-prediction-head
description: Use when 用 6 维 se(3) 增量预测 7 维位姿 (流形引擎)。
version: 1.0.0
author: Hermes Agent
license: proprietary
metadata:
  hermes:
    tags: [se3, manifold, quaternion, geodesic, pose-prediction, zmax]
    related_skills: [se3-impedance-control, manifold-sphere-geometry, geometric-latent-branch]
---

# SE(3) 7 维位姿预测头 (6 维切空间 → 指数映射 → 7 数)

## When to Use
- 要用网络预测机器人位姿, 但**不许**直吐 7 个数 (四元数约束)
- 要做 SE(3) 流形引擎的「6 维 ξ → 7 维位姿」链路或查它为何 NaN / 不准
- 需要测地线损失 / 群乘法更新 / 四元数模长保持的验收口径

网络**永远只吐 6 维** ξ=[ρ;φ] (平移在前, 方案口径), 7 维由流形引擎的群乘法给出:
```
ξ ∈ se(3) → T' = T·exp(ξ^) → pose7 = [x,y,z,qw,qx,qy,qz]
四元数更新走 q' = q ⊗ Δq(φ)          # 不经矩阵反解 ⇒ ‖q‖≡1 (硬约束由流形给, 不是学的)
损失 = SE(3) 测地线: 2·atan2(‖v‖,|w|) of q_p⁻¹q_t + ‖Δp‖   # 不逐元素回归四元数
```
入口: `src/lerobot/manifold/se3_pose_head.py` · 引擎接法 `ManifoldEngine.set_se3_pose_provider()`
(rec["se3_pose"]) · 训练 `tools/se3_pose_head_train.py` · 实机 `tools/se3_pose_provider.py` ·
验收 `tools/verify_se3_engine.py` (四组判据, 出 reports/se3_engine/)

## 🔴 四个会让结果静默错的坑

1. **acos 在 1 处导数发散** ⇒ 用 `2·acos(⟨q_p,q_t⟩)` 做旋转损失, 训练**第一步就 NaN**
   (预测≈真值时内积→1)。改 `2·atan2(‖v‖, |w|)`, w=⟨q_p⁻¹q_t⟩ 的实部, 全程有限。
2. **四元数不要从旋转矩阵反解** (Shepperd 分支在 tr→−1 处分母趋 0, float 下出 NaN)。
   既然已有 q 和 Δq, 直接 `q⊗Δq` 复合; 矩阵只用来算平移 `t' = t + R(q)·J_l(φ)ρ`。
3. **仿真复位瞬态会写进训练集**: 实测复位后单步 0.21 m / 32° (物理冲击), 不是任务动作。
   训练与评测**都要先丢 20 步**; 不丢时模型学"复位冲击", 留出评测也是瞬态主导。
4. **夹具/环境变量泄露**: provider 用 `SE3_POSE_FIXTURE` 环境变量时, 同进程后面的用例会
   默默沿用旧夹具 ⇒ 位姿与预测对不上, 残差虚高到 **0.9 m**(踩过)。多个用例就**显式传 pose_path**。

## 分量序 (最贵的约定)
`lie_intent.se3_exp/se3_log` 是 **[ω; v]** (旋转在前); 方案/控制律几乎都是 **[ρ; ω]** (平移在前)。
本模块对外 `XI_ORDER="rho_phi"`, 换算出入口只有 `xi_rho_phi_to_repo()/xi_repo_to_rho_phi()` 两个。
落笔前量一次: 纯平移 x=0.5 ⇒ `[0.5,0,0, 0,0,0]`; 纯绕 z 30° ⇒ `[0,0,0, 0,0,0.5236]`。

## 群指数 vs 解耦近似 (方案伪代码写的是后者)
方案 step4 写 `p += ρ, q ⊗= Δq` — 那是解耦近似; 严格群是 `t' = t + R·J_l(φ)ρ` (平移被旋转耦合)。
两种都给, `mode="group"` 为默认。实测同 ξ 下差: 小增量 6e-4 m vs 大增量 5.5e-2 m ⇒ 耦合项真的在起作用。
汇报时必须说清用的是哪种, 不然"预测准"没有共同口径。

## 真值陈旧守卫 (不能省)
预测头每周期读真机位姿 (`zmax_data/rokae_sdk/tcp_out/latest.json`)。位姿停更时**必须拒绝**
(`ok=False` + 写明 age), 否则就是拿旧位姿编 7 个数。实测: 机器人下电后该文件 950s 不刷新,
引擎里就应显示"拒绝预测", 而不是继续吐数。

## 验收数字 (2026-11-05 实测, 4060)
| 项 | 值 |
|---|---|
| exp/log 往返 (‖φ‖<π) | 4.7e-14 |
| ‖φ‖>π 绕圈后位姿一致 | 4.7e-12 |
| 四元数 1e4 步 (累计 745° ) 模长漂移 | 1.1e-16 |
| 测地线左不变性 / q vs −q | 1.1e-16 / 2.8e-17 |
| torch ↔ numpy 群更新 | 9.9e-10 |
| 留出种子 1 步预测 | **1.90° / 10.24mm** vs 不动基线 2.16° / 13.06mm |

诚实边界: 训练域=**仿真 AR 工位** (obs→PCA 潜表示, 而 obs 含 tcp_p/tcp_R ⇒ 学的是动力学不是视觉识别);
实机部署必须带 `domain` 字段; 训练步长 20ms vs 实机周期 100ms ⇒ ξ 幅值要按 dt 折算后才可用于下发。
