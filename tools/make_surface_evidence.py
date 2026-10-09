#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把表面检测实测证据拼成一张给老倪看的图 (原图+ROI框+亮物框 / ROI裁片)"""
import glob
import os

import cv2
import numpy as np

d = sorted(glob.glob("/home/ubuntu/zmax/reports/aoi_surface_probe_*/origin.png"))[-1]
d = os.path.dirname(d)
img = cv2.imread(os.path.join(d, "origin.png"), cv2.IMREAD_GRAYSCALE)
vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
# 程序 ROI (330,960)-(1815,1440) — 绿框
cv2.rectangle(vis, (330, 960), (1815, 1440), (0, 255, 0), 6)
cv2.putText(vis, "program ROI  (inside: mean=25.9  bright=0.0000)", (340, 940),
            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 255, 0), 4)
# 实测亮物 (634,1491)-(1648,1852) — 红框
cv2.rectangle(vis, (634, 1491), (1648, 1852), (0, 0, 255), 6)
cv2.putText(vis, "bright object  mean=239 (outside ROI, 51~412px below)", (640, 1470),
            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 255), 4)
small = cv2.resize(vis, (1224, 1024), interpolation=cv2.INTER_AREA)

roi = img[960:1440, 330:1815]
roi_big = cv2.resize(roi, (1224, int(480 * 1224 / 1485)), interpolation=cv2.INTER_AREA)
roi_vis = cv2.cvtColor(roi_big, cv2.COLOR_GRAY2BGR)
cv2.putText(roi_vis, "ROI crop as-is (dark: p50=25, nothing > 200)", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

h = small.shape[0] + roi_vis.shape[0] + 40
canvas = np.zeros((h, 1224, 3), np.uint8)
canvas[:small.shape[0]] = small
canvas[small.shape[0] + 20:small.shape[0] + 20 + roi_vis.shape[0]] = roi_vis
out = os.path.join(d, "surface_evidence.png")
cv2.imwrite(out, canvas)
print(out)
