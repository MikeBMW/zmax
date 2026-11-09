#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 权重同源对照: 同一帧喂两个权重, 不给任何一方占便宜。

老倪口径: 「每条杆杆出同口径对照」。所以不是"v2 跑 20 帧 / v3 跑 20 帧"
(臂在动, 帧本来就不同), 而是每一帧同时喂 v2 和 v3。

用法: python tools/l2_ab_eval.py [--frames 24] [--cam close] [--a v2 --b v3]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def load(tag):
    from ultralytics import YOLO
    p = ROOT / ("models/ar_yolo_%s.pt" % tag)
    return YOLO(str(p)), p


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--cam", default="close")
    ap.add_argument("--a", default="v2")
    ap.add_argument("--b", default="v3")
    a = ap.parse_args()
    import ar_percept as ap_
    ma, pa = load(a.a)
    mb, pb = load(a.b)
    st = {a.a: {"hit": 0, "conf": [], "ms": []}, a.b: {"hit": 0, "conf": [], "ms": []}}
    agree = []
    for i in range(a.frames):
        arr, meta = ap_.fetch(a.cam)
        rgb = arr[:, :, ::-1].copy()
        ra = ma.predict(rgb, conf=0.3, imgsz=640, device="cpu", verbose=False)[0]
        rb = mb.predict(rgb, conf=0.3, imgsz=640, device="cpu", verbose=False)[0]
        ba = ra.boxes[0].xyxy[0].tolist() if len(ra.boxes) else None
        bb = rb.boxes[0].xyxy[0].tolist() if len(rb.boxes) else None
        for tag, r, b in ((a.a, ra, ba), (a.b, rb, bb)):
            st[tag]["ms"].append(float(r.speed["inference"]))
            if b is not None:
                st[tag]["hit"] += 1
                st[tag]["conf"].append(float(r.boxes[0].conf))
        if ba and bb:
            agree.append(iou(ba, bb))
        time.sleep(0.03)
    out = {"frames": a.frames, "cam": a.cam, "weights": {"a": pa.name, "b": pb.name}}
    for tag in (a.a, a.b):
        s = st[tag]
        out[tag] = {"detect_rate": round(s["hit"] / a.frames, 3),
                    "conf_mean": round(sum(s["conf"]) / len(s["conf"]), 3) if s["conf"] else None,
                    "infer_ms_mean": round(sum(s["ms"]) / len(s["ms"]), 1)}
    out["box_iou_mean"] = round(sum(agree) / len(agree), 3) if agree else None
    print(json.dumps(out, ensure_ascii=False, indent=1))
    o = ROOT / "reports"
    o.mkdir(exist_ok=True)
    (o / ("l2_ab_%s_%s.json" % (a.a, a.b))).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")


if __name__ == "__main__":
    main()
