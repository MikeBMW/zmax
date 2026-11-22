#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_bundle.py — 捆绑平差式手眼标定(模块不动, 臂走位姿)。

为什么这样做: 逐槽手工摆放模块时, 摆放位置本身有 ±5~10mm 不确定度,
           实测 4 点 PnP 残差 13.8/12.4/2.3/1.1 px, 方向还不一致 —— 被摆放误差吃掉。
           改成 **模块放在一个槽里别动**, 臂走 N 个位姿:
             未知量 = 手眼外参 X=(R_x,t_x) 6 个 + 模块基座坐标 P_base 3 个  (共 9)
             每个位姿给 2 个方程(像素 u,v), N≥5 就有多余观测 → 残差是真精度
           位姿来自 /api/tcp 的 frames.tool1(控制器真值), 不用估。

模型: p_cam_i = R_x · (R_tiᵀ (P_base − s_ti)) + t_x   →  投影到像素 (含畸变)

用法:
  python tools/handeye_bundle.py --run     # 走 6 个位姿 + 采集 + 平差
  python tools/handeye_bundle.py --draw    # 用解出的外参在最新帧画 tool1 三轴
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.request

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation as Rot

ROOT = "/home/ubuntu/zmax"
RS = "http://192.168.23.66:8794"
D = os.path.join(ROOT, "zmax_data/percept/calib/bundle")
CAL = os.path.join(ROOT, "zmax_data/percept/calib/handeye_bundle.json")

POSES = [
    ("P1", 339.3, 372.2, 139.9, (3.089, -1.015, 0.071)),
    ("P2", 380.0, 380.0, 152.0, (3.089, -1.015, 0.071)),
    ("P3", 300.0, 360.0, 152.0, (3.089, -1.015, 0.071)),
    ("P4", 350.0, 400.0, 168.0, (3.089, -1.015, 0.071)),
    ("P5", 345.0, 350.0, 150.0, (3.089, -1.015, 0.300)),
    ("P6", 360.0, 390.0, 176.0, (3.089, -1.015, -0.150)),
]


def g(u, t=8):
    return urllib.request.urlopen(u, timeout=t).read()


def tcp():
    d = json.loads(g("http://127.0.0.1:8797/api/tcp", 5))
    f = d["frames"]["tool1"]
    return np.array(f["origin"], float), np.stack([np.array(f[a], float) for a in "xyz"], 1)


def intr():
    K = json.loads(g(RS + "/intrinsics"))
    Kmtx = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
    dist = np.array(K.get("coeffs") or [0, 0, 0, 0, 0], float)
    return Kmtx, dist


def observe():
    """返回模块中心像素 (u,v) 与点数; 失败返回 None。"""
    im = cv2.imdecode(np.frombuffer(g(RS + "/frame.jpg"), np.uint8), cv2.IMREAD_COLOR)
    raw = cv2.imdecode(np.frombuffer(g(RS + "/depth.png"), np.uint8), cv2.IMREAD_UNCHANGED).astype(np.float32)
    Z = raw * 0.1
    from ultralytics import YOLO
    r = YOLO(os.path.join(ROOT, "models/yolo_peg_live.pt")).predict(im, conf=0.25, device="cpu", verbose=False)[0]
    if not len(r.boxes):
        return None
    b = max(r.boxes, key=lambda x: float(x.conf))
    x1, y1, x2, y2 = [int(float(v)) for v in b.xyxy[0]]
    pad = 6
    x1, y1, x2, y2 = max(0, x1 - pad), max(0, y1 - pad), x2 + pad, y2 + pad
    gg = cv2.cvtColor(im[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    th = int(min(70, max(45, np.percentile(gg, 25) - 8)))
    mask = (gg < th).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, 4]))
    m_full = np.zeros(Z.shape, np.uint8)
    m_full[y1:y2, x1:x2] = (lab == i).astype(np.uint8)
    cnts = cv2.findContours(m_full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    (cu, cv_), (rw, rh), ang = cv2.minAreaRect(cnt)
    if cv2.contourArea(cnt) < 150:
        return None
    return (float(cu), float(cv_)), int(cv2.contourArea(cnt)), [round(float(rw), 1), round(float(rh), 1)]


def residuals(p, recs, Kmtx, dist):
    rvec, tvec, Pb = p[:3], p[3:6], p[6:9]
    R_x = Rot.from_rotvec(rvec).as_matrix()
    out = []
    for q in recs:
        R_t = np.array(q["tcp_R"], float)
        s_t = np.array(q["tcp_o"], float) * 1000.0
        p_cam = R_x @ (R_t.T @ (Pb - s_t)) + tvec
        uv, _ = cv2.projectPoints(p_cam.reshape(1, 3), np.zeros(3), np.zeros(3), Kmtx, dist)
        out.extend([uv[0, 0, 0] - q["uv"][0], uv[0, 0, 1] - q["uv"][1]])
    return np.array(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data/percept/tool1_frame_cam.jpg"))
    ap.add_argument("--axis-mm", type=float, default=60.0)
    a = ap.parse_args()
    os.makedirs(D, exist_ok=True)
    Kmtx, dist = intr()

    if a.run:
        recs = []
        for name, x, y, z, rpy in POSES:
            env = dict(os.environ, ZMAX_VIEW_XYZ="%.1f,%.1f,%.1f" % (x, y, z),
                       ZMAX_VIEW_RPY="%.4f,%.4f,%.4f" % rpy, ZMAX_SEG_SPEED="25")
            print("── %s → %.0f,%.0f,%.0f rpy %s" % (name, x, y, z, rpy), flush=True)
            r = subprocess.run(["bash", "tools/rokae_sdk_run.sh", "--script", "move_view.py"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
            last = (r.stdout.strip().splitlines() or ["(无输出)"])[-1]
            print("   " + last, flush=True)
            if r.returncode != 0:
                continue
            time.sleep(1.0)
            ob = observe()
            if ob is None:
                print("   ✗ 未检出/分割失败")
                continue
            uv, area, wh = ob
            o, R = tcp()
            recs.append({"pose": name, "uv": list(uv), "area": area, "wh": wh,
                         "tcp_o": o.tolist(), "tcp_R": R.tolist()})
            print("   ✓ uv (%.1f, %.1f) 面积 %d 矩形 %s" % (uv[0], uv[1], area, wh), flush=True)
        if len(recs) < 5:
            print("✗ 有效位姿 %d 个 (<5), 解不出" % len(recs))
            return 2

        # 初值: 用"模块基座坐标 = 各观测反推的平均"占位, rvec=0, t=(0,0,250)
        # 🔒 初值必须多起点 + 边界: 位姿间基线(几十 mm)远小于目标距离(300mm), 给零旋转初值会发散到 1e5 mm
        rng = np.random.default_rng(7)
        lo = np.array([-np.pi, -np.pi, -np.pi, -500, -500, -500, 200, -200, -50])
        hi = np.array([np.pi, np.pi, np.pi, 500, 500, 500, 900, 900, 400])
        best = None
        starts = [np.array([0.4, -0.2, 1.2, 40, -60, 240, 517, 404, 118])]
        for _ in range(60):
            starts.append(np.array([
                rng.uniform(-np.pi, np.pi), rng.uniform(-np.pi, np.pi), rng.uniform(-np.pi, np.pi),
                rng.uniform(-300, 300), rng.uniform(-300, 300), rng.uniform(-300, 300),
                rng.uniform(300, 800), rng.uniform(0, 900), rng.uniform(60, 200)]))
        for q0 in starts:
            try:
                sol = least_squares(residuals, q0, args=(recs, Kmtx, dist), bounds=(lo, hi),
                                    method="trf", max_nfev=6000, xtol=1e-12, ftol=1e-12)
            except Exception:
                continue
            if best is None or sol.cost < best.cost:
                best = sol
        sol = best
        res = residuals(sol.x, recs, Kmtx, dist).reshape(-1, 2)
        rms = float(np.sqrt((res ** 2).sum(1).mean()))
        per = {q["pose"]: round(float(np.hypot(*e)), 2) for q, e in zip(recs, res)}
        print("── 平差结果 ──")
        print("手眼 X(tool1→cam): R=rotvec %s · t %.1f,%.1f,%.1f mm"
              % (np.round(sol.x[:3], 4).tolist(), *(sol.x[3:6] * 1000)))
        print("模块基座坐标 (解出来的):  %.1f, %.1f, %.1f mm" % tuple(sol.x[6:9]))
        print("逐位姿重投影误差 px: " + ", ".join("%s=%.2f" % (k, v) for k, v in per.items()))
        print("RMS %.2f px (合格线 ≤3px) · 最大 %.2f px" % (rms, max(per.values())))
        json.dump({"rvec_tool_cam": sol.x[:3].tolist(), "t_tool_cam_m": (sol.x[3:6]).tolist(),
                   "P_base_m": (sol.x[6:9] / 1000.0).tolist(), "reproj_px": per, "rms_px": round(rms, 3),
                   "n_poses": len(recs), "recs": recs}, open(CAL, "w"), ensure_ascii=False, indent=1)
        print("落 %s" % CAL)
        return 0

    if a.draw:
        C = json.load(open(CAL))
        R_x = Rot.from_rotvec(C["rvec_tool_cam"]).as_matrix()
        t_x = np.array(C["t_tool_cam_m"], float)
        im = cv2.imdecode(np.frombuffer(g(RS + "/frame.jpg"), np.uint8), cv2.IMREAD_COLOR)
        o, R_t = tcp()
        L = a.axis_mm / 1000.0
        out = im.copy()

        def proj(pb):
            pc = R_x @ (R_t.T @ (np.asarray(pb) - o)) + t_x
            if pc[2] <= 0.05:
                return None
            uv, _ = cv2.projectPoints(pc.reshape(1, 3), np.zeros(3), np.zeros(3), Kmtx, dist)
            return int(uv[0, 0, 0]), int(uv[0, 0, 1])

        O = proj(o)
        if O is None:
            print("✗ tool1 原点不在相机前方")
            return 3
        cols = {"X": (60, 60, 240), "Y": (60, 210, 60), "Z": (240, 170, 60)}
        for i, axn in enumerate("XYZ"):
            q = proj(o + R_t[:, i] * L)
            if q is None:
                continue
            cv2.arrowedLine(out, O, q, cols[axn], 2, cv2.LINE_AA, tipLength=0.2)
            cv2.putText(out, "tool1." + axn, (q[0] + 5, q[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                        cols[axn], 2, cv2.LINE_AA)
        cv2.circle(out, O, 6, (255, 255, 255), -1)
        cv2.putText(out, "tool1 O=(%.0f,%.0f,%.0f)" % tuple(o * 1000), (O[0] + 9, O[1] + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imwrite(a.out, out)
        print("画好 → %s" % a.out)
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
