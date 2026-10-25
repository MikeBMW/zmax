#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中央相机单帧: 有没有标定板? 若有, 板在画面里的像素尺寸/位置/姿态线索。

只做**能落数的**判断, 不做猜测:
  · 棋盘格 (findChessboardCornersSB + 经典) 多尺寸遍历
  · 圆点阵列 (findCirclesGrid, 对称/非对称)
  · ArUco / ChArUco 字典遍历
  · 兜底: 高亮四边形状 —— 只作为"疑似板"线索, 不当作检出
用法: python probe_central_board.py <jpg> [--json out.json]
"""
from __future__ import annotations

import json
import sys

import cv2
import numpy as np

CHESS = [(9, 6), (7, 6), (8, 6), (11, 8), (6, 9), (5, 4), (7, 5), (9, 7), (12, 9),
         (8, 5), (6, 4), (10, 7), (4, 3), (5, 3), (6, 5), (10, 8), (13, 9), (4, 11)]
CIRCLES = [(4, 11), (7, 7), (5, 4), (6, 6), (4, 4), (3, 4), (8, 5), (5, 5), (9, 6)]
ARUCO_DICTS = ["DICT_4X4_50", "DICT_4X4_100", "DICT_5X5_50", "DICT_6X6_250", "DICT_7X7_100"]


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/central_now.jpg"
    img = cv2.imread(path)
    if img is None:
        print("读不到图: %s" % path)
        return 1
    H, W = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    print("图: %s · %dx%d · 亮度 %.1f · 拉普拉斯(清晰度) %.1f"
          % (path, W, H, gray.mean(), cv2.Laplacian(gray, cv2.CV_64F).var()))

    out = {"image": path, "size": [W, H], "brightness": float(gray.mean()),
           "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var()), "detections": []}

    # ① 棋盘格 —— SB 检测器 (抗噪好) + 经典
    for (cols, rows) in CHESS:
        try:
            ok, corners = cv2.findChessboardCornersSB(gray, (cols, rows), flags=cv2.CALIB_CB_EXHAUSTIVE)
        except Exception:                                                  # noqa: BLE001
            ok, corners = False, None
        if ok and corners is not None:
            c = corners.reshape(-1, 2)
            w_px = float(c[:, 0].max() - c[:, 0].min())
            h_px = float(c[:, 1].max() - c[:, 1].min())
            out["detections"].append({"kind": "chessboard_SB", "pattern": [cols, rows],
                                      "n_corners": int(len(c)), "w_px": w_px, "h_px": h_px,
                                      "center_px": [float(c[:, 0].mean()), float(c[:, 1].mean())],
                                      "area_frac": float(w_px * h_px / (W * H))})
            print("✅ 棋盘格(SB) %dx%d · 角点 %d · 板 %.0f×%.0f px · 占画面 %.1f%%"
                  % (cols, rows, len(c), w_px, h_px, 100 * w_px * h_px / (W * H)))
        else:
            ok2, c2 = cv2.findChessboardCorners(gray, (cols, rows),
                                                flags=cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE)
            if ok2 and c2 is not None:
                c = c2.reshape(-1, 2)
                w_px = float(c[:, 0].max() - c[:, 0].min())
                h_px = float(c[:, 1].max() - c[:, 1].min())
                out["detections"].append({"kind": "chessboard", "pattern": [cols, rows],
                                          "n_corners": int(len(c)), "w_px": w_px, "h_px": h_px,
                                          "area_frac": float(w_px * h_px / (W * H))})
                print("✅ 棋盘格(经典) %dx%d · 角点 %d · 板 %.0f×%.0f px" % (cols, rows, len(c), w_px, h_px))

    # ② 圆点阵列
    for (cols, rows) in CIRCLES:
        for sym in (False, True):
            flags = cv2.CALIB_CB_SYMMETRIC_GRID if sym else cv2.CALIB_CB_ASYMMETRIC_GRID
            ok, c = cv2.findCirclesGrid(gray, (cols, rows), flags=flags)
            if ok and c is not None:
                cc = c.reshape(-1, 2)
                w_px = float(cc[:, 0].max() - cc[:, 0].min())
                h_px = float(cc[:, 1].max() - cc[:, 1].min())
                out["detections"].append({"kind": "circles_sym" if sym else "circles_asym",
                                          "pattern": [cols, rows], "n_pts": int(len(cc)),
                                          "w_px": w_px, "h_px": h_px,
                                          "area_frac": float(w_px * h_px / (W * H))})
                print("✅ 圆点阵列 %s %dx%d · 点 %d · %.0f×%.0f px"
                      % ("对称" if sym else "非对称", cols, rows, len(cc), w_px, h_px))

    # ③ ArUco / ChArUco
    for dn in ARUCO_DICTS:
        try:
            dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dn))
            det = cv2.aruco.ArucoDetector(dic, cv2.aruco.DetectorParameters())
            corners, ids, _ = det.detectMarkers(gray)
            if ids is not None and len(ids) > 0:
                out["detections"].append({"kind": "aruco", "dict": dn,
                                          "ids": [int(i) for i in ids.ravel()],
                                          "n": int(len(ids))})
                print("✅ ArUco %s · %d 个标记 · ids=%s" % (dn, len(ids), ids.ravel().tolist()[:8]))
        except Exception:                                                  # noqa: BLE001
            pass

    # ④ 兜底: 高亮(近白)区域 —— 只是"疑似板面"线索
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    Lc = lab[:, :, 0]
    bright = (Lc > 200).astype(np.uint8) * 255
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:3]:
        a = cv2.contourArea(c)
        if a < 0.005 * W * H:
            continue
        peri = cv2.arcLength(c, True)
        ap = cv2.approxPolyDP(c, 0.02 * peri, True)
        x, y, w, h = cv2.boundingRect(c)
        cands.append({"area_px": float(a), "area_frac": float(a / (W * H)),
                      "bbox": [int(x), int(y), int(w), int(h)], "poly_pts": int(len(ap)),
                      "fill_ratio": float(a / max(1, w * h))})
    out["bright_rect_candidates"] = cands
    for c in cands:
        print("· 疑似亮面(不当作检出): bbox=%s 占 %.1f%% 四边形点数=%d 填充率=%.2f"
              % (c["bbox"], 100 * c["area_frac"], c["poly_pts"], c["fill_ratio"]))

    out["n_detections"] = len(out["detections"])
    print("\n结论: 标定板检出 %d 处" % out["n_detections"] if out["n_detections"]
          else "\n结论: 这一帧没有可识别的标定板图案 (棋盘/圆点/ArUco 都没检出)")
    if len(sys.argv) > 3 and sys.argv[2] == "--json":
        json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
