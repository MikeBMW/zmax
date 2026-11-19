#!/usr/bin/env python3
"""sweep_pitch_joints.py — 俯仰(关节空间) + 横线扫掠(笛卡尔，用实测 rpy 回传) 采集。

教训(2026-11-19 真机碰撞): 用 **rpy 增量** 加俯仰 会因控制器 rpy 在 ±π 附近的表示歧义
把 TCP 甩到 675/246/191(离工装面板仅 14.7mm)。所以俯仰**只走关节空间**(MoveAbsJ, 由
tools/pitch_plan_joints.py 用真 URDF 做 IK 得到), 横线仍用笛卡尔但 rpy **一律回传实测值**。

安全口径(硬编码):
  · 前置 power=on · automatic · idle · 无 estop
  · 每个姿态: 关节误差 >1.0° 停; TCP 偏离期望 >2.0mm 停; |ΔF| > 25N 停
  · 横线每段: 位置偏差 >1.5mm 停; 姿态(实测 rpy 回传后)变化 >0.6° 停
  · 单段位移 ≤ 25mm; 速度 ≤ 15mm/s; 全程不靠近面板(实测间隙 ≥240mm)

用法(容器内):
    python3 /sdk/sweep_pitch_joints.py --plan /sdk/pitch_joints.json --pitches="0,-12,12" --half 80 --step 20 --speed 15
    ... --dry
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
    ap.add_argument("--plan", default="/sdk/pitch_joints.json")
    ap.add_argument("--pitches", default="0,-12,12")
    ap.add_argument("--half", type=float, default=80.0)
    ap.add_argument("--step", type=float, default=20.0)
    ap.add_argument("--speed", type=float, default=15.0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    by_p = {round(float(p["pitch"]), 1): p for p in plan["poses"]}
    want = [float(v) for v in a.pitches.split(",") if v.strip()]
    missing = [p for p in want if round(p, 1) not in by_p]
    if missing:
        print("拒绝: 计划里没有这些俯仰 %s" % missing)
        return 2

    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: power=%s mode=%s op=%s" % (pw, md, op), flush=True)
    if "on" not in pw:
        print("拒绝: power 不是 on")
        return 3
    if "automatic" not in md:
        if "idle" not in op:
            print("拒绝: 不在 idle(当前 %s), 不改模式 —— 请先松手/切回自动" % op)
            return 3
        r.setOperateMode(x.OperateMode.automatic, {})
        time.sleep(0.8)
        md = str(r.operateMode({}))
        print("模式切换 → %s" % md, flush=True)
        if "automatic" not in md:
            print("拒绝: 切不到 automatic")
            return 3

    fc = r.forceControl()
    b = [x.PyTypeVectorDouble() for _ in range(4)]

    def read_f():
        fc.getEndTorque(x.FrameType.tool, b[0], b[1], b[2], b[3], {})
        return (vals(b[3]) + [0.0] * 6)[:6]

    def joints():
        return [float(v) for v in r.jointPos({})][:6]

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]

    def wait_settle(jt, tol=0.6, timeout=40.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.1)
            if "idle" in str(r.operationState({})).lower():
                aj = joints()
                if max(abs(math.degrees(y - z)) for y, z in zip(jt, aj)) <= tol:
                    return True, max(abs(math.degrees(y - z)) for y, z in zip(jt, aj))
        aj = joints()
        return False, max(abs(math.degrees(y - z)) for y, z in zip(jt, aj))

    def move_j(jt, speed=12.0):
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend([x.MoveAbsJCommand(x.JointPosition([float(v) for v in jt]), speed, -1)],
                     x.PyString("pitch"), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            return False, 999.0, str(ec)
        r.moveStart({})
        ok, err = wait_settle(jt)
        return ok, err, ""

    def move_l(tgt, rpy, speed):
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt],
                                                        [float(v) for v in rpy]), speed, -1),
                     x.PyString("y"), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            return False, str(ec)
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 40 and "idle" not in str(r.operationState({})).lower():
            time.sleep(0.05)
        time.sleep(0.2)
        return True, ""

    # 基准姿态 = 计划里的 0° (对插口)
    j_base = by_p[0.0]["joints_rad"]
    p_now, rpy_now = pose()
    print("当前 TCP=[%.1f %.1f %.1f]mm · 基准(0°)计划 TCP=%s mm" % (
        p_now[0] * 1000, p_now[1] * 1000, p_now[2] * 1000, plan["tcp_mm"]), flush=True)
    if a.dry:
        for p in want:
            print("dry 俯仰 %+.0f° → 关节 %s (误差 %.2fmm/%.3f°, 间隙 %.0fmm)" % (
                p, by_p[round(p, 1)]["joints_deg"], by_p[round(p, 1)]["pos_err_mm"],
                by_p[round(p, 1)]["rot_err_deg"], by_p[round(p, 1)]["clear_mm"]))
        print("dry: 不下发")
        return 0

    os.makedirs(EV, exist_ok=True)
    log = {"t0": time.time(), "plan": a.plan, "passes": []}
    code = 0

    # 1) 先回基准姿态
    ok, err, e = move_j(j_base)
    p0, rpy0 = pose()
    f0 = read_f()
    print("回基准: 关节误差 %.2f° · TCP=[%.1f %.1f %.1f]mm %s" % (
        err, p0[0] * 1000, p0[1] * 1000, p0[2] * 1000, e), flush=True)
    if not ok or err > 1.0:
        print("停: 回基准不合格")
        return 5

    n = int(round(a.half / a.step))
    for pd in want:
        rec_p = by_p[round(pd, 1)]
        ok, err, e = move_j(rec_p["joints_rad"])
        p1, rpy1 = pose()
        dxy = math.dist(p1, p0) * 1000
        df = math.dist(f0[:3], read_f()[:3])
        print("俯仰 %+.0f°: 关节误差 %.2f° · TCP 变化 %.1fmm · ΔF %.1fN" % (pd, err, dxy, df), flush=True)
        rec = {"pitch": pd, "jerr_deg": round(err, 2), "tcp_delta_mm": round(dxy, 1),
               "dF": round(df, 1), "segments": []}
        log["passes"].append(rec)
        if not ok or err > 1.0:
            print("停: 俯仰不到位"); code = 5; break
        if dxy > 25.0:
            print("停: TCP 变化 %.1fmm > 25mm(俯仰应只转不动点)" % dxy); code = 6; break
        if df > 25.0:
            print("停: ΔF %.1fN > 25N" % df); code = 7; break
        # 2) 该俯仰下扫横线: 每段回传**实测 rpy**(不做任何 rpy 运算)
        for i in range(-n, n + 1):
            pc, rpyc = pose()
            tgt = [pc[0], p1[1] + i * a.step / 1000.0, pc[2]]
            ok, e = move_l(tgt, rpyc, a.speed)
            p2, rpy2 = pose()
            dy = (p2[1] - tgt[1]) * 1000
            drot = max(abs(math.degrees(rpy2[k] - rpyc[k])) for k in range(3))
            df2 = math.dist(f0[:3], read_f()[:3])
            rec["segments"].append({"i": i, "dy_mm": round(dy, 2), "drot_deg": round(drot, 3),
                                    "dF": round(df2, 1)})
            print("   %+d° 段%2d y%+.0f → 差 %+.2fmm · 姿态变 %.3f° · ΔF %.1fN" % (
                pd, i, tgt[1] * 1000, dy, drot, df2), flush=True)
            if abs(dy) > 1.5 or drot > 0.6:
                print("停: 段不合格"); code = 8; break
            if df2 > 25.0:
                print("停: ΔF %.1fN > 25N" % df2); code = 7; break
        if code:
            break
        # 回中心
        pc, rpyc = pose()
        move_l([pc[0], p0[1], pc[2]], rpyc, a.speed)
    # 3) 回基准姿态收工
    ok, err, _ = move_j(j_base)
    p3, _ = pose()
    print("收尾: 关节误差 %.2f° · TCP=[%.1f %.1f %.1f]mm" % (err, p3[0] * 1000, p3[1] * 1000, p3[2] * 1000), flush=True)
    log["code"] = code
    fn = os.path.join(EV, "sweep_pitch_joints_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(log, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    print("日志 → %s · rc=%d" % (fn, code), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
