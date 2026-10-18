#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pose_probe.py — 10Hz 采样 8793 的 TCP 真值, 用来判"到底停没停"

输出 jsonl: {"t": 相对时间, "x","y","z"}  (米)
用法: ./gui-venv311/bin/python tools/pose_probe.py --sec 60 --out /tmp/pose_probe.jsonl
"""
import argparse
import json
import time
import urllib.request


def pose():
    with urllib.request.urlopen("http://127.0.0.1:8793/pose", timeout=2) as r:
        d = json.loads(r.read().decode())
        x, y, z = (float(v) for v in d["xyz"])
        return x, y, z


ap = argparse.ArgumentParser()
ap.add_argument("--sec", type=float, default=60.0)
ap.add_argument("--hz", type=float, default=10.0)
ap.add_argument("--out", default="/tmp/pose_probe.jsonl")
a = ap.parse_args()
t0 = time.time()
with open(a.out, "w", encoding="utf-8") as f:
    while time.time() - t0 < a.sec:
        try:
            x, y, z = pose()
            f.write(json.dumps({"t": round(time.time() - t0, 3), "x": x, "y": y, "z": z}) + "\n")
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(1.0 / a.hz)
print("probe done →", a.out)
