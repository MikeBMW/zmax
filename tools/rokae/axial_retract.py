#!/usr/bin/env python3
"""axial_retract.py — 沿工具轴**纯轴向**退出 (保持姿态, 慢速, 分段, 全程读力)。

老倪 2026-11-19 10:0x 要求: "现在的光模块还是在插口里, 你能自己退出来么? 注意要保持轴向, 慢一点"
纪律 (硬写在代码里, 不靠自觉):
  · 只沿 -tool_z 走, 姿态 rpy 全程不变 (不改角, 不侧移)
  · 每段 --step mm (默认 3), 段内速度 --speed (默认 2mm/s)
  · 每段后核: 侧向漂移 |Δxy⊥| ≤ --lat-tol (默认 0.10mm), 否则立即停
  · 每段后核: |ΔF_tool| 超过 --force-jump (默认 8N) 立即停 (卡住/挂住)
  · 累计退到 --mm 或 轴向力回到静止水平 -0.5N 以内即停
` 不会反向推进: 代码里没有任何正向前进分支。

用法 (容器内):
    python3 /sdk/axial_retract.py --mm 48 --step 3 --speed 2
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
    ap.add_argument("--mm", type=float, default=48.0, help="总共退出 mm")
    ap.add_argument("--step", type=float, default=3.0, help="每段 mm")
    ap.add_argument("--speed", type=float, default=2.0, help="mm/s (慢)")
    ap.add_argument("--lat-tol", type=float, default=0.10, help="允许的侧向漂移 mm")
    ap.add_argument("--force-jump", type=float, default=8.0, help="单段力变化上限 N")
    a = ap.parse_args()
    r = x.xMateRobot()
    r.connectToRobot(IP)
    ec = {}
    print("自检: power=%s mode=%s op=%s" % (r.powerState(ec), r.operateMode({}), r.operationState({})), flush=True)
    if "on" not in str(r.powerState({})):
        print("拒绝: power 不是 on")
        return 3
    if "automatic" not in str(r.operateMode({})):
        # 手动拖动后控制器停在 manual, SDK 的 MoveL 只在 automatic 下被接受
        if "idle" not in str(r.operationState({})):
            print("拒绝: 不在 idle, 不改模式")
            return 3
        e2 = {}
        r.setOperateMode(x.OperateMode.automatic, e2)
        time.sleep(0.8)
        now = str(r.operateMode({}))
        print("模式切换: manual → %s %s" % (now, e2 if e2 else ""), flush=True)
        if "automatic" not in now:
            print("拒绝: 切不到 automatic")
            return 3
    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]

    def read_f():
        e = {}
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], e)
        f = vals(b[3])
        return (f + [0.0] * 6)[:6]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    p0, rpy = pose()
    R = rpy2R(rpy)
    uz = [R[i][2] for i in range(3)]
    f0 = read_f()
    print("起点 TCP=[%.4f %.4f %.4f] · 工具Z=[%+.3f %+.3f %+.3f] · F_tool=%s" % (*p0, *uz, [round(v, 2) for v in f0[:3]]), flush=True)
    print("计划: 沿 -Z 共退 %.1fmm · 每段 %.1fmm @ %.1fmm/s · 姿态锁定 · 侧漂限 %.2fmm · 单段力变限 %.1fN" % (
        a.mm, a.step, a.speed, a.lat_tol, a.force_jump), flush=True)

    trace = [{"t": time.time(), "x": p0[0], "f": f0[:3], "done_mm": 0.0}]
    done = 0.0
    seg = 0
    code = 0
    while done < a.mm:
        seg += 1
        step = min(a.step, a.mm - done)
        pc, _ = pose()
        tgt = [pc[k] - uz[k] * step / 1000.0 for k in range(3)]
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        ec = {}
        r.moveReset(ec)
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy]),
                                    a.speed, -1), x.PyString("retract"), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("段%d 下发失败: %s" % (seg, ec), flush=True)
            code = 4
            break
        r.moveStart({})
        t1 = time.time()
        while time.time() - t1 < 30 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.25)
        p1, rpy1 = pose()
        f1 = read_f()
        # 轴向实走量 (投影到 -uz)
        adv = sum((pc[k] - p1[k]) * uz[k] for k in range(3)) * 1000.0
        # 侧向漂移 = 总位移向量减去轴向分量
        dv = [p1[k] - pc[k] for k in range(3)]
        ax = sum(dv[k] * uz[k] for k in range(3))
        lat = math.sqrt(max(1e-12, sum(v * v for v in dv) - ax * ax)) * 1000.0
        fj = math.dist(f0[:3], f1[:3])
        rot = max(abs(rpy1[k] - rpy[k]) for k in range(3)) if len(rpy1) == 3 else 0.0
        done += adv
        trace.append({"t": time.time(), "x": p1[0], "f": f1[:3], "done_mm": round(done, 2)})
        print("段%-2d 退 %5.2fmm (累计 %5.1f) · 侧漂 %.3fmm · 转角 %.4frad · F_tool=[%+6.2f %+6.2f %+6.2f] · |ΔF|=%.2fN" % (
            seg, adv, done, lat, rot, f1[0], f1[1], f1[2], fj), flush=True)
        if lat > a.lat_tol:
            print("停: 侧向漂移 %.2f > %.2f mm (不保持轴向)" % (lat, a.lat_tol), flush=True)
            code = 5
            break
        if rot > 0.01:
            print("停: 姿态变了 %.4f rad" % rot, flush=True)
            code = 6
            break
        if fj > a.force_jump:
            print("停: 单段力变化 %.1fN > %.1fN (可能挂住)" % (fj, a.force_jump), flush=True)
            code = 7
            break
        if abs(f1[2]) < 0.5:
            print("停: 轴向力已回零 (%.2fN) ⇒ 已脱开插口" % f1[2], flush=True)
            break
    pE, _ = pose()
    res = {"code": code, "done_mm": round(done, 2), "start": p0, "end": pE, "rpy": rpy,
           "f_start": [round(v, 2) for v in f0[:3]], "f_end": [round(v, 2) for v in read_f()[:3]]}
    print("结果:", json.dumps(res, ensure_ascii=False), flush=True)
    os.makedirs(EV, exist_ok=True)
    fp = os.path.join(EV, "retract_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump({"args": vars(a), "result": res, "trace": trace}, open(fp, "w"), ensure_ascii=False, indent=1)
    print("证据:", fp, flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
