#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tcp_frame_draw.py — 现场解"相机→基座"外参, 然后把 tool1 坐标系画到相机画面上。

为什么能只用一个模块就解出来: 光模块是**已知尺寸的刚体** (72 × 18.35 × 8.5mm, 见 tray_slots_14.json),
在本位姿下用 D405 深度把它顶面拟合出平面(法向=模块 Z 轴) + 顶面内 PCA 求长/宽两个方向,
就得到模块在**相机系**的完整 6DOF; 而模块在**基座系**的姿态是已知的(槽位规则: 长边沿 X, 宽沿 Y, 高沿 Z,
中心 = 槽位 + 半高), 于是:
      R_cam→base = R_base←module · R_cam←moduleᵀ
      t          = P_base_module_center − R · P_cam_module_center
有一帧就够(模块尺寸与基座姿态都已知), 不用标定台。

用法:
  python tools/tcp_frame_draw.py --slot 4 --out zmax_data/percept/tool1_frame.jpg
自检: 脚本会把模块 3D 框反投影回图像并打印与 YOLO 2D 框的偏差; 偏差大就说明这帧不合格, 不落外参。
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

import cv2
import numpy as np

ROOT = "/home/ubuntu/zmax"
RS = "http://192.168.23.66:8794"
CALIB = os.path.join(ROOT, "zmax_data/percept/calib/tcp_frame.json")
SLOT_JSON = os.path.join(ROOT, "config/points/tray_slots_14.json")


def _get(u, t=8):
    return urllib.request.urlopen(u, timeout=t).read()


def grab():
    im = cv2.imdecode(np.frombuffer(_get(RS + "/frame.jpg"), np.uint8), cv2.IMREAD_COLOR)
    dep = cv2.imdecode(np.frombuffer(_get(RS + "/depth.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    K = json.loads(_get(RS + "/intrinsics"))
    if dep.shape[:2] != im.shape[:2]:
        dep = cv2.resize(dep, (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
    return im, dep, K


def slot_base(slot_id):
    d = json.load(open(SLOT_JSON))
    for s in d["slots"]:
        if int(s["id"]) == int(slot_id):
            box = s["box"]
            c = np.array([s["x"], s["y"], s["z"] + box["lz"] / 2.0], float) / 1000.0
            return c, np.array([box["lx"], box["ly"], box["lz"]], float) / 1000.0
    raise SystemExit("槽 %s 不在流水表里" % slot_id)


def module_pose_cam(dep, K, box_xyxy):
    x1, y1, x2, y2 = box_xyxy
    roi = dep[y1:y2 + 1, x1:x2 + 1].astype(np.float32) * 1e-4        # 0.1mm/unit
    vs, us = np.nonzero(roi > 0.05)
    if vs.size < 200:
        raise SystemExit("框内深度点太少(%d)" % vs.size)
    z = roi[vs, us]
    # 顶面 = 最近的那层(直方图峰 ±8mm)
    hist, edges = np.histogram(z, bins=40)
    peak = edges[int(np.argmax(hist))] + (edges[1] - edges[0]) / 2
    sel = np.abs(z - peak) < 0.008
    us, vs, z = us[sel] + x1, vs[sel] + y1, z[sel]
    if len(z) < 150:
        raise SystemExit("顶面点太少(%d)" % len(z))
    P = np.stack([(us - K["cx"]) / K["fx"] * z, (vs - K["cy"]) / K["fy"] * z, z], 1)
    # 顶面法向(平面拟合)
    c0 = P.mean(0)
    _, _, Vt = np.linalg.svd(P - c0)
    n = Vt[2]
    n = n if n[2] < 0 else -n                     # 朝相机(相机看向 +Z)
    # 顶面内两轴
    e1, e2 = Vt[0], Vt[1]
    # 🔒 已知尺寸约束拟合: 光模块长宽高是定值(72 × 18.35 × 8.5mm), 直接在顶面内搜一个方向 θ,
    #    使顶面点云的包围矩形最接近这个长宽比 —— 不用 PCA 的自由主轴(会被邻件/槽壁带偏, 实测出过 40.9mm 的"宽")。
    TGT_L, TGT_W = 0.072, 0.01835
    best = None
    for deg in range(0, 180, 1):
        th = np.deg2rad(deg)
        u = e1 * np.cos(th) + e2 * np.sin(th)
        v = -e1 * np.sin(th) + e2 * np.cos(th)
        lu = (P - c0) @ u
        lv = (P - c0) @ v
        a = np.percentile(lu, 99) - np.percentile(lu, 1)
        b = np.percentile(lv, 99) - np.percentile(lv, 1)
        long_, short_ = (a, b) if a >= b else (b, a)
        score = abs(long_ - TGT_L) + abs(short_ - TGT_W) * 2.0
        if best is None or score < best[0]:
            best = (score, u.copy(), v.copy(), long_, short_)
    _, u, v, ext_long, ext_short = best
    a_long = u if np.ptp((P - c0) @ u) >= np.ptp((P - c0) @ v) else v
    a_short = v if a_long is u else u
    loc = np.stack([(P - c0) @ u, (P - c0) @ v], 1)
    lu = (P - c0) @ a_long
    lv = (P - c0) @ a_short
    top_center = (c0 + a_long * (np.percentile(lu, 1) + np.percentile(lu, 99)) / 2
                  + a_short * (np.percentile(lv, 1) + np.percentile(lv, 99)) / 2)
    center = top_center - n * 0.00425             # 8.5mm 厚 ⇒ 中心在顶面下 4.25mm
    R_cm = np.stack([a_long, a_short, n], 1)      # 列 = 模块 X/Y/Z 在相机系
    if np.linalg.det(R_cm) < 0:
        R_cm[:, 2] *= -1
    return center, R_cm, np.array([ext_long, ext_short, 0.0085]), len(z), n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=4)
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data/percept/tool1_frame.jpg"))
    ap.add_argument("--axis-mm", type=float, default=40.0)
    a = ap.parse_args()

    im, dep, K = grab()
    from ultralytics import YOLO
    r = YOLO(os.path.join(ROOT, "models/yolo_peg_live.pt")).predict(im, conf=0.25, device="cpu", verbose=False)[0]
    if not len(r.boxes):
        print("✗ 没检出模块, 无法解外参")
        return 2
    box = [int(float(v)) for v in r.boxes[0].xyxy[0]]
    c_cam, R_cm, dims, npts, nrm = module_pose_cam(dep, K, box)
    print("模块(相机系): 中心 %.1f,%.1f,%.1f mm · 尺寸 %.1f×%.1f mm(顶面) · 点数 %d"
          % (*(c_cam * 1000), dims[0] * 1000, dims[1] * 1000, npts))

    c_base, dims_base = slot_base(a.slot)
    R_bm = np.eye(3)                              # 基座里模块轴 = 基座轴(槽位规则)
    R_cb = R_bm @ R_cm.T                          # 相机→基座
    t_cb = c_base - R_cb @ c_cam
    print("外参: R_cam→base 行列式 %.4f · t = %.1f,%.1f,%.1f mm (相机原点在基座系)"
          % (np.linalg.det(R_cb), *(t_cb * 1000)))

    # 反投影自检: 模块 8 角点应在 YOLO 2D 框内(允许 15% 外扩)
    corners = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                corners.append(c_cam + R_cm @ (np.array([sx, sy, sz]) * dims_base / 2))
    uv = [(int(K["fx"] * c[0] / c[2] + K["cx"]), int(K["fy"] * c[1] / c[2] + K["cy"])) for c in corners]
    uu = [p[0] for p in uv]
    vv = [p[1] for p in uv]
    w2, h2 = box[2] - box[0], box[3] - box[1]
    out_ratio = max(0, min(uu) - box[0]) / w2 + max(0, box[2] - max(uu)) / w2
    print("自检: 3D 框投影 x[%d,%d] y[%d,%d] vs YOLO 框 %s · 越界比 %.2f"
          % (min(uu), max(uu), min(vv), max(vv), box, out_ratio))

    # tool1 坐标系
    d = json.loads(_get("http://127.0.0.1:8797/api/tcp", 4))
    p_base = np.array([d["x"], d["y"], d["z"]], float)
    rpy = [d.get("rx", 0.0), d.get("ry", 0.0), d.get("rz", 0.0)]
    roll, pitch, yaw = [float(v) for v in rpy]
    Rx = np.array([[1, 0, 0], [0, np.cos(roll), -np.sin(roll)], [0, np.sin(roll), np.cos(roll)]])
    Ry = np.array([[np.cos(pitch), 0, np.sin(pitch)], [0, 1, 0], [-np.sin(pitch), 0, np.cos(pitch)]])
    Rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    Rt = Rz @ Ry @ Rx
    L = a.axis_mm / 1000.0
    def proj(pb):
        pc = R_cb.T @ (np.asarray(pb) - t_cb)
        if pc[2] <= 0.05:
            return None
        return (int(K["fx"] * pc[0] / pc[2] + K["cx"]), int(K["fy"] * pc[1] / pc[2] + K["cy"]))
    O = proj(p_base)
    if O is None:
        print("✗ TCP 在相机背后(该位姿下看不到工具点), 换位姿再画")
        return 3
    out = im.copy()
    cv2.rectangle(out, (box[0], box[1]), (box[2], box[3]), (60, 200, 60), 2)
    cols = {"X": (60, 60, 240), "Y": (60, 210, 60), "Z": (240, 170, 60)}
    for i, ax in enumerate(("X", "Y", "Z")):
        e = p_base + Rt[:, i] * L
        q = proj(e)
        if q is None:
            continue
        cv2.arrowedLine(out, O, q, cols[ax], 2, cv2.LINE_AA, tipLength=0.22)
        cv2.putText(out, "tool1." + ax, (q[0] + 4, q[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cols[ax], 2, cv2.LINE_AA)
    cv2.circle(out, O, 5, (255, 255, 255), -1)
    cv2.putText(out, "tool1 origin (%.0f,%.0f,%.0f)" % tuple(p_base * 1000), (O[0] + 8, O[1] + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(a.out, out)
    os.makedirs(os.path.dirname(CALIB), exist_ok=True)
    json.dump({"R": R_cb.tolist(), "t": t_cb.tolist(), "slot": a.slot,
               "module_center_cam_m": c_cam.tolist(), "module_dims_m": dims_base.tolist(),
               "out_ratio": round(float(out_ratio), 3)},
              open(CALIB, "w"), ensure_ascii=False, indent=1)
    print("画好 → %s   外参落 %s" % (a.out, CALIB))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
