#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""insert_push.py — 位置模式慢推 + 被动看门狗 + 位置域李萨如(卡住时)。

老倪: 「插, 力控算法, 你要用 L5 来指导」
口径来自 `force-controlled-insertion` 技能(本机实测过的部分):
  · **不进力控模式**: 硬接触下 fcStart/setLissajousOverlay 必触发 41451 控制器下电(实测 5 次)
    ⇒ "力控算法"在这里落成: 位置慢推 + 20ms 被动力看门狗 + 位置域李萨如搜索
  · 力判据一律用 **Δ(相对本段起点基线)**; 绝对值含工具自重(-23.6N 级)
  · 力先 5 帧中值滤波 + 剔除 |F|>200N 尖峰(实测快速段有 948N/2771N 假峰)
  · 触线即 stop + moveReset + **沿 −x 退 3mm 卸力**(stop 只保持位置, 不卸力: 实测会自己爬到 179N)
  · 轴向 = 工具 z(本姿态对应 base +x) ; 侧向 = hypot(tool fx, tool fy)
  · 卡住判据: 单段位移 <0.4mm 且 ΔF>8N ⇒ 先位置域李萨如(±1.2mm, Y-Z 正交, 0.7/1.1Hz)再试;
    连续两次卡住 ⇒ 判"端面没对正", 停手退出(李萨如只能修孔内 ≤0.5mm)

用法:
  python3 insert_push.py --targets 760.5,761.75,763.5,766.0 --speed 0.4
  python3 insert_push.py --targets 768,771,774,777,780 --speed 0.5 --no-lissa
"""
from __future__ import annotations

import argparse
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
F_AXIAL_STOP = float(os.environ.get("ZMAX_F_AX", "25"))
F_LAT_STOP = float(os.environ.get("ZMAX_F_LAT", "10"))
F_SPIKE = 200.0
STUCK_MM = 0.4


def vals(v):
    return [float(t) for t in (v.get() if hasattr(v, "get") else v)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--speed", type=float, default=0.4)
    ap.add_argument("--lissa", dest="lissa", action="store_true", default=True)
    ap.add_argument("--no-lissa", dest="lissa", action="store_false")
    ap.add_argument("--unload-mm", type=float, default=3.0)
    a = ap.parse_args()
    tgts = [float(t) for t in a.targets.split(",")]

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
        if max(abs(t) for t in v) > F_SPIKE:
            return None
        hist.append(v)
        if len(hist) > 5:
            hist.pop(0)
        return [statistics.median([h[i] for h in hist]) for i in range(3)]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def motion(tgt, rpy, spd, watch=True, baseline=None):
        """下发一条 MoveL, 过程中 20ms 看门狗。返回 (tripped, peak_ax, peak_lat, disp_mm)"""
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition(tgt, [float(v) for v in rpy]), spd, -1),
                     x.PyString("push"), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            raise RuntimeError("下发失败 %s" % ec)
        p_from, _ = pose()
        peak_ax = peak_lat = 0.0
        tripped = False
        seen_moving = False
        t0 = time.time()
        r.moveStart({})
        while time.time() - t0 < 90:
            f = f_filt()
            if watch and f is not None and baseline is not None:
                d = [f[i] - baseline[i] for i in range(3)]
                ax = abs(d[2])
                lat = math.hypot(d[0], d[1])
                peak_ax = max(peak_ax, ax)
                peak_lat = max(peak_lat, lat)
                if ax > F_AXIAL_STOP or lat > F_LAT_STOP:
                    r.stop({})
                    r.moveReset({})
                    tripped = True
                    break
            st = str(r.operationState({}))
            if "moving" in st:
                seen_moving = True
            elif "idle" in st and seen_moving:
                break
            time.sleep(0.02)
        p_to, _ = pose()
        return tripped, peak_ax, peak_lat, math.dist([v * 1000 for v in p_to], [v * 1000 for v in p_from])

    def unload(mm):
        time.sleep(0.5)
        want = None
        for attempt in (1, 2):
            p, _ = pose()
            if want is None:
                want = p[0] - mm / 1000.0
            tgt = [want, p[1], p[2]]
            try:
                motion(tgt, RPY_T, 1.5, watch=False, baseline=None)
            except RuntimeError as e:
                print("  (卸力下发异常 %s, 重试)" % str(e)[:60], flush=True)
            p2, _ = pose()
            if abs(p2[0] - want) * 1000 < 0.6:
                break
            print("  (卸力未到位 x=%.2f, 第%d次重试)" % (p2[0] * 1000, attempt), flush=True)
        p2, _ = pose()
        f = f_filt() or f_raw()
        print("  卸力后 x=%.2f · |F|-baseline 差 %.1fN" % (p2[0] * 1000, math.dist(f[:3], base_now[:3])), flush=True)
        return [v * 1000 for v in p2]

    def lissa(cycles=4, amp=1.2):
        """位置域李萨如: Y-Z 正交正弦, 恒定位移, 力只做被动判据。"""
        p0, _ = pose()
        k = 0
        ph = 0.0
        stuck = 0
        while k < cycles:
            t = ph
            dy = amp * math.sin(2 * math.pi * 0.7 * t) / 1000.0
            dz = amp * math.sin(2 * math.pi * 1.1 * t + math.pi / 2) / 1000.0
            tgt = [p0[0], p0[1] + dy, p0[2] + dz]
            tr, ax, lat, _ = motion(tgt, RPY_T, 4.0, watch=True, baseline=base_now)
            if tr:
                return True, ax, lat
            ph += 0.18
            k += 1
        return False, 0.0, 0.0

    p0, rpy0 = pose()
    p0m = [v * 1000 for v in p0]
    for _ in range(6):
        f_filt()
    base_now = f_filt() or f_raw()
    print("起点 %.2f %.2f %.2f · 力基线(tool) [%.1f %.1f %.1f]N"
          % (p0m[0], p0m[1], p0m[2], base_now[0], base_now[1], base_now[2]), flush=True)
    log = {"start_mm": [round(v, 1) for v in p0m], "base_f": [round(v, 2) for v in base_now],
           "speed": a.speed, "seg": []}
    stuck_n = 0
    for tx in tgts:
        p, rp = pose()
        pm = [v * 1000 for v in p]
        if tx <= pm[0] + 0.05:
            print("  跳过 %.2f (已在 %.2f)" % (tx, pm[0]), flush=True)
            continue
        base_now = f_filt() or f_raw()          # 每段重取基线(同姿态差分)
        tgt = [tx / 1000.0, p[1], p[2]]
        tr, ax, lat, disp = motion(tgt, RPY_T, a.speed, watch=True, baseline=base_now)
        p1, _ = pose()
        p1m = [v * 1000 for v in p1]
        depth = p1m[0] - 761.75
        print("  → %7.2f · 本段 %5.2fmm · 进深 %+6.2fmm · 峰轴向 %5.1fN · 峰侧向 %4.1fN%s"
              % (p1m[0], disp, depth, ax, lat, "  ⛔看门狗" if tr else ""), flush=True)
        log["seg"].append({"x": round(p1m[0], 2), "disp": round(disp, 2), "depth": round(depth, 2),
                           "peak_axial": round(ax, 2), "peak_lat": round(lat, 2), "tripped": tr})
        if tr:
            p2 = unload(a.unload_mm)
            print("  ⛔ 触线 ⇒ 已退 %.1fmm 卸力, 现在 x=%.2f · 停手" % (a.unload_mm, p2[0]), flush=True)
            log["unload_x"] = round(p2[0], 2)
            break
        short = (tx - p1m[0])
        if short > STUCK_MM and ax > 8.0:
            stuck_n += 1
            print("  卡住签名: 差 %.2fmm 未到 + 峰轴向 %.1fN ⇒ %s"
                  % (short, ax, "位置域李萨如搜索" if a.lissa else "不看门狗, 直接停"), flush=True)
            log["seg"][-1]["stuck"] = True
            if not a.lissa or stuck_n >= 2:
                p2 = unload(a.unload_mm)
                print("  ⛔ 连续卡住/未启用搜索 ⇒ 判端面未对正, 退 %.1fmm 停手 (x=%.2f)" % (a.unload_mm, p2[0]), flush=True)
                log["unload_x"] = round(p2[0], 2)
                break
            tr2, ax2, lat2 = lissa()
            if tr2:
                p2 = unload(a.unload_mm)
                print("  ⛔ 搜索段触线(轴向 %.1fN/侧向 %.1fN) ⇒ 退 %.1fmm 停手" % (ax2, lat2, a.unload_mm), flush=True)
                log["unload_x"] = round(p2[0], 2)
                break
            base_now = f_filt() or f_raw()
            tr3, ax3, lat3, disp3 = motion(tgt, RPY_T, a.speed, watch=True, baseline=base_now)
            p3, _ = pose()
            p3m = [v * 1000 for v in p3]
            print("  搜索后再推 → %.2f · 本段 %5.2fmm · 进深 %+6.2fmm · 峰轴向 %.1fN%s"
                  % (p3m[0], disp3, p3m[0] - 761.75, ax3, "  ⛔" if tr3 else ""), flush=True)
            log["seg"].append({"x": round(p3m[0], 2), "disp": round(disp3, 2),
                               "depth": round(p3m[0] - 761.75, 2), "peak_axial": round(ax3, 2), "after_lissa": True})
            if tr3:
                p2 = unload(a.unload_mm)
                print("  ⛔ 已退 %.1fmm 停手 (x=%.2f)" % (a.unload_mm, p2[0]), flush=True)
                log["unload_x"] = round(p2[0], 2)
                break
    pf, _ = pose()
    pfm = [v * 1000 for v in pf]
    print("结束 %.2f %.2f %.2f · 进深 %+.2fmm" % (pfm[0], pfm[1], pfm[2], pfm[0] - 761.75), flush=True)
    os.makedirs("/sdk/logs", exist_ok=True)
    json.dump(log, open("/sdk/logs/insert_%s.json" % time.strftime("%H%M%S"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
