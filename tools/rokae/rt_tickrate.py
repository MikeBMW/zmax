#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_tickrate.py — 零运动: 只测 RT 控制回路真实回调频率

做法: 切 RtCommandMode → setControlLoopJoi(回调=返回当前关节角) → startLoop(False)
     不动臂(不调 startMove) ⇒ 控制器认为"已进入控制回路但没收到运动指令", 臂保持静止。
     统计 5s 内回调次数, 再 stopLoop / 切回 NrtCommandMode。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
SECS = float(os.environ.get("ZMAX_RT_TICKSECS") or 5.0)


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def local_ip(dst):
    import socket as _s
    ss = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    try:
        ss.connect((dst, 9))
        return ss.getsockname()[0]
    finally:
        ss.close()


def ensure_power(r, tries=6):
    """RT 模式切换后控制器常掉电 ⇒ 测试前自己上电(只 setPowerState, 不发运动)"""
    for i in range(tries):
        if "on" in str(r.powerState({})):
            return True
        for fn in (lambda: r.clearServoAlarm({}), lambda: r.moveReset({}), lambda: r.setPowerState(True, {})):
            try:
                fn()
            except Exception:                                            # noqa: BLE001
                pass
        time.sleep(0.6)
    return "on" in str(r.powerState({}))


def main():
    r = x.xMateRobot()
    r.connectToRobot(IP, local_ip(IP))
    pw = ensure_power(r)
    out(before={"power": str(r.powerState({})), "op": str(r.operationState({})), "power_ready": pw})
    if not pw:
        out(ok=False, why="上电失败(需示教器复位?)")
        return
    cnt = {"n": 0, "t0": None, "last": None, "gaps": []}
    hold = [0.0] * 6

    def cb():
        now = time.monotonic()
        if cnt["t0"] is None:
            cnt["t0"] = now
        if cnt["last"] is not None:
            cnt["gaps"].append(now - cnt["last"])
        cnt["last"] = now
        cnt["n"] += 1
        return x.JointPosition(list(hold))

    ok = True
    why = ""
    try:
        hold = [float(v) for v in r.jointPos({})][:6]
        ec = {}
        r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
        out(switch=ec, op=str(r.operationState({})))
        rt = r.getRtMotionController()
        rt.startMove(x.RtControllerMode.jointPosition)   # startLoop 前置: 必须先 startMove(目标=当前角 ⇒ 不动)
        rt.setControlLoopJoi(cb, 0, False)
        t0 = time.time()
        rt.startLoop(False)
        while time.time() - t0 < SECS:
            time.sleep(0.05)
            if cnt["n"] > 3 and cnt["t0"] and (time.monotonic() - cnt["t0"]) > SECS:
                break
        rt.stopLoop()
        rt.stopMove()
    except Exception as e:                                               # noqa: BLE001
        ok = False
        why = "%s: %s" % (type(e).__name__, e)
        try:
            rt.stopLoop()
            rt.stopMove()
        except Exception:                                                # noqa: BLE001
            pass
    finally:
        try:
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        except Exception as e:                                           # noqa: BLE001
            out(err_back=str(e))
    gaps = cnt["gaps"]
    dur = (cnt["last"] - cnt["t0"]) if (cnt["last"] and cnt["t0"]) else 0
    out(ok=ok, why=why, ticks=cnt["n"], dur_s=round(dur, 3),
        hz=round(cnt["n"] / dur, 1) if dur > 0 else None,
        gap_ms_p50=round(sorted(gaps)[len(gaps) // 2] * 1000, 1) if gaps else None,
        gap_ms_min=round(min(gaps) * 1000, 1) if gaps else None,
        gap_ms_max=round(max(gaps) * 1000, 1) if gaps else None,
        power_after=str(r.powerState({})), op_after=str(r.operationState({})),
        joints_deg=[round(v * 57.2958, 2) for v in r.jointPos({})][:6])
    try:
        r.disconnectFromRobot({})
    except Exception:                                                    # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
