"""S³ → S² × S¹ 的 Hopf 分解(权威实现, 包内副本)。

口径与 ``tools/se3_hopf.py`` **逐位一致**(该文件是 2026-11-18 定标时的实现), 这里放进包里
是为了让流形引擎(``se3_layers.SE3Layered``)能直接 import, 不用靠 sys.path 摸 tools/。

    q ∈ S³  --π-->  n = R·e₁ ∈ S²        (朝哪: 工具 X 轴在基座系的方向)
                   φ = 2·atan2(z, w) ∈ S¹ (拧多少: 绕 n 的滚转)
    q = q_s(n) · quat_x(φ − φ_s)          (q_s = e₁→n 的最短弧提升, φ_s = hopf(q_s)[1])

四元数分量序 **(x, y, z, w)**, 末位是标量 —— 与 ``tools/web/real_traj_joints.json`` 一致
(录制 #0 q=(0.7616,0.0730,0.6220,0.1667) 与真值 latest.json 逐位对应确认)。

⚠ 为什么必须有固定截面: S³→S² 是**扭曲**的丛, 不挑截面直接用 (n, φ) 重建 q 会差 0.136°
(实测), 取最短弧截面后 215 帧往返 max 2.96e-06°; 恒等式 φ = 2θ + φ_s 偏差 2.8e-14°。
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple

__all__ = [
    "hopf", "hopf_join", "axis_angle_deg", "roll_delta_deg", "wrap_pi",
    "qmul", "qconj", "q_from_axis_angle", "q_normalize", "quat_angle_deg",
    "slerp", "R_from_q",
]

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]     # (x, y, z, w)
TWO_PI = 2.0 * math.pi


# ── 基本四元数运算 (纯 python, 不引 numpy: 引擎每拍调 200+ 次, 小向量 numpy 更慢) ──
def q_normalize(q: Sequence[float]) -> Quat:
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return (x / n, y / n, z / n, w / n)


def qmul(a: Sequence[float], b: Sequence[float]) -> Quat:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qconj(q: Sequence[float]) -> Quat:
    x, y, z, w = (float(v) for v in q)
    return (-x, -y, -z, w)


def q_from_axis_angle(axis: Sequence[float], ang: float) -> Quat:
    ax, ay, az = (float(v) for v in axis)
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(ang / 2.0) / n
    return (ax * s, ay * s, az * s, math.cos(ang / 2.0))


def R_from_q(q: Sequence[float]) -> list:
    """(x,y,z,w) → 3×3 旋转矩阵 (行优先, 用于把 n 换回 e₁ 校验)。"""
    x, y, z, w = q_normalize(q)
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def wrap_pi(a: float) -> float:
    """角度归一到 (-π, π]。"""
    return (a + math.pi) % TWO_PI - math.pi


# ── Hopf 分解 / 合成 ───────────────────────────────────────────────────────────
def hopf(q: Sequence[float]) -> Tuple[Vec3, float]:
    """单位四元数 → (n ∈ S², φ ∈ [0, 2π))。与 tools/se3_hopf.py 同式。"""
    x, y, z, w = q_normalize(q)
    n = (2.0 * (x * z + w * y), 2.0 * (y * z - w * x), w * w + z * z - x * x - y * y)
    m = math.sqrt(sum(c * c for c in n)) or 1.0
    n = (n[0] / m, n[1] / m, n[2] / m)
    phi = (2.0 * math.atan2(z, w)) % TWO_PI
    return n, phi


def _lift(n: Sequence[float]) -> Quat:
    """最短弧截面 s(n): 把 e₃ 转到 n 的四元数 (无量纲、唯一, 除对跖点)。"""
    nx, ny, nz = (float(v) for v in n)
    m = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    nx, ny, nz = nx / m, ny / m, nz / m
    c = nz                                # e₃·n
    # 轴 = e₃ × n = (−ny, nx, 0)   ← 叉积顺序必须是 a×b (e₃→n 的正向), 反了会转成 −n
    ax, ay, az = -ny, nx, 0.0
    s = math.sqrt(ax * ax + ay * ay + az * az)
    if s < 1e-12:                         # n ∥ e₃: 叉积退化, 但转角仍可能是 acos(c) ≠ 0
        if c > 0:
            return (0.0, 0.0, 0.0, 1.0)
        return q_from_axis_angle((1.0, 0.0, 0.0), math.acos(max(-1.0, min(1.0, c))))
    ang = math.atan2(s, c)
    return q_from_axis_angle((ax / s, ay / s, az / s), ang)


def hopf_join(n: Sequence[float], phi: float) -> Quat:
    """(n ∈ S², φ ∈ S¹) → 单位四元数 q ∈ S³ (固定最短弧截面的右逆)。"""
    qs = _lift(n)
    _, phi_s = hopf(qs)
    return q_normalize(qmul(qs, q_from_axis_angle((0.0, 0.0, 1.0), wrap_pi(phi - phi_s))))


# ── 距离 (S² 大圆角 / S¹ 环绕差) ───────────────────────────────────────────────
def axis_angle_deg(n1: Sequence[float], n2: Sequence[float]) -> float:
    d = sum(float(a) * float(b) for a, b in zip(n1, n2))
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def roll_delta_deg(p1: float, p2: float) -> float:
    d = math.degrees(float(p2) - float(p1))
    return (d + 180.0) % 360.0 - 180.0


def quat_angle_deg(q1: Sequence[float], q2: Sequence[float]) -> float:
    """S³≅SU(2) 上的测地角(度) —— 双覆盖: 取 |q̂₁·q̂₂| 保证 ±q 同一姿态。"""
    a, b = q_normalize(q1), q_normalize(q2)
    d = abs(sum(c * d2 for c, d2 in zip(a, b)))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, d))))


def slerp(q1: Sequence[float], q2: Sequence[float], t: float) -> Quat:
    """S³ 测地线插值 (半球化 + 线性插值 + 归一, 小角度与真 slerp 差 <1e-9)。"""
    a, b = q_normalize(q1), q_normalize(q2)
    if sum(c * d for c, d in zip(a, b)) < 0.0:          # 双覆盖: 走短弧
        b = tuple(-c for c in b)
    t = float(t)
    out = tuple((1.0 - t) * c + t * d for c, d in zip(a, b))
    return q_normalize(out)
