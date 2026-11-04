#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对位阶段取证: 逐帧打印 stage / |x−peg| / u / 是否卡住"""
import os, sys
import numpy as np
os.environ.setdefault("MUJOCO_GL", "egl")
ROOT = "/home/ubuntu/zmax"
for p in (f"{ROOT}/tools", f"{ROOT}/tools/gui", f"{ROOT}/src"):
    sys.path.insert(0, p)
os.environ.setdefault("STABLEWM_HOME", f"{ROOT}/zmax_data/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", f"{ROOT}/zmax_data/stable-wm-cache")

from state_space_sim_real import RealStateSpaceSim   # noqa: E402

sim = RealStateSpaceSim(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 104, vision=False, mode="insert", log=lambda *a: None)
tr = sim.run(max_steps=int(sys.argv[2]) if len(sys.argv) > 2 else 400)
stage = tr["stage"]; x = np.asarray(tr["x"])
peg = np.asarray(tr["peg"], dtype=float).ravel()[:3] if "peg" in tr else None
u = np.asarray(tr.get("u_exec_vec", tr.get("u_sat_vec", np.zeros((len(stage), 4)))))
print("frames", len(stage), "peg", peg)
prev = None; hold = 0
for i, s in enumerate(stage):
    d = float(np.linalg.norm(x[i][:2] - peg[:2])) if peg is not None else -1
    if s != prev:
        print(f"[{i:4d}] stage→{s:12s} d_xy={d*1000:7.2f}mm x={np.round(x[i],4)} u={np.round(u[i][:3],4)}")
        prev = s; hold = 0
    else:
        hold += 1
        if hold % 100 == 0:
            print(f"       … {s} 持续 {hold} 帧, d_xy={d*1000:.2f}mm, u={np.round(u[i][:3],4)}")
