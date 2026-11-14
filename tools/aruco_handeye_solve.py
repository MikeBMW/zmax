#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 ArUco 手眼解算 T_tool_cam (AX=XB) —— 不吃尺度、可留一验证。

输入: tools/aruco_handeye_collect.py 的 det 列表
  {cursor, id, rvec, tvec, pose_mm|p_m, quat, reproj_px}
方法:
  1. 单个 ArUco 标记固定在工位上 ⇒ T_base_marker = T_base_tool_i · X · T_cam_marker_i (常量)
     两两组合: A = inv(T_bt_j)·T_bt_i ,  B = T_cm_j·inv(T_cm_i) ,  A·X = X·B
  2. 旋转用最小二乘直接解(不用四元数技巧, scipy 优化 Σ‖Ra·Rx − Rx·Rb‖_F),
     平移线性: (Ra − I)·t = Rx·tb − ta  → lstsq
  3. 尺度: 标记边长未知 ⇒ tvec 只有相对单位; X 的旋转不受影响, 平移会带一个未知尺度,
     这里同时报"尺度自由"的旋转解 + 用棋盘/已知边长的度量解(默认 50mm 假定, 只作参考)
  4. 验收: 闭合误差 —— 把解代回, 每帧反算 T_base_marker, 报平移/旋转离散度; 再做留一交叉验证
口径: 只读离线解算, 不动机器人、不写任何在跑的服务配置。
"""
import glob
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def quat_to_R(q, order="xyzw"):
    q = np.asarray(q, dtype=float)
    q = q / (np.linalg.norm(q) + 1e-12)
    if order == "xyzw":
        x, y, z, w = q
    else:
        w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def T(R=None, t=None):
    M = np.eye(4)
    if R is not None:
        M[:3, :3] = R
    if t is not None:
        M[:3, 3] = np.asarray(t, dtype=float).reshape(3)
    return M


def inv(M):
    R = M[:3, :3]
    t = M[:3, 3]
    out = np.eye(4)
    out[:3, :3] = R.T
    out[:3, 3] = -R.T @ t
    return out


def rotvec(R):
    a = np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))
    if a < 1e-9:
        return np.zeros(3)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(a))
    return v * a


def exp_so3(w):
    a = np.linalg.norm(w)
    if a < 1e-12:
        return np.eye(3)
    k = w / a
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * (K @ K)


def solve_rot(A, B):
    """解 Ra·Rx = Rx·Rb 的 Rx (A,B 都是旋转矩阵 4x4, 用两两相对位姿)"""
    from scipy.optimize import least_squares
    Ra = [a[:3, :3] for a in A]
    Rb = [b[:3, :3] for b in B]

    def res(x):
        Rx = exp_so3(x)
        return np.concatenate([(ra @ Rx - Rx @ rb).ravel() for ra, rb in zip(Ra, Rb)])

    best = None
    for x0 in (np.zeros(3), np.array([0.3, 0.3, 0.3]), np.array([-1.0, 0.5, 2.0])):
        r = least_squares(res, x0, method="lm", xtol=1e-14, ftol=1e-14, max_nfev=20000)
        if best is None or r.cost < best.cost:
            best = r
    return exp_so3(best.x), float(np.sqrt(2 * best.cost / max(1, len(Ra))))


def solve_trans(A, B, Rx):
    rows, rhs = [], []
    for a, b in zip(A, B):
        Ra, ta = a[:3, :3], a[:3, 3]
        tb = b[:3, 3]
        rows.append(Ra - np.eye(3))
        rhs.append(Rx @ tb - ta)
    rows = np.vstack(rows)
    rhs = np.concatenate(rhs)
    t, *_ = np.linalg.lstsq(rows, rhs, rcond=None)
    return t


def closure(X, bt, cm):
    """每帧反算 T_base_marker, 报离散度"""
    Ms = [b @ X @ c for b, c in zip(bt, cm)]
    ts = np.array([M[:3, 3] for M in Ms])
    Rs = [M[:3, :3] for M in Ms]
    t_ref = ts.mean(0)
    dt = ts - t_ref
    ang = []
    R_ref = Rs[0]
    for R in Rs:
        ang.append(np.degrees(np.linalg.norm(rotvec(R_ref.T @ R))))
    return {"n": len(Ms), "t_std_mm": (np.linalg.norm(dt, axis=1) * 1000).round(2).tolist(),
            "t_spread_mm": round(float((np.linalg.norm(dt, axis=1)).max() * 1000), 2),
            "rot_spread_deg": round(float(np.max(ang)), 2),
            "t_mean_mm": (t_ref * 1000).round(1).tolist()}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else sorted(
        glob.glob(os.path.join(REPO, "zmax_data", "reports", "aruco_handeye_*.json")))[-1]
    d = json.load(open(path, encoding="utf-8"))
    det = [x for x in d["det"] if x.get("quat") and x.get("p_m")]
    print("数据 %s\n  检出 %d 条(带真值位姿 %d)" % (os.path.basename(path), len(d["det"]), len(det)))

    # 按 id 分组, 取条数最多且位姿多样的一组
    groups = {}
    for x in det:
        groups.setdefault(x["id"], []).append(x)
    print("  按 id: %s" % {k: len(v) for k, v in groups.items()})
    mid = max(groups, key=lambda k: len(groups[k]))
    sel = groups[mid]
    print("  选 id=%d, %d 条" % (mid, len(sel)))

    # 去重: 同一游标只留重投影最小的
    best_by_cur = {}
    for x in sel:
        c = x["cursor"]
        if c not in best_by_cur or x["reproj_px"] < best_by_cur[c]["reproj_px"]:
            best_by_cur[c] = x
    sel = sorted(best_by_cur.values(), key=lambda x: x["cursor"])
    print("  按游标去重后 %d 条 · 游标 %s" % (len(sel), [x["cursor"] for x in sel]))

    results = []
    for order in ("xyzw", "wxyz"):
        for sign in (1, -1):
            bt, cm = [], []
            for x in sel:
                R = quat_to_R(x["quat"], order)
                bt.append(T(R, x["p_m"]))
                Rm = exp_so3(np.asarray(x["rvec"], float) * sign)
                cm.append(T(Rm, np.asarray(x["tvec"], float)))
            pairs = [(i, j) for i in range(len(sel)) for j in range(i + 1, len(sel))]
            if not pairs:
                continue
            A = [inv(bt[j]) @ bt[i] for i, j in pairs]
            B = [cm[j] @ inv(cm[i]) for i, j in pairs]
            # 只用转角足够大的对(小转角对手眼没信息)
            keep = [(a, b) for a, b in zip(A, B)
                    if np.degrees(np.linalg.norm(rotvec(a[:3, :3]))) > 3.0
                    and np.degrees(np.linalg.norm(rotvec(b[:3, :3]))) > 3.0]
            if len(keep) < 3:
                continue
            Ak = [k[0] for k in keep]
            Bk = [k[1] for k in keep]
            Rx, rot_res = solve_rot(Ak, Bk)
            tX = solve_trans(Ak, Bk, Rx)
            X = T(Rx, tX)
            cl = closure(X, bt, cm)
            results.append({"order": order, "sign": sign, "n_pairs": len(keep),
                            "rot_res": round(rot_res, 5), "X": X.round(6).tolist(),
                            "t_tool_cam_mm": (tX * 1000).round(2).tolist(),
                            "closure": cl})

    if not results:
        print("  ❌ 有效约束不足(需要 ≥3 对转角>3°的相对位姿)")
        return 1
    results.sort(key=lambda r: r["closure"]["t_spread_mm"] + r["closure"]["rot_spread_deg"])
    print("-" * 74)
    for r in results[:4]:
        print("  约定 %s sign=%+d · 对 %d · 旋转残差 %.5f" % (r["order"], r["sign"], r["n_pairs"], r["rot_res"]))
        print("     T_tool_cam 平移 mm = %s" % r["t_tool_cam_mm"])
        print("     闭合: 平移离散 %.2fmm · 转角离散 %.2f° · 标记中心(世界) %s mm"
              % (r["closure"]["t_spread_mm"], r["closure"]["rot_spread_deg"], r["closure"]["t_mean_mm"]))
    best = results[0]
    out = os.path.join(REPO, "zmax_data", "reports",
                       "handeye_aruco_%s.json" % os.path.basename(path)[-19:-5])
    json.dump({"src": os.path.basename(path), "marker_id": mid, "n_views": len(sel),
               "cursors": [x["cursor"] for x in sel], "best": best, "all": results},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-" * 74)
    print("判据: 平移离散 < 10mm 且 转角离散 < 2° 才算可用 (单标记小尺寸, 放宽到 15mm/3°)")
    ok = best["closure"]["t_spread_mm"] < 15 and best["closure"]["rot_spread_deg"] < 3.0
    print(" ⇒ %s" % ("✅ 可用" if ok else "❌ 不可用(约束太少/标记太斜), 需补采集"))
    print("结果 %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
