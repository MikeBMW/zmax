#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_insert.py — 盯光模块插入 (只读遥测, 不下发任何指令)

每秒采一次, 打一行:
  时刻 · TCP(x,y,z mm) · 轴向力/侧向力 N · 光模块实时框(是否检出/中心/宽高) · 臂画面变化(与首帧的差分%)
用处: 老倪在做插入动作时, 用来判"臂动了没有 / 力有没有接触变化 / 检测器还看不看得见模块"。
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

REPO = "/home/ubuntu/zmax"


def jget(url, timeout=8, default=None):
    try:
        return json.loads(urllib.request.urlopen(url, timeout=timeout).read().decode())
    except Exception:                                                     # noqa: BLE001
        return default if default is not None else {}


def bget(url, timeout=8):
    try:
        return urllib.request.urlopen(url, timeout=timeout).read()
    except Exception:                                                     # noqa: BLE001
        return b""


def main(secs=60, hz=1.0):
    t0 = time.time()
    ref = None
    print("%-8s %-22s %-16s %-28s %-7s" % ("t", "TCP mm", "力 N(轴/侧)", "光模块实时框", "画面差"))
    print("-" * 92, flush=True)
    last_sig = None
    while time.time() - t0 < secs:
        now = time.strftime("%H:%M:%S")
        # 位姿真值
        try:
            d = json.load(open(REPO + "/zmax_data/rokae_sdk/tcp_out/latest.json"))
            pose = "%7.1f %7.1f %7.1f" % (d.get("x", 0) * 1000, d.get("y", 0) * 1000, d.get("z", 0) * 1000)
        except Exception:                                                 # noqa: BLE001
            pose = "  —"
        # 真机六维力
        try:
            f = json.load(open(REPO + "/zmax_data/rokae_sdk/ft_out/latest.json"))
            ax = float(f.get("fx") or 0)
            lat = (float(f.get("fy") or 0) ** 2 + float(f.get("fz") or 0) ** 2) ** 0.5
            force = "%6.1f /%6.1f" % (ax, lat)
        except Exception:                                                 # noqa: BLE001
            force = "  —"
        # 光模块实时检测(不是定主那份)
        m = jget("http://127.0.0.1:8797/api/module3d")
        live = (m.get("live") or {}) if m.get("locked") else m
        b2 = (live.get("box2d") or []) if isinstance(live, dict) else []
        if b2:
            box = "检出 c=(%4.0f,%4.0f) %3.0fx%3.0f" % ((b2[0] + b2[2]) / 2, (b2[1] + b2[3]) / 2, b2[2] - b2[0], b2[3] - b2[1])
        else:
            box = "未检出"
        # 臂画面差分
        b = bget("http://127.0.0.1:8791/snapshot/arm.jpg")
        diff = "  —"
        mean = 0.0
        if b:
            try:
                a = np.asarray(Image.open(io.BytesIO(b)).convert("L")).astype(np.float32)
                mean = float(a.mean())
                if ref is None:
                    ref = a
                    diff = "首帧"
                else:
                    diff = "%.1f%%" % (float(np.abs(a - ref).mean()) / max(mean, 1) * 100)
            except Exception:                                             # noqa: BLE001
                pass
        line = "%-8s %-22s %-16s %-28s %-7s" % (now, pose, force, box, diff)
        print(line, flush=True)
        time.sleep(max(0.05, 1.0 / hz))
    print("\n采样结束 · 臂画面均值 %.1f (0=全黑)" % mean)


if __name__ == "__main__":
    s = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    main(secs=s)
