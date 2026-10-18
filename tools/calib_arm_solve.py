#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_arm_solve.py —— 离线解算: 用已落盘的"每个位姿的臂轮廓掩膜 + TCP 真值"求固定相机外参

背景(2026-10-18): 采集端 calib_from_arm.py 在解算处崩了一次(已经修), 但 8 个位姿的
图片和掩膜都已经落盘 ⇒ 不必重新动臂, 直接离线解。

算法:
  · 每个位姿有一张 mask(该位姿下臂的轮廓, 由 ±8mm 微动的帧差分得到)
  · 位姿 i 的"臂尖像素"取 mask 上**离基座最远**的点(取最远 1% 的均值, 抗噪)
  · 基座像素是未知量 ⇒ 迭代: 质心初值 → 解 → 投基座 → 重取最远点 → 再解
用法:
  ./gui-venv311/bin/python tools/calib_arm_solve.py --tcp "[500,180,220],[500,340,220],..." \
      --masks zmax_data/calib_d435/arm0{1..8}_mask.png
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
from calib_from_module import solve_extrinsics     # noqa: E402


def farthest(mask, ref):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    dd = (xs - ref[0]) ** 2 + (ys - ref[1]) ** 2
    k = max(1, len(dd) // 100)
    idx = np.argpartition(-dd, min(k, len(dd) - 1))[:k]
    return [float(xs[idx].mean()), float(ys[idx].mean())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcp", required=True, help='[[500,180,220],[...]] 或 "500,180,220;500,340,220"')
    ap.add_argument("--masks", nargs="+", required=True)
    ap.add_argument("--img-pattern", default="", help="证明图模板, 默认由 mask 名推 *_A.jpg")
    ap.add_argument("--save", default=os.path.join(REPO, "data", "scene", "cam_calib.json"))
    ap.add_argument("--key", default="local")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    txt = a.tcp.strip()
    if txt.startswith("["):
        P3 = np.array(json.loads(txt), float)
    else:
        P3 = np.array([[float(v) for v in s.split(",")] for s in txt.split(";")], float)

    masks, names = [], []
    for m in a.masks:
        for f in sorted(glob.glob(m)):
            im = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            if im is None:
                continue
            masks.append((im > 40).astype(np.uint8))
            names.append(f)
    print("位姿 %d 个 · 掩膜 %d 张" % (len(P3), len(masks)))
    if len(P3) != len(masks):
        print("⚠ 位姿数 %d ≠ 掩膜数 %d" % (len(P3), len(masks)))
        n = min(len(P3), len(masks))
        P3, masks, names = P3[:n], masks[:n], names[:n]

    H, W = masks[0].shape
    tip = [[float(np.nonzero(m)[1].mean()), float(np.nonzero(m)[0].mean())] for m in masks]
    best = None
    for it in range(5):
        T, K, rms, mx = solve_extrinsics(P3, np.array(tip), W, H)
        rvec, _ = cv2.Rodrigues(T[:3, :3])
        uv, _ = cv2.projectPoints(np.zeros((1, 1, 3)), rvec, T[:3, 3], K, None)
        base_px = uv.reshape(2)
        new_tip = [farthest(m, base_px) or tip[i] for i, m in enumerate(masks)]
        T2, K2, rms2, mx2 = solve_extrinsics(P3, np.array(new_tip), W, H)
        print("  迭代%d: RMS %.2f→%.2fpx · 光心 %s mm" % (it + 1, rms, rms2, np.round(T2[:3, 3], 0)))
        if best and abs(rms2 - best[2]) < 0.05:
            best = (T2, K2, rms2, mx2, new_tip, base_px)
            break
        best = (T2, K2, rms2, mx2, new_tip, base_px)
        tip = [list(q) for q in new_tip]

    T, K, rms, mx, tip, base_px = best
    cam = T[:3, 3]
    dist = float(np.linalg.norm(cam))
    print("\n解: f=%.1f · 光心 base %s mm · 离基座 %.0fmm · RMS %.2fpx 最大 %.2fpx" % (
        K[0, 0], np.round(cam, 0), dist, rms, mx))
    # 逐点残差
    rvec, _ = cv2.Rodrigues(T[:3, :3])
    uv, _ = cv2.projectPoints(P3.reshape(-1, 1, 3), rvec, T[:3, 3], K, None)
    uv = uv.reshape(-1, 2)
    for i in range(len(P3)):
        e = np.linalg.norm(uv[i] - np.array(tip[i]))
        print("  位姿%d TCP %s → 实测点 (%.0f,%.0f) · 投 (%.0f,%.0f) · 差 %.1fpx" % (
            i + 1, P3[i].astype(int).tolist(), tip[i][0], tip[i][1], uv[i][0], uv[i][1], e))
    sane = rms <= 12.0 and 500.0 <= dist <= 4000.0 and 100.0 <= cam[2] <= 2500.0
    print("口径: %s" % ("通过" if sane else "不通过(不落盘)"))
    if a.dry:
        return 0
    # 留证
    for i, f in enumerate(names):
        img = cv2.imread(f.replace("_mask.png", "_A.jpg"))
        if img is None:
            continue
        m = cv2.cvtColor((masks[i] * 255), cv2.COLOR_GRAY2BGR)
        vis = cv2.addWeighted(img, 0.75, m, 0.25, 0)
        cv2.circle(vis, tuple(int(v) for v in tip[i]), 8, (0, 200, 255), 2)
        cv2.drawMarker(vis, tuple(int(v) for v in uv[i]), (60, 60, 235), cv2.MARKER_CROSS, 22, 2)
        cv2.drawMarker(vis, tuple(int(v) for v in base_px), (255, 120, 60), cv2.MARKER_TILTED_CROSS, 26, 2)
        cv2.putText(vis, "pose%d  TCP %s" % (i + 1, P3[i].astype(int).tolist()), (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imwrite(f.replace("_mask.png", "_proof.jpg"), vis)
    if not sane:
        print("留证图已写 *_proof.jpg, 但外参不落盘")
        return 4
    cal = json.load(open(a.save, encoding="utf-8")) if os.path.exists(a.save) else {}
    e = cal.get(a.key) or {}
    e.update({"kind": "extrinsic", "model": "pinhole", "f": float(K[0, 0]), "cx": float(K[0, 2]),
              "cy": float(K[1, 2]), "T_base_cam": T.tolist(),
              "source": "臂轮廓最远点 %d 位姿 · RMS %.2fpx · 最大 %.2fpx" % (len(P3), rms, mx),
              "rmse_px": round(rms, 3), "n_pts": len(P3)})
    cal[a.key] = e
    json.dump(cal, open(a.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写入 %s [%s]" % (a.save, a.key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
