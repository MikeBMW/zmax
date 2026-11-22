#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_tick2.py —— 插桩版 RT 回调频率实测 (零运动)

比 rt_tickrate.py 多三件事, 用来定位上次到底卡在哪、频率能不能上来:
  1. 每一步都 flush 一行, 不带缓冲 ⇒ 卡死也能看出死在哪个调用
  2. signal.alarm 硬超时(默认 45s) ⇒ 绝不留下 rtControlling 残局
  3. 两个待验证的开关:
       ZMAX_RT_TOL   包丢失阈值 (0-100, 切 RT 前设)      默认 100
       ZMAX_RT_STATE useStateDataInLoop (True=跟随状态包周期) 默认 1
     回调只返回「当前关节角」⇒ 臂理论上不动(容差内保持)

用法:
  bash tools/rokae_sdk_run.sh --script rt_tick2.py
  ZMAX_RT_STATE=0 bash tools/rokae_sdk_run.sh --script rt_tick2.py   # 对照
"""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
SECS = float(os.environ.get("ZMAX_RT_SECS") or 6.0)
TOL = int(os.environ.get("ZMAX_RT_TOL") or 100)
USE_STATE = os.environ.get("ZMAX_RT_STATE", "1") != "0"
HARD = float(os.environ.get("ZMAX_RT_HARD") or 45.0)

R = None
RT = None


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def local_ip(dst):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((dst, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def _alarm(signum, frame):                                                    # noqa: ARG001
    out(alarm="hard timeout %.0fs ⇒ 强制退出 (finally 里会 stopLoop/退 RT)" % HARD)
    raise TimeoutError("hard timeout")


def st():
    return {"power": str(R.powerState({})), "op": str(R.operationState({}))}


def main() -> int:
    global R, RT
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(int(HARD))

    R = x.xMateRobot()
    R.connectToRobot(IP, local_ip(IP))
    out(step="connect", state=st())
    if "on" not in str(R.powerState({})).lower():
        ec = {}
        R.setPowerState(True, ec)
        time.sleep(0.5)
        out(step="power_on", ec=ec, state=st())

    cnt = {"n": 0, "t0": None, "last": None, "gaps": []}
    hold = [float(v) for v in list(R.jointPos({}))[:6]]
    out(step="hold", hold_deg=[round(v * 57.2958, 2) for v in hold])

    def cb():
        now = time.monotonic()
        if cnt["t0"] is None:
            cnt["t0"] = now
        if cnt["last"] is not None:
            cnt["gaps"].append(now - cnt["last"])
        cnt["last"] = now
        cnt["n"] += 1
        return x.JointPosition([float(v) for v in hold])

    try:
        ec = {}
        R.setRtNetworkTolerance(TOL, ec)
        out(step="tolerance", pct=TOL, ec=ec)

        # 🔴 useStateDataInLoop=True 前必须让控制器开始发状态包, 否则回调报
        #    "rtState: Not start receiving data" (实测 2026-11-21)
        if USE_STATE:
            import datetime as _dt
            ms = int(os.environ.get("ZMAX_RT_INTERVAL") or 1)
            try:
                R.startReceiveRobotState(_dt.timedelta(milliseconds=ms),
                                         [x.RtSupportedFields.jointPos_m])
                out(step="start_recv_state", interval_ms=ms)
            except Exception as e:                                            # noqa: BLE001
                out(step="start_recv_state_exc", why="%s: %s" % (type(e).__name__, e))
                raise

        ec = {}
        R.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
        out(step="switch_rt", ec=ec, state=st())

        RT = R.getRtMotionController()
        out(step="got_rt", type=str(type(RT)))

        t = time.time()
        RT.setControlLoopJoi(cb, 0, USE_STATE)
        out(step="set_loop", useStateDataInLoop=USE_STATE, secs=round(time.time() - t, 2))

        t = time.time()
        RT.startMove(x.RtControllerMode.jointPosition)
        out(step="start_move", secs=round(time.time() - t, 2), state=st())

        t = time.time()
        RT.startLoop(False)
        out(step="start_loop", secs=round(time.time() - t, 2))

        t0 = time.time()
        while time.time() - t0 < SECS:
            time.sleep(0.1)
        RT.stopLoop()
        out(step="loop_stopped", ticks=cnt["n"], secs=round(time.time() - t0, 2))
        RT.stopMove()
    except Exception as e:                                                    # noqa: BLE001
        out(step="exception", why="%s: %s" % (type(e).__name__, e), ticks=cnt["n"])
        try:
            RT and RT.stopLoop()
        except Exception:                                                     # noqa: BLE001
            pass
        try:
            RT and RT.stopMove()
        except Exception:                                                     # noqa: BLE001
            pass
    finally:
        signal.alarm(0)
        try:
            R.stopReceiveRobotState()
        except Exception:                                                     # noqa: BLE001
            pass
        try:
            R.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        except Exception as e:                                                # noqa: BLE001
            out(step="back_nrt_exc", why=str(e))
        gaps = sorted(cnt["gaps"])
        dur = (cnt["last"] - cnt["t0"]) if (cnt["last"] and cnt["t0"]) else 0
        out(ok=True, ticks=cnt["n"], dur_s=round(dur, 3),
            hz=round(cnt["n"] / dur, 1) if dur > 0 else None,
            gap_ms_p50=round(gaps[len(gaps) // 2] * 1000, 1) if gaps else None,
            gap_ms_min=round(gaps[0] * 1000, 1) if gaps else None,
            gap_ms_max=round(gaps[-1] * 1000, 1) if gaps else None,
            state_after=st(), joints_deg=[round(float(v) * 57.2958, 2)
                                          for v in list(R.jointPos({}))[:6]])
        try:
            R.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
