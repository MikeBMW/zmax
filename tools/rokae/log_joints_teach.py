#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""log_joints_teach.py — 边点动边记**关节角 + TCP**(10Hz)。

为什么要这个: 想用 MoveAbsJ 复现示教轨迹, 必须有关节角; 但控制器不提供 IK,
而 spec 里的链模型与真机对不上(FK 自检差 235mm)。最稳的办法是示教时直接记关节角 ——
有了 j 就能 MoveAbsJ 原样回放, 完全绕开 IK 与手腕奇异区。

用法(宿主):
  timeout 1800 bash tools/rokae_sdk_run.sh --script log_joints_teach.py
产出: zmax_data/rokae_sdk/teach_joints_<时间>.jsonl
"""
import json
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = "192.168.23.160"
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 1500.0

r = x.xMateRobot()
r.connectToRobot(IP)
path = "/sdk/teach_joints_%s.jsonl" % time.strftime("%H%M%S")
f = open(path, "w")
print("记录 →", path, flush=True)
t0 = time.time()
n = 0
while time.time() - t0 < DUR:
    try:
        jp = r.jointPos({})
        q = list(jp.jointPosition)[:6] if hasattr(jp, "jointPosition") else list(jp)[:6]
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        rec = {"ts": round(time.time(), 4),
               "j": [round(float(v), 6) for v in q],
               "p": [round(float(v) * 1000.0, 2) for v in cp.trans],
               "rpy": [round(float(v), 6) for v in cp.rpy]}
        f.write(json.dumps(rec) + "\n")
        f.flush()
        n += 1
    except Exception as e:
        f.write(json.dumps({"ts": round(time.time(), 4), "err": str(e)}) + "\n")
        f.flush()
    time.sleep(0.1)
print("结束: %d 条 → %s" % (n, path), flush=True)
