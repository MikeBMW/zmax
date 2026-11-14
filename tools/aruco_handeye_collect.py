#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 ArUco 位姿采集 (手眼标定用) —— 全帧、多字典、放宽参数。

背景: board_scan_frames.py 严格参数下 787 帧只命中 3 帧(游标 3 / 186 / 188),
      但这 3 帧的 TCP 位姿相差很大((399,-383,509) / (385,-392,374) / (682,66,264))
      ⇒ 那个 ArUco 角标在若干个过路位姿上确实进了画面, 只是标记小/斜/曝光不足,
        严格参数抓不住。这里放宽(小标记率 0.01、亚像素角点、纠错 0.6、多字典),
        目标是凑够 ≥8 个姿态各异的手眼约束。

输出: zmax_data/reports/aruco_handeye_<ts>.json
  det: [{cursor, id, dict, corners(4x2 px), rvec, tvec, reproj_px, pose_mm, quat, file}]
口径: 标记边长未知 ⇒ tvec 只当"某单位", 解手眼时用**旋转**(不受尺度影响)+ 线性解尺度。
只读: 不动机器人、不下发、不改任何在跑的服务。
"""
import glob
import json
import os
import sys
import time

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "zmax_data", "reports")
MARKER_LEN = 0.050          # 假定 50mm, 只影响 tvec 单位, 不影响旋转

DICTS = ["DICT_ARUCO_ORIGINAL", "DICT_4X4_50", "DICT_4X4_100", "DICT_4X4_250",
         "DICT_4X4_1000", "DICT_5X5_50", "DICT_5X5_100", "DICT_5X5_250",
         "DICT_6X6_50", "DICT_6X6_100", "DICT_6X6_250", "DICT_7X7_50", "DICT_7X7_100"]


def make_params():
    p = cv2.aruco.DetectorParameters()
    p.adaptiveThreshWinSizeMin = 3
    p.adaptiveThreshWinSizeMax = 53
    p.adaptiveThreshWinSizeStep = 4
    p.adaptiveThreshConstant = 5
    p.minMarkerPerimeterRate = 0.010          # 远远小于默认 0.03: 小标记也要
    p.maxMarkerPerimeterRate = 4.0
    p.polygonalApproxAccuracyRate = 0.08
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 5
    p.cornerRefinementMaxIterations = 50
    p.cornerRefinementMinAccuracy = 0.01
    p.errorCorrectionRate = 0.6
    p.perspectiveRemovePixelPerCell = 8
    p.minDistanceToBorder = 1
    return p


def load_frames():
    dirs = sorted(glob.glob(os.path.join(REPO, "zmax_data", "run_capture", "*")))
    out = []
    for d in dirs:
        man = os.path.join(d, "manifest.jsonl")
        if not os.path.exists(man):
            continue
        for line in open(man, encoding="utf-8"):
            r = json.loads(line)
            out.append({"cursor": r.get("cursor"), "file": os.path.join(d, r["file"]),
                        "pose_mm": r.get("pose_mm"), "joint_deg": r.get("joint_deg")})
    return out


def main():
    frames = load_frames()
    traj = json.load(open(os.path.join(REPO, "tools", "web", "real_traj_joints.json"),
                          encoding="utf-8"))["frames"]
    for f in frames:
        c = f.get("cursor")
        if isinstance(c, int) and 0 <= c < len(traj):
            f["quat"] = traj[c]["q"]
            f["p_m"] = traj[c]["p"]
    print("帧数 %d (带真值位姿 %d)" % (len(frames), sum(1 for f in frames if f.get("quat"))), flush=True)

    params = make_params()
    detectors = []
    for nm in DICTS:
        if not hasattr(cv2.aruco, nm):
            continue
        try:
            detectors.append((nm, cv2.aruco.ArucoDetector(
                cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, nm)), params)))
        except Exception:
            pass
    print("字典 %d 个 · 参数已放宽" % len(detectors), flush=True)

    det, scanned = [], 0
    for f in frames:
        img = cv2.imread(f["file"])
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        scanned += 1
        for nm, dt in detectors:
            corners, ids, _ = dt.detectMarkers(g)
            if ids is None:
                continue
            for k, cid in enumerate(ids.ravel()):
                cs = corners[k].reshape(4, 2).astype(float)
                L = MARKER_LEN
                obj = np.array([[-L / 2, L / 2, 0], [L / 2, L / 2, 0],
                                [L / 2, -L / 2, 0], [-L / 2, -L / 2, 0]], dtype=np.float32)
                K = np.array([[394.1, 0, 320.0], [0, 393.5, 240.0], [0, 0, 1]], dtype=np.float64)
                okp, rv, tv = cv2.solvePnP(obj, cs.astype(np.float32), K, None,
                                           flags=cv2.SOLVEPNP_IPPE_SQUARE)
                if not okp:
                    continue
                rv = rv.reshape(3).astype(float)
                tv = tv.reshape(3).astype(float)
                prj, _ = cv2.projectPoints(obj, rv, tv, K, None)
                rep = float(np.mean(np.linalg.norm(prj.reshape(4, 2) - cs, axis=1)))
                det.append({"cursor": f["cursor"], "id": int(cid), "dict": nm,
                            "corners": cs.tolist(), "rvec": rv.tolist(), "tvec": tv.tolist(),
                            "reproj_px": round(rep, 3),
                            "side_px": round(float(np.mean([np.linalg.norm(cs[i] - cs[(i + 1) % 4])
                                                            for i in range(4)])), 1),
                            "pose_mm": f.get("pose_mm"), "quat": f.get("quat"),
                            "p_m": f.get("p_m"), "file": f["file"]})
        if scanned % 100 == 0:
            print("  …%d/%d · 检出 %d 条" % (scanned, len(frames), len(det)), flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "aruco_handeye_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    by_id = {}
    for d in det:
        by_id[str(d["id"])] = by_id.get(str(d["id"]), 0) + 1
    json.dump({"n_frames": len(frames), "n_scanned": scanned, "marker_len_m": MARKER_LEN,
               "det": det, "per_id": by_id},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-" * 70)
    print("检出 %d 条 · 按 id: %s" % (len(det), by_id))
    print("明细 %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
