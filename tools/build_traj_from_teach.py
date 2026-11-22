#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_traj_from_teach.py — 把人工示教(teach_*.jsonl)学成一圈可回放的轨迹 + 段表。

产出(与演示回放同格式, 直接给 replay_demo_seg.py 用):
  zmax_data/rokae_sdk/real_traj_teach.json    frames: [{i,p[mm],rpy}]
  zmax_data/rokae_sdk/phase_states_teach.json states: [{i0,i1,name}] + 一条 "整圈"

重采样: 等弧长 STEP 毫米(默认 25mm); 姿态按段线性插值; 停点保留 3 帧窗口(与演示同规则)。
"""
from __future__ import annotations

import glob
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEP = float(os.environ.get("ZMAX_TEACH_STEP") or 25.0)


def main() -> int:
    src = sorted(glob.glob(os.path.join(ROOT, "zmax_data/teach/teach_*.jsonl")))[-1]
    learned = sorted(glob.glob(os.path.join(ROOT, "zmax_data/teach/learned_*.json")))[-1]
    rows = [json.loads(l) for l in open(src)]
    P = [[v * 1000.0 for v in r["p"]] for r in rows]
    R = [list(r["rpy"]) for r in rows]
    T = [r["ts"] for r in rows]

    # 等弧长重采样(保留原始姿态, 按弧长比例取/插值)
    acc = [0.0]
    for k in range(len(P) - 1):
        acc.append(acc[-1] + math.dist(P[k], P[k + 1]))
    tot = acc[-1]
    n = max(2, int(tot / STEP) + 1)
    frames, idx_map = [], []
    j = 0
    for t in range(n):
        target = tot * t / (n - 1)
        while j + 1 < len(acc) - 1 and acc[j + 1] < target:
            j += 1
        seg = acc[j + 1] - acc[j] if j + 1 < len(acc) else 0.0
        u = 0.0 if seg <= 1e-9 else max(0.0, min(1.0, (target - acc[j]) / seg))
        p = [a + (b - a) * u for a, b in zip(P[j], P[min(j + 1, len(P) - 1)])]
        r = [a + (b - a) * u for a, b in zip(R[j], R[min(j + 1, len(R) - 1)])]
        frames.append({"i": t, "p": [round(v, 1) for v in p], "rpy": [round(v, 4) for v in r],
                       "t": round(T[min(j, len(T) - 1)], 2)})
        idx_map.append(min(j, len(P) - 1))

    # 原始帧号 → 重采样帧号
    def to_new(k: int) -> int:
        best, bd = 0, 1e18
        for t, orig in enumerate(idx_map):
            d = abs(orig - k)
            if d < bd:
                best, bd = t, d
        return best

    st = json.load(open(learned))["states"]
    states = []
    for s in st:
        states.append({"i0": to_new(s["i0"]), "i1": to_new(s["i1"]), "name": s["name"]})
    states.append({"i0": 0, "i1": len(frames) - 1, "name": "整圈"})

    tj = os.path.join(ROOT, "zmax_data/rokae_sdk/real_traj_teach.json")
    ps = os.path.join(ROOT, "zmax_data/rokae_sdk/phase_states_teach.json")
    json.dump({"summary": {"len_mm": round(tot, 1), "n": len(frames)}, "frames": frames},
              open(tj, "w"), ensure_ascii=False)
    json.dump({"states": states}, open(ps, "w"), ensure_ascii=False, indent=1)
    print("示教轨迹: %d 点 · %.0fmm · 段 %d 条" % (len(frames), tot, len(states)))
    print("写入:", tj, "|", ps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
