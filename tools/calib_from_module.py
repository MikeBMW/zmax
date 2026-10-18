#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_from_module.py —— 不靠标定板: 用"夹爪夹着的光模块"当靶标, 自动解固定相机(D435)外参

思路(老倪 2026-10-18: 「自动化跑吧」「三维视图的3个长方体, 不要碰到了, 那是边界」):
  · 模块被夹爪夹住 ⇒ 它跟着 TCP 走, 每个位姿都有一个**已知的 base 3D 点**(腕相机链路算出)
  · 同一时刻在固定相机(D435)里检出它的像素 ⇒ 一对 3D↔2D 对应
  · 采 ≥8 个位姿(在安全区内四角+两高度) ⇒ DLT 线性初值 + LM 收细 ⇒ T_base_cam
  · 验收: 每个位姿把 3D 投回像素, 报残差; 画叠加图留证

安全: 每个目标点都过 guard(围栏盒子 m→mm + 外扩 margin + 台面 z + x 下限), 超限拒发。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G          # noqa: E402
import opt_box3d as OB         # noqa: E402

OUT = os.path.join(REPO, "zmax_data", "calib_d435")
FENCES = os.path.join(REPO, "zmax_data", "ar_rs", "fences.json")
MOD_STATE = "/dev/shm/mod3_latest.json"


def boxes_mm():
    out = []
    d = json.load(open(FENCES, encoding="utf-8"))
    for e in d.get("items", []):
        if str(e.get("type")).lower() != "box" or e.get("enabled") is False:
            continue
        a, b = e["p1"], e["p2"]
        lo = [min(a[i], b[i]) * 1000.0 for i in range(3)]
        hi = [max(a[i], b[i]) * 1000.0 for i in range(3)]
        out.append((e.get("name") or e["id"], lo, hi))
    return out


def guard(pt, boxes, margin=150.0, zmin=60.0, xmin=100.0):
    """TCP 点 + 外扩 margin 不许碰围栏盒子。返回拒绝原因或 None。"""
    x, y, z = pt
    if z < zmin:
        return "z=%.0f < %.0f" % (z, zmin)
    if x < xmin:
        return "x=%.0f < %.0f" % (x, xmin)
    for name, lo, hi in boxes:
        if (lo[0] - margin <= x <= hi[0] + margin and lo[1] - margin <= y <= hi[1] + margin
                and lo[2] - margin <= z <= hi[2] + margin):
            return "离围栏[%s]不足 %.0fmm" % (name, margin)
    return None


def wait_idle(timeout=60.0):
    """等控制器回 idle。实测: 上一条 move 刚发完就发下一条, 前置会判 "不空闲(moving)" ⇒ 整轮白跑。"""
    import urllib.request as _ur
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = json.loads(_ur.urlopen("http://127.0.0.1:8793/ctl/status", timeout=4).read().decode())
            r = st.get("robot") or {}
            if str(r.get("operation", "")).lower() in ("idle", "idle_state", "stationary") and not r.get("has_error"):
                return True
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(1.0)
    return False


def d435_frame():
    import urllib.request
    b = urllib.request.urlopen("http://127.0.0.1:8791/snapshot/local2.jpg", timeout=8).read()
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def head_uv(img, box):
    """模块**头顶中心**的像素: 在检出框里找绿色拉环(bail)质心 —— 老倪: TCP=头顶中心, 绿拉环就在头顶。
    绿像素太少(远景/糊)时退回框中心, 并标 fallback。"""
    import cv2 as _cv
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1 = max(0, x1 - 6), max(0, y1 - 6)
    x2, y2 = min(img.shape[1], x2 + 6), min(img.shape[0], y2 + 6)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0), "box"
    hsv = _cv.cvtColor(crop, _cv.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] > 33) & (hsv[:, :, 0] < 98) & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 40))
    if m.sum() >= 30:
        ys, xs = np.nonzero(m)
        return (x1 + float(xs.mean()), y1 + float(ys.mean())), "green_bail"
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0), "box"


def det_in_d435(img, prev_box=None):
    """在 D435 图里找光模块。先用全图(低阈), 再在 prev 附近 ROI 放大重检; 取最近者。"""
    def pick(items):
        if not items:
            return None
        if prev_box is None:
            return max(items, key=lambda d: d["conf"])
        cx, cy = (prev_box[0] + prev_box[2]) / 2, (prev_box[1] + prev_box[3]) / 2
        return min(items, key=lambda d: math.hypot((d["xyxy"][0] + d["xyxy"][2]) / 2 - cx,
                                                  (d["xyxy"][1] + d["xyxy"][3]) / 2 - cy))
    d = pick(OB.detect_boxes(img, 0.12))
    if d:
        return d, "global"
    if prev_box is not None:
        H, W = img.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in prev_box]
        pad = 80
        cx1, cy1 = max(0, x1 - pad), max(0, y1 - pad)
        cx2, cy2 = min(W, x2 + pad), min(H, y2 + pad)
        crop = img[cy1:cy2, cx1:cx2]
        if crop.size:
            for fx in (2.0, 3.0):
                big = cv2.resize(crop, None, fx=fx, fy=fx, interpolation=cv2.INTER_CUBIC)
                r = OB.detect_boxes(big, 0.10)
                if r:
                    b = dict(max(r, key=lambda t: t["conf"]))
                    b["xyxy"] = [cx1 + v / fx for v in b["xyxy"]]
                    return b, "roi%.0fx" % fx
    return None, None


def solve_extrinsics(pts3, pts2, W, H):
    """DLT(Hartley 归一化) + LM 收细: 7 参 f+rvec+t, 主点固定图像中心。"""
    from scipy.optimize import least_squares
    P3 = np.asarray(pts3, float)
    P2 = np.asarray(pts2, float)
    c3 = P3.mean(0)
    s3 = np.sqrt(3) / max(1e-9, np.mean(np.linalg.norm(P3 - c3, axis=1)))
    T3 = np.eye(4)
    T3[:3, :3] *= s3
    T3[:3, 3] = -s3 * c3
    c2 = P2.mean(0)
    s2 = np.sqrt(2) / max(1e-9, np.mean(np.linalg.norm(P2 - c2, axis=1)))
    T2 = np.array([[s2, 0, -s2 * c2[0]], [0, s2, -s2 * c2[1]], [0, 0, 1]])
    A = []
    for (X, Y, Z, _), (u, v) in zip((T3 @ np.hstack([P3, np.ones((len(P3), 1))]).T).T, (T2 @ np.hstack([P2, np.ones((len(P2), 1))]).T).T):
        A.append([X, Y, Z, 1, 0, 0, 0, 0, -u * X, -u * Y, -u * Z, -u])
        A.append([0, 0, 0, 0, X, Y, Z, 1, -v * X, -v * Y, -v * Z, -v])
    _, _, Vt = np.linalg.svd(np.array(A))
    Pn = Vt[-1].reshape(3, 4)
    P = np.linalg.inv(T2) @ Pn @ T3
    K, R = cv2.RQDecomp3x3(P[:, :3])[:2]
    f = float((K[0, 0] + K[1, 1]) / 2.0)
    t = np.linalg.solve(K, P[:, 3])

    def resid(x):
        ff, rv, tt = x[0], x[1:4], x[4:7]
        Rm, _ = cv2.Rodrigues(rv)
        proj = (Rm @ P3.T).T + tt
        proj[:, :2] /= proj[:, 2:3]
        uv = np.c_[ff * proj[:, 0] + W / 2.0, ff * proj[:, 1] + H / 2.0]
        return (uv - P2).ravel()

    x0 = np.r_[f, cv2.Rodrigues(R)[0].ravel(), t]
    sol = least_squares(resid, x0, method="trf", x_scale="jac")
    ff, rv, tt = sol.x[0], sol.x[1:4], sol.x[4:7]
    Rm, _ = cv2.Rodrigues(rv)
    T = np.eye(4)
    T[:3, :3] = Rm
    T[:3, 3] = tt
    K = np.array([[ff, 0, W / 2.0], [0, ff, H / 2.0], [0, 0, 1]])
    return T, K, float(np.sqrt(np.mean(sol.fun ** 2))), float(np.abs(sol.fun).max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--speed", type=float, default=30.0, help="mm/s, 慢慢来")
    ap.add_argument("--pause", type=float, default=10.0, help="每动一段停几秒(画面有延迟)")
    ap.add_argument("--step", type=float, default=50.0, help="单段最大位移 mm(>100 会被奇异区拒)")
    ap.add_argument("--save", default=os.path.join(REPO, "data", "scene", "cam_calib.json"))
    ap.add_argument("--margin", type=float, default=130.0, help="离围栏盒子的最小外扩 mm")
    ap.add_argument("--xs", default="500,620")
    ap.add_argument("--ys", default="70,180,300")
    ap.add_argument("--zs", default="190,340")
    ap.add_argument("--key", default="local2")
    a = ap.parse_args()
    boxes = boxes_mm()
    xs = [float(v) for v in a.xs.split(",")]
    ys = [float(v) for v in a.ys.split(",")]
    zs = [float(v) for v in a.zs.split(",")]
    plan = [(x, y, z) for z in zs for x in xs for y in ys]
    bad = [(p, guard(p, boxes, margin=a.margin)) for p in plan]
    for p, r in bad:
        print(("  跳过 %s: %s" % (tuple(round(v) for v in p), r)) if r else ("  采点 %s" % (tuple(round(v) for v in p),)))
    plan = [p for p, r in bad if not r]
    print("计划 %d 个位姿 (围栏 %d 个盒子, 外扩 %.0fmm)" % (len(plan), len(boxes), a.margin))
    if a.dry:
        return 0

    os.makedirs(OUT, exist_ok=True)
    recs = []
    prev_box = None
    for i, p in enumerate(plan, 1):
        ok, bad0, _st, _rb = G.preflight()
        if not ok:
            print("🛑 前置失效: %s ⇒ 停" % " / ".join(bad0))
            break
        p0 = np.array(G.pose()[0]) * 1000.0
        # 🔴 实测: 单步位移 >100mm 就被控制器判 "疑似 50102 奇异点" 拒发(110/230/280mm 全被拒, 60mm 通过)
        # ⇒ 一律拆成 ≤60mm 的小段: 先抬 → 再横移 → 再下降, 每段回读真值。
        STEP = a.step

        def seg(a, b):
            a = np.asarray(a, float)
            b = np.asarray(b, float)
            n = int(max(1, math.ceil(np.linalg.norm(b - a) / STEP)))
            return [a + (b - a) * (k + 1) / n for k in range(n)]

        cur = np.array(G.pose()[0]) * 1000.0
        hi_z = max(p[2], cur[2], 380.0)
        path = []
        path += seg(cur, [cur[0], cur[1], hi_z])
        path += seg([cur[0], cur[1], hi_z], [p[0], p[1], hi_z])
        path += seg([p[0], p[1], hi_z], [p[0], p[1], p[2]])
        aborted = False
        for j, st in enumerate(path, 1):
            c0 = np.array(G.pose()[0]) * 1000.0
            if math.dist(st, c0) < 6:
                continue
            ok, bad0, _st, _rb = G.preflight()
            if not ok:
                print("[%d/%d] 第%d段前置失效: %s" % (i, len(plan), j, " / ".join(bad0)))
                aborted = True
                break
            # 50120 实测: 笛卡尔 MoveL 沿路径进奇异区 ⇒ 直接要关节空间 MoveJ(整段仍是笛卡尔目标)
            r = G.send({"cmd": "move-abs", "x": st[0] / 1000.0, "y": st[1] / 1000.0, "z": st[2] / 1000.0,
                        "speed": a.speed, "motion": "J", "allow_movej_retry": True}, wait=60)
            if "PASS" not in str(r.get("verdict", "")):
                print("[%d/%d] 第%d段被拒(%.0fmm): %s" % (i, len(plan), j, math.dist(st, c0),
                                                        str(r.get("verdict"))[:80]))
                aborted = True
                break
            G.wait_settle(c0 / 1000.0, float(math.dist(st, c0)), timeout=40, min_frac=0.5)
            if not wait_idle(60):
                print("[%d/%d] 第%d段后没等到 idle ⇒ 停" % (i, len(plan), j))
                aborted = True
                break
            time.sleep(a.pause)          # 🔴 老倪 2026-10-18「画面有延迟, 你要慢慢移动, 动一下停10秒」
        if aborted:
            continue
        if math.dist(np.array(G.pose()[0]) * 1000.0, np.array(p)) > 12:
            print("[%d/%d] 没走到目标位姿(现值 %s) ⇒ 跳过" % (
                i, len(plan), np.round(np.array(G.pose()[0]) * 1000, 0)))
            continue
        wait_idle(60)
        tcp_xyz = np.array(G.pose()[0]) * 1000.0
        try:
            mod = json.load(open(MOD_STATE, encoding="utf-8"))
        except Exception:                                                   # noqa: BLE001
            mod = {}
        if not (mod.get("ok") and time.time() - float(mod.get("ts") or 0) < 3.0):
            print("[%d/%d] 腕相机模块状态过期/失败 ⇒ 跳过" % (i, len(plan)))
            continue
        img = d435_frame()
        det, how = det_in_d435(img, prev_box)
        if not det:
            print("[%d/%d] D435 里没检出模块 ⇒ 跳过" % (i, len(plan)))
            continue
        bx = det["xyxy"]
        prev_box = bx
        uv, uv_how = head_uv(img, bx)
        # 🔴 老倪 2026-10-18: 「tool1 TCP 就是光模块头顶中心, 这个点很重要」
        # ⇒ 3D 点直接用 TCP 真值(全站最硬的一个数), 不再用视觉反推的模块中心。
        p3 = tcp_xyz.tolist()
        recs.append({"tcp_mm": tcp_xyz.tolist(), "uv_how": uv_how, "base_mm": p3,   # = TCP 真值(模块头顶中心) "uv": uv, "conf": det["conf"], "how": how,
                     "t": time.strftime("%H:%M:%S")})
        f = os.path.join(OUT, "pose%02d_%s.jpg" % (i, time.strftime("%H%M%S")))
        cv2.imwrite(f, img)
        recs[-1]["img"] = f
        print("[%d/%d] TCP(=模块头顶中心) %s → 像素 (%.0f, %.0f) conf %.2f (%s/%s)" % (
            i, len(plan), np.round(tcp_xyz, 1), uv[0], uv[1], det["conf"], how, uv_how))

    json.dump(recs, open(os.path.join(OUT, "module_pairs.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    if len(recs) < 6:
        print("只采到 %d 对点 (<6 解不了外参) ⇒ 如实不落盘" % len(recs))
        return 3
    P3 = np.array([r["base_mm"] for r in recs])
    P2 = np.array([r["uv"] for r in recs])
    H, W = 720, 1280
    T, K, rms, mx = solve_extrinsics(P3, P2, W, H)
    print("解出: f=%.1f · 光心 %s · 重投影 RMS %.2fpx / 最大 %.2fpx" % (
        K[0, 0], np.round(T[:3, 3], 1), rms, mx))
    if T[2, 3] < 0 or rms > 12:
        print("⚠ 不合理(光心 z=%.1f, rms %.1f) ⇒ 不落盘" % (T[2, 3], rms))
        return 4
    if a.save:
        cal = json.load(open(a.save, encoding="utf-8")) if os.path.exists(a.save) else {}
        e = cal.get(a.key) or {}
        e.update({"kind": "extrinsic", "model": "pinhole", "f": float(K[0, 0]), "cx": float(K[0, 2]),
                  "cy": float(K[1, 2]), "T_base_cam": T.tolist(),
                  "source": "模块头顶中心(=TCP真值) %d 位姿 · 重投影 RMS %.2fpx · 最大 %.2fpx" % (len(P3), rms, mx),
                  "rmse_px": round(rms, 3), "n_pts": len(P3)})
        cal[a.key] = e
        json.dump(cal, open(a.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写入 %s [%s]" % (a.save, a.key))
    # 留证: 每帧画投影点
    for r in recs[:4]:
        img = cv2.imread(r["img"])
        if img is None:
            continue
        pr, _ = cv2.projectPoints(np.array([r["base_mm"]]), cv2.Rodrigues(T[:3, :3])[0].ravel(), T[:3, 3], K, None)
        uv = pr.reshape(2)
        cv2.drawMarker(img, (int(uv[0]), int(uv[1])), (0, 220, 120), cv2.MARKER_CROSS, 40, 3)
        cv2.circle(img, (int(r["uv"][0]), int(r["uv"][1])), 8, (0, 160, 255), 2)
        cv2.imwrite(r["img"].replace(".jpg", "_proof.jpg"), img)
    print("留证图: %s/pose*_proof.jpg (绿十字=按外参投的, 橙圈=检测到的)" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
