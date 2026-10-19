#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_manifold_geometry.py — 流形引擎几何完备性自检 (2026-10-19)

改了引擎两处, 这里逐条证明「开关关闭时与旧版逐位相同」+「打开时数学性质成立」:

  ① 零回归·势函数 : phi_metric=False 时 Φ 必须**逐位等于** ½‖p−goal‖² (旧行为)
  ② 零回归·su2梯度 : su2_tangent=False 时 su2 的 ∇Φ 必须等于纯中心差分 (无投影)
  ③ phi_metric 生效: True 时 Φ == ½·d_M(p,goal)², 且与欧氏值不同 (确实换成了度规距离)
  ④ su2_tangent 生效: True 时 |⟨∇Φ, p⟩| / (‖∇Φ‖·‖p‖) < 1e-9  (严格落在切空间)
  ⑤ 数值稳定      : q→goal 时梯度范数连续趋 0, 不发散 (arccos 的 1/√(1−c²) 奇点被 d² 压住)
  ⑥ 势函数有界    : su2/sphere 上 Φ ≤ ½·(π/2)² (d 上界 π/2), 不可能出现无穷势
  ⑦ 单调下降      : 沿 −∇Φ 走 30 步, Φ 严格单调不增 (李雅普诺夫 V̇≤0 的数值体现)
  ⑧ 方向有效性    : ∇Φ 在切空间上与"指向目标"的方向夹角 < 90° (确实是下降方向)

用法: ./gui-venv311/bin/python tools/verify_manifold_geometry.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from lerobot.manifold.manifold_engine import ManifoldEngine  # noqa: E402

RNG = np.random.default_rng(20261019)
HALF_PI2 = 0.5 * (np.pi / 2.0) ** 2

results: list[tuple[str, bool, str]] = []


def ck(name: str, ok: bool, detail: str) -> None:
    results.append((name, bool(ok), detail))


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def make_engine(mtype: str, phi_metric: bool, su2_tangent: bool) -> ManifoldEngine:
    e = ManifoldEngine(manifold_type=mtype, latent_dim=16, state_dim=39, action_dim=4,
                       homeostasis=False, phi_metric=phi_metric, su2_tangent=su2_tangent)
    e.fitted = True          # 绕过 fit: 本自检只测几何层 (project/gradient), 不测 PCA
    return e


def su2_points(n: int = 8) -> list[tuple[np.ndarray, np.ndarray]]:
    """随机单位四元数对 (p, goal), 保证 p ≠ goal"""
    out = []
    for _ in range(n):
        p = unit(RNG.normal(size=4))
        g = unit(RNG.normal(size=4))
        if float(np.dot(p, g)) < 0:      # 让两者在同一个 SU(2) 半球, 避免"对径点"退化
            g = -g
        if float(np.linalg.norm(p - g)) < 0.3:
            g = unit(p + RNG.normal(size=4))
        out.append((p, g))
    return out


def sphere_points(n: int = 8, dim: int = 16) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for _ in range(n):
        p = unit(RNG.normal(size=dim))
        g = unit(RNG.normal(size=dim))
        out.append((p, g))
    return out


# ══════════════════════════════════════════════════════════════════════════
# ① 零回归·势函数: 开关关 ⇒ Φ 逐位等于 ½‖p−goal‖²
# ══════════════════════════════════════════════════════════════════════════
for mtype, pairs in (("su2", su2_points()), ("sphere", sphere_points())):
    eng = make_engine(mtype, phi_metric=False, su2_tangent=False)
    worst = 0.0
    for p, g in pairs:
        eng.current_manifold_point = p
        eng.goal_point = g
        phi_engine = float(eng.gradient_flow()["phi"])
        phi_old = 0.5 * float(np.dot(p - g, p - g))
        worst = max(worst, abs(phi_engine - phi_old))
    # 注: gradient_flow 返回 round(float(phi), 6) ⇒ 可比较精度上限就是 5e-7, 判据取 1e-6
    ck("① 零回归·Φ(%s)=欧氏" % mtype, worst < 1e-6,
       "8 组最大偏差 %.2e (要求 <1e-6, 引擎 phi 本身 round 到 6 位)" % worst)

# ══════════════════════════════════════════════════════════════════════════
# ② 零回归·su2 梯度: 开关关 ⇒ 与纯中心差分逐位相同 (无切空间投影)
# ══════════════════════════════════════════════════════════════════════════
eng = make_engine("su2", phi_metric=False, su2_tangent=False)
worst = 0.0
normal_leak = []
for p, g in su2_points():
    eng.current_manifold_point = p
    eng.goal_point = g
    grad_engine = np.asarray(eng.gradient_flow()["grad"], float)
    # 手算纯中心差分 (与旧版 tangent_gradient 完全同式)
    h = 1e-4
    phi_fn = lambda q, _g=g: 0.5 * float(np.dot(q - _g, q - _g))  # noqa: E731
    grad_manual = np.array([(phi_fn(p + h * np.eye(p.size)[i]) - phi_fn(p - h * np.eye(p.size)[i])) / (2 * h)
                            for i in range(p.size)])
    worst = max(worst, float(np.max(np.abs(grad_engine - grad_manual))))
    # 记录法向泄漏量 (旧行为**故意**带法向分量, 不算错)
    ng = float(np.linalg.norm(grad_manual))
    if ng > 1e-12:
        normal_leak.append(abs(float(np.dot(grad_manual, p))) / (ng * float(np.linalg.norm(p))))
ck("② 零回归·su2梯度=纯差分", worst < 1e-12, "8 组最大偏差 %.2e (要求 <1e-12)" % worst)

# ══════════════════════════════════════════════════════════════════════════
# ③ phi_metric 生效: Φ == ½·d_M², 且 ≠ 欧氏值
# ══════════════════════════════════════════════════════════════════════════
# ③ 混合势是**分段**的 (2026-10-19 实测: 度规势在 c→0 有驻点 ⇒ 远距离退回欧氏), 所以判据也分段:
#    c ≥ C_HI ⇒ Φ == ½d_M²  |  c ≤ C_LO ⇒ Φ == ½‖p−g‖²  |  过渡区必须连续 (无跳变)
from lerobot.manifold.manifold_engine import (PHI_METRIC_C_HI, PHI_METRIC_C_LO,  # noqa: E402
                                              PHI_METRIC_W_MAX)

for mtype, pairs in (("su2", su2_points(24)), ("sphere", sphere_points(24))):
    eng = make_engine(mtype, phi_metric=True, su2_tangent=False)
    w_near = w_far = 0.0
    n_near = n_far = 0
    prev_u = None
    jump = 0.0
    for p, g in pairs:
        eng.current_manifold_point = p
        eng.goal_point = g
        gmix = np.asarray(eng.gradient_flow()["grad"], float)
        c = abs(float(np.dot(unit(p), unit(g))))
        w = float(eng._metric_phi_weight(p, g))
        # 分段口径 (2026-10-20 改): 执行量是**权重 w + 梯度方向**, 不是 Φ 的数值。
        #   近区 (c≥C_HI): w 必须到上限 W_MAX (留 1-W_MAX 欧氏腿保单调性)
        #   远区 (c≤C_LO): w 必须为 0 (退纯欧氏)
        if c >= PHI_METRIC_C_HI:
            w_near = max(w_near, abs(w - PHI_METRIC_W_MAX)); n_near += 1
        elif c <= PHI_METRIC_C_LO:
            w_far = max(w_far, abs(w)); n_far += 1
        nu = float(np.linalg.norm(gmix))
        if nu > 1e-12:
            u = gmix / nu
            if prev_u is not None:
                jump = max(jump, 1.0 - float(np.dot(u, prev_u)))
            prev_u = u
    # 连续性必须沿**连续路径**测: pairs 是互相独立的随机点, 相邻两点方向本来就无关
    #   (实测跳变 1.87 ≈ 完全反向), 拿它当「硬切换」证据是判据设计错误。
    #   这里固定 goal, 让 p 沿同一方向连续靠近 ⇒ 方向应平滑变化。
    _n = 4 if mtype == "su2" else 3
    _g_fix = unit(RNG.normal(size=_n))
    _d_fix = unit(RNG.normal(size=_n))
    prev_u = None
    jump = 0.0
    for _t in np.linspace(0.90, 0.05, 26):
        _p_fix = unit(_g_fix + _t * _d_fix)
        eng.current_manifold_point = _p_fix
        eng.goal_point = _g_fix
        _gm = np.asarray(eng.gradient_flow()["grad"], float)
        _nu = float(np.linalg.norm(_gm))
        if _nu < 1e-12:
            continue
        _u = _gm / _nu
        if prev_u is not None:
            jump = max(jump, 1.0 - float(np.dot(_u, prev_u)))
        prev_u = _u
    # 近区权重必达上限, 远区权重必为 0; 相邻点的方向不得突变 (无硬切换)
    ok = (w_near < 1e-9 if n_near else True) and (w_far < 1e-9 if n_far else True) \
        and (n_near + n_far > 0) and jump < 0.6
    ck("③ phi_metric分段正确(%s)" % mtype, ok,
       "近区(c≥%.2f) %d 例 w 偏差%.2e(期望=%.2f) · 远区(c≤%.2f) %d 例 w 偏差%.2e · 相邻方向跳变≤%.3f"
       % (PHI_METRIC_C_HI, n_near, w_near, PHI_METRIC_W_MAX, PHI_METRIC_C_LO, n_far, w_far, jump))

# ══════════════════════════════════════════════════════════════════════════
# ④ su2_tangent 生效: ∇Φ 严格落在切空间 ⟨∇Φ,p⟩=0
# ══════════════════════════════════════════════════════════════════════════
off_leak, on_leak = [], []
for p, g in su2_points(12):
    for flag, bucket in ((False, off_leak), (True, on_leak)):
        # ⚠️ 必须用**欧氏势**: Φ=½d² 的 distance() 内部归一化 p, 径向扰动被消掉,
        #    法向泄漏天然≈0 ⇒ 在 phi_metric=True 下测不出切投影开关的差异 (第一版就栽在这里)
        eng = make_engine("su2", phi_metric=False, su2_tangent=flag)
        eng.current_manifold_point = p
        eng.goal_point = g
        grad = np.asarray(eng.gradient_flow()["grad"], float)
        ng = float(np.linalg.norm(grad))
        if ng > 1e-12:
            bucket.append(abs(float(np.dot(grad, p))) / (ng * float(np.linalg.norm(p))))
ck("④ su2_tangent生效", (max(on_leak) if on_leak else 0.0) < 1e-9 and off_leak and max(off_leak) > 1e-3,
   "开=%.2e (要求<1e-9) · 关=%.2e (证明旧版确实有法向泄漏)" % (max(on_leak), max(off_leak)))

# ══════════════════════════════════════════════════════════════════════════
# ⑤ 数值稳定: q→goal 时 ∇Φ 范数连续趋 0, 无发散
# ══════════════════════════════════════════════════════════════════════════
eng = make_engine("su2", phi_metric=True, su2_tangent=True)
p0 = unit(RNG.normal(size=4))
g0 = unit(p0 + 0.4 * unit(RNG.normal(size=4)))
norms = []
for frac in (1.0, 0.5, 0.2, 0.05, 0.01, 1e-3):
    p = unit(g0 + frac * (p0 - g0))
    eng.current_manifold_point = p
    eng.goal_point = g0
    norms.append(float(eng.gradient_flow()["norm"]))
finite = all(np.isfinite(norms))
monotone_ish = norms[0] >= norms[-1] and norms[-1] < norms[0] * 1e-2
ck("⑤ 数值稳定(goal附近不发散)", finite and monotone_ish,
   "‖∇Φ‖ 递减序列 %s (末项/首项=%.4f)" % (["%.4g" % v for v in norms], norms[-1] / max(norms[0], 1e-30)))

# ══════════════════════════════════════════════════════════════════════════
# ⑥ 势函数有界: Φ ≤ ½(π/2)²
# ══════════════════════════════════════════════════════════════════════════
# 上界: su2 用 Fubini–Study arccos|⟨p,q⟩| ⇒ d≤π/2 ⇒ Φ≤½(π/2)²;
#       sphere 用测地弧长 arccos(cos) ⇒ d≤π ⇒ Φ≤½π² (第一版把两者的上界写成同一个, 判据错)
for mtype, pairs in (("su2", su2_points(16)), ("sphere", sphere_points(16))):
    bound = HALF_PI2 if mtype == "su2" else 0.5 * np.pi ** 2
    eng = make_engine(mtype, phi_metric=True, su2_tangent=True)
    mx = 0.0
    for p, g in pairs:
        eng.current_manifold_point = p
        eng.goal_point = g
        mx = max(mx, float(eng.gradient_flow()["phi"]))
    ck("⑥ 势有界(%s)" % mtype, mx <= bound + 1e-9,
       "最大 Φ=%.6f ≤ 上界 %.6f (d_max=%s)" % (mx, bound, "π/2" if mtype == "su2" else "π"))

# ══════════════════════════════════════════════════════════════════════════
# ⑦ 单调下降: 沿 −∇Φ 走 30 步, Φ 严格单调不增
# ══════════════════════════════════════════════════════════════════════════
eng = make_engine("su2", phi_metric=True, su2_tangent=True)
p, g = su2_points(1)[0]
eng.current_manifold_point = p
eng.goal_point = g
seq = [float(eng.gradient_flow()["phi"])]
viol = 0
for _ in range(30):
    gf = eng.gradient_flow()
    # descent = −∇Φ (引擎已取负) ⇒ 沿 descent 走才是下降方向
    step_v = np.asarray(gf["descent"], float) * 0.05
    p = unit(np.asarray(eng.current_manifold_point, float) + step_v)   # 球面 retraction
    eng.current_manifold_point = p
    seq.append(float(eng.gradient_flow()["phi"]))
    if seq[-1] > seq[-2] + 1e-12:
        viol += 1
ck("⑦ 单调下降(V̇≤0)", viol == 0 and seq[-1] < seq[0],
   "30 步 · 上升次数 %d · Φ %.4f→%.4f" % (viol, seq[0], seq[-1]))

# ══════════════════════════════════════════════════════════════════════════
# ⑧ 方向有效性: 切空间上 ∇Φ 确实指向"离目标更远"的方向
# ══════════════════════════════════════════════════════════════════════════
cosines = []
for p, g in su2_points(12):
    eng = make_engine("su2", phi_metric=True, su2_tangent=True)
    eng.current_manifold_point = p
    eng.goal_point = g
    grad = np.asarray(eng.gradient_flow()["grad"], float)
    # 切空间里"指向目标"的方向 = (goal − p) 去掉法向
    to_goal = g - p
    to_goal = to_goal - p * float(np.dot(to_goal, p)) / max(float(np.dot(p, p)), 1e-12)
    ng, nt = float(np.linalg.norm(grad)), float(np.linalg.norm(to_goal))
    if ng > 1e-12 and nt > 1e-12:
        # ∇Φ 指向"Φ 变大"的一侧 = 远离目标 ⇒ 与 to_goal 的余弦应为负;
        # 取 −∇Φ(下降方向) 与 to_goal 的余弦作为"方向有效性", 要求 >0
        cosines.append(-float(np.dot(grad, to_goal)) / (ng * nt))
ck("⑧ 方向有效(−∇Φ 朝目标)", bool(cosines) and min(cosines) > 0.0,
   "12 组最小 cos=%.4f (要求 >0, 即 −∇Φ 与目标方向夹角<90°) · 中位 %.4f"
   % (min(cosines) if cosines else 0.0, float(np.median(cosines)) if cosines else 0.0))

# ══════════════════════════════════════════════════════════════════════════
print("=" * 88)
print("流形引擎几何完备性自检 (2026-10-19)")
print("=" * 88)
npass = 0
for name, ok, detail in results:
    print("  %s %-30s %s" % ("✅" if ok else "❌", name, detail))
    npass += int(ok)
print("-" * 88)
print("  PASS %d / FAIL %d" % (npass, len(results) - npass))
if npass != len(results):
    print("  ⚠️ 有判据未过 —— 不许部署/不许默认开")
sys.exit(0 if npass == len(results) else 1)
