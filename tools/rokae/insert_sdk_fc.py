#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""insert_sdk_fc.py —— 「里萨如力控插入」的 SDK 直连实现 (不依赖 Orin ROS 运动栈)。

背景 (2026-10-20 现场): 产线 `/lissajous_force_search` 服务**不在图上** (Orin 只有夹爪/相机/tap 节点,
robot_driver 没跑) ⇒ L2.lissa_search 回执 `waiting for service to become available...`、位移 0.00mm。
老倪选 B: 用 xCoreSDK 力控原语现场实现同一套算法。

配方抄产线 `/lissajous_force_search` (docs/.../l2-force-insert-and-verification.md §一, 不猜):
    frame_type = tool · plane = XY · cartesian_desired_force = [0,0,6,0,0,0] (6N 沿工具 Z)
    lissajous: 6mm@3Hz + 4mm@2Hz, 相位差 π/2 · 搜索盒 ±10mm · 超时 8s · 先标定力传感器
SDK 对应原语 (xCoreSDK __init__.pyi):
    forceControl().fcInit(FrameType.tool) · setControlType(1 笛卡尔阻抗) · setCartesianStiffness
    · setCartesianMaxVel · fcMonitor(True) · fcStart · setCartesianDesiredForce
    · setLissajousOverlay(plane, A1, f1, A2, f2, phase) · startOverlay · stopOverlay · fcStop
    · getEndTorque(ref, jtm, etm, ctq, cfo, ec) → cart_force [X,Y,Z] N

三道自保 (真机红线):
    ① 前置: power on / automatic / idle / 无报警 / 静止 (极差 <0.02mm), 不满足一条不发
    ② 力上限看门狗: |Fz|>25N 或 |Fxy|>25N ⇒ 立刻 stopOverlay+fcStop (20ms 量级)
    ③ 位移/时间双限: 累计位移 > --max-mm 或 > --timeout 秒 ⇒ 停; 全程不发夹爪指令

用法 (必须容器里跑, SDK 是 cpython-310):
    bash tools/rokae_sdk_run.sh --script insert_sdk_fc.py --mode probe     # 只读: 状态/位姿/力基线
    bash tools/rokae_sdk_run.sh --script insert_sdk_fc.py --mode zero      # 零力空跑: 只证明力控能起停
    bash tools/rokae_sdk_run.sh --script insert_sdk_fc.py --mode insert    # 真插 (6N + 李萨如)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time

FZ_HARD_N = 40.0      # 🔴 老倪 2026-10-20 19:1x 现场改为: 「最大插入力限制在40牛」(18:50 原话是30牛)
FZ_TRIP_N = 34.0      # 实际停手阈值(留 6N 余量; 命令行给更大也只按这个跑)

SDK_DIR = os.environ.get("ZMAX_SDK_DIR", "/sdk")
EVID_DIR = os.path.join(SDK_DIR, "logs")
IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")

sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402

LOG = []


def log(s):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), s)
    print(line, flush=True)
    LOG.append(line)


def chk(ec, what):
    """珞石 SDK 的成功返回是 {'ec':0,'message':'success'} —— 键名是 ec。"""
    code = ec.get("ec", ec.get("code", ec.get("err"))) if isinstance(ec, dict) else None
    if code not in (None, 0, "0"):
        raise RuntimeError("%s 失败: ec=%s msg=%s" % (what, code, (ec or {}).get("message")))
    return ec


# ---------------- 只读 ----------------
def read_state(r):
    return {"power": str(r.powerState({})), "op": str(r.operationState({})),
            "mode": str(r.operateMode({}))}


def read_pose(r):
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]


def rpy2R(rpy):
    """ZYX (yaw-pitch-roll) → 旋转矩阵, 与 controller 的 rpy 口径一致。"""
    r, p, y = float(rpy[0]), float(rpy[1]), float(rpy[2])
    cr, sr, cp_, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return [[cy * cp_, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp_, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp_ * sr, cp_ * cr]]


def make_buffers():
    try:
        return (x.PyTypeVectorDouble(), x.PyTypeVectorDouble(), x.PyTypeVectorDouble(), x.PyTypeVectorDouble())
    except Exception:                                                    # noqa: BLE001
        return ([], [], [], [])


def _vals(v):
    """PyTypeVectorDouble / list / tuple → list[float] (SDK 的向量不能下标, 只能 get()/content())"""
    if hasattr(v, "get"):
        return [float(t) for t in v.get()]
    if hasattr(v, "content"):
        return [float(t) for t in v.content()]
    return [float(t) for t in v]


def read_force(fc, bufs, ref):
    jtm, etm, ctq, cfo = bufs
    ec = {}
    fc.getEndTorque(ref, jtm, etm, ctq, cfo, ec)
    chk(ec, "getEndTorque")
    f, t = _vals(cfo), _vals(ctq)
    t = (t + [0.0, 0.0, 0.0])[:3]
    return (f[0], f[1], f[2], t[0], t[1], t[2])


def wait_still(r, tol=2e-5, need=3, timeout=6.0):
    t0, prev, still = time.time(), None, 0
    while time.time() - t0 < timeout:
        p, _ = read_pose(r)
        if prev and max(abs(p[i] - prev[i]) for i in range(3)) < tol:
            still += 1
            if still >= need:
                return True
        else:
            still = 0
        prev = p
        time.sleep(0.25)
    return False


def preflight(r, need_idle=True):
    st = read_state(r)
    log("自检: %s" % json.dumps(st, ensure_ascii=False))
    if "on" not in st["power"]:
        return "上电不是 on (%s)" % st["power"]
    if need_idle and "idle" not in st["op"]:
        return "不空闲 (%s)" % st["op"]
    if "automatic" not in st["mode"]:
        return "不是自动模式 (%s)" % st["mode"]
    return None


def write_evid(out, tag):
    os.makedirs(EVID_DIR, exist_ok=True)
    p = os.path.join(EVID_DIR, "insert_fc_%s_%s.json" % (tag, time.strftime("%Y%m%d_%H%M%S")))
    out["evidence_path"] = p
    out["log"] = LOG
    out["container_time"] = time.strftime("%F %T")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("证据: %s" % p)
    return p


# ---------------- 力控主体 ----------------
def fc_run(r, a, mode):
    """mode: 'zero' (零力自检) | 'step' (短脉冲, 只看方向) | 'insert' (真插: 6N + 李萨如)。"""
    out = {"mode": mode, "ip": IP, "force_n": a.force, "args": vars(a)}
    p0, rpy0 = read_pose(r)
    out["pre_pose"] = {"tcp": p0, "rpy": rpy0}
    R0 = rpy2R(rpy0)
    zaxis = [R0[0][2], R0[1][2], R0[2][2]]                       # 工具 Z 在 base 里的方向
    out["tool_z_base"] = [round(v, 4) for v in zaxis]
    log("起点 TCP=[%.5f, %.5f, %.5f] · 工具Z(base)=[%+.3f, %+.3f, %+.3f]"
        % (p0[0], p0[1], p0[2], zaxis[0], zaxis[1], zaxis[2]))

    fc = r.forceControl()
    bufs = make_buffers()

    # ---- 1) 力控起 (顺序按 SDK 文档: fcInit → 参数 → fcMonitor → fcStart → 负载/期望力) ----
    ec = {}
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec)
    chk(ec, "setMotionControlMode(NrtCommandMode)")
    for fn, args, nm in ((fc.fcInit, (x.FrameType.tool,), "fcInit(tool)"),
                         (fc.setControlType, (1,), "setControlType(1)"),
                         (fc.setCartesianStiffness, (list(a.stiffness),), "setCartesianStiffness"),
                         (fc.setCartesianMaxVel, (list(a.maxvel),), "setCartesianMaxVel"),
                         (fc.fcMonitor, (True,), "fcMonitor(True)"),
                         (fc.fcStart, (), "fcStart")):
        ec = {}
        fn(*(list(args) + [ec]))
        chk(ec, nm)
    started = True
    log("力控已起: stiffness=%s maxvel=%s" % (list(a.stiffness), list(a.maxvel)))

    # ---- 2) 静态读数 = 工具(夹爪+模块)重力 ⇒ 反解 m/cog, setLoad 让读数等于"接触力" ----
    f0 = read_force(fc, bufs, x.FrameType.tool)
    out["force_raw"] = [round(v, 3) for v in f0]
    log("静态读数(未补偿): F=[%+.2f, %+.2f, %+.2f]N · T=[%+.3f, %+.3f, %+.3f]Nm" % f0)
    fmag = math.sqrt(f0[0] ** 2 + f0[1] ** 2 + f0[2] ** 2)
    if a.auto_load and fmag > 2.0:
        try:
            m = fmag / 9.81
            Fv, Tt = (f0[0], f0[1], f0[2]), (f0[3], f0[4], f0[5])
            FxT = (Fv[1] * Tt[2] - Fv[2] * Tt[1], Fv[2] * Tt[0] - Fv[0] * Tt[2], Fv[0] * Tt[1] - Fv[1] * Tt[0])
            n2 = Fv[0] ** 2 + Fv[1] ** 2 + Fv[2] ** 2
            cog = [round(v / n2, 5) for v in FxT]
            if max(abs(v) for v in cog) > 0.3:          # 反解出 >30cm 的质心 ⇒ 力矩通道已归零, 不可信
                cog = [0.0, 0.0, 0.0]
                out["cog_rejected"] = True
            ec = {}
            fc.setLoad(x.Load(float(m), cog, [1e-4, 1e-4, 1e-4]), ec)
            chk(ec, "setLoad")
            out["load"] = {"mass_kg": round(m, 4), "cog_m": cog}
            log("负载补偿: m=%.3fkg cog=%s" % (m, cog))
            time.sleep(0.3)
        except Exception as e:                                           # noqa: BLE001
            log("⚠️ 负载补偿失败(继续): %s" % str(e)[:160])
            out["load_err"] = str(e)[:200]

    # ---- 3) 力传感器标定 (文档: 标定前 load 要对) ----
    if a.calibrate:
        try:
            ec = {}
            r.calibrateForceSensor(True, 0, ec)
            chk(ec, "calibrateForceSensor")
            time.sleep(0.45)
            log("力传感器已标定 (all_axes)")
        except Exception as e:                                           # noqa: BLE001
            log("⚠️ 标定异常(继续): %s" % str(e)[:160])
            out["calibrate_err"] = str(e)[:200]
    fb = read_force(fc, bufs, x.FrameType.tool)
    out["force_baseline"] = [round(v, 3) for v in fb]
    log("补偿+标定后基线: F=[%+.2f, %+.2f, %+.2f]N" % fb[:3])
    if max(abs(fb[0]), abs(fb[1]), abs(fb[2])) > 20.0:
        out["verdict"] = "ABORT 基线残余 >20N"
        log("🛑 " + out["verdict"])
        try:
            fc.fcStop({})
        except Exception:                                                # noqa: BLE001
            pass
        return 7, out

    rows, verdict, fx_peak = [], "?", 0.0
    overlaid = False
    os.makedirs(EVID_DIR, exist_ok=True)
    csv_path = os.path.join(EVID_DIR, "insert_fc_%s_%s.csv" % (mode, time.strftime("%Y%m%d_%H%M%S")))
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    wr = csv.writer(cf)
    wr.writerow(["t", "x", "y", "z", "fx", "fy", "fz", "tx", "ty", "tz", "adv_mm"])
    want = 0.0 if mode == "zero" else a.force
    try:
        ec = {}
        fc.setCartesianDesiredForce([0.0, 0.0, want, 0.0, 0.0, 0.0], ec)
        chk(ec, "setCartesianDesiredForce")
        log("期望力 = [0, 0, %.2f, 0, 0, 0]N (工具系)" % want)
        if mode == "insert":
            ec = {}
            fc.setLissajousOverlay(a.plane, a.amp1, a.freq1, a.amp2, a.freq2, a.phase, ec)
            chk(ec, "setLissajousOverlay")
            log("李萨如: plane=%d · %.1fmm@%.1fHz + %.1fmm@%.1fHz · 相位 %.2f"
                % (a.plane, a.amp1, a.freq1, a.amp2, a.freq2, a.phase))
            ec = {}
            fc.startOverlay(ec)
            chk(ec, "startOverlay")
            overlaid = True
            log("搜索运动已开 ⇒ 监视中 (力上限 %.0fN · 位移上限 %.1fmm · %.1fs)"
                % (a.watchdog_n, a.max_mm, a.timeout))

        t0, hit, prev_dist = time.time(), 0, 0.0
        while True:
            time.sleep(1.0 / max(a.rate, 1.0))
            p, _ = read_pose(r)
            fx, fy, fz, tx, ty, tz = read_force(fc, bufs, x.FrameType.tool)
            adv = sum((p[i] - p0[i]) * zaxis[i] for i in range(3)) * 1000.0
            dist = math.sqrt(sum((p[i] - p0[i]) ** 2 for i in range(3))) * 1000.0
            rows.append((time.time() - t0, p[0], p[1], p[2], fx, fy, fz, tx, ty, tz, adv))
            wr.writerow([round(rows[-1][0], 4), round(p[0], 6), round(p[1], 6), round(p[2], 6),
                         round(fx, 3), round(fy, 3), round(fz, 3), round(tx, 3), round(ty, 3), round(tz, 3),
                         round(adv, 3)])
            fx_peak = max(fx_peak, math.sqrt(fx * fx + fy * fy + fz * fz))
            if rows[1:] and dist - prev_dist > 3.0:
                verdict = "ABORT 位移跳变 (%.1fmm/帧)" % (dist - prev_dist)
                log("🛑 " + verdict)
                break
            prev_dist = dist
            fxy = math.hypot(fx, fy)
            _trip = min(a.watchdog_n, FZ_TRIP_N)
            if fxy > _trip or abs(fz) > _trip:
                verdict = "ABORT 力超上限 (Fxy=%.1fN Fz=%.1fN > %.0fN)" % (fxy, fz, a.watchdog_n)
                log("🛑 " + verdict)
                break
            if mode != "zero" and abs(fz - fb[2]) >= a.stop_n:
                hit += 1
                if hit >= 3:
                    verdict = "force_reached (|ΔFz|=%.2fN ≥ %.1fN)" % (abs(fz - fb[2]), a.stop_n)
                    break
            else:
                hit = 0
            if dist >= a.max_mm:
                verdict = "disp_limit (%.1fmm ≥ %.1fmm)" % (dist, a.max_mm)
                break
            if time.time() - t0 >= a.timeout:
                verdict = "timeout (%.1fs)" % (time.time() - t0)
                break
    finally:
        if overlaid:
            try:
                fc.stopOverlay({})
            except Exception:                                            # noqa: BLE001
                pass
        if started:
            try:
                fc.fcStop({})
            except Exception:                                            # noqa: BLE001
                pass
            try:
                fc.fcMonitor(False, {})
            except Exception:                                            # noqa: BLE001
                pass
        try:
            r.setMotionControlMode(x.MotionControlMode.Idle, {})
        except Exception:                                                # noqa: BLE001
            pass
        cf.close()

    p1, rpy1 = read_pose(r)
    d = [p1[i] - p0[i] for i in range(3)]
    out.update({"verdict": verdict, "end_pose": {"tcp": p1, "rpy": rpy1},
                "delta_mm": [round(v * 1000, 3) for v in d],
                "adv_toolz_mm": round(sum(d[i] * zaxis[i] for i in range(3)) * 1000, 3),
                "dist_mm": round(math.sqrt(sum(v * v for v in d)) * 1000, 3),
                "force_peak_n": round(fx_peak, 2), "n_samples": len(rows), "csv": csv_path,
                "force_last": [round(v, 2) for v in (rows[-1][4:7] if rows else (0, 0, 0))]})
    log("结果: %s" % verdict)
    log("位移: Δ=[%+.2f, %+.2f, %+.2f]mm · |Δ|=%.2fmm · 沿工具Z前进 %.2fmm"
        % (out["delta_mm"][0], out["delta_mm"][1], out["delta_mm"][2], out["dist_mm"], out["adv_toolz_mm"]))
    log("力峰值 %.2fN · 采样 %d 帧" % (fx_peak, len(rows)))
    ok = verdict.startswith(("force_reached", "disp_limit", "timeout"))
    return (0 if ok else 1), out


def fc_advance(r, a, mode="advance"):
    """力控模式下的直线推进 (SDK 文档: fcStart 后可执行运动指令) + 李萨如叠加 + 力阈值停车。

    与 fc_run(zero/step/insert) 的区别: 那里靠"期望力"推, 实测臂一动不动(0.01mm);
    产线的深度其实来自**位置模式的直线推进**(阶段2 推进 60mm), 力控只负责柔顺与找孔。
    所以这里: fcStart(给柔顺/重力补偿) → MoveL 直线推进 → 同时开李萨如 → 力超阈立即 r.stop()。
    """
    out = {"mode": mode, "ip": IP, "args": vars(a)}
    p0, rpy0 = read_pose(r)
    R0 = rpy2R(rpy0)
    zaxis = [R0[0][2], R0[1][2], R0[2][2]]
    out.update({"pre_pose": {"tcp": p0, "rpy": rpy0}, "tool_z_base": [round(v, 4) for v in zaxis],
                "travel_mm": a.travel_mm, "speed": a.speed})
    log("起点 TCP=[%.5f, %.5f, %.5f] · 工具Z(base)=[%+.3f, %+.3f, %+.3f]"
        % (p0[0], p0[1], p0[2], zaxis[0], zaxis[1], zaxis[2]))

    fc = r.forceControl()
    bufs = make_buffers()
    ec = {}
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec)
    chk(ec, "setMotionControlMode")

    started = overlaid = False
    rows, verdict, peak = [], "?", 0.0
    os.makedirs(EVID_DIR, exist_ok=True)
    csv_path = os.path.join(EVID_DIR, "insert_fc_%s_%s.csv" % (mode, time.strftime("%Y%m%d_%H%M%S")))
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    wr = csv.writer(cf)
    wr.writerow(["t", "x", "y", "z", "fx", "fy", "fz", "tx", "ty", "tz", "adv_mm"])
    try:
        for fn, args, nm in ((fc.fcInit, (x.FrameType.tool,), "fcInit(tool)"),
                             (fc.setControlType, (1,), "setControlType(1)"),
                             (fc.setCartesianStiffness, (list(a.stiffness),), "setCartesianStiffness"),
                             (fc.setCartesianMaxVel, (list(a.maxvel),), "setCartesianMaxVel"),
                             (fc.fcMonitor, (True,), "fcMonitor(True)"),
                             (fc.fcStart, (), "fcStart")):
            ec = {}
            fn(*(list(args) + [ec]))
            chk(ec, nm)
        started = True
        # 实测(10:44:00): fcStart 后立刻读基线会读到**未收敛的值**(同一姿态三次会话基线 -0.15/+0.15/-16.06N),
        # 拿它当零点 ⇒ 判据全错。这里等到连续两次读数各轴差 <1N 再采用。
        fb, prev_fb, t_w = read_force(fc, bufs, x.FrameType.tool), None, time.time()
        while time.time() - t_w < 2.5:
            time.sleep(0.25)
            prev_fb, fb = fb, read_force(fc, bufs, x.FrameType.tool)
            if max(abs(fb[i] - prev_fb[i]) for i in range(3)) < 1.0:
                break
        out["force_baseline"] = [round(v, 3) for v in fb]
        out["baseline_settle_s"] = round(time.time() - t_w, 2)
        log("力控已起 (K=%s) · 基线(收敛 %.2fs) F=[%+.2f, %+.2f, %+.2f]N" % (list(a.stiffness), out["baseline_settle_s"], fb[0], fb[1], fb[2]))

        if a.lissajous:
            ec = {}
            fc.setLissajousOverlay(a.plane, a.amp1, a.freq1, a.amp2, a.freq2, a.phase, ec)
            chk(ec, "setLissajousOverlay")
            ec = {}
            fc.startOverlay(ec)
            chk(ec, "startOverlay")
            overlaid = True
            log("李萨如叠加已开: %.1fmm@%.1fHz + %.1fmm@%.1fHz" % (a.amp1, a.freq1, a.amp2, a.freq2))

        tgt = [p0[i] + zaxis[i] * a.travel_mm / 1000.0 for i in range(3)]
        cp = x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy0])
        out["target"] = [round(v, 6) for v in tgt]
        log("目标(TCP) = [%.5f, %.5f, %.5f] · 推进 %.1fmm · speed=%.0f(≈%.1fmm/s)"
            % (tgt[0], tgt[1], tgt[2], a.travel_mm, a.speed, a.speed * 0.0999))
        ec = {}
        r.moveReset(ec)
        ec = {}
        r.setDefaultSpeed(a.speed, ec)
        ec = {}
        r.moveAppend(x.MoveLCommand(cp, a.speed, -1), x.PyString("fc_adv_%d" % int(time.time())), ec)
        chk(ec, "moveAppend(MoveL)")
        ec = {}
        r.moveStart(ec)
        chk(ec, "moveStart")
        log("已下发 MoveL, 盯真值 + 力阈值 %.1fN" % a.stop_n)

        t0, hit, prev = time.time(), 0, 0.0
        while True:
            time.sleep(1.0 / max(a.rate, 1.0))
            p, _ = read_pose(r)
            fx, fy, fz, tx, ty, tz = read_force(fc, bufs, x.FrameType.tool)
            adv = sum((p[i] - p0[i]) * zaxis[i] for i in range(3)) * 1000.0
            rows.append((time.time() - t0, p[0], p[1], p[2], fx, fy, fz, tx, ty, tz, adv))
            wr.writerow([round(rows[-1][0], 4), round(p[0], 6), round(p[1], 6), round(p[2], 6),
                         round(fx, 3), round(fy, 3), round(fz, 3), round(tx, 3), round(ty, 3), round(tz, 3),
                         round(adv, 3)])
            peak = max(peak, math.sqrt(fx * fx + fy * fy + fz * fz))
            dfz = abs(fz - fb[2])
            # 注意: 运动中 fx 常驻 ~-15N (工具重力落在传感器该轴上, 与 fc 静态补偿口径不同) ⇒
            # 侧向只看 fy, 压入轴看 Δfz; fx 只记录不判 (实测它有恒定偏置, 拿它当看门狗会误停)
            _trip = min(a.watchdog_n, FZ_TRIP_N)
            if abs(fy - fb[1]) > _trip or dfz > _trip:
                verdict = "ABORT 力超上限 (dFz=%.1fN dFy=%.1fN)" % (dfz, abs(fy - fb[1]))
                log("🛑 " + verdict)
                try:
                    r.stop({})
                except Exception:                                        # noqa: BLE001
                    pass
                break
            if dfz >= a.stop_n:
                hit += 1
                if hit >= 1:
                    verdict = "force_stop (ΔFz=%.2fN ≥ %.1fN ⇒ 顶到孔/壁, 已停)" % (dfz, a.stop_n)
                    log("🛑 " + verdict)
                    try:
                        r.stop({})
                    except Exception:                                    # noqa: BLE001
                        pass
                    break
            else:
                hit = 0
            if adv >= a.travel_mm - 0.3:
                verdict = "target_reached (推进 %.2fmm)" % adv
                break
            if time.time() - t0 >= a.timeout:
                verdict = "timeout (%.1fs, 推进 %.2fmm)" % (time.time() - t0, adv)
                break
    finally:
        if overlaid:
            try:
                fc.stopOverlay({})
            except Exception:                                            # noqa: BLE001
                pass
        try:
            r.stop({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.moveReset({})       # 清掉队列里没跑完的 MoveL —— 实测: 上一段被中止后, 队列里的
                                  # MoveL 会在**下一次会话**接着执行 (10:43:54→10:44:00 自己前移 4.68mm)
        except Exception:                                                # noqa: BLE001
            pass
        if started:
            try:
                fc.fcStop({})
            except Exception:                                            # noqa: BLE001
                pass
        try:
            r.setMotionControlMode(x.MotionControlMode.Idle, {})
        except Exception:                                                # noqa: BLE001
            pass
        cf.close()

    p1, _ = read_pose(r)
    d = [p1[i] - p0[i] for i in range(3)]
    out.update({"verdict": verdict, "end_pose": [round(v, 6) for v in p1],
                "delta_mm": [round(v * 1000, 3) for v in d],
                "adv_toolz_mm": round(sum(d[i] * zaxis[i] for i in range(3)) * 1000, 3),
                "force_peak_n": round(peak, 2), "n_samples": len(rows), "csv": csv_path})
    log("结果: %s" % verdict)
    log("位移: Δ=[%+.2f, %+.2f, %+.2f]mm · 沿工具Z %.2fmm · 力峰值 %.2fN"
        % (out["delta_mm"][0], out["delta_mm"][1], out["delta_mm"][2], out["adv_toolz_mm"], peak))
    return (0 if verdict.startswith(("target_reached", "force_stop")) else 1), out


def fc_search(r, a):
    """位置空间自实现的李萨如找孔 + 小步推进 (力只看工具Z, 超阈立即停)。

    为什么不用 SDK 的 setLissajousOverlay: 实测它的幅值是**力/力矩口径**(文档单位 Nm),
    填产线文档的 6.0/4.0 得到 ±19.6N 力尖峰而位移只有 0.43mm ⇒ 拿它压模块等于拿模块当保险丝。
    这里改成**我能精确控制毫米**的做法: 每周期 XY 走一个李萨如点(幅值 mm 自己算), Z 前进 step(mm),
    每周期读一次力, |ΔFz| 超阈 ⇒ 退回 0.4mm 换个相位再来 (顶到孔口面时就是这样"蹭"孔)。

    判据(不吹): 力一直很低且累计前进到 max_mm ⇒ 进了; 同一个深度反复顶超阈 ⇒ 卡在面/壁。
    """
    out = {"mode": "search", "ip": IP, "args": vars(a)}
    p_face, rpy = read_pose(r)
    R = rpy2R(rpy)
    zaxis = [R[0][2], R[1][2], R[2][2]]
    xaxis, yaxis = [R[0][0], R[1][0], R[2][0]], [R[0][1], R[1][1], R[2][1]]
    out.update({"start_pose": [round(v, 6) for v in p_face], "rpy": [round(v, 5) for v in rpy],
                "tool_z": [round(v, 4) for v in zaxis], "amp_mm": a.lat_mm, "step_mm": a.step_mm})
    log("起点 TCP=[%.5f, %.5f, %.5f] · 幅值 ±%.2fmm · 步进 %.2fmm/周期" % (p_face[0], p_face[1], p_face[2], a.lat_mm, a.step_mm))

    fc = r.forceControl()
    bufs = make_buffers()
    rows, stuck, verdict = [], [], "?"
    os.makedirs(EVID_DIR, exist_ok=True)
    csv_path = os.path.join(EVID_DIR, "insert_search_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    wr = csv.writer(cf)
    wr.writerow(["cycle", "t", "x", "y", "z", "fz", "adv_mm", "lat_mm", "note"])

    guard = {"on": False, "bufs": None, "fc": None, "fz0": 0.0, "limit": FZ_TRIP_N}

    def one_move(tgt, speed):
        ec = {}
        r.moveReset(ec)
        r.setDefaultSpeed(speed, ec)
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy]),
                                    speed, -1), x.PyString("fc_s_%d" % int(time.time() * 1000 % 1e9)), ec)
        chk(ec, "moveAppend")
        ec = {}
        r.moveStart(ec)
        chk(ec, "moveStart")
        t0 = time.time()
        while time.time() - t0 < 12:
            time.sleep(0.02)
            if guard["on"]:
                try:
                    _f = read_force(guard["fc"], guard["bufs"], x.FrameType.tool)
                    if abs(_f[2] - guard["fz0"]) > guard["limit"]:
                        r.stop({})
                        r.moveReset({})
                        log("  🛑 运动中力超阈 %.1fN (红线 %.0fN/停手 %.0fN) ⇒ 立即停"
                            % (abs(_f[2] - guard["fz0"]), FZ_HARD_N, guard["limit"]))
                        return "force_abort"
                except Exception:                                        # noqa: BLE001
                    pass
            if "idle" in str(r.operationState({})):
                if time.time() - t0 > 0.15:
                    return True
        return False

    try:
        ec = {}
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec)
        chk(ec, "setMotionControlMode")

        # ① 先退到面外 (此刻臂是被 27N 顶着的 9.2mm 柔顺偏移, 不退就是继续压)
        back = [p_face[i] - zaxis[i] * a.back_mm / 1000.0 for i in range(3)]
        log("退 %.1fmm 解除顶压 → [%.5f, %.5f, %.5f]" % (a.back_mm, back[0], back[1], back[2]))
        one_move(back, a.speed)
        p_face, _ = read_pose(r)
        log("退后 TCP=[%.5f, %.5f, %.5f]" % (p_face[0], p_face[1], p_face[2]))

        # ② 力控起 (只为拿到补偿后的力读数; 运动仍是位置模式)
        for fn, args, nm in ((fc.fcInit, (x.FrameType.tool,), "fcInit"),
                             (fc.setControlType, (1,), "setControlType(1)"),
                             (fc.setCartesianStiffness, (list(a.stiffness),), "setCartesianStiffness"),
                             (fc.setCartesianMaxVel, (list(a.maxvel),), "setCartesianMaxVel"),
                             (fc.fcMonitor, (True,), "fcMonitor"),
                             (fc.fcStart, (), "fcStart")):
            ec = {}
            fn(*(list(args) + [ec]))
            chk(ec, nm)
        fz0, prevf = None, None
        t_w = time.time()
        while time.time() - t_w < 2.5:
            time.sleep(0.25)
            f = read_force(fc, bufs, x.FrameType.tool)
            if prevf and abs(f[2] - prevf[2]) < 0.8:
                fz0 = f[2]
                break
            prevf = f
        fz0 = fz0 if fz0 is not None else (prevf[2] if prevf else 0.0)
        out["fz_baseline"] = round(fz0, 3)
        guard.update({"on": True, "bufs": bufs, "fc": fc, "fz0": fz0,
                      "limit": min(a.stop_n, FZ_TRIP_N)})
        log("力基线 ΔFz0=%.2fN (收敛 %.2fs) · 运动中实时盯力, 超 %.0fN 立即停 (红线 %.0fN)"
            % (fz0, time.time() - t_w, guard["limit"], FZ_HARD_N))

        # ③ 李萨如 + 小步推进
        n = int(a.max_mm / a.step_mm) + 1
        k = 0
        best_adv = 0.0
        while k < n:
            k += 1
            t = k * a.cyc_s
            ox = a.lat_mm * math.sin(2 * math.pi * a.f1 * t)
            oy = a.lat_mm * math.sin(2 * math.pi * a.f2 * t + math.pi / 2)
            adv = a.step_mm * k
            tgt = [p_face[i] + zaxis[i] * adv / 1000.0 + xaxis[i] * ox / 1000.0 + yaxis[i] * oy / 1000.0
                   for i in range(3)]
            one_move(tgt, a.speed)
            p, _ = read_pose(r)
            f = read_force(fc, bufs, x.FrameType.tool)
            adv_real = sum((p[i] - p_face[i]) * zaxis[i] for i in range(3)) * 1000.0
            dfz = abs(f[2] - fz0)
            lat = math.hypot(ox, oy)
            note = ""
            if dfz > a.stop_n:
                note = "顶住 %.1fN ⇒ 退 0.4mm 换相位" % dfz
                bk = [p[i] - zaxis[i] * 0.4 / 1000.0 for i in range(3)]
                one_move(bk, a.speed)
                stuck.append(round(adv_real, 2))
                k -= 1 if len(stuck) > 1 and stuck[-1] - stuck[-2] < 0.2 else 0
            wr.writerow([k, round(time.time(), 3), round(p[0], 6), round(p[1], 6), round(p[2], 6),
                         round(f[2], 3), round(adv_real, 3), round(lat, 3), note])
            rows.append((k, adv_real, f[2], dfz, note))
            if adv_real > best_adv:
                best_adv = adv_real
            if k % 5 == 0 or note:
                log("  #%d adv=%.2fmm ΔFz=%.2fN lat=%.2fmm %s" % (k, adv_real, dfz, lat, note))
            if adv_real >= a.max_mm - 0.6:
                verdict = "inserted (前进 %.2fmm, 力未超阈)" % adv_real
                break
            if len(stuck) >= a.max_stuck:
                verdict = "stuck (卡在 %.2fmm: %d 次顶超阈, 孔口面对不上)" % (best_adv, len(stuck))
                break
    finally:
        try:
            r.stop({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.moveReset({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            fc.fcStop({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.setMotionControlMode(x.MotionControlMode.Idle, {})
        except Exception:                                                # noqa: BLE001
            pass
        cf.close()

    if verdict == "?":
        verdict = "cycle_limit (跑了 %d 周期, 最深 %.2fmm)" % (len(rows), best_adv)
    p_end, _ = read_pose(r)
    out.update({"verdict": verdict, "best_adv_mm": round(best_adv, 2),
                "end_pose": [round(v, 6) for v in p_end],
                "depth_from_mouth_mm": round((p_end[0] - a.mouth_x) * 1000, 2) if a.mouth_x else None,
                "stuck_at": stuck[:12], "n_cycles": len(rows), "csv": csv_path})
    log("结果: %s" % verdict)
    log("最深前进 %.2fmm · 卡点 %s" % (best_adv, stuck[:6]))
    return (0 if verdict.startswith("inserted") else 1), out


def fc_push(r, a):
    """位置模式纯推 + 力只做**被动看门狗** (不进力控模式)。

    为什么: 实测 2026-10-20 19:05~19:10 连续 5 次, 只要 fcStart 起力控(即使 K_z=2000/20000、不加李萨如),
    在"模块顶在孔口"这种硬接触状态下控制器都会判 `41451 Cart Velocity OverLimit` 直接下电。
    力控的目的是"柔顺+限力", 但这里我们只要"慢推 + 力不超红线", 那就:
      · 力控全程不启动 ⇒ 没有力控速度保护
      · 位置模式 MoveL, 慢到 0.45~0.9mm/s
      · 用 getEndTorque 只读做看门狗: 静止基线取一次, 运动中每 20ms 比 Δfz, 超阈立即 r.stop()
    红线: 插入力 ≤40N, 本模式默认 30N 停手(留 10N 余量)。
    """
    out = {"mode": "push", "ip": IP, "args": vars(a)}
    p0, rpy = read_pose(r)
    R = rpy2R(rpy)
    zaxis = [R[0][2], R[1][2], R[2][2]]
    out.update({"start_pose": [round(v, 6) for v in p0], "tool_z": [round(v, 4) for v in zaxis],
                "travel_mm": a.travel_mm, "stop_n": a.stop_n})
    log("起点 TCP=[%.5f, %.5f, %.5f] · 工具Z=[%+.3f,%+.3f,%+.3f]" % (p0[0], p0[1], p0[2], *zaxis))

    fc = r.forceControl()
    bufs = make_buffers()
    base = None
    for _ in range(6):
        base = read_force(fc, bufs, x.FrameType.tool)
        time.sleep(0.08)
    out["fz_baseline"] = round(base[2], 3)
    log("静止力基线(仅监测用, 未进力控): F=[%+.2f, %+.2f, %+.2f]N" % base[:3])

    os.makedirs(EVID_DIR, exist_ok=True)
    csv_path = os.path.join(EVID_DIR, "push_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    wr = csv.writer(cf); wr.writerow(["t", "x", "y", "z", "fz", "dfz", "adv_mm", "dlat", "dtq"])
    rows, verdict, peak = [], "?", 0.0
    try:
        ec = {}
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec); chk(ec, "mode")
        tgt = [p0[i] + zaxis[i] * a.travel_mm / 1000.0 for i in range(3)]
        cp = x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy])
        out["target"] = [round(v, 6) for v in tgt]
        log("目标=[%.5f, %.5f, %.5f] · 推进 %.1fmm · speed=%.1f(≈%.2fmm/s) · 力阈 %.1fN(红线 %.0fN)"
            % (tgt[0], tgt[1], tgt[2], a.travel_mm, a.speed, a.speed * 0.45, a.stop_n, FZ_HARD_N))
        ec = {}; r.moveReset(ec)
        ec = {}; r.setDefaultSpeed(a.speed, ec)
        ec = {}
        r.moveAppend(x.MoveLCommand(cp, a.speed, -1), x.PyString("push_%d" % int(time.time() * 1000 % 1e9)), ec)
        chk(ec, "moveAppend")
        ec = {}; r.moveStart(ec); chk(ec, "moveStart")
        t0 = time.time()
        limit = min(a.stop_n, FZ_TRIP_N)
        while True:
            time.sleep(0.02)
            p, _ = read_pose(r)
            f = read_force(fc, bufs, x.FrameType.tool)
            dfz = abs(f[2] - base[2])
            # 侧向力: 老倪 19:1x「注意不要有侧向力」⇒ 侧向一涨就停, 不靠轴向阈值兜
            dlat = math.hypot(f[0] - base[0], f[1] - base[1])
            dtq = max(abs(f[3] - base[3]), abs(f[4] - base[4]), abs(f[5] - base[5]))
            adv = sum((p[i] - p0[i]) * zaxis[i] for i in range(3)) * 1000.0
            rows.append((time.time() - t0, adv, f[2], dfz))
            wr.writerow([round(rows[-1][0], 4), round(p[0], 6), round(p[1], 6), round(p[2], 6),
                         round(f[2], 3), round(dfz, 3), round(adv, 3), round(dlat, 3), round(dtq, 3)])
            peak = max(peak, dfz)
            if dtq > a.lissa_tq_max:
                verdict = "torque_stop (力矩 Δ%.2fNm > %.1fNm ⇒ 停)" % (dtq, a.lissa_tq_max)
                log("🛑 " + verdict)
                try:
                    r.stop({})
                except Exception:                                        # noqa: BLE001
                    pass
                break
            if dlat > a.lat_max:
                verdict = "lateral_stop (侧向合力 Δ=%.1fN > %.0fN ⇒ 停)" % (dlat, a.lat_max)
                log("🛑 " + verdict)
                try:
                    r.stop({})
                except Exception:                                        # noqa: BLE001
                    pass
                break
            if dfz > limit:
                verdict = "force_stop (ΔFz=%.1fN ≥ %.1fN ⇒ 停手)" % (dfz, limit)
                log("🛑 " + verdict)
                try:
                    r.stop({})
                except Exception:                                        # noqa: BLE001
                    pass
                break
            if abs(adv) >= abs(a.travel_mm) - 0.2:
                verdict = "target_reached (推进 %.2fmm, 力峰值 %.1fN)" % (adv, peak)
                break
            if "idle" in str(r.operationState({})) and abs(adv) > 0.05 and time.time() - t0 > 1.0:
                verdict = "motion_done (推进 %.2fmm, 力峰值 %.1fN)" % (adv, peak)
                break
            if time.time() - t0 > a.timeout:
                verdict = "timeout (%.0fs, 推进 %.2fmm, 力峰值 %.1fN)" % (time.time() - t0, adv, peak)
                break
    finally:
        try:
            r.stop({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.moveReset({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.setMotionControlMode(x.MotionControlMode.Idle, {})
        except Exception:                                                # noqa: BLE001
            pass
        cf.close()

    p1, _ = read_pose(r)
    out.update({"verdict": verdict, "end_pose": [round(v, 6) for v in p1],
                "adv_toolz_mm": round(sum((p1[i] - p0[i]) * zaxis[i] for i in range(3)) * 1000, 3),
                "force_peak_n": round(peak, 2), "csv": csv_path, "n": len(rows)})
    log("结果: %s" % verdict)
    log("沿轴推进 %.2fmm · ΔFz 峰值 %.1fN (红线 %.0fN)" % (out["adv_toolz_mm"], peak, FZ_HARD_N))
    return (0 if verdict.startswith(("target_reached", "motion_done")) else 1), out


def fc_scan(r, a):
    """力扫描找中心 (不用视觉, 不盲推): 在当前点周围沿工具 X/Y 走 5 点十字,
    每点只做 0.5mm 级微动, 到位静止后读六维力, 输出各点 |F_lat| / fz, 取最小的方向作中心偏置。
    只读力 + 毫米级微动, 全程不进力控, 不做大位移。
    """
    out = {"mode": "scan", "args": vars(a)}
    p0, rpy = read_pose(r)
    R = rpy2R(rpy)
    ux = [R[i][0] for i in range(3)]
    uy = [R[i][1] for i in range(3)]
    fc = r.forceControl(); bufs = make_buffers()
    def rd():
        f = read_force(fc, bufs, x.FrameType.tool)
        return [round(float(v), 3) for v in f]
    def goto(pt, speed=1):
        ec = {}
        r.moveReset(ec)
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in pt], [float(v) for v in rpy]), speed, -1),
                     x.PyString("scan"), ec)
        ec = {}
        r.moveStart(ec)
        t0 = time.time()
        while time.time() - t0 < 8.0:
            time.sleep(0.03)
            if "idle" in str(r.operationState({})) and time.time() - t0 > 0.35:
                break
        time.sleep(0.15)
        return read_pose(r)[0]
    d = a.scan_mm / 1000.0
    pts = [("中心", 0, 0), ("+X", d, 0), ("-X", -d, 0), ("+Y", 0, d), ("-Y", 0, -d)]
    rows = []
    base = rd()
    log("扫描前基线: F=[%+.2f,%+.2f,%+.2f]N T=[%+.2f,%+.2f,%+.2f]Nm" % tuple(base))
    for name, ex, ey in pts:
        tgt = [p0[i] + ux[i] * ex + uy[i] * ey for i in range(3)]
        goto(tgt)
        f = rd()
        dlat = math.hypot(f[0] - base[0], f[1] - base[1])
        dtq = max(abs(f[3] - base[3]), abs(f[4] - base[4]), abs(f[5] - base[5]))
        rows.append({"点": name, "Δlat_N": round(dlat, 2), "fz": f[2], "Δtq_Nm": round(dtq, 2)})
        log("  %-3s → 侧向 Δ%5.2fN · fz %+7.2fN · 力矩 Δ%5.2fNm" % (name, dlat, f[2], dtq))
    goto(p0, speed=1)
    out["rows"] = rows
    out["best"] = min([x for x in rows if x["点"] != "中心"], key=lambda z: z["Δlat_N"])["点"] if len(rows) > 1 else "?"
    log("最小侧向点 = %s ⇒ 中心偏置朝该方向" % out["best"])
    return 0, out


def unload_after_stop(r, mm=1.5):
    """力停手后**必须回退一点卸力** —— 2026-10-20 20:0x 实测: stop() 只是保持位置,
    模块楔在孔里时伺服一直顶着, 六维力从 36N 涨到 179N 且自己不会掉。回退 3mm 后立刻回到 12.6N。
    所以任何 force/axial/lateral/torque_stop 之后都自动慢退 mm 毫米。返回回退后的 |F|。
    """
    try:
        p0, rpy = read_pose(r)
        ec = {}
        r.moveReset(ec)
        back = [p0[0], p0[1], p0[2]]
        # 沿工具 -Z 退 (工具 Z ≈ 插入轴)
        R = rpy2R(rpy)
        uz = [R[i][2] for i in range(3)]
        tgt = [p0[i] - uz[i] * mm / 1000.0 for i in range(3)]
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in tgt], [float(v) for v in rpy]), 1, -1),
                     x.PyString("unload"), ec)
        ec = {}
        r.moveStart(ec)
        t0 = time.time()
        while time.time() - t0 < 6.0:
            time.sleep(0.05)
            if "idle" in str(r.operationState({})) and time.time() - t0 > 0.4:
                break
        r.stop({})
        fc = r.forceControl(); bufs = make_buffers()
        f = read_force(fc, bufs, x.FrameType.tool)
        mag = math.sqrt(f[0] ** 2 + f[1] ** 2 + f[2] ** 2)
        log("↩ 自动卸力: 沿轴退 %.1fmm ⇒ |F|=%.1fN" % (mm, mag))
        return mag
    except Exception as e:                                                    # noqa: BLE001
        log("⚠️ 自动卸力失败: %r" % (e,))
        return None


def fc_lissa(r, a):
    """李萨如找孔/插入 —— **位置空间**自实现 (不动控制器力控, 避开 41451 下电)。

    为什么不用 `setLissajousOverlay`: 实测 2026-10-20 19:02~19:12 连续 5 次, 只要 fcStart 起力控
    或起 overlay, 在"模块顶在孔口"状态下控制器就判 `41451 Cart Velocity OverLimit` 直接下电。
    所以李萨如轨迹在这里用**位置空间采样点**生成 (X/Y 两个正交正弦, 频率比 f1:f2), 用 MoveL 连排队走,
    六维力只做**被动看门狗**(不进力控模式 ⇒ 不会触发那个保护):

      轴向(工具 Z)  |Δfz| ≥ stop_n   → 停 (默认 30N, 硬红线 40N)
      侧向(工具XY)  hypot(Δfx,Δfy) ≥ lat_max → 停 (默认 6N, 防划伤)
      力矩(tx,ty,tz) |Δ| ≥ tq_max   → 停 (默认 1.5Nm, 防别劲)
    """
    out = {"mode": "lissa", "ip": IP, "args": vars(a)}
    p0, rpy = read_pose(r)
    R = rpy2R(rpy)
    uz = [R[i][2] for i in range(3)]
    ux = [R[i][0] for i in range(3)]
    uy = [R[i][1] for i in range(3)]
    out.update({"start_pose": [round(v, 6) for v in p0], "tool_z": [round(v, 4) for v in uz]})
    log("起点 TCP=[%.5f, %.5f, %.5f] · 工具Z=[%+.3f,%+.3f,%+.3f]" % (p0[0], p0[1], p0[2], *uz))

    fc = r.forceControl()
    bufs = make_buffers()
    base = None
    for _ in range(6):
        base = read_force(fc, bufs, x.FrameType.tool)
        time.sleep(0.08)
    log("六维力静止基线(仅看门狗): F=[%+.2f,%+.2f,%+.2f]N T=[%+.2f,%+.2f,%+.2f]Nm" % (base[0], base[1], base[2], base[3], base[4], base[5]))

    # —— 李萨如路径点 (轴向 step 推进 + 两轴正交正弦) ——
    n = max(1, int(round(abs(a.travel_mm) / a.lissa_step)))
    seg_s = max(0.08, a.lissa_step / max(0.05, a.speed * 0.45))     # 每段时长
    sgn = 1.0 if a.travel_mm >= 0 else -1.0
    def mkpt(i, ox=0.0, oy=0.0):
        """第 i 段的位姿点: 轴向 i*step + 李萨如正弦 + 导纳偏置 ox/oy (mm)。"""
        t = i * seg_s
        lx = a.lissa_amp * math.sin(2 * math.pi * a.lissa_f1 * t) + ox
        ly = a.lissa_amp * math.sin(2 * math.pi * a.lissa_f2 * t + math.pi / 2.0) + oy
        d = sgn * a.lissa_step * i / 1000.0
        return [p0[k] + uz[k] * d + ux[k] * lx / 1000.0 + uy[k] * ly / 1000.0 for k in range(3)]

    def mkcmd(i, ox=0.0, oy=0.0):
        return x.MoveLCommand(x.CartesianPosition([float(v) for v in mkpt(i, ox, oy)],
                                                  [float(v) for v in rpy]), a.speed, -1)
    out.update({"n_points": n, "seg_s": round(seg_s, 3), "amp_lat_mm": a.lissa_amp,
                "f1": a.lissa_f1, "f2": a.lissa_f2, "end_target": [round(v, 6) for v in mkpt(n)]})
    log("李萨如: 轴向 %.1fmm = %d 段 × %.2fmm · 侧向正弦 ±%.2fmm @ %.2f/%.2fHz · 总时长 ≈%.1fs"
        % (a.travel_mm, n, a.lissa_step, a.lissa_amp, a.lissa_f1, a.lissa_f2, n * seg_s))
    log("看门狗: 轴向 %.0fN / 侧向 %.0fN / 力矩 %.1fNm (硬红线 轴向 %.0fN)"
        % (min(a.stop_n, FZ_TRIP_N), a.lat_max, a.lissa_tq_max, FZ_HARD_N))

    os.makedirs(EVID_DIR, exist_ok=True)
    csv_path = os.path.join(EVID_DIR, "lissa_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    cf = open(csv_path, "w", newline="", encoding="utf-8")
    wr = csv.writer(cf)
    wr.writerow(["t", "x", "y", "z", "dfz", "dlat", "dtq", "fx", "fy", "fz", "tx", "ty", "tz", "adv_mm"])
    verdict, peak_a, peak_l, peak_t = "?", 0.0, 0.0, 0.0
    try:
        ec = {}
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec); chk(ec, "mode")
        ec = {}; r.moveReset(ec)
        ec = {}; r.setDefaultSpeed(a.speed, ec)
        nm = x.PyString("lissa_%d" % int(time.time() * 1000 % 1e9))
        ec = {}
        r.moveAppend(mkcmd(1), nm, ec); chk(ec, "moveAppend[0]")
        t0 = time.time()
        ec = {}; r.moveStart(ec); chk(ec, "moveStart")
        # 姿态跟踪: 已经有 n 段排好; 边跑边补 (保持队列不空)
        qi = 2
        ox = oy = 0.0
        tprev = time.time()
        while True:
            time.sleep(0.02)
            p, _ = read_pose(r)
            f = read_force(fc, bufs, x.FrameType.tool)
            dfz = abs(f[2] - base[2])
            dlat = math.hypot(f[0] - base[0], f[1] - base[1])
            dtq = max(abs(f[3] - base[3]), abs(f[4] - base[4]), abs(f[5] - base[5]))
            adv = sum((p[i] - p0[i]) * uz[i] for i in range(3)) * 1000.0
            peak_a, peak_l, peak_t = max(peak_a, dfz), max(peak_l, dlat), max(peak_t, dtq)
            wr.writerow([round(time.time() - t0, 4), round(p[0], 6), round(p[1], 6), round(p[2], 6),
                         round(dfz, 3), round(dlat, 3), round(dtq, 3), round(f[0], 3), round(f[1], 3),
                         round(f[2], 3), round(f[3], 3), round(f[4], 3), round(f[5], 3), round(adv, 3)])
            if dfz > min(a.stop_n, FZ_TRIP_N):
                verdict = "axial_stop (轴向 Δ%.1fN ≥ %.0fN ⇒ 停)" % (dfz, min(a.stop_n, FZ_TRIP_N)); break
            if dlat > a.lat_max:
                verdict = "lateral_stop (侧向 Δ%.1fN ≥ %.0fN ⇒ 停, 防划伤)" % (dlat, a.lat_max); break
            if dtq > a.lissa_tq_max:
                verdict = "torque_stop (力矩 Δ%.2fNm ≥ %.1fNm ⇒ 停, 别劲)" % (dtq, a.lissa_tq_max); break
            # —— 侧向导纳: 六维力里的侧向分量把轨迹往"减力"方向挪 (k mm/N/s), 主动居中, 减少贴壁摩擦
            tn = time.time(); dtl = max(1e-3, tn - tprev); tprev = tn
            if a.lissa_adm_k > 0:
                ox = max(-a.lissa_adm_max, min(a.lissa_adm_max, ox - a.lissa_adm_k * (f[0] - base[0]) * dtl))
                oy = max(-a.lissa_adm_max, min(a.lissa_adm_max, oy - a.lissa_adm_k * (f[1] - base[1]) * dtl))
            if qi <= n and adv > 0:
                try:
                    ec2 = {}
                    r.moveAppend(mkcmd(qi, ox, oy), x.PyString("lissa_%d" % qi), ec2)
                    if not ec2 or ec2.get("ec", 0) == 0:
                        qi += 1
                except Exception:                                        # noqa: BLE001
                    pass
            if "idle" in str(r.operationState({})) and qi > n and time.time() - t0 > 0.5:
                verdict = "done (走完全程 %.2fmm)" % adv; break
            if time.time() - t0 > a.timeout:
                verdict = "timeout (%.0fs, 推进 %.2fmm)" % (time.time() - t0, adv); break
        if not verdict.startswith(("done", "timeout")):
            try:
                r.stop({})
            except Exception:                                            # noqa: BLE001
                pass
            out["unload_after_N"] = unload_after_stop(r, 1.5)
    finally:
        try:
            r.stop({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.moveReset({})
        except Exception:                                                # noqa: BLE001
            pass
        try:
            r.setMotionControlMode(x.MotionControlMode.Idle, {})
        except Exception:                                                # noqa: BLE001
            pass
        cf.close()

    p1, _ = read_pose(r)
    out.update({"verdict": verdict, "end_pose": [round(v, 6) for v in p1],
                "adv_toolz_mm": round(sum((p1[i] - p0[i]) * uz[i] for i in range(3)) * 1000, 3),
                "peak_axial_n": round(peak_a, 2), "peak_lateral_n": round(peak_l, 2),
                "peak_torque_nm": round(peak_t, 3), "csv": csv_path,
                "adm_offset_mm": [round(ox, 3), round(oy, 3)]})
    log("结果: %s" % verdict)
    log("沿轴推进 %.2fmm · 峰值 轴向 %.1fN / 侧向 %.1fN / 力矩 %.2fNm" % (out["adv_toolz_mm"], peak_a, peak_l, peak_t))
    return (0 if verdict.startswith(("done", "axial_stop", "lateral_stop", "torque_stop")) else 1), out


def quat2rpy(q):
    """quat(x,y,z,w) → rpy(ZYX, 与控制器 cp.rpy 同口径, 已实测一致)。"""
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    s2 = max(-1.0, min(1.0, 2 * (w * y - z * x)))
    pitch = math.asin(s2)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [roll, pitch, yaw]


def load_point(name):
    """从示教台账读点位 (data/skills/l2_atomic/taught_points.json)。"""
    st = json.load(open(os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json"), encoding="utf-8"))
    p = (st.get("points") or {}).get(name)
    if not p:
        raise SystemExit("❌ 点位不存在: %s" % name)
    return p


def fc_seat(r, a):
    """一步直插到示教点位 (默认 插入到位_1020c) + 力看门狗兜底。

    两段一次排队: 先快走到 seat 沿轴退 approach_mm 处(自由段, speed 快), 再以低速直插到 seat。
    全程只读 getEndTorque 做被动看门狗 (不进力控 ⇒ 不会 41451 下电):
        轴向 Δfz ≥ stop_n(30N) / 硬红线 FZ_HARD_N(40N) · 侧向 ≥ lat_max(10N) · 力矩 ≥ tq_max(3Nm) → stop
    """
    if a.seat_pos:
        pos = [float(v) for v in a.seat_pos.split(",")]
        rpy = [float(v) for v in (a.seat_rpy or "").split(",")]
        if len(rpy) != 3:
            raise SystemExit("❌ --seat-rpy 需要 r,p,y 三个数 (rad)")
    else:
        pt = load_point(a.point)
        pos = [float(v) for v in pt["pos"]]
        rpy = quat2rpy(pt["quat"])
    out = {"mode": "seat", "point": a.point, "ip": IP, "seat_pos": [round(v, 6) for v in pos],
           "seat_rpy": [round(v, 4) for v in rpy], "args": vars(a)}
    R = rpy2R(rpy)
    uz = [R[i][2] for i in range(3)]
    p0, _ = read_pose(r)
    log("目标点位 %s = [%.5f, %.5f, %.5f] (轴向前置 %.1fmm)" % (a.point, pos[0], pos[1], pos[2], a.approach_mm))
    log("起点 TCP=[%.5f, %.5f, %.5f] · 距点位 %.2fmm" %
        (p0[0], p0[1], p0[2], 1000 * math.dist(p0, pos)))
    appr = [pos[i] - uz[i] * a.approach_mm / 1000.0 for i in range(3)]
    out["approach_pos"] = [round(v, 6) for v in appr]

    fc = r.forceControl(); bufs = make_buffers()
    base = None
    for _ in range(6):
        base = read_force(fc, bufs, x.FrameType.tool); time.sleep(0.08)
    log("六维力基线(看门狗): F=[%+.2f,%+.2f,%+.2f]N T=[%+.2f,%+.2f,%+.2f]Nm" % tuple(base))

    os.makedirs(EVID_DIR, exist_ok=True)
    csv_path = os.path.join(EVID_DIR, "seat_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    cf = open(csv_path, "w", newline="", encoding="utf-8"); wr = csv.writer(cf)
    wr.writerow(["t", "x", "y", "z", "dfz", "dlat", "dtq", "adv_mm", "phase"])
    verdict, peak_a, peak_l, peak_t = "?", 0.0, 0.0, 0.0
    try:
        ec = {}; r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec); chk(ec, "mode")
        ec = {}; r.moveReset(ec)
        # 已经在接近点之前(更深)就不要往回退: 只按轴向投影判断, 避免多走一段反向行程(实测 19:33 就是退出去时撞上卡扣)
        past = sum((p0[i] - appr[i]) * uz[i] for i in range(3)) > 0.0
        out["skip_approach"] = bool(past)
        if past:
            log("已在接近点之前(更深 %.2fmm) ⇒ 跳过接近段, 直接慢插" % (1000 * sum((p0[i] - appr[i]) * uz[i] for i in range(3))))
        else:
            ec = {}
            r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in appr], [float(v) for v in rpy]),
                                        a.fast_speed, -1), x.PyString("seat_appr"), ec)
            chk(ec, "moveAppend[approach]")
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([float(v) for v in pos], [float(v) for v in rpy]),
                                    a.speed, -1), x.PyString("seat_final"), ec)
        chk(ec, "moveAppend[seat]")
        t0 = time.time(); ec = {}; r.moveStart(ec); chk(ec, "moveStart")
        limit = min(a.stop_n, FZ_TRIP_N)
        while True:
            time.sleep(0.02)
            p, _ = read_pose(r)
            f = read_force(fc, bufs, x.FrameType.tool)
            dfz = abs(f[2] - base[2])
            dlat = math.hypot(f[0] - base[0], f[1] - base[1])
            dtq = max(abs(f[3] - base[3]), abs(f[4] - base[4]), abs(f[5] - base[5]))
            adv = 1000.0 * sum((p[i] - p0[i]) * uz[i] for i in range(3))
            phase = "approach" if math.dist(p, appr) > 0.0005 else "seat"
            peak_a, peak_l, peak_t = max(peak_a, dfz), max(peak_l, dlat), max(peak_t, dtq)
            wr.writerow([round(time.time() - t0, 4), round(p[0], 6), round(p[1], 6), round(p[2], 6),
                         round(dfz, 3), round(dlat, 3), round(dtq, 3), round(adv, 3), phase])
            if dfz > limit:
                verdict = "axial_stop (轴向 Δ%.1fN ≥ %.0fN ⇒ 停, 未到点位)" % (dfz, limit); break
            if dlat > a.lat_max:
                verdict = "lateral_stop (侧向 Δ%.1fN ≥ %.0fN ⇒ 停, 防划伤)" % (dlat, a.lat_max); break
            if dtq > a.lissa_tq_max:
                verdict = "torque_stop (力矩 Δ%.2fNm ≥ %.1fNm ⇒ 停, 别劲)" % (dtq, a.lissa_tq_max); break
            if math.dist(p, pos) < 0.00035:
                verdict = "reached (到点位, 指令误差 %.2fmm)" % (1000 * math.dist(p, pos)); break
            if time.time() - t0 > a.timeout:
                verdict = "timeout (%.0fs, 距点位 %.2fmm)" % (time.time() - t0, 1000 * math.dist(p, pos)); break
        if verdict.startswith(("axial_stop", "lateral_stop", "torque_stop", "timeout")):
            try:
                r.stop({})
            except Exception:                                            # noqa: BLE001
                pass
    finally:
        try: r.stop({})
        except Exception: pass                                           # noqa: BLE001
        try: r.moveReset({})
        except Exception: pass                                           # noqa: BLE001
        try: r.setMotionControlMode(x.MotionControlMode.Idle, {})
        except Exception: pass                                           # noqa: BLE001
        cf.close()

    p1, _ = read_pose(r)
    out.update({"verdict": verdict, "end_pose": [round(v, 6) for v in p1],
                "err_mm": round(1000 * math.dist(p1, pos), 3),
                "peak_axial_n": round(peak_a, 2), "peak_lateral_n": round(peak_l, 2),
                "peak_torque_nm": round(peak_t, 3), "csv": csv_path})
    log("结果: %s" % verdict)
    log("到点位误差 %.2fmm · 峰值 轴向 %.1fN / 侧向 %.1fN / 力矩 %.2fNm" %
        (1000 * math.dist(p1, pos), peak_a, peak_l, peak_t))
    return (0 if verdict.startswith("reached") else 1), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["probe", "zero", "step", "insert", "advance", "search", "push", "lissa", "seat", "scan"], default="probe")
    ap.add_argument("--force", type=float, default=6.0, help="期望压入的轴向力 N (产线 6N)")
    ap.add_argument("--stop-n", type=float, default=5.5, help="|Fz| 达到即判『压到位』")
    ap.add_argument("--watchdog-n", type=float, default=25.0, help="任一方向力超此值立刻停")
    ap.add_argument("--amp1", type=float, default=6.0, help="李萨如方向1幅值 mm (产线 6mm)")
    ap.add_argument("--freq1", type=float, default=3.0)
    ap.add_argument("--amp2", type=float, default=4.0)
    ap.add_argument("--freq2", type=float, default=2.0)
    ap.add_argument("--phase", type=float, default=math.pi / 2)
    ap.add_argument("--plane", type=int, default=0, help="0=XY 1=XZ 2=YZ")
    ap.add_argument("--max-mm", type=float, default=50.0)
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--stiffness", type=float, nargs=6, default=[6000, 6000, 0, 300, 300, 100])
    ap.add_argument("--maxvel", type=float, nargs=6, default=[0.15, 0.15, 0.01, 0.5, 0.5, 0.5])
    ap.add_argument("--no-calibrate", dest="calibrate", action="store_false")
    ap.add_argument("--lat-mm", type=float, default=2.0, help="李萨如 XY 幅值 mm (自己算, 不受 SDK 力口径影响)")
    ap.add_argument("--f1", type=float, default=0.7)
    ap.add_argument("--f2", type=float, default=1.1)
    ap.add_argument("--cyc-s", type=float, default=0.6, help="每周期时长 s (含运动)")
    ap.add_argument("--step-mm", type=float, default=0.5, help="每周期沿轴前进 mm")
    ap.add_argument("--back-mm", type=float, default=4.0, help="开始前先退多少 mm 解除顶压")
    ap.add_argument("--max-stuck", type=int, default=8, help="连续顶超阈几次就判卡死")
    ap.add_argument("--mouth-x", type=float, default=0.75929, help="插入口 x (用于报深度)")
    ap.add_argument("--travel-mm", type=float, default=15.0, help="本段沿工具Z推进的行程 mm")
    ap.add_argument("--speed", type=float, default=30.0, help="SDK speed (≈0.0999mm/s) ⇒ 30≈3mm/s")
    ap.add_argument("--lissa-step", type=float, default=0.2, help="李萨如每段轴向步长 mm")
    ap.add_argument("--lissa-amp", type=float, default=0.4, help="李萨如侧向幅值 mm")
    ap.add_argument("--lissa-f1", type=float, default=0.7, help="侧向正弦 1 频率 Hz")
    ap.add_argument("--lissa-f2", type=float, default=1.1, help="侧向正弦 2 频率 Hz (与 f1 正交)")
    ap.add_argument("--scan-mm", type=float, default=0.5, help="力扫描每点偏移 mm")
    ap.add_argument("--seat-pos", default="", help="目标 x,y,z (m), 给了就不读点位文件 (容器内没有 data/)")
    ap.add_argument("--seat-rpy", default="", help="目标 r,p,y (rad)")
    ap.add_argument("--point", default="插入到位_1020c", help="一步直插的目标示教点")
    ap.add_argument("--approach-mm", type=float, default=12.0, help="先快走到点位沿轴外多少 mm 再慢插")
    ap.add_argument("--fast-speed", type=float, default=8.0, help="接近段速度 (≈3.6mm/s)")
    ap.add_argument("--lissa-adm-k", type=float, default=0.05, help="侧向导纳增益 mm/N/s (0=关)")
    ap.add_argument("--lissa-adm-max", type=float, default=1.2, help="导纳偏置饱和 mm")
    ap.add_argument("--lissa-tq-max", type=float, default=1.5, help="力矩增量上限 Nm (超则停)")
    ap.add_argument("--lat-max", type=float, default=8.0, help="侧向合力上限 N (一超就停)")
    ap.add_argument("--no-lissajous", dest="lissajous", action="store_false")
    ap.add_argument("--no-auto-load", dest="auto_load", action="store_false", help="不自动反解工具负载")
    a = ap.parse_args()
    if a.watchdog_n > FZ_TRIP_N:
        print("[!] --watchdog-n=%.0fN 超过红线: 现场要求插入力 ≤%.0fN ⇒ 实际按 %.0fN 停手"
              % (a.watchdog_n, FZ_HARD_N, FZ_TRIP_N), flush=True)
        a.watchdog_n = FZ_TRIP_N
    if a.stop_n > FZ_TRIP_N:
        a.stop_n = FZ_TRIP_N

    r = x.xMateRobot()
    # 🔴 2026-10-20 20:0x 事故: 上一会话被 kill -9 打断时, 控制器里**残留的 MoveL 队列**会在新会话
    #   moveStart 时继续跑(实测一次退了 150mm)。⇒ 任何模式开动前先: stop() → moveReset() → 必须静止。
    try:
        _ec = {}
        r.stop(_ec)
        _ec = {}
        r.moveReset(_ec)
        import time as _t
        _t.sleep(0.4)
        _p1 = r.robotState().getTCPPose() if hasattr(r, "robotState") else None
        _a = read_pose(r)[0]
        _t.sleep(0.25)
        _b = read_pose(r)[0]
        _d = max(abs(_b[i] - _a[i]) for i in range(3)) * 1000.0
        if _d > 0.05:
            print("[!] 上电后仍有残留运动: 0.25s 内位移 %.2fmm ⇒ 不发出任何新指令, 先查现场" % _d, flush=True)
            return 3
    except Exception as _e:                                                  # noqa: BLE001
        print("[!] 预静止检查异常(继续): %r" % (_e,), flush=True)
    try:
        r.connectToRobot(IP)
    except Exception as e:                                                # noqa: BLE001
        log("⛔ 连不上控制器 %s: %s" % (IP, e))
        return 3
    try:
        if a.mode == "probe":
            out = {"mode": "probe", "state": read_state(r), "pose": dict(zip(("tcp", "rpy"), read_pose(r))),
                   "still": wait_still(r)}
            bufs = make_buffers()
            fc = r.forceControl()
            f = read_force(fc, bufs, x.FrameType.tool)
            out["force_tool"] = [round(v, 3) for v in f]
            out["has"] = {n: hasattr(fc, n) for n in
                          ("fcInit", "fcStart", "fcStop", "setCartesianDesiredForce", "setCartesianStiffness",
                           "setCartesianMaxVel", "setLissajousOverlay", "startOverlay", "stopOverlay",
                           "setForceCondition", "setPoseBoxCondition", "waitCondition")}
            try:
                ts = r.toolset({})
                out["toolset"] = {"load_mass": float(ts.load.mass), "load_cog": [float(v) for v in ts.load.cog],
                                  "end_trans": [round(float(v), 5) for v in ts.end.trans],
                                  "ref_trans": [round(float(v), 5) for v in ts.ref.trans]}
            except Exception as e:                                       # noqa: BLE001
                out["toolset_err"] = str(e)[:160]
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
            write_evid(out, "probe")
            return 0

        err = preflight(r)
        if err:
            log("🛑 前置不满足: %s ⇒ 一条也不发" % err)
            return 4
        if not wait_still(r):
            log("🛑 没停稳 ⇒ 不发")
            return 4
        if a.mode == "scan":
            code, out = fc_scan(r, a)
            write_evid(out, "scan")
            return code
        if a.mode == "seat":
            code, out = fc_seat(r, a)
            write_evid(out, "seat")
            return code
        if a.mode == "lissa":
            code, out = fc_lissa(r, a)
            write_evid(out, "lissa")
            return code
        if a.mode == "push":
            code, out = fc_push(r, a)
            write_evid(out, "push")
            return code
        if a.mode == "search":
            code, out = fc_search(r, a)
            write_evid(out, "search")
            return code
        if a.mode == "advance":
            code, out = fc_advance(r, a)
            write_evid(out, "advance")
            return code
        code, out = fc_run(r, a, a.mode)
        write_evid(out, a.mode)
        return code
    except RuntimeError as e:                                             # noqa: BLE001
        log("🛑 %s" % e)
        try:
            r.forceControl().fcStop({})
        except Exception:                                                 # noqa: BLE001
            pass
        write_evid({"mode": a.mode, "error": str(e)[:400], "fatal": True}, "error")
        return 5
    finally:
        try:
            r.disconnectFromRobot({})
        except Exception:                                                 # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
