#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_probe_joints.py — 落一份"当前关节角 + TCP"快照, 供 tools/robot_kin.py selftest 校验链模型。"""
import json
import sys

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

r = x.xMateRobot()
r.connectToRobot("192.168.23.160")
jp = r.jointPos({})
q = list(jp.jointPosition) if hasattr(jp, "jointPosition") else list(jp)
cp = r.cartPosture(x.CoordinateType.endInRef, {})
out = {"q": [round(float(v), 9) for v in q][:6],
       "tcp_mm": [round(float(v) * 1000.0, 2) for v in cp.trans],
       "rpy": [round(float(v), 6) for v in cp.rpy]}
json.dump(out, open("/sdk/tcp_out/joints.json", "w"))
print(json.dumps(out))
