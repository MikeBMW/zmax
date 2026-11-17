#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traj_point_table.py — 215 点轨迹「这一拍到底在哪/在干什么」判定表

为什么需要: 用户报的是**时钟读数**(如「MT 33.1s 你写的是插入孔内」), 而段表/几何是按**点号**的。
点数均分会算错 —— 必须用逐点实测耗时累加( replay215_timing.json 的 points[].secs )。

用法:
  python3 traj_point_table.py                    # 打印 0~45 点: t/TCP/离参考点距/单点s/累计s
  python3 traj_point_table.py --at 33.1          # 只回答「33.1s 落在第几点, 那么它离孔多远」
  python3 traj_point_table.py --i0 80 --i1 130   # 看别的区间
  python3 traj_point_table.py --ref 811.6,229.8,187.6   # 换参考真值(默认 2 号孔插到位)

判定口径(两把尺):
  · 离参考点 >100mm  ⇒ 不可能是「在该点位上做插入/接触」那类动作
  · 单点 secs 明显偏长(邻居 1~2s 而它 4s+) ⇒ 停在那里做事(扫码/检测/等待), 不是走过场
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

REPO = os.environ.get("ZMAX_REPO", os.path.expanduser("~/zmax"))
FRAMES = os.path.join(REPO, "tools", "web", "real_traj_joints.json")
TIMING = os.path.join(REPO, "zmax_data", "runtime", "traj", "replay215_timing.json")


def load():
    fr = json.load(open(FRAMES, encoding="utf-8"))["frames"]
    tm = json.load(open(TIMING, encoding="utf-8"))["points"]
    secs = [float(p.get("secs") or 0.0) for p in tm]
    acc = [0.0]
    for s in secs:
        acc.append(acc[-1] + s)
    return fr, secs, acc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="811.6,229.8,187.6", help="参考真值 mm, 默认 2 号孔插到位")
    ap.add_argument("--at", type=float, default=None, help="时钟读数(s), 回答它落在第几点")
    ap.add_argument("--i0", type=int, default=8)
    ap.add_argument("--i1", type=int, default=45)
    a = ap.parse_args()

    fr, secs, acc = load()
    ref = [float(x) for x in a.ref.split(",")]
    if len(ref) != 3:
        print("ref 要是 x,y,z", file=sys.stderr)
        return 2

    def dist_mm(i):
        p = fr[i]["p"]
        return math.dist([p[0] * 1000, p[1] * 1000, p[2] * 1000], ref)

    print("共 %d 点 · 实测总耗时 %.2fs · 参考点 %s" % (len(fr), acc[-1], ref))

    if a.at is not None:
        hit = None
        for i, s in enumerate(secs):
            if acc[i] <= a.at < acc[i + 1]:
                hit = i
                break
        if hit is None:
            print("%.1fs 超出总时长 %.1fs" % (a.at, acc[-1]))
            return 0
        p = [round(v * 1000, 1) for v in fr[hit]["p"]]
        print("→ %.1fs 落在第 %d 点 (累计 %.2f~%.2fs, 单点 %.2fs)" % (a.at, hit, acc[hit], acc[hit + 1], secs[hit]))
        print("  TCP %s mm · 离参考点 %.0f mm · t=%.2fs" % (p, dist_mm(hit), fr[hit]["t"]))
        print("  判读: %s" % ("离参考点>100mm ⇒ 不在该点位上" if dist_mm(hit) > 100 else "在参考点附近"))
        print("  单点耗时: %s" % ("偏长 ⇒ 有停留动作" if secs[hit] > 3.0 else "常规"))

    print("\n  i     t(s)   TCP mm                       离参考mm  单点s   累计s")
    for i in range(max(0, a.i0), min(len(fr), a.i1 + 1)):
        p = [round(v * 1000, 1) for v in fr[i]["p"]]
        print("%3d %7.2f  [%7.1f %7.1f %7.1f]   %5.0f   %5.2f  %7.1f"
              % (i, fr[i]["t"], p[0], p[1], p[2], dist_mm(i), secs[i], acc[i + 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
