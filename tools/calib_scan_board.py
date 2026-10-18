#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_scan_board.py —— 自动找到标定板: 让腕相机在台面上方扫几个位姿, 每处检出 ArUco 就记一个视图

老倪 2026-10-18: 「自动化跑吧, 而且我给你前面放了一个标定板子, 你自己标定吧」
板子在哪不知道 ⇒ 先扫。扫描高度在台面之上(z≥--z), 每步都过安全闸(授权/自动/空闲 + 围栏盒体素),
命中 ≥--need 个视图就停, 写进 views.json 交给 calib_fixed_cam.py。

用法:
  ./gui-venv311/bin/python tools/calib_scan_board.py --dry          # 只打印路线
  ./gui-venv311/bin/python tools/calib_scan_board.py --need 3
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G          # noqa: E402  复用: 前置检查 / move-abs / 等稳定 / pose

FENCES = os.path.join(REPO, "zmax_data", "ar_rs", "fences.json")


def load_boxes():
    """围栏里的盒子(不可进入), 返回 [(name, (x1,y1,z1), (x2,y2,z2))]。"""
    out = []
    try:
        d = json.load(open(FENCES, encoding="utf-8"))
        items = d.get("items") if isinstance(d, dict) else d
        for e in (items or []):
            if str(e.get("type") or e.get("kind")).lower() not in ("box", "cube", "cuboid"):
                continue
            if e.get("enabled") is False:
                continue
            a, b = e.get("p1"), e.get("p2")
            if not a or not b:
                continue
            # 🔴 fences.json 里的坐标是**米**, 本脚本全用毫米 —— 不换算会把闸放空(实测第一次就 0 个盒子)
            a = [float(v) * 1000.0 for v in a]
            b = [float(v) * 1000.0 for v in b]
            lo = [min(a[i], b[i]) for i in range(3)]
            hi = [max(a[i], b[i]) for i in range(3)]
            out.append((e.get("name") or e.get("id") or "box", lo, hi))
    except Exception:                                                       # noqa: BLE001
        pass
    return out


def blocked(pt, boxes, pad=60.0, z_pad=45.0):
    x, y, z = pt
    for name, lo, hi in boxes:
        if lo[0] - pad <= x <= hi[0] + pad and lo[1] - pad <= y <= hi[1] + pad and lo[2] - z_pad <= z <= hi[2] + z_pad:
            return name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--z", type=float, default=340.0, help="扫描高度 mm (台面=0)")
    ap.add_argument("--xs", default="520,660", help="x 列表")
    ap.add_argument("--ys", default="-250,-100,50,200,350", help="y 列表")
    ap.add_argument("--speed", type=float, default=70.0)
    ap.add_argument("--need", type=int, default=3, help="凑够几个含 marker 的视图就停")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    xs = [float(v) for v in a.xs.split(",")]
    ys = [float(v) for v in a.ys.split(",")]
    boxes = load_boxes()
    print("围栏盒子 %d 个" % len(boxes))
    plan = []
    for x in xs:
        for y in ys:
            p = (x, y, a.z)
            b = blocked(p, boxes)
            if not (100 <= x <= 800 and -500 <= y <= 500 and 40 <= a.z <= 700):
                print("  跳过(超范围) %s" % (p,))
                continue
            if b:
                print("  跳过(围栏 %s) %s" % (b, p))
                continue
            plan.append(p)
    print("扫描点 %d 个: %s" % (len(plan), [tuple(round(v) for v in p) for p in plan]))
    if a.dry:
        return 0

    ok, bad, st, rb = G.preflight()
    if not ok:
        print("🛑 前置不满足: %s" % " / ".join(bad))
        return 2

    hits = 0
    for i, p in enumerate(plan, 1):
        ok, bad, st, rb = G.preflight()
        if not ok:
            print("🛑 中途前置失效: %s ⇒ 停" % " / ".join(bad))
            return 3
        p0 = np.array(G.pose()[0]) * 1000.0
        print("[%d/%d] → %s mm (从 %s)" % (i, len(plan), tuple(round(v) for v in p), tuple(round(v, 1) for v in p0)))
        r = G.send({"cmd": "move-abs", "x": p[0] / 1000.0, "y": p[1] / 1000.0, "z": p[2] / 1000.0,
                    "speed": float(a.speed)}, wait=60)
        if "PASS" not in str(r.get("verdict", "")):
            print("   移动未确认: %s ⇒ 停" % str(r.get("verdict"))[:120])
            return 4
        G.wait_settle(np.array(G.pose()[0]), math.dist(p, p0), timeout=45, min_frac=0.5)
        time.sleep(0.6)
        import subprocess
        out = subprocess.run([os.path.join(REPO, "gui-venv311", "bin", "python"),
                              os.path.join(REPO, "tools", "calib_grab_view.py"),
                              "--tag", "scan%02d" % i], capture_output=True, text=True, timeout=120)
        line = (out.stdout or "").strip().splitlines()
        print("   " + (line[-1] if line else out.stderr[-200:]))
        if line and "检出 marker []" not in line[-1]:
            hits += 1
            print("   ✅ 第 %d 个含 marker 的视图" % hits)
            if hits >= a.need:
                print("凑够 %d 个视图 ⇒ 停扫描, 去解算" % hits)
                return 0
    print("扫完, 只命中 %d 个视图" % hits)
    return 0 if hits else 5


if __name__ == "__main__":
    sys.exit(main())
