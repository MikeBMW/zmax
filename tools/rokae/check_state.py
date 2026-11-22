#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_state.py — 只读查询控制器状态(不下发任何动作)。用于 EStop 后确认是否已复位。"""
import json
import os
import sys

sys.path.insert(0, "/sdk")
import xcoresdk_python as x   # noqa: E402

IP = os.environ.get("ROKAE_IP") or "192.168.23.160"

r = x.xMateRobot()
r.connectToRobot(IP)
out = {
    "powerState": str(r.powerState({})),
    "operationState": str(r.operationState({})),
    "operateMode": str(r.operateMode({})),
}
cp = r.cartPosture(x.CoordinateType.endInRef, {})
out["tcp_mm"] = [round(float(v) * 1000.0, 1) for v in cp.trans]
out["rpy"] = [round(float(v), 3) for v in cp.rpy]
print(json.dumps(out, ensure_ascii=False))
