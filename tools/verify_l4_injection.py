#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_l4_injection.py — L4 几何注入的三项实测（离线，不动机械臂）

背景: 画布上 `l4_cond_injected=false` —— L4 流形的几何量过去没进入 L3 动作。
      本脚本验证新算法（各向异性黎曼自然梯度注入）是否真的成立。

三项实验
--------
A. 受控扰动收敛：给定初始横向偏差 1.0 / 0.5 / 0.2 mm，
   每拍按 Δξ = −α M⁻¹∇V 修正，看偏差是否单调收敛、几拍进入 0.05mm。
   （受控数值实验：初值是设定值、动力学是模型，不是真机数据）

B. 各向异性生效：同一梯度下「径向修正量 / 轴向修正量」之比
   应 ≈ (σ_n/σ_t)² 量级，证明度规真的区分了两个方向。

C. AR 段表一致性：取 sim_insert 全部段（真实 a→b 位移），检查
   (a) 修正方向与 −∇V 余弦 ≥ 0.99；
   (b) 单拍修正永不超 max_ratio（限幅生效）；
   (c) Lyapunov ∇VᵀΔξ ≤ 0 成立率。

口径: 全部为模型内计算，不下发任何动作；真机仍需 8793 授权。
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.manifold.geodesic_inject import (  # noqa: E402
    anisotropic_metric, correct, lyapunov_check, split_components,
)

W = np.diag([0.4, 1.0, 1.0])       # 与 PerformanceManifold 同源
SIGMA = 4.0                        # mm
AXIS = np.array([1.0, 0.0, 0.0])   # 孔轴 +x


def Vp(d):
    return 0.5 * float(d @ W @ d)


def run_convergence(delta_perp_mm: float, max_iter: int = 12):
    """初始横向偏差 → 逐拍修正，返回每拍后的径向偏差序列（mm）。

    只跟踪**径向**偏差 δ⊥：轴向推进 ξ 不影响它，因此每拍径向变化完全来自修正量。
    （早前版本把轴向推进也累加进 δ，导致 |δ| 虚增 ⇒ cap 被撑大、符号翻转，已修）
    """
    d = np.array([0.0, delta_perp_mm, 0.0])
    traj = [float(np.linalg.norm(d - np.dot(d, AXIS) * AXIS))]
    xi = np.array([0.5, 0.0, 0.0])                 # 名义动作：恒定沿轴推进 0.5mm/拍
    for _ in range(max_iter):
        g = W @ d
        vp = Vp(d)
        eta = float(np.exp(-vp / SIGMA ** 2))
        _, info = correct(list(xi) + [0.0], g, AXIS, eta=eta, V_p=vp)
        d = d + np.array(info["delta"], float)     # 只加修正量（xi 不影响径向）
        d[0] = 0.0                                  # 轴向不参与偏差跟踪
        traj.append(float(np.linalg.norm(d - np.dot(d, AXIS) * AXIS)))
        if traj[-1] < 0.02:
            break
    return traj


def experiment_A():
    print("=" * 68)
    print("A. 受控扰动收敛（横向偏差 → 逐拍修正，目标 < 0.05mm）")
    print("%-10s %-14s %-12s %-8s" % ("初始δ⊥", "进入<0.05mm", "末值(mm)", "单调?"))
    out = {}
    for d0 in (1.0, 0.5, 0.2):
        t = run_convergence(d0)
        mono = all(t[i + 1] <= t[i] + 1e-9 for i in range(len(t) - 1))
        hit = next((i for i, v in enumerate(t) if v < 0.05), None)
        print("%-10s %-14s %-12.4f %-8s" % (
            "%.2f mm" % d0,
            ("第 %d 拍" % hit) if hit is not None else "未达到", t[-1],
            "是" if mono else "否"))
        out["%.1f" % d0] = {"traj_mm": [round(x, 4) for x in t],
                            "monotonic": bool(mono), "iters_to_0.05mm": hit}
    return out


def experiment_B():
    print("\n" + "=" * 68)
    print("B. 各向异性生效（同一梯度幅值下比较径向 / 轴向修正量）")
    print("%-12s %-12s %-12s %-14s" % ("梯度方向", "径向|Δ|", "轴向|Δ|", "径向/轴向"))
    out = {}
    for name, g in [("纯径向", np.array([0.0, 1.0, 0.0])),
                    ("纯轴向", np.array([1.0, 0.0, 0.0])),
                    ("45°混合", np.array([0.7071, 0.7071, 0.0]))]:
        _, info = correct([5.0, 0.0, 0.0, 0.0], g, AXIS, eta=1.0, V_p=0.0)
        comp = split_components(info["delta"], AXIS)
        r, a = comp["radial"], abs(comp["axial"])
        ratio = (r / a) if a > 1e-9 else None
        print("%-12s %-12.5f %-12.5f %-14s" % (
            name, r, a, ("%.1f×" % ratio) if ratio is not None else "纯径向"))
        out[name] = {"radial": round(r, 6), "axial": round(a, 6),
                     "ratio": (round(ratio, 2) if ratio is not None else None)}
    M = anisotropic_metric(AXIS, 0.30, 6.00)
    ev = sorted(np.linalg.eigvalsh(M))
    print("   度规特征值 (radial, radial, axial) = (%.4f, %.4f, %.4f)" % tuple(ev))
    print("   理论放大倍数 (σ_n/σ_t)² = %.0f×  · 实测条件数 %.0f×" %
          ((6.0 / 0.30) ** 2, ev[-1] / ev[0]))
    return out


def experiment_C():
    print("\n" + "=" * 68)
    print("C. AR 段表一致性（sim_insert 真实位移 + 受控径向扰动）")
    files = sorted(glob.glob(os.path.join(
        ROOT, "zmax_data", "runtime", "traj", "plan_550c", "sim_insert-*.json")))
    if not files:
        print("   无段表文件，跳过")
        return {}
    n_seg = 0
    cos_list, lyap_list, cap_viol = [], [], 0
    for f in files:
        try:
            q = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        ab = np.asarray(q.get("abs_mm") or [], float)
        if ab.ndim != 2 or len(ab) < 2:
            continue
        for i in range(len(ab) - 1):
            xi = ab[i + 1] - ab[i]
            nrm = float(np.linalg.norm(xi))
            if nrm < 1e-6:
                continue
            n_seg += 1
            rng = np.random.default_rng(i)                 # 固定种子 ⇒ 可复现
            d = np.array([0.0, rng.normal(0, 0.20), rng.normal(0, 0.20)])
            g = W @ d
            vp = Vp(d)
            eta = float(np.exp(-vp / SIGMA ** 2))
            _, info = correct(list(xi) + [0.0], g, AXIS, eta=eta, V_p=vp)
            if not info["injected"]:
                continue
            dxi = np.array(info["delta"])
            gn = -g / max(np.linalg.norm(g), 1e-12)
            dn = dxi / max(np.linalg.norm(dxi), 1e-12)
            cos_list.append(float(np.dot(gn, dn)))
            lyap_list.append(lyapunov_check(g, dxi, anisotropic_metric(AXIS, 0.30, 6.00)))
            _cap = min(max(0.60 * nrm, 0.30) + 0.02,
                       float(np.linalg.norm(d)) * 0.95 + 0.02)
            if np.linalg.norm(dxi) > _cap + 1e-6:
                cap_viol += 1
    if not n_seg:
        print("   段表为空，跳过")
        return {}
    cos_arr, ly_arr = np.array(cos_list), np.array(lyap_list)
    print("   段数 %d   参与 %d" % (n_seg, len(cos_arr)))
    print("   ① 修正方向与 −∇V 余弦: 平均 %.4f  最小 %.4f" % (cos_arr.mean(), cos_arr.min()))
    print("   ② Lyapunov ∇VᵀΔξ ≤ 0 成立率: %.1f%%" % (100.0 * np.mean(ly_arr <= 1e-9)))
    print("   ③ 限幅越界次数: %d （应为 0）" % cap_viol)
    return {"n_seg": n_seg, "n_eval": len(cos_arr),
            "cos_mean": float(cos_arr.mean()), "cos_min": float(cos_arr.min()),
            "lyap_ok_pct": float(100.0 * np.mean(ly_arr <= 1e-9)),
            "cap_violations": int(cap_viol)}


def main():
    print("L4 几何注入验证 —— 各向异性黎曼自然梯度")
    print("算法: Δξ = −α M⁻¹∇V,  M = σ_t²P_t + σ_n²P_n,  α = α₀·η·exp(−V_p/V₀)")
    print("参数: σ_t=0.30mm σ_n=6.00mm α₀=0.85 V₀=10mm²  孔轴=+x\n")
    a = experiment_A()
    b = experiment_B()
    c = experiment_C()
    out = {
        "algo": "anisotropic_riemannian_natural_gradient",
        "formula": "dxi = -alpha * M^-1 * grad_V ; M = sigma_t^2*Pt + sigma_n^2*Pn ; alpha = alpha0*eta*exp(-Vp/V0)",
        "params": {"sigma_t_mm": 0.30, "sigma_n_mm": 6.00, "alpha0": 0.85, "V0_mm2": 10.0},
        "A_convergence": a, "B_anisotropy": b, "C_segment_consistency": c,
        "note": "全部为模型内计算，不下发动作；C 的横向扰动为受控注入(固定种子)",
    }
    p = os.path.join(ROOT, "zmax_data", "ss_live", "l4_injection_eval.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n明细已存: %s" % os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()
