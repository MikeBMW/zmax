#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_and_deskew.py —— 工件刚体: 动态搜索 + 同帧摆正(纯旋转, 零拉伸) + 自检。

一帧到底:
  ① 搜索: CLAHE + Otsu + 形态学 → 逐轮廓评分(面积占比 × 矩形度) → minAreaRect 四角
  ② 摆正: getRotationMatrix2D(scale=1.0) + warpAffine + getRectSubPix(按检出真实尺寸)
  ③ 自检: 输出尺寸==检出尺寸 · 同像素亮度差 · 饱和度/暗部
  ④ 交付: 原图+搜索框(绿框+四角标记) 与 摆正图 分别落盘(不拼图)

用法:
  python find_and_deskew.py --image frame.png --out-dir /tmp/x
  python find_and_deskew.py --url 'http://host:10083/picture?kind=origin&grab=1' --out-dir /tmp/x
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np


def fetch(url: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-probe"})   # 探针必须带 UA
    return urllib.request.urlopen(req, timeout=30).read()


def find_rect(img: np.ndarray):
    """返回 (rect, box4x2, dbg)。位置无关: 不含任何固定坐标。"""
    h, w = img.shape[:2]
    g = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    g = cv2.GaussianBlur(g, (5, 5), 0)
    t, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = (g > t).astype(np.uint8) * 255
    if m.mean() / 255.0 > 0.6:                       # 前景过大 ⇒ Otsu 失效, 改用分位兜底
        m = (g > float(np.percentile(g, 80))).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((25, 25), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cs:
        a = cv2.contourArea(c)
        frac = a / float(h * w)
        if frac < 0.005 or frac > 0.75:
            continue
        r = cv2.minAreaRect(c)
        fill = a / max(1.0, r[1][0] * r[1][1])       # 矩形度
        score = frac * fill
        if best is None or score > best[0]:
            best = (score, r, cv2.boxPoints(r).astype(np.float32), frac, fill)
    if best is None:
        return None, None, {"n_contours": len(cs)}
    dbg = {"score": round(float(best[0]), 5), "area_frac": round(float(best[3]), 4),
           "fill": round(float(best[4]), 4), "n_contours": len(cs)}
    return best[1], best[2], dbg


def deskew(img: np.ndarray, rect):
    """纯旋转(scale=1.0) + 按检出真实像素尺寸裁剪 ⇒ 零拉伸。"""
    (cx, cy), (rw, rh), ang = rect
    W, H = max(rw, rh), min(rw, rh)
    if rw < rh:
        ang = ang + 90.0
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_CUBIC)
    crop = cv2.getRectSubPix(rot, (int(round(W)), int(round(H))), (cx, cy))
    return crop, float(W), float(H), float(ang)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--url")
    ap.add_argument("--out-dir", default="/tmp/crop_rect")
    a = ap.parse_args()
    if not a.image and not a.url:
        print("need --image or --url", file=sys.stderr)
        return 2
    if a.url:
        img = cv2.imdecode(np.frombuffer(fetch(a.url), np.uint8), cv2.IMREAD_COLOR)
        src = a.url
    else:
        img = cv2.imread(a.image)
        src = a.image
    if img is None:
        print("cannot read frame", file=sys.stderr)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)

    rect, box, dbg = find_rect(img)
    if rect is None:
        print("\u274c 未搜到矩形刚体 (dbg=%s)" % dbg)
        return 1
    (cx, cy), (rw, rh), ang = rect
    W0, H0 = max(rw, rh), min(rw, rh)

    # ① 原图 + 搜索框(交付主图)
    over = img.copy()
    cv2.polylines(over, [box.astype(np.int32).reshape(-1, 1, 2)], True, (0, 255, 0), 14)
    for i, p in enumerate(box.astype(int)):
        cv2.circle(over, tuple(p), 26, (0, 0, 255), -1)
        cv2.putText(over, "ABCD"[i], (p[0] + 30, p[1] - 22), cv2.FONT_HERSHEY_SIMPLEX,
                    4.0, (0, 0, 255), 10)
    cv2.putText(over, "crop area: %.0fx%.0f  tilt %.2fdeg  area %.1f%%  fill %.2f"
                % (W0, H0, ang, 100 * dbg["area_frac"], dbg["fill"]),
                (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 3.2, (0, 255, 0), 9)   # ASCII only
    p_over = os.path.join(a.out_dir, "overlay_box.png")
    cv2.imwrite(p_over, over)

    # ② 同帧摆正
    crop, W, H, ang2 = deskew(img, rect)
    p_crop = os.path.join(a.out_dir, "deskew_crop.png")
    cv2.imwrite(p_crop, crop)

    # ③ 自检
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(mask, [box.astype(np.int32)], 255)
    gi = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gc = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    o_mean, o_med = float(gi[mask > 0].mean()), float(np.median(gi[mask > 0]))
    c_mean, c_med = float(gc.mean()), float(np.median(gc))
    n_crop = gc.size
    print("搜索: 面积占比 %.1f%%  矩形度 %.2f  得分 %.4f  倾角 %.2f°  检出 %.0fx%.0f"
          % (100 * dbg["area_frac"], dbg["fill"], dbg["score"], ang, W0, H0))
    print("摆正: %.0fx%.0f  (旋转 %.2f° · 缩放 1.0)  ⇒ 尺寸一致=%s"
          % (crop.shape[1], crop.shape[0], ang2, (crop.shape[1], crop.shape[0]) == (int(W0), int(H0))))
    print("亮度(同帧同像素): 原图矩形内 %.1f/中位%.0f (n=%d)  vs  摆正图 %.1f/中位%.0f  ⇒ 均值差 %.2f"
          % (o_mean, o_med, int((mask > 0).sum()), c_mean, c_med, c_mean - o_mean))
    print("摆正图: 饱和>=250 %.2f%%  暗部<20 %.2f%%"
          % (100 * (gc >= 250).mean(), 100 * (gc < 20).mean()))
    print("交付: %s (原图+框) · %s (摆正, 独立文件)" % (p_over, p_crop))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
