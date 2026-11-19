#!/usr/bin/env python3
"""sweep_pitch.py — 横线扫掠 + 俯仰变化(补斜视视差), 逐段核验, 异常即停。

老倪 2026-11-19: 「还是不行，加俯仰」
  背景: 前面 4451 帧全在一条水平横线上, **只有平移视差** ⇒ 3DGS 解不出插口立面/内壁,
        渲染出来还是糊。俯仰 ±15° 才给到斜视视角。

安全口径(硬编码):
  · 前置 power=on · automatic · idle · estop=false · has_error=false
  · 俯仰只绕 **TCP 点** 转(位置不动), 手腕画圆弧 R=工具长 259mm ⇒ 15° 时手爪偏移 67mm,
    当前 TCP 距工装面板 105mm、法兰距面板 ~364mm ⇒ 俯仰后仍在 300mm 外
  · 每段到位读真值: 位置偏差 >1.5mm 停 · 姿态偏差 >1.5° 停 · |ΔF|>25N 停
  · 先转姿态(原地), 再走横线; 每遍走完回中心

用法(容器内):
    python3 /sdk/sweep_pitch.py --half 100 --step 25 --speed 15 --pitches "-15,0,15" --dry
    python3 /sdk/sweep_pitch.py --half 100 --step 25 --speed 15 --pitches "-15,0,15"
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


def rpy2R(r, p, y):
    """ZYX: R = Rz(y)·Ry(p)·Rx(r)  —— 与控制器 cartPosture 的 rpy 口径一致(实测 15° 对得上)。"""
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr]]


def R2rpy(R):
    """ZYX 逆解(与 rpy2R 互逆), 用于把旋转矩阵换算回控制器能接受的 rpy。"""
    p = math.asin(max(-1.0, min(1.0, -R[2][0])))
    r = math.atan2(R[2][1], R[2][2])
    y = math.atan2(R[1][0], R[0][0])
    return [r, p, y]


def geodesic_deg(Ra, Rb):
    """两个旋转之间的最小夹角(度) —— 必须这么比: 控制器 rpy 表示会欧拉回绕(实测偏 180° 的假差)。"""
    tr = sum(Ra[i][k] * Rb[i][k] for i in range(3) for k in range(3))
    c = max(-1.0, min(1.0, (tr - 1.0) / 2.0))
    return math.degrees(math.acos(c))


def rot_tool_y(R, deg):
    """绕工具自身 Y 轴转 deg 度: R' = R · Ry(deg)。"""
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    Ry = [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
    return [[sum(R[i][k] * Ry[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def vals(v):
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", type=float, default=100.0, help="左右半幅 mm")
    ap.add_argument("--step", type=float, default=25.0, help="单段 mm")
    ap.add_argument("--speed", type=float, default=15.0, help="mm/s")
    ap.add_argument("--pitches", default="-15,0,15", help="俯仰角(度), 逗号分隔")
    ap.add_argument("--pitch-idx", type=int, default=1, help="rpy 里俯仰的分量下标(默认 1)")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-seg", type=int, default=0)
    ap.add_argument("--base-rpy", default="",
                    help="基准姿态(度, 逗号分隔 r,p,y); 空=用当前位姿。上次跑完停在某个俯仰上时必须显式给")
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
        r.setOperateMode(x.OperateMode.automatic, {})
        time.sleep(0.8)
        md = str(r.operateMode({}))
        print("模式切换: → %s" % md, flush=True)
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

    def move_to(tgt, rpy, tag, timeout=45.0):
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt],
                                                        [float(v) for v in rpy]),
                                    a.speed, -1), x.PyString(tag), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            return False, "下发失败 %s" % ec
        r.moveStart({})
        t1 = time.time()
        while time.time() - t1 < timeout and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.2)
        return True, ""

    p0, rpy0 = pose()
    if a.base_rpy:
        rpy0 = [math.radians(float(v)) for v in a.base_rpy.split(",")]
        print("基准姿态(显式): rpy=%s ; 先回基准姿态" % [round(v, 4) for v in rpy0], flush=True)
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in p0],
                                                        [float(v) for v in rpy0]), 10.0, -1),
                     x.PyString("base_rpy"), {})
        r.moveStart({})
        t1 = time.time()
        while time.time() - t1 < 45 and "idle" not in str(r.operationState({})):
            time.sleep(0.05)
        time.sleep(0.2)
        p0, _ = pose()
        _R = rpy2R(*pose()[1])
        print("  → 回基准后几何夹角 %.3f°" % geodesic_deg(_R, rpy2R(*rpy0)), flush=True)
    f0 = read_f()
    pitches = [float(v) for v in a.pitches.split(",") if v.strip()]
    print("起点 TCP=[%.4f %.4f %.4f] rpy=%s · |F|=%.1fN" % (*p0, [round(v, 4) for v in rpy0],
                                                          math.dist(f0[:3], [0, 0, 0])), flush=True)
    print("计划: %d 个俯仰 × 横线 ±%.0fmm(步 %.0f) @ %.0fmm/s" % (len(pitches), a.half, a.step, a.speed), flush=True)
    if a.dry:
        print("dry: 不下发")
        return 0

    os.makedirs(EV, exist_ok=True)
    log = {"t0": time.time(), "start": p0, "rpy0": rpy0, "pitches": pitches, "passes": []}
    code = 0
    n = int(round(a.half / a.step))
    seg_total = 0
    R0 = rpy2R(*rpy0)
    for pi, pd in enumerate(pitches):
        # 🔴 2026-11-19 实测: 控制器回读的 rpy 会欧拉回绕(命令 -15° 后回读成 [0.0004,-1.4013,-3.1247],
        #   与原 rpy 逐个比差 180° 的"假差", 但旋转矩阵夹角正好 15°) ⇒ 一律按**旋转矩阵**下发和校验。
        Rp = rot_tool_y(R0, pd)
        rpy_p = R2rpy(Rp)
        # 1) 原地转俯仰(位置不动)
        ok, err = move_to(p0, rpy_p, "pitch%+d" % int(pd))
        p1, rpy1 = pose()
        R1 = rpy2R(*rpy1)
        dtilt = geodesic_deg(R1, Rp)
        dpos = math.dist(p1, p0) * 1000
        dF = math.dist(f0[:3], read_f()[:3])
        print("俯仰 %+d°: 到位差 %.3f° · 位置漂 %.2fmm · ΔF %.2fN" % (pd, dtilt, dpos, dF), flush=True)
        rec = {"pitch": pd, "tilt_err_deg": round(dtilt, 3), "pos_drift_mm": round(dpos, 2),
               "dF": round(dF, 2), "segments": []}
        log["passes"].append(rec)
        if not ok:
            print("停: %s" % err); code = 4; break
        if dtilt > 1.5 or dpos > 2.0:
            print("停: 俯仰到位不合格")
            code = 5
            break
        if dF > 25.0:
            print("停: 转俯仰时 ΔF %.1fN > 25N" % dF)
            code = 7
            break
        # 2) 该俯仰下走横线
        for i in range(-n, n + 1):
            if a.max_seg and seg_total >= a.max_seg:
                break
            pc, _ = pose()
            tgt = [pc[0], p0[1] + i * a.step / 1000.0, pc[2]]
            ok, err = move_to(tgt, rpy_p, "p%d_y%d" % (int(pd), i))
            p2, rpy2 = pose()
            dy = (p2[1] - tgt[1]) * 1000
            dtt = geodesic_deg(rpy2R(*rpy2), Rp)
            df = math.dist(f0[:3], read_f()[:3])
            seg_total += 1
            rec["segments"].append({"i": i, "dy_mm": round(dy, 2), "dt_deg": round(dtt, 3), "dF": round(df, 2)})
            print("  %+d° 段%2d y%+.0f → 差 %+.2fmm · 姿态差 %.3f° · ΔF %.2fN" % (pd, i, tgt[1] * 1000, dy, dtt, df), flush=True)
            if not ok or abs(dy) > 1.5 or dtt > 1.5:
                print("停: 段不合格")
                code = 6
                break
            if df > 25.0:
                print("停: ΔF %.1fN > 25N" % df)
                code = 7
                break
        # 回中心 + 回原姿态
        move_to([p0[0], p0[1], p0[2]], rpy0, "home")
        print("  → 回基准 几何夹角 %.3f°" % geodesic_deg(rpy2R(*pose()[1]), R0), flush=True)
        if code:
            break
    p3, rpy3 = pose()
    print("收尾 TCP=[%.1f %.1f %.1f]mm rpy=%s" % (p3[0] * 1000, p3[1] * 1000, p3[2] * 1000,
                                                  [round(v, 4) for v in rpy3]), flush=True)
    log["end"] = p3
    log["code"] = code
    fn = os.path.join(EV, "sweep_pitch_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(log, open(fn, "w", encoding="utf-8"), ensure_ascii=False)
    print("日志 → %s · rc=%d" % (fn, code), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
