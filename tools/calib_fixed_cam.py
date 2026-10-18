#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_fixed_cam.py —— 固定相机(笔记本 USB D435)外参自动标定

为什么这样标（老倪 2026-10-18: 「自动化跑吧，而且我给你前面放了一个标定板子，你自己标定吧」）：

固定相机没有手眼，硬要 6 个已知 base 3D 点。板子能给像素，但**板的物理尺寸/位置未知**，
所以用已标定的臂上相机做"米级锚"：

  ① 腕相机在 ≥2 个位姿看同一块 ArUco 板 → 每帧 PnP 得到"单位尺寸下的板位姿"
     ⇒ 板中心 P_i = C_i + R_i·(t_i·s) 必须处处相等 ⇒ 线性最小二乘解出 **真实边长 s**
     ⇒ 得到板在 base 系的位姿（米级，不靠任何标称尺寸）
  ② 固定相机看同一个 marker → 用已知 s 做 PnP ⇒ T_cam_marker
  ③ T_base_cam = T_base_marker @ inv(T_cam_marker)
  ④ 验收: 把 base 系点投回固定相机像素，报重投影 rmse；再画一张叠加图留证

用法:
  ./gui-venv311/bin/python tools/calib_fixed_cam.py --wrist views.json --fixed d435.jpg --out data/scene/cam_calib.json --key local2
views.json = [{"img": "path.jpg", "tcp": {"xyz":[m,m,m], "abc_rad":[r,r,r]}}, ...]
可选 --marker-mm 50   直接给定边长(跳过①的 s 反解, 但仍用它做交叉核对)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

ARUCO_DICTS = ["DICT_ARUCO_ORIGINAL", "DICT_4X4_50", "DICT_5X5_50", "DICT_6X6_50", "DICT_7X7_50",
               "DICT_4X4_100", "DICT_5X5_100"]


def _detector():
    ps = cv2.aruco.DetectorParameters()
    ps.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    ps.adaptiveThreshWinSizeMin = 3
    ps.adaptiveThreshWinSizeMax = 41
    ps.minMarkerPerimeterRate = 0.01
    return ps


def find_markers(img, ids_want=None):
    """在所有常见字典里找 marker，返回 {id: (dict_name, corners4x2)}。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    out = {}
    ps = _detector()
    for name in ARUCO_DICTS:
        dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))
        det = cv2.aruco.ArucoDetector(dic, ps)
        c, ids, _ = det.detectMarkers(g)
        if ids is None:
            continue
        for cc, i in zip(c, ids.ravel()):
            i = int(i)
            if ids_want is not None and i not in ids_want:
                continue
            if i not in out:
                out[i] = (name, cc.reshape(4, 2).astype(np.float64))
    return out


def marker_obj_pts(s_mm):
    """ArUco 单标记物点(标记自身坐标, 原点=左上角, z=0, 单位 mm)。"""
    return np.array([[0, 0, 0], [s_mm, 0, 0], [s_mm, s_mm, 0], [0, s_mm, 0]], np.float64)


def pnp(img_pts, K, dist, s_mm):
    ok, rvec, tvec = cv2.solvePnP(marker_obj_pts(s_mm), img_pts.astype(np.float64), K, dist,
                                  flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None
    proj, _ = cv2.projectPoints(marker_obj_pts(s_mm), rvec, tvec, K, dist)
    rmse = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img_pts) ** 2, axis=1))))
    return rvec.reshape(3), tvec.reshape(3), rmse


def T_from_rvec_t(rvec, t):
    R, _ = cv2.Rodrigues(np.asarray(rvec, float))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = np.asarray(t, float)
    return T


def camera_pose_from_tcp(tcp):
    """臂上相机: T_base_cam。用与 opt_box3d.camera_pose 完全同一口径(手眼标定文件)。"""
    import opt_box3d as OB
    T_bc, T_bt, he = OB.camera_pose(tcp)
    return T_bc, T_bt, he


def intrinsics_for(kind):
    if kind == "wrist":
        import opt_box3d as OB
        return OB.intrinsics()
    p = os.path.join(REPO, "data", "scene", "cam_calib.json")
    d = json.load(open(p, encoding="utf-8"))
    e = d.get("local2") or {}
    if not e.get("f"):
        raise SystemExit("固定相机内参缺失: %s 里没有 local2.f/cx/cy" % p)
    f, cx, cy = float(e["f"]), float(e["cx"]), float(e["cy"])
    return np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], float), np.zeros(5)


def solve_scale_from_views(views, mid):
    """用腕相机多视图解 marker 真实边长 s (mm)。
    每视图: 单位尺寸 PnP ⇒ 板左上角在相机系 = t_i(单位) ; 板左上角在 base = T_bc·t_i
    若单位尺寸=1(mm), 则真实点 P = C_i + R_i·(s·t_i)。取前两视图做差求 s，再多视最小二乘。"""
    eqs = []
    data = []
    for v in views:
        if mid not in v["markers"]:
            continue
        T_bc, T_bt, _ = camera_pose_from_tcp(v["tcp"])
        s1 = 1.0
        p = pnp(v["markers"][mid][1], v["K"], v["dist"], s1)
        if not p:
            continue
        rvec, tvec, rmse = p
        if rmse > 2.0:
            continue
        R = cv2.Rodrigues(rvec)[0]
        C = T_bc[:3, 3]
        Rb = T_bc[:3, :3]
        # base 系里: P = C + Rb·(R·(s·t))  ⇒ 方向向量 d = Rb·R·t, 基准点 C
        d = Rb @ (R @ tvec)
        data.append((C, d, v["img"], rmse))
    if len(data) < 2:
        return None, data
    # 两两求 s: C1 + s·d1 = C2 + s·d2 ⇒ s·(d1-d2) = C2-C1 ⇒ 最小二乘
    num = 0.0
    den = 0.0
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            dd = data[i][1] - data[j][1]
            cc = data[j][0] - data[i][0]
            num += float(dd @ cc)
            den += float(dd @ dd)
    s = num / den if abs(den) > 1e-9 else None
    return s, data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wrist", help="腕相机多视图清单 json")
    ap.add_argument("--fixed", help="固定相机图像")
    ap.add_argument("--marker-mm", type=float, default=None)
    ap.add_argument("--out", default=os.path.join(REPO, "data", "scene", "cam_calib.json"))
    ap.add_argument("--key", default="local2")
    ap.add_argument("--proof", default=os.path.join(REPO, "zmax_data", "calib_d435", "d435_calib_proof.png"))
    ap.add_argument("--tcp", help="验证用: 当前 TCP json 文件(把 TCP 投到固定相机上看对不对)")
    a = ap.parse_args()

    views = []
    if a.wrist:
        for v in json.load(open(a.wrist, encoding="utf-8")):
            img = cv2.imread(v["img"])
            if img is None:
                print("跳过(读不到图):", v["img"])
                continue
            K, dist = intrinsics_for("wrist")
            v.update(img=img, K=K, dist=dist, markers=find_markers(img))
            views.append(v)
            print("腕视图 %-40s marker=%s" % (os.path.basename(v["img"]), sorted(v["markers"])))
    mids = sorted({m for v in views for m in v["markers"]})
    if not mids:
        print("腕相机视图里没有 marker ⇒ 无法给固定相机做米级锚")
        return 2
    mid = mids[0]
    print("用 marker id =", mid)

    s_mm = a.marker_mm
    if s_mm is None:
        s_solved, data = solve_scale_from_views(views, mid)
        print("① 由 %d 个腕视图反解 marker 边长 = %s mm" % (len(data), None if s_solved is None else round(s_solved, 2)))
        if s_solved and not (5 < s_solved < 500):
            print("   ⚠ 边长解不合理(%.1fmm)，检查视图/内参" % s_solved)
        s_mm = s_solved
    else:
        print("① 给定 marker 边长 = %.2f mm" % s_mm)
    if not s_mm:
        return 3

    # 板在 base 系的 3D 点(用腕相机各视图解 + 平均)
    base_pts = []
    for v in views:
        if mid not in v["markers"]:
            continue
        p = pnp(v["markers"][mid][1], v["K"], v["dist"], s_mm)
        if not p:
            continue
        rvec, tvec, rmse = p
        T_bc, T_bt, _ = camera_pose_from_tcp(v["tcp"])
        T_cm = T_from_rvec_t(rvec, tvec)
        T_bm = T_bc @ T_cm
        base_pts.append(T_bm)
        print("   腕视图 %s: 重投影 %.2fpx · 板中心 base=%s" % (
            os.path.basename(v["img"]), rmse, np.round(T_bm[:3, 3] + T_bm[:3, :3] @ np.array([s_mm / 2, s_mm / 2, 0]), 1)))
    if not base_pts:
        print("腕相机 PnP 全失败")
        return 4
    # 取中位(逐元素)作为板位姿: 位置取中位, 旋转取第一帧(角度平均更麻烦, 视图间通常差很小)
    centers = np.array([T[:3, 3] for T in base_pts])
    spread = centers.max(0) - centers.min(0)
    print("② 板位姿在 base 系的一致性: 位置极差 = %s mm" % np.round(spread, 2))
    T_bm = base_pts[0].copy()
    T_bm[:3, 3] = np.median(centers, axis=0)

    if not a.fixed:
        return 0
    img_f = cv2.imread(a.fixed)
    mk = find_markers(img_f)
    print("③ 固定相机检出:", {k: v[0] for k, v in mk.items()})
    if mid not in mk:
        print("固定相机里没有 id=%d 的 marker" % mid)
        return 5
    K2, d2 = intrinsics_for("fixed")
    p = pnp(mk[mid][1], K2, d2, s_mm)
    if not p:
        print("固定相机 PnP 失败")
        return 6
    rvec2, tvec2, rmse2 = p
    T_cm2 = T_from_rvec_t(rvec2, tvec2)
    print("   固定相机 marker 重投影 %.2fpx · 距离 %.1fmm" % (rmse2, float(np.linalg.norm(tvec2))))
    T_bc2 = T_bm @ np.linalg.inv(T_cm2)

    # 相机光心应在台面之上 (z>0)
    C = T_bc2[:3, 3]
    print("④ T_base_cam: 光心 = %s mm  (台面 z=0, 应 z>0)" % np.round(C, 1))
    if C[2] <= 0:
        print("   ⚠ 光心在台面以下 ⇒ 解错了")
        return 7

    # 验收: 把板角点投回固定相机
    corners3 = []
    for q in marker_obj_pts(s_mm):
        corners3.append((T_bm @ np.array([q[0], q[1], q[2], 1.0]))[:3])
    proj, _ = cv2.projectPoints(np.array(corners3), cv2.Rodrigues(T_bc2[:3, :3])[0].ravel(),
                                T_bc2[:3, 3], K2, d2)
    err = np.linalg.norm(proj.reshape(-1, 2) - mk[mid][1], axis=1)
    print("⑤ 独立验收(板角点 base→固定相机像素): 最大 %.2fpx · 均值 %.2fpx" % (err.max(), err.mean()))

    big = img_f.copy()
    for i in range(4):
        cv2.circle(big, tuple(np.round(proj.reshape(-1, 2)[i]).astype(int)), 6, (0, 220, 120), 2)
    cv2.aruco.drawDetectedMarkers(big, [mk[mid][1].reshape(1, 4, 2).astype(np.float32)],
                                  np.array([[mid]], np.int32))
    if a.tcp and os.path.exists(a.tcp):
        tcp = json.load(open(a.tcp, encoding="utf-8"))
        import opt_box3d as OB
        _, T_bt, _ = OB.camera_pose(tcp)
        pt = T_bt[:3, 3].reshape(1, 3)
        pr, _ = cv2.projectPoints(pt, cv2.Rodrigues(T_bc2[:3, :3])[0].ravel(), T_bc2[:3, 3], K2, d2)
        uv = pr.reshape(2)
        cv2.drawMarker(big, (int(uv[0]), int(uv[1])), (0, 130, 255), cv2.MARKER_CROSS, 44, 3)
        cv2.putText(big, "TCP", (int(uv[0]) + 8, int(uv[1]) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 130, 255), 2)
        print("   TCP %s mm → 像素 (%.0f, %.0f)" % (np.round(pt.ravel(), 1), uv[0], uv[1]))
    os.makedirs(os.path.dirname(a.proof), exist_ok=True)
    cv2.imwrite(a.proof, big)
    print("   留证图:", a.proof)

    if a.out:
        cal = json.load(open(a.out, encoding="utf-8")) if os.path.exists(a.out) else {}
        e = cal.get(a.key) or {}
        e.update({"kind": "extrinsic", "model": "pinhole", "f": float(K2[0, 0]), "cx": float(K2[0, 2]),
                  "cy": float(K2[1, 2]), "T_base_cam": T_bc2.tolist(),
                  "source": "aruco %d · 边长 %.2fmm(腕相机反解) · marker 重投影 %.2fpx · 角点验收 %.2fpx"
                            % (mid, s_mm, rmse2, err.max()),
                  "marker_mm": float(s_mm), "rmse_marker_px": round(float(rmse2), 3),
                  "rmse_corner_px": round(float(err.max()), 3),
                  "marker_tcp_views": len(base_pts), "spread_mm": [round(float(x), 2) for x in spread]})
        cal[a.key] = e
        json.dump(cal, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("⑥ 已写入 %s [%s]" % (a.out, a.key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
