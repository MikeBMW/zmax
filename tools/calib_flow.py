#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_flow.py —— 用"纯平移下同一批特征点的像素位移"解固定相机(D435)外参

为什么这么做(2026-10-18 现场):
  · D435 里没有能用的靶标: 圆点板/ArUco 都没有; 在役 YOLO 权重只认腕相机视角, 在 D435 上一片 0 检出。
  · 但臂在画面里很大(local 流: 不动机器人两帧差 0.01%, 臂移 80mm 变化 12%)。
  · 于是: 让臂**只平移不转**(姿态保持不变), 平移量 TCP 真值已知 ⇒ 臂上任意一点的三维位移都等于该平移量。
    用 LK 光流把同一批特征点从第 1 个位姿跟到第 n 个位姿, 就得到 (P_j, P_j+Δ_i) → (u_ij, v_ij) 的约束。
  · 未知量: 相机 f、旋转 R(3)、平移 t(3) + 每个特征点初始三维 P_j(3)。
    方程 2*N_feat*N_pose 个 ≫ 未知量 ⇒ 联合最小二乘(bundle adjustment 的简化版, 结构点共享)。
  · 判据: 重投影 RMS ≤ 3px 且解出的相机在机器人前方 0.4~4m、高度 0.1~2.5m ⇒ 才落盘。

子命令:
  --capture   移动并采 6 个纯平移位姿(每段 ≤45mm, 动一下停 --pause 秒), 落盘 frames/ + poses.json
  --solve     离线解算(不动机器人)
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
import grasp_opt as G                                      # noqa: E402
from calib_from_module import boxes_mm, guard               # noqa: E402

OUT = os.path.join(REPO, "zmax_data", "calib_d435", "flow")


def snap():
    """真 D435 = 8791 'local' (640×480)。local2 是 MAXHUB, 别搞错。"""
    b = urllib.request.urlopen("http://127.0.0.1:8791/snapshot/local.jpg", timeout=8).read()
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def wait_idle(timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st = json.loads(urllib.request.urlopen("http://127.0.0.1:8793/ctl/status", timeout=4).read().decode())
            r = st.get("robot") or {}
            if str(r.get("operation", "")).lower() in ("idle", "idle_state", "stationary") and not r.get("has_error"):
                return True
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(0.8)
    return False


def move_to(p, speed, step, pause, abc0=None):
    """只平移(姿态保持 abc0 不变), 分 ≤step 的小段 + 每段停 pause 秒"""
    cur = np.array(G.pose()[0]) * 1000.0
    tgt = np.asarray(p, float)
    n = int(max(1, math.ceil(np.linalg.norm(tgt - cur) / step)))
    for k in range(1, n + 1):
        st = cur + (tgt - cur) * k / n
        ok, bad, _s, _r = G.preflight()
        if not ok:
            print("   前置失效: %s" % " / ".join(bad))
            return False
        cmd = {"cmd": "move-abs", "x": float(st[0] / 1000), "y": float(st[1] / 1000),
               "z": float(st[2] / 1000), "speed": speed, "motion": "J", "allow_movej_retry": True}
        c0 = np.array(G.pose()[0]) * 1000.0
        r = G.send(cmd, wait=60)
        if "PASS" not in str(r.get("verdict", "")):
            print("   被拒(%.0fmm): %s ⇒ 放弃" % (math.dist(st, c0), str(r.get("verdict"))[:60]))
            return False
        G.wait_settle(c0 / 1000.0, float(math.dist(st, c0)), timeout=40, min_frac=0.5)
        if not wait_idle(10):
            print("   等不到 idle ⇒ 放弃")
            return False
        time.sleep(pause)
    return math.dist(np.array(G.pose()[0]) * 1000.0, tgt) < 12


def capture(a):
    boxes = boxes_mm()
    os.makedirs(OUT, exist_ok=True)
    p0 = np.array(G.pose()[0]) * 1000.0
    # 🔴 老倪 2026-10-18「别升高太高了」: 位移以**横向**为主, 竖向只做小幅(≤40mm)且封顶 z=380
    zcap = min(p0[2] + 40.0, a.zcap)
    # 🔴 实测: x 方向 +60mm 就撞上"检测设备"盒子外扩区(x≥625 全被否) ⇒ 改成**只在 y 方向走 + 小 z 下移**,
    #    位姿点全在 x=610、y 145~305、z 260~300 这条窄走廊里, 既不升高也不靠近围栏。
    deltas = [[0, 0, 0], [0, -80, 0], [0, -160, 0], [0, -80, -40], [0, 0, -40]]
    plan = []
    for d in deltas:
        q = p0 + np.array(d, float)
        q[2] = min(q[2], zcap)
        if q[2] < 60:
            continue
        plan.append(q)
    plan = [p for p in plan if guard(p, boxes, margin=a.margin) is None]
    print("计划 %d 个纯平移位姿(姿态不动), 围栏外扩 %.0fmm" % (len(plan), a.margin))
    recs = []
    for i, p in enumerate(plan, 1):
        print("[%d/%d] → %s" % (i, len(plan), tuple(round(v) for v in p)))
        if not move_to(p, a.speed, a.step, a.pause):
            print("   没到位 ⇒ 跳过")
            continue
        time.sleep(a.pause)                       # 老倪: 画面有延迟, 停稳再拍
        im = snap()
        tcp = np.array(G.pose()[0]) * 1000.0
        f = os.path.join(OUT, "f%02d.jpg" % i)
        cv2.imwrite(f, im)
        recs.append({"tcp_mm": tcp.tolist(), "img": f})
        print("   拍下 %s · TCP %s" % (f.split("/")[-1], np.round(tcp, 1)))
    json.dump(recs, open(os.path.join(OUT, "poses.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("落盘 %d 个位姿 → %s/poses.json" % (len(recs), OUT))
    return 0


def solve(a):
    man = json.load(open(os.path.join(OUT, "poses.json"), encoding="utf-8"))
    imgs = [cv2.imread(r["img"], cv2.IMREAD_GRAYSCALE) for r in man]
    imgs = [i for i in imgs if i is not None]
    P3 = np.array([r["tcp_mm"] for r in man], float)
    if len(imgs) < 3:
        print("位姿不足")
        return 2
    H, W = imgs[0].shape
    # 特征: 第 1 帧的角点, 用 LK 逐帧跟踪
    p0 = cv2.goodFeaturesToTrack(imgs[0], maxCorners=400, qualityLevel=0.01, minDistance=8)
    if p0 is None:
        print("没有角点")
        return 3
    tracks = [p0.reshape(-1, 2)]
    prev = imgs[0]
    for k in range(1, len(imgs)):
        nxt, st, err = cv2.calcOpticalFlowPyrLK(prev, imgs[k], tracks[-1].reshape(-1, 1, 2).astype(np.float32),
                                               None, winSize=(21, 21), maxLevel=3)
        tracks.append(nxt.reshape(-1, 2))
        st = st.reshape(-1)
        tracks = [t[st > 0] for t in tracks]            # 只保留一直跟得住的
        if len(tracks[-1]) < 20:
            print("跟踪点太少(%d) ⇒ 停" % len(tracks[-1]))
            return 4
        prev = imgs[k]
    N = len(tracks[-1])
    obs = np.stack([tracks[k][:N] for k in range(len(imgs))])          # (K,N,2)
    print("特征点 %d 个 · 位姿 %d 个" % (N, len(imgs)))
    top = [np.linalg.norm(obs[k] - obs[0], axis=1).mean() for k in range(len(imgs))]
    print("平均像素位移(相对第1位姿): %s" % [round(v, 1) for v in top])

    from scipy.optimize import least_squares
    D = P3 - P3[0]                                    # 各位姿相对第 1 个位姿的已知平移(mm)

    def unpack(x):
        f, rv, t, pts = x[0], x[1:4], x[4:7], x[7:].reshape(N, 3)
        R, _ = cv2.Rodrigues(rv)
        return f, R, t, pts

    def resid(x):
        f, R, t, pts = unpack(x)
        out = []
        for k in range(len(imgs)):
            Q = (R @ (pts + D[k]).T).T + t
            z = Q[:, 2]
            z = np.where(np.abs(z) < 1e-3, 1e-3, z)
            uv = np.c_[f * Q[:, 0] / z + W / 2.0, f * Q[:, 1] / z + H / 2.0]
            out.append((uv - obs[k]).ravel())
        return np.concatenate(out)

    best = None
    span = float(np.linalg.norm(D.max(0) - D.min(0))) + 1.0
    for dist in (900.0, 1400.0, 2000.0):
        for az in (-40, 0, 40, 90, 140):
            # 相机放在"臂前方 dist 处, 方位 az", 看回臂
            tgt0 = P3[0]
            cam = tgt0 + np.array([dist * math.sin(math.radians(az)), -dist * math.cos(math.radians(az)), 350.0])
            fwd = tgt0 - cam
            fwd = fwd / np.linalg.norm(fwd)
            up = np.array([0, 0, 1.0])
            right = np.cross(fwd, up)
            right /= max(1e-9, np.linalg.norm(right))
            up2 = np.cross(right, fwd)
            Rcw = np.stack([right, -up2, fwd])                  # 相机系 x右 y下 z前
            # P_cam = Rcw (P - cam)  ⇒ 世界→相机 R=Rcw, t=-Rcw@cam
            rv = cv2.Rodrigues(Rcw)[0].ravel()
            t = -Rcw @ cam
            pts0 = np.tile(tgt0 + np.array([0, 0, 0.0]), (N, 1)).astype(float)
            # 用第 1 帧像素与假想深度反解初值
            for j in range(N):
                u = (obs[0][j][0] - W / 2.0) / 500.0
                v = (obs[0][j][1] - H / 2.0) / 500.0
                pts0[j] = cam + Rcw.T @ (np.array([u, v, 1.0]) * dist)
            x0 = np.r_[500.0, rv, t, pts0.ravel()]
            try:
                sol = least_squares(resid, x0, method="trf", x_scale="jac", max_nfev=60)
            except Exception:                                               # noqa: BLE001
                continue
            rms = float(np.sqrt(np.mean(sol.fun ** 2)))
            f, R, t, pts = unpack(sol.x)
            cam_pos = -R.T @ t
            if best is None or rms < best[0]:
                best = (rms, sol.x, cam_pos, f)
                print("  初值 dist=%.0f az=%.0f° → RMS %.2fpx f=%.0f 光心 %s" % (
                    dist, az, rms, f, np.round(cam_pos, 0)))
    if best is None:
        print("全部初值失败")
        return 5
    rms, x, cam_pos, f = best
    fv, R, t, pts = unpack(x)
    dist = float(np.linalg.norm(cam_pos))
    sane = rms <= 3.0 and 400.0 <= dist <= 4000.0 and 100.0 <= cam_pos[2] <= 2500.0
    print("\n最优: RMS %.2fpx · f=%.0f · 光心 base %s mm · 离基座 %.0fmm · %s" % (
        rms, fv, np.round(cam_pos, 0), dist, "通过" if sane else "不通过"))
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    K = np.array([[fv, 0, W / 2.0], [0, fv, H / 2.0], [0, 0, 1]])
    # 留证: 各位姿把 TCP 投到图上
    for k, r in enumerate(man[:len(imgs)]):
        img = cv2.imread(r["img"])
        Q = R @ (P3[k] - P3[0] + P3[0]) + t
        if Q[2] > 0:
            uv = np.array([fv * Q[0] / Q[2] + W / 2.0, fv * Q[1] / Q[2] + H / 2.0])
            cv2.drawMarker(img, tuple(int(v) for v in uv), (60, 60, 235), cv2.MARKER_CROSS, 26, 2)
            cv2.putText(img, "TCP %s → px %s" % (P3[k].astype(int).tolist(), uv.astype(int).tolist()),
                        (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imwrite(r["img"].replace(".jpg", "_proof.jpg"), img)
    if not sane or a.dry:
        return 4 if not sane else 0
    cal = json.load(open(a.save, encoding="utf-8")) if os.path.exists(a.save) else {}
    e = cal.get(a.key) or {}
    e.update({"kind": "extrinsic", "model": "pinhole", "f": float(fv), "cx": float(W / 2), "cy": float(H / 2),
              "T_base_cam": T.tolist(), "rmse_px": round(rms, 3), "n_pts": int(N),
              "source": "纯平移光流 BA %d 位姿/%d 特征 · RMS %.2fpx" % (len(imgs), N, rms)})
    cal[a.key] = e
    json.dump(cal, open(a.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写入 %s [%s]" % (a.save, a.key))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--solve", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--speed", type=float, default=28.0)
    ap.add_argument("--step", type=float, default=45.0)
    ap.add_argument("--pause", type=float, default=8.0)
    ap.add_argument("--margin", type=float, default=120.0)
    ap.add_argument("--zcap", type=float, default=380.0, help="最高 z(mm) —— 老倪要求别升太高")
    ap.add_argument("--save", default=os.path.join(REPO, "data", "scene", "cam_calib.json"))
    ap.add_argument("--key", default="local")
    a = ap.parse_args()
    if a.capture:
        return capture(a)
    if a.solve:
        return solve(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
