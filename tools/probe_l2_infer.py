#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 检测器在线推理实测: 真机画面 → 在役权重 → 框 + 耗时 (CPU, 不占训练 GPU)

⚠️ ultralytics 吃 BGR (cv2 原生), 若上游给的是 RGB 会整体掉分 —— 本探针两种都跑, 报差异。
用法: gui-venv311/bin/python tools/probe_l2_infer.py [图片URL或路径...]
"""
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

W = "zmax_data/models/yolo_peg_live.pt"
if not os.path.exists(os.path.join(ROOT, W)):
    alt = [p for p in ("models/yolo_peg_live.pt", "zmax_data/models/yolo_peg.pt") if os.path.exists(os.path.join(ROOT, p))]
    W = alt[0] if alt else W
print("在役权重: %s → %s" % (W, "存在 ✅" if os.path.exists(os.path.join(ROOT, W)) else "缺失 ❌"))

srcs = sys.argv[1:] or ["http://192.168.23.66:8792/frame.jpg"]


def load(src):
    if src.startswith("http"):
        import urllib.request
        buf = np.frombuffer(urllib.request.urlopen(src, timeout=8).read(), np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)      # BGR
    return cv2.imread(src)


from ultralytics import YOLO  # noqa: E402

t0 = time.time()
m = YOLO(os.path.join(ROOT, W))
print("加载 %s 用 %.1fs · 类别 %s" % (os.path.basename(W), time.time() - t0, getattr(m, "names", None)))

for s in srcs:
    try:
        bgr = load(s)
    except Exception as e:                                                  # noqa: BLE001
        print("  ❌ 取图失败 %s: %s" % (s, e))
        continue
    if bgr is None:
        print("  ❌ 解不出图: %s" % s)
        continue
    for tag, im in (("BGR(cv2原生)", bgr), ("RGB(误用)", bgr[:, :, ::-1].copy())):
        t = time.time()
        r = m.predict(im, verbose=False, conf=0.25)[0]
        dt = (time.time() - t) * 1000
        boxes = r.boxes
        names = [m.names[int(c)] for c in boxes.cls] if boxes is not None else []
        confs = [round(float(c), 3) for c in boxes.conf] if boxes is not None else []
        print("  %-13s %s  %dx%d  检出 %d 个  %.0f ms  %s"
              % (tag, os.path.basename(s)[:34], bgr.shape[1], bgr.shape[0], len(names), dt,
                 list(zip(names, confs))[:4]))
