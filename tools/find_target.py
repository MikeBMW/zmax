#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_target.py —— 在任意图像里找标定靶标（ArUco / 圆点阵列 / 棋盘格），一次全试

为什么要有: 现场板型不确定(老倪 2026-10-18 放的板子, 腕相机看到的是黑底白点阵列,
固定相机看到的是 ArUco id0)。先搞清楚"两台相机都能看到什么", 再决定标定链。

用法:
  ./gui-venv311/bin/python tools/find_target.py img1.jpg img2.jpg [--save]
输出: 每张图命中的靶标类型/尺寸/像素坐标
"""
from __future__ import annotations

import sys

import cv2
import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax/tools")
import calib_fixed_cam as CF          # noqa: E402

GRIDS = [(3, 3), (4, 3), (4, 4), (5, 4), (4, 5), (5, 5), (6, 4), (6, 5), (6, 6), (7, 5), (7, 6), (7, 7), (8, 6)]


def circle_grid(gray, upscale=2.0):
    """圆点阵列: 试 对称/非对称 × 正/反极性 × 多种阵列尺寸; 报 (模式, 行列, 点数, rmse-ish)。"""
    out = []
    big = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    variants = {"gray": big, "invert": cv2.bitwise_not(big),
                "clahe_inv": cv2.bitwise_not(cv2.createCLAHE(2.0, (8, 8)).apply(big))}
    for vn, v in variants.items():
        for (c, r) in GRIDS:
            for flags, mn in ((cv2.CALIB_CB_SYMMETRIC_GRID, "sym"), (cv2.CALIB_CB_ASYMMETRIC_GRID, "asym")):
                ok, pts = cv2.findCirclesGrid(v, (c, r), flags=flags)
                if ok:
                    p = pts.reshape(-1, 2) / upscale
                    d = np.linalg.norm(np.diff(p[:min(6, len(p))], axis=0), axis=1)
                    out.append({"kind": "circles", "mode": mn, "grid": (c, r), "n": int(len(p)),
                                "variant": vn, "pts": p, "spacing_px": float(np.median(d))})
    return out


def chessboard(gray, upscale=1.5):
    out = []
    big = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    for (c, r) in [(9, 6), (8, 6), (11, 8), (7, 6), (10, 7), (6, 5), (9, 7), (12, 9)]:
        ok, pts = cv2.findChessboardCornersSB(big, (c, r), flags=cv2.CALIB_CB_EXHAUSTIVE + cv2.CALIB_CB_ACCURACY)
        if ok:
            out.append({"kind": "chess", "grid": (c, r), "n": int(len(pts)),
                        "pts": pts.reshape(-1, 2) / upscale})
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = "--save" in sys.argv
    for path in args:
        img = cv2.imread(path)
        if img is None:
            print("%s: 读不到" % path)
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        print("=== %s  %s  亮度 %.0f" % (path.split("/")[-1], img.shape, g.mean()))
        mk = CF.find_markers(img)
        print("  ArUco: %s" % ({k: v[0] for k, v in mk.items()} or "无"))
        res = circle_grid(g) + chessboard(g)
        seen = set()
        for r in res:
            key = (r["kind"], tuple(r["grid"]), r.get("mode"))
            if key in seen:
                continue
            seen.add(key)
            p = r["pts"]
            print("  %-7s %s%s n=%d  x %.0f~%.0f  y %.0f~%.0f%s" % (
                r["kind"], r["grid"], (" " + r["mode"]) if r.get("mode") else "", r["n"],
                p[:, 0].min(), p[:, 0].max(), p[:, 1].min(), p[:, 1].max(),
                ("  variant=%s 间距%.1fpx" % (r["variant"], r["spacing_px"])) if r.get("spacing_px") else ""))
        if not res:
            print("  圆点/棋盘: 无")
        if save and res:
            big = img.copy()
            r = res[0]
            for q in r["pts"]:
                cv2.circle(big, (int(q[0]), int(q[1])), 4, (0, 220, 120), 1)
            out = path.rsplit(".", 1)[0] + "_found.png"
            cv2.imwrite(out, big)
            print("  标注图:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
