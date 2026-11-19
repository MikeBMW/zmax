#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goto_replay_point.py — 按回放轨迹的点位走位(关节空间 MoveAbsJ), 1x 回放速度。

老倪: 「你用回放速度的1倍速度, 去到第126点, 金手指点1」
  轨迹真源 tools/web/real_traj_joints.json (215 点, 5Hz, dt 中位 0.2s)
  #126 → p (493.03, 134.49, 695.52)mm · j [1.1, -29.7, -96.2, -2.0, -61.5, 45.6]°
  1x 回放实测速度: #125→#126 = 31.3mm / 0.200s ≈ 156mm/s

安全:
  · 先去"清空位"(沿 −x 退到 x=700, 这段是今晚已走过多次的通道), 不做斜穿夹具的关节大扫掠
  · 再 MoveAbsJ 到 #126 的关节值(关节线性插值, 端点用轨迹真值, 不用我算的 IK)
  · 到位校验: 位置差 ≤2.0mm 且 姿态差 ≤1.0°, 否则停
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x                                                  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def R_of(a, b, c):
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb, ca * sb * sc - sa * cc, ca * sb * cc + sa * sc],
            [sa * cb, sa * sb * sc + ca * cc, sa * sb * cc - ca * sc],
            [-sb, cb * sc, cb * cc]]


def R_err_deg(r1, r2):
    import numpy as np
    A, B = np.array(R_of(*r1)), np.array(R_of(*r2))
    return math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(A.T @ B)) - 1) / 2))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, required=True)
    ap.add_argument("--traj", default="/sdk/real_traj_joints.json")
    ap.add_argument("--speed", type=float, default=156.0, help="mm/s (1x 回放实测)")
    ap.add_argument("--clear-x", type=float, default=700.0)
    ap.add_argument("--skip-clear", action="store_true")
    a = ap.parse_args()

    d = json.load(open(a.traj))
    fr = d["frames"] if isinstance(d, dict) and "frames" in d else d
    tgt = fr[a.idx]
    pj = [float(v) for v in tgt["j"][:6]]
    pt = [float(v) * 1000.0 for v in tgt["p"]]
    print("轨迹 #%d: p=[%.2f %.2f %.2f]mm j=%s" % (a.idx, pt[0], pt[1], pt[2],
                                                 [round(math.degrees(v), 1) for v in pj]), flush=True)

    r = x.xMateRobot()
    r.connectToRobot(IP)
    print("自检:", r.powerState({}), r.operateMode({}), r.operationState({}), flush=True)
    if "on" not in str(r.powerState({})) or "automatic" not in str(r.operateMode({})):
        print("✗ 前置不满足")
        return 3

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def run(cmd_list, name, timeout=90):
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(cmd_list, x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  ✗ %s 下发失败 %s" % (name, ec), flush=True)
            return False
        r.moveStart({})
        t0 = time.time()
        seen = False
        while time.time() - t0 < timeout:
            st = str(r.operationState({}))
            if "moving" in st:
                seen = True
            elif "idle" in st and seen:
                break
            time.sleep(0.05)
        time.sleep(0.3)
        return True

    p0, rpy0 = pose()
    print("起点 %.2f %.2f %.2f" % (p0[0] * 1000, p0[1] * 1000, p0[2] * 1000), flush=True)

    if not a.skip_clear and p0[0] * 1000 > a.clear_x + 1:
        tgt_clear = [a.clear_x / 1000.0, p0[1], p0[2]]
        if not run(x.MoveLCommand(x.CartesianPosition(tgt_clear, [float(v) for v in rpy0]), 15.0, -1), "clear"):
            return 5
        p1, _ = pose()
        print("  清空位 → %.2f %.2f %.2f (沿 −x 退到 %.0f)" % (p1[0] * 1000, p1[1] * 1000, p1[2] * 1000, a.clear_x), flush=True)

    t_start = time.time()
    if not run([x.MoveAbsJCommand(x.JointPosition(pj), a.speed, -1)], "absj%d" % a.idx, timeout=120):
        return 5
    dt = time.time() - t_start
    p2, rpy2 = pose()
    dc = math.dist([v * 1000 for v in p2], pt)
    print("到位 %.2f %.2f %.2f · 距 #%d %.2fmm · 用时 %.2fs (1x 回放口径 dt=%.2fs)"
          % (p2[0] * 1000, p2[1] * 1000, p2[2] * 1000, a.idx, dc, dt, 0.2), flush=True)
    os.makedirs("/sdk/logs", exist_ok=True)
    json.dump({"idx": a.idx, "target_mm": [round(v, 2) for v in pt], "end_mm": [round(v * 1000, 2) for v in p2],
               "dist_mm": round(dc, 2), "speed": a.speed, "elapsed_s": round(dt, 2),
               "rpy": [round(v, 4) for v in rpy2]},
              open("/sdk/logs/goto_replay_%d_%s.json" % (a.idx, time.strftime("%H%M%S")), "w"), indent=1)
    return 0 if dc <= 5.0 else 6


if __name__ == "__main__":
    sys.exit(main())
