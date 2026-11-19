#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""approach_port.py — 从观察位沿插入轴推到孔口前 2mm, 只接近不插入。

老倪: 「你能插入么? 你有真正插入的数据, 能用李萨如算法和中央相机的视差引导插入么?」
本脚本只做"把人送到口前"这一段(零接触意图), 依据 `force-controlled-insertion` 技能:
  · 接触/近接触段一律 **位置模式慢推 + 被动看门狗**, 不进力控模式(硬接触必 41451 下电)
  · 运动中 20ms 采样一次力, |ΔF|>25N 立刻 stop + moveReset + 沿轴退 3mm 卸力
  · 力先 5 帧中值滤波 + 剔除 |F|>200N 尖峰
  · 每段 ≤10mm, 越接近口越慢(1→0.8mm/s)
分段(从 726.0 → 759.7, 口 761.75, 留 2mm):
    736.0 / 746.0 / 752.0 / 756.5 / 759.7
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x                                                  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
RPY_T = [-2.9484, -1.5163, -0.1782]
MOUTH_X = 761.75
F_STOP = 25.0
SEG = [(754.6, 0.5, "segA"), (756.6, 0.5, "segB"),
       (758.4, 0.5, "segC"), (759.7, 0.5, "segD")]


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足")
        return 3
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]
    hist = []

    def f_raw():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        return (vals(b[3]) + [0.0] * 6)[:3]

    def f_filt():
        v = f_raw()
        if max(abs(t) for t in v) > 200.0:                       # 尖峰剔除
            return None
        hist.append(v)
        if len(hist) > 5:
            hist.pop(0)
        return [statistics.median([h[i] for h in hist]) for i in range(3)]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def unload(mm=3.0):
        p, _ = pose()
        tgt = [p[0] - mm / 1000.0, p[1], p[2]]
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition(tgt, [float(v) for v in RPY_T]), 2.0, -1),
                     x.PyString("unload"), ec)
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 20 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.25)
        p2, _ = pose()
        return [v * 1000 for v in p2]

    p0, rpy0 = pose()
    p0m = [v * 1000 for v in p0]
    for _ in range(6):
        f_filt()
    base = f_filt() or f_raw()
    print("起点 %.1f %.1f %.1f · 力基线 |F|=%.1fN" % (p0m[0], p0m[1], p0m[2],
                                                  math.dist(base[:3], [0, 0, 0])), flush=True)
    log = {"start_mm": [round(v, 1) for v in p0m], "base_f": [round(v, 2) for v in base], "seg": []}
    for tx, spd, name in SEG:
        p, rp = pose()
        if tx > 759.75:
            print("  ✗ 目标 x=%.2f 超过口前 2mm 限制, 拒绝" % tx, flush=True)
            break
        tgt = [tx / 1000.0, p[1], p[2]]
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition(tgt, [float(v) for v in RPY_T]), spd, -1),
                     x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  ✗ %s 下发失败 %s" % (name, ec), flush=True)
            return 5
        t0 = time.time()
        r.moveStart({})
        peak = 0.0
        tripped = False
        seen_moving = False
        while time.time() - t0 < 60:
            f = f_filt()
            if f is not None:
                d = math.dist(f[:3], base[:3])
                peak = max(peak, d)
                if d > F_STOP:
                    tripped = True
                    r.stop({})
                    r.moveReset({})
                    break
            st = str(r.operationState({}))
            if "moving" in st:
                seen_moving = True
            elif "idle" in st and seen_moving:      # 只有真的动过才认 idle, 防竞态早退
                break
            time.sleep(0.02)
        p1, rp1 = pose()
        p1m = [v * 1000 for v in p1]
        f = f_filt() or f_raw()
        dnow = math.dist(f[:3], base[:3])
        print("  %-5s → %7.1f (%5.2fmm/s) · 位移 %6.2fmm · 峰值|ΔF| %5.1fN · 现|ΔF| %4.1fN · 距口 %5.2fmm%s"
              % (name, p1m[0], spd, p1m[0] - p0m[0], peak, dnow, MOUTH_X - p1m[0],
                 "  ⛔看门狗" if tripped else ""), flush=True)
        log["seg"].append({"name": name, "x": round(p1m[0], 2), "dx": round(p1m[0] - p0m[0], 2),
                           "peak_dF": round(peak, 2), "dF_now": round(dnow, 2), "tripped": tripped})
        if tripped:
            p2 = unload(3.0)
            print("  ⛔ 触发看门狗 ⇒ 已沿 −x 退 3mm 卸力, 现在 x=%.1f · 停手" % p2[0], flush=True)
            log["unload_x"] = round(p2[0], 2)
            break
        if abs((p1m[0] - p0m[0]) - (tx - p0m[0])) > 1.5:
            print("  ✗ 位移不足, 停", flush=True)
            break
        p0m = p1m
    pf, _ = pose()
    pfm = [v * 1000 for v in pf]
    print("到位 %.1f %.1f %.1f · 距口 %.2fmm  (未插入, 停在口前)" % (pfm[0], pfm[1], pfm[2], MOUTH_X - pfm[0]), flush=True)
    os.makedirs("/sdk/logs", exist_ok=True)
    json.dump(log, open("/sdk/logs/approach_%s.json" % time.strftime("%H%M%S"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
