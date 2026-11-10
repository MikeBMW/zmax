#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""geodesic_inject.py — L4 几何量 → L3 动作的各向异性黎曼自然梯度注入

背景
----
L4 流形层输出的是几何量（势能 Φ、性能代价 V_p、接触进度、约束轴），
L3 动作层输出的是名义位移 ξ_d ∈ R³。过去的接法是「把 l4_cond 拼进网络输入端」，
但该通道在 ckpt 里没训练过（`action_head.ensure_l4_cond` 懒创建、scale=0.02 随机投影），
喂进去只等于给动作加噪声，所以一直标 `l4_cond_injected=false`。

本模块**不依赖训练**，用解析几何把 L4 的量注入 L3：

    装配容差是各向异性的 ——
    沿插入轴（孔轴 n）容差大（可推进、可回转），
    径向（垂直于 n 的平面）容差小（偏一点就刮擦或卡死）。

    把这件事写成度规：

        M = σ_t² · P_t + σ_n² · P_n ,   P_n = n nᵀ ,  P_t = I − n nᵀ

    σ_t ≪ σ_n  ⇒  M⁻¹ 在径向放大、轴向抑制。

    修正量取黎曼自然梯度（度规梯度流），保证在 M 的意义下是最速下降：

        Δξ = −α · M⁻¹ ∇V_p ,      α = α₀ · η · exp(−V_p / V₀)

    其中 η 是性能流形置信度（`ssmani_p.eta`），V_p 是装配代价
    （`V_p = ½ δᵀ W δ`，δ = 模块头 − 孔底）。

为什么它对
----------
1. **Lyapunov**：沿该方向 ξ̇ = Δξ 有
       dV/dt = ∇Vᵀ Δξ = −α ∇Vᵀ M⁻¹ ∇V ≤ 0
   （M 正定 ⇒ M⁻¹ 正定），即装配代价单调不增；α→0 时自动退化为原动作。
2. **各向异性有物理依据**：σ_t / σ_n 直接由孔轴公差与推进行程给出，不是调参玄学。
3. **可解释**：Δξ 可分解成「径向纠偏」+「轴向推进」两个分量，各自有量纲、可画、可验收。
4. **可关**：cfg.enabled=False 或几何量缺失时原样返回并标 injected=false —— 不造数。

契约
----
纯函数，不读写文件、不 import 中间件；输入输出都是 numpy / list。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# ── 默认参数（可由画布主参数覆盖）────────────────────────────────────────
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "sigma_t_mm": 0.30,     # 径向容差（孔与模块的单边间隙量级）
    "sigma_n_mm": 6.00,     # 轴向容差（推进行程量级）
    "alpha0": 0.85,         # 基准步长系数（乘在名义步长上）
    "max_ratio": 0.60,      # 单拍修正上限 ≤ 名义步长的 60%
    "cap_min_mm": 0.30,     # 但至少允许修 0.3mm/拍（对位阶段名义步长常只有 0.05mm，
                            #   只按比例限幅会把纠偏压成 0，实测 12 拍才收敛 40%）
    "eps_mm": 0.02,         # 名义步长趋零时的下限，避免除零
    "V0": 10.0,             # 代价衰减尺度（mm²；δ≈4.5mm 横向时 gate 衰减 1/e）
    "eta_floor": 0.05,      # 置信度下限（防止 eta=0 时完全不动或完全乱动）
}


def _unit(v) -> np.ndarray | None:
    a = np.asarray(v, dtype=float).reshape(-1)
    if a.size < 3:
        return None
    a = a[:3]
    nrm = float(np.linalg.norm(a))
    if not np.isfinite(nrm) or nrm < 1e-9:
        return None
    return a / nrm


def anisotropic_metric(axis, sigma_t: float, sigma_n: float) -> np.ndarray | None:
    """M = σ_t² P_t + σ_n² P_n ，返回 3×3 对称正定阵。"""
    n = _unit(axis)
    if n is None or sigma_t <= 0 or sigma_n <= 0:
        return None
    Pn = np.outer(n, n)
    Pt = np.eye(3) - Pn
    return (sigma_t ** 2) * Pt + (sigma_n ** 2) * Pn


def split_components(delta, axis) -> dict[str, float]:
    """把修正量分解为 (径向, 轴向)，单位与输入一致。"""
    n = _unit(axis)
    d = np.asarray(delta, dtype=float).reshape(-1)[:3]
    if n is None:
        return {"radial": float(np.linalg.norm(d)), "axial": 0.0}
    axial = float(np.dot(d, n))
    radial = float(np.linalg.norm(d - axial * n))
    return {"radial": radial, "axial": axial}


def correct(nominal, grad_V, axis, *, eta: float | None = None,
            V_p: float | None = None, cfg: dict | None = None) -> tuple[list[float], dict]:
    """对名义动作做一次各向异性自然梯度修正。

    参数
    ----
    nominal : 长度 ≥3 的名义动作（[x,y,z] 或 [x,y,z,grip]），单位 mm / 归一化夹爪
    grad_V  : ∇V_p（3 维空间梯度；来自性能流形 `grad`）
    axis    : 约束轴 / 插入轴（`ssmani_c.axis`，无真值时可传 [0,0,1]）
    eta     : 性能流形置信度 ∈ [0,1]
    V_p     : 当前装配代价（用于门控 exp(-V/V0)）
    cfg     : 覆盖 DEFAULTS

    返回
    ----
    (u_star, info)
      u_star : 修正后的动作（与 nominal 同长度）
      info   : 注入明细（决定下游能否如实标注）
    """
    c = dict(DEFAULTS)
    if cfg:
        c.update({k: v for k, v in cfg.items() if v is not None})

    u = [float(x) for x in (nominal or [])]
    info: dict[str, Any] = {
        "injected": False, "reason": None, "mode": "anisotropic_natural_gradient",
        "delta": [0.0, 0.0, 0.0], "alpha": 0.0, "gate": 0.0,
        "radial": 0.0, "axial": 0.0, "metric": None,
    }
    if not c["enabled"]:
        info["reason"] = "开关关闭"
        return u, info
    if len(u) < 3 or not np.all(np.isfinite(u[:3])):
        info["reason"] = "名义动作缺失"
        return u, info

    g = np.asarray(grad_V if grad_V is not None else [], dtype=float).reshape(-1)
    if g.size < 3 or not np.all(np.isfinite(g[:3])):
        info["reason"] = "无 ∇V_p 真值（性能流形未出数）"
        return u, info
    g = g[:3]

    M = anisotropic_metric(axis, c["sigma_t_mm"], c["sigma_n_mm"])
    if M is None:
        info["reason"] = "约束轴无效（无法构造度规）"
        return u, info

    # ① 黎曼自然梯度： Δ = − M⁻¹ ∇V
    try:
        d = -np.linalg.solve(M, g)
    except np.linalg.LinAlgError:
        info["reason"] = "度规奇异"
        return u, info
    if not np.all(np.isfinite(d)):
        info["reason"] = "梯度非有限"
        return u, info

    # ② 置信度门控：eta 越低越不敢动；代价越大步长越小
    e = float(eta) if isinstance(eta, (int, float)) else 1.0
    e = min(max(e, c["eta_floor"]), 1.0)
    v = float(V_p) if isinstance(V_p, (int, float)) and V_p >= 0 else 0.0
    gate = e * math.exp(-v / max(c["V0"], 1e-9))

    # ③ 步长：以名义步长为尺度，硬限幅 ≤ max_ratio
    step = float(np.linalg.norm(u[:3]))
    if step < 1e-9:
        info["reason"] = "名义步长≈0（无需修正）"
        return u, info
    dn = float(np.linalg.norm(d))
    if dn < 1e-12:
        info["reason"] = "∇V_p≈0（已在极小值）"
        return u, info
    unit_d = d / dn
    alpha = c["alpha0"] * gate
    delta = unit_d * (alpha * step)
    cap = max(c["max_ratio"] * step, c["cap_min_mm"]) + c["eps_mm"]
    # 🔴 还不得超过「当前偏差本身」：δ = W⁻¹∇V ⇒ 一拍最多走到零点，天然不过冲。
    #    实测反例：1.0mm 偏差、cap 固定 0.32mm ⇒ 第 4 拍越过零点来回振荡。
    try:
        d_dev = np.linalg.solve(W_OF(g), g)          # W⁻¹ ∇V = δ
        cap = min(cap, float(np.linalg.norm(d_dev)) * 0.95 + c["eps_mm"])
    except Exception:                                 # noqa: BLE001
        pass
    if float(np.linalg.norm(delta)) > cap:
        delta = delta / float(np.linalg.norm(delta)) * cap

    u_star = list(u)
    for i in range(3):
        u_star[i] = round(u[i] + float(delta[i]), 6)

    comp = split_components(delta, axis)
    info.update({
        "injected": True, "reason": "ok",
        "delta": [round(float(x), 6) for x in delta],
        "alpha": round(alpha, 6), "gate": round(gate, 6),
        "radial": round(comp["radial"], 6), "axial": round(comp["axial"], 6),
        "metric": {"sigma_t_mm": c["sigma_t_mm"], "sigma_n_mm": c["sigma_n_mm"],
                   "ratio_t_over_n": round(c["sigma_t_mm"] / c["sigma_n_mm"], 4)},
        "V_p": (round(v, 6) if isinstance(V_p, (int, float)) else None),
        "eta": (round(e, 6) if isinstance(eta, (int, float)) else None),
    })
    return u_star, info


def W_OF(grad_V) -> np.ndarray:
    """∇V = W δ 中的 W。（与 PerformanceManifold 同源：轴向 0.4、横向 1.0）"""
    return np.diag([0.4, 1.0, 1.0])


def lyapunov_check(grad_V, delta, M) -> float:
    """检验 dV/dt = ∇VᵀΔξ ≤ 0 是否成立；返回归一化后的值（≤0 为合格）。"""
    g = np.asarray(grad_V, dtype=float).reshape(-1)[:3]
    d = np.asarray(delta, dtype=float).reshape(-1)[:3]
    Mm = np.asarray(M, dtype=float)
    denom = float(np.linalg.norm(g) * np.linalg.norm(d)) or 1.0
    return float(np.dot(g, d) / denom)
