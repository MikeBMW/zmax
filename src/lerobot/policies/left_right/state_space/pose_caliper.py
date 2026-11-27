# -*- coding: utf-8 -*-
"""pose_caliper.py — 「四元数游标卡尺」: 把旋转当作 S³ 上的一段可计算轨迹 (无压缩、无信息丢失)

与 su2.encode_obs43 的分工 (别混)
---------------------------------
· su2.encode_obs43 = **误差指示器**: ω = π·tanh(2‖e‖)·ê, 角度饱和在 π, 只表达「偏多少、往哪偏」。
  它是给人/给层合成看的语义量, 实测 100mm→35.5°, 1000mm→173.5°, 5000mm→180° (分辨率掉 200 倍)。
· 本模块 = **尺子**: q = exp(θ/2 · n̂) 精确指数映射 (θ 为物理旋转角), 不做 tanh、不做裁剪;
  S³ 上两点夹角 = θ/2 (SU(2)→SO(3) 是 2:1 覆盖 ⇒ 球面走一半角), 测地线 = slerp。
  判据全部机器精度: 往返重建、双覆盖商、球面弧长 = θ/2、逐点单位模长。

对外
----
    q_from_R(R) / R_from_q(q) / q_from_rotvec(ω) / rotvec_from_q(q)   精确双射 (含 ±q 商)
    canonical(q)                 双覆盖商: 强制 w≥0 (w≈0 时按首个非零分量定符号), 幂等
    slerp(q0, q1, t)             S³ 测地线 (最短弧 + 对跖安全)
    path(seq, n)                 位姿序列 → 插值轨迹 [{q, R, theta_so3, s3_angle}]
    arc_length(path)             S³ 弧长 (= 半角累计), 与物理转角之和对照
    resolution(step_deg)         尺子的刻度: 输入 Δθ(°) → 输出 S³ 步长(°) 与四元数分量差
    selftest(n=5000)             全部判据真跑, 返回 {ok, 各项误差}
"""
from __future__ import annotations

import numpy as np

# ── 精确双射 ────────────────────────────────────────────────────────────────


def q_from_rotvec(w) -> np.ndarray:
    """ω (旋转向量, 弧度) → 单位四元数 [w,x,y,z] = exp(θ/2·n̂)。**不做任何压缩/裁剪**。"""
    w = np.asarray(w, dtype=float).reshape(3)
    th = float(np.linalg.norm(w))
    if th < 1e-15:
        return np.array([1.0, 0.0, 0.0, 0.0])
    n = w / th
    h = 0.5 * th
    return np.concatenate([[np.cos(h)], np.sin(h) * n])


def rotvec_from_q(q) -> np.ndarray:
    """单位四元数 → 旋转向量 (最短弧, 0..π)。符号先商掉 (w≥0), 否则会得到 >π 的等价解。"""
    q = canonical(q)
    w = float(np.clip(q[0], -1.0, 1.0))
    v = np.asarray(q[1:4], dtype=float)
    s = float(np.linalg.norm(v))
    if s < 1e-15:
        return np.zeros(3)
    th = 2.0 * np.arctan2(s, w)          # = 2*acos(w), 数值更稳
    return v / s * th


def q_from_R(R) -> np.ndarray:
    """3×3 旋转矩阵 → 单位四元数 (Shepperd 分支, 全象限稳)。"""
    R = np.asarray(R, dtype=float).reshape(3, 3)
    tr = float(R[0, 0] + R[1, 1] + R[2, 2])
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [(R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s]
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s]
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s]
    return canonical(np.asarray(q, dtype=float) / np.linalg.norm(q))


def R_from_q(q) -> np.ndarray:
    """单位四元数 → 3×3 旋转矩阵 (与 q_from_R 同一符号约定)。"""
    w, x, y, z = (float(v) for v in canonical(q))
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


# ── 双覆盖商 / 测地线 ────────────────────────────────────────────────────────


def canonical(q) -> np.ndarray:
    """SU(2)→SO(3) 是 2:1 覆盖 ⇒ q 与 −q 表示同一旋转。强制 w≥0 (w≈0 用首个非零分量定符号)。
    幂等: canonical(canonical(q)) == canonical(q)。不做这步, 轨迹会在符号跳变处出现"伪长弧"。"""
    q = np.asarray(q, dtype=float).reshape(4)
    n = float(np.linalg.norm(q))
    if n < 1e-15:
        raise ValueError("零四元数不是旋转")
    q = q / n
    if q[0] < 0 or (abs(q[0]) < 1e-15 and q[1 + int(np.argmax(np.abs(q[1:])))] < 0):
        q = -q
    return q


def slerp(q0, q1, t) -> np.ndarray:
    """S³ 测地线 (最短弧): 对跖/近对跖安全, 端点精确, 全程单位模长。"""
    a, b = canonical(q0), canonical(q1)
    d = float(np.dot(a, b))
    if d < 0:                       # 走短弧 (双覆盖)
        b, d = -b, -d
    d = float(np.clip(d, -1.0, 1.0))
    if d > 1.0 - 1e-12:             # 近同点 → 线性 + 归一 (避免 0/0)
        q = a + float(t) * (b - a)
        return q / np.linalg.norm(q)
    th = np.arccos(d)               # S³ 上两点夹角 (1/2 物理转角)
    s = np.sin(th)
    return (np.sin((1.0 - float(t)) * th) * a + np.sin(float(t) * th) * b) / s


def theta_so3(q) -> float:
    """该四元数代表的**物理**旋转角 (0..π) = 2·S³ 夹角。"""
    return float(2.0 * np.arctan2(np.linalg.norm(np.asarray(q, float)[1:4]),
                                  abs(float(np.asarray(q, float)[0]))))


def s3_angle(q0, q1) -> float:
    """S³ 上两点夹角 (0..π/2) —— 乘 2 才是物理转角。这就是尺子的刻度关系。

    🐛 2026-11-03 实测修正: 原来先 `canonical()` 再点乘, 但 canonical 的"w≥0"规则在 **w≈0 附近
    不唯一** —— 同一点的两个符号表示可能都满足 w>0 (实测 q=[0.0036,-0.545,-0.826,-0.143] 与
    [-0.0087,+0.558,+0.817,+0.145] 点积 −0.9998), 于是算成 178.9° (×2=357.8°) 的假巨角。
    距离必须直接商掉双覆盖: 用 |⟨q0,q1⟩| ⇒ 恒在 [0,π/2], 与 w 的符号无关 (与 SU2Element.distance_fs 同式)。
    """
    a = np.asarray(q0, dtype=float).reshape(4)
    b = np.asarray(q1, dtype=float).reshape(4)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-15 or nb < 1e-15:
        raise ValueError("零四元数不是旋转")
    d = abs(float(np.dot(a / na, b / nb)))
    return float(np.arccos(np.clip(d, 0.0, 1.0)))


def path(seq, n_per_seg=8):
    """位姿序列 (四元数或 3×3 矩阵的 list) → 逐点轨迹 [{q, R, theta_so3, s3_angle}]。
    n_per_seg = 每段插值点数 (含段末)。用于给 IK 逐拍跟踪: 位姿序列, 不是速度序列。"""
    qs = [x if np.asarray(x).shape == (4,) else q_from_R(x) for x in seq]
    out = []
    for i in range(len(qs) - 1):
        a, b = qs[i], qs[i + 1]
        tot = s3_angle(a, b)
        for k in range(n_per_seg):
            t = k / float(n_per_seg)
            q = slerp(a, b, t)
            out.append({"q": q.tolist(), "R": R_from_q(q).tolist(),
                        "theta_so3": round(theta_so3(q), 9),
                        "s3_angle": round(s3_angle(a, q), 9), "seg": i,
                        "t": round(t, 6), "seg_s3_total": round(tot, 9)})
    qlast = qs[-1]
    out.append({"q": qlast.tolist(), "R": R_from_q(qlast).tolist(),
                "theta_so3": round(theta_so3(qlast), 9), "s3_angle": 0.0,
                "seg": len(qs) - 2 if len(qs) > 1 else 0, "t": 1.0, "seg_s3_total": 0.0})
    return out


def arc_length(trace) -> dict:
    """轨迹的 S³ 弧长 (= 物理转角之和的一半) —— 用于对照「算出来的轨迹」与「规划转角」。"""
    s3 = 0.0
    for i in range(1, len(trace)):
        s3 += s3_angle(trace[i - 1]["q"], trace[i]["q"])
    return {"s3_arc": round(s3, 12), "so3_sum_deg": round(np.degrees(2.0 * s3), 9),
            "n_points": len(trace)}


def resolution(step_deg=0.1, axis=(1, 0, 0)) -> dict:
    """尺子刻度: 物理 Δθ → S³ 步长(°) → 四元数分量差。线性区(θ≤π)内不允许饱和。"""
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    a = q_from_rotvec(np.radians(0.0) * axis)
    b = q_from_rotvec(np.radians(float(step_deg)) * axis)
    return {"step_deg": float(step_deg),
            "s3_deg": round(float(np.degrees(s3_angle(a, b))), 9),
            "dq_per_deg": round(float(np.linalg.norm(b - a) / max(step_deg, 1e-12)), 9),
            "expected_s3_deg": round(float(step_deg) / 2.0, 9)}


# ── 判据自检 ────────────────────────────────────────────────────────────────


def selftest(n=5000, seed=7) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    # ① 往返双射: 随机旋转 → q → R' , 误差 (机器精度)
    err = 0.0
    for _ in range(n):
        v = rng.normal(size=3)
        v = v / np.linalg.norm(v) * rng.uniform(0, np.pi)
        R = R_from_q(q_from_rotvec(v))
        R2 = R_from_q(q_from_rotvec(rotvec_from_q(q_from_R(R))))
        err = max(err, float(np.linalg.norm(R - R2)))
    out["roundtrip_max_err"] = err
    # ② 双覆盖商: canonical 幂等 + ±q 同解
    idem, same = True, True
    for _ in range(n):
        q = rng.normal(size=4)
        c = canonical(q)
        idem &= np.allclose(canonical(c), c, atol=1e-15, rtol=0)   # 归一化二次浮点 1 ulp 差 tolerated
        same &= np.allclose(canonical(-q), c, atol=1e-15, rtol=0)
        same &= np.allclose(R_from_q(-q), R_from_q(q), atol=1e-12)
    out["canonical_idempotent"] = bool(idem)
    out["double_cover_quotient"] = bool(same)
    # ③ 半角判据: 任意 q 到单位元的 S³ 夹角 × 2 == 该 q 的物理旋转角
    worst = 0.0
    for _ in range(n):
        q = q_from_rotvec(rng.normal(size=3) * rng.uniform(0, np.pi))
        worst = max(worst, abs(2.0 * s3_angle(np.array([1.0, 0, 0, 0]), q) - theta_so3(q)))
    out["half_angle_residual"] = worst
    # ④ 90° 旋转的 S³ 弧长必须 = 90°/2 = 45°
    q0 = np.array([1.0, 0, 0, 0])
    q1 = q_from_rotvec([np.pi / 2, 0, 0])
    out["s3_for_90deg_rotation_deg"] = round(float(np.degrees(s3_angle(q0, q1))), 9)
    # ⑤ 轨迹全程单位模长 + 端点精确
    tr = path([q0, q1, q_from_rotvec([0, np.pi / 3, 0])], n_per_seg=64)
    nrm = max(abs(float(np.linalg.norm(p["q"])) - 1.0) for p in tr)
    out["path_norm_max_err"] = nrm
    qs = [canonical(x) for x in (q0, q1, q_from_rotvec([0, np.pi / 3, 0]))]
    out["path_endpoints_exact"] = bool(np.allclose(tr[0]["q"], qs[0], atol=1e-15) and
                                       np.allclose(tr[-1]["q"], qs[-1], atol=1e-15))
    r = resolution(0.1)
    out["resolution_0p1deg"] = r
    out["ok"] = bool(err < 1e-12 and idem and same and nrm < 1e-12
                     and worst < 1e-9
                     and abs(out["s3_for_90deg_rotation_deg"] - 45.0) < 1e-9
                     and abs(r["s3_deg"] - r["expected_s3_deg"]) < 1e-9)
    return out


if __name__ == "__main__":
    import json
    r = selftest()
    print(json.dumps(r, ensure_ascii=False, indent=1))
