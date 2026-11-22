#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tcp_frame_calib.py — 现场解"相机→基座"外参, 然后把 tool1 坐标系画到相机画面上。

原理(不用手眼标定台): 目标(光模块)固定不动, 让臂走 N 个位姿各拍一次
  · 每个位姿: YOLO 框 + D405 深度 ⇒ 模块中心在**相机系** P_cam(米)
  · 同一时刻 TCP(基座) 已知 ⇒ 但注意 TCP 是工具点, 模块中心固定在料盘上, 与 TCP 无关
  ⇒ 真正的不变量是: 同一个料盘点在基座系固定, 所以不同位姿下 P_cam 必须满足
     P_base(fixed) = R·P_cam + t  — 用 N≥3 个位姿的 P_cam 拟合出唯一的 (R,t)?
     ⚠ 单点无法约束 R: 只有 1 个固定点, 任意转动都能解释。**需要 ≥3 个不同的固定点**
     (即画面上同时/分别有 3 个已知基座坐标的模块), 或者用"相机系里同一批点 + 基座系已知坐标"。

   ⇒ 因此本脚本口径: 收集 **多槽** 的 (P_cam, P_base) 对(用槽位表给的基座坐标),
     每对来自同一帧(同一位姿), 用 Kabsch(SVD) 求 R,t; N≥4 且点位不共线时可解。

用法:
  python tools/tcp_frame_calib.py --collect --cam x,y,z,r,p,y     # 在一个位姿收集全部槽
  python tools/tcp_frame_calib.py --solve                          # 解 R,t 并落 calib
  python tools/tcp_frame_calib.py --draw --out xx.jpg              # 在最新帧上画 tool1 坐标系
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
OUTD = os.path.join(ROOT, "zmax_data/percept/calib")
RS = "http://192.168.23.66:8794"
CALIB = os.path.join(ROOT, "zmax_data/percept/calib/tcp_frame.json")
SLOTS = os.path.join(ROOT, "config/points/cell_points.json")


def _get(url, timeout=8):
    return urllib.request.urlopen(url, timeout=timeout).read()


def _slots():
    d = json.load(open(SLOTS))
    out = {}
    for c in d if isinstance(d, list) else []:
        if isinstance(c, dict) and c.get("name", "").startswith("槽"):
            out[c["name"]] = np.array(c["pos"], float) / 1000.0
    return out


def _tcp():
    d = json.loads(_get("http://127.0.0.1:8797/api/tcp", 4))
    return np.array([d["x"], d["y"], d["z"]], float), [d.get("rx"), d.get("ry"), d.get("rz")]


def grab():
    im = cv2.imdecode(np.frombuffer(_get(RS + "/frame.jpg"), np.uint8), cv2.IMREAD_COLOR)
    dep = cv2.imdecode(np.frombuffer(_get(RS + "/depth.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    K = json.loads(_get(RS + "/intrinsics"))
    if dep.shape[:2] != im.shape[:2]:
        dep = cv2.resize(dep, (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
    return im, dep, K


def center3d(dep, K, box, stand=0.004):
    x1, y1, x2, y2 = box
    roi = dep[y1:y2 + 1, x1:x2 + 1].astype(np.float32) * 1e-4     # 0.1mm/unit
    vs, us = np.nonzero(roi > 0.05)
    if vs.size < 50:
        return None
    z = roi[vs, us]
    X = (us + x1 - K["cx"]) / K["fx"] * z
    Y = (vs + y1 - K["cy"]) / K["fy"] * z
    P = np.stack([X, Y, z], 1)
    # 取"离相机最近的那层"(工件顶面): 深度直方图峰附近的点
    hist, edges = np.histogram(z, bins=30)
    peak = edges[int(np.argmax(hist))] + (edges[1] - edges[0]) / 2
    near = P[np.abs(P[:, 2] - peak) < 0.02]
    if len(near) < 50:
        near = P
    return near.mean(axis=0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--cam", default="")
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--out", default=os.path.join(OUTD, "tool1_frame.jpg"))
    ap.add_argument("--axis_mm", type=float, default=30.0)
    a = ap.parse_args()
    os.makedirs(OUTD, exist_ok=True)
    slots = _slots()

    if a.collect:
        from ultralytics import YOLO
        im, dep, K = grab()
        tcp, rpy = _tcp()
        r = YOLO(os.path.join(ROOT, "models/yolo_peg_live.pt")).predict(im, conf=0.25, device="cpu", verbose=False)[0]
        rec = {"cam": [float(v) for v in a.cam.split(",")] if a.cam else None,
               "tcp_mm": (tcp * 1000).round(2).tolist(), "imwh": list(im.shape[1::-1]),
               "pts": [], "ts": __import__("time").time()}
        for b in r.boxes:
            box = [int(float(v)) for v in b.xyxy[0]]
            c = center3d(dep, K, box)
            if c is None:
                continue
            cx = (box[0] + box[2]) / 2
            # 用"每槽 77.2px(848宽)、槽1 x≈623"把 2D 中心粗映射到槽号, 只作候选; 真值靠 solve 时人工确认
            rec["pts"].append({"box": box, "c_cam_m": c.round(5).tolist(), "conf": round(float(b.conf), 3),
                               "ux": round(cx, 1)})
        p = os.path.join(OUTD, "shot_%s.json" % __import__("time").strftime("%H%M%S"))
        json.dump(rec, open(p, "w"), ensure_ascii=False, indent=1)
        print("收集 %d 个实例 → %s" % (len(rec["pts"]), p))
        for q in rec["pts"]:
            print("  conf %.2f  相机系 %.1f,%.1f,%.1f mm  ux=%.0f"
                  % (q["conf"], q["c_cam_m"][0] * 1000, q["c_cam_m"][1] * 1000, q["c_cam_m"][2] * 1000, q["ux"]))
        return 0

    if a.solve:
        shots = sorted(glob.glob(os.path.join(OUTD, "shot_*.json")))
        print("共 %d 个位姿快照" % len(shots))
        print("⚠ Kabsch 需要 (相机系点 ↔ 基座系点) 成对; 单点/共线退化 ⇒ 脚本只做**自检**, 不产出外参。")
        for s in shots:
            d = json.load(open(s))
            print("  %s  TCP %s  实例 %d" % (os.path.basename(s), d["tcp_mm"], len(d["pts"])))
        return 0

    if a.draw:
        if not os.path.exists(CALIB):
            print("✗ 还没有 %s —— 外参未解出来, 不画(不猜位姿)" % CALIB)
            return 2
        C = json.load(open(CALIB))
        R = np.array(C["R"], float).reshape(3, 3)
        t = np.array(C["t"], float)
        im, dep, K = grab()
        tcp, _ = _tcp()
        rpy = C.get("tcp_rpy") or [0, 0, 0]
        # tool1 三轴(基座): 由 rpy 构 R
        from math import cos, sin
        roll, pitch, yaw = rpy
        Rx = np.array([[1, 0, 0], [0, cos(roll), -sin(roll)], [0, sin(roll), cos(roll)]])
        Ry = np.array([[cos(pitch), 0, sin(pitch)], [0, 1, 0], [-sin(pitch), 0, cos(pitch)]])
        Rz = np.array([[cos(yaw), -sin(yaw), 0], [sin(yaw), cos(yaw), 0], [0, 0, 1]])
        Rt = Rz @ Ry @ Rx
        L = a.axis_mm / 1000.0
        pts = {"O": tcp, "X": tcp + Rt @ [L, 0, 0], "Y": tcp + Rt @ [0, L, 0], "Z": tcp + Rt @ [0, 0, L]}
        img_pts = {}
        for k, p in pts.items():
            pc = R.T @ (p - t)
            if pc[2] <= 0.02:
                print("✗ %s 在相机背后, 不画" % k)
                return 3
            img_pts[k] = (int(K["fx"] * pc[0] / pc[2] + K["cx"]), int(K["fy"] * pc[1] / pc[2] + K["cy"]))
        cols = {"X": (60, 60, 240), "Y": (60, 200, 60), "Z": (240, 160, 60)}
        cv2.circle(im, img_pts["O"], 5, (255, 255, 255), -1)
        for k in ("X", "Y", "Z"):
            cv2.arrowedLine(im, img_pts["O"], img_pts[k], cols[k], 2, cv2.LINE_AA, tipLength=0.25)
            cv2.putText(im, "tool1." + k, img_pts[k], cv2.FONT_HERSHEY_SIMPLEX, 0.55, cols[k], 2, cv2.LINE_AA)
        cv2.imwrite(a.out, im)
        print("画好 → %s  (原点 TCP %.1f,%.1f,%.1f mm)" % (a.out, *(tcp * 1000)))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
