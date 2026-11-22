#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""learn_from_teach.py — 把人工示教(点动)的一段位姿流学成"工序段表"。

输入:  zmax_data/teach/teach_*.jsonl   (10Hz, 每行 {ts,p[m],rpy})
输出:  zmax_data/teach/learned_<ts>.json
        {"n": 拍数, "len_mm": 弧长, "stops": [...], "states": [{i0,i1,name,dur_s,p}...]}

判据:
  · 停留 = 连续 ≥0.35s 且位移 < 2.5mm 的窗口
  · 段名 = 用现有真源(config/points/*.json + 演示相位的操作点名)里最近的点命名,
    距离 ≤25mm 才算"到点", 否则叫 移动→未知N
  · 相邻停留点之间一律 "移动→<目标点名>"
"""
from __future__ import annotations

import glob
import json
import math
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_known():
    """已知点名 → 坐标(mm)。真源: config/points/*.json + 演示段表。"""
    out = {}
    for f in glob.glob(os.path.join(ROOT, "config/points/*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for k, v in (d.items() if isinstance(d, dict) else []):
            if isinstance(v, dict) and all(c in v for c in "xyz"):
                out[k] = [float(v["x"]), float(v["y"]), float(v["z"])]
            elif isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(c, (int, float)) for c in v):
                out[k] = [float(c) for c in v]
    try:
        pd = os.path.join(ROOT, "zmax_data/rokae_sdk/phase_states_demo.json")
        tj = os.path.join(ROOT, "zmax_data/rokae_sdk/real_traj_joints_demo.json")
        st = json.load(open(pd))["states"]
        fr = json.load(open(tj))["frames"]
        for s in st:
            if "→" not in s["name"]:
                out.setdefault(s["name"], [float(c) for c in fr[s["i1"]]["p"]])
    except Exception:
        pass
    return out


def main() -> int:
    f = sorted(glob.glob(os.path.join(ROOT, "zmax_data/teach/teach_*.jsonl")))[-1]
    rows = [json.loads(l) for l in open(f)]
    P = [[v * 1000.0 for v in r["p"]] for r in rows]
    T = [r["ts"] for r in rows]
    known = load_known()

    # 1) 停留检测
    stops, i = [], 0
    while i < len(P):
        j = i
        while j + 1 < len(P) and math.dist(P[j + 1], P[i]) < 2.5:
            j += 1
        if T[j] - T[i] >= 0.35:
            stops.append({"i0": i, "i1": j, "p": P[(i + j) // 2], "dur": round(T[j] - T[i], 2)})
        i = j + 1

    # 2) 命名
    def name_of(p):
        best, bd = None, 1e9
        for k, c in known.items():
            d = math.dist(p, c)
            if d < bd:
                best, bd = k, d
        return (best, round(bd, 1)) if bd <= 25.0 else ("未知%d" % (len(stops)), round(bd, 1))

    states = []
    if stops and stops[0]["i0"] > 0:
        states.append({"i0": 0, "i1": stops[0]["i0"] - 1, "name": "初始点"})
    prev = None
    for n, s in enumerate(stops):
        nm, dd = name_of(s["p"])
        s["name"], s["dist"] = nm, dd
        # 同一个点的"二次停顿"(手抖/换手) 合并, 否则会多出 移动→X / X 的重复段
        if prev is not None and nm == prev["name"] and math.dist(prev["p"], s["p"]) < 30.0:
            prev["i1"] = s["i1"]
            prev["dur"] = round(prev["dur"] + s["dur"], 2)
            continue
        if prev is not None and s["i0"] - 1 >= prev["i1"] + 1:
            states.append({"i0": prev["i1"] + 1, "i1": s["i0"] - 1, "name": "移动→" + nm})
        states.append({"i0": s["i0"], "i1": s["i1"], "name": str(nm)})
        prev = s
    if prev is not None and prev["i1"] + 1 < len(P):
        states.append({"i0": prev["i1"] + 1, "i1": len(P) - 1, "name": "移动→回初始位"})

    ln = sum(math.dist(P[k], P[k + 1]) for k in range(len(P) - 1))
    out = {"src": f, "n": len(P), "len_mm": round(ln, 1),
           "t0": T[0], "t1": T[-1], "stops": stops, "states": states}
    dst = os.path.join(ROOT, "zmax_data/teach/learned_%s.json" % time.strftime("%H%M%S"))
    json.dump(out, open(dst, "w"), ensure_ascii=False, indent=1)

    print("学到: %d 拍 · %.0fmm · %.1fs · 停留 %d 个 · 段 %d 条"
          % (len(P), ln, T[-1] - T[0], len(stops), len(states)))
    for s in states:
        print("  %3d-%-3d %-22s" % (s["i0"], s["i1"], s["name"]))
    print("写入:", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
