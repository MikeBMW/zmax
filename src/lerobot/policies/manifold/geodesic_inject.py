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
    # ── 视触觉融合 (2026-11-11 老倪: 「纯视觉精度不足、必须引入触觉」) ──────────
    "tac_enable": True,     # 触觉梯度是否参与融合
    "tac_contact_c0": 0.35,  # 接触概率达到该值开始切换到触觉主导
    "tac_gamma": 2.0,       # 切换陡度 (越大切换越硬)
    "tac_w_max": 0.90,      # 触觉权重上限 (永远留一点视觉, 防止触觉退化时全盲)
    "force_max": 40.0,      # 力上限 (N) —— 与现场「插入力≤40N」一致
    "force_k": 6.0,         # 超限后置信度衰减陡度
    "force_abort_ratio": 1.5,  # 超限 1.5 倍 ⇒ 直接停机(不走修正)
    "contact_stiffness": 6.0,  # 接触刚度 K (N/mm) —— 力反解偏差必须除它, 见 correct() 步骤③
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


def _radial_part(v, axis) -> np.ndarray:
    """剔除轴向分量（径向量）。触觉力的轴向部分属于插深通道，不参与对准纠偏。"""
    a = np.asarray(v, dtype=float).reshape(-1)[:3]
    n = _unit(axis)
    if n is None:
        return a
    return a - float(np.dot(a, n)) * n


def anisotropic_metric(axis, sigma_t: float, sigma_n: float) -> np.ndarray | None:
    """M = σ_t² P_t + σ_n² P_n ，返回 3×3 对称正定阵。"""
    n = _unit(axis)
    if n is None or sigma_t <= 0 or sigma_n <= 0:
        return None
    Pn = np.outer(n, n)
    Pt = np.eye(3) - Pn
    return (sigma_t ** 2) * Pt + (sigma_n ** 2) * Pn


def tactile_to_gradient(F=None, contact=None, dir_xy=None, residual=None,
                        axis=None, cfg: dict | None = None) -> tuple[np.ndarray | None, dict]:
    """触觉/接触信息 → 势能梯度 ∇V_tac（3 维，单位与输入一致）。

    物理
    ----
    接触力是**排斥力**：孔壁把模块推离孔心，力的方向就是势能上升的方向，故

        ∇V_tac ∝ **+F_radial**

    ⚠️ 这一符号与直觉相反、也容易写错：直觉会写 ∇V ∝ −F（"力指低谷"），
       但用 Δξ = −M⁻¹∇V 时，−(−F) 会把模块**推出孔**。
       实测反例（2026-11-11 C2）：按 −F 写，0.4mm 偏差的修正量符号为负，朝远离孔方向走。
       正解：力 → 势能上升方向 → ∇V ∝ +F → Δξ = −M⁻¹F 指向孔心（力的反方向）。
    只取垂直孔轴的径向分量，轴向推进不据此修正。

    三档来源，优先级从高到低，且**输出里必须如实标 src**：

    ① `F`      真六维/三轴力(N)        → src="force"           ← 专利所描述的那一路
    ② `contact`+`dir_xy` 接触状态代理  → src="contact_proxy"   （无真力时的降级：接触概率×接触方向）
    ③ `residual` 闭环残差代理          → src="residual_proxy"  （执行后实测偏差，非开环视觉预测）
    都没有 → 返回 (None, {"src": None, "why": ...})，调用方据此不注入。

    🔴 为什么不用「peg−hole 方向」当代理：`gen_tactile.synth_tactile` 的 dir 就是
       (peg−hole)/d，与视觉梯度**同源同向**，用它等于把视觉算两遍，盲插区拿不到任何新信息。

    参数
    ----
    F        : 力向量(3 维) —— 有真力就传，最可信
    contact  : 接触概率 ∈[0,1]（`synth_tactile` t1 或 `ssinnov.contact_p`）
    dir_xy   : 接触方向(径向 2 维或 3 维)，仅在与 contact 同源时才用
    residual : 闭环残差(3 维)，来自 `ssinnov.residual`
    axis     : 约束轴，用于剔除轴向分量
    """
    c = dict(DEFAULTS)
    if cfg:
        c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    n = _unit(axis)
    out = {"src": None, "why": None, "grad": None, "contact": contact,
           "raw_norm": 0.0, "radial_norm": 0.0, "axial_norm": 0.0}

    def _proj_radial(v):
        return _radial_part(v, axis)

    g = None
    # ① 真力（最可信，专利主张的路径）
    if F is not None:
        f = np.asarray(F, dtype=float).reshape(-1)
        if f.size >= 3 and np.all(np.isfinite(f[:3])) and float(np.linalg.norm(f[:3])) > 1e-9:
            g = _proj_radial(f[:3])           # 力=排斥=势能上升方向 ⇒ ∇V ∝ +F
            out.update({"src": "force", "why": "六维/三轴力直接反投影（专利路径）"})
    # ② 接触状态代理
    if g is None and contact is not None and dir_xy is not None:
        try:
            cp = float(contact)
            d = np.asarray(dir_xy, dtype=float).reshape(-1)
            if d.size >= 2 and cp > 0 and np.all(np.isfinite(d)):
                d3 = np.zeros(3)
                d3[:min(3, d.size)] = d[:min(3, d.size)]
                g = _proj_radial(d3) * cp     # 同号: 接触方向即排斥方向
                out.update({"src": "contact_proxy",
                            "why": "接触概率×接触方向（无真力时的降级，非真实力）"})
        except Exception:                                              # noqa: BLE001
            g = None
    # ③ 闭环残差代理（执行后实测偏差，仍不是力）
    if g is None and residual is not None:
        try:
            rr = np.asarray(residual, dtype=float).reshape(-1)
            if rr.size >= 3 and np.all(np.isfinite(rr[:3])) and float(np.linalg.norm(rr[:3])) > 1e-12:
                g = _proj_radial(rr[:3])         # 残差本身即"偏离孔心"⇒ 与 ∇V 同向
                out.update({"src": "residual_proxy",
                            "why": "闭环残差反向（执行后实测偏差，非力传感器）"})
        except Exception:                                              # noqa: BLE001
            g = None

    if g is None:
        out["why"] = out["why"] or "无触觉/力/残差可用 ⇒ 不注入"
        return None, out

    gn = float(np.linalg.norm(g))
    if not np.isfinite(gn) or gn < 1e-12:
        out.update({"grad": None, "why": "触觉梯度为零 ⇒ 不注入"})
        return None, out
    rad = _proj_radial(g)
    out.update({
        "grad": [round(float(x), 6) for x in np.asarray(g, dtype=float).reshape(-1)[:3]],
        "raw_norm": round(gn, 6),
        "radial_norm": round(float(np.linalg.norm(rad)), 6),
        "axial_norm": round(abs(float(np.dot(g, n))) if n is not None else 0.0, 6),
    })
    return g, out


def fuse_gradient(g_vis, g_tac, contact=None, cfg: dict | None = None) -> tuple[np.ndarray | None, dict]:
    """视觉梯度 ⊕ 触觉梯度 融合，权重随接触程度切换。

        w_tac = tac_w_max · clip(contact / c0, 0, 1)^γ
        w_vis = 1 − w_tac
        ∇V    = w_vis·ĝ_vis + w_tac·ĝ_tac      （各自归一化后加权，避免量纲差吃掉一方）

    语义：没接触时信视觉（远场它准）；一旦接触，视觉在盲插区不可信，权重迅速交给触觉。
    归一化再加权是关键 —— 力(N)与视觉代价梯度量纲差几个数量级，直接相加等于只信大的那个。
    """
    c = dict(DEFAULTS)
    if cfg:
        c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    info = {"mode": "vis_only", "w_vis": 1.0, "w_tac": 0.0, "contact": contact}
    gv = None
    if g_vis is not None:
        a = np.asarray(g_vis, dtype=float).reshape(-1)[:3]
        if a.size == 3 and np.all(np.isfinite(a)) and float(np.linalg.norm(a)) > 1e-12:
            gv = a
    gt = None
    if g_tac is not None:
        b = np.asarray(g_tac, dtype=float).reshape(-1)[:3]
        if b.size == 3 and np.all(np.isfinite(b)) and float(np.linalg.norm(b)) > 1e-12:
            gt = b
    if gv is None and gt is None:
        info["reason"] = "两路梯度都缺"
        return None, info
    if gt is None or not c.get("tac_enable", True):
        info["reason"] = ("触觉关闭" if gt is None and gv is not None else None)
        return gv, info
    if gv is None:
        info.update({"mode": "tac_only", "w_vis": 0.0, "w_tac": 1.0})
        return gt, info

    try:
        cp = float(contact) if contact is not None else 0.0
    except Exception:                                                  # noqa: BLE001
        cp = 0.0
    c0 = max(1e-6, float(c["tac_contact_c0"]))
    w = float(c["tac_w_max"]) * min(1.0, max(0.0, cp / c0)) ** float(c["tac_gamma"])
    w = min(1.0, max(0.0, w))
    u_v = gv / float(np.linalg.norm(gv))
    u_t = gt / float(np.linalg.norm(gt))
    # 方向冲突检测: 余弦 < 0 ⇒ 两路互相矛盾, 以接触深浅决定信任谁, 但如实报出来
    cos = float(np.dot(u_v, u_t))
    g = (1.0 - w) * u_v + w * u_t
    gn = float(np.linalg.norm(g))
    if gn < 1e-9:
        info.update({"mode": "conflict", "w_vis": 1.0 - w, "w_tac": w, "cos": round(cos, 6),
                     "reason": "两路梯度方向相反且权重抵消 ⇒ 退回视觉"})
        return gv, info
    # 幅度按权重插值, 方向取融合方向(已归一化)
    mag = (1.0 - w) * float(np.linalg.norm(gv)) + w * float(np.linalg.norm(gt))
    info.update({"mode": ("tac_dominant" if w >= 0.5 else "vis_dominant"),
                 "w_vis": round(1.0 - w, 6), "w_tac": round(w, 6), "cos_vis_tac": round(cos, 6),
                 "mag": round(mag, 6)})
    return (g / gn) * mag, info


def force_guard(force_norm=None, cfg: dict | None = None) -> dict:
    """力阈值保护：超过 F_max 让置信度骤降；超 1.5 倍直接停机。

    返回 {"scale": eta 乘子, "abort": bool, "why": str}
    没有力数据时 scale=1、abort=False（不改变既有行为）。
    """
    c = dict(DEFAULTS)
    if cfg:
        c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    out = {"scale": 1.0, "abort": False, "why": None, "F": force_norm,
           "F_max": c["force_max"]}
    if force_norm is None:
        out["why"] = "无力数据(不介入)"
        return out
    try:
        F = abs(float(force_norm))
    except Exception:                                                  # noqa: BLE001
        out["why"] = "力数据非法"
        return out
    if c["force_max"] <= 0:
        return out
    ratio = F / float(c["force_max"])
    if ratio > float(c["force_abort_ratio"]):
        out.update({"scale": 0.0, "abort": True,
                    "why": "力 %.1fN 超上限 %.0fN 的 %.1f 倍 ⇒ 停机" % (F, c["force_max"], ratio)})
        return out
    if ratio > 1.0:
        s = math.exp(-(ratio - 1.0) * float(c["force_k"]))
        out.update({"scale": max(0.0, s),
                    "why": "力 %.1fN 超上限 %.0fN ⇒ 置信度×%.3f" % (F, c["force_max"], s)})
    return out


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
            V_p: float | None = None, cfg: dict | None = None,
            force=None, contact=None, dir_xy=None, residual=None
            ) -> tuple[list[float], dict]:
    """对名义动作做一次各向异性自然梯度修正。

    参数
    ----
    nominal : 长度 ≥3 的名义动作（[x,y,z] 或 [x,y,z,grip]），单位 mm / 归一化夹爪
    grad_V  : ∇V_p（3 维空间梯度；来自性能流形 `grad`）
    axis    : 约束轴 / 插入轴（`ssmani_c.axis`，无真值时可传 [0,0,1]）
    eta     : 性能流形置信度 ∈ [0,1]
    V_p     : 当前装配代价（用于门控 exp(-V/V0)）
    cfg     : 覆盖 DEFAULTS
    force   : 力向量(N) —— 真六维/三轴力，有就优先（专利路径）
    contact : 接触概率 ∈[0,1]，无真力时与 dir_xy 一起做接触代理
    dir_xy  : 接触方向（径向）
    residual: 闭环残差(3 维)，无接触信息时的最次级代理

    视触觉融合（2026-11-11）
    ------------------------
    纯视觉在盲插区「接触即盲」：进孔后相机看不到 0.1mm 级径向偏差。
    本函数把 ∇V 改成两路融合：远场视觉主导、接触后触觉主导，
    并用力上限保护（超过 F_max 置信度骤降，超 1.5 倍直接停机）。
    融合权重、各向模权、力保护全部落进 info，下游可如实标注。

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

    # ── 视触觉融合：视觉梯度不再强制存在 ──────────────────────────────
    g_vis = None
    gg = np.asarray(grad_V if grad_V is not None else [], dtype=float).reshape(-1)
    if gg.size >= 3 and np.all(np.isfinite(gg[:3])):
        g_vis = gg[:3]

    g_tac, tinfo = tactile_to_gradient(force, contact, dir_xy, residual, axis, c)
    g, finfo = fuse_gradient(g_vis, g_tac, contact, c)
    info["tactile"] = tinfo
    info["fusion"] = finfo
    if g is None:
        info["reason"] = ("无 ∇V 真值（视觉与触觉均无）" if g_vis is None
                          else "无 ∇V_p 真值（性能流形未出数）")
        return u, info

    # ── 力阈值保护（专利步骤4）──────────────────────────────────────
    guard = force_guard(
        (float(np.linalg.norm(np.asarray(force, dtype=float).reshape(-1)[:3]))
         if force is not None else None), c)
    info["guard"] = guard
    if guard["abort"]:
        u_stop = [0.0, 0.0, 0.0] + [float(x) for x in u[3:]]
        info.update({"injected": False, "reason": guard["why"], "aborted": True})
        return u_stop, info

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
    # 触觉主导时不再用视觉代价 V_p 做衰减 —— 盲插区 V_p 本就不可信,
    # 此时门控应由力阈值(guard)接管, 否则「越接近卡住越不敢修」正是死锁。
    if float(finfo.get("w_tac") or 0.0) >= 0.5:
        gate = e * float(guard.get("scale") or 1.0)
        info["gate_mode"] = "tactile_bypass_Vp"
    else:
        gate = e * math.exp(-v / max(c["V0"], 1e-9)) * float(guard.get("scale") or 1.0)
        info["gate_mode"] = "visual_exp_Vp"

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
    d_dev = 0.0
    # 🔴 还不得超过「当前偏差本身」：一拍最多走到零点，天然不过冲。
    #    视觉路径: δ 由 δ = W⁻¹∇V 精确反解。
    #    触觉路径: ∇V 是**力(N)**，δ = |F|/K（K=接触刚度 N/mm），
    #              直接套 W⁻¹∇V 会得到 1/K 倍大的假偏差 ⇒ 限幅失效 ⇒ 极限环。
    #              实测(fix前): 0.4mm 偏差在 0.08↔0.24 之间来回 12 拍不收敛。
    try:
        if float(finfo.get("w_tac") or 0.0) >= 0.5 and force is not None:
            _Fr = _radial_part(np.asarray(force, dtype=float).reshape(-1)[:3], axis)
            K = float(c["contact_stiffness"]) or 1.0
            d_dev = float(np.linalg.norm(_Fr)) / K
        else:
            d_dev = float(np.linalg.norm(np.linalg.solve(W_OF(g), g)))
        # 不加 eps: eps 是为防除零, 加进 cap 反而让限幅越过真实偏差 ⇒ 过冲。
        cap = min(cap, d_dev * 0.95)
    except Exception as _e:                           # noqa: BLE001
        # 不静默: 限幅失效比不修正更危险(会过冲/极限环), 必须留痕
        info["cap_err"] = "%s: %s" % (type(_e).__name__, _e)
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
        "grad_src": tinfo.get("src") if float(finfo.get("w_tac") or 0.0) >= 0.5
                    else ("visual" if g_vis is not None else tinfo.get("src")),
        "w_tac": finfo.get("w_tac"), "w_vis": finfo.get("w_vis"),
        "force_N": (round(float(np.linalg.norm(np.asarray(force, dtype=float).reshape(-1)[:3])), 4)
                    if force is not None else None),
        "dev_est_mm": round(float(d_dev), 6),
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
