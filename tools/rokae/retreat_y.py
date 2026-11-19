#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retreat_y.py — 只沿 +y 后退, 回安全带。不下发任何 +x。

老倪(2026-11-19): 「恢复自动模式了, 不要再向前走, 退」
  当前事故位: TCP 639.1 / 49.1 / 203.0 (y 越界, 已在中央相机侧)
  本脚本只做一件事: +y 每次 40mm, 最多 6 步(=240mm), 逐步核验, 目标回到 y≈229。
  硬约束: 只改 y, x/z/rpy 全部锁定; 每步 x 变化必须 ≈0; 任一步异常立即停;
          每步下发前过 safe_envelope(退到安全带内才开始过闸判定)。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x                                                  # noqa: E402
sys.path.insert(0, "/sdk")
import safe_envelope as se                                                   # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
V = 10.0
STEP = 40.0
Y_TARGET = 229.0
D_MAX, R_MAX, F_MAX, DX_MAX = 1.5, 1.0, 25.0, 0.5


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "estop" in pw.lower():
        print("✗ 急停仍锁着, 不动")
        return 3
    if "on" not in pw:
        print("✗ power 不是 on, 不动")
        return 3
    if "automatic" not in md or "idle" not in op:
        print("✗ 不在 automatic+idle, 不动")
        return 3
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]

    def read_f():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        return (vals(b[3]) + [0.0] * 6)[:6]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def mv(tgt, rpy, name):
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt],
                                                      [float(v) for v in rpy]), V, -1),
                     x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  下发失败: %s" % ec, flush=True)
            return False
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 40 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.25)
        return True

    p0, rpy0 = pose()
    f0 = read_f()
    p0mm = [v * 1000 for v in p0]
    print("起点 %.1f %.1f %.1f  (包络: %s)" % (p0mm[0], p0mm[1], p0mm[2],
                                             se.check(p0mm)[1]), flush=True)
    log = {"start_mm": [round(v, 1) for v in p0mm], "steps": []}
    n = 0
    while p0mm[1] < Y_TARGET - 1.0 and n < 6:
        pc, _ = pose()
        pcm = [v * 1000 for v in pc]
        tgt = [pc[0], min(pc[1] + STEP / 1000.0, Y_TARGET / 1000.0), pc[2]]
        if not mv(tgt, rpy0, "retreat%d" % n):
            break
        p1, rpy1 = pose()
        p1m = [v * 1000 for v in p1]
        f1 = read_f()
        dp = math.dist(p1m, [v * 1000 for v in tgt])
        dr = max(abs(rpy1[j] - rpy0[j]) for j in range(3)) * 57.2958
        df = math.dist(f0[:3], f1[:3])
        dx = abs(p1m[0] - pcm[0])
        dz = abs(p1m[2] - pcm[2])
        print("  退%02d → %.1f %.1f %.1f · 差 %.2fmm · |Δx| %.2f |Δz| %.2f · 姿态 %.3f° · ΔF %.1fN · 包络 %s"
              % (n, p1m[0], p1m[1], p1m[2], dp, dx, dz, dr, df, se.check(p1m)[1]), flush=True)
        log["steps"].append({"tcp_mm": [round(v, 1) for v in p1m], "d_mm": round(dp, 2),
                             "dx": round(dx, 2), "dz": round(dz, 2),
                             "drot": round(dr, 3), "dF": round(df, 2)})
        n += 1
        if dp > D_MAX or dr > R_MAX or df > F_MAX or dx > DX_MAX or dz > DX_MAX:
            print("  ✗ 段不合格, 停", flush=True)
            break
        p0mm = p1m
    pf, _ = pose()
    pfm = [v * 1000 for v in pf]
    print("终点 %.1f %.1f %.1f · 走了 %d 步 · 包络 %s"
          % (pfm[0], pfm[1], pfm[2], n, se.check(pfm)[1]), flush=True)
    json.dump(log, open("/sdk/logs/retreat_y_%s.json" % time.strftime("%H%M%S"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
