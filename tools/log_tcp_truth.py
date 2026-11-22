#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""log_tcp_truth.py — 30Hz 落真值时间序列 (与图像分开存, 训练时按时间戳配对)。

背景: 图像流 /arm.mjpg 实测上限约 15Hz, 而真值中继已提到 30Hz。
      把真值单独按 30Hz 存下来, 抓取接触瞬间(40mm 垂直段)不会漏采样;
      训练时用"图像 ts → 最近真值"配对, 动作标签用真值序列差分更细。

只读: 只 GET /api/tcp, 不碰机器人。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

ROOT = "/home/ubuntu/zmax"
OUT_DIR = os.path.join(ROOT, "zmax_data/live_truth")
URL = "http://127.0.0.1:8797/api/tcp"
HZ = float(os.environ.get("ZMAX_TRUTH_HZ", "30"))
SECS = float(os.environ.get("ZMAX_TRUTH_SECS", "5400"))


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "truth_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    t0 = time.time()
    n = 0
    with open(out, "w", buffering=1) as f:
        while time.time() - t0 < SECS:
            ts = time.time()
            try:
                d = json.loads(urllib.request.urlopen(URL, timeout=2).read())
                f.write(json.dumps({"ts": ts, "x": d["x"] * 1000.0, "y": d["y"] * 1000.0,
                                    "z": d["z"] * 1000.0, "rpy": d.get("rpy"),
                                    "age": d.get("age_s")}) + "\n")
                n += 1
            except Exception:
                pass
            time.sleep(max(0.0, 1.0 / HZ - (time.time() - ts)))
    print("truth: %d 条 → %s" % (n, out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
