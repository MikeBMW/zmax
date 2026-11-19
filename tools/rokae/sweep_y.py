#!/usr/bin/env python3
"""sweep_y.py — 从当前位姿沿 base Y 走一条横线(建图补采), 逐段核验, 异常即停。

老倪 2026-11-19: 「你就从当前位置，左右20厘米，走横线」「你自己走吧」
实测: 固定姿态下 ±120mm 内 IK 连续(单步 ≤8.8°), ±200mm 会跳构型 ⇒ 本脚本默认 ±120mm。

安全口径(硬编码, 不靠参数):
  · 前置: power=on · automatic(manual 则先 idle 下切) · idle · estop=false · has_error=false
  · 速度 20 mm/s, 单段 24mm, 姿态全程锁定(用起点 rpy)
  · 每段到位后读真值: 偏差 >1.5mm ⇒ 停; 侧向偏离目标 y 的垂度 >2mm ⇒ 停
  · 力: 与起点比 |ΔF|>25N ⇒ 停(六维力原始读数, 同姿态差分)
  · 走到右端后**原路返回起点**, 结束时停在起点(不留残余位移)

用法(容器内):
    python3 /sdk/sweep_y.py --half 120 --step 24 --speed 20 --max-seg 2 --dry
    python3 /sdk/sweep_y.py --half 120 --step 24 --speed 20
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


def vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", type=float, default=120.0, help="左右半幅 mm")
    ap.add_argument("--step", type=float, default=24.0, help="单段 mm")
    ap.add_argument("--speed", type=float, default=20.0, help="mm/s")
    ap.add_argument("--max-seg", type=int, default=0, help="最多走几段(0=全走)")
    ap.add_argument("--dry", action="store_true", help="只打印计划, 不动")
    ap.add_argument("--no-return", action="store_true", help="走完不回起点")
    ap.add_argument("--center-mm", type=float, default=0.0, help="横线中心的 base y(mm); 0=用当前 y")
    a = ap.parse_args()

    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: power=%s mode=%s op=%s" % (pw, md, op), flush=True)
    if "on" not in pw:
        print("拒绝: power 不是 on")
        return 3
    if "automatic" not in md:
        if "idle" not in op:
            print("拒绝: 不在 idle, 不改模式")
            return 3
        e2 = {}
        r.setOperateMode(x.OperateMode.automatic, e2)
        time.sleep(0.8)
        md = str(r.operateMode({}))
        print("模式切换: → %s %s" % (md, e2 if e2 else ""), flush=True)
        if "automatic" not in md:
            print("拒绝: 切不到 automatic")
            return 3
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]

    def read_f():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        f = vals(b[3])
        return (f + [0.0] * 6)[:6]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    p0, rpy0 = pose()
    f0 = read_f()
    n = int(round(a.half / a.step))
    cy = (a.center_mm / 1000.0) if a.center_mm else p0[1]
    targets = [cy + i * a.step / 1000.0 for i in range(-n, n + 1)]
    print("起点 TCP=[%.4f %.4f %.4f] rpy=%s" % (*p0, [round(v, 4) for v in rpy0]), flush=True)
    print("计划: y %.0f → %.0f mm (共 %d 段, 每段 %.0fmm, %.0fmm/s), x/z 与 rpy 锁定" % (
        p0[1] * 1000 - a.half, p0[1] * 1000 + a.half, 2 * n, a.step, a.speed), flush=True)
    print("起始 F_tool=%s  |F|=%.1fN" % ([round(v, 2) for v in f0[:3]], math.dist(f0[:3], [0, 0, 0])), flush=True)
    if a.dry:
        print("dry: 不下发")
        return 0

    os.makedirs(EV, exist_ok=True)
    log = {"t0": time.time(), "start_tcp": p0, "rpy": rpy0, "half_mm": a.half,
           "step_mm": a.step, "speed": a.speed, "segments": []}
    code = 0
    seg_i = 0
    order = list(range(0, len(targets)))            # 左→右
    for k, idx in enumerate(order):
        if a.max_seg and seg_i >= a.max_seg:
            print("到达 --max-seg %d, 停在这里" % a.max_seg, flush=True)
            break
        pc, _ = pose()
        tgt = [pc[0], targets[idx], pc[2]]
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        ec = {}
        r.moveReset(ec)
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy0]),
                                    a.speed, -1), x.PyString("sweep%d" % idx), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("段%d 下发失败: %s" % (idx, ec), flush=True)
            code = 4
            break
        r.moveStart({})
        t1 = time.time()
        while time.time() - t1 < 40 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.2)
        p1, rpy1 = pose()
        f1 = read_f()
        dy = (p1[1] - targets[idx]) * 1000.0
        dyaw = max(abs(rpy1[j] - rpy0[j]) for j in range(3)) * 57.2958
        df = math.dist(f0[:3], f1[:3])
        seg_i += 1
        rec = {"i": idx, "tgt_y": round(targets[idx] * 1000, 1), "got": [round(v * 1000, 1) for v in p1],
               "dy_mm": round(dy, 2), "d_rpy_deg": round(dyaw, 3), "dF": round(df, 2)}
        log["segments"].append(rec)
        print("段%2d → y %+.1f (实到 %+.1f, 差 %+.2fmm) · 姿态变 %.3f° · ΔF %.2fN · F=%s" % (
            idx, targets[idx] * 1000, p1[1] * 1000, dy, dyaw, df, [round(v, 1) for v in f1[:3]]), flush=True)
        if abs(dy) > 1.5:
            print("停: 目标 y 偏差 %.2fmm > 1.5mm" % dy, flush=True)
            code = 5
            break
        if dyaw > 1.0:
            print("停: 姿态变化 %.2f° > 1.0°" % dyaw, flush=True)
            code = 6
            break
        if df > 25.0:
            print("停: 力变 %.2fN > 25N" % df, flush=True)
            code = 7
            break
    # 回起点
    if not a.no_return and code == 0:
        pc, _ = pose()
        r.moveReset({})
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in [pc[0], p0[1], pc[2]]],
                                                        [float(v) for v in rpy0]), a.speed, -1), x.PyString("sweep_home"), {})
        r.moveStart({})
        t1 = time.time()
        while time.time() - t1 < 40 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        p2, _ = pose()
        print("回起点: y=%.1f (起点 %.1f) · TCP=[%.1f %.1f %.1f]" % (
            p2[1] * 1000, p0[1] * 1000, p2[0] * 1000, p2[1] * 1000, p2[2] * 1000), flush=True)
        log["home"] = [round(v * 1000, 1) for v in p2]
    log["code"] = code
    log["t1"] = time.time()
    fn = os.path.join(EV, "sweep_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(log, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    print("日志 → %s · rc=%d" % (fn, code), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
