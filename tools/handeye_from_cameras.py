#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤝 用**现有固定轨迹**的建图数据解手眼 T_tcp_cam —— 不用标定板, 不用拖姿态。

输入(已存在, 零新增动作):
  ds_cov1114/cameras.json   每帧: T_cam2world(SfM 相机位姿) + pose[x,y,z,a,b,c](机器人 TCP 位姿)

原理 eye-in-hand  A X = X B:
  A = T_base_tcp_i^-1 · T_base_tcp_j    机器人相对运动
  B = T_cam2world_i^-1 · T_cam2world_j  SfM 相对运动
  → X = T_tcp_cam   (Park-Martin: 旋转用 SVD, 平移最小二乘；cv2 5.x 已无 calibrateHandEye)

验收(全自动):
  ① AX=XB 残差
  ② T_base_world 在 1149 帧上是否恒定(旋转/平移散度)  ← 这是真判据
  ③ 用解出的外参把 7 个槽位投影回画面, 看落在图像内的比例

输出 zmax_data/calib/handeye_tcp_cam.json
"""
import json
import math
import os
import time

import numpy as np

REPO = os.path.expanduser("~/zmax")
CAM = os.path.join(REPO, "zmax_data", "gs_rt", "ds_cov1114_local", "cameras.json")
TAUGHT = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
OUT = os.path.join(REPO, "zmax_data", "calib", "handeye_tcp_cam.json")


def Rz(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def Ry(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, 0, s], [0, 1.0, 0], [-s, 0, c]])


def Rx(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[1.0, 0, 0], [0, c, -s], [0, s, c]])


CONV = {
    "ZYX": lambda a, b, c: Rz(a) @ Ry(b) @ Rx(c),
    "XYZ": lambda a, b, c: Rx(a) @ Ry(b) @ Rz(c),
    "ZYX_rev": lambda a, b, c: Rx(c) @ Ry(b) @ Rz(a),
    "XZY": lambda a, b, c: Rx(a) @ Rz(b) @ Ry(c),
    "YXZ": lambda a, b, c: Ry(a) @ Rx(b) @ Rz(c),
}


def T_of(R, t):
    M = np.eye(4)
    M[:3, :3] = np.asarray(R, dtype=float)
    M[:3, 3] = np.asarray(t, dtype=float).ravel()
    return M


def logR(R):
    """旋转矩阵 → 旋转向量(rad)。"""
    R = np.asarray(R, dtype=float)
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    th = math.acos(c)
    if th < 1e-9:
        return np.zeros(3)
    if abs(math.pi - th) < 1e-6:                       # 接近 180°: 用对称部分
        w, V = np.linalg.eigh((R + np.eye(3)) / 2.0)
        v = V[:, int(np.argmax(w))]
        return v / np.linalg.norm(v) * th
    return th / (2.0 * math.sin(th)) * np.array(
        [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def solve_park_martin(pairs):
    """pairs: [(R_A, t_A, R_B, t_B)] → (R_X, t_X)

    ⚠️ SfM 的平移是**未定尺度**的(单目/COLMAP 常规), 所以不能直接解 t_X:
    先解旋转(Park-Martin SVD), 再把尺度 s 与 t_X 一起线性解出来:
        (R_A − I) t_X − s·(R_X t_B) = −t_A
    """
    M = np.zeros((3, 3))
    for Ra, ta, Rb, tb in pairs:
        M += np.outer(logR(Rb), logR(Ra))
    U, S, Vt = np.linalg.svd(M)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    RX = Vt.T @ D @ U.T

    # 旋转准不准: 先看这个(尺度不影响旋转)
    rot_err = []
    for Ra, ta, Rb, tb in pairs:
        dR = (Ra @ RX).T @ (RX @ Rb)
        rot_err.append(math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(dR) - 1) / 2)))))

    A_lin, b = [], []
    for Ra, ta, Rb, tb in pairs:
        A_lin.append(np.hstack([Ra - np.eye(3), -(RX @ tb).reshape(3, 1)]))
        b.append(-ta.ravel())
    A_lin = np.vstack(A_lin)
    b = np.hstack(b)
    sol, *_ = np.linalg.lstsq(A_lin, b, rcond=None)
    tX, s = sol[:3], float(sol[3])
    return RX, tX, float(np.mean(rot_err)), s


def residuals(pairs, RX, tX):
    ang, tr = [], []
    for Ra, ta, Rb, tb in pairs:
        R1 = Ra @ RX
        R2 = RX @ Rb
        dR = R1.T @ R2
        ang.append(math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(dR) - 1) / 2)))))
        e = (Ra @ tX + ta.ravel()) - (RX @ tb.ravel() + tX)
        tr.append(float(np.linalg.norm(e)))
    return float(np.mean(ang)), float(np.mean(tr))


def main():
    d = json.load(open(CAM, encoding="utf-8"))
    K = np.array(d["K"], dtype=float)
    frames = []
    for f in d["frames"]:
        p = f["pose"]
        frames.append({"file": f.get("file"), "Tc2w": np.array(f["T_cam2world"], dtype=float),
                       "p": np.array(p[:3], dtype=float), "abc": np.array(p[3:6], dtype=float)})
    # 只取运动量够大的帧对(否则 A、B 都近似单位阵, 无信息)
    step = 8
    print("数据: %d 帧成对(SfM 相机位姿 ⇄ 机器人 TCP 位姿)" % len(frames))
    best = None
    for name, mk in CONV.items():
        Tb = [T_of(mk(*f["abc"]), f["p"]) for f in frames]
        pairs = []
        for i in range(0, len(frames) - step, step):
            j = i + step
            A = np.linalg.inv(Tb[i]) @ Tb[j]
            B = np.linalg.inv(frames[i]["Tc2w"]) @ frames[j]["Tc2w"]
            if np.linalg.norm(logR(A[:3, :3])) < 0.05:      # 机器人几乎没动, 丢掉
                continue
            if np.linalg.norm(logR(B[:3, :3])) < 0.05:
                continue
            pairs.append((A[:3, :3], A[:3, 3], B[:3, :3], B[:3, 3]))
        if len(pairs) < 8:
            continue
        RX, tX, a_err, s = solve_park_martin(pairs)
        # T_base_world 一致性: SfM 平移按解出的尺度 s 还原成米
        X = T_of(RX, tX)
        Tw2b = []
        for T, f in zip(Tb, frames):
            Tc = f["Tc2w"].copy()
            Tc[:3, 3] *= s
            Tw2b.append(T @ X @ Tc)
        Ps = np.array([M[:3, 3] for M in Tw2b])
        spread_t = float(np.linalg.norm(Ps - Ps.mean(axis=0), axis=1).mean())
        Rm = [M[:3, :3] for M in Tw2b]
        angs = [math.degrees(math.acos(max(-1.0, min(1.0, (Rm[0].T @ Rr).trace() - 1) / 2))) for Rr in Rm]
        spread_r = float(np.mean(angs))
        score = spread_t * 1000 + spread_r * 10
        print("  %-8s 对 %3d · 旋转残差 %.3f° · 尺度 s=%.3f · T_base_world 散度 %.1fmm / %.2f°"
              % (name, len(pairs), a_err, s, spread_t * 1000, spread_r))
        if best is None or score < best["score"]:
            best = {"conv": name, "RX": RX, "tX": tX, "a_err": a_err, "scale": s,
                    "spread_t": spread_t, "spread_r": spread_r, "score": score,
                    "n_pairs": len(pairs), "Tw2b": Ps.mean(axis=0), "X": X}

    if not best:
        print("❌ 解算失败(可用帧对不足)")
        return 1

    print("-" * 76)
    print("最优: 欧拉 %s · 帧对 %d" % (best["conv"], best["n_pairs"]))
    print("  AX=XB 残差        %.3f° / %.2f mm" % (best["a_err"], best["t_err"] * 1000))
    print("  T_base_world 散度 %.2f mm / %.3f°  ← 越接近 0 越对" % (best["spread_t"] * 1000, best["spread_r"]))
    print("  T_tcp_cam 平移    [%.1f, %.1f, %.1f] mm" % tuple(best["tX"] * 1000))
    print("  T_tcp_cam 旋转\n" + np.array2string(best["RX"], precision=5, suppress_small=True))

    # ③ 投影验证
    tp = json.load(open(TAUGHT, encoding="utf-8"))["points"]
    slots = [(k, np.array(tp[k]["pos"][:3], dtype=float)) for k in
             ("slot1", "slot2", "slot3", "slot4", "slot5", "slot6", "slot7") if k in tp]
    mk = CONV[best["conv"]]
    W, H = int(K[0, 2] * 2), int(K[1, 2] * 2)
    n_in = n_tot = 0
    print("-" * 76)
    print("投影验证: 槽位投到像素, 落在 640x480 内的算看到")
    for f in frames[:800:100]:
        Tb = T_of(mk(*f["abc"]), f["p"])
        inv = np.linalg.inv(Tb @ best["X"])
        vis = []
        for name, sp in slots:
            pc = inv @ np.append(sp, 1.0)
            n_tot += 1
            if pc[2] <= 0.05:
                continue
            uv = K @ (pc[:3] / pc[2])
            if 0 <= uv[0] < W and 0 <= uv[1] < H:
                vis.append(name)
                n_in += 1
        print("  %-22s 视野内 %d/7 %s" % (str(f["file"])[:22], len(vis), ",".join(vis)[:36]))
    print("-" * 76)
    print("合计: 槽位投影落在画面内 %d/%d (%.0f%%)" % (n_in, n_tot, 100.0 * n_in / max(1, n_tot)))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "source": "ds_cov1114/cameras.json (SfM 相机位姿 + 机器人 TCP 位姿 成对, 现有固定轨迹)",
               "euler_conv": best["conv"], "solver": "Park-Martin (SVD + 最小二乘)",
               "n_pairs": best["n_pairs"], "T_tcp_cam": best["X"].tolist(),
               "R_tcp_cam": best["RX"].tolist(), "t_tcp_cam_m": best["tX"].ravel().tolist(),
               "T_base_world_mean_m": best["Tw2b"].tolist(),
               "residual": {"axxb_rot_deg": round(best["a_err"], 4),
                            "axxb_trans_mm": round(best["t_err"] * 1000, 3),
                            "consistent_trans_mm": round(best["spread_t"] * 1000, 3),
                            "consistent_rot_deg": round(best["spread_r"], 4)},
               "note": "零新增动作: 直接用现有 215 点轨迹的建图数据解出; 判据=T_base_world 恒定"},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("已写 %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
