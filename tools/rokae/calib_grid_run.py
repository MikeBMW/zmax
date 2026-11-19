#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_grid_run.py — B 路线正式采集: 先从低处解出来, 再排网格, 每站同时抓两路相机。

老倪(2026-11-19): 「你自己动吧, 我看着」
  起点实测 TCP 639.1/229.1/203.0 · 关节 32.1/23.3/−146.7/43.0/64.8/112.6° (肘压到底、腕拧着)
  ⇒ 必须先 +z 抬升把关节从极限区解出来, 再 −x 后撤, 最后在远端排网格(不动 z 太多, 保证二维码在视野)。

阶段(每步都核验, 越界即停并回本阶段起点):
  S0 切 automatic (不动机器)
  S1 +z 30mm ×2 = +60mm
  S2 −x 40mm ×2 = −80mm
  S3 12 位姿网格: y ∈ {−40,0,+40} × x ∈ {0,−40} × z 相对 {0,−20}
  S4 回 S2 结束位 (采集位姿的"零点")

每站落盘: arm_<i>.jpg (臂相机 1280×720) + cen_<i>.jpg (中央相机 640×480) + poses.jsonl(含 TCP/rpy/时间)
安全: 12mm/s · 单段 ≤60mm · |Δ|<1.5mm · 姿态<1.0° · ΔF<25N
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
ARM = "http://192.168.23.66:8792/frame.jpg"
CEN = "http://127.0.0.1:8812/snap.jpg"
V = 12.0
D_MAX, R_MAX, F_MAX = 1.5, 1.0, 25.0


def vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def grab(url: str, path: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            b = r.read()
        with open(path, "wb") as f:
            f.write(b)
        return len(b) > 3000
    except Exception as e:                                                   # noqa: BLE001
        print("    grab fail %s: %s" % (os.path.basename(path), e), flush=True)
        return False


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    r = x.xMateRobot()
    r.connectToRobot(IP)
    print("自检: %s %s %s" % (r.powerState({}), r.operateMode({}), r.operationState({})), flush=True)
    if "on" not in str(r.powerState({})):
        print("拒绝: power 不是 on")
        return 3
    if "automatic" not in str(r.operateMode({})):
        if "idle" not in str(r.operationState({})):
            print("拒绝: 非 idle, 不切模式")
            return 3
        ec = {}
        r.setOperateMode(x.OperateMode.automatic, ec)
        time.sleep(1.0)
        m = str(r.operateMode({}))
        print("S0 切模式 → %s %s" % (m, ec), flush=True)
        if "automatic" not in m:
            print("✗ 切不到 automatic, 中止")
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
                                                       [float(v) for v in rpy]), V, -1),
                     x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("    下发失败 %s: %s" % (name, ec), flush=True)
            return False
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 40 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.25)
        return True

    p0, rpy0 = pose()
    f0 = read_f()
    print("起点 TCP %.1f %.1f %.1f mm" % (p0[0] * 1000, p0[1] * 1000, p0[2] * 1000), flush=True)
    log = {"start_tcp_mm": [round(v * 1000, 2) for v in p0], "rpy": rpy0, "steps": [], "poses": []}

    def step(dx, dy, dz, tag):
        """相对上一位置移动 (mm), 核验后返回新位姿; 失败返回 None。"""
        pc, _ = pose()
        tgt = [pc[0] + dx / 1000.0, pc[1] + dy / 1000.0, pc[2] + dz / 1000.0]
        if not move_to(tgt, rpy0, tag):
            return None
        p1, rpy1 = pose()
        f1 = read_f()
        dp = math.dist([v * 1000 for v in p1], [v * 1000 for v in tgt])
        dr = max(abs(rpy1[j] - rpy0[j]) for j in range(3)) * 57.2958
        df = math.dist(f0[:3], f1[:3])
        rec = {"tag": tag, "tcp_mm": [round(v * 1000, 1) for v in p1],
               "d_mm": round(dp, 2), "d_rot_deg": round(dr, 3), "dF": round(df, 1)}
        log["steps"].append(rec)
        print("  %-8s → %.1f %.1f %.1f · 差 %.2fmm · 姿态 %.3f° · ΔF %.1fN"
              % (tag, p1[0] * 1000, p1[1] * 1000, p1[2] * 1000, dp, dr, df), flush=True)
        if dp > D_MAX or dr > R_MAX or df > F_MAX:
            print("  ✗ 段不合格, 停", flush=True)
            return None
        return p1

    # S1 抬升
    for i in range(2):
        if step(0, 0, 30, "lift%d" % (i + 1)) is None:
            return 5
    # S2 后撤
    for i in range(2):
        if step(-40, 0, 0, "back%d" % (i + 1)) is None:
            return 5
    base, _ = pose()
    print("采集零点 %.1f %.1f %.1f" % (base[0] * 1000, base[1] * 1000, base[2] * 1000), flush=True)

    # S3 网格 (相对零点)
    grid = [(dy, dx, dz) for dz in (0, -20) for dx in (0, -40) for dy in (-40, 0, 40)]
    k = 0
    fails = 0
    for dy, dx, dz in grid:
        tgt = [base[0] + dx / 1000.0, base[1] + dy / 1000.0, base[2] + dz / 1000.0]
        if not move_to(tgt, rpy0, "g%02d" % k):
            fails += 1
            k += 1
            continue
        p1, rpy1 = pose()
        f1 = read_f()
        dp = math.dist([v * 1000 for v in p1], [v * 1000 for v in tgt])
        dr = max(abs(rpy1[j] - rpy0[j]) for j in range(3)) * 57.2958
        df = math.dist(f0[:3], f1[:3])
        ok_a = grab(ARM, os.path.join(OUT, "arm_%02d.jpg" % k))
        ok_c = grab(CEN, os.path.join(OUT, "cen_%02d.jpg" % k))
        rec = {"i": k, "tcp_mm": [round(v * 1000, 1) for v in p1], "rpy": [round(v, 4) for v in rpy1],
               "d_mm": round(dp, 2), "d_rot_deg": round(dr, 3), "dF": round(df, 1),
               "arm_ok": ok_a, "cen_ok": ok_c, "t": time.strftime("%F %T")}
        log["poses"].append(rec)
        print("  站%02d %8.1f %8.1f %8.1f · 差 %.2fmm · 姿态 %.2f° · ΔF %4.1fN · 臂%s 中%s"
              % (k, p1[0] * 1000, p1[1] * 1000, p1[2] * 1000, dp, dr, df,
                 "✓" if ok_a else "✗", "✓" if ok_c else "✗"), flush=True)
        if dp > D_MAX or dr > R_MAX or df > F_MAX:
            print("  ✗ 站不合格, 停采集", flush=True)
            fails += 1
            break
        k += 1

    move_to(base, rpy0, "home")
    pb, _ = pose()
    print("回采集零点 %.1f %.1f %.1f · 成功站 %d / %d · 失败 %d"
          % (pb[0] * 1000, pb[1] * 1000, pb[2] * 1000, len(log["poses"]), len(grid), fails), flush=True)
    json.dump(log, open(os.path.join(OUT, "grid_log.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if fails == 0 else 6


if __name__ == "__main__":
    sys.exit(main())
