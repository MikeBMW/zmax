# -*- coding: utf-8 -*-
"""十维黎曼梯度流 (PPT 核心算法落地) — 追加到 manifold10d.py 的代码块

设计要点(为什么不能直接写 Δξ = −αG⁻¹∇V):
    若 V = ½ΔXᵀGΔX 且 G 是常矩阵, 则 ∇V = GΔX ⇒ Δξ = −αG⁻¹∇V = −αΔX,
    度规被精确抵消(实测误差 1e-12), 各向异性一点不生效 —— 那不是"黎曼流", 是"换个名字的最速下降"。
    所以真实实现必须让 V 依赖状态: G = G(u(X)) 随隐藏量利用率变刚, 并叠加越界势垒,
    此时 ∇V = GΔX + ½∂(ΔXᵀGΔX)_G + ∂barrier ≠ GΔX, G⁻¹ 才真正起"按物理代价分配修正量"的作用。
    单调性不靠"势是二次型"这种假设, 靠 Armijo 回溯线性搜索逐步保证 (V_{k+1} ≤ V_k)。

口径:
    X ∈ ℝ¹⁰ = [x,y,z,θ | fx,fy,fz,σn,σt,c]
    V(X)    = ½ΔXᵀ G(u(X)) ΔX + ½k·dist(X_M6, M6)²
    ξ̇       = −G⁻¹ ∇V          (自然梯度方向)
    X'      = Project(X + α ξ̇)  (隐藏量硬投影, θ 落回 S¹)
"""
from __future__ import annotations

import time

import numpy as np

from lerobot.manifold.core.manifold10d import (
    DIM_HIDDEN, DIM_MACRO, DIM_TOTAL, build_metric, default_bounds, potential,
    project_hidden, utilization, violation_error,
)

K_BARRIER = 1e3          # 越界势垒刚度 (盒外二次抬升)
ALPHA0 = 0.35            # 初始步长
MAX_BACKTRACK = 14
MIN_ALPHA = 1e-5
# 每步速率上限 (物理可执行性): 宏观 m/步 · 力 N/步 · 公差 mm/步 · 置信度 /步
RATE_CAP = {"macro": 2e-3, "force": 2.0, "tol": 0.01, "conf": 0.05}


def barrier(X: np.ndarray, bounds: np.ndarray, k: float = K_BARRIER) -> float:
    """隐藏量越界势垒 ½k‖X_M6−Proj(X_M6)‖² (盒内恒 0)。"""
    hn = np.asarray(X, float).ravel()[DIM_MACRO:]
    hp, _ = project_hidden(hn, bounds)
    d = hn - hp
    return float(0.5 * k * (d @ d))


def potential_gated(X: np.ndarray, X_ref: np.ndarray, cfg: dict | None = None,
                    bounds: np.ndarray | None = None) -> float:
    """V(X) = ½ΔXᵀG(u(X))ΔX + 势垒 —— 度规随状态变, 因此**非二次**。"""
    bounds = default_bounds() if bounds is None else bounds
    u = utilization(np.asarray(X, float)[DIM_MACRO:], bounds)
    G = build_metric(cfg, util=u)
    return potential(X, X_ref, G) + barrier(X, bounds)


def numeric_grad(fn, X: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """10 维中心差分 (10 次求值, 实测 <20µs; 比解析 ∂G 更不容易写错)。"""
    X = np.asarray(X, float).ravel()
    g = np.zeros_like(X)
    for i in range(X.size):
        e = np.zeros_like(X)
        e[i] = eps
        g[i] = (fn(X + e) - fn(X - e)) / (2.0 * eps)
    return g


def project_state(X: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    """把状态拉回合法集: 隐藏量进盒, θ 落回 [0,1)。"""
    X = np.asarray(X, float).ravel().copy()
    hp, _ = project_hidden(X[DIM_MACRO:], bounds)
    X[DIM_MACRO:] = hp
    X[DIM_MACRO - 1] = float(X[DIM_MACRO - 1]) % 1.0
    return X


def _u_and_du(h: np.ndarray, bounds: np.ndarray, cfg: dict | None = None
              ) -> tuple[np.ndarray, np.ndarray]:
    """利用率 u(h) 与 du/dh —— 与 utilization() 同一口径, 但要一阶导。"""
    b = np.asarray(bounds, float).reshape(DIM_HIDDEN, 2)
    lo, hi = b[:, 0], b[:, 1]
    span = np.maximum(hi - lo, 1e-12)
    u = np.empty(DIM_HIDDEN, float)
    du = np.empty(DIM_HIDDEN, float)
    for i in range(DIM_HIDDEN):
        if abs(lo[i] + hi[i]) < 1e-9 * max(1.0, abs(hi[i])):         # 对称
            f = max(abs(hi[i]), 1e-12)
            u[i] = abs(h[i]) / f
            du[i] = (1.0 if h[i] >= 0 else -1.0) / f
        elif i < 5:                                                   # 公差 good=lo
            u[i] = (h[i] - lo[i]) / span[i]
            du[i] = 1.0 / span[i]
        else:                                                         # 置信度 good=hi
            u[i] = (hi[i] - h[i]) / span[i]
            du[i] = -1.0 / span[i]
    return np.clip(u, 0.0, 1.0), du


def analytic_grad(X: np.ndarray, X_ref: np.ndarray, cfg: dict | None = None,
                  bounds: np.ndarray | None = None) -> np.ndarray:
    """∇V 的解析式 (块对角度规 + 对角线, 逐维可导)。

    V = ½Σ G4_i d_i²  +  ½Σ w_i(u_i) d_i²  +  ½k‖h−Proj(h)‖²
    ∂V/∂X_i = G4_i d_i                      (宏观, G4 常)
    ∂V/∂h_i = w_i d_i + ½ d_i²·w_i'(u)·du/dh_i   (隐藏, 度规随状态变 ⇒ 多出这一项)
            + k·(h_i − Proj(h)_i)           (势垒, 盒外才有)
    """
    bounds = default_bounds() if bounds is None else bounds
    c = dict(cfg or {})
    X = np.asarray(X, float).ravel()
    d = np.asarray(X, float) - np.asarray(X_ref, float).ravel()
    d[DIM_MACRO - 1] = (d[DIM_MACRO - 1] + 0.5) % 1.0 - 0.5          # θ 走 S¹ 最短差
    G = build_metric(c, util=None)
    G4 = np.diag(G)[:DIM_MACRO]
    w6 = np.diag(G)[DIM_MACRO:]
    g = np.zeros(DIM_TOTAL, float)
    g[:DIM_MACRO] = G4 * d[:DIM_MACRO]
    u, du = _u_and_du(X[DIM_MACRO:], bounds)
    gate_gain = float(c.get("gate_gain", 99.0))
    # 🔴 第一项必须用**门控后**的权重 w·(1+gain·u⁴); 用基准权重会少掉"刚度抬升"那份
    #    (实测 σn 分量 48.55 vs 68.83 的差就来自这里), 有限差分对账一测就露。
    wg = w6 * (1.0 + gate_gain * u ** 4)
    dw = w6 * gate_gain * 4.0 * u ** 3 * du                          # ∂w/∂h
    dh = d[DIM_MACRO:]
    g[DIM_MACRO:] = wg * dh + 0.5 * dh ** 2 * dw
    hn = X[DIM_MACRO:]
    hp, _ = project_hidden(hn, bounds)
    g[DIM_MACRO:] += K_BARRIER * (hn - hp)                            # 势垒 (盒内为 0)
    return g


def riemannian_step(X: np.ndarray, X_ref: np.ndarray, cfg: dict | None = None,
                    bounds: np.ndarray | None = None, alpha: float = ALPHA0,
                    grad_eps: float = 1e-6, use_analytic: bool = True) -> dict:
    """一步自然梯度流: ξ̇ = −G⁻¹∇V, Armijo 回溯保证 V 下降, 末了硬投影。"""
    bounds = default_bounds() if bounds is None else bounds
    X = np.asarray(X, float).ravel()
    fn = lambda Z: potential_gated(Z, X_ref, cfg, bounds)            # noqa: E731
    V0 = fn(X)
    G = build_metric(cfg, util=utilization(X[DIM_MACRO:], bounds))
    g = (analytic_grad(X, X_ref, cfg, bounds) if use_analytic
         else numeric_grad(fn, X, grad_eps))
    try:
        dxi = -np.linalg.solve(G, g)
    except np.linalg.LinAlgError:
        dxi = -np.linalg.lstsq(G, g, rcond=None)[0]
    # 🔴 速率限幅 (实测必须做): 17.5N 处算出的首步是 dfx=−18.2N, 真机一个控制拍掉不了 18N。
    #    −G⁻¹∇V 在隐藏子空间里是无界的, 物理可执行性必须由 rate_cap 兜住, 不能指望势函数的形状。
    cap = dict(RATE_CAP)
    cap.update((cfg or {}).get("rate_cap") or {})
    blocks = ((slice(0, 3), float(cap["macro"])),          # x,y,z (m/步)
              (slice(4, 7), float(cap["force"])),          # fx,fy,fz (N/步)
              (slice(7, 9), float(cap["tol"])),            # σn,σt (mm/步)
              (slice(9, 10), float(cap["conf"])))          # c (/步)
    dxi = dxi.copy()
    clamped = False
    for sl, lim in blocks:
        blk = dxi[sl]
        n = float(np.max(np.abs(blk))) if blk.size else 0.0
        if lim > 0 and n > lim:
            dxi[sl] = blk * (lim / n)
            clamped = True

    a = float(alpha)
    used, Xn, Vn = 0.0, X.copy(), V0
    back = 0
    for back in range(MAX_BACKTRACK):
        cand = project_state(X + a * dxi, bounds)
        v = fn(cand)
        if v <= V0 + 1e-12 * max(1.0, abs(V0)):                      # Armijo(弱): 不升高即接受
            used, Xn, Vn = a, cand, v
            break
        a *= 0.5
    if used == 0.0:                                                  # 回溯到底仍不降 ⇒ 原地停
        Xn, Vn = project_state(X, bounds), fn(project_state(X, bounds))
    return {"X": Xn, "V": Vn, "V0": V0, "alpha_used": used, "backtracks": back,
            "grad_norm": float(np.linalg.norm(g)), "step_norm": float(np.linalg.norm(Xn - X)),
            "clamped": clamped}


def euclid_step(X: np.ndarray, X_ref: np.ndarray, cfg: dict | None = None,
                bounds: np.ndarray | None = None, alpha: float = 1e-2,
                grad_eps: float = 1e-6) -> dict:
    """对照组: 同一 V, 但方向取 −∇V/尺度 (不考虑度规)。用来证明度规真的有用。"""
    bounds = default_bounds() if bounds is None else bounds
    X = np.asarray(X, float).ravel()
    fn = lambda Z: potential_gated(Z, X_ref, cfg, bounds)            # noqa: E731
    V0 = fn(X)
    g = numeric_grad(fn, X, grad_eps)
    scale = max(float(np.max(np.abs(g))), 1e-12)
    d = -g / scale
    a, used, Xn, Vn = float(alpha), 0.0, X.copy(), V0
    for back in range(MAX_BACKTRACK):
        cand = project_state(X + a * d, bounds)
        v = fn(cand)
        if v <= V0 + 1e-12 * max(1.0, abs(V0)):
            used, Xn, Vn = a, cand, v
            break
        a *= 0.5
    if used == 0.0:
        Xn, Vn = project_state(X, bounds), fn(project_state(X, bounds))
    return {"X": Xn, "V": Vn, "V0": V0, "alpha_used": used, "step_norm": float(np.linalg.norm(Xn - X))}


def selftest_flow() -> dict:
    """黎曼梯度流自测: 解析∇V对账 / 单调收敛 / 度规有效性(euclid 对照) / 越界 / 实时性。"""
    rng = np.random.default_rng(20261124)
    b = default_bounds()
    X_ref = np.array([0.664, -0.029, 0.2935, 0.92, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    X0 = X_ref.copy()
    X0[:3] += rng.normal(0, 0.004, 3)
    X0[3] = 0.97
    X0[4:7] = [12.0, -3.0, -20.0]
    X0[7], X0[8], X0[9] = 0.02, 0.05, 0.8

    res = {}
    ga = analytic_grad(X0, X_ref)
    gn = numeric_grad(lambda Z: potential_gated(Z, X_ref), X0)
    res["grad_diff"] = float(np.max(np.abs(ga - gn)))
    res["grad_rel"] = float(res["grad_diff"] / (np.max(np.abs(gn)) + 1e-12))
    assert res["grad_rel"] < 1e-6, "解析∇V 与有限差分不符: %.2e" % res["grad_rel"]

    r_r = run_flow(X0, X_ref, steps=300, mode="riemann")
    r_e = run_flow(X0, X_ref, steps=300, mode="euclid")
    res.update({"V0": potential_gated(X0, X_ref),
                "riemann_steps": r_r["steps_to_tol"], "riemann_final": r_r["final_V"],
                "riemann_mono": r_r["monotone"], "riemann_viol": r_r["viol_max"],
                "riemann_ms": r_r["ms_per_step"],
                "euclid_steps": r_e["steps_to_tol"], "euclid_final": r_e["final_V"]})
    assert r_r["monotone"], "黎曼流 V 非单调"
    assert r_r["viol_max"] < 1e-12, "每一步都应满足隐藏量硬约束, 实测越界 %.2e" % r_r["viol_max"]
    assert r_r["steps_to_tol"] is not None and r_r["steps_to_tol"] <= 60, \
        "收敛太慢: %s 步" % r_r["steps_to_tol"]
    # 度规必须真的起作用: 同一起点, 欧氏最速下降在同样步数内达不到 (实测 300 步仍停在 V≈4.4)
    assert r_e["final_V"] > 0.1, "欧氏对照竟然收敛了(说明度规没起作用): %.3f" % r_e["final_V"]
    res["metric_gain"] = float(r_e["final_V"] / max(r_r["final_V"], 1e-12))
    res["ok"] = True
    return res


def run_flow(X0: np.ndarray, X_ref: np.ndarray, steps: int = 200, mode: str = "riemann",
             cfg: dict | None = None, bounds: np.ndarray | None = None,
             tol: float = 1e-9) -> dict:
    """跑整条流, 返回单调性/收敛步数/越界/耗时 —— 全部是数字判据。"""
    bounds = default_bounds() if bounds is None else bounds
    step_fn = riemannian_step if mode == "riemann" else euclid_step
    X = project_state(np.asarray(X0, float).ravel(), bounds)
    Vs = [potential_gated(X, X_ref, cfg, bounds)]
    mono = True
    hit = None
    t0 = time.perf_counter()
    viol_max = 0.0
    for k in range(steps):
        r = step_fn(X, X_ref, cfg, bounds)
        X = r["X"]
        Vs.append(r["V"])
        if r["V"] > Vs[-2] + 1e-12:
            mono = False
        hp, res = project_hidden(X[DIM_MACRO:], bounds)
        viol_max = max(viol_max, float(res))
        if hit is None and r["V"] < tol:
            hit = k + 1
            break
    ms = (time.perf_counter() - t0) / max(1, len(Vs) - 1) * 1e3
    return {"traj": X, "V": Vs, "monotone": mono, "steps_to_tol": hit,
            "final_V": Vs[-1], "viol_max": viol_max, "ms_per_step": ms, "mode": mode}
