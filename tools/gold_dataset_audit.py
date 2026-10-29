#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金手指图集体检：用现役 yolo_ar_peg.pt 在 gold_collect 原图上推理，统计检出率。

决定「能否自动打标训练」还是「必须人工标注」。
"""
import glob
import json
import os
import sys

sys.path.insert(0, "src")
from ultralytics import YOLO  # noqa: E402

IMGS = sorted(glob.glob("zmax_data/gold_collect_20261020/origin/*.png"))
W = "models/yolo_ar_peg.pt"

print(f"图 {len(IMGS)} 张 · 权重 {W}")
m = YOLO(W)
print("类别:", m.names)

hit, miss, confs, boxes = 0, 0, [], []
for i, p in enumerate(IMGS):
    r = m.predict(p, imgsz=640, conf=0.25, verbose=False)[0]
    if len(r.boxes):
        hit += 1
        c = float(r.boxes.conf.max())
        confs.append(c)
        b = r.boxes.xyxy[0].cpu().numpy().tolist()
        boxes.append({"file": os.path.basename(p), "conf": round(c, 4),
                      "xyxy": [round(x, 1) for x in b],
                      "cls": int(r.boxes.cls[0])})
    else:
        miss += 1

n = len(IMGS)
print(f"\n检出 {hit}/{n} = {100.0 * hit / max(n, 1):.1f}%   漏检 {miss}")
if confs:
    confs.sort()
    print(f"置信度 中位 {confs[len(confs) // 2]:.3f} 最低 {confs[0]:.3f} 最高 {confs[-1]:.3f}")
    hi = sum(1 for c in confs if c >= 0.5)
    print(f"高置信(>=0.5) {hi}/{hit} = {100.0 * hi / hit:.1f}%")

os.makedirs("zmax_data/aoi_v4/gold_auto", exist_ok=True)
json.dump(boxes, open("zmax_data/aoi_v4/gold_auto/detections.json", "w"),
          ensure_ascii=False, indent=1)
print("\n→ zmax_data/aoi_v4/gold_auto/detections.json")
