# -*- coding: utf-8 -*-
"""metric_inject.py — 度规硬注入（Hard Injection）：训练端马氏损失 + 推理端 ODE 步内注入

哲学
----
AI 网络负责"大方向和大致速度"，物理几何负责"绝对安全底线"。
度规 M 不是靠反向传播盲猜的权重，而是由**装配公差**给定的物理先验，在两个地方硬生效：

  训练端  L = (v_θ − v*)ᵀ M (v_θ − v*)        马氏距离重塑损失地形
  推理端  x_{t+Δ} = x_t + Δ(v_θ − α·M⁻¹∇V)     每步积分都纠偏，不是终点叠加

两个 M⁻¹/M 的作用方向**看似相反，实则同源**（M⁻¹M = I），这是刻意分工：
  · 训练端：M 的径向特征值小 ⇒ 径向误差惩罚小 ⇒ 网络少管径向（交给解析层）
  · 推理端：M⁻¹ 的径向增益大 ⇒ 解析层疯狂纠径向（防刮擦）
如果两处都"用力"，网络会和解析层打架；分工后各管一段。

三个函数
--------
1. `metric_flow_loss`   — 马氏加权的 Flow Matching 损失（训练）
2. `hard_inject_step`   — ODE 单步硬注入（推理，逐积分步）
3. `project_metric_ball`— 公差盒投影 Project_M（推理，逐步截断）

单位/量纲
---------
· axis 为插入轴单位向量；σ_t / σ_n 与 x、v 同单位（本项目动作层用 mm）
· 损失函数不改变量纲；M⁻¹∇V 中 ∇V 必须是**位移量纲**才与速度同量纲
  （触觉力 N 需先除接触刚度 K 反解成 mm，见 ZMP-2026-013 §4.6）
"""
from __future__ import annotations

import numpy as np

EPS = 1e-12


def _unit(v) -> np.ndarray | None:
    a = np.asarray(v, dtype=float).reshape(-1)[:3]
    n = float(np.linalg.norm(a))
    if not np.isfinite(n) or n < EPS:
        return None
    return a / n


def metric_matrix(axis, sigma_t: float, sigma_n: float) -> np.ndarray | None:
    """M = σ_t²·P_t + σ_n²·P_n  （P_t = I − nnᵀ 径向, P_n = nnᵀ 轴向）"""
    n = _unit(axis)
    if n is None or sigma_t <= 0 or sigma_n <= 0:
        return None
    Pt = np.eye(3) - np.outer(n, n)
    Pn = np.outer(n, n)
    return (sigma_t ** 2) * Pt + (sigma_n ** 2) * Pn


# ══════════════════════════════════════════════════════════════════
# 1. 训练端：马氏加权 Flow Matching 损失
# ══════════════════════════════════════════════════════════════════
def metric_flow_loss(v_pred, v_target, axis, sigma_t: float, sigma_n: float,
                     reduce: bool = True):
    """L = (v_θ − v*)ᵀ M (v_θ − v*)，逐样本返回或取均值。

    v_pred / v_target: (..., 3) 或 (3,)
    reduce=True  → 返回标量均值；False → 返回逐样本损失数组

    与各向同性 L2 的区别：
      · 轴向误差被放大 (σ_n)² 倍 ⇒ 网络必须严防"轴向猛冲"
      · 径向误差被压缩 (σ_t)² 倍 ⇒ 网络不必为径向精度过度用力（解析层会兜）
    """
    M = metric_matrix(axis, sigma_t, sigma_n)
    if M is None:
        return None
    p = np.asarray(v_pred, dtype=float)
    g = np.asarray(v_target, dtype=float)
    err = (p - g)[..., :3]
    # eᵀMe 逐样本：einsum 比循环快且无广播歧义
    quad = np.einsum("...i,ij,...j->...", err, M, err)
    quad = np.maximum(quad, 0.0)
    return float(np.mean(quad)) if reduce else quad


def isotropic_flow_loss(v_pred, v_target, reduce: bool = True):
    """对照用：各向同性 L2（传统 Flow Matching 损失）。"""
    p = np.asarray(v_pred, dtype=float)
    g = np.asarray(v_target, dtype=float)
    quad = np.sum((p - g)[..., :3] ** 2, axis=-1)
    return float(np.mean(quad)) if reduce else quad


# ══════════════════════════════════════════════════════════════════
# 2. 推理端：ODE 单步硬注入
# ══════════════════════════════════════════════════════════════════
def hard_inject_step(x_t, v_theta, grad_V, axis, sigma_t: float, sigma_n: float,
                     dt: float, alpha: float,
                     force_norm: float | None = None,
                     f_max: float = 40.0, abort_ratio: float = 1.5,
                     max_corr: float | None = None):
    """把一步积分从 x_t 推到 x_{t+Δ}，中途用 M⁻¹∇V 硬改写速度场。

        x_{t+Δ} = x_t + dt · ( v_θ − α · M⁻¹ ∇V )

    参数
    ----
    x_t       : (3,) 当前位置/动作（与 v 同量纲）
    v_theta   : (3,) 世界模型输出的名义速度
    grad_V    : (3,) 物理误差梯度（**位移量纲**；力需先 /K）
    alpha     : 门控系数（含置信度与代价衰减）
    force_norm: 法向力幅值（N），用于力保护；None 表示无力信息
    f_max / abort_ratio : 与 ZMP-2026-013 一致的力阈值与停机倍数

    返回  (x_next, info)
    info: {"injected", "why", "v_corr", "dv", "gate", "stop"}
    """
    x = np.asarray(x_t, dtype=float).reshape(-1)[:3]
    v = np.asarray(v_theta, dtype=float).reshape(-1)[:3]
    out = {"injected": False, "why": None, "v_corr": v.copy(),
           "dv": np.zeros(3), "gate": float(alpha), "stop": False}

    M = metric_matrix(axis, sigma_t, sigma_n)
    if M is None:
        out["why"] = "invalid_axis_or_sigma"
        return x + dt * v, out
    if grad_V is None:
        out["why"] = "no_grad"
        return x + dt * v, out

    # 力保护优先：超停机阈值 ⇒ 门控归零，退化为原始 AI 动作（不纠偏、不叠加）
    gate = float(alpha)
    if force_norm is not None and np.isfinite(force_norm):
        r = float(force_norm) / max(float(f_max), EPS)
        if r > float(abort_ratio):
            gate = 0.0
            out["stop"] = True
            out["why"] = "force_abort"
        elif r > 1.0:
            gate = gate * float(np.exp(-(r - 1.0)))
    if gate <= 0.0:
        out["gate"] = 0.0
        out["why"] = out["why"] or "gate_zero"
        return x + dt * v, out

    g = np.asarray(grad_V, dtype=float).reshape(-1)[:3]
    if not np.all(np.isfinite(g)):
        out["why"] = "grad_nonfinite"
        return x + dt * v, out

    dv = -gate * (np.linalg.inv(M) @ g)
    # ⚠️ M⁻¹ 径向放大 (σn/σt)² 倍, 无限幅时会一次修过头:
    #    实测 0.40mm 偏差单步修成 −3.38mm(过冲 8 倍)。
    # max_corr 的语义是**单步位移上限(mm)**, 不是速度上限 ——
    #   dv 加在速度上, 实际位移 = dt·dv, 所以速度上限要除 dt。
    #   (曾把 max_corr 当速度上限, 结果 dt=0.05 时每步只修 0.019mm, 20 步都追不上终点叠加)
    if max_corr is not None and max_corr > 0 and dt > 0:
        dv_cap = max_corr / dt
        dn = float(np.linalg.norm(dv))
        if dn > dv_cap:
            dv = dv * (dv_cap / dn)
            out["capped"] = True
    v_corr = v + dv
    out.update({"injected": True, "why": "ok", "v_corr": v_corr, "dv": dv,
                "gate": gate})
    return x + dt * v_corr, out


# ══════════════════════════════════════════════════════════════════
# 3. 推理端：公差盒投影 Project_M
# ══════════════════════════════════════════════════════════════════
def project_metric_ball(x, axis, tol_radial: float | None = None,
                        ref=None, radial_only: bool = True):
    """把位置/动作投影回公差允许的盒内。

    radial_only=True（默认）：只把**径向偏移**夹到 ±tol_radial，轴向不动
      —— 轴向是推进通道，夹它等于禁止插入。
    tol_radial 为 None ⇒ 不投影（返回原值与 applied=False）。

    返回 (x_proj, info)
    """
    xa = np.asarray(x, dtype=float).reshape(-1)[:3]
    info = {"applied": False, "clipped": 0.0}
    n = _unit(axis)
    if n is None or tol_radial is None or tol_radial <= 0:
        return xa, info
    Pt = np.eye(3) - np.outer(n, n)
    # ⚠️ ref=None 时必须用**原点(孔心)**作参考, 不能用 xa 自身 ——
    #    用自身会让 (xa − base) ≡ 0, 径向偏移恒为 0, 投影永远判不出超差(实测踩过)
    base = np.zeros(3) if ref is None else np.asarray(ref, dtype=float).reshape(-1)[:3]
    rad = Pt @ (xa - base)                     # 径向偏移（相对孔心）
    rn = float(np.linalg.norm(rad))
    if rn <= tol_radial:
        return xa, info
    rad_clipped = rad * (tol_radial / rn)
    xp = xa - Pt @ (xa - base) + rad_clipped   # 只替换径向部分
    if not radial_only:
        pass
    info.update({"applied": True, "clipped": rn - tol_radial, "r_before": rn,
                 "r_after": tol_radial})
    return xp, info


__all__ = ["metric_matrix", "metric_flow_loss", "isotropic_flow_loss",
           "hard_inject_step", "project_metric_ball"]
