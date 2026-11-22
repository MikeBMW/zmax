#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""states_from_traj.py — 直接按"点位置"给轨迹分段命名(不再靠帧比例映射, 那样会整体错位)。

判据: 每帧找最近已知工位点, 距离 ≤20mm 记为该点(操作点), 否则记为移动;
      连续同类合并成段; 操作段不足 3 帧的从相邻移动段借。
输出: zmax_data/rokae_sdk/phase_states_demo.json
"""
from __future__ import annotations

import json
import math
import os

SDK = "/home/ubuntu/zmax/zmax_data/rokae_sdk"

PTS = {
    "初始点": (663.9, -29.3, 293.5),
    "槽2抓取": (649.0, 454.0, 111.0),
    "扫码": (754.6, 28.8, 271.4),
    "插入到底": (817.8, 227.3, 189.9),
    "等待检测": (720.6, 225.4, 227.9),
    # ⚠️ 钩位(806,230,189) 与"插入到底"(818,227,190) 只差 13mm —— 两个都留在字典里会让
    #    近邻判定随机抢标、段顺序错乱(实测: 钩拉环跑到插入之前)。这里只留"插入到底",
    #    钩段由"移动→"承载; 要单列钩段得用关节角或时间顺序区分。
    # "钩拉环解锁": (806.1, 230.1, 188.8),
    "金手指检测1": (492.8, 134.4, 696.0),
    "金手指检测点2": (493.3, 129.4, 701.4),
    "侧面点1": (415.3, -378.0, 537.3),
    "侧面点2": (411.4, -403.4, 535.0),
    "侧面点3": (408.0, -421.7, 535.0),
    "侧面点4": (394.4, -372.3, 542.8),
    "下盘放料": (648.1, -192.9, 118.1),
}


def main() -> int:
    tr = json.load(open(os.path.join(SDK, "real_traj_joints_demo.json")))["frames"]
    P = [f["p"] for f in tr]
    lab = []
    for p in P:
        best, bd = None, 1e9
        for k, c in PTS.items():
            d = math.dist(p, c)
            if d < bd:
                best, bd = k, d
        lab.append(best if bd <= 20.0 else None)

    runs = []
    for i, v in enumerate(lab):
        if runs and runs[-1][0] == v:
            runs[-1][2] = i
        else:
            runs.append([v, i, i])

    states = []
    for j, (v, a, b) in enumerate(runs):
        if v:
            states.append({"i0": a, "i1": b, "name": v})
        else:
            nxt = next((r[0] for r in runs[j:] if r[0]), "回初始位")
            states.append({"i0": a, "i1": b, "name": "移动→" + nxt})

    # 操作段补到至少 3 帧
    for i, s in enumerate(states):
        if not s["name"].startswith("移动→") and s["i1"] - s["i0"] < 2 and i > 0:
            need = 2 - (s["i1"] - s["i0"])
            if (states[i - 1]["i1"] - states[i - 1]["i0"] + 1) - need >= 1:
                states[i - 1]["i1"] -= need
                s["i0"] -= need

    states = [s for s in states if s["i1"] >= s["i0"]]
    json.dump({"states": states}, open(os.path.join(SDK, "phase_states_demo.json"), "w"),
              ensure_ascii=False, indent=1)
    print("段 %d 条(轨迹 %d 帧)" % (len(states), len(P)))
    for s in states:
        print("  %3d-%-3d %s" % (s["i0"], s["i1"], s["name"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
