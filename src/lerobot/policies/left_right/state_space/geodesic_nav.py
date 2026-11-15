# -*- coding: utf-8 -*-
"""🧭 测地线导航 (L2 规划引导的算法本体)

老倪 2026-11-15「所有 L2 节点的算法都要迁到 state_space 这个路径下」——
测地线原本长在 `manifold/manifold_engine.py::Navigator.compute_geodesic`, 现在**本体在这里**,
引擎那侧只保留一个转发 (manifold_engine.Navigator.compute_geodesic → 本模块), 免得两份实现漂移。

口径 (与引擎逐位一致, 换位置不改行为):
  sphere / su2 : 归一化球面大圆 slerp (su2 先同叶)
  so3          : 旋转矩阵四元数 slerp
  se3          : R 用 slerp、平移线性插值 (p 至少 12 维: 9 旋转 + 3 平移)
  torus        : 逐轴最短环绕
  其他         : 线性插值
长度 = 沿路径逐段测地距离累加; end_error = 末点与目标的测地距离。
"""
from __future__ import annotations

import numpy as np

GEODESIC_KINDS = {
    "sphere": "大圆 (slerp)",
    "su2": "大圆 (slerp, 同叶)",
    "so3": "四元数 slerp",
    "se3": "螺旋 (R slerp + t 线性)",
    "torus": "环绕最短",
}


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def slerp_unit(p0: np.ndarray, p1: np.ndarray, t: float) -> np.ndarray:
    p0, p1 = unit(np.asarray(p0, float).ravel()), unit(np.asarray(p1, float).ravel())
    d = float(np.clip(np.dot(p0, p1), -1.0, 1.0))
    if d > 0.9995:
        return unit((1 - t) * p0 + t * p1)
    th = np.arccos(d)
    return unit(np.sin((1 - t) * th) / np.sin(th) * p0 + np.sin(t * th) / np.sin(th) * p1)


def slerp_R(R0: np.ndarray, R1: np.ndarray, t: float) -> np.ndarray:
    """SO(3) 测地插值: 位姿里带四元数工具时走四元数 slerp, 否则 SVD 正交化兜底。"""
    try:
        from lerobot.manifold.lie_intent import quat_from_R, R_from_quat          # noqa: PLC0415
        q0, q1 = quat_from_R(np.asarray(R0, float)), quat_from_R(np.asarray(R1, float))
        if float(np.dot(q0, q1)) < 0:
            q1 = -q1
        return R_from_quat(slerp_unit(q0, q1, t))
    except Exception:                                                       # noqa: BLE001
        U, _, Vt = np.linalg.svd((1 - t) * np.asarray(R0, float) + t * np.asarray(R1, float))
        return U @ Vt


def distance(p: np.ndarray, q: np.ndarray, manifold_type: str = "sphere") -> float:
    """测地距离 (各流形自己的口径)。"""
    p = np.asarray(p, float).ravel()
    q = np.asarray(q, float).ravel()
    t = manifold_type
    if t in ("sphere", "su2"):
        pn, qn = unit(p), unit(q)
        c = float(np.clip(abs(float(np.dot(pn, qn))), -1.0, 1.0))
        return float(np.arccos(c))
    if t == "torus":
        d = np.mod(q - p + np.pi, 2 * np.pi) - np.pi
        return float(np.linalg.norm(d))
    if t in ("so3", "se3") and p.size >= 9 and q.size >= 9:
        R0 = p[:9].reshape(3, 3)
        R1 = q[:9].reshape(3, 3)
        tr = float(np.trace(R0.T @ R1))
        ang = float(np.arccos(np.clip((tr - 1.0) / 2.0, -1.0, 1.0)))
        if t == "se3" and p.size >= 12 and q.size >= 12:
            return float(np.sqrt(ang ** 2 + float(np.sum((q[9:12] - p[9:12]) ** 2))))
        return ang
    return float(np.linalg.norm(q - p))


def compute_geodesic(p0, pT, T: int = 16, manifold_type: str = "sphere") -> dict:
    """起点→终点的测地路径 (T 个点) + 真弧长 + 末端误差。"""
    p0, pT = np.asarray(p0, float).ravel(), np.asarray(pT, float).ravel()
    T = max(2, int(T))
    ts = np.linspace(0.0, 1.0, T)
    t = manifold_type
    path = []
    for a in ts:
        if t in ("sphere", "su2"):
            path.append(slerp_unit(p0, pT, float(a)))
        elif t in ("so3", "se3"):
            if t == "se3" and p0.size >= 12:
                R = slerp_R(p0[:9].reshape(3, 3), pT[:9].reshape(3, 3), float(a))
                tt = (1 - a) * p0[9:12] + a * pT[9:12]
                path.append(np.concatenate([R.ravel(), tt]))
            else:
                path.append(slerp_R(p0.reshape(3, 3), pT.reshape(3, 3), float(a)).ravel())
        elif t == "torus":
            d = np.mod(pT - p0 + np.pi, 2 * np.pi) - np.pi
            path.append(np.mod(p0 + a * d, 2 * np.pi))
        else:
            path.append((1 - a) * p0 + a * pT)
    path = np.asarray(path)
    L = 0.0
    for i in range(len(path) - 1):
        L += distance(path[i], path[i + 1], t)
    return {"path": path, "n": T, "length": round(float(L), 6),
            "end_error": round(float(distance(path[-1], pT, t)), 6),
            "geodesic_kind": GEODESIC_KINDS.get(t, "直线")}
