#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move_view.py — 单点 MoveJ 到观察位(不碰工件)。

用途: 抬到料盘上方俯视, 让相机看清槽位里有/没有光模块。
环境变量: ZMAX_VIEW_XYZ="x,y,z" (mm)  ZMAX_VIEW_RPY="r,y,p" (rad)  ZMAX_SEG_SPEED
"""
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = "192.168.23.160"
xyz = [float(v) for v in (os.environ.get("ZMAX_VIEW_XYZ") or "650,454,360").split(",")]
rpy = [float(v) for v in (os.environ.get("ZMAX_VIEW_RPY") or "2.9607,-1.4898,0.2052").split(",")]
SPEED = float(os.environ.get("ZMAX_SEG_SPEED") or 40)

r = x.xMateRobot()
r.connectToRobot(IP)
pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
print("自检:", pw, md, op, flush=True)
if "on" not in pw or "automatic" not in md or "idle" not in op:
    print("✗ 前置不满足, 不动")
    sys.exit(3)

cp = r.cartPosture(x.CoordinateType.endInRef, {})
p0 = [float(v) * 1000.0 for v in cp.trans]
print("当前 %.1f,%.1f,%.1f → 目标 %.1f,%.1f,%.1f" % (*p0, *xyz), flush=True)
if not (200 <= xyz[0] <= 900 and -560 <= xyz[1] <= 620 and 95 <= xyz[2] <= 780):
    print("✗ 目标超出安全包络")
    sys.exit(2)

r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
r.moveReset({})
ec = {}
r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in xyz], rpy), SPEED, -1),
             x.PyString("VIEW"), ec)
if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
    print("✗ 下发被拒", ec)
    sys.exit(4)
for wait in (0.0, 0.5, 1.0, 2.0, 4.0):
    if wait:
        time.sleep(wait)
        r.moveReset({})
        r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in xyz], rpy), SPEED, -1),
                     x.PyString("VIEW"), {})
    e2 = {}
    r.moveStart(e2)
    if (e2.get("ec", 0) if isinstance(e2, dict) else 0) in (0, None):
        break
    print("  ⋯ 退避 %.1fs: %s" % (wait, e2), flush=True)
else:
    print("✗ 起不来, 停")
    sys.exit(5)

t0 = time.time()
while time.time() - t0 < 180:
    time.sleep(0.2)
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    # 判到位用"最大轴偏差", 不用三轴平均: 平均会把"z 还差 5mm"这种情况判成到位
    # 容差要小于本次位移量, 否则 1mm 级微调会被立刻判"已到位"
    if max(abs(float(a) * 1000.0 - b) for a, b in zip(cp.trans, xyz)) < 0.5:
        break
cp = r.cartPosture(x.CoordinateType.endInRef, {})
p1 = [float(v) * 1000.0 for v in cp.trans]
print("到位 %.1f,%.1f,%.1f · 偏差 %.1fmm" % (*p1, sum(abs(a - b) for a, b in zip(p1, xyz)) / 3.0), flush=True)
