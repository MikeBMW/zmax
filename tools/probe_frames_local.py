#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_frames_local.py — 不依赖产线网卡的「本机真帧」视觉可用性核查。

背景 (2026-10-15 06:1x): AOI .23.23 / Orin .66 全不可达 (产线网卡无地址, 100% 丢包) ⇒
10083 的 kind=origin 真帧拿不到, 也无法抬曝光。此脚本只用**本机**可拿到的帧 (8791 local/local2/depth ·
8797 AR 底图 arm), 逐帧核 均值/std/max/非黑像素占比, 给后续 YOLO/VLM 视觉分支选帧。
只读取帧, 不写任何参数、不发动作。
"""
from __future__ import annotations

import io
import json
import urllib.request

import numpy as np

try:
    import cv2
except Exception:                                                             # noqa: BLE001
    cv2 = None

SRCS = [
    ("8791/local", "http://127.0.0.1:8791/snapshot/local.jpg"),
    ("8791/local2", "http://127.0.0.1:8791/snapshot/local2.jpg"),
    ("8791/depth", "http://127.0.0.1:8791/snapshot/depth.jpg"),
    ("8797/arm", "http://127.0.0.1:8797/snap/arm.jpg"),
]


def main() -> int:
    out = []
    for name, url in SRCS:
        rec = {"name": name, "url": url}
        try:
            b = urllib.request.urlopen(url, timeout=15).read()
            rec["bytes"] = len(b)
            if cv2 is None:
                rec["err"] = "no cv2"
            else:
                g = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE)
                if g is None:
                    rec["err"] = "decode fail"
                else:
                    rec.update({"w": int(g.shape[1]), "h": int(g.shape[0]),
                                "mean": round(float(g.mean()), 3), "std": round(float(g.std()), 3),
                                "max": int(g.max()), "nonblack_pct": round(float((g > 8).mean()) * 100, 2)})
        except Exception as e:                                                # noqa: BLE001
            rec["err"] = "%s: %s" % (type(e).__name__, str(e)[:70])
        out.append(rec)
        print("  %-14s %s" % (name, json.dumps(rec, ensure_ascii=False)))
    ok = [r for r in out if r.get("nonblack_pct", 0) > 5]
    print("\n可用的有内容帧: %d/%d ⇒ %s" % (len(ok), len(out), ", ".join(r["name"] for r in ok) or "无"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
