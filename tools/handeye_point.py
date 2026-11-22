#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_point.py — 采集"单点手眼标定"的一个观测, 并解外参。

思路(不用标定板, 也不用量模块尺寸):
  光模块当靶标, 但只用它的**中心**, 不用它的尺寸 —— 中心从"图像暗区掩膜 ∩ 有效深度"的 3D 质心取,
  避开 YOLO 框外扩把台面/邻件带进来的问题(实测框内固定尺寸拟合会跑出 410×65mm)。
  模块每次放在**已知槽位**(槽位几何真值), 臂在各次之间**位姿不同**, 于是:
      v_i = R_iᵀ (P_base_i − s_i) = R_x·P_cam_i + t_x
  3 个不共线槽位 → Kabsch 解 (R_x, t_x)。中心 1~2mm 的偏差只让外参轻微偏, 不影响"画出坐标系"的用途。

用法:
  python tools/handeye_point.py --slot 2        # 机械臂现在停在能看见该槽的位姿, 采一个点
  python tools/handeye_point.py --solve         # 解外参(≥3 点) 并落盘
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import urllib.request

import cv2
import numpy as np

ROOT = "/home/ubuntu/zmax"
RS = "http://192.168.23.66:8794"
D = os.path.join(ROOT, "zmax_data/percept/calib/pts")
CAL = os.path.join(ROOT, "zmax_data/percept/calib/handeye_tool1_cam.json")
SLOT_JSON = os.path.join(ROOT, "config/points/tray_slots_14.json")


def g(u, t=8):
    return urllib.request.urlopen(u, timeout=t).read()


def tcp():
    d = json.loads(g("http://127.0.0.1:8797/api/tcp", 5))
    f = d["frames"]["tool1"]
    o = np.array(f["origin"], float)
    R = np.stack([np.array(f[a], float) for a in "xyz"], 1)
    return o, R, d.get("age_s"), d.get("joints")


def slot(sid):
    d = json.load(open(SLOT_JSON))
    for s in d["slots"]:
        if int(s["id"]) == sid:
            return np.array([s["x"], s["y"], s["z"] + s["box"]["lz"] / 2], float) / 1000.0
    raise SystemExit("槽 %s 不存在" % sid)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--pnp", action="store_true")
    a = ap.parse_args()
    os.makedirs(D, exist_ok=True)

    if a.slot:
        im = cv2.imdecode(np.frombuffer(g(RS + "/frame.jpg"), np.uint8), cv2.IMREAD_COLOR)
        raw = cv2.imdecode(np.frombuffer(g(RS + "/depth.png"), np.uint8), cv2.IMREAD_UNCHANGED).astype(np.float32)
        K = json.loads(g(RS + "/intrinsics"))
        Z = raw * 0.1
        from ultralytics import YOLO
        r = YOLO(os.path.join(ROOT, "models/yolo_peg_live.pt")).predict(im, conf=0.25, device="cpu", verbose=False)[0]
        if not len(r.boxes):
            print("✗ 无检出")
            return 2
        b = max(r.boxes, key=lambda x: float(x.conf))
        x1, y1, x2, y2 = [int(float(v)) for v in b.xyxy[0]]
        pad = 6
        x1, y1, x2, y2 = max(0, x1 - pad), max(0, y1 - pad), x2 + pad, y2 + pad
        roi = im[y1:y2, x1:x2]
        gg = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        th = int(min(70, max(45, np.percentile(gg, 25) - 8)))
        mask = (gg < th).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(mask, 8)
        if n < 2:
            print("✗ 暗区没分出来")
            return 2
        i = 1 + int(np.argmax(st[1:, 4]))
        m_full = np.zeros(Z.shape, np.uint8)
        m_full[y1:y2, x1:x2] = (lab == i).astype(np.uint8)
        vs, us = np.nonzero((m_full > 0) & (Z > 150) & (Z < 800))
        if vs.size < 100:
            print("✗ 暗区内有效深度太少(%d)" % vs.size)
            return 2
        z = Z[vs, us]
        # 🔒 必须去畸变: 实测不去畸变时, 离光轴越远偏差越大(槽14 离轴31°残差 25mm, 槽2/9 离轴18° 残差 10~18mm)
        Kmtx = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
        dist = np.array(K.get("coeffs") or [0, 0, 0, 0, 0], float)
        uv = np.stack([us, vs], 1).astype(np.float64).reshape(-1, 1, 2)
        xn = cv2.undistortPoints(uv, Kmtx, dist).reshape(-1, 2)
        P = np.stack([xn[:, 0] * z, xn[:, 1] * z, z], 1).astype(float) / 1000.0
        # 去掉离群(远端背景)
        med = np.median(P[:, 2])
        P = P[np.abs(P[:, 2] - med) < 0.05]
        if len(P) < 120:
            print("✗ 有效点太少(%d) —— 掩膜没抓住模块, 不采" % len(P))
            return 2
        c = P.mean(0)
        o, R, age, joints = tcp()
        cnt_all = cv2.findContours(((lab == i).astype(np.uint8)), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        cnt = max(cnt_all, key=cv2.contourArea) if cnt_all else None
        (rcx, rcy), (rw, rh), rang = cv2.minAreaRect(cnt) if cnt is not None else ((0, 0), (0, 0), 0)
        uv_c = (float(rcx + x1), float(rcy + y1))          # minAreaRect 中心(回落原图坐标)
        rec = {"slot": a.slot, "uv": uv_c, "rect_wh": [round(float(rw), 1), round(float(rh), 1)],
               "p_cam_m": c.tolist(), "p_base_m": slot(a.slot).tolist(),
               "tcp_o": o.tolist(), "tcp_R": R.tolist(), "age_s": age, "joints": joints,
               "npts": int(len(P)), "conf": round(float(b.conf), 3)}
        p = os.path.join(D, "pt_slot%d_%s.json" % (a.slot, __import__("time").strftime("%H%M%S")))
        json.dump(rec, open(p, "w"), ensure_ascii=False, indent=1)
        print("槽%d ✓ p_cam %.1f,%.1f,%.1f mm · p_base %.1f,%.1f,%.1f mm · 点 %d · TCP age %.2fs"
              % (a.slot, *(c * 1000), *(slot(a.slot) * 1000), len(P), age or -1))
        print("  → %s" % p)
        return 0

    if a.pnp:
        fs = sorted(glob.glob(os.path.join(D, "pt_slot*.json")))
        recs = [json.load(open(f)) for f in fs if "uv" in json.load(open(f))]
        if len(recs) < 3:
            print("✗ 带 uv 的观测只有 %d 个, 至少 3 个(建议 4+)" % len(recs))
            return 2
        K = json.loads(g(RS + "/intrinsics"))
        Kmtx = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
        dist = np.array(K.get("coeffs") or [0, 0, 0, 0, 0], float)
        obj = np.array([r["p_base_m"] for r in recs], float) * 1000.0
        img = np.array([r["uv"] for r in recs], float)
        ok, rvec, tvec = False, None, None
        for flag in ((cv2.SOLVEPNP_IPPE,) if len(obj) >= 4 else ()) + (cv2.SOLVEPNP_SQPNP, cv2.SOLVEPNP_AP3P):
            try:
                ok, rvec, tvec = cv2.solvePnP(obj, img, Kmtx, dist, flags=flag)
                if ok:
                    break
            except cv2.error:
                ok = False
        if not ok:
            print("✗ PnP 不收敛")
            return 2
        R_cb, _ = cv2.Rodrigues(rvec)
        proj, _ = cv2.projectPoints(obj, rvec, tvec, Kmtx, dist)
        res = np.linalg.norm(proj.reshape(-1, 2) - img, axis=1)
        print("PnP(基座→相机): R det %.4f · 相机原点在基座系 %.1f,%.1f,%.1f mm"
              % (np.linalg.det(R_cb), *(np.array([*(R_cb.T @ (-tvec.ravel()))]).ravel())))
        print("逐点重投影误差 px: " + ", ".join("槽%d=%.2f" % (r["slot"], e) for r, e in zip(recs, res)))
        print("RMS %.2f px · 最大 %.2f px  (合格线 ≤3px)" % (float(np.sqrt((res ** 2).mean())), float(res.max())))
        json.dump({"rvec": rvec.ravel().tolist(), "tvec": tvec.ravel().tolist(),
                   "R_cam_from_base": R_cb.tolist(), "reproj_px": [round(float(e), 2) for e in res],
                   "slots": [r["slot"] for r in recs]}, open(CAL, "w"), ensure_ascii=False, indent=1)
        print("落 %s" % CAL)
        return 0

    if a.solve:
        fs = sorted(glob.glob(os.path.join(D, "pt_slot*.json")))
        recs = [json.load(open(f)) for f in fs]
        slots = [r["slot"] for r in recs]
        print("观测 %d 个: 槽%s" % (len(recs), slots))
        if len(recs) < 3:
            print("✗ 少于 3 个, 解不出")
            return 2
        A, B = [], []
        for q in recs:
            R = np.array(q["tcp_R"], float)
            s = np.array(q["tcp_o"], float)
            A.append(np.array(q["p_cam_m"]))
            B.append(R.T @ (np.array(q["p_base_m"]) - s))
        A, B = np.array(A), np.array(B)
        ca, cb = A.mean(0), B.mean(0)
        H = (A - ca).T @ (B - cb)
        U, S, Vt = np.linalg.svd(H)
        d = np.sign(np.linalg.det(Vt.T @ U.T))
        R_x = Vt.T @ np.diag([1, 1, d]) @ U.T
        t_x = cb - R_x @ ca
        res = [np.linalg.norm(R_x @ A[i] + t_x - B[i]) * 1000 for i in range(len(A))]
        print("T_tool1→cam: det %.4f · t %.1f,%.1f,%.1f mm" % (np.linalg.det(R_x), *(t_x * 1000)))
        print("残差 mm: " + ", ".join("槽%d=%.1f" % (q["slot"], e) for q, e in zip(recs, res)))
        print("中位 %.2f · 最大 %.2f mm" % (float(np.median(res)), float(max(res))))
        json.dump({"R_tool_cam": R_x.tolist(), "t_tool_cam": t_x.tolist(),
                   "residuals_mm": {("槽%d" % q["slot"]): round(e, 2) for q, e in zip(recs, res)},
                   "n": len(recs)}, open(CAL, "w"), ensure_ascii=False, indent=1)
        print("落 %s" % CAL)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
