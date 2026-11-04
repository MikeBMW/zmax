#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""se3_pose_head.py — SE(3) 流形引擎的「6 维切空间预测 → 7 维位姿」内核

老倪 2026-11-04 方案: 网络**不预测 7 个数**(四元数必须 ‖q‖=1, 直接回归易崩),
只预测 6 维李代数增量 ξ ∈ se(3), 由流形引擎指数映射严谨地变成 7 维物理位姿。

    ξ = [ρ; φ]      ρ=平移 3 维, φ=旋转轴角 3 维      (方案里的分量序, 平移在前)
    T_next = T · exp(ξ^)                              (群乘法, 体坐标增量)
    pose7  = [x, y, z, qw, qx, qy, qz]

🔴 两条与仓内既有算子的口径差异, 必须显式转换 (否则静默错轴):
   · `lie_intent.se3_exp/se3_log` 用 **[ω; v]**(旋转在前), 本模块对外用 **[ρ; φ]**(平移在前)。
     换算出入口只有 `xi_rho_phi_to_repo()` / `xi_repo_to_rho_phi()` 两个函数。
   · 方案伪代码 step4 写的是「p += ρ 且 q ⊗= Δq」——那是**解耦近似**;
     严格群指数是 `t = J_l(φ)·ρ`, 平移被旋转耦合一阶项。本模块两种都给:
       mode="group"     : T' = T·exp(ξ^)        (严格, 默认)
       mode="decoupled" : p+=ρ, q⊗=Δq(φ)        (与方案伪代码逐行对应)
     两者在小 ξ 下差 O(‖ξ‖²), `self_test()` 里有这条对账。

numpy 内核 (引擎 10Hz 用, 无 torch 依赖) + torch 头 (训练用, 导出权重)。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

XI_ORDER = "rho_phi"          # 对外契约: [ρ; φ]
REPO_ORDER = "omega_v"        # lie_intent: [ω; v]


# ══════════════════════════ 分量序换算 ══════════════════════════
def xi_rho_phi_to_repo(xi) -> np.ndarray:
    """[ρ; φ] → [φ; ρ] (仓内 lie_intent 序)。"""
    x = np.asarray(xi, float).ravel()
    return np.concatenate([x[3:6], x[0:3]])


def xi_repo_to_rho_phi(x) -> np.ndarray:
    """[φ; ρ] → [ρ; φ] (本模块契约序)。"""
    x = np.asarray(x, float).ravel()
    return np.concatenate([x[3:6], x[0:3]])


# ══════════════════════════ 基础算子 (numpy) ══════════════════════════
def hat(v) -> np.ndarray:
    x, y, z = np.asarray(v, float).ravel()[:3]
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def quat_normalize(q) -> np.ndarray:
    q = np.asarray(q, float).ravel()[:4]
    n = float(np.linalg.norm(q))
    if n < 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    return q / n


def quat_mul(q1, q2) -> np.ndarray:
    """Hamilton 积 (w,x,y,z)。结果已归一化 ⇒ 更新后必在 S³ 上。"""
    w1, x1, y1, z1 = quat_normalize(q1)
    w2, x2, y2, z2 = quat_normalize(q2)
    return quat_normalize(np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2]))


def quat_from_rotvec(w) -> np.ndarray:
    w = np.asarray(w, float).ravel()[:3]
    th = float(np.linalg.norm(w))
    if th < 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    s = math.sin(th / 2.0) / th
    return quat_normalize(np.array([math.cos(th / 2.0), w[0] * s, w[1] * s, w[2] * s]))


def rotvec_from_quat(q) -> np.ndarray:
    w, x, y, z = quat_normalize(q)
    if w < 0:                                  # q 与 −q 同一旋转 ⇒ 取短弧 (θ≤π)
        w, x, y, z = -w, -x, -y, -z
    s = math.sqrt(max(0.0, 1.0 - w * w))
    if s < 1e-12:
        return np.zeros(3)
    th = 2.0 * math.atan2(s, w)
    return np.array([x, y, z]) / s * th


def R_from_quat(q) -> np.ndarray:
    w, x, y, z = quat_normalize(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def quat_from_R(R) -> np.ndarray:
    """Shepperd 分支法 (数值稳, 不除小量)。"""
    R = np.asarray(R, float).reshape(3, 3)
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s]
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s]
    return quat_normalize(q)


def so3_exp(w) -> np.ndarray:
    """Rodrigues, 含小角级数分支 (θ<1e-8 不除 0)。"""
    w = np.asarray(w, float).ravel()[:3]
    th = float(np.linalg.norm(w))
    W = hat(w)
    if th < 1e-8:
        return np.eye(3) + W + 0.5 * W @ W
    return (np.eye(3) + (math.sin(th) / th) * W + ((1.0 - math.cos(th)) / th ** 2) * W @ W)


def so3_log(R) -> np.ndarray:
    R = np.asarray(R, float).reshape(3, 3)
    c = max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))
    th = math.acos(c)
    if th < 1e-8:
        return np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) * 0.5
    if abs(math.pi - th) < 1e-6:
        # θ≈π: 从 R+I 取主轴 (log 在该点不唯一, 取一个确定分支并标注)
        A = (R + np.eye(3)) / 2.0
        i = int(np.argmax(np.diag(A)))
        v = A[:, i] / math.sqrt(max(A[i, i], 1e-12))
        v = v / (np.linalg.norm(v) or 1.0) * math.sqrt(max(A[i, i], 0.0))
        v = v / (np.linalg.norm(v) or 1.0)
        return v * th
    return (th / (2.0 * math.sin(th))) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def J_left(phi) -> np.ndarray:
    """SE(3) 左雅可比: t = J_l(φ)·ρ。"""
    phi = np.asarray(phi, float).ravel()[:3]
    th = float(np.linalg.norm(phi))
    P = hat(phi)
    if th < 1e-6:
        return np.eye(3) + 0.5 * P + (1.0 / 6.0) * P @ P
    return (np.eye(3) + ((1.0 - math.cos(th)) / th ** 2) * P
            + ((th - math.sin(th)) / th ** 3) * P @ P)


def J_left_inv(phi) -> np.ndarray:
    phi = np.asarray(phi, float).ravel()[:3]
    th = float(np.linalg.norm(phi))
    P = hat(phi)
    if th < 1e-6:
        return np.eye(3) - 0.5 * P + (1.0 / 12.0) * P @ P
    c = (1.0 + math.cos(th)) / (2.0 * th * math.sin(th))
    return np.eye(3) - 0.5 * P + (1.0 / th ** 2 - c) * P @ P


# ══════════════════════════ SE(3) exp/log ══════════════════════════
def exp_se3(xi) -> np.ndarray:
    """[ρ; φ] → 4×4。平移走 J_l(φ)·ρ (严格群指数, 不是 ρ)。"""
    x = np.asarray(xi, float).ravel()[:6]
    rho, phi = x[:3], x[3:]
    T = np.eye(4)
    T[:3, :3] = so3_exp(phi)
    T[:3, 3] = J_left(phi) @ rho
    return T


def log_se3(T) -> np.ndarray:
    """4×4 → [ρ; φ]。"""
    T = np.asarray(T, float).reshape(4, 4)
    phi = so3_log(T[:3, :3])
    rho = J_left_inv(phi) @ T[:3, 3]
    return np.concatenate([rho, phi])


# ══════════════════════════ 7 维位姿 ↔ 4×4 ══════════════════════════
def pose7_to_T(pose7) -> np.ndarray:
    p = np.asarray(pose7, float).ravel()[:7]
    T = np.eye(4)
    T[:3, :3] = R_from_quat(p[3:7])
    T[:3, 3] = p[:3]
    return T


def T_to_pose7(T) -> np.ndarray:
    T = np.asarray(T, float).reshape(4, 4)
    return np.concatenate([T[:3, 3], quat_from_R(T[:3, :3])])


def step_pose(pose7, xi, mode: str = "group") -> np.ndarray:
    """Pose7 + 6 维增量 → Pose7 (严格按当前 mode)。

    group     : T' = T·exp(ξ^)   (体坐标增量; 严格 SE(3), 默认)
    decoupled : p+=ρ, q⊗=Δq(φ)   (方案伪代码 step4 的近似写法)
    """
    x = np.asarray(xi, float).ravel()[:6]
    p = np.asarray(pose7, float).ravel()[:7]
    rho, phi = x[:3], x[3:]
    q_delta = quat_from_rotvec(phi)
    q_new = quat_mul(p[3:7], q_delta)                  # 四元数直接复合 ⇒ ‖q‖ 恒 1 (不经过矩阵求逆)
    if mode == "decoupled":
        return np.concatenate([p[:3] + rho, q_new])
    # 严格群: t' = t + R(q)·(J_l(φ)·ρ)
    R = R_from_quat(p[3:7])
    return np.concatenate([p[:3] + R @ (J_left(phi) @ rho), q_new])


def pose_distance(pose7_a, pose7_b) -> dict:
    """测地线误差 (完整口径, 分别给旋转角/平移, 再给带权合量)。

    · rot_rad   : θ = ‖log(R_aᵀ R_b)‖ ∈ [0, π]        —— S³ 上的测地线
    · trans_m   : ‖t_b − t_a‖                          —— R³ 欧氏
    · se3       : 左不变度规加权合量 (默认 w_rot=0.5 m/rad, 便于单标量看趋势)
    """
    Ta, Tb = pose7_to_T(pose7_a), pose7_to_T(pose7_b)
    dT = np.linalg.inv(Ta) @ Tb
    rot = float(np.linalg.norm(so3_log(dT[:3, :3])))
    trans = float(np.linalg.norm(dT[:3, 3]))
    return {"rot_rad": rot, "rot_deg": math.degrees(rot), "trans_m": trans,
            "se3": float(math.hypot(rot * 0.5, trans))}


# ══════════════════════════ torch 头 (训练用) ══════════════════════════
def _torch():
    try:
        import torch  # noqa: F401
        return __import__("torch")
    except Exception:                                                        # noqa: BLE001
        return None


def build_head(latent_dim: int = 16, hidden: int = 128, max_trans: float = 0.02,
               max_rot: float = 0.20, torch=None):
    """SE(3) 预测头: z → 6 维 ξ (有界, 单位: m / rad)。输出层 tanh 限幅 = 物理护栏。"""
    th = torch or _torch()
    if th is None:
        raise RuntimeError("没有 torch ⇒ 只能跑 numpy 内核, 不能训练")
    nn = th.nn

    class SE3PoseHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.max_trans = float(max_trans)
            self.max_rot = float(max_rot)
            self.net = nn.Sequential(
                nn.Linear(latent_dim, hidden), nn.GELU(),
                nn.Linear(hidden, hidden), nn.GELU(),
                nn.Linear(hidden, 6))

        def forward(self, z):
            out = th.tanh(self.net(z))
            scale = th.tensor([self.max_trans] * 3 + [self.max_rot] * 3,
                              dtype=out.dtype, device=out.device)
            return out * scale                    # ξ = [ρ; φ], 有界

        def predict_pose(self, z, pose7):
            """6 维 ξ → 7 维位姿 (可微, group 模式)。这就是"网络绝不直接吐 7 数"的落点。"""
            return torch_step_pose(pose7, self.forward(z))

    return SE3PoseHead()


def torch_step_pose(pose7, xi, eps: float = 1e-6):
    """可微版群更新: pose7_next = pose7 ⊗ exp(ξ^) (group 模式, 与 numpy 逐位同公式)。

    pose7: [B,7] = [x,y,z,qw,qx,qy,qz];  xi: [B,6] = [ρ; φ]
    """
    _t = _torch()
    p, q = pose7[:, :3], pose7[:, 3:7]
    q = q / (q.norm(dim=-1, keepdim=True) + 1e-9)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    R = _t.stack([
        _t.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        _t.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        _t.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1)], -2)
    rho, phi = xi[:, :3], xi[:, 3:6]
    th = phi.norm(dim=-1, keepdim=True).clamp_min(eps)          # [B,1]
    K = _t.zeros(phi.shape[0], 3, 3, dtype=phi.dtype, device=phi.device)
    K[:, 0, 1], K[:, 0, 2] = -phi[:, 2], phi[:, 1]
    K[:, 1, 0], K[:, 1, 2] = phi[:, 2], -phi[:, 0]
    K[:, 2, 0], K[:, 2, 1] = -phi[:, 1], phi[:, 0]
    K2 = K @ K
    # so3_exp 与 J_l 的级数 (θ→0 也稳, 不做分支)
    a = (_t.sin(th) / th).unsqueeze(-1)
    b = ((1 - _t.cos(th)) / th ** 2).unsqueeze(-1)
    Rd = _t.eye(3, dtype=phi.dtype, device=phi.device).expand(phi.shape[0], 3, 3) + a * K + b * K2
    c = ((1 - _t.cos(th)) / th ** 2).unsqueeze(-1)
    d = ((th - _t.sin(th)) / th ** 3).unsqueeze(-1)
    Jl = _t.eye(3, dtype=phi.dtype, device=phi.device).expand(phi.shape[0], 3, 3) + c * K + d * K2
    t_delta = (Jl @ rho.unsqueeze(-1)).squeeze(-1)
    t_new = p + (R @ t_delta.unsqueeze(-1)).squeeze(-1)
    # 四元数直接复合 (q ⊗ Δq): 数值稳, 且 ‖q_new‖≡1 —— 不走 R→q 的反解 (那条在 tr≈−1 处分母趋 0)
    th2 = (th * 0.5)
    s_ = _t.sin(th2) / th
    qd = _t.stack([_t.cos(th2).squeeze(-1), phi[:, 0] * s_.squeeze(-1),
                   phi[:, 1] * s_.squeeze(-1), phi[:, 2] * s_.squeeze(-1)], -1)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    w2, x2, y2, z2 = qd[:, 0], qd[:, 1], qd[:, 2], qd[:, 3]
    q_new = _t.stack([w * w2 - x * x2 - y * y2 - z * z2,
                      w * x2 + x * w2 + y * z2 - z * y2,
                      w * y2 - x * z2 + y * w2 + z * x2,
                      w * z2 + x * y2 - y * x2 + z * w2], -1)
    q_new = q_new / (q_new.norm(dim=-1, keepdim=True) + 1e-9)
    return _t.cat([t_new, q_new], dim=-1)


def _quat_from_R_torch(R):
    """可微四元数 (Shepperd 分支, 用 where 组分支; 归一化在末端统一做)。"""
    _t = _torch()
    m00, m01, m02 = R[:, 0, 0], R[:, 0, 1], R[:, 0, 2]
    m10, m11, m12 = R[:, 1, 0], R[:, 1, 1], R[:, 1, 2]
    m20, m21, m22 = R[:, 2, 0], R[:, 2, 1], R[:, 2, 2]
    tr = m00 + m11 + m22
    s0 = _t.sqrt(_t.clamp(tr + 1.0, min=1e-12)) * 2
    q0 = _t.stack([0.25 * s0, (m21 - m12) / s0, (m02 - m20) / s0, (m10 - m01) / s0], -1)
    s1 = _t.sqrt(_t.clamp(1.0 + m00 - m11 - m22, min=1e-12)) * 2
    q1 = _t.stack([(m21 - m12) / s1, 0.25 * s1, (m01 + m10) / s1, (m02 + m20) / s1], -1)
    s2 = _t.sqrt(_t.clamp(1.0 + m11 - m00 - m22, min=1e-12)) * 2
    q2 = _t.stack([(m02 - m20) / s2, (m01 + m10) / s2, 0.25 * s2, (m12 + m21) / s2], -1)
    s3 = _t.sqrt(_t.clamp(1.0 + m22 - m00 - m11, min=1e-12)) * 2
    q3 = _t.stack([(m10 - m01) / s3, (m02 + m20) / s3, (m12 + m21) / s3, 0.25 * s3], -1)
    cond1 = (m00 > m11) & (m00 > m22)
    cond2 = m11 > m22
    q = _t.where((tr > 0).unsqueeze(-1), q0,
                 _t.where(cond1.unsqueeze(-1), q1, _t.where(cond2.unsqueeze(-1), q2, q3)))
    return q / (q.norm(dim=-1, keepdim=True) + 1e-9)


def geodesic_loss(pred7, true7, w_rot: float = 0.5, w_trans: float = 1.0):
    """SE(3) 测地线损失 (可反传): 旋转用 log(R_pᵀR_t) 的角, 平移用欧氏距离。

    🔴 不用四元数逐元素差: q 与 −q 是同一旋转, 逐元素差会把"同一个姿态"罚成大误差。
    """
    _t = _torch()
    qp, qt = pred7[:, 3:7], true7[:, 3:7]
    # 归一化 (头输出不做归一, 这里强制投回 S³)
    qp = qp / (qp.norm(dim=-1, keepdim=True) + 1e-9)
    qt = qt / (qt.norm(dim=-1, keepdim=True) + 1e-9)
    # 🔴 不能用 acos(⟨q_p,q_t⟩): 预测≈真值时内积→1, acos 的导数在 1 处发散 ⇒ 训练第 1 步就 NaN。
    #   用 q_p⁻¹⊗q_t 的 atan2 形式: θ = 2·atan2(‖v‖, |w|), 全程有限且导数有界。
    cw, cx, cy, cz = qp[:, 0], -qp[:, 1], -qp[:, 2], -qp[:, 3]        # 共轭
    tw, tx, ty, tz = qt[:, 0], qt[:, 1], qt[:, 2], qt[:, 3]
    rw = cw * tw - cx * tx - cy * ty - cz * tz
    rx = cw * tx + cx * tw + cy * tz - cz * ty
    ry = cw * ty - cx * tz + cy * tw + cz * tx
    rz = cw * tz + cx * ty - cy * tx + cz * tw
    vnorm = _t.sqrt(rx * rx + ry * ry + rz * rz + 1e-18)
    rot = 2.0 * _t.atan2(vnorm, rw.abs().clamp_min(1e-12))            # ∈ [0, π]
    trans = (pred7[:, :3] - true7[:, :3]).norm(dim=-1)
    return (w_rot * rot + w_trans * trans).mean(), {"rot_rad": rot.detach(), "trans_m": trans.detach()}


# ══════════════════════════ 自检 (数学正确性) ══════════════════════════
def self_test(verbose: bool = True) -> dict:
    rng = np.random.default_rng(20261104)
    res: dict[str, Any] = {}
    say = print if verbose else (lambda *a, **k: None)

    # ① exp/log 往返 —— 只在 log 的**唯一分支**内比数值: ‖φ‖<π 时 log(exp(ξ)) 必须逐位回到 ξ。
    #    (‖φ‖>π 时 exp 会绕圈, log 只能给出等价的最小角表示, 那样的"往返失败"是数学事实, 不是 bug;
    #     下面 ①b 单独验这个绕圈情形: 位姿必须一致, 6 维向量允许不同。)
    e1 = 0.0
    for _ in range(400):
        phi = rng.normal(size=3)
        phi = phi / (np.linalg.norm(phi) or 1.0) * rng.uniform(0.0, 3.0)     # ‖φ‖ < π
        xi = np.concatenate([rng.normal(size=3) * 0.05, phi])
        e1 = max(e1, float(np.abs(log_se3(exp_se3(xi)) - xi).max()))
    res["exp_log_roundtrip_max"] = e1

    # ①b 大角绕圈: ‖φ‖=5rad ⇒ 6 维不唯一, 但 exp(log(exp(ξ))) 必须回到同一个 T
    e2 = 0.0
    for _ in range(100):
        xi = np.concatenate([rng.normal(size=3), rng.normal(size=3) / 1.7 * 5.0])
        T1 = exp_se3(xi)
        T2 = exp_se3(log_se3(T1))
        e2 = max(e2, float(np.abs(T1 - T2).max()))
    res["exp_log_wrap_pose_err"] = e2
    res["wrap_note"] = "‖φ‖>π 时 6 维表示不唯一, 以 4×4 位姿为准"

    # ② 纯平移 / 纯旋转解析值
    t = exp_se3([0.5, 0, 0, 0, 0, 0])
    res["pure_trans_x"] = float(t[0, 3])
    r = exp_se3([0, 0, 0, 0, 0, math.pi / 6])
    res["pure_rot30_angle_deg"] = float(math.degrees(np.linalg.norm(so3_log(r[:3, :3]))))

    # ③ 四元数更新后必在 S³ 上 (10000 步连续大角旋转, 含 >360°)
    q = np.array([1.0, 0, 0, 0])
    worst = 0.0
    for i in range(10000):
        q = quat_mul(q, quat_from_rotvec([0.0, 0.0, 0.13]))   # 每步 7.45°, 累计 ~745°
        worst = max(worst, abs(float(np.linalg.norm(q)) - 1.0))
    res["quat_norm_drift_10k"] = worst
    res["quat_total_turn_deg"] = round(math.degrees(10000 * 0.13), 1)

    # ④ 群 vs 解耦 两种更新: 小增量差 O(‖ξ‖²)
    d_small = d_big = 0.0
    for _ in range(200):
        p7 = np.concatenate([rng.normal(size=3) * 0.3, quat_from_rotvec(rng.normal(size=3))])
        xi = np.concatenate([rng.normal(size=3) * 1e-4, rng.normal(size=3) * 1e-3])
        a = step_pose(p7, xi, "group")
        b = step_pose(p7, xi, "decoupled")
        d_small = max(d_small, float(np.linalg.norm(a - b)))
        xi2 = np.concatenate([rng.normal(size=3) * 0.01, rng.normal(size=3) * 0.1])
        d_big = max(d_big, float(np.linalg.norm(step_pose(p7, xi2, "group") - step_pose(p7, xi2, "decoupled"))))
    res["group_vs_decoupled_small"] = d_small      # 应 ≪ 1
    res["group_vs_decoupled_big"] = d_big          # 应明显更大 (证明耦合项真的在起作用)

    # ⑤ 测地线误差: 同一姿态=0; 对 q/−q 不敏感; 左不变 (整体刚体变换后距离不变)
    p7 = np.concatenate([np.array([0.1, 0.2, 0.3]), quat_from_rotvec([0.2, -0.1, 0.05])])
    res["dist_self"] = pose_distance(p7, p7)["se3"]
    res["dist_q_neg"] = pose_distance(p7, np.concatenate([p7[:3], -p7[3:]]))["se3"]
    G = exp_se3([0.3, -0.2, 0.1, 0.4, 0.1, -0.2])
    q7 = step_pose(np.concatenate([np.array([0.5, 0, 0.1]), quat_from_rotvec([0, 0.3, 0])]),
                   np.array([0.01, 0.02, -0.03, 0.05, 0.02, 0.01]))
    d0 = pose_distance(p7, q7)["se3"]
    d1 = pose_distance(T_to_pose7(G @ pose7_to_T(p7)), T_to_pose7(G @ pose7_to_T(q7)))["se3"]
    res["left_invariance_err"] = abs(d0 - d1)

    # ⑥ 分量序换算往返
    xi = np.arange(1.0, 7.0)
    res["order_roundtrip"] = float(np.abs(xi_repo_to_rho_phi(xi_rho_phi_to_repo(xi)) - xi).max())
    res["order_map_std"] = xi_rho_phi_to_repo(xi).tolist()   # [1,2,3,4,5,6] → [4,5,6,1,2,3]

    # ⑦ torch: 头输出有界 + 损失可反传 + numpy/torch 一致
    th = _torch()
    if th is None:
        res["torch"] = "未安装"
    else:
        head = build_head(latent_dim=16, hidden=32, torch=th)
        z = th.randn(8, 16)
        xi_t = head(z)
        res["head_out_dim"] = int(xi_t.shape[-1])
        true7 = th.tensor(np.array([p7] * 8), dtype=th.float32)
        pose7_t = th.tensor(np.array([p7] * 8), dtype=th.float32)
        pred7 = head.predict_pose(z, pose7_t)          # 6 维 → 7 维, 梯度过流形
        loss, parts = geodesic_loss(pred7, true7)
        loss_same, _ = geodesic_loss(pose7_t, true7)   # 预测=真值 ⇒ 损失必须为 0
        loss.backward()
        g = sum(float(p.grad.abs().sum()) for p in head.parameters() if p.grad is not None)
        res["loss_at_same_pose"] = float(loss_same)
        res["grad_flows"] = g > 0
        res["loss_head"] = round(float(loss), 6)
        # 数值一致性: numpy step_pose vs torch 公式 (同一 ξ)
        xi_np = np.array([0.003, -0.002, 0.004, 0.02, -0.01, 0.03])
        a = step_pose(p7, xi_np, "group")
        b = T_to_pose7(pose7_to_T(p7) @ exp_se3(xi_np))
        res["numpy_step_consistency"] = float(np.abs(a - b).max())
        res["head_bound_ok"] = bool(float(xi_t.abs().max()) <= 0.21)
        # ⑧ torch 群更新 vs numpy 群更新 逐位一致 (同一个 ξ, 同一初值)
        xi_tn = th.tensor(np.array([xi_np]), dtype=th.float64)
        p7_t = th.tensor(np.array([p7]), dtype=th.float64)
        res["torch_vs_numpy_step"] = float(np.abs(
            torch_step_pose(p7_t, xi_tn).detach().numpy()[0] - a).max())
        res["torch_step_ok"] = bool(res["torch_vs_numpy_step"] < 1e-8)

    ok = (res["exp_log_roundtrip_max"] < 1e-9
          and abs(res["quat_norm_drift_10k"]) < 1e-12
          and res["group_vs_decoupled_small"] < res["group_vs_decoupled_big"]
          and res["dist_self"] < 1e-12 and res["dist_q_neg"] < 1e-12
          and res["left_invariance_err"] < 1e-9 and res["order_roundtrip"] < 1e-12
          and abs(res.get("loss_at_same_pose", 0.0)) < 1e-6
          and res.get("torch_step_ok", True)
          and res["grad_flows"] and res["exp_log_wrap_pose_err"] < 1e-9)
    res["ok"] = bool(ok)
    say("\n".join("%-28s %s" % (k, v) for k, v in res.items()))
    return res


if __name__ == "__main__":
    r = self_test()
    raise SystemExit(0 if r["ok"] else 1)
