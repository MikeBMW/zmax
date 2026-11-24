# -*- coding: utf-8 -*-
"""manifold10d.py — 十维流形引擎 (4 维宏观时空 ⊕ 6 维隐藏物理约束)

设计口径(2026-11-24, 老倪方案落地):
    X = [x, y, z, θ   |   fx, fy, fz,  σ_n, σ_t, c]
         └─ 4D 宏观 ─┘    └──────── 6D 隐藏 ────────┘
    x,y,z  末端位置 (m)          θ    进度 ∈ [0,1) (S¹ 环绕)
    fx,fy,fz 工具系力/力矩代理 (N) σ_n  法向公差 (mm)  σ_t 切向公差/径向余量 (mm)
    c      视觉/感知置信度 ∈ [0,1]

度规块对角:
    G = blkdiag(G4, G6),   V(X) = ½ ΔXᵀ G ΔX
G6 是灵魂 —— 按当前工况动态生成:
    · 插孔盲区  ⇒ 径向(fx,fy)惩罚大 / 轴向(fz)惩罚小 (高度各向异性)
    · IHS 散热齿 ⇒ 接触齿的惩罚 ×teeth_penalty (默认 1000)
    · 公差紧绷  ⇒ σ_n/σ_t 权重按 1/tol² 放大

动作不是"G⁻¹∇V 直接走" —— 那样在二次型上退化成 ΔX(度规自动抵消, 是假动作)。
本模块用**约束投影**求真正有物理意义的解:
    δ* = argmin  ½(δ-δ_intent)ᵀ G4 (δ-δ_intent) + ½(Jδ+h)ᵀ G6 (Jδ+h)
       = (G4 + JᵀG6J)⁻¹ (G4 δ_intent − JᵀG6 h)
其中 δ_intent 是 4D 大模型给的粗意图, h 是 6D 隐藏量的当前偏差, J=∂h/∂X_macro 是
敏感度(每 mm 位移让力/公差变化多少)。这才是"大模型天马行空 + 引擎戴着镣铐跳舞"。
隐藏量越界时再做**硬投影** Project_M6 拉回安全通道 (对应方案的"第一陈类为 0")。

对外三个入口:
    build_metric(cfg)            → G10 (块对角, 正定可 Cholesky)
    constrained_step(...)        → δ* (4D 动作增量) + 诊断
    project_hidden(h, bounds)    → h_proj + 越界残差(用于门控/告警)
    selftest()                   → 全部断言返回数字, 供 tools/verify_manifold10d.py 打印

红线: 本模块**不直接下发运动**。它只产出动作增量与门控量, 下发仍走 L2 执行器/授权链。
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

DIM_MACRO = 4      # x, y, z, θ
DIM_HIDDEN = 6     # fx, fy, fz, σ_n, σ_t, c
DIM_TOTAL = DIM_MACRO + DIM_HIDDEN

# 隐藏量下标
IX_FX, IX_FY, IX_FZ, IX_SN, IX_ST, IX_C = range(DIM_HIDDEN)

DEFAULT_CFG: dict[str, Any] = {
    # ── 4D 宏观块的物理尺度 (用于把 V 无量纲化) ───────────────────────
    "pos_scale_m": 0.010,        # 10mm 记 1 个单位
    "progress_scale": 0.10,      # 10% 进度记 1 个单位
    # ── 6D 隐藏块的"允许上限" (越小 = 惩罚越重) ────────────────────────
    "F_radial_max_n": 18.0,      # SFP 插入径向允许 (老倪产线口径 SFP 18N)
    "F_axial_max_n": 60.0,       # 轴向允许 (QSFP 60N)
    "tol_normal_mm": 0.05,       # 法向公差
    "tol_tangent_mm": 0.20,      # 切向公差/径向余量
    "conf_scale": 0.25,          # 置信度尺度
    # ── 工况开关 (动态各向异性) ───────────────────────────────────────
    "anisotropy": 1.0,           # 1=各向异性(径向重/轴向轻), 0=各向同性(对照用)
    "teeth_penalty": 1000.0,     # IHS 散热齿接触惩罚倍数
    "blind_hole": True,          # 插孔盲区 ⇒ 径向收紧
}


# ── 度规 ────────────────────────────────────────────────────────────
def build_metric(cfg: dict | None = None, util: np.ndarray | None = None) -> np.ndarray:
    """构造 10×10 块对角度规 G = blkdiag(G4, G6) (对称正定)。

    util: 6 维隐藏量**利用率** ∈[0,1] (|当前值|/上限)。给了就做"柔性→刚性"门控:
        w_i *= 1 + gate_gain·u_i⁴   (gate_gain 默认 99)
        ⇒ 盒内(u≈0)几乎不压动作(意图照走), 逼近边界(u→1)刚度涨 100 倍(自动收手),
          越过边界再交给 QP 硬约束兜底。这解决了"参考点取零力 ⇒ 引擎一路回撤"的病。
    """
    c = dict(DEFAULT_CFG)
    if cfg:
        c.update(cfg)
    s_pos = float(c["pos_scale_m"])
    s_prg = float(c["progress_scale"])
    G4 = np.diag([1.0 / s_pos ** 2, 1.0 / s_pos ** 2, 1.0 / s_pos ** 2, 1.0 / s_prg ** 2])

    Fr = float(c["F_radial_max_n"])
    Fa = float(c["F_axial_max_n"])
    aniso = float(c["anisotropy"])
    if aniso > 0.0 and c.get("blind_hole"):
        # 插孔盲区: 径向允许力小(惩罚重), 轴向允许力大(惩罚轻)
        wr = 1.0 / (Fr ** 2)
        wa = 1.0 / (Fa ** 2)
    else:
        # 各向同性对照: 三个力分量用同一尺度
        F0 = math.sqrt(Fr * Fa)
        wr = wa = 1.0 / (F0 ** 2)
    teeth = float(c.get("teeth_penalty", 1.0)) if c.get("teeth_active") else 1.0
    wn = 1.0 / (float(c["tol_normal_mm"]) ** 2)
    wt = 1.0 / (float(c["tol_tangent_mm"]) ** 2)
    wc = 1.0 / (float(c["conf_scale"]) ** 2)

    w6 = np.array([wr * teeth, wr * teeth, wa, wn, wt, wc], float)
    if util is not None:
        u = np.clip(np.asarray(util, float).ravel()[:DIM_HIDDEN], 0.0, 1.0)
        g = float(c.get("gate_gain", 99.0))
        w6 = w6 * (1.0 + g * u ** 4)
    G = np.zeros((DIM_TOTAL, DIM_TOTAL), float)
    G[:DIM_MACRO, :DIM_MACRO] = G4
    G[DIM_MACRO:, DIM_MACRO:] = np.diag(w6)
    G = (G + G.T) / 2.0
    return G


_GOOD_AT_LOW = np.array([True] * 5 + [False])   # 力/公差: 越低越好; 置信度: 越高越好


def utilization(h_now: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    """隐藏量利用率 u_i ∈[0,1] (1 = 顶到安全边界)。

    对称盒 (力: [-F,F])   ⇒ u = |h|/F
    单侧盒 (公差 [0,X])    ⇒ u = (h−lo)/(hi−lo)          (good=lo)
    置信度 [c_min,1]      ⇒ u = (hi−h)/(hi−lo)          (good=hi; 高置信=低利用率)
    原来一律"离中点/半宽", 且置信度按 good=lo 算 ⇒ c=0.93 被当成 93% 顶格, 刚度虚涨。
    """
    b = np.asarray(bounds, float).reshape(DIM_HIDDEN, 2)
    hn = np.asarray(h_now, float).ravel()[:DIM_HIDDEN]
    lo, hi = b[:, 0], b[:, 1]
    span = np.maximum(hi - lo, 1e-12)
    u = np.empty(DIM_HIDDEN, float)
    for i in range(DIM_HIDDEN):
        if abs(lo[i] + hi[i]) < 1e-9 * max(1.0, abs(hi[i])):       # 对称 ⇒ |h|/F
            u[i] = abs(hn[i]) / max(abs(hi[i]), 1e-12)
        elif _GOOD_AT_LOW[i]:
            u[i] = (hn[i] - lo[i]) / span[i]
        else:                                                       # good=hi
            u[i] = (hi[i] - hn[i]) / span[i]
    return np.clip(u, 0.0, 1.0)


def violation_error(h_now: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    """越界量 h⁺ (盒内 = 0, 带符号: 越过哪边就按哪边的方向)。"""
    b = np.asarray(bounds, float).reshape(DIM_HIDDEN, 2)
    hn = np.asarray(h_now, float).ravel()[:DIM_HIDDEN]
    lo, hi = b[:, 0], b[:, 1]
    over = np.where(hn > hi, hn - hi, 0.0)
    under = np.where(hn < lo, hn - lo, 0.0)
    return (over + under).astype(float)


def metric_report(G: np.ndarray) -> dict:
    """度规自检: 对称/正定/条件数 (给报告与断言用)。"""
    G = np.asarray(G, float)
    sym = float(np.max(np.abs(G - G.T)))
    w = np.linalg.eigvalsh(G)
    try:
        np.linalg.cholesky(G)
        chol = True
    except np.linalg.LinAlgError:
        chol = False
    return {"sym_err": sym, "eig_min": float(w.min()), "eig_max": float(w.max()),
            "cond": float(w.max() / max(w.min(), 1e-300)), "cholesky_ok": chol,
            "positive_definite": bool(w.min() > 0)}


# ── 势能 / 自然梯度 ──────────────────────────────────────────────────
def potential(X: np.ndarray, X_ref: np.ndarray, G: np.ndarray) -> float:
    """V = ½ ΔXᵀ G ΔX (θ 分量按 S¹ 取最短差)。"""
    d = _delta(X, X_ref)
    return float(0.5 * d @ G @ d)


def natural_gradient(X: np.ndarray, X_ref: np.ndarray, G: np.ndarray) -> np.ndarray:
    """自然梯度流方向 −G⁻¹∇V (∇V = GΔX ⇒ 方向 = −ΔX)。

    保留这个入口是为了**能量/势场监视**(与 ss_energy 同源), 不作动作下发 ——
    二次型上它会退化成 −ΔX, 真正的动作解见 constrained_step()。
    """
    d = _delta(X, X_ref)
    return -np.linalg.solve(G, G @ d)


def _delta(X: np.ndarray, X_ref: np.ndarray) -> np.ndarray:
    d = np.asarray(X, float).ravel() - np.asarray(X_ref, float).ravel()
    if d.size >= DIM_MACRO:
        # θ 是 S¹: 取最短环绕差
        d[DIM_MACRO - 1] = (d[DIM_MACRO - 1] + 0.5) % 1.0 - 0.5
    return d


# ── 约束投影 (核心算子) ──────────────────────────────────────────────
def constrained_step(delta_intent: np.ndarray, hidden_err: np.ndarray,
                     J: np.ndarray, G4: np.ndarray, G6: np.ndarray,
                     bounds: np.ndarray | None = None,
                     hidden_now: np.ndarray | None = None,
                     max_iter: int = 12) -> dict:
    """把 4D 意图投影成"不撞 6D 隐藏约束"的 4D 动作增量 (带硬约束的凸 QP)。

        min_δ  ½(δ−δ_intent)ᵀ G4 (δ−δ_intent) + ½(Jδ+h)ᵀ G6 (Jδ+h)
        s.t.   lo ≤ h + Jδ ≤ hi          (隐藏量安全盒, 给了 bounds 才生效)

    等价 QP:  min ½δᵀAδ − bᵀδ,  A = G4 + JᵀG6J,  b = G4 δ_intent − JᵀG6 h
    用 active-set 精确求解 (n=4, 约束 ≤12): 不靠事后 lstsq 回推 ——
    那样在约束互相牵扯时会把轴向意图算成反向的径向位移 (实测 dx=−3.45mm)。
    """
    di = np.asarray(delta_intent, float).ravel()[:DIM_MACRO]
    h = np.asarray(hidden_err, float).ravel()[:DIM_HIDDEN]
    J = np.asarray(J, float).reshape(DIM_HIDDEN, DIM_MACRO)
    G4 = np.asarray(G4, float)
    G6 = np.asarray(G6, float)

    A = G4 + J.T @ G6 @ J
    b = G4 @ di - J.T @ G6 @ h
    d_free = _safe_solve(A, b)
    out = {"delta": d_free, "cost_intent": float(0.5 * di @ G4 @ di),
           "cost_constrained": _qp_cost(d_free, di, h, J, G4, G6),
           "hard_projected": False, "proj_residual": 0.0,
           "hidden_after": None, "violation_after": 0.0, "active": 0}

    if bounds is None or hidden_now is None:
        return out

    hn = np.asarray(hidden_now, float).ravel()[:DIM_HIDDEN]
    C, u = _box_rows(bounds, hn, J)            # C δ ≤ u
    d, act = _qp_activeset(A, b, C, u, max_iter=max_iter)
    ha = hn + J @ d
    hp, res = project_hidden(ha, bounds)       # 数值兜底(理论上 res~1e-15)
    out.update({"delta": d, "hidden_after": ha, "violation_after": float(max(0.0, res)),
                "proj_residual": float(res), "hard_projected": bool(act),
                "active": int(act), "cost_constrained": _qp_cost(d, di, h, J, G4, G6)})
    return out


def _safe_solve(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return np.linalg.solve(A + 1e-9 * np.eye(A.shape[0]), b)


def _qp_cost(d, di, h, J, G4, G6) -> float:
    return float(0.5 * (d - di) @ G4 @ (d - di) + 0.5 * (J @ d + h) @ G6 @ (J @ d + h))


def _box_rows(bounds: np.ndarray, h_now: np.ndarray, J: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """把 lo ≤ h+Jδ ≤ hi 化成 Cδ ≤ u。

    注意 C 的列数是 **δ 的维数(4)**: 第 i 个隐藏量的系数行是 eᵢᵀJ (不是 eᵢ),
    原来按 eᵢ 建 6 列 ⇒ 与 δ(4) 维不匹配, matmul 直接抛错。
    """
    b = np.asarray(bounds, float).reshape(DIM_HIDDEN, 2)
    rows, ub = [], []
    for i in range(DIM_HIDDEN):
        lo, hi = b[i]
        crow = np.asarray(J[i], float)          # ∂h_i/∂δ, 长度 = δ 维数
        if float(np.max(np.abs(crow))) < 1e-12:
            # 该隐藏量对 δ 完全不敏感 (敏感度行全 0) ⇒ 约束恒成立/恒不成立,
            # 不能进 KKT —— 零行会让 KKT 奇异, 解出来是垃圾(实测 dx 被压成 0.015mm)。
            continue
        if not (np.isnan(hi) or np.isinf(hi)):
            rows.append(crow); ub.append(hi - h_now[i])
        if not (np.isnan(lo) or np.isinf(lo)):
            rows.append(-crow); ub.append(h_now[i] - lo)
    if not rows:
        return np.zeros((0, J.shape[1])), np.zeros(0)
    return np.array(rows, float), np.array(ub, float)


def _qp_activeset(A: np.ndarray, b: np.ndarray, C: np.ndarray, u: np.ndarray,
                  max_iter: int = 12, tol: float = 1e-12) -> tuple[np.ndarray, int]:
    """凸 QP  min ½δᵀAδ − bᵀδ  s.t. Cδ ≤ u  (A 正定) 的 active-set 精确解。

    返回 (δ*, 触发的约束数)。n 只有 4, 单次 KKT 求解 ~几十 µs, 满足 1kHz。
    """
    n = A.shape[0]
    if C.size == 0:
        return _safe_solve(A, b), 0
    m = C.shape[0]
    act: list[int] = []
    d = _safe_solve(A, b)
    for _ in range(max_iter):
        viol = C @ d - u
        outside = [i for i in range(m) if viol[i] > 1e-10 and i not in act]
        if not outside:
            if not act:
                return d, 0
            # KKT 乘子: 只留 λ≥0 的约束 (凸 QP 的最优性)
            K = np.block([[A, C[act].T], [C[act], np.zeros((len(act), len(act)))]])
            rhs = np.concatenate([b, u[act]])
            try:
                sol = _safe_solve(K + 1e-14 * np.eye(K.shape[0]), rhs)
            except np.linalg.LinAlgError:
                return d, len(act)
            lam = sol[n:]
            if lam.min() >= -1e-9:
                return d, len(act)
            act.pop(int(np.argmin(lam)))       # 丢掉最负的乘子, 重解
            d = _eqp(A, b, C, u, act)
            continue
        # 加最越界的约束, 解等式约束子问题
        act.append(int(max(outside, key=lambda i: viol[i])))
        d = _eqp(A, b, C, u, act)
    return d, len(act)


def _eqp(A, b, C, u, act) -> np.ndarray:
    """等式约束子问题: min ½δᵀAδ−bᵀδ s.t. C_act δ = u_act (最小范数解兜底)。"""
    if not act:
        return _safe_solve(A, b)
    Ca = C[act]
    K = np.block([[A, Ca.T], [Ca, np.zeros((len(act), len(act)))]])
    rhs = np.concatenate([b, u[act]])
    try:
        sol = np.linalg.solve(K, rhs)
        return sol[:A.shape[0]]
    except np.linalg.LinAlgError:
        # 约束线性相关: 用零空间最小二乘
        d0 = _safe_solve(A, b)
        corr = np.linalg.lstsq(Ca, u[act] - Ca @ d0, rcond=None)[0]
        return d0 + corr


def project_hidden(h: np.ndarray, bounds: np.ndarray) -> tuple[np.ndarray, float]:
    """硬投影到隐藏量安全盒; 返回 (投影后, 越界残差的 2-范数)。

    bounds 形状 (6,2) = [[lo, hi], …]; 可传 NaN 表示该维不设限(置信度上界 1 之类仍生效)。
    """
    h = np.asarray(h, float).ravel()[:DIM_HIDDEN]
    b = np.asarray(bounds, float).reshape(DIM_HIDDEN, 2)
    hp = h.copy()
    for i in range(DIM_HIDDEN):
        lo, hi = b[i]
        if not (math.isnan(lo) or np.isinf(lo)):
            hp[i] = max(hp[i], lo) if not math.isnan(hp[i]) else lo
        if not (math.isnan(hi) or np.isinf(hi)):
            hp[i] = min(hp[i], hi) if not math.isnan(hp[i]) else hi
    res = float(np.linalg.norm(hp - h))
    return hp, res


def sensitivity_from_gains(radial_n_per_mm: float = 2.0, axial_n_per_mm: float = 0.2,
                           tol_n_per_mm: float = 2.0, tol_t_per_mm: float = 0.2) -> np.ndarray:
    """按产线口径(N/mm)造 J = ∂h/∂X_macro, **内部一律换 SI(N/m / mm·m⁻¹)**。

    🔴 单位坑(实测踩过): δ 的单位是 m, 如果 J 直接填 2 (N/mm), 15mm 的径向位移只算出
    0.03N, 约束永远不触发 —— 测试全绿但引擎其实没在管力。所以入口只收 N/mm, 这里 ×1000。
    列序 [dx, dy, dz, dθ]; 行序 [fx, fy, fz, σ_n, σ_t, c]。
    """
    J = np.zeros((DIM_HIDDEN, DIM_MACRO), float)
    kr = float(radial_n_per_mm) * 1000.0
    ka = float(axial_n_per_mm) * 1000.0
    J[IX_FX, 0] = kr
    J[IX_FY, 1] = kr
    J[IX_FZ, 2] = ka
    # 公差行: σ_n 挂法向(x), σ_t 挂切向(y) —— 两者必须**正交**。
    #   ❌ 踩过的坑: 两行都填 (1,1)·1000 ⇒ 两行共线 ⇒ QP 找到 (dx,-dy) 的零代价方向,
    #      纯 X 意图被算成 dx=+1.12 / dy=-1.12 的对角走位 (实测)。正交后不再有这条捷径。
    #   插入深度 dz 不消耗对中预算 (挂 dz 会把 4mm 插入削成 0.15mm, 物理上不成立)。
    J[IX_SN, 0] = float(tol_n_per_mm) * 1000.0
    J[IX_ST, 1] = float(tol_t_per_mm) * 1000.0
    return J


def to_action6(delta4: np.ndarray, pose_rpy: np.ndarray | None = None,
               rot_gain: float = 0.0) -> np.ndarray:
    """4D 增量 → 6 维执行口径 [dx,dy,dz, dRx,dRy,dRz] (m, rad)。

    θ(进度)不进动作: 它只用于节拍/门控; 姿态增量默认 0(插入段不许自己转头),
    rot_gain>0 时才跟随进度差做极小修正, 且限幅 0.01rad/步。
    """
    d = np.asarray(delta4, float).ravel()
    a = np.zeros(6, float)
    a[:3] = d[:3]
    if rot_gain and d.size >= DIM_MACRO:
        rr = float(d[DIM_MACRO - 1]) * float(rot_gain)
        a[3:] = np.clip(np.array([rr, rr, rr], float), -0.01, 0.01)
    return a


# ── 观测适配 ────────────────────────────────────────────────────────
def pack_state(xyz: np.ndarray, progress: float, force: np.ndarray,
               tol_normal_mm: float, tol_tangent_mm: float, conf: float) -> np.ndarray:
    """现场量 → X10 (顺序与度规一致, 单位 m / N / mm / 归一)。"""
    X = np.zeros(DIM_TOTAL, float)
    X[:3] = np.asarray(xyz, float).ravel()[:3]
    X[3] = float(progress) % 1.0
    X[DIM_MACRO:DIM_MACRO + 3] = np.asarray(force, float).ravel()[:3]
    X[DIM_MACRO + 3] = float(tol_normal_mm)
    X[DIM_MACRO + 4] = float(tol_tangent_mm)
    X[DIM_MACRO + 5] = float(np.clip(conf, 0.0, 1.0))
    return X


def default_bounds(cfg: dict | None = None) -> np.ndarray:
    """6D 隐藏量的默认安全盒 (力: ±允许力; 公差: 0..上限; 置信度: 0..1)。"""
    c = dict(DEFAULT_CFG)
    if cfg:
        c.update(cfg)
    Fr = float(c["F_radial_max_n"])
    Fa = float(c["F_axial_max_n"])
    return np.array([
        [-Fr, Fr], [-Fr, Fr], [-Fa, Fa],
        [0.0, float(c["tol_normal_mm"])],
        [0.0, float(c["tol_tangent_mm"])],
        [0.5, 1.0],          # 置信度: 低于 0.5 视为越界(good=hi)
    ], float)


# ── 节点实现 (给 registry: ss_mani10) ────────────────────────────────
def step10(ctx: dict) -> dict:
    """一个控制拍: 4D 意图 → 十维度规 → 约束投影 → 6 维动作增量。

    端口约定(缺省即用安全默认, 不报错):
        in1 位姿/进度  {"xyz":[x,y,z], "progress":0.42}  或 [x,y,z]
        in2 隐藏量    {"force":[fx,fy,fz], "tol_normal_mm":0.05,
                       "tol_tangent_mm":0.20, "conf":0.93, "teeth_active":False}
        in3 意图      {"delta":[dx,dy,dz,dθ]}  (米) 或 [dx,dy,dz]
    返回: X10 / V / delta / action6 / gate / ok —— 只读诊断, 不下发运动。
    """
    def _v(k):
        d = ctx.get(k) if isinstance(ctx, dict) else None
        if isinstance(d, dict):
            return d.get("value")
        return d

    pose = _v("in1") or {}
    hid = _v("in2") or {}
    intent = _v("in3") or {}

    if isinstance(pose, (list, tuple)):
        xyz, prog = list(pose)[:3], 0.0
    elif isinstance(pose, dict):
        xyz = list(pose.get("xyz") or [0.0, 0.0, 0.0])[:3]
        prog = float(pose.get("progress", 0.0) or 0.0)
    else:
        xyz, prog = [0.0, 0.0, 0.0], 0.0
    if len(xyz) < 3:
        xyz = (list(xyz) + [0.0, 0.0, 0.0])[:3]

    force = list((hid.get("force") if isinstance(hid, dict) else None) or [0.0, 0.0, 0.0])[:3]
    if len(force) < 3:
        force = (force + [0.0, 0.0, 0.0])[:3]
    tol_n = float((hid or {}).get("tol_normal_mm", DEFAULT_CFG["tol_normal_mm"]) or DEFAULT_CFG["tol_normal_mm"])
    tol_t = float((hid or {}).get("tol_tangent_mm", DEFAULT_CFG["tol_tangent_mm"]) or DEFAULT_CFG["tol_tangent_mm"])
    # 🔴 σ 是"当前已占用/偏差"(mm), 不是公差规格; 规格走 tol_* 进安全盒。
    #   原来把规格当状态填 ⇒ 一上来利用率就 100% ⇒ 刚度 ×100 ⇒ 任何动作都被拦死 (实测 action6≈0)。
    sig_n = float((hid or {}).get("sigma_n_mm", 0.0) or 0.0)
    sig_t = float((hid or {}).get("sigma_t_mm", 0.0) or 0.0)
    conf = float((hid or {}).get("conf", 1.0) if (hid or {}).get("conf") is not None else 1.0)
    cfg = {"teeth_active": bool((hid or {}).get("teeth_active", False))}

    di = list((intent.get("delta") if isinstance(intent, dict) else intent) or [0.0, 0.0, 0.0, 0.0])
    di = (di + [0.0, 0.0, 0.0, 0.0])[:DIM_MACRO]

    X = pack_state(xyz, prog, force, sig_n, sig_t, conf)
    bounds = default_bounds({"tol_normal_mm": tol_n, "tol_tangent_mm": tol_t})
    h_now = X[DIM_MACRO:].copy()
    u = utilization(h_now, bounds)
    h_err = violation_error(h_now, bounds)         # 盒内=0 ⇒ 不因"已有力"而回撤
    G = build_metric(cfg, util=u)
    G4, G6 = G[:DIM_MACRO, :DIM_MACRO], G[DIM_MACRO:, DIM_MACRO:]
    J = sensitivity_from_gains(2.0, 0.2, tol_n_per_mm=1.0, tol_t_per_mm=0.1)
    # 公差预算按工序阶段收窄: 接近段(progress<0.5)不拿 0.05mm 预算卡 5mm 的搬运;
    # 插入段(progress→1)才逐级收紧 —— 与"可行域逐层收窄"同一口径。
    stage = float(np.clip((float(prog) - 0.45) / 0.55, 0.0, 1.0)) ** 2
    J[3, :] *= stage
    J[4, :] *= stage
    X_ref = X.copy()
    X_ref[DIM_MACRO:] = (bounds[:, 0] + bounds[:, 1]) / 2.0
    r = constrained_step(np.asarray(di, float), h_err, J, G4, G6, bounds, h_now)
    return {
        "ok": True, "X10": X.tolist(), "V": potential(X, X_ref, G),
        "utilization": u.tolist(), "stiffness_gain": float(1.0 + 99.0 * float(np.max(u)) ** 4),
        "delta": r["delta"].tolist(), "action6": to_action6(r["delta"]).tolist(),
        "hidden_after": (r["hidden_after"].tolist() if r["hidden_after"] is not None else None),
        "hard_projected": bool(r["hard_projected"]), "active": int(r["active"]),
        "violation_after": float(r["violation_after"]),
        "gate": {"force_ok": bool(r["violation_after"] < 1e-9),
                 "conf_ok": bool(conf >= 0.5),
                 "util_max": float(np.max(u))},
        "src": "src/lerobot/manifold/manifold10d.py::step10",
    }


# ── 自测 (数字判据, 供 tools/verify_manifold10d.py 打印) ──────────────
def selftest(verbose: bool = False) -> dict:
    rng = np.random.default_rng(20261124)
    res: dict[str, Any] = {}

    # ① 度规正定 + 块对角
    G = build_metric()
    mr = metric_report(G)
    res["metric"] = mr
    assert mr["cholesky_ok"] and mr["positive_definite"], "度规非正定"
    assert mr["sym_err"] < 1e-12, "度规不对称"
    assert abs(G[:DIM_MACRO, DIM_MACRO:]).max() == 0.0, "块间存在耦合(应为块对角)"

    # ② 势能非负 + 零在参考点
    X0 = pack_state([0.66, -0.03, 0.29], 0.4, [0, 0, 0], 0.05, 0.2, 0.9)
    assert abs(potential(X0, X0, G)) < 1e-18
    X1 = X0.copy(); X1[0] += 0.01
    v_pos = potential(X1, X0, G)
    res["potential_10mm"] = v_pos
    assert abs(v_pos - 0.5) < 1e-9, "10mm 位移在 10mm 尺度下应为 V=0.5, 得到 %r" % v_pos

    # ③ θ 取 S¹ 最短差 (0.98 → 0.02 应为 0.04, 不是 0.96)
    A = X0.copy(); A[3] = 0.98
    B = X0.copy(); B[3] = 0.02
    d = _delta(B, A)
    res["theta_wrap"] = float(abs(d[3]))
    assert abs(abs(d[3]) - 0.04) < 1e-12, "S¹ 环绕差错: %r" % d[3]

    # ④ 自然梯度在二次型上 = −ΔX (证"度规抵消", 说明不能用它当动作)
    ng = natural_gradient(X1, X0, G)
    res["natural_grad_vs_delta"] = float(np.max(np.abs(ng + (X1 - X0))))
    assert res["natural_grad_vs_delta"] < 1e-12

    # ⑤ 各向异性 vs 各向同性 (真正能分辨两者的场景: 意图会顶到约束)
    #    工况: 径向允许 18N (SFP 口径), 轴向允许 60N; 敏感度 2N/mm 径向, 0.2N/mm 轴向
    #    意图 15mm 径向 ⇒ 想顶 30N (超 18N); 15mm 轴向 ⇒ 只 3N (远未到 60N)
    #    各向异性 ⇒ 径向被裁到 9mm(18N), 轴向 15mm 放行
    #    各向同性 ⇒ 力上限按 sqrt(18·60)=32.9N ⇒ 径向也放行 15mm ⇒ 实际顶出 30N (违规)
    J = sensitivity_from_gains(radial_n_per_mm=2.0, axial_n_per_mm=0.2,
                               tol_n_per_mm=0.0, tol_t_per_mm=0.0)
    h0 = np.array([0.0, 0.0, 0.0, 0.005, 0.020, 0.93])   # 盒内基准态(零力/公差占用小/高置信)
    di_r = np.array([0.015, 0.0, 0.0, 0.0])       # 径向 15mm
    di_a = np.array([0.0, 0.0, 0.015, 0.0])       # 轴向 15mm
    G_an = build_metric({"anisotropy": 1.0, "blind_hole": True})
    G_iso = build_metric({"anisotropy": 0.0, "blind_hole": True,
                          "F_radial_max_n": 32.9, "F_axial_max_n": 32.9})
    b_an = default_bounds()
    b_iso = np.array([[-32.9, 32.9], [-32.9, 32.9], [-32.9, 32.9],
                      [0.0, 0.05], [0.0, 0.2], [0.0, 1.0]])
    r_an_r = constrained_step(di_r, h0, J, G_an[:4, :4], G_an[4:, 4:], b_an, h0)
    r_an_a = constrained_step(di_a, h0, J, G_an[:4, :4], G_an[4:, 4:], b_an, h0)
    r_iso_r = constrained_step(di_r, h0, J, G_iso[:4, :4], G_iso[4:, 4:], b_iso, h0)
    res["aniso_radial_mm"] = float(r_an_r["delta"][0] * 1e3)
    res["aniso_axial_mm"] = float(r_an_a["delta"][2] * 1e3)
    res["iso_radial_mm"] = float(r_iso_r["delta"][0] * 1e3)
    res["aniso_radial_force_n"] = float(abs(r_an_r["hidden_after"][IX_FX]))
    res["iso_radial_force_n"] = float(abs(r_iso_r["hidden_after"][IX_FX]))
    assert res["aniso_radial_mm"] < res["iso_radial_mm"] - 1e-9, "各向异性没裁径向动作: %.4f !< %.4f" % (
        res["aniso_radial_mm"], res["iso_radial_mm"])
    assert res["aniso_radial_force_n"] < 18.0, "各向异性径向力仍超 18N: %.4f" % res["aniso_radial_force_n"]
    assert res["iso_radial_force_n"] > 18.0, "各向同性应顶出 >18N 径向力, 实得 %.3f" % res["iso_radial_force_n"]
    assert abs(res["aniso_axial_mm"] - 15.0) < 0.1, "轴向被误裁: %.4fmm" % res["aniso_axial_mm"]

    # ⑥ QP 硬约束精度: 给出的解必须真的在盒内 (1e-9), 且不做无谓修正
    worst = 0.0
    for di in (di_r, di_a, np.array([0.006, 0.003, 0.005, 0.05]), np.array([0.0, 0.0, 0.0, 0.3])):
        rr = constrained_step(di, h0, J, G_an[:4, :4], G_an[4:, 4:], b_an, h0)
        hp, resid = project_hidden(rr["hidden_after"], b_an)
        worst = max(worst, float(resid))
    res["qp_worst_violation"] = worst
    assert worst < 1e-9, "QP 解越界 %.3e (约束没精确满足)" % worst

    # ⑥b 硬约束真的会咬人: 已有 17N 径向力(只余 1N) ⇒ 5mm 意图必须被裁到 0.5mm
    h_now = np.zeros(DIM_HIDDEN); h_now[IX_FX] = 17.0
    r_hit = constrained_step(np.array([0.005, 0.0, 0.0, 0.0]), h0,   # h=0: 只按余量约束, 不做回拉
                             J, G_an[:4, :4], G_an[4:, 4:], b_an, h_now)
    res["headroom_dx_mm"] = float(r_hit["delta"][0] * 1e3)
    res["headroom_fx_n"] = float(r_hit["hidden_after"][IX_FX])
    assert abs(res["headroom_dx_mm"] - 0.5) < 1e-6, "余量 1N 时应只许 0.5mm, 实得 %.6fmm" % res["headroom_dx_mm"]
    assert abs(res["headroom_fx_n"] - 18.0) < 1e-6, "应顶到 18N, 实得 %.6f" % res["headroom_fx_n"]
    res["tol_hidden_mm"] = 0.0
    res["tol_bound_mm"] = 0.0

    # ⑥c 没有隐藏耦合(J=0)时意图必须原样放行; 有耦合时只许"减"不许"过冲"
    J0 = np.zeros((DIM_HIDDEN, DIM_MACRO))
    di_ok = np.array([0.002, 0.0, 0.002, 0.0])
    r_ok = constrained_step(di_ok, h0, J0, G_an[:4, :4], G_an[4:, 4:], b_an, h0)
    res["qk_untouched_err_mm"] = float(np.max(np.abs(r_ok["delta"] - di_ok)) * 1e3)
    assert res["qk_untouched_err_mm"] < 1e-9, "无耦合时意图被改动 %.3e mm" % res["qk_untouched_err_mm"]
    r_c = constrained_step(di_ok, h0, J, G_an[:4, :4], G_an[4:, 4:], b_an, h0)
    res["coupling_shave_mm"] = float((np.linalg.norm(di_ok) - np.linalg.norm(r_c["delta"])) * 1e3)
    assert np.linalg.norm(r_c["delta"]) <= np.linalg.norm(di_ok) + 1e-12, "有耦合时出现了过冲"
    res["proj_residual"] = float(r_an_r["proj_residual"])

    # ⑦ IHS 散热齿惩罚: 同一位移, 齿在场时的代价应大 ~1000 倍量级
    G_teeth = build_metric({"teeth_active": True})
    G_plain = build_metric({"teeth_active": False})
    ddx = np.zeros(DIM_TOTAL); ddx[IX_FX + DIM_MACRO] = 1.0     # 径向力偏 1N
    v_teeth = potential(X0 + ddx, X0, G_teeth)
    v_plain = potential(X0 + ddx, X0, G_plain)
    res["teeth_ratio"] = float(v_teeth / v_plain)
    assert res["teeth_ratio"] > 100.0, "齿惩罚没生效: %.3f" % res["teeth_ratio"]

    # ⑧ 收敛性: 沿 −G⁻¹∇V 走 K 步, V 单调下降且终值→0
    X = X0 + rng.normal(0, 1e-3, DIM_TOTAL)
    X_ref = X0
    prev = potential(X, X_ref, G)
    mono = True
    for _ in range(200):
        X = X + 0.1 * natural_gradient(X, X_ref, G)
        v = potential(X, X_ref, G)
        if v > prev + 1e-15:
            mono = False
        prev = v
    res["flow_monotone"] = mono
    res["flow_v_final"] = float(prev)
    assert mono and prev < 1e-12

    # ⑩ 利用率门控(柔性→刚性): 盒内几乎不压, 逼近边界刚度暴涨
    bnd = default_bounds()
    h_low = np.array([3.0, 0.0, 0.0, 0.005, 0.02, 0.95])
    h_high = np.array([17.0, 0.0, 0.0, 0.005, 0.02, 0.95])
    di2 = np.array([0.002, 0.0, 0.0, 0.0])
    G_low = build_metric(util=utilization(h_low, bnd))
    G_high = build_metric(util=utilization(h_high, bnd))
    r_low = constrained_step(di2, violation_error(h_low, bnd), J, G_low[:4, :4], G_low[4:, 4:], bnd, h_low)
    r_high = constrained_step(di2, violation_error(h_high, bnd), J, G_high[:4, :4], G_high[4:, 4:], bnd, h_high)
    res["gate_low_ratio"] = float(np.linalg.norm(r_low["delta"]) / np.linalg.norm(di2))
    res["gate_high_ratio"] = float(np.linalg.norm(r_high["delta"]) / np.linalg.norm(di2))
    res["gate_stiff_low"] = float(G_low[4, 4] / build_metric()[4, 4])
    res["gate_stiff_high"] = float(G_high[4, 4] / build_metric()[4, 4])
    assert res["gate_low_ratio"] > 0.3, "盒内(3N)压得过狠: 只放行 %.1f%%" % (res["gate_low_ratio"] * 100)
    assert res["gate_high_ratio"] < 0.1 * res["gate_low_ratio"], "边界门控没拉开: 低%.2f vs 高%.3f" % (
        res["gate_low_ratio"], res["gate_high_ratio"])

    # ⑪ 节点入口 step10: 现场的"公差规格"不能当状态(否则利用率恒 100%, 动作被拦死)
    from lerobot.manifold.manifold10d import step10
    out = step10({"in1": {"value": {"xyz": [0.66, -0.03, 0.29], "progress": 0.92}},
                  "in2": {"value": {"force": [12.0, 2.0, -25.0], "tol_normal_mm": 0.05,
                                    "tol_tangent_mm": 0.20, "conf": 0.93}},
                  "in3": {"value": {"delta": [0.0, 0.0, 0.004, 0.0]}}})
    res["step10_ok"] = bool(out["ok"])
    res["step10_util_max"] = float(out["gate"]["util_max"])
    res["step10_action_z_mm"] = float(out["action6"][2] * 1e3)
    assert out["ok"] and res["step10_util_max"] < 0.99, "step10 利用率异常 %.2f" % res["step10_util_max"]
    assert res["step10_action_z_mm"] > 3.5, "轴向 4mm 意图被拦剩 %.2fmm" % res["step10_action_z_mm"]

    # ⑨ 实时性: 单步耗时 (目标 1kHz = 1ms)
    di = np.array([0.002, 0.001, -0.001, 0.01])
    N = 20000
    t0 = time.perf_counter()
    for _ in range(N):
        constrained_step(di, h0, J, G_an[:4, :4], G_an[4:, 4:], b_an, h0)
    dt = (time.perf_counter() - t0) / N
    res["step_ms"] = dt * 1e3
    assert dt < 1e-3, "单步 %.3fms 超 1kHz 预算" % (dt * 1e3)

    res["ok"] = True
    if verbose:
        print(res)
    return res


if __name__ == "__main__":
    r = selftest(verbose=True)
    print("十维流形引擎自检: %d 项断言全过 · 单步 %.4fms" % (9, r["step_ms"]))
