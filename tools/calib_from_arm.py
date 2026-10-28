#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_from_arm.py —— 不用标定板、不用贴标记: 靠"臂动了画面哪块变了"解固定相机(D435)外参

老倪 2026-10-18: 「自动化跑吧」「画面有延迟，你要慢慢移动，动一下停10秒」

为什么这么做:
  · D435 在 3~4m 外, 光模块只有十几像素, YOLO 检出的是静态杂物
    (实测两次不同 TCP 映射到同一像素 723,551) ⇒ "拿模块当靶标"这条路被判死。
  · 但**整条臂**在 D435 里又大又亮, 动一下就能靠帧差分把它抠出来。
  · 每个位姿做一次 +8mm 微动 ⇒ 差分 = 该位姿下臂的轮廓 ⇒ 取轮廓上**离基座最远**的点当"臂尖"像素;
    3D 侧用 TCP 真值 ⇒ 8 对 3D↔2D ⇒ DLT + LM 解外参。
  · 基座像素本身未知 ⇒ 迭代: 先按轮廓质心解一次 → 把基座原点投到图上 → 重取"离基座最远的轮廓点" → 再解, 3~4 轮。

判据(不满足不落盘, 如实报):
  · 重投影 RMS ≤ 10px、最大 ≤ 25px
  · 解出的相机光心在机器人前方 0.8~4.5m、高度 0.2~3m

用法:
  ./gui-venv311/bin/python tools/calib_from_arm.py --dry
  ./gui-venv311/bin/python tools/calib_from_arm.py --speed 28 --step 45 --pause 10
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G                                   # noqa: E402
from calib_from_module import boxes_mm, guard, solve_extrinsics   # noqa: E402

OUT = os.path.join(REPO, "zmax_data", "calib_d435")
FENCES = os.path.join(REPO, "zmax_data", "ar_rs", "fences.json")


def wait_idle(timeout=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = json.loads(urllib.request.urlopen("http://127.0.0.1:8793/ctl/status", timeout=4).read().decode())
            r = st.get("robot") or {}
            if str(r.get("operation", "")).lower() in ("idle", "idle_state", "stationary") and not r.get("has_error"):
                return True
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(1.0)
    return False


def d435():
    """真 D435 = 8791 的 'local' (640×480)。
    🔴 2026-10-18 遇到问题: 'local2'(1280×720) 是 MAXHUB 顶摄, 不是 D435 —— 用错流会得
    "臂只有 90px、离 2.5~3m" 的荒谬结论。判据: 不动机器人时两帧差 0.01%(local) vs 0.93%(local2)。"""
    b = urllib.request.urlopen("http://127.0.0.1:8791/snapshot/local.jpg", timeout=8).read()
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def move_to(p, speed, step, pause):
    """小段移动(≤step mm, motion=J) + 每段停 pause 秒。返回是否到位。"""
    cur = np.array(G.pose()[0]) * 1000.0
    tgt = np.asarray(p, float)
    n = int(max(1, math.ceil(np.linalg.norm(tgt - cur) / step)))
    for k in range(1, n + 1):
        st = cur + (tgt - cur) * k / n
        c0 = np.array(G.pose()[0]) * 1000.0
        ok, bad, _s, _r = G.preflight()
        if not ok:
            print("   前置失效: %s" % " / ".join(bad))
            return False
        r = G.send({"cmd": "move-abs", "x": float(st[0] / 1000), "y": float(st[1] / 1000),
                    "z": float(st[2] / 1000), "speed": speed, "motion": "J",
                    "allow_movej_retry": True}, wait=60)
        if "PASS" not in str(r.get("verdict", "")):
            print("   被拒(%.0fmm): %s ⇒ 抬 z 再试" % (math.dist(st, c0), str(r.get("verdict"))[:60]))
            lift = c0.copy()
            lift[2] += 40.0
            r2 = G.send({"cmd": "move-abs", "x": lift[0] / 1000, "y": lift[1] / 1000, "z": lift[2] / 1000,
                         "speed": speed, "motion": "J", "allow_movej_retry": True}, wait=60)
            if "PASS" not in str(r2.get("verdict", "")):
                print("   抬 z 也被拒 ⇒ 放弃本段")
                return False
            G.wait_settle(c0 / 1000.0, 40.0, timeout=40, min_frac=0.5)
            if not wait_idle(10):
                return False
            time.sleep(pause)
            c1 = np.array(G.pose()[0]) * 1000.0
            r3 = G.send({"cmd": "move-abs", "x": st[0] / 1000, "y": st[1] / 1000, "z": st[2] / 1000,
                         "speed": speed, "motion": "J", "allow_movej_retry": True}, wait=60)
            if "PASS" not in str(r3.get("verdict", "")):
                print("   绕行后仍被拒 ⇒ 放弃本段")
                return False
            G.wait_settle(c1 / 1000.0, float(math.dist(st, c1)), timeout=40, min_frac=0.5)
            if not wait_idle(10):
                return False
            time.sleep(pause)
        G.wait_settle(c0 / 1000.0, float(math.dist(st, c0)), timeout=40, min_frac=0.5)
        if not wait_idle(10):
            # 🔴 实测: 一条被拒的 move 后控制器会一直停在 "moving" ⇒ 不能傻等 60s, 10s 不动就判死,
            #    否则整轮 8 个位姿全空转(现场见过 "不空闲(moving)" 连报 7 次)。
            print("   等不到 idle(10s) ⇒ 本轮作废")
            return False
        time.sleep(pause)
    return math.dist(np.array(G.pose()[0]) * 1000.0, tgt) < 12


def mask_of(a, b, thr=22, min_area=400):
    d = cv2.absdiff(a, b).max(axis=2)
    m = (d > thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None
    k = 1 + int(np.argmax(st[1:, 4]))
    if st[k, 4] < min_area:
        return None
    return (lab == k).astype(np.uint8)


def farthest(mask, ref):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    dd = (xs - ref[0]) ** 2 + (ys - ref[1]) ** 2
    # 取最远处 1% 点的平均, 抗单像素噪声
    k = max(1, len(dd) // 100)
    idx = np.argpartition(-dd, min(k, len(dd) - 1))[:k]
    return [float(np.nanmean(xs[idx])), float(np.nanmean(ys[idx]))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--speed", type=float, default=28.0)
    ap.add_argument("--step", type=float, default=45.0)
    ap.add_argument("--pause", type=float, default=10.0, help="每动一段停几秒(老倪: 画面有延迟)")
    ap.add_argument("--deadzone", type=float, default=8.0, help="每个位姿的微动 mm(用来抠出该位姿的臂轮廓)")
    ap.add_argument("--margin", type=float, default=120.0)
    ap.add_argument("--xs", default="500,610")
    ap.add_argument("--ys", default="180,340")
    ap.add_argument("--zs", default="220,330")
    ap.add_argument("--save", default=os.path.join(REPO, "data", "scene", "cam_calib.json"))
    ap.add_argument("--key", default="local2")
    a = ap.parse_args()

    boxes = boxes_mm()
    plan = [(float(x), float(y), float(z))
            for z in a.zs.split(",") for x in a.xs.split(",") for y in a.ys.split(",")]
    keep = []
    for p in plan:
        why = guard(p, boxes, margin=a.margin)
        if why:
            print("  跳过 %s: %s" % (tuple(round(v) for v in p), why))
        else:
            print("  采点 %s" % (tuple(round(v) for v in p),))
            keep.append(p)
    print("计划 %d 个位姿 · 围栏 %d 个盒子 · 每个位姿加 %.0fmm 微动抠轮廓" % (len(keep), len(boxes), a.deadzone))
    if a.dry or len(keep) < 6:
        return 0 if a.dry else 2

    os.makedirs(OUT, exist_ok=True)
    recs = []
    for i, p in enumerate(keep, 1):
        print("[%d/%d] → %s" % (i, len(keep), tuple(round(v) for v in p)))
        if not move_to(p, a.speed, a.step, a.pause):
            print("   没到位 ⇒ 跳过")
            continue
        A = d435()
        tcp = np.array(G.pose()[0]) * 1000.0
        # +deadzone 微动(只动 z, 小步, 一定在安全高度上)
        q = tcp.copy()
        q[2] += a.deadzone
        if not move_to(q, a.speed, a.step, max(2.0, a.pause / 2)):
            print("   微动失败 ⇒ 跳过")
            continue
        B = d435()
        m = mask_of(A, B)
        if m is None:
            print("   差分没抠出臂(画面太静/太糊) ⇒ 跳过")
            continue
        cx, cy = np.nonzero(m)[1].mean(), np.nonzero(m)[0].mean()
        f = [(i * 1000) + i for i in range(0)]
        cv2.imwrite(os.path.join(OUT, "arm%02d_A.jpg" % i), A)
        cv2.imwrite(os.path.join(OUT, "arm%02d_mask.png" % i), m * 255)
        recs.append({"tcp_mm": tcp.tolist(), "centroid": [float(cx), float(cy)], "mask": m,
                     "img": os.path.join(OUT, "arm%02d_A.jpg" % i)})
        print("   臂轮廓 %d px · 质心 (%.0f, %.0f) · TCP %s" % (
            int(m.sum()), cx, cy, np.round(tcp, 0)))

    if len(recs) < 6:
        print("只采到 %d 组 (<6 解不了外参) ⇒ 不落盘" % len(recs))
        return 3

    P3 = np.array([r["tcp_mm"] for r in recs])
    H, W = 480, 640
    tip = [list(r["centroid"]) for r in recs]
    best = None
    for it in range(4):
        P2 = np.array(tip)
        T, K, rms, mx = solve_extrinsics(P3, P2, W, H)
        # 基座原点投到图上, 用它重取"离基座最远的轮廓点"
        rvec, _ = cv2.Rodrigues(T[:3, :3])
        uv, _ = cv2.projectPoints(np.zeros((1, 1, 3)), rvec, T[:3, 3], K, None)
        base_px = uv.reshape(2)
        if not np.isfinite(base_px).all():
            break
        tip = []
        for r in recs:
            f = farthest(r["mask"], base_px)
            tip.append(f if f else list(r["centroid"]))
        P2b = np.array(tip)
        T2, K2, rms2, mx2 = solve_extrinsics(P3, P2b, W, H)
        print("  迭代%d: 质心/最远点 → RMS %.2f/%.2fpx · 光心 %s" % (
            it + 1, rms, rms2, np.round(T2[:3, 3], 0)))
        best = (T2, K2, rms2, mx2, P2b, base_px)
        tip = [list(q) for q in P2b]

    T, K, rms, mx, P2, base_px = best
    cam = T[:3, 3]
    print("\n解出: f=%.1f · 光心 base %s mm · 重投影 RMS %.2fpx 最大 %.2fpx" % (
        K[0, 0], np.round(cam, 0), rms, mx))
    # 留证图: 8 个位姿的臂尖 + 基座投影
    for i, r in enumerate(recs):
        img = cv2.imread(r["img"])
        if img is None:
            continue
        cv2.circle(img, tuple(int(v) for v in P2[i]), 9, (0, 200, 255), 2)
        cv2.drawMarker(img, tuple(int(v) for v in base_px), (255, 80, 80), cv2.MARKER_CROSS, 30, 2)
        cv2.putText(img, "pose%d TCP %s" % (i + 1, np.round(r["tcp_mm"], 0).astype(int).tolist()),
                    (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imwrite(r["img"].replace(".jpg", "_proof.jpg"), img)

    dist = float(np.linalg.norm(cam))
    sane = (rms <= 10.0 and mx <= 25.0 and 800.0 <= dist <= 4500.0 and 200.0 <= cam[2] <= 3000.0)
    print("口径检查: 光心离基座 %.0fmm · z=%.0fmm · %s" % (dist, cam[2], "通过" if sane else "不通过"))
    if not sane:
        print("⇒ 不落盘(解不可信, 如实上报). 留证图已在 %s" % OUT)
        return 4
    cal = json.load(open(a.save, encoding="utf-8")) if os.path.exists(a.save) else {}
    e = cal.get(a.key) or {}
    e.update({"kind": "extrinsic", "model": "pinhole", "f": float(K[0, 0]), "cx": float(K[0, 2]),
              "cy": float(K[1, 2]), "T_base_cam": T.tolist(),
              "source": "臂尖帧差分 %d 位姿 · RMS %.2fpx · 最大 %.2fpx" % (len(P3), rms, mx),
              "rmse_px": round(rms, 3), "n_pts": len(P3)})
    cal[a.key] = e
    json.dump(cal, open(a.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump([{"tcp_mm": r["tcp_mm"], "uv": P2[i].tolist()} for i, r in enumerate(recs)],
              open(os.path.join(OUT, "arm_pairs.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写入 %s [%s]" % (a.save, a.key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
