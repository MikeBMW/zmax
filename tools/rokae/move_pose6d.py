#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move_pose6d.py — 单点 MoveJ 到 6D 位姿(位置+姿态都要判到位)。

为什么不用 move_view.py: 它只判位置(|Δp|<0.5mm)。**纯姿态调整**时位置本来就相等,
  它当场判"到位"然后容器退出 ⇒ 旋转根本没走完, 实测 rpy 一点没变(2026-11-22)。

环境变量:
  ZMAX_VIEW_XYZ="x,y,z"   mm      (默认 648.8,407.0,175.0)
  ZMAX_VIEW_RPY="r,p,y"   rad     (默认 2.961,-1.49,0.205 = 真机录制里料盘抓取位姿)
  ZMAX_SEG_SPEED          mm/s    (默认 8)
  ZMAX_POSE_TOL_MM        位置容差, 默认 0.6
  ZMAX_POSE_TOL_RAD       姿态容差, 默认 0.02 (=1.15°)
"""
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
xyz = [float(v) for v in (os.environ.get("ZMAX_VIEW_XYZ") or "648.8,407.0,175.0").split(",")]
rpy = [float(v) for v in (os.environ.get("ZMAX_VIEW_RPY") or "2.961,-1.49,0.205").split(",")]
SPEED = float(os.environ.get("ZMAX_SEG_SPEED") or 8)
TOLP = float(os.environ.get("ZMAX_POSE_TOL_MM") or 0.6)
TOLR = float(os.environ.get("ZMAX_POSE_TOL_RAD") or 0.02)

r = x.xMateRobot()
r.connectToRobot(IP)
pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
print("自检:", pw, md, op, flush=True)
if "on" not in pw or "automatic" not in md or "idle" not in op:
    print("✗ 前置不满足, 不动")
    sys.exit(3)

if not (200 <= xyz[0] <= 900 and -560 <= xyz[1] <= 620 and 95 <= xyz[2] <= 780):
    print("✗ 目标超出安全包络")
    sys.exit(2)


def pose():
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    return ([float(v) * 1000.0 for v in cp.trans], [float(v) for v in cp.rpy])


p0, r0 = pose()
print("当前 %.1f,%.1f,%.1f  rpy %.3f,%.3f,%.3f" % (*p0, *r0), flush=True)
print("目标 %.1f,%.1f,%.1f  rpy %.3f,%.3f,%.3f" % (*xyz, *rpy), flush=True)

r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
r.moveReset({})
r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in xyz], rpy), SPEED, -1),
             x.PyString("POSE6D"), {})
r.moveStart({})

t0 = time.time()
ok = False
last = None
WAIT = float(os.environ.get("ZMAX_POSE_WAIT") or 240)
while time.time() - t0 < WAIT:
    time.sleep(0.2)
    p, rr = pose()
    dp = max(abs(a - b) for a, b in zip(p, xyz))
    dr = max(abs(a - b) for a, b in zip(rr, rpy))
    last = (p, rr, dp, dr)
    if dp < TOLP and dr < TOLR:
        ok = True
        break
    if time.time() - t0 > 6 and dp > 900:
        break

p, rr = pose()
dp = max(abs(a - b) for a, b in zip(p, xyz))
dr = max(abs(a - b) for a, b in zip(rr, rpy))
moved_r = max(abs(a - b) for a, b in zip(rr, r0))
print("到位 %s · %.1f,%.1f,%.1f rpy %.3f,%.3f,%.3f · Δp %.2fmm Δr %.4frad · 姿态实际变化 %.4frad"
      % ("✓" if ok else "✗", *p, *rr, dp, dr, moved_r), flush=True)
sys.exit(0 if ok else 6)
