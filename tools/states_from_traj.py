#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""states_from_traj.py — 按**工序顺序**自动给轨迹分段命名(不需要人工点)。

为什么不只按最近点: 钩位(806,230,189) 与 插入到底(818,227,190) 只差 13mm, 纯几何就近会抢标,
出现"钩拉环跑到插入之前"这种乱序。这里加两个约束:
  ① 顺序约束: 已知一圈的工序顺序(ORDER), 只能**往前走**(允许跳过整步, 不许回头);
  ② 到位约束: 与当前期望点的距离 ≤ TOL 才算"到点", 否则算移动。
这样命名能自洽, 且与现场演示的顺序一致。
输出: zmax_data/rokae_sdk/phase_states_demo.json
"""
from __future__ import annotations

import json
import math
import os

SDK = "/home/ubuntu/zmax/zmax_data/rokae_sdk"
TOL = 15.0
# 两处相距很近的点(插入到底 818,227,190 与 钩位 806,230,189 只差 13mm)要用更紧的容差,
# 否则一次到点会把下一步也"顺带越过"(实测: 插入到底整个丢失、钩拉环出现两次)。
TOL_PT = {"插入到底": 7.0, "钩拉环解锁": 7.0,
          "金手指检测1": 4.0, "金手指检测点2": 4.0}

ORDER = [
    ("初始点", (663.9, -29.3, 293.5)),
    ("槽2抓取", (649.0, 454.0, 111.0)),
    ("扫码", (754.6, 28.8, 271.4)),
    ("插入到底", (817.8, 227.3, 189.9)),
    ("等待检测", (720.6, 225.4, 227.9)),
    ("钩拉环解锁", (806.1, 230.1, 188.8)),
    ("金手指检测1", (492.8, 134.4, 696.0)),
    ("金手指检测点2", (493.3, 129.4, 701.4)),
    ("侧面点1", (415.3, -378.0, 537.3)),
    ("侧面点2", (411.4, -403.4, 535.0)),
    ("侧面点3", (408.0, -421.7, 535.0)),
    ("侧面点4", (394.4, -372.3, 542.8)),
    ("下盘放料", (648.1, -192.9, 118.1)),
    ("回初始位", (663.9, -29.3, 293.5)),
]


def main() -> int:
    tr = json.load(open(os.path.join(SDK, "real_traj_joints_demo.json")))["frames"]
    P = [f["p"] for f in tr]
    labels = []
    seen = set()
    k = 0
    for p in P:
        # 只看"当前该到的点"和"下一步": 就近抢标会把 13mm 的邻居点抢走(顺序就会丢步)
        d0 = math.dist(p, ORDER[k][1])
        t0 = TOL_PT.get(ORDER[k][0], TOL)
        d1 = math.dist(p, ORDER[k + 1][1]) if k + 1 < len(ORDER) else 1e9
        t1 = TOL_PT.get(ORDER[k + 1][0], TOL) if k + 1 < len(ORDER) else 0.0
        # 每个工序点在这一圈里只标一次(重复经过不算新工序, 否则页面会出现两条同名段)
        if d0 <= t0 and d0 <= d1 and ORDER[k][0] not in seen:
            labels.append(ORDER[k][0])
            seen.add(ORDER[k][0])
        elif d1 <= t1 and ORDER[k + 1][0] not in seen:
            k += 1
            labels.append(ORDER[k][0])
            seen.add(ORDER[k][0])
        else:
            labels.append(None)

    runs = []
    for i, v in enumerate(labels):
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
    # 同名相邻段合并(避免 12/14 那种重复)
    merged = []
    for s in states:
        if merged and merged[-1]["name"] == s["name"] and merged[-1]["i1"] + 1 >= s["i0"]:
            merged[-1]["i1"] = max(merged[-1]["i1"], s["i1"])
        else:
            merged.append(dict(s))
    merged = [s for s in merged if s["i1"] >= s["i0"]]

    json.dump({"states": merged}, open(os.path.join(SDK, "phase_states_demo.json"), "w"),
              ensure_ascii=False, indent=1)
    print("段 %d 条(轨迹 %d 帧)" % (len(merged), len(P)))
    for n, s in enumerate(merged, 1):
        print("  %2d %3d-%-3d %s" % (n, s["i0"], s["i1"], s["name"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
