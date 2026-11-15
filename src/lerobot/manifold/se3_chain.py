"""SE(3) 流形链路 —— 位姿引擎本体 (替代 s3_chain.py 的 S³ 表示)。

为什么要有它
------------
s3_chain.py 把 3 维**平移误差** e 经 `from_rotvec(gain*e)` 压成单位四元数放进 S³:
方向 ê 当转轴、‖e‖ 经 tanh 当角度。后果是三样东西不在流形里:
  ① 末端绝对平移 (末端在哪个 xyz) —— S³ 只有 3 自由度, SE(3) 是 6 自由度;
  ② 末端姿态 —— e 是平移误差, 不是姿态误差;
  ③ 误差量级 —— tanh 饱和后大误差/小误差挤在一起。
本模块把表示换成刚体变换群 SE(3): 点 T 是 4×4 齐次矩阵, 速度是 se(3) 的 6 维 twist ξ = [ρ; φ]。

约定 (与 geometric-latent-branch / SE3 阻抗同序)
------------------------------------------------
  ξ = [ρ; φ]        ρ ∈ R³ 平移分量 (m), φ ∈ R³ 旋转分量 (rad, axis*angle)
  T = [[R, t], [0, 1]]
  指数:  exp([ρ;φ]) = [[R(φ), V(φ)ρ], [0,1]],  V = I + (1-cosθ)/θ² [φ]× + (θ-sinθ)/θ³ [φ]×²
  对数:  log(T) = [V⁻¹ t; log R]
  测地线: T(s) = T0 · exp(s · log(T0⁻¹ T1))
  势:    φ(T) = 0.5 ‖log(T_goal⁻¹ T)‖²_W  (W 为 6 维权重, 单位不同量纲要分开)

只算不下发: 返回建议 twist, 真机执行走现场授权链。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EPS = 1e-12


# ════════════════════════════════════════════════════════════════════════════
# 1. 基本群运算
# ════════════════════════════════════════════════════════════════════════════
def skew(v) -> np.ndarray:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]], float)


def vee(M) -> np.ndarray:
    return np.array([M[2, 1], M[0, 2], M[1, 0]], float)


def adjoint(T: np.ndarray) -> np.ndarray:
    """Ad_T : se(3) → se(3), ξ_空间 = Ad_T ξ_体。序 [ρ; φ]。"""
    R, t = T[:3, :3], T[:3, 3]
    A = np.zeros((6, 6))
    A[:3, :3] = R
    A[3:, 3:] = R
    A[:3, 3:] = skew(t) @ R
    return A


def T_from_rot_t(R, t) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = np.asarray(R, float)
    T[:3, 3] = np.asarray(t, float).reshape(3)
    return T


def _V(phi: np.ndarray) -> np.ndarray:
    """V(φ) = I + (1-cosθ)/θ² K + (θ-sinθ)/θ³ K²,  K = [φ]×。"""
    th2 = float(phi @ phi)
    K = skew(phi)
    if th2 < 1e-12:
        # 泰勒: (1-cosθ)/θ² → 1/2 - θ²/24 ; (θ-sinθ)/θ³ → 1/6 - θ²/120
        return np.eye(3) + 0.5 * K + (1.0 / 6.0) * (K @ K)
    th = math.sqrt(th2)
    a = (1.0 - math.cos(th)) / th2
    b = (th - math.sin(th)) / (th2 * th)
    return np.eye(3) + a * K + b * (K @ K)


def _V_inv(phi: np.ndarray) -> np.ndarray:
    """V⁻¹(φ) = I - 1/2 K + (1/θ² - (1+cosθ)/(2θ sinθ)) K²。"""
    th2 = float(phi @ phi)
    K = skew(phi)
    if th2 < 1e-12:
        return np.eye(3) - 0.5 * K + (1.0 / 12.0) * (K @ K)
    th = math.sqrt(th2)
    c = 1.0 / th2 - (1.0 + math.cos(th)) / (2.0 * th * math.sin(th))
    return np.eye(3) - 0.5 * K + c * (K @ K)


def rot_exp(phi) -> np.ndarray:
    """so(3) → SO(3), Rodrigues。"""
    phi = np.asarray(phi, float).reshape(3)
    th2 = float(phi @ phi)
    K = skew(phi)
    if th2 < 1e-12:
        return np.eye(3) + K + 0.5 * (K @ K)
    th = math.sqrt(th2)
    return np.eye(3) + (math.sin(th) / th) * K + ((1.0 - math.cos(th)) / th2) * (K @ K)


def rot_log(R) -> np.ndarray:
    """SO(3) → so(3) (返回旋转向量 φ, ‖φ‖ = 旋转角)。"""
    R = np.asarray(R, float)
    c = (np.trace(R) - 1.0) * 0.5
    c = min(1.0, max(-1.0, c))
    th = math.acos(c)
    if th < 1e-9:
        return 0.5 * vee(R - R.T)
    if abs(math.pi - th) < 1e-6:
        # θ≈π: 从 R+I 的列取轴 (对称情形数值稳定)
        A = (R + np.eye(3)) * 0.5
        axis = np.sqrt(np.maximum(np.diag(A), 0.0))
        k = int(np.argmax(axis))
        if axis[k] > 0:
            axis = A[:, k] / axis[k]
        axis = axis / max(np.linalg.norm(axis), EPS)
        return axis * math.pi
    return (th / (2.0 * math.sin(th))) * vee(R - R.T)


def se3_exp(xi) -> np.ndarray:
    """se(3) 6 维 twist [ρ; φ] → SE(3) 4×4。"""
    xi = np.asarray(xi, float).reshape(6)
    rho, phi = xi[:3], xi[3:]
    T = np.eye(4)
    T[:3, :3] = rot_exp(phi)
    T[:3, 3] = _V(phi) @ rho
    return T


def se3_log(T) -> np.ndarray:
    """SE(3) 4×4 → se(3) 6 维 twist [ρ; φ]。"""
    T = np.asarray(T, float)
    R, t = T[:3, :3], T[:3, 3]
    phi = rot_log(R)
    rho = _V_inv(phi) @ t
    return np.concatenate([rho, phi])


def geodesic(T0, T1, s: float) -> np.ndarray:
    """SE(3) 上的测地线: T(s) = T0 · exp(s · log(T0⁻¹ T1)), s∈[0,1]。"""
    T0 = np.asarray(T0, float)
    T1 = np.asarray(T1, float)
    d = se3_log(np.linalg.inv(T0) @ T1)
    return T0 @ se3_exp(float(s) * d)


def se3_dist(T0, T1, w=None) -> float:
    """加权李代数距离 (单位不同 ⇒ 平移/旋转分开加权)。"""
    d = se3_log(np.linalg.inv(np.asarray(T0, float)) @ np.asarray(T1, float))
    if w is not None:
        w = np.asarray(w, float).reshape(6)
        d = d * w
    return float(np.linalg.norm(d))


# ════════════════════════════════════════════════════════════════════════════
# 2. 位姿真源 (rokae SDK 直读, 10Hz)
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class PoseTruth:
    T: np.ndarray
    t_mm: np.ndarray
    quat_xyzw: np.ndarray
    ts: float
    age_s: float
    frame: str
    src: str

    def as_dict(self) -> dict:
        return {"x": float(self.t_mm[0]), "y": float(self.t_mm[1]), "z": float(self.t_mm[2]),
                "qx": float(self.quat_xyzw[0]), "qy": float(self.quat_xyzw[1]),
                "qz": float(self.quat_xyzw[2]), "qw": float(self.quat_xyzw[3]),
                "age_s": round(self.age_s, 3), "frame": self.frame, "src": self.src}


def quat_to_R(q) -> np.ndarray:
    x, y, z, w = [float(v) for v in np.asarray(q, float).reshape(4)]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], float)


def R_to_quat(R) -> np.ndarray:
    """SO(3) → 单位四元数 (x, y, z, w), 数值稳定分支。"""
    R = np.asarray(R, float)
    tr = np.trace(R)
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], float)
    return q / (np.linalg.norm(q) or 1.0)


def read_pose_truth(root: str, max_age_s: float = 2.0) -> PoseTruth | None:
    """读真机 TCP 位姿真值 (rokae SDK 直读)。拿不到或太旧 ⇒ None (绝不拿陈旧值冒充)。"""
    import json
    import os
    import time

    f = os.path.join(root, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
    try:
        age = time.time() - os.path.getmtime(f)
        if age > max_age_s:
            return None
        d = json.load(open(f))
    except Exception:                                                    # noqa: BLE001
        return None
    try:
        t_m = np.array([d["x"], d["y"], d["z"]], float)
        q = d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")
        if any(v is None for v in q):
            return None
        q = np.array([float(v) for v in q], float)
        R = quat_to_R(q)
    except Exception:                                                    # noqa: BLE001
        return None
    return PoseTruth(T=T_from_rot_t(R, t_m), t_mm=t_m * 1000.0, quat_xyzw=q,
                     ts=float(d.get("ts") or 0.0), age_s=age,
                     frame=str(d.get("frame") or "?"), src=str(d.get("src") or "?"))


# ════════════════════════════════════════════════════════════════════════════
# 3. 势场 (在 SE(3) 上定义, 用李代数范数; 平移/旋转分开加权)
# ════════════════════════════════════════════════════════════════════════════
def R_to_rpy(R) -> np.ndarray:
    """SE(3) 旋转 → rpy (ZYX 序, 与 hjepa_manifold_provider._rpy_to_T 的 Rz@Ry@Rx 严格互逆)。

    引擎 obs 的 state7 口径是 [x,y,z(m), rx,ry,rz(rad), grip], 真机位姿给的是四元数,
    所以必须能从 R 反解 rpy —— 不自造第三套序。
    """
    R = np.asarray(R, float).reshape(3, 3)
    sy = float(np.clip(-R[2, 0], -1.0, 1.0))
    ry = float(np.arcsin(sy))
    if abs(sy) < 1.0 - 1e-9:
        rx = float(np.arctan2(R[2, 1], R[2, 2]))
        rz = float(np.arctan2(R[1, 0], R[0, 0]))
    else:                                    # 万向锁: 只定 rx+rz 的组合
        rx = float(np.arctan2(-R[1, 2], R[1, 1]))
        rz = 0.0
    return np.array([rx, ry, rz], float)


def potential(T: np.ndarray, T_goal: np.ndarray, w=None) -> tuple[float, np.ndarray]:
    """φ(T) = 0.5‖W·log(T_goal⁻¹T)‖², 返回 (φ, 对 ξ 的梯度 = W²·log)。

    梯度就是李代数误差本身 (加权), 这是 SE(3) 上二次势的标准结果:
        ∂φ/∂ξ = W² ξ,  ξ = log(T_goal⁻¹ T)
    """
    d = se3_log(np.linalg.inv(np.asarray(T_goal, float)) @ np.asarray(T, float))
    w6 = np.ones(6) if w is None else np.asarray(w, float).reshape(6)
    dw = d * w6
    return 0.5 * float(dw @ dw), w6 * dw


def twist_to_pose_rate(T: np.ndarray, xi_body, dt: float) -> np.ndarray:
    """本体 twist → 下一拍位姿: T' = T · exp(ξ·dt)。"""
    return np.asarray(T, float) @ se3_exp(np.asarray(xi_body, float).reshape(6) * float(dt))


# ════════════════════════════════════════════════════════════════════════════
# 4. 自检 (数学恒等式 + 真值对账, 全部实测不靠断言口说)
# ════════════════════════════════════════════════════════════════════════════
def selftest(root: str = "/home/ubuntu/zmax", n: int = 200, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    rep = {"n": int(n), "checks": {}}

    # ① exp/log 往返
    e1 = e2 = 0.0
    for _ in range(n):
        xi = np.concatenate([rng.normal(size=3) * 0.4, rng.normal(size=3) * 0.8])
        T = se3_exp(xi)
        e1 = max(e1, float(np.max(np.abs(se3_exp(se3_log(T)) - T))))
        e2 = max(e2, float(np.max(np.abs(se3_log(se3_exp(xi)) - xi))))
    rep["checks"]["exp_log_roundtrip_T"] = e1
    rep["checks"]["log_exp_roundtrip_xi"] = e2

    # ② 小角度/零角度分支 (θ→0 泰勒)
    T0 = se3_exp(np.array([1e-9, -2e-9, 3e-9, 1e-10, -1e-10, 2e-10]))
    rep["checks"]["tiny_twist_exp_minus_I"] = float(np.max(np.abs(T0 - np.eye(4))))

    # ③ 测地线端点 + 中点距离减半
    Ta = se3_exp(np.concatenate([rng.normal(size=3) * 0.2, rng.normal(size=3) * 0.5]))
    Tb = se3_exp(np.concatenate([rng.normal(size=3) * 0.2, rng.normal(size=3) * 0.5]))
    Tm = geodesic(Ta, Tb, 0.5)
    d_ab, d_am, d_mb = se3_dist(Ta, Tb), se3_dist(Ta, Tm), se3_dist(Tm, Tb)
    rep["checks"]["geodesic_end"] = float(max(np.max(np.abs(geodesic(Ta, Tb, 0.0) - Ta)),
                                              np.max(np.abs(geodesic(Ta, Tb, 1.0) - Tb))))
    rep["checks"]["geodesic_midpoint_ratio"] = float(d_am / max(d_ab, EPS))

    # ④ SE(3) 群性质: exp(ξ) 必须保刚体 (RᵀR=I, det=1)
    dev = 0.0
    for _ in range(n):
        T = se3_exp(np.concatenate([rng.normal(size=3) * 0.3, rng.normal(size=3) * 1.2]))
        R = T[:3, :3]
        dev = max(dev, float(np.max(np.abs(R.T @ R - np.eye(3)))), abs(float(np.linalg.det(R)) - 1.0))
    rep["checks"]["rigid_body_deviation"] = dev

    # ⑤ 伴随性质: Ad_T · ξ_体 = log(T exp(ξ) T⁻¹)  (空间 twist 一致)
    xi = np.array([0.03, -0.02, 0.05, 0.1, -0.2, 0.15])
    T = se3_exp(np.array([0.2, -0.1, 0.3, 0.3, -0.15, 0.25]))
    lhs = adjoint(T) @ xi
    rhs = se3_log(T @ se3_exp(xi) @ np.linalg.inv(T))
    rep["checks"]["adjoint_identity"] = float(np.max(np.abs(lhs - rhs)))

    # ⑥ 与 scipy 对账 (若可用)
    try:
        from scipy.spatial.transform import Rotation as Rsc
        q = rng.normal(size=3)
        q = q / np.linalg.norm(q) * 1.1
        R1 = rot_exp(q)
        R2 = Rsc.from_rotvec(q).as_matrix()
        rep["checks"]["vs_scipy_rot_exp"] = float(np.max(np.abs(R1 - R2)))
    except Exception as exc:                                             # noqa: BLE001
        rep["checks"]["vs_scipy_rot_exp"] = "skip: %s" % exc

    # ⑦ 真值对账: tcp_out 的 x,y,z + quat → T → 反算必须逐位回到原值
    pt = read_pose_truth(root)
    if pt is not None:
        T = pt.T
        back_q = R_to_quat(T[:3, :3])
        back_t = T[:3, 3] * 1000.0
        rep["truth"] = pt.as_dict()
        rep["checks"]["truth_t_roundtrip_mm"] = float(np.max(np.abs(back_t - pt.t_mm)))
        rep["checks"]["truth_quat_roundtrip"] = float(min(
            np.max(np.abs(back_q - pt.quat_xyzw)),
            np.max(np.abs(back_q + pt.quat_xyzw))))       # q 与 -q 同姿态
        rep["checks"]["truth_T_det"] = float(np.linalg.det(T[:3, :3]))
    else:
        rep["truth"] = None
        rep["checks"]["truth"] = "tcp_out 不可用或陈旧 ⇒ 未对账"

    th = {"exp_log_roundtrip_T": 1e-9, "log_exp_roundtrip_xi": 1e-8,
          "tiny_twist_exp_minus_I": 1e-8, "geodesic_end": 1e-9,
          "geodesic_midpoint_ratio": (0.499, 0.501), "rigid_body_deviation": 1e-10,
          "adjoint_identity": 1e-8}
    fails = []
    for k, lim in th.items():
        v = rep["checks"].get(k)
        if not isinstance(v, (int, float)):
            continue
        if isinstance(lim, tuple):
            if not (lim[0] <= v <= lim[1]):
                fails.append(k)
        elif v > lim:
            fails.append(k)
    for k in ("truth_t_roundtrip_mm", "truth_quat_roundtrip"):
        v = rep["checks"].get(k)
        if isinstance(v, float) and v > 1e-6:
            fails.append(k)
    rep["fails"] = fails
    rep["ok"] = not fails
    return rep


if __name__ == "__main__":
    import json as _json
    r = selftest()
    print(_json.dumps(r, ensure_ascii=False, indent=2))
    raise SystemExit(0 if r["ok"] else 1)
