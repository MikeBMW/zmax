#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 251 点相位轨迹的「槽6 → 末尾」段写成 real_traj_joints.json 格式, 供 step_traj 下发。

为什么不用现成的 215 点: 215 点从槽6(#9) 往后仍有 49 点落在 F668833 检测设备盒内
(x712~844 / y-91~302 / z0~340) —— 那就是 11-24 20:32 撞机的位置。
251 点从 #75 往后 176 点与该盒交集为 0, 所以改用这一段。

用法:
  python3 tools/aoi_seg_to_traj.py [--from 75] [--dry-run]
产物:
  tools/web/real_traj_joints.json         (原文件备份为 .bak_slot6_<ts>)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEO = os.path.join(REPO, "zmax_data/traj_phase/phase251_20261124/geo_raw.json")
J372 = os.path.join(REPO, "zmax_data/traj_phase/phase251_20261124/joints_372f.json")
OUT = os.path.join(REPO, "tools/web/real_traj_joints.json")
FENCE = ((712., -91., 0.), (844., 302., 340.))     # F668833, mm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="i0", type=int, default=75,
                    help="起始点索引(251 点口径), 默认 75 = 槽6 最近点")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    geo = json.load(open(GEO, encoding="utf-8"))
    fr = geo["frames"]
    P = np.array([f["p"] for f in fr], float)
    n251 = len(fr)
    print("251 点轨迹 %d 点; 起点 #%d = (%.0f,%.0f,%.0f)" % (n251, a.i0, *P[a.i0]))

    seg = P[a.i0:]
    lo, hi = [np.array(v) for v in FENCE]
    inb = ((seg >= lo) & (seg <= hi)).all(1)
    print("段长 %d 点, F668833 命中 %d 点 %s" % (len(seg), inb.sum(),
                                            "✅" if inb.sum() == 0 else "🔴 中止"))
    if inb.sum():
        return 2

    jd = json.load(open(J372, encoding="utf-8"))
    jl = jd["frames"] if isinstance(jd, dict) else jd
    n372 = len(jl)
    print("372 帧关节源 %d 帧" % n372)

    # 251 索引 -> 372 帧索引 (phase_traj_ik2 是逐点 IK + 插值, 两端线性对应)
    idx = [int(round(i / max(1, n251 - 1) * (n372 - 1))) for i in range(a.i0, n251)]
    print("取 372 帧 [%d..%d] 共 %d 帧" % (idx[0], idx[-1], len(idx)))

    frames = []
    t = 0.0
    for k, (i251, i372) in enumerate(zip(range(a.i0, n251), idx)):
        src = jl[i372]
        fr_geo = fr[i251]
        frames.append({
            "i": k,
            "p": [float(x) for x in fr_geo["p"]],       # mm
            "q": [float(x) for x in fr_geo["q"]],       # [w,x,y,z] (8815 口径)
            "j": [float(x) for x in src["j"]],          # rad
            "t": round(t, 3),
        })
        t += 1.0 / 25.0

    out = {"ok": True, "src": os.path.relpath(GEO, REPO), "from": a.i0,
           "n": len(frames), "fps": 25, "dur_s": round(t, 2),
           "note": "槽6(#%d)→末尾, 与 F668833 检测设备盒交集为 0" % a.i0,
           "frames": frames}

    print("产出 %d 帧 · %.2fs @25fps" % (len(frames), t))
    jz = [f["j"] for f in frames]
    jz = np.array(jz)
    print("关节范围(deg) min %s max %s" % (
        np.round(np.degrees(jz.min(0)), 1).tolist(),
        np.round(np.degrees(jz.max(0)), 1).tolist()))
    step = np.abs(np.degrees(np.diff(jz, axis=0))).max(1) if len(jz) > 1 else np.array([0])
    print("单帧最大关节跳变 %.1f°" % step.max())

    if a.dry_run:
        print("(--dry-run) 未写文件")
        return 0

    if os.path.isfile(OUT):
        bak = OUT + ".bak_slot6_" + time.strftime("%H%M%S")
        shutil.copy2(OUT, bak)
        print("已备份原文件 → %s" % os.path.basename(bak))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("已写 %s (%d 帧)" % (os.path.relpath(OUT, REPO), len(frames)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
