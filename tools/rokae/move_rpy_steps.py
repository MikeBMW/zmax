#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move_rpy_steps.py — 原地分段改姿态 (位置不动), 每步 ≤ ZMAX_RPY_STEP。

为什么需要: 大角度一次改会被控制器按奇异区拒(50113)并**假报到位**
  实测 2026-11-22: 目标 rpy 2.961,-1.49,0.205 实际停在 2.061,-1.164,0.948,
  Δr 0.9003rad 而"姿态实际变化 0.0000rad" (move_pose6d 报 到位 ✗)。
  ⇒ 按 ~5° 一段走, 每段都读真值, 某段跟不上就停 (不硬冲)。

环境变量:
  ZMAX_RPY_TARGET="r,p,y"   rad   要去的姿态 (必填)
  ZMAX_RPY_STEP             rad   单步最大角, 默认 0.0873 (=5°)
  ZMAX_SEG_SPEED            mm/s  默认 10
  ZMAX_POSE_WAIT            s     每段等待上限, 默认 60
  ZMAX_RPY_TOL_RAD          rad   每段判到位, 默认 0.02
"""
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
TGT = [float(v) for v in (os.environ.get("ZMAX_RPY_TARGET") or "").split(",")]
STEP = float(os.environ.get("ZMAX_RPY_STEP") or 0.0873)
SPEED = float(os.environ.get("ZMAX_SEG_SPEED") or 10)
WAIT = float(os.environ.get("ZMAX_POSE_WAIT") or 60)
TOL = float(os.environ.get("ZMAX_RPY_TOL_RAD") or 0.02)
ABORT = 0.06                                   # 单段偏差 >3.4° ⇒ 认输, 不硬冲
if len(TGT) != 3:
    print('✗ 需要 ZMAX_RPY_TARGET="r,p,y" (rad)')
    sys.exit(2)

r = x.xMateRobot()
r.connectToRobot(IP)


def pose():
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    return ([float(v) * 1000.0 for v in cp.trans], [float(v) for v in cp.rpy])


pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
print("自检:", pw, md, op, flush=True)
if "on" not in pw or "automatic" not in md or "idle" not in op:
    print("✗ 前置不满足(on/automatic/idle), 不动")
    sys.exit(3)

p0, a0 = pose()
print("起点 %.1f,%.1f,%.1f  rpy %.4f,%.4f,%.4f" % (*p0, *a0), flush=True)
delta = [TGT[i] - a0[i] for i in range(3)]
span = max(abs(v) for v in delta)
n = max(1, int(math.ceil(span / STEP)))
print("要转 %.1f° ⇒ 分 %d 段, 每段 ≤%.1f°" % (span * 180 / math.pi, n, STEP * 180 / math.pi), flush=True)

r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
r.moveReset({})

for k in range(1, n + 1):
    f = k / float(n)
    a = [a0[i] + delta[i] * f for i in range(3)]
    r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in p0], a), SPEED, -1),
                 x.PyString("RPY%02d" % k), {})
    r.moveStart({})
    t0 = time.time()
    ac = a0
    while time.time() - t0 < WAIT:
        time.sleep(0.25)
        _, ac = pose()
        if max(abs(ac[i] - a[i]) for i in range(3)) < TOL:
            break
    _, ac = pose()
    err = max(abs(ac[i] - a[i]) for i in range(3))
    print("段 %d/%d 目标 rpy %.4f,%.4f,%.4f · 实际 %.4f,%.4f,%.4f · Δ%.4frad %s"
          % (k, n, *a, *ac, err, "✓" if err < TOL else "✗"), flush=True)
    if err > ABORT:
        print("✗ 段 %d 没跟上(>%.1f°), 停 —— 不硬冲" % (k, ABORT * 180 / math.pi))
        sys.exit(4)

p1, a1 = pose()
err = max(abs(a1[i] - TGT[i]) for i in range(3))
print("终点 %.1f,%.1f,%.1f  rpy %.4f,%.4f,%.4f · 与目标差 %.4frad(%.1f°) %s"
      % (*p1, *a1, err, err * 180 / math.pi, "✓" if err < 0.03 else "✗"), flush=True)
sys.exit(0 if err < 0.03 else 5)
