"""AX = XB (eye-in-hand) 解算 — 纯 numpy, 不依赖 cv2.calibrateHandEye。

用途: 手上有「相机相对运动 B」与「机器人相对运动 A」的成对数据时求 X = T_tcp_cam。
覆盖两种来源:
  ① 标定板 / 已知目标: A、B 平移都是米 ⇒ scale=None
  ② SfM(COLMAP 类)相机位姿: 平移**未定尺度** ⇒ scale="auto", 与 t_X 联合线性解

用法(在仓库里做一次性分析时直接 import):
    from axxb_park_martin import solve_axxb, check_by_consistency
    X, info = solve_axxb(pairs, scale="auto")
    spread = check_by_consistency(T_base_tcp_list, X, T_cam2world_list)   # 旋转/平移散度

判据: 解对时 check_by_consistency 的平移散度 ~mm、旋转散度 ~0.1°;
     解错时常见 300~1000mm / 85~100° —— 先看这个数, 再看投影。
"""

import math

import numpy as np


def logR(R):
    """旋转矩阵 → 旋转向量(rad)。"""
    R = np.asarray(R, dtype=float)
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    th = math.acos(c)
    if th < 1e-9:
        return np.zeros(3)
    if abs(math.pi - th) < 1e-6:                      # 接近 180°: 用对称部分取轴
        w, V = np.linalg.eigh((R + np.eye(3)) / 2.0)
        v = V[:, int(np.argmax(w))]
        return v / np.linalg.norm(v) * th
    return th / (2.0 * math.sin(th)) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def solve_axxb(pairs, scale=None):
    """pairs: [(R_A, t_A, R_B, t_B)] — 同一对之间的相对运动。

    scale=None    : 平移已是同单位(米/毫米都行, 换算自便)
    scale="auto"  : B 的平移尺度未知, 与 t_X 一起解
    scale=<float> : 已知尺度(把 B 的平移乘以它变成与 A 同单位)

    返回 (X(4x4), info)
    """
    M = np.zeros((3, 3))
    for Ra, _ta, Rb, _tb in pairs:
        M += np.outer(logR(Rb), logR(Ra))
    U, S, Vt = np.linalg.svd(M)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    RX = Vt.T @ D @ U.T                              # Park-Martin 旋转解

    rot_err = [math.degrees(math.acos(max(-1.0, min(1.0, (
        (Ra @ RX).T @ (RX @ Rb)).trace() - 1) / 2))) for Ra, _a, Rb, _b in pairs]

    A_lin, b = [], []
    auto = (scale == "auto")
    s = 1.0 if scale in (None, "auto") else float(scale)
    for Ra, ta, Rb, tb in pairs:
        block = [Ra - np.eye(3)]
        if auto:
            block.append(-(RX @ np.asarray(tb, float)).reshape(3, 1))
        A_lin.append(np.hstack(block[:1] + block[1:]) if auto else np.hstack(block))
        b.append(-np.asarray(ta, float).ravel())
    sol, *_ = np.linalg.lstsq(np.vstack(A_lin), np.hstack(b), rcond=None)
    tX = sol[:3]
    if auto:
        s = float(sol[3])

    X = np.eye(4)
    X[:3, :3] = RX
    X[:3, 3] = tX
    info = {"rot_err_deg": float(np.mean(rot_err)), "scale": s,
            "n_pairs": len(pairs),
            "t_tcp_cam_mm": (tX * 1000.0).tolist() if abs(tX).max() < 10 else tX.tolist()}
    return X, info


def check_by_consistency(T_base_tcp, X, T_cam2world, scale=None):
    """验收: T_base_world = T_base_tcp · X · T_cam2world 应在全部帧上恒定。"""
    Tw2b = []
    for T, Tc in zip(T_base_tcp, T_cam2world):
        Tc = np.array(Tc, dtype=float, copy=True)
        if scale is not None:
            Tc[:3, 3] *= float(scale)
        Tw2b.append(np.asarray(T, float) @ X @ Tc)
    Ps = np.array([M[:3, 3] for M in Tw2b])
    R0 = Tw2b[0][:3, :3]
    ang = [math.degrees(math.acos(max(-1.0, min(1.0, ((R0.T @ M[:3, :3]).trace() - 1) / 2))))
           for M in Tw2b]
    return {"trans_spread_mm": float(np.linalg.norm(Ps - Ps.mean(axis=0), axis=1).mean() * 1000),
            "rot_spread_deg": float(np.mean(ang)),
            "T_base_world_mean": Ps.mean(axis=0).tolist()}


def pairing_quality(p_robot, t_cam2world, step=7, k=12):
    """可解性预检: 机器人位姿与 SfM 相机位置的**成对距离相关系数**。

    r > 0.98 ⇒ 两套位姿确实来自同一次采集, 可以解手眼。
    实测 r=0.611 时无论换哪种欧拉约定都解不对 ⇒ 这批数据不能用来标定。
    """
    P = np.asarray(p_robot, float)
    C = np.asarray([np.asarray(t, float)[:3, 3] for t in t_cam2world])
    dr, dc = [], []
    for a in range(0, len(P), step):
        for b in range(a + 1, min(a + 1 + k, len(P)), step):
            dr.append(np.linalg.norm(P[a] - P[b]))
            dc.append(np.linalg.norm(C[a] - C[b]))
    dr, dc = np.array(dr), np.array(dc)
    r = float(np.corrcoef(dr, dc)[0, 1]) if len(dr) > 3 else float("nan")
    s = float((dr * dc).sum() / max(1e-9, (dc * dc).sum()))
    return {"r": r, "scale": s, "median_resid_mm": float(np.median(np.abs(dr - s * dc)) * 1000),
            "usable": bool(r > 0.98)}


if __name__ == "__main__":
    print(__doc__)
