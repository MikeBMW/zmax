#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handeye_calib.py — 眼在手上(eye-in-hand)手眼标定: 解 T_tool1_cam, 再画 tool1 坐标系。

原理(单点法, 比标定板更省事):
  料盘上的光模块是**固定不动**的点 P_base(槽4 中心 = 647.4,353.9,114.25 mm, 槽位几何真值)。
  臂走 N 个位姿 i, 每个位姿:
    · 从 /api/tcp 拿 T_base_tool1(i) = (R_i, s_i)      ← 控制器真值, 不是自己算的
    · 从 D405 深度+YOLO 拿模块中心 P_cam(i)
  关系:  P_base = R_i · (R_x · P_cam(i) + t_x) + s_i
  令   v_i = R_iᵀ (P_base − s_i), 则  R_x·P_cam(i) + t_x = v_i  ⇒ 对 {(P_cam(i), v_i)} 做 Kabsch(SVD) 即得 (R_x, t_x)。
  N≥3 且 P_cam 不共线时可解; 残差直接给出标定质量。

用法:
  python tools/handeye_calib.py --run      # 走位姿 + 采集 + 解算(会真动机械臂)
  python tools/handeye_calib.py --draw     # 用已存外参在最新帧上画 tool1 三轴
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

ROOT = "/home/ubuntu/zmax"
RS = "http://192.168.23.66:8794"
OUT = os.path.join(ROOT, "zmax_data/percept/calib")
CAL = os.path.join(OUT, "handeye_tool1_cam.json")
SLOT_JSON = os.path.join(ROOT, "config/points/tray_slots_14.json")
MODEL = os.path.join(ROOT, "models/yolo_peg_live.pt")
TGT = (0.072, 0.01835, 0.0085)          # 模块 长×宽×高 (m)

POSES = [
    ("A", 339.3, 372.2, 139.9, (3.089, -1.015, 0.071)),
    ("B", 380.0, 372.2, 150.0, (3.089, -1.015, 0.071)),
    ("C", 339.3, 410.0, 150.0, (3.089, -1.015, 0.071)),
    ("D", 339.3, 340.0, 150.0, (3.089, -1.015, 0.071)),
    ("E", 360.0, 372.2, 172.0, (3.089, -1.015, 0.300)),
]


def get(url, t=8):
    return urllib.request.urlopen(url, timeout=t).read()


def tcp_frame():
    d = json.loads(get("http://127.0.0.1:8797/api/tcp", 5))
    f = d["frames"]["tool1"]
    o = np.array(f["origin"], float)
    R = np.stack([np.array(f["x"], float), np.array(f["y"], float), np.array(f["z"], float)], axis=1)
    return o, R, d.get("age_s")


def grab():
    im = cv2.imdecode(np.frombuffer(get(RS + "/frame.jpg"), np.uint8), cv2.IMREAD_COLOR)
    dep = cv2.imdecode(np.frombuffer(get(RS + "/depth.png"), np.uint8), cv2.IMREAD_UNCHANGED)
    K = json.loads(get(RS + "/intrinsics"))
    if dep.shape[:2] != im.shape[:2]:
        dep = cv2.resize(dep, (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
    return im, dep, K


def slot_center(sid=4):
    d = json.load(open(SLOT_JSON))
    for s in d["slots"]:
        if int(s["id"]) == sid:
            b = s["box"]
            return np.array([s["x"], s["y"], s["z"] + b["lz"] / 2.0], float) / 1000.0
    raise SystemExit("no slot %d" % sid)


def segment_module(im, dep, K):
    """框内 → RANSAC 平面(顶面) → 固定长宽比矩形 → 模块中心(相机系, 米)。返回 None 表示这帧不合格。"""
    from ultralytics import YOLO
    r = YOLO(MODEL).predict(im, conf=0.25, device="cpu", verbose=False)[0]
    if not len(r.boxes):
        return None, "无检出"
    b = max(r.boxes, key=lambda x: float(x.conf))
    x1, y1, x2, y2 = [int(float(v)) for v in b.xyxy[0]]
    roi = dep[max(0, y1):y2 + 1, max(0, x1):x2 + 1].astype(np.float32) * 1e-4
    vs, us = np.nonzero(roi > 0.05)
    if vs.size < 200:
        return None, "深度点少(%d)" % vs.size
    z = roi[vs, us]
    P = np.stack([(us + x1 - K["cx"]) / K["fx"] * z, (vs + y1 - K["cy"]) / K["fy"] * z, z], 1)
    # RANSAC 平面
    rng = np.random.default_rng(0)
    best = (0, None, None)
    for _ in range(200):
        idx = rng.choice(len(P), 3, replace=False)
        p0, p1, p2 = P[idx]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n /= nn
        d0 = -n.dot(p0)
        cnt = int((np.abs(P @ n + d0) < 0.0015).sum())
        if cnt > best[0]:
            best = (cnt, n, d0)
    cnt, n, d0 = best
    if n is None or cnt < 150:
        return None, "平面点少(%d)" % cnt
    if n[2] > 0:
        n, d0 = -n, -d0
    top = P[np.abs(P @ n + d0) < 0.0015]
    c0 = top.mean(0)
    # 平面内两基
    a = np.array([1.0, 0, 0])
    if abs(a @ n) > 0.9:
        a = np.array([0, 1.0, 0])
    e1 = np.cross(n, a)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    bestr = None
    for deg in range(0, 180, 2):
        th = np.deg2rad(deg)
        u = e1 * np.cos(th) + e2 * np.sin(th)
        v = np.cross(n, u)
        lu = (top - c0) @ u
        lv = (top - c0) @ v
        A = np.percentile(lu, 99) - np.percentile(lu, 1)
        B = np.percentile(lv, 99) - np.percentile(lv, 1)
        L, W = (A, B) if A >= B else (B, A)
        score = abs(L - TGT[0]) + 2 * abs(W - TGT[1])
        if bestr is None or score < bestr[0]:
            bestr = (score, u.copy(), v.copy(), L, W)
    score, u, v, L, W = bestr
    if abs(L - TGT[0]) > 0.02 or abs(W - TGT[1]) > 0.012:
        return None, "尺寸不符 %.0f×%.0f mm" % (L * 1000, W * 1000)
    lu = (top - c0) @ u
    lv = (top - c0) @ v
    center_top = c0 + u * (np.percentile(lu, 1) + np.percentile(lu, 99)) / 2 \
        + v * (np.percentile(lv, 1) + np.percentile(lv, 99)) / 2
    center = center_top - n * (TGT[2] / 2)         # 顶面 → 体中心
    return {"p_cam": center, "n": n, "u": u, "v": v, "L": L, "W": W, "npts": int(cnt)}, "ok"


def kabsch(A, B):
    ca, cb = A.mean(0), B.mean(0)
    H = (A - ca).T @ (B - cb)
    U, S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    return R, cb - R @ ca


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--draw", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data/percept/tool1_frame.jpg"))
    ap.add_argument("--axis-mm", type=float, default=40.0)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    P_base = slot_center(4)

    if a.run:
        recs = []
        for name, x, y, z, rpy in POSES:
            env = dict(os.environ, ZMAX_VIEW_XYZ="%.1f,%.1f,%.1f" % (x, y, z),
                       ZMAX_VIEW_RPY="%.4f,%.4f,%.4f" % rpy, ZMAX_SEG_SPEED="25")
            print("── 位姿 %s → %.1f,%.1f,%.1f rpy=%s" % (name, x, y, z, rpy), flush=True)
            r = subprocess.run(["bash", "tools/rokae_sdk_run.sh", "--script", "move_view.py"],
                               cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
            print("   " + (r.stdout.strip().splitlines() or ["(无输出)"])[-1], flush=True)
            if r.returncode != 0:
                print("   ✗ 走位失败, 跳过该位姿")
                continue
            time.sleep(1.0)
            im, dep, K = grab()
            seg, why = segment_module(im, dep, K)
            o, R, age = tcp_frame()
            if seg is None:
                print("   ✗ 分割不合格: %s" % why)
                continue
            recs.append({"pose": name, "p_cam": seg["p_cam"].tolist(), "tcp_o": o.tolist(),
                         "tcp_R": R.tolist(), "L": seg["L"], "W": seg["W"], "n": seg["npts"]})
            print("   ✓ p_cam %.1f,%.1f,%.1f mm · 顶面 %.0f×%.0f mm · TCP %.1f,%.1f,%.1f (age %.2fs)"
                  % (*(seg["p_cam"] * 1000), seg["L"] * 1000, seg["W"] * 1000, *(o * 1000), age or -1))
        if len(recs) < 3:
            print("✗ 有效位姿只有 %d 个(<3), 解不出外参" % len(recs))
            return 2
        A, B = [], []
        for q in recs:
            R = np.array(q["tcp_R"], float)
            s = np.array(q["tcp_o"], float)
            A.append(np.array(q["p_cam"], float))
            B.append(R.T @ (P_base - s))
        R_x, t_x = kabsch(np.array(A), np.array(B))
        res = [np.linalg.norm(R_x @ np.array(q["p_cam"]) + t_x - np.array(b))
               for q, b in zip(recs, B)]
        print("外参 T_tool1→cam: R(行列式 %.4f) t=%.1f,%.1f,%.1f mm"
              % (np.linalg.det(R_x), *(t_x * 1000)))
        print("逐位姿残差 mm: " + ", ".join("%s=%.2f" % (q["pose"], e * 1000) for q, e in zip(recs, res)))
        print("中位残差 %.2f mm · 最大 %.2f mm" % (np.median(res) * 1000, max(res) * 1000))
        json.dump({"R_tool_cam": R_x.tolist(), "t_tool_cam": t_x.tolist(),
                   "residuals_mm": {q["pose"]: round(e * 1000, 2) for q, e in zip(recs, res)},
                   "poses": recs, "p_base_module_m": P_base.tolist()},
                  open(CAL, "w"), ensure_ascii=False, indent=1)
        print("落 %s" % CAL)
        return 0

    if a.draw:
        if not os.path.exists(CAL):
            print("✗ 还没标定 (%s)" % CAL)
            return 2
        C = json.load(open(CAL))
        R_x = np.array(C["R_tool_cam"], float)
        t_x = np.array(C["t_tool_cam"], float)
        im, dep, K = grab()
        o, R_t, age = tcp_frame()
        L = a.axis_mm / 1000.0
        out = im.copy()

        def proj(pb):
            pc = R_x.T @ (R_t.T @ (np.asarray(pb) - o))
            if pc[2] <= 0.05:
                return None
            return (int(K["fx"] * pc[0] / pc[2] + K["cx"]), int(K["fy"] * pc[1] / pc[2] + K["cy"]))

        O = proj(o)
        if O is None:
            print("✗ 该位姿下 tool1 原点不在相机前方(看不到), 换个位姿再画")
            return 3
        cols = {"X": (60, 60, 240), "Y": (60, 210, 60), "Z": (240, 170, 60)}
        for i, ax in enumerate(("X", "Y", "Z")):
            q = proj(o + R_t[:, i] * L)
            if q is None:
                continue
            cv2.arrowedLine(out, O, q, cols[ax], 2, cv2.LINE_AA, tipLength=0.22)
            cv2.putText(out, "tool1." + ax, (q[0] + 5, q[1] - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.65, cols[ax], 2, cv2.LINE_AA)
        cv2.circle(out, O, 6, (255, 255, 255), -1)
        cv2.putText(out, "tool1 O=(%.0f,%.0f,%.0f)mm" % tuple(o * 1000), (O[0] + 9, O[1] + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imwrite(a.out, out)
        print("画好 → %s  (TCP age %.2fs)" % (a.out, age or -1))
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
