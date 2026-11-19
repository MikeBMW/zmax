#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goto_port.py — 把末端送到插口附近的观察位（不插、不进）, 全程逐步核验。

老倪: 「你先把自己送到插口附近, 你能搞么?」
目标位(沿成功模板的轴线, 但停在离插口 35mm 的观察位, 不进插口):
    入点真值   (761.75, 228.07, 190.36)  rpy(-2.9484, -1.5163, -0.1782)
    观察位     (726.0,  228.1,  190.4 )  同 rpy      ← 距插口 35.7mm, 只在外面
路径(全部先在高处转身, 再下降, 最后短距接近):
    S0 抬到 z=245      (在原 y/x 上抬, 先脱离低处)
    S1 → (690, 232, 245) 横移/后撤, 仍在高处
    S2 → (700, 228.1, 245) 对准插口轴线正上方
    S3 原地转身 → 目标 rpy   (高处转身, 离夹具 58mm, 腕部旋转不扫夹具)
    S4 → (700, 228.1, 190.4) 垂直下降
    S5 → (726, 228.1, 190.4) 沿 +x 短距接近(32mm)
每步核: |Δ|<1.5mm / 姿态差<1.0° / ΔF<25N / 过 safe_envelope + 路径插值
任一步异常: 立即停, 不再继续后续步。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x                                                  # noqa: E402
import safe_envelope as se                                                   # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
RPY_T = [-2.9484, -1.5163, -0.1782]
D_MAX, R_MAX, F_MAX = 1.5, 1.0, 25.0


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def R_of(a, b, c):
    """控制器 rpy = (yaw, pitch, roll) → R = Rz(a)Ry(b)Rx(c)"""
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cc, sc = math.cos(c), math.sin(c)
    return [[ca * cb, ca * sb * sc - sa * cc, ca * sb * cc + sa * sc],
            [sa * cb, sa * sb * sc + ca * cc, sa * sb * cc - ca * sc],
            [-sb, cb * sc, cb * cc]]


def R_err_deg(r1, r2):
    import numpy as np
    A, B = np.array(R_of(*r1)), np.array(R_of(*r2))
    d = np.clip((np.trace(A.T @ B) - 1) / 2.0, -1.0, 1.0)
    return math.degrees(math.acos(d))


def main() -> int:
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

    def mv(tgt_mm, rpy, name, speed):
        ok, why = se.check(tgt_mm, name)
        if not ok:
            print("  ✗ 包络拒绝: %s" % why, flush=True)
            return False
        pc, _ = pose()
        ok2, why2 = se.check_path([v * 1000 for v in pc], tgt_mm, 12)
        if not ok2:
            print("  ✗ 路径拒绝: %s" % why2, flush=True)
            return False
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([v / 1000.0 for v in tgt_mm],
                                                      [float(v) for v in rpy]), speed, -1),
                     x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  ✗ 下发失败 %s" % ec, flush=True)
            return False
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 60 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.3)
        return True

    p0, rpy0 = pose()
    f0 = read_f()
    p0mm = [v * 1000 for v in p0]
    print("起点 %.1f %.1f %.1f · rpy %s" % (p0mm[0], p0mm[1], p0mm[2],
                                          [round(v, 4) for v in rpy0]), flush=True)
    log = {"start_mm": [round(v, 1) for v in p0mm], "rpy0": [round(v, 4) for v in rpy0], "steps": []}
    z_hi = max(245.0, p0mm[2])
    steps = [
        ("S0 抬升",   [p0mm[0], p0mm[1], z_hi],  rpy0, 25.0),
        ("S1 横移",   [690.0, 232.0, z_hi],      rpy0, 25.0),
        ("S2 对准",   [690.0, 228.1, z_hi],      rpy0, 15.0),
        ("S3 转身",   [690.0, 228.1, z_hi],      RPY_T, 10.0),
        ("S4 下降",   [690.0, 228.1, 190.4],     RPY_T, 10.0),
        ("S5 接近",   [726.0, 228.1, 190.4],     RPY_T, 8.0),
    ]
    for name, tgt, rpy, spd in steps:
        if not mv(tgt, rpy, name, spd):
            print("  ✗ %s 失败, 停" % name, flush=True)
            return 5
        p1, rpy1 = pose()
        p1m = [v * 1000 for v in p1]
        f1 = read_f()
        dp = math.dist(p1m, tgt)
        dr = R_err_deg(rpy1, rpy)
        df = math.dist(f0[:3], f1[:3])
        print("  %-8s → %7.1f %7.1f %7.1f · 差 %.2fmm · 姿态差 %.3f° · ΔF %.1fN · 距插口 %.1fmm"
              % (name, p1m[0], p1m[1], p1m[2], dp, dr, df,
                 math.dist(p1m, [761.75, 228.07, 190.36])), flush=True)
        log["steps"].append({"name": name, "tcp_mm": [round(v, 1) for v in p1m],
                             "rpy": [round(v, 4) for v in rpy1], "d_mm": round(dp, 2),
                             "drot_deg": round(dr, 3), "dF": round(df, 2)})
        if dp > D_MAX or dr > R_MAX or df > F_MAX:
            print("  ✗ %s 超限, 停(不再继续后续步)" % name, flush=True)
            return 6
    pf, rpyf = pose()
    pfm = [v * 1000 for v in pf]
    print("到位 %.1f %.1f %.1f · rpy %s · 距插口 %.1fmm"
          % (pfm[0], pfm[1], pfm[2], [round(v, 4) for v in rpyf],
             math.dist(pfm, [761.75, 228.07, 190.36])), flush=True)
    os.makedirs("/sdk/logs", exist_ok=True)
    json.dump(log, open("/sdk/logs/goto_port_%s.json" % time.strftime("%H%M%S"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
