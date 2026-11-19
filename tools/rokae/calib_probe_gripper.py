#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_probe_gripper.py — 走 B 第一步: 用「帧差」确认中央相机看得见夹爪, 并量出它在画面的哪里。

老倪(2026-11-19): 「走 B, 你自己看到你的夹抓轮廓边沿」
  不贴标记 ⇒ 用运动分割: 中央相机固定, 机械臂在两个位姿各拍一张, |A−B| 大的像素就是"动起来的夹爪"。
  连做两次移动 ⇒ 差集覆盖夹爪扫过的区域 ⇒ 说明可见 + 给出 bbox(供后面排网格点位)。

安全口径(与 sweep_y.py 同款, 硬编码):
  v ≤ 12mm/s · 单段 ≤60mm · 逐段核对 |Δ|<1.5mm / 姿态<1.0° / ΔF<25N · 异常即停并回原位
本脚本只做探测: 先 -x 退 60mm(离面板更远), 再 y ±50mm, 不进夹具区。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/sdk")
import xcoresdk_python as x                                                  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
OUT = "/sdk/calib_frames"
SNAP = "http://127.0.0.1:8812/snap.jpg"
VMAX = 12.0
SEG_MM = 60.0
D_MM_MAX = 1.5
ROT_MAX = 1.0
DF_MAX = 25.0


def vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def snap(tag: str) -> bool:
    os.makedirs(OUT, exist_ok=True)
    try:
        with urllib.request.urlopen(SNAP, timeout=4) as r:
            b = r.read()
        with open(os.path.join(OUT, "g_%s.jpg" % tag), "wb") as f:
            f.write(b)
        print("  snap %-8s %6d B" % (tag, len(b)), flush=True)
        return True
    except Exception as e:                                                   # noqa: BLE001
        print("  snap %-8s FAIL %s" % (tag, e), flush=True)
        return False


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: power=%s mode=%s op=%s" % (pw, md, op), flush=True)
    if "on" not in pw:
        print("拒绝: power 不是 on")
        return 3
    if "automatic" not in md:
        if "idle" not in op:
            print("拒绝: 不在 idle")
            return 3
        e2 = {}
        r.setOperateMode(x.OperateMode.automatic, e2)
        time.sleep(0.8)
        if "automatic" not in str(r.operateMode({})):
            print("拒绝: 切不到 automatic")
            return 3
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]

    def read_f():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        return (vals(b[3]) + [0.0] * 6)[:6]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def move_to(tgt, rpy, name):
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt],
                                                       [float(v) for v in rpy]), VMAX, -1),
                     x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  下发失败 %s: %s" % (name, ec), flush=True)
            return False
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 40 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.25)
        return True

    p0, rpy0 = pose()
    f0 = read_f()
    print("起点 TCP [%.1f %.1f %.1f]mm · rpy %s" % (
        p0[0] * 1000, p0[1] * 1000, p0[2] * 1000, [round(v, 3) for v in rpy0]), flush=True)
    snap("p0")

    seq = [("xm", [-SEG_MM / 1000.0, 0, 0]),
           ("yp", [0, 50 / 1000.0, 0]),
           ("ym", [0, -100 / 1000.0, 0])]
    code = 0
    for tag, d in seq:
        tgt = [p0[0] + d[0], p0[1] + d[1], p0[2] + d[2]]
        if not move_to(tgt, rpy0, tag):
            code = 4
            break
        p1, rpy1 = pose()
        f1 = read_f()
        dp = math.dist([v * 1000 for v in p1], [v * 1000 for v in tgt])
        dr = max(abs(rpy1[j] - rpy0[j]) for j in range(3)) * 57.2958
        df = math.dist(f0[:3], f1[:3])
        print("  %-3s → [%.1f %.1f %.1f] 差 %.2fmm · 姿态变 %.3f° · ΔF %.1fN" % (
            tag, p1[0] * 1000, p1[1] * 1000, p1[2] * 1000, dp, dr, df), flush=True)
        if dp > D_MM_MAX or dr > ROT_MAX or df > DF_MAX:
            print("停: 段不合格", flush=True)
            code = 5
            break
        snap(tag)

    move_to(p0, rpy0, "home")
    pb, _ = pose()
    print("回起点 [%.1f %.1f %.1f]" % (pb[0] * 1000, pb[1] * 1000, pb[2] * 1000), flush=True)
    json.dump({"pose0_mm": [round(v * 1000, 2) for v in p0], "rpy": rpy0,
               "frames_dir": OUT, "code": code},
              open(os.path.join(OUT, "probe.json"), "w"), indent=1)
    return code


if __name__ == "__main__":
    sys.exit(main())
