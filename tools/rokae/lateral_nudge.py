#!/usr/bin/env python3
"""lateral_nudge.py — 力扫描给出的方向做一次毫米级侧向让位 (位置控制, 慢速, 全程读力)。

背景 (2026-11-19 实测): 口沿十字扫描 0.5mm 微动
    中心 侧向Δ0.43N · +X 1.87 · -X 3.89 · +Y 4.47 · -Y 7.06  ⇒ 最松 = 工具 +X, 最紧 = -Y
而按对射尺量的端口基准算出的"应对中方向"是 base z -3.0 / base y +3.6,
换算到工具系正好是 tool X -2.97 / tool Y -3.62 —— **与力扫描方向相反**。
⇒ 结论: 端口几何基准不可信, 以力扫描为准 (力不会撒谎, 尺量有遮挡和斜面)。

本工具只做一件事: 沿工具 X/Y 平移 (dx,dy) 毫米, 速度 2mm/s, 前后各读一次六维力,
打印侧向Δ变化。不做轴向推进、不碰夹爪。位移上限 ±3mm (防手滑)。

用法 (容器内, 只读力 + 毫米级微动):
    python3 /sdk/lateral_nudge.py --dx 0.8 --dy 0.5
    python3 /sdk/lateral_nudge.py --back 2.0        # 只沿轴退 2mm 卸力, 不动侧向
"""
import argparse
import json
import math
import os
import sys
import time

SDK_DIR = os.environ.get("ZMAX_SDK_DIR", "/sdk")
IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
EV = os.path.join(SDK_DIR, "logs")
sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402


def rpy2R(rpy):
    r, p, y = rpy
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr]]


def vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dx", type=float, default=0.0, help="工具 X 平移 mm (+X = 扫描最松方向)")
    ap.add_argument("--dy", type=float, default=0.0, help="工具 Y 平移 mm")
    ap.add_argument("--back", type=float, default=0.0, help="沿工具 Z 后退 mm (卸力)")
    ap.add_argument("--speed", type=float, default=2.0)
    ap.add_argument("--limit", type=float, default=3.0, help="单次位移上限 mm")
    a = ap.parse_args()
    for n, v in (("dx", a.dx), ("dy", a.dy), ("back", a.back)):
        if abs(v) > a.limit:
            print("拒绝: %s=%.2f 超过上限 %.1fmm" % (n, v, a.limit))
            return 2
    r = x.xMateRobot()
    r.connectToRobot(IP)
    ec = {}
    st = {"power": str(r.powerState(ec)), "op": str(r.operationState(ec)), "mode": str(r.operateMode(ec))}
    print("自检:", json.dumps(st, ensure_ascii=False))
    if "on" not in st["power"] or "automatic" not in st["mode"]:
        print("拒绝: 需要 power=on + automatic")
        return 3
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    pos = [float(v) for v in cp.trans]
    rpy = [float(v) for v in cp.rpy]
    R = rpy2R(rpy)
    ux = [R[i][0] for i in range(3)]
    uy = [R[i][1] for i in range(3)]
    uz = [R[i][2] for i in range(3)]
    fc = r.forceControl()
    b1, b2, b3, b4 = x.PyTypeVectorDouble(), x.PyTypeVectorDouble(), x.PyTypeVectorDouble(), x.PyTypeVectorDouble()

    def read_f():
        e = {}
        fc.getEndTorque(x.FrameType.tool, b1, b2, b3, b4, e)
        out = vals(b4)
        if len(out) < 3:
            out = vals(b3)
        return [round(v, 2) for v in out[:3]]

    f0 = read_f()
    tgt = [pos[k] + ux[k] * a.dx / 1000.0 + uy[k] * a.dy / 1000.0 - uz[k] * a.back / 1000.0 for k in range(3)]
    d = math.dist(pos, tgt)
    print("起点 TCP=[%.4f %.4f %.4f] · 力 F=%s" % (pos[0], pos[1], pos[2], f0))
    print("目标 TCP=[%.4f %.4f %.4f] · 距离 %.2fmm · 速度 %.1fmm/s" % (tgt[0], tgt[1], tgt[2], d * 1000, a.speed))
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec)
    ec = {}
    r.moveReset(ec)
    ec = {}
    r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy]), a.speed, -1),
                 x.PyString("nudge"), ec)
    ec = {}
    r.moveStart(ec)
    t0 = time.time()
    while time.time() - t0 < 20:
        if "idle" in str(r.operationState({})):
            break
        time.sleep(0.1)
    time.sleep(0.4)
    cp1 = r.cartPosture(x.CoordinateType.endInRef, {})
    p1 = [float(v) for v in cp1.trans]
    f1 = read_f()
    res = {"f_before": f0, "f_after": f1, "d_lat": round(math.dist(f0, f1), 2),
           "move_mm": round(math.dist(pos, p1) * 1000, 2),
           "residual_mm": round(math.dist(tgt, p1) * 1000, 2), "cmd_mm": round(d * 1000, 2)}
    print("结果:", json.dumps(res, ensure_ascii=False))
    os.makedirs(EV, exist_ok=True)
    fp = os.path.join(EV, "nudge_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"args": vars(a), "result": res, "start": pos, "target": tgt, "rpy": rpy}, open(fp, "w"), ensure_ascii=False, indent=1)
    print("证据:", fp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
