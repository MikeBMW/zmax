#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_3d_pixels.py — 自己**量像素**判 3D 场景缺陷 (不靠肉眼/不靠猜)

口径: 颜色都是代码里固定不变的常量, 所以能反查:
· 带孔盒 红 (0.95,0.22,0.14)      → RGB(242,56,36)
· 孔口 深 (0.04,0.03,0.02)        → RGB(10,8,5)
· 光模块 金 (0.95,0.72,0.10)      → RGB(242,184,26)  (臂上)
· 料盘/盘 光模块 金 (0.92,0.74,0.24) → RGB(235,189,61)
· 盘壁 黑 (0.10,0.10,0.11)        → RGB(26,26,28)
· 台面 乳白/绿
若某件的窗口颜色是"淡金/发白" ⇒ 说明它被半透明层叠加或本身 alpha<1 (纯金会被冲淡)。
"""
import sys
import cv2
import numpy as np


def load(p):
    im = cv2.imread(p)
    if im is None:
        print("   ✗ 读不到", p)
        sys.exit(2)
    return im


def mask_near(im, rgb, tol=22):
    b, g, r = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
    return (abs(r - rgb[0]) <= tol) & (abs(g - rgb[1]) <= tol) & (abs(b - rgb[2]) <= tol)


def bbox(m):
    ys, xs = np.where(m)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()), int(m.sum())


def report(name, path):
    im = load(path)
    H, W = im.shape[:2]
    print("\n══ %s (%dx%d) ══" % (name, W, H))
    for lab, rgb in (("带孔盒红", (242, 56, 36)), ("孔口深", (10, 8, 5)),
                     ("光模块金(纯)", (242, 184, 26)), ("盘件金(纯)", (235, 189, 61)),
                     ("盘壁黑", (26, 26, 28))):
        m = mask_near(im, rgb)
        bb = bbox(m)
        if bb:
            print("  %-12s 像素 %6d · bbox x[%d..%d] y[%d..%d]" % (lab, bb[4], bb[0], bb[1], bb[2], bb[3]))
        else:
            print("  %-12s 无" % lab)
    # 金被"冲淡"的检验: 亮且偏黄但饱和度低 = 叠了半透明层
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    gold_sat = (h >= 15) & (h <= 35) & (s >= 120) & (v >= 120)          # 饱和金 = 实心件
    pale_gold = (h >= 15) & (h <= 35) & (s >= 30) & (s < 120) & (v >= 170)  # 淡金 = 被冲淡/半透明
    print("  金色像素: 饱和(实心) %6d · 淡(疑似半透明) %6d · 淡/饱和 = %.2f"
          % (int(gold_sat.sum()), int(pale_gold.sum()),
             pale_gold.sum() / max(1, gold_sat.sum())))
    return im


if __name__ == "__main__":
    a = report("插拔场景", "/tmp/qa_fw.png")
    b = report("摆盘场景", "/tmp/qa_tray.png")
    # 插拔: 盒 vs 孔口 的纵向/横向像素差
    print("\n══ 插拔: 盒 ↔ 孔口 像素关系 ══")
    mb, mm = mask_near(a, (242, 56, 36)), mask_near(a, (10, 8, 5))
    bb, bm = bbox(mb), bbox(mm)
    if bb and bm:
        cx_b, cx_m = (bb[0] + bb[1]) / 2, (bm[0] + bm[1]) / 2
        cy_b, cy_m = (bb[2] + bb[3]) / 2, (bm[2] + bm[3]) / 2
        print("  盒中心(px) (%.0f, %.0f) · 孔口中心(px) (%.0f, %.0f)" % (cx_b, cy_b, cx_m, cy_m))
        print("  → 水平差 %.0fpx · 垂直差 %.0fpx (盒bbox高 %dpx = 190mm ⇒ 1px≈%.2fmm)"
              % (cx_m - cx_b, cy_m - cy_b, bb[3] - bb[2], 190.0 / max(1, bb[3] - bb[2])))
        print("  孔口是否落在盒 bbox 外: %s" % ("是 ⇒ 视觉错开" if not (bb[0] <= cx_m <= bb[1] and bb[2] <= cy_m <= bb[3]) else "否 (在盒内)"))
    # 摆盘: 盘内 光模块 是否伸出盘外
    print("\n══ 摆盘: 盘件金 ↔ 盘壁黑 像素关系 ══")
    mg, mk = mask_near(b, (235, 189, 61)), mask_near(b, (26, 26, 28))
    bg, bk = bbox(mg), bbox(mk)
    if bg and bk:
        print("  盘件金 bbox x[%d..%d] y[%d..%d] · 盘壁黑 bbox x[%d..%d] y[%d..%d]"
              % (bg[0], bg[1], bg[2], bg[3], bk[0], bk[1], bk[2], bk[3]))
        print("  → 金件水平跨度 %dpx vs 黑盘跨度 %dpx ⇒ 比值 %.2f (>1 = 伸出盘外)"
              % (bg[1] - bg[0], bk[1] - bk[0], (bg[1] - bg[0]) / max(1, bk[1] - bk[0])))
