#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面 ROI 在三档曝光下是否有光模块条: 逐档量 ROI 内亮度/结构"""
import glob
import os

import cv2
import numpy as np

d = sorted(glob.glob("/home/ubuntu/zmax/reports/aoi_surface_expo_*"))[-1]
print("档位目录: %s" % d)
x0, y0, x1, y1 = 330, 960, 1815, 1440
for f in sorted(glob.glob(os.path.join(d, "*.png"))):
    img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
    if img is None or img.shape[1] != 2448:
        continue
    roi = img[y0:y1, x0:x1]
    rowfrac = (roi > 200).mean(axis=1)
    runs = []
    inrun = False
    for i, v in enumerate(rowfrac):
        if v > 0.15 and not inrun:
            s = i; inrun = True
        elif v <= 0.15 and inrun:
            runs.append((y0 + s, y0 + i, i - s)); inrun = False
    if inrun:
        runs.append((y0 + s, y0 + len(rowfrac), len(rowfrac) - s))
    # 全图最亮条
    fr = (img > 200).mean(axis=1)
    bruns = [(y, v) for y, v in enumerate(fr) if v > 0.30]
    bspan = (bruns[0][0], bruns[-1][0]) if bruns else None
    print("\n%-22s 全图 mean=%.1f p50=%.0f p90=%.0f" % (os.path.basename(f), img.mean(),
                                                        np.percentile(img, 50), np.percentile(img, 90)))
    print("   ROI mean=%.1f p90=%.0f >200占比=%.4f  亮行带(>15%%): %s"
          % (roi.mean(), np.percentile(roi, 90), (roi > 200).mean(), runs[:4] or "无"))
    print("   全图 >200 且占比>30%% 的行区间: %s" % (bspan,))
