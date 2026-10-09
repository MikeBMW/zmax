#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面帧场景分析: ROI 内/外找光模块条 + 存证切片"""
import glob
import os

import cv2
import numpy as np

p = sorted(glob.glob("/home/ubuntu/zmax/reports/aoi_surface_probe_*/origin.png"))[-1]
img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
H, W = img.shape
print("帧: %s  %dx%d  mean=%.1f" % (os.path.basename(p), W, H, img.mean()))

blur = cv2.GaussianBlur(img, (31, 31), 0)
ret, bi = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
print("Otsu 阈值=%.0f  前景占比=%.3f  前景均值=%.1f 背景均值=%.1f"
      % (ret, (bi > 0).mean(), img[bi > 0].mean(), img[bi == 0].mean()))

n, lab, stats, cent = cv2.connectedComponentsWithStats((bi > 0).astype(np.uint8), 8)
cand = sorted([(int(stats[i][4]), i) for i in range(1, n)], reverse=True)
print("最大前景块 前5:")
for a, i in cand[:5]:
    x, y, w, h, aa = stats[i]
    reg = img[lab == i]
    print("  x[%d..%d] y[%d..%d] %dx%d area=%d 均值=%.1f 长宽比=%.2f"
          % (x, x + w, y, y + h, w, h, aa, reg.mean(), max(w, h) / max(1, min(w, h))))

print("行剖面(每128行均值): " + " ".join("%.0f" % img[y:y + 128].mean() for y in range(0, H, 128)))
print("列剖面(每256列均值): " + " ".join("%.0f" % img[:, x:x + 256].mean() for x in range(0, 2048, 256)))

# 程序自己的 ROI [330,960,1815,1440]
x0, y0, x1, y1 = 330, 960, 1815, 1440
roi = img[y0:y1, x0:x1]
print("\n程序 ROI [%d,%d,%d,%d]: %dx%d mean=%.1f p50=%.0f p90=%.0f sat=%.3f bright(>200)=%.4f"
      % (x0, y0, x1, y1, roi.shape[1], roi.shape[0], roi.mean(), np.percentile(roi, 50),
         np.percentile(roi, 90), (roi >= 250).mean(), (roi > 200).mean()))
# ROI 内找亮条 (行方向: 每行亮像素占比, 找连续亮行带)
rowfrac = (roi > 200).mean(axis=1)
runs = []
inrun = False
for i, v in enumerate(rowfrac):
    if v > 0.15 and not inrun:
        s = i; inrun = True
    elif v <= 0.15 and inrun:
        runs.append((s, i, i - s)); inrun = False
if inrun:
    runs.append((s, len(rowfrac), len(rowfrac) - s))
print("ROI 内亮行带(>15%% 亮像素): %s" % ([(y0 + a, y0 + b, c) for a, b, c in runs][:6] or "无"))

out = os.path.dirname(p)
cv2.imwrite(os.path.join(out, "roi_crop.png"), roi)
for k, (ya, yb) in enumerate(((960, 1440), (1440, 1914), (1400, 2048))):
    cv2.imwrite(os.path.join(out, "band_%d_%d_%d.png" % (k, ya, yb)), img[ya:yb])
print("切片存证: %s (roi_crop.png + band_*.png)" % out)
