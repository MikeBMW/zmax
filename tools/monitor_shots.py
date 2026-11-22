#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monitor_shots.py — 连续盯拍: 每 3s 抓一帧臂相机, 记录 位姿/亮度/检出数。

只读。用途: 人工调姿势时, 自动找出"看得清且检出到东西"的那一帧。
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import time
import urllib.request

import cv2

OUT = "/home/ubuntu/zmax/zmax_data/percept/mon"
os.makedirs(OUT, exist_ok=True)


def pose():
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/tcp", timeout=2).read())
        return [d["x"] * 1000, d["y"] * 1000, d["z"] * 1000]
    except Exception:
        return None


def main() -> int:
    from ultralytics import YOLO
    m = YOLO("/home/ubuntu/zmax/models/yolo_peg_live.pt")
    t_end = time.time() + float(os.environ.get("ZMAX_MON_SEC", "180"))
    best = (0, None)
    while time.time() < t_end:
        p = pose()
        f = os.path.join(OUT, "m_%s.jpg" % time.strftime("%H%M%S"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i",
                        "http://127.0.0.1:8791/arm.mjpg", "-frames:v", "1", f], check=False)
        if not os.path.exists(f):
            time.sleep(3)
            continue
        g = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2GRAY)
        r = m.predict(f, conf=0.12, device="cpu", verbose=False)[0]
        br = float(g.mean())
        print("%s 位姿 %s 亮度%.0f 检出%d" % (
            time.strftime("%H:%M:%S"),
            "%.0f,%.0f,%.0f" % tuple(p) if p else "?",
            br, len(r.boxes)), flush=True)
        score = br + 25 * len(r.boxes)
        if score > best[0]:
            best = (score, f)
        time.sleep(3)
    print("BEST %s" % best[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
