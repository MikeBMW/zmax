#!/usr/bin/env python3
"""torch 参考结果 (本机 GPU): 与端侧 IR 结果同口径对比, 证明 IR 没跑偏。
用法: python edge_yolo_ref.py <权重> <图片...> --out ref.json
"""
import argparse, json, os
import torch
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("weights"); ap.add_argument("images", nargs="+")
ap.add_argument("--out", default="torch_ref.json"); ap.add_argument("--conf", type=float, default=0.25)
a = ap.parse_args()
files = []
for p in a.images:
    if os.path.isdir(p):
        files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith((".jpg", ".png"))]
    else:
        files.append(p)
files = files[:8]
m = YOLO(a.weights)
rows = []
for f in files:
    r = m.predict(f, imgsz=640, conf=a.conf, verbose=False)[0]
    dets = []
    for b in r.boxes:
        dets.append({"cls": int(b.cls[0]), "conf": round(float(b.conf[0]), 4),
                     "xyxy": [round(float(v), 1) for v in b.xyxy[0].tolist()]})
    dets.sort(key=lambda d: -d["conf"])
    rows.append({"file": os.path.basename(f), "dets": dets})
    print("%-28s %d 个框 %s" % (os.path.basename(f), len(dets), [(d["cls"], d["conf"]) for d in dets[:3]]), flush=True)
json.dump({"rows": rows}, open(a.out, "w"), ensure_ascii=False, indent=2)
print("写出", a.out)
