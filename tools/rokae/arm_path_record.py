#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_path_record.py —— 控制器端「路径录制 → 按倍率回放」(绕开主机 RT 实时性)

背景 (2026-11-21):
  主机侧 RT 流式回放受两点限制: ①容器内回调只有 ~7Hz ②切 RT 后报 19-kInstabilityDetection。
  但厂家 SDK 自带控制器端路径引擎:
      startRecordPath(duration) -> (跑轨迹) -> stopRecordPath() -> saveRecordPath(name)
      replayPath(name, rate<3.0)  + moveStart()      # rate=1 为录制原速率
  ⇒ 时间基准由控制器自己给, 与主机 jitter 无关; rate 可 >1 压时间。

用法(容器内, 由 rokae_sdk_run.sh 挂载):
  bash tools/rokae_sdk_run.sh --script arm_path_record.py record
  bash tools/rokae_sdk_run.sh --script arm_path_record.py replay      # 用 ZMAX_PR_RATE
  bash tools/rokae_sdk_run.sh --script arm_path_record.py list        # 只列控制器里的路径

环境变量:
  ZMAX_PR_NAME    路径名(默认 zmax215)
  ZMAX_PR_N       录制点数(默认 0=全部 215)
  ZMAX_PR_SPEED   录制时的 MoveAbsJ 速度%(默认 200 —— 实测上限, 400 掉电)
  ZMAX_PR_ZONE    录制时转弯区 mm(默认 3)
  ZMAX_PR_RATE    回放倍率(默认 3.0, SDK 上限 <3.0)
  ZMAX_PR_ALIGN   回放前是否先归位到第 0 点(默认 1)
  ZMAX_PR_DRY     1 = 只做前置检查, 不录不跑
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
TRAJ = os.environ.get("ZMAX_REPLAY_TRAJ") or "/sdk/real_traj_joints.json"
CMD = os.environ.get("ZMAX_REPLAY_CMD") or "/sdk/traj_step_cmd.json"
LOGDIR = os.environ.get("ZMAX_RT_LOGDIR") or "/sdk/logs"

NAME = os.environ.get("ZMAX_PR_NAME") or "zmax215"
MAX_JUMP_DEG = 40.0
PREP_SEG_DEG = 18.0
TOL_DEG = 1.5


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def joints(r):
    v = r.jointPos({})
    if isinstance(v, dict):
        for k in ("jointPos", "joint", "values", "data"):
            if k in v:
                v = v[k]
                break
        else:
            v = list(v.values())[0]
    return [float(t) for t in list(v)[:6]]


def opstate(r):
    return str(r.operationState({}))


def _as_j(f):
    if isinstance(f, dict):
        for k in ("j", "joints", "joint", "q"):
            v = f.get(k)
            if isinstance(v, (list, tuple)) and len(v) >= 6:
                return [float(t) for t in v[:6]]
        raise ValueError("帧里找不到关节角字段 keys=%s" % list(f.keys()))
    return [float(t) for t in list(f)[:6]]


def load_frames(n_env):
    src = TRAJ if os.path.isfile(TRAJ) else CMD
    d = json.load(open(src, encoding="utf-8"))
    frames = d.get("frames") or []
    if not frames:
        raise RuntimeError("轨迹没有帧: %s" % src)
    n = min(n_env or len(frames), len(frames))
    return src, d, frames[:n], n, len(frames)


def check_jumps(frames):
    prev = _as_j(frames[0])
    worst, worst_i, bad = 0.0, -1, []
    for i, f in enumerate(frames):
        jt = _as_j(f)
        jump = max(abs(math.degrees(b - a)) for a, b in zip(prev, jt))
        if jump > worst:
            worst, worst_i = jump, i
        if jump > MAX_JUMP_DEG:
            bad.append({"i": i, "jump_deg": round(jump, 2)})
        prev = jt
    return worst, worst_i, bad


def wait_idle(r, budget, poll=0.1):
    t0 = time.time()
    while time.time() - t0 < budget:
        time.sleep(poll)
        if "idle" in opstate(r).lower():
            return True, time.time() - t0
    return False, time.time() - t0


def align_to(r, target, speed=100.0, label="align"):
    """单点 MoveAbsJ 归位(精确停); <=TOL 就不动。"""
    cur = joints(r)
    jump = max(abs(math.degrees(b - a)) for a, b in zip(cur, target))
    if jump <= TOL_DEG:
        return {"aligned": True, "jump_deg": round(jump, 2), "moved": False}
    k = max(1, int(math.ceil(jump / PREP_SEG_DEG)))
    for t in range(1, k + 1):
        pj = [cur[m] + (target[m] - cur[m]) * (t / float(k)) for m in range(6)]
        r.moveReset({})
        ec = {}
        r.moveAppend([x.MoveAbsJCommand(x.JointPosition([float(v) for v in pj]), speed, -1)],
                     x.PyString("%s%d" % (label, t)), ec)
        if ec.get("ec", 0) != 0:
            raise RuntimeError("归位第 %d/%d 点被拒: %s" % (t, k, ec))
        r.moveStart({})
        ok, secs = wait_idle(r, 60.0)
        out(align_step=t, of=k, ok=ok, secs=round(secs, 2))
        if not ok:
            raise RuntimeError("归位第 %d 点超时未到位" % t)
    return {"aligned": True, "jump_deg": round(jump, 2), "moved": True, "n_seg": k}


def do_list(r):
    ec = {}
    lst = r.queryPathLists(ec)
    return {"ec": ec, "paths": list(lst) if lst is not None else []}


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "record").lstrip("-")
    dry = os.environ.get("ZMAX_PR_DRY") == "1"
    n_env = int(os.environ.get("ZMAX_PR_N") or 0)
    speed = float(os.environ.get("ZMAX_PR_SPEED") or 200.0)
    zone = float(os.environ.get("ZMAX_PR_ZONE") or 3.0)
    rate = float(os.environ.get("ZMAX_PR_RATE") or 3.0)
    align = os.environ.get("ZMAX_PR_ALIGN", "1") != "0"
    out(mode=mode, name=NAME, speed_pct=speed, zone_mm=zone, rate=rate, dry=dry)

    src, d, frames, n, n_all = load_frames(n_env)
    worst, worst_i, bad = check_jumps(frames)
    out(src=src, n=n, n_all=n_all, max_jump_deg=round(worst, 2), max_jump_at=worst_i,
        bad=bad[:5])
    if bad:
        out(ok=False, why="帧内跳变 >%.0f° 整条拒发" % MAX_JUMP_DEG)
        return 1

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                                    # noqa: BLE001
        out(ok=False, why="连不上 %s: %s: %s" % (IP, type(e).__name__, e))
        return 2

    try:
        st = {"power": str(r.powerState({})), "op": opstate(r)}
        out(state_before=st)
        if "on" not in st["power"].lower():
            out(ok=False, why="未上电(power=%s) —— 先 arm_power.py on" % st["power"])
            return 2
        if not ("idle" in st["op"].lower() or "automatic" in st["op"].lower()):
            out(ok=False, why="模式不满足: %s" % st["op"])
            return 2

        if mode == "list":
            out(ok=True, **do_list(r))
            return 0

        cur = joints(r)
        j0 = _as_j(frames[0])
        start_jump = max(abs(math.degrees(b - a)) for a, b in zip(cur, j0))
        out(joints_now_deg=[round(math.degrees(v), 2) for v in cur],
            start_jump_deg=round(start_jump, 2))
        if dry:
            out(ok=True, note="dry: 前置/跳变检查通过, 未下发")
            return 0

        if mode == "record":
            if start_jump > MAX_JUMP_DEG:
                out(ok=False, why="起点跳变 %.1f° > %.0f°" % (start_jump, MAX_JUMP_DEG))
                return 1
            out(align=align_to(r, j0, speed=100.0, label="pre"))

            ec = {}
            r.startRecordPath(int(os.environ.get("ZMAX_PR_DUR") or 900), ec)
            out(start_record=ec)
            if ec.get("ec", 0) != 0:
                out(ok=False, why="startRecordPath 被拒: %s" % ec)
                return 1

            t_all = time.time()
            r.moveReset({})
            ec = {}
            for i, f in enumerate(frames):
                ec1 = {}
                r.moveAppend([x.MoveAbsJCommand(x.JointPosition(_as_j(f)), speed, zone)],
                             x.PyString("r%d" % i), ec1)
                if ec1.get("ec", 0) != 0:
                    r.moveStop({})
                    out(ok=False, why="第 %d 点 append 被拒 %s" % (i, ec1))
                    return 1
            r.moveStart({})
            ok, secs = wait_idle(r, n * 3.0 + 60.0)
            dur = time.time() - t_all
            out(run_done=ok, run_s=round(dur, 2), per_pt_s=round(dur / n, 3))

            ec = {}
            r.stopRecordPath(ec)
            out(stop_record=ec)
            if ec.get("ec", 0) != 0:
                out(ok=False, why="stopRecordPath 被拒: %s" % ec)
                return 1
            ec = {}
            r.saveRecordPath(NAME, ec)
            out(save_record=ec, name=NAME)
            lst = do_list(r)
            out(ok=(ec.get("ec", 0) == 0), saved_in_controller=NAME in lst["paths"],
                paths=lst["paths"][:20], run_s=round(dur, 2))
            return 0

        if mode == "replay":
            if align:
                out(align=align_to(r, j0, speed=100.0, label="a"))
            ec = {}
            r.replayPath(NAME, rate, ec)
            out(replay_cmd=ec, name=NAME, rate=rate)
            if ec.get("ec", 0) != 0:
                out(ok=False, why="replayPath 被拒: %s" % ec)
                return 1
            t_all = time.time()
            r.moveStart({})
            ok, secs = wait_idle(r, n * 3.0 + 120.0)
            dur = time.time() - t_all
            end_err = max(abs(math.degrees(b - a)) for a, b in zip(joints(r), _as_j(frames[-1])))
            out(ok=bool(ok and end_err <= TOL_DEG), replay_done=ok, dur_s=round(dur, 2),
                per_pt_s=round(dur / n, 3), end_err_deg=round(end_err, 2), rate=rate, n=n)
            return 0

        out(ok=False, why="未知模式 %s (record|replay|list)" % mode)
        return 2
    except Exception as e:                                                    # noqa: BLE001
        out(ok=False, why="%s: %s" % (type(e).__name__, e))
        try:
            r.moveStop({})
        except Exception:                                                     # noqa: BLE001
            pass
        return 1
    finally:
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
