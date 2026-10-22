#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdk_j6.py —— 关节空间原地转 J6 (绕工具轴自转), 用于**脱离腕部奇异**.

为什么需要:
  2026-10-20 实测 J6≈0.0017rad(≈0.1°) 且 J5≈0.153rad ⇒ 腕部接近奇异 (tool Z 与 J1 轴同向),
  控制器对任何笛卡尔直线运动都回 `控制器未执行(6s 零位移且 idle · 疑似 50102 奇异点)`,
  moveReset / 切 manual→auto / 重新上电都无效 —— 只有把 J6 转开几度才能继续走直线。

口径:
  · 只改 J6, 其余关节保持; 速度慢(默认 5%) · 单次 |Δ| ≤ 45°
  · 前置 power on / automatic / idle; 结束回读关节角 + 报警

用法:
  bash tools/rokae_sdk_run.sh --script sdk_j6.py --deg 20
  bash tools/rokae_sdk_run.sh --script sdk_j6.py --deg -20 --speed 4
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def joints(r):
    v = r.jointPos({})
    if isinstance(v, dict):
        for k in ("jointPos", "joint", "values", "data"):
            if k in v:
                v = v[k]
                break
        else:
            v = list(v.values())[0]
    return [float(t) for t in list(v)[:6]]


def main() -> int:
    deg = 20.0
    speed = 5.0
    jidx = 6
    for i, a in enumerate(sys.argv):
        if a == "--deg" and i + 1 < len(sys.argv):
            deg = float(sys.argv[i + 1])
        if a == "--speed" and i + 1 < len(sys.argv):
            speed = float(sys.argv[i + 1])
        if a == "--joint" and i + 1 < len(sys.argv):
            jidx = int(sys.argv[i + 1])
    deg = max(-45.0, min(45.0, deg))
    jidx = max(1, min(6, jidx))
    r = x.xMateRobot()
    r.connectToRobot(IP)
    st = {"power": str(r.powerState({})), "op": str(r.operationState({}))}
    if "on" not in st["power"].lower() or "idle" not in st["op"].lower():
        print(json.dumps({"ok": False, "why": "前置不满足", "state": st}, ensure_ascii=False))
        return 2
    j0 = joints(r)
    tgt = list(j0)
    tgt[jidx - 1] = j0[jidx - 1] + math.radians(deg)
    ec = {}
    r.moveReset({})
    cmd = x.MoveAbsJCommand(x.JointPosition([float(v) for v in tgt]), speed, -1)
    r.moveAppend([cmd], x.PyString("jmove%d" % jidx), ec)
    if ec.get("ec", 0) != 0:
        print(json.dumps({"ok": False, "why": "moveAppend 被拒", "ec": ec}, ensure_ascii=False))
        return 2
    r.moveStart({})
    t0 = time.time()
    while time.time() - t0 < 30:
        time.sleep(0.1)
        if "idle" in str(r.operationState({})) and time.time() - t0 > 0.6:
            break
    j1 = joints(r)
    d = [round(math.degrees(b - a), 2) for a, b in zip(j0, j1)]
    out = {"ok": abs(d[jidx - 1]) > 0.5, "joint": jidx, "req_deg": deg,
           "joint_deg_before": [round(math.degrees(v), 2) for v in j0],
           "joint_deg_after": [round(math.degrees(v), 2) for v in j1],
           "delta_deg": d, "secs": round(time.time() - t0, 2), "op": str(r.operationState({}))}
    print(json.dumps(out, ensure_ascii=False))
    try:
        r.disconnectFromRobot({})
    except Exception:  # noqa: BLE001
        pass
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
