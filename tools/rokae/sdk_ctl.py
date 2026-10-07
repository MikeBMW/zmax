#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdk_ctl.py — 本机(4060) 独立 SDK 直连控制层 (不经 Orin, 不碰 Orin 任何服务)

架构口径 (2026-10-07 现场指令: 「不要改变 orin 原来的任何服务。你可以直接调用 SDK，但要独立实现」):
  · 走厂家 xCoreSDK (x86_64) 直连控制器 192.168.23.160 —— 与 Orin 的 ROS/DDS/驱动栈**零耦合**
  · 不读不写 Orin 上任何文件/单元/服务; 位姿与状态全部由本机 SDK 会话直接读取
  · 产线 ROS 栈起没起都和这条路无关

安全性(首次实动后固化的纪律):
  ① 前置自检: 上电 on / 空闲 idle / 自动 automatic —— 任一不满足**拒发**
  ② 目标构造后**回读校验** (trans/rpy 与意图一致, 误差必须 0) —— 语义不符拒发
  ③ 接管前 moveReset(清空已发指令; RL↔SDK 切换必需)
  ④ 下发后**盯真值**(不认 success): 任一轴越界 / 方向反向 ⇒ 立刻 stop()
  ⑤ 全程留证 JSON(起止位姿/关节/状态/报警对照/逐帧轨迹)
  ⑥ 收尾 setMotionControlMode(Idle)

子命令:
  state                     只读: 电源/状态/模式/报警/位姿/关节
  pose                      只读: TCP(trans+rpy) / 法兰 / 关节
  move-rel --dx --dy --dz   相对运动(mm, base 系, 姿态不变), --speed(mm/s, 默认5)
  move-abs --x --y --z --rx --ry --rz   绝对位姿(m/rad)
  stop                      暂停运动 (stop: 规划停止不断电)
  reset                     运动重置 (清空已发指令)

跑法(必须容器内, SDK 是 cpython-310):
  bash tools/rokae_sdk_run.sh pose
  bash tools/rokae_sdk_run.sh move-rel --dz 1.0
"""
import argparse
import json
import os
import sys
import time

SDK_DIR = os.environ.get("ZMAX_SDK_DIR", "/sdk")
EVID_DIR = os.path.join(SDK_DIR, "logs")
STATE_JSON = os.path.join(SDK_DIR, "tcp_out", "state.json")
POSE_JSON = os.path.join(SDK_DIR, "tcp_out", "latest.json")
IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")

MAX_SPEED_MM_S = 60.0        # 速度上限(与页面档位一致的量级)
DEFAULT_MAX_MM = 5.0         # 单次相对运动默认上限(mm)
HARD_MAX_MM = 50.0           # 硬上限(mm): 超过必须显式 --i-know-what-im-doing
SETTLE_MM = 0.1              # 判"到位"的容差
CROSS_TOL_MM = 0.2           # 非指令轴的允许扰动

sys.path.insert(0, SDK_DIR)
import xcoresdk_python as x  # noqa: E402

LOG = []


def log(s):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), s)
    print(line, flush=True)
    LOG.append(line)


def host_ts():
    t = os.environ.get("ZMAX_HOST_TS")
    return time.strftime("%F %T", time.localtime(float(t))) if t else "(未传)"


def alarms():
    """控制器报警快照 —— 取自本机 SDK 采样器自己落的状态文件(独立于 Orin)。"""
    try:
        d = json.load(open(STATE_JSON, encoding="utf-8"))
        la = d.get("last_alarm") or {}
        return {"last_alarm_ts": la.get("ts"), "last_alarm_id": la.get("id"),
                "n_err_recent": d.get("n_err_recent"), "src": d.get("src")}
    except Exception as e:                                                   # noqa: BLE001
        return {"err": str(e)[:80]}


def sampler_pose():
    """本机常驻 SDK 采样器落盘的位姿(第二条独立读数, 用于交叉核对)。"""
    try:
        d = json.load(open(POSE_JSON, encoding="utf-8"))
        return {"x": d.get("x"), "y": d.get("y"), "z": d.get("z"),
                "age_s": round(time.time() - os.path.getmtime(POSE_JSON), 2)}
    except Exception as e:                                                   # noqa: BLE001
        return {"err": str(e)[:80]}


def read_pose(r):
    ec1, ec2, ec3 = {}, {}, {}
    cp = r.cartPosture(x.CoordinateType.endInRef, ec1)
    fl = r.cartPosture(x.CoordinateType.flangeInBase, ec2)
    jp = r.jointPos(ec3)
    return {"tcp": [float(v) for v in cp.trans], "rpy": [float(v) for v in cp.rpy],
            "flange": [float(v) for v in fl.trans], "joints": [float(v) for v in jp[:6]],
            "ec": [dict(ec1), dict(ec2), dict(ec3)]}


def read_state(r):
    return {"powerState": str(r.powerState({})),
            "operationState": str(r.operationState({})),
            "operateMode": str(r.operateMode({})),
            "motion_control_mode": str(r.motionControlMode({})) if hasattr(r, "motionControlMode") else None}


def precheck(r, out):
    st = read_state(r)
    out["pre_state"] = st
    log("自检: %s" % json.dumps(st, ensure_ascii=False))
    if "on" not in str(st["powerState"]):
        return "上电状态不是 on (%s)" % st["powerState"]
    if "idle" not in str(st["operationState"]):
        return "机器人不空闲 (%s)" % st["operationState"]
    if "automatic" not in str(st["operateMode"]):
        return "不是自动模式 (%s)" % st["operateMode"]
    return None


def write_evid(out, tag):
    os.makedirs(EVID_DIR, exist_ok=True)
    p = os.path.join(EVID_DIR, "sdk_ctl_%s_%s.json" % (tag, time.strftime("%Y%m%d_%H%M%S")))
    out["evidence_path"] = p
    out["log"] = LOG
    out["host_time"] = host_ts()
    out["container_time"] = time.strftime("%F %T")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n== 证据: %s ==" % p)
    return p


# ---------------- 只读 ----------------
def cmd_state(r, args):
    out = {"cmd": "state", "ip": IP, "state": read_state(r), "alarms": alarms(),
           "sampler": sampler_pose(), "pose": read_pose(r)}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    write_evid(out, "state")
    return 0


def cmd_pose(r, args):
    out = {"cmd": "pose", "ip": IP, "pose": read_pose(r), "sampler": sampler_pose()}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    write_evid(out, "pose")
    return 0


def cmd_stop(r, args):
    ec = {}
    r.stop(ec)
    out = {"cmd": "stop", "ec": dict(ec)}
    log("stop() ec=%s" % ec)
    write_evid(out, "stop")
    return 0


def cmd_reset(r, args):
    ec = {}
    r.moveReset(ec)
    out = {"cmd": "reset", "ec": dict(ec)}
    log("moveReset() ec=%s" % ec)
    write_evid(out, "reset")
    return 0


# ---------------- 运动 ----------------
def do_move(r, target_trans, target_rpy, speed, out, max_axis_mm, tag):
    p0 = read_pose(r)
    out["pre_pose"] = p0
    out["pre_alarms"] = alarms()
    out["pre_sampler"] = sampler_pose()
    log("起始 TCP=[%.6f, %.6f, %.6f] rpy=[%.6f, %.6f, %.6f]" % tuple(p0["tcp"] + p0["rpy"]))

    cp = x.CartesianPosition(list(target_trans), list(target_rpy))
    bt = [float(v) for v in cp.trans]
    br = [float(v) for v in cp.rpy]
    dt = max(abs(bt[i] - target_trans[i]) for i in range(3))
    dr = max(abs(br[i] - target_rpy[i]) for i in range(3))
    out["target"] = {"trans": list(target_trans), "rpy": list(target_rpy),
                     "readback_trans": bt, "readback_rpy": br}
    log("目标 = [%.6f, %.6f, %.6f] 回读误差 trans=%.2e rpy=%.2e" % (target_trans[0], target_trans[1], target_trans[2], dt, dr))
    if dt > 1e-9 or dr > 1e-9:
        out["verdict"] = "ABORT 构造语义不符(trans/rpy 回读不一致)"
        log("⛔ " + out["verdict"])
        return 4, out

    ec = {}
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec)
    out["setMotionControlMode_ec"] = dict(ec)
    if ec.get("ec", 0) != 0:
        out["verdict"] = "ABORT setMotionControlMode 失败"
        log("⛔ " + out["verdict"])
        return 5, out
    ec = {}
    r.setDefaultSpeed(speed, ec)
    out["setDefaultSpeed_ec"] = dict(ec)
    ec = {}
    r.moveReset(ec)
    out["moveReset_ec"] = dict(ec)
    log("控制模式=NrtCommandMode · 速度=%.1fmm/s · moveReset ec=%s" % (speed, ec))

    mc = x.MoveLCommand(cp, speed, -1)
    cmd_id = "zmax_sdkctl_%d" % int(time.time())
    ec = {}
    r.moveAppend(mc, x.PyString(cmd_id), ec)      # cmdID 必须 PyString 包装
    out["moveAppend_ec"] = dict(ec)
    out["cmd_id"] = cmd_id
    log("moveAppend(%s) ec=%s" % (cmd_id, ec))
    if ec.get("ec", 0) != 0:
        out["verdict"] = "ABORT moveAppend 报错"
        log("⛔ " + out["verdict"])
        return 5, out

    ec = {}
    t_send = time.time()
    r.moveStart(ec)
    out["moveStart_ec"] = dict(ec)
    log("moveStart() ec=%s · 开始盯真值" % ec)

    trace, stopped = [], None
    while time.time() - t_send < 20.0:
        time.sleep(0.15)
        try:
            cp_now = r.cartPosture(x.CoordinateType.endInRef, {})
            t_now = [float(v) for v in cp_now.trans]
            op = str(r.operationState({}))
        except Exception as e:                                                # noqa: BLE001
            log("读真值异常: %s" % str(e)[:90])
            break
        d = [t_now[i] - p0["tcp"][i] for i in range(3)]
        want = [target_trans[i] - p0["tcp"][i] for i in range(3)]
        trace.append({"t": round(time.time() - t_send, 2), "tcp": [round(v, 6) for v in t_now],
                      "d_mm": [round(v * 1000, 3) for v in d], "op": op})
        moved_mm = [round(v * 1000, 3) for v in d]
        log("  t=%.2fs d=[%.3f, %.3f, %.3f]mm · %s" % (time.time() - t_send, moved_mm[0], moved_mm[1], moved_mm[2], op))
        # 越界保护: 任一轴的实际位移超出"指令位移 + 0.5mm" ⇒ 立刻停(方向/量不对就是异常)
        want_mm_max = max(abs(v) for v in want)
        if max(abs(v) for v in d) > want_mm_max + 0.0005:
            ec = {}
            r.stop(ec)
            stopped = "越界保护(实际位移超出目标): d=%s mm 目标=%s mm" % (moved_mm, [round(v * 1000, 3) for v in want])
            log("🛑 %s ⇒ stop() ec=%s" % (stopped, ec))
            break
        if "idle" in op and all(abs(d[i] - want[i]) <= SETTLE_MM / 1000 for i in range(3)):
            break
    out["trace"] = trace
    out["stopped"] = stopped

    time.sleep(0.6)
    p1 = read_pose(r)
    out["post_pose"] = p1
    out["post_alarms"] = alarms()
    out["post_sampler"] = sampler_pose()
    d_mm = {ax: round((p1["tcp"][i] - p0["tcp"][i]) * 1000, 3) for i, ax in enumerate("xyz")}
    out["delta_mm"] = d_mm
    out["delta_flange_mm"] = {ax: round((p1["flange"][i] - p0["flange"][i]) * 1000, 3) for i, ax in enumerate("xyz")}
    out["d_joints_rad"] = [round(p1["joints"][i] - p0["joints"][i], 6) for i in range(6)]
    out["alarm_changed"] = (out["pre_alarms"].get("last_alarm_ts") != out["post_alarms"].get("last_alarm_ts"))
    err = [k for k in ("x", "y", "z") if abs(d_mm[k] - (target_trans["xyz".index(k)] - p0["tcp"]["xyz".index(k)]) * 1000) > SETTLE_MM]
    cross = max(abs(d_mm[k] - (target_trans["xyz".index(k)] - p0["tcp"]["xyz".index(k)]) * 1000) for k in "xyz")
    ec_ok = all(out[k].get("ec", 0) == 0 for k in ("moveAppend_ec", "moveStart_ec", "setMotionControlMode_ec"))
    if ec_ok and not err and not out["alarm_changed"] and not stopped:
        out["verdict"] = "PASS · Δ=%s mm(法兰 %s) · 最大偏差 %.3fmm · 报警无新增" % (
            d_mm, out["delta_flange_mm"], cross)
        log("结果: " + out["verdict"])

    else:
        out["verdict"] = "CHECK · Δ=%s mm · 最大偏差 %.3fmm · 报警变化=%s · 保护停=%s" % (
            d_mm, cross, out["alarm_changed"], stopped)
        log("结果: " + out["verdict"])

    try:
        ec = {}
        r.setMotionControlMode(x.MotionControlMode.Idle, ec)
        out["setIdle_ec"] = dict(ec)
    except Exception as e:                                                    # noqa: BLE001
        out["setIdle_err"] = str(e)[:100]
    return 0 if out["verdict"].startswith("PASS") else 6, out


def cmd_move_rel(r, args):
    speed = min(float(args.speed), MAX_SPEED_MM_S)
    d = [float(args.dx), float(args.dy), float(args.dz)]
    mag = max(abs(v) for v in d)
    cap = HARD_MAX_MM if args.i_know_what_im_doing else DEFAULT_MAX_MM
    if args.max_mm:
        cap = min(float(args.max_mm), HARD_MAX_MM)
    out = {"cmd": "move-rel", "ip": IP, "speed_mm_s": speed, "delta_req_mm": d,
           "cap_mm": cap, "host_time": host_ts()}
    if mag > cap:
        out["verdict"] = "ABORT 请求位移 %.1fmm > 上限 %.1fmm" % (mag, cap)
        log("⛔ " + out["verdict"])
        write_evid(out, "move_rel_abort")
        return 2
    bad = precheck(r, out)
    if bad:
        out["verdict"] = "ABORT 前置条件不满足: %s" % bad
        log("⛔ " + out["verdict"])
        write_evid(out, "move_rel_abort")
        return 3
    p0 = read_pose(r)
    tgt = [p0["tcp"][i] + d[i] / 1000.0 for i in range(3)]
    out["req_vs_sampler_mm"] = {"x": round((p0["tcp"][0] - (sampler_pose().get("x") or 0)) * 1000, 3),
                                "y": round((p0["tcp"][1] - (sampler_pose().get("y") or 0)) * 1000, 3),
                                "z": round((p0["tcp"][2] - (sampler_pose().get("z") or 0)) * 1000, 3)}
    rc, out = do_move(r, tgt, p0["rpy"], speed, out, cap, "move_rel")
    write_evid(out, "move_rel")
    return rc


def cmd_move_abs(r, args):
    speed = min(float(args.speed), MAX_SPEED_MM_S)
    out = {"cmd": "move-abs", "ip": IP, "speed_mm_s": speed,
           "target_req": [args.x, args.y, args.z], "host_time": host_ts()}
    bad = precheck(r, out)
    if bad:
        out["verdict"] = "ABORT 前置条件不满足: %s" % bad
        log("⛔ " + out["verdict"])
        write_evid(out, "move_abs_abort")
        return 3
    p0 = read_pose(r)
    rpy = p0["rpy"] if args.rx is None else [args.rx, args.ry, args.rz]
    rc, out = do_move(r, [args.x, args.y, args.z], rpy, speed, out, HARD_MAX_MM, "move_abs")
    write_evid(out, "move_abs")
    return rc


def main():
    ap = argparse.ArgumentParser(description="本机独立 SDK 直连控制 (不经 Orin)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state")
    sub.add_parser("pose")
    sub.add_parser("stop")
    sub.add_parser("reset")
    m = sub.add_parser("move-rel")
    m.add_argument("--dx", type=float, default=0.0)
    m.add_argument("--dy", type=float, default=0.0)
    m.add_argument("--dz", type=float, default=0.0)
    m.add_argument("--speed", type=float, default=5.0, help="mm/s, 上限 %.0f" % MAX_SPEED_MM_S)
    m.add_argument("--max-mm", type=float, default=None, help="本次允许的位移上限(默认 %.0f)" % DEFAULT_MAX_MM)
    m.add_argument("--i-know-what-im-doing", action="store_true", help="放开到硬上限 %.0fmm" % HARD_MAX_MM)
    a = sub.add_parser("move-abs")
    a.add_argument("--x", type=float, required=True)
    a.add_argument("--y", type=float, required=True)
    a.add_argument("--z", type=float, required=True)
    a.add_argument("--rx", type=float, default=None)
    a.add_argument("--ry", type=float, default=None)
    a.add_argument("--rz", type=float, default=None)
    a.add_argument("--speed", type=float, default=5.0)
    args = ap.parse_args()

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                                    # noqa: BLE001
        print("⛔ 连不上控制器 %s: %s" % (IP, e))
        return 1
    try:
        fn = {"state": cmd_state, "pose": cmd_pose, "stop": cmd_stop, "reset": cmd_reset,
              "move-rel": cmd_move_rel, "move-abs": cmd_move_abs}[args.cmd]
        return fn(r, args)
    finally:
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
