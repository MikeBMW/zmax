#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_axis_safe.py — 安全带内摸清"臂怎么动 ⇒ 中央画面里模块头怎么动"。

老倪: 「只要不碰撞就行, 你继续」
现场约束(都是硬的):
  · 每一站下发前过 safe_envelope(check + check_path), 不过就拒绝
  · x 不超过 700; y 保持 [150,330]; z 保持 [130,330]
  · 全部单段 40mm, 10mm/s, 逐步核 |Δ|<1.5mm / 姿态<1° / ΔF<25N
目的: 得到中央相机的像素雅可比(每 mm 走多少 px), 才知道把模块头从画面左缘
      挪到中间该往哪边走 —— 上次就是"没这个映射"朝着相机撞过去的。
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
import safe_envelope as se                                                   # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
V = 10.0
OUT = "/sdk/axis_probe"
CEN = "http://127.0.0.1:8812/snap.jpg"
D_MAX, R_MAX, F_MAX = 1.5, 1.0, 25.0

# (标签, 目标 base 点 mm) —— 起点 639.1 / 229.0 / 203.0
SEQ = [
    ("base",   [639.1, 229.0, 203.0]),
    ("z+40",   [639.1, 229.0, 243.0]),
    ("base2",  [639.1, 229.0, 203.0]),
    ("z-40",   [639.1, 229.0, 163.0]),
    ("base3",  [639.1, 229.0, 203.0]),
    ("y-40",   [639.1, 189.0, 203.0]),
    ("y+40",   [639.1, 269.0, 203.0]),
    ("base4",  [639.1, 229.0, 203.0]),
    ("x+40",   [679.1, 229.0, 203.0]),
    ("base5",  [639.1, 229.0, 203.0]),
]


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足, 不动")
        return 3
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]

    def read_f():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        return (vals(b[3]) + [0.0] * 6)[:6]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def grab(path):
        try:
            with urllib.request.urlopen(CEN, timeout=5) as rq:
                data = rq.read()
            open(path, "wb").write(data)
            return len(data) > 2000
        except Exception as e:                                                # noqa: BLE001
            print("  抓图失败 %s" % e, flush=True)
            return False

    def mv(tgt_mm, rpy, name):
        ok, why = se.check(tgt_mm, name)
        if not ok:
            print("  ✗ 包络拒绝: %s" % why, flush=True)
            return False
        pc, _ = pose()
        pcm = [v * 1000 for v in pc]
        ok2, why2 = se.check_path(pcm, tgt_mm, 8)
        if not ok2:
            print("  ✗ 路径拒绝: %s" % why2, flush=True)
            return False
        tgt = [v / 1000.0 for v in tgt_mm]
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt],
                                                      [float(v) for v in rpy]), V, -1),
                     x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  ✗ 下发失败 %s" % ec, flush=True)
            return False
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 40 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.25)
        return True

    p0, rpy0 = pose()
    f0 = read_f()
    print("起点 %.1f %.1f %.1f · rpy %s" % (p0[0] * 1000, p0[1] * 1000, p0[2] * 1000,
                                          [round(v, 4) for v in rpy0]), flush=True)
    log = {"rpy": [round(v, 4) for v in rpy0], "frames": []}
    for tag, tgt_mm in SEQ:
        pc, _ = pose()
        pcm = [v * 1000 for v in pc]
        if math.dist(pcm, tgt_mm) < 0.5:
            if not grab(os.path.join(OUT, "%s.jpg" % tag)):
                return 6
            print("  %-6s 已在位 · 抓图 ✓" % tag, flush=True)
            log["frames"].append({"tag": tag, "tcp_mm": [round(v, 1) for v in pcm]})
            continue
        if not mv(tgt_mm, rpy0, tag):
            print("  ✗ %s 放弃" % tag, flush=True)
            break
        p1, rpy1 = pose()
        p1m = [v * 1000 for v in p1]
        f1 = read_f()
        dp = math.dist(p1m, tgt_mm)
        dr = max(abs(rpy1[j] - rpy0[j]) for j in range(3)) * 57.2958
        df = math.dist(f0[:3], f1[:3])
        okg = grab(os.path.join(OUT, "%s.jpg" % tag))
        print("  %-6s → %.1f %.1f %.1f · 差 %.2fmm · 姿态 %.3f° · ΔF %.1fN · 图%s"
              % (tag, p1m[0], p1m[1], p1m[2], dp, dr, df, "✓" if okg else "✗"), flush=True)
        log["frames"].append({"tag": tag, "tcp_mm": [round(v, 1) for v in p1m],
                              "d_mm": round(dp, 2), "drot": round(dr, 3), "dF": round(df, 2)})
        if dp > D_MAX or dr > R_MAX or df > F_MAX:
            print("  ✗ 段不合格, 停", flush=True)
            break
    json.dump(log, open(os.path.join(OUT, "axis_probe.json"), "w"), ensure_ascii=False, indent=1)
    pf, _ = pose()
    print("结束位 %.1f %.1f %.1f" % (pf[0] * 1000, pf[1] * 1000, pf[2] * 1000), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
