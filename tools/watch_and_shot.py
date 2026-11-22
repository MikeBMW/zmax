#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_and_shot.py — 等机械臂停稳(人工点动停手)后, 抓臂相机一帧并做检出。

只读: 不向控制器下发任何指令。
判停: 位姿在 2.0s 内变化 < 1.5mm。
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import time
import urllib.request

OUT = "/home/ubuntu/zmax/zmax_data/percept"


def pose():
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/tcp", timeout=2).read())
        return [d["x"] * 1000, d["y"] * 1000, d["z"] * 1000]
    except Exception:
        return None


def stable(win=2.0, tol=1.5):
    p0 = pose()
    if p0 is None:
        return None
    time.sleep(win)
    p1 = pose()
    if p1 is None:
        return None
    if max(abs(a - b) for a, b in zip(p0, p1)) < tol:
        return p1
    return None


def shot(tag="watch"):
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, "%s_%s.jpg" % (tag, time.strftime("%H%M%S")))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i",
                    "http://127.0.0.1:8791/arm.mjpg", "-frames:v", "1", f], check=False)
    return f


def main() -> int:
    t0 = time.time()
    while time.time() - t0 < 600:
        p = stable()
        if p:
            f = shot()
            print("停稳 %.1f,%.1f,%.1f → %s" % (*p, f), flush=True)
            print("SHOT %s" % f)
            return 0
        time.sleep(0.5)
    print("✗ 600s 内没等到停稳")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
