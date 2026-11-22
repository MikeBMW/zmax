#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_diag_chain.py — 离线对齐链模型: 用 real_traj_joints_v2q.json(239 帧, 带 j 与 p) 找
"关节顺序/符号/单位"哪个组合能让 FK 命中实测 TCP。不动机械臂。"""
import itertools
import json
import sys

import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax")
from tools.robot_kin import fk, load_chain  # noqa: E402

d = json.load(open("/home/ubuntu/zmax/zmax_data/rokae_sdk/real_traj_joints_v2q.json"))["frames"]
js = load_chain()
rows = [f for f in d if f.get("j") and f.get("p")][:8]
print("样例 j:", [round(v, 3) for v in rows[0]["j"]], " p:", rows[0]["p"])


def err(order, flip, scale):
    es = []
    for f in rows:
        q = [f["j"][order[i]] * flip[i] * scale for i in range(6)]
        T = fk(js, q)
        # ⚠️ p 存的是**米**(0.663), FK 输出米 → 统一到毫米再比
        es.append(float(np.linalg.norm(T[:3, 3] * 1000.0 - np.asarray(f["p"]) * 1000.0)))
    return sum(es) / len(es)


best = (1e9, None)
for scale in (1.0, 57.29578):
    for flip in itertools.product((1, -1), repeat=6):
        for order in [tuple(range(6))]:
            e = err(order, flip, scale)
            if e < best[0]:
                best = (e, (order, flip, scale))
print("最好: err %.1fmm  order=%s flip=%s scale=%s" % (best[0], best[1][0], best[1][1], best[1][2]))
