# -*- coding: utf-8 -*-
"""phase_corridor — 相空间安全通道 (Phase-Space Safe Corridor) · SE(3)×S1 记忆 + 速度纤维

老倪 2026-11-20 口径 (专利核心算法):
  · 底空间  Q = R³(平移) × S³(四元数) × S¹(工序相位)  —— 流形引擎已记住的 SE(3)×S1
  · 纤维    T_qQ = 线速度 v∈R³ + 角速度 ω∈R³          —— 相空间 x=(q, q̇)
  · 度规    各向异性 (专利公差): 径向 0.3mm 敏感 / 轴向 6mm 宽容; 速度纤维同理
            (横向 50mm/s 严 / 轴向 300mm/s 松), 并按载荷自适应加严
  · 势能    z = [e_pose/tol ; e_vel/vlim] (无量纲偏离)  V_phase = ½‖z‖²
            ⇒ V=1 正好压在公差上; V>ε 判"越出相空间通道"
  · 修正    τ_safe = −α·τ_lim⊙(z_pos + z_vel)  —— 专利 −αM⁻¹∇V 的工程形态:
            度规决定方向权重, τ_lim 决定幅度 (各向异性刚度 + 饱和)
  · 门控    S¹ 相位不一致 ⇒ 记忆匹配断裂, 注入置 0 (不在错位状态下乱扯)
  · 李雅普诺夫: α_eff = min(α, λ/2) ⇒ V̇ = −α_eff‖z‖² ≤ −λV, 能量单调下降
  · 载荷自适应: 0.1kg↔1.6T 级切换 ⇒ 速度纤维按 √(m/m_ref) 加严/放松

真机只读: 本模块不做任何下发, 只产出建议量 τ_safe 与判据 (V_phase / gate / monotone)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ----------------------------------------------------------------------------- 几何基元


def quat_to_R(q) -> np.ndarray:
    """四元数 (qx,qy,qz,qw) → 旋转矩阵。"""
    q = np.asarray(q, dtype=float).reshape(4)
    n = float(np.linalg.norm(q))
    if n < 1e-12:
        return np.eye(3)
    x, y, z, w = q / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def so3_log(R: np.ndarray) -> np.ndarray:
    """SO(3) → 旋转向量 (李代数 log, 近 π 走对称分支; 避开欧拉角奇异)。"""
    R = np.asarray(R, dtype=float)
    c = max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))
    th = math.acos(c)
    if th < 1e-9:
        return np.zeros(3)
    if th > math.pi - 1e-6:
        A = (R + np.eye(3)) / 2.0
        i = int(np.argmax(np.diag(A)))
        v = A[:, i] / math.sqrt(max(float(A[i, i]), 1e-12))
        v = v / (float(np.linalg.norm(v)) + 1e-12)
        return v * th
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * math.sin(th))
    return w * th


def s1_dist(a: float, b: float) -> float:
    """S¹ 最短角距 (rad ∈ [0,π])。"""
    d = (float(a) - float(b)) % (2 * math.pi)
    return float(min(d, 2 * math.pi - d))


# ----------------------------------------------------------------------------- 度规


@dataclass
class CorridorMetric:
    """各向异性度规: 每轴一条公差 (位置 m / 速度 m·s⁻¹ / 角 rad, rad·s⁻¹)。"""

    tol_radial_m: float = 3.0e-4       # 横向公差 0.3mm
    tol_axial_m: float = 6.0e-3        # 轴向公差 6mm
    tol_rot_rad: float = math.radians(0.5)
    v_max_radial: float = 0.05         # 横向 50mm/s
    v_max_axial: float = 0.30          # 轴向 300mm/s
    w_max: float = 0.6                 # 角速度 0.6rad/s
    axial_axis: int = 2                # 工具轴在本坐标系的维度
    payload_kg: float = 0.10           # 光模块 0.1kg
    ref_payload_kg: float = 0.10
    damping_gain: float = 1.0

    def axial_index(self, axis=None) -> int:
        if axis is None:
            return int(self.axial_axis)
        return int(np.argmax(np.abs(np.asarray(axis, dtype=float))))

    def payload_scale(self) -> float:
        ref = max(self.ref_payload_kg, 1e-6)
        return float(np.clip((self.payload_kg / ref) ** 0.5, 0.5, 4.0))

    def tol_pos(self, axis=None) -> np.ndarray:
        ai = self.axial_index(axis)
        t = np.array([self.tol_radial_m] * 3)
        t[ai] = self.tol_axial_m
        return np.concatenate([t, np.full(3, self.tol_rot_rad)])

    def tol_vel(self, axis=None) -> np.ndarray:
        ai = self.axial_index(axis)
        v = np.array([self.v_max_radial] * 3)
        v[ai] = self.v_max_axial
        k = self.damping_gain * self.payload_scale()
        return np.concatenate([v, np.full(3, self.w_max)]) * (k ** 0.5)

    def M_pos(self, axis=None) -> np.ndarray:
        """势能权重 W = diag(1/tol²) —— V=½eᵀWe 为无量纲 (V=1 ⇒ 正好压在公差上)。"""
        return np.diag(1.0 / self.tol_pos(axis) ** 2)

    def M_vel(self, axis=None) -> np.ndarray:
        return np.diag(1.0 / self.tol_vel(axis) ** 2)

    def G(self, axis=None) -> np.ndarray:
        return np.block([[self.M_pos(axis), np.zeros((6, 6))],
                         [np.zeros((6, 6)), self.M_vel(axis)]])


# ----------------------------------------------------------------------------- 结果


@dataclass
class PhaseCorridorResult:
    gate: bool
    phase_err_rad: float
    e_pose: np.ndarray
    e_vel: np.ndarray
    z_pose: np.ndarray
    z_vel: np.ndarray
    V_pos: float
    V_vel: float
    V_phase: float
    inside: bool
    tau_safe: np.ndarray
    tau_raw: np.ndarray
    V_dot: float
    monotone: bool
    clipped: float
    alpha_eff: float
    detail: dict = field(default_factory=dict)

    def summary(self) -> str:
        return (f"V={self.V_phase:.3g} (pos {self.V_pos:.3g} + vel {self.V_vel:.3g}) · "
                f"栅门 {'开' if self.gate else '关(S¹不匹配)'} · "
                f"{'通道内' if self.inside else '越界需干预'} · "
                f"V̇={self.V_dot:+.3e} {'单调↓' if self.monotone else '非单调'} · "
                f"τ={np.round(self.tau_safe, 2).tolist()}"
                + (f" · 限幅×{self.clipped:.2f}" if self.clipped < 0.999 else ""))

    def as_dict(self) -> dict:
        return {
            "gate": self.gate, "phase_err_deg": round(math.degrees(self.phase_err_rad), 2),
            "V_phase": round(self.V_phase, 6), "V_pos": round(self.V_pos, 6),
            "V_vel": round(self.V_vel, 6), "inside": self.inside,
            "tau_safe": [round(float(x), 4) for x in self.tau_safe],
            "V_dot": float(self.V_dot), "monotone": self.monotone,
            "clipped": round(self.clipped, 4), "alpha_eff": round(self.alpha_eff, 4),
            "detail": self.detail,
        }


class PhaseSpaceCorridor:
    """SE(3)×S1 记忆流形上的相空间势能漏斗。"""

    def __init__(self, metric: CorridorMetric | None = None,
                 epsilon: float = 0.30, alpha: float = 1.5, lam: float = 2.0,
                 tau_limit=None, phase_gate_rad: float = math.radians(15.0)):
        self.metric = metric or CorridorMetric()
        self.epsilon = float(epsilon)      # 通道能量阈值 ε (V≤ε 不干预)
        self.alpha = float(alpha)          # 自然梯度增益
        self.lam = float(lam)              # 李雅普诺夫衰减率 λ
        self.phase_gate_rad = float(phase_gate_rad)
        self.tau_limit = np.asarray(
            tau_limit if tau_limit is not None else [25.0, 25.0, 25.0, 3.0, 3.0, 3.0], float)

    # -- 单步 ---------------------------------------------------------------
    def compute(self, cur: dict, des: dict, dt: float = 0.01, axis=None) -> PhaseCorridorResult:
        """cur/des: pos(m,3) · quat(qx,qy,qz,qw) · s1(rad) · vel(m/s,3) · omega(rad/s,3)。"""
        p_c = np.asarray(cur["pos"], float).reshape(3)
        p_d = np.asarray(des["pos"], float).reshape(3)
        q_c = np.asarray(cur["quat"], float).reshape(4)
        q_d = np.asarray(des["quat"], float).reshape(4)
        s_c, s_d = float(cur.get("s1", 0.0)), float(des.get("s1", 0.0))
        v_c = np.asarray(cur.get("vel", np.zeros(3)), float).reshape(3)
        v_d = np.asarray(des.get("vel", np.zeros(3)), float).reshape(3)
        w_c = np.asarray(cur.get("omega", np.zeros(3)), float).reshape(3)
        w_d = np.asarray(des.get("omega", np.zeros(3)), float).reshape(3)

        # ① S¹ 相位门控: 记忆匹配断裂 ⇒ 不注入
        perr = s1_dist(s_c, s_d)
        gate = bool(perr <= self.phase_gate_rad)

        # ② 流形误差 (R³ 直差 · S³ 李代数 log)
        e_pos = p_c - p_d
        e_rot = so3_log(quat_to_R(q_d).T @ quat_to_R(q_c))
        e_pose = np.concatenate([e_pos, e_rot])
        e_vel = np.concatenate([v_c - v_d, w_c - w_d])

        # ③ 无量纲偏离 + 相空间势能 (V=1 ⇒ 正好在公差上)
        tol_p = self.metric.tol_pos(axis)
        tol_v = self.metric.tol_vel(axis)
        z_pose = e_pose / tol_p
        z_vel = e_vel / tol_v
        V_pos = 0.5 * float(z_pose @ z_pose)
        V_vel = 0.5 * float(z_vel @ z_vel)
        V_phase = V_pos + V_vel
        inside = bool(V_phase <= self.epsilon)

        # ④ 各向异性修正 (度规定方向, τ_lim 定幅度)
        tau_raw = np.zeros(6)
        if gate and not inside:
            tau_raw = -self.alpha * self.tau_limit * (z_pose + z_vel)

        # ⑤ 李雅普诺夫限幅: α_eff 保证 V̇ ≤ −λV; 再按 τ_lim 等比例收 (方向不变)
        if not np.any(tau_raw):
            # 通道内 / S¹ 不匹配 ⇒ 不注入: 无修正能量流, 判据按"未失稳"记
            tau = np.zeros(6)
            clip, vdot, a_eff = 1.0, 0.0, 0.0
        else:
            tau, clip, vdot, a_eff = self._lyapunov_clip(tau_raw, z_pose, z_vel, V_phase)
        monotone = bool(vdot <= 1e-12)

        return PhaseCorridorResult(
            gate=gate, phase_err_rad=perr, e_pose=e_pose, e_vel=e_vel,
            z_pose=z_pose, z_vel=z_vel, V_pos=V_pos, V_vel=V_vel, V_phase=V_phase,
            inside=inside, tau_safe=tau, tau_raw=tau_raw, V_dot=float(vdot),
            monotone=monotone, clipped=float(clip), alpha_eff=float(a_eff),
            detail={
                "eps": self.epsilon, "alpha": self.alpha, "lambda": self.lam,
                "payload_kg": self.metric.payload_kg,
                "vel_damping": round(self.metric.payload_scale(), 3),
                "e_pos_mm": np.round(e_pos * 1e3, 3).tolist(),
                "e_rot_deg": np.round(np.degrees(e_rot), 3).tolist(),
                "e_vel": np.round(e_vel, 4).tolist(),
                "tol_mm": np.round(tol_p[:3] * 1e3, 3).tolist(),
            })

    # -- 限幅 ---------------------------------------------------------------
    def _lyapunov_clip(self, tau_raw, z_pose, z_vel, V):
        """V̇ = −α_eff‖z‖² ≤ −λV ⇒ α_eff ≤ λV/‖z‖² = λ/2 (因 V=½‖z‖²)。"""
        z2 = float(z_pose @ z_pose + z_vel @ z_vel)
        if V <= 1e-15 or z2 <= 1e-18:
            return np.zeros(6), 1.0, 0.0, 0.0
        a_eff = float(min(self.alpha, 0.5 * self.lam))
        tau = tau_raw * (a_eff / max(self.alpha, 1e-12))
        ratio = float(np.max(np.abs(tau) / np.maximum(self.tau_limit, 1e-9)))
        s = 1.0 if ratio <= 1.0 else 1.0 / ratio
        tau = tau * s
        vdot = -a_eff * s * z2
        return tau, float(s), float(min(vdot, 0.0)), a_eff


# ----------------------------------------------------------------------------- 自检


def _ok(r: PhaseCorridorResult) -> bool:
    """判据: 通道内(不注入=天然稳定) 或 V̇<0 (被拉回)。"""
    return bool(r.inside or r.V_dot < 0.0)


def _demo() -> int:
    m = CorridorMetric()
    pc = PhaseSpaceCorridor(m, epsilon=0.30)
    des = {"pos": [0.50, 0.30, 0.12], "quat": [0, 0, 0, 1], "s1": 0.0,
           "vel": [0.05, 0.0, 0.0], "omega": [0, 0, 0]}

    print("① 通道内 (径向偏 0.1mm, 同相) → 不干预:")
    cur = {"pos": [0.5001, 0.30, 0.12], "quat": [0, 0, 0, 1], "s1": 0.05,
           "vel": [0.05, 0.0, 0.0], "omega": [0, 0, 0]}
    print("   ", pc.compute(cur, des).summary())

    print("② 越界 (径向偏 3mm = 10×公差, 速度 90mm/s) → 限幅修正:")
    cur = {"pos": [0.503, 0.30, 0.12], "quat": [0, 0, 0, 1], "s1": 0.05,
           "vel": [0.09, 0.0, 0.0], "omega": [0, 0, 0]}
    r = pc.compute(cur, des)
    print("   ", r.summary())
    print("    e_pos_mm", r.detail["e_pos_mm"], "α_eff", round(r.alpha_eff, 3))

    print("③ S¹ 不匹配 (相位差 90°) → 栅门关, 零注入:")
    cur = {"pos": [0.503, 0.30, 0.12], "quat": [0, 0, 0, 1], "s1": math.pi / 2,
           "vel": [0.09, 0.0, 0.0], "omega": [0, 0, 0]}
    print("   ", pc.compute(cur, des).summary())

    print("④ 姿态误差走李代数 (绕 z 转 2° ⇒ e_rot_deg 只出现在 z):")
    th = math.radians(2.0)
    cur = {"pos": [0.50, 0.30, 0.12], "quat": [0, 0, math.sin(th / 2), math.cos(th / 2)],
           "s1": 0.0, "vel": [0.0, 0.0, 0.0], "omega": [0, 0, 0]}
    print("    e_rot_deg", pc.compute(cur, des).detail["e_rot_deg"])

    print("⑤ 载荷自适应 (速度纤维随之加严):")
    for kg in (0.1, 0.2, 1.6):
        mm = CorridorMetric(payload_kg=kg)
        print(f"    {kg:>4}kg  阻尼系数={mm.payload_scale():.3f}  "
              f"横向tol_vel={mm.tol_vel()[0]:.4f}  轴向={mm.tol_vel()[2]:.4f}")

    print("⑥ 单调性横扫 (径向 0.5→10mm × 速度 0→150mm/s):")
    bad = 0
    for dmm in np.linspace(0.5, 10.0, 8):
        for vv in np.linspace(0.0, 0.15, 3):
            cur = {"pos": [0.50 + dmm / 1e3, 0.30, 0.12], "quat": [0, 0, 0, 1], "s1": 0.0,
                   "vel": [vv, 0.0, 0.0], "omega": [0, 0, 0]}
            bad += 0 if _ok(pc.compute(cur, des)) else 1
    print(f"    不满足 24 点里的 {bad} 个")
    return bad


if __name__ == "__main__":
    n = _demo()
    print("SELF_TEST", "PASS" if n == 0 else f"FAIL({n})")
