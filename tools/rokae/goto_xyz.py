#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goto_xyz.py — 单点走位(保持姿态), 过包络闸 + 运动中力看门狗。

用于按回放轨迹的坐标点走位(轨迹 reference: tools/web/real_traj_joints.json)。
姿态**不改**: 用当前实测 rpy 原样下发(轨迹里 #20 的 q 与已成功两次的入点姿态相差 178.8°,
是 180° 滚转的另一支, 照抄会把模块翻过来), 只借轨迹的**位置与深度标尺**。

用法: python3 goto_xyz.py --target 762.60,228.05,190.06 --speed 0.4
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x                                                  # noqa: E402
import safe_envelope as se                                                   # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="x,y,z mm")
    ap.add_argument("--speed", type=float, default=0.4)
    ap.add_argument("--f-stop", type=float, default=12.0)
    a = ap.parse_args()
    tgt_mm = [float(t) for t in a.target.split(",")]

    r = x.xMateRobot()
    r.connectToRobot(IP)
    print("自检:", r.powerState({}), r.operateMode({}), r.operationState({}), flush=True)
    if "on" not in str(r.powerState({})) or "automatic" not in str(r.operateMode({})):
        print("✗ 前置不满足")
        return 3
    ok, why = se.check(tgt_mm, "target")
    print("包络:", why, flush=True)
    if not ok:
        return 4
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]
    hist = []

    def f_filt():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        d = vals(b[3])[:3]
        if max(abs(t) for t in d) > 200:
            return None
        hist.append(d)
        if len(hist) > 5:
            hist.pop(0)
        return [statistics.median([h[i] for h in hist]) for i in range(3)]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    p0, rpy = pose()
    p0m = [v * 1000 for v in p0]
    ok2, why2 = se.check_path(p0m, tgt_mm, 12)
    print("路径:", why2, flush=True)
    if not ok2:
        return 4
    for _ in range(6):
        f_filt()
    base = f_filt()
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
    r.moveReset({})
    ec = {}
    r.moveAppend(x.MoveLCommand(x.CartesianPosition([v / 1000.0 for v in tgt_mm],
                                                  [float(v) for v in rpy]), a.speed, -1),
                 x.PyString("goto"), ec)
    if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
        print("✗ 下发失败", ec)
        return 5
    r.moveStart({})
    t0 = time.time()
    peak = 0.0
    tripped = False
    seen = False
    while time.time() - t0 < 90:
        f = f_filt()
        if f and base:
            d = math.dist(f, base)
            peak = max(peak, d)
            if d > a.f_stop:
                r.stop({})
                r.moveReset({})
                tripped = True
                break
        st = str(r.operationState({}))
        if "moving" in st:
            seen = True
        elif "idle" in st and seen:
            break
        time.sleep(0.02)
    p1, rpy1 = pose()
    p1m = [v * 1000 for v in p1]
    print("起点 %.2f %.2f %.2f → 终点 %.2f %.2f %.2f · 差 %.2fmm · 峰|ΔF| %.1fN%s"
          % (p0m[0], p0m[1], p0m[2], p1m[0], p1m[1], p1m[2],
             math.dist(p1m, tgt_mm), peak, "  ⛔看门狗" if tripped else ""), flush=True)
    os.makedirs("/sdk/logs", exist_ok=True)
    json.dump({"from": [round(v, 2) for v in p0m], "to": [round(v, 2) for v in p1m],
               "tgt": tgt_mm, "peak_dF": round(peak, 2), "tripped": tripped,
               "rpy": [round(v, 4) for v in rpy1]},
              open("/sdk/logs/goto_%s.json" % time.strftime("%H%M%S"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
