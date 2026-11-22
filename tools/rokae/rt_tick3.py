#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_tick3.py —— RT 回调频率实测 v3 (零运动, 扛得住 stopLoop 卡死)

前两版的教训 (2026-11-21 实测):
  · rt_tickrate.py: 切完 RT 卡在 startMove/startLoop, 容器内无输出
  · rt_tick2.py:   startLoop 成功, 但 RT.stopLoop() 卡死(不回) ⇒ 拿不到频率
  · 另: useStateDataInLoop=True 前必须 startReceiveRobotState(), 否则
        "rtState: Not start receiving data"

本版做法: 回调每次把「序号+单调时钟」直接 os.write 到 /sdk/logs/rt_ticks_*.txt
         (不走 Python 缓冲, 被 kill 也不丢), 主线程等够 N 秒直接 os._exit(0),
         不调 stopLoop/stopMove ⇒ 不会被卡死。收尾统一由 rt_back_nrt.py 做。

用法:
  bash tools/rokae_sdk_run.sh --script rt_tick3.py
  bash tools/rokae_sdk_run.sh --script rt_back_nrt.py     # 之后必须收尾(退 RT)
环境变量:
  ZMAX_RT_SECS      采样时长(默认 8)
  ZMAX_RT_TOL       包丢失阈值 0-100(切 RT 前设, 默认 100)
  ZMAX_RT_STATE     1=useStateDataInLoop(默认 1, 需状态流) 0=自由跑
  ZMAX_RT_INTERVAL  状态包间隔 ms (1/2/4/8/1000, 默认 1)
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
SECS = float(os.environ.get("ZMAX_RT_SECS") or 8.0)
TOL = int(os.environ.get("ZMAX_RT_TOL") or 100)
USE_STATE = os.environ.get("ZMAX_RT_STATE", "1") != "0"
LOGDIR = os.environ.get("ZMAX_RT_LOGDIR") or "/sdk/logs"
MS = int(os.environ.get("ZMAX_RT_INTERVAL") or 1)


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def local_ip(dst):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((dst, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def st(r):
    return {"power": str(r.powerState({})), "op": str(r.operationState({}))}


def main() -> int:
    os.makedirs(LOGDIR, exist_ok=True)
    path = os.path.join(LOGDIR, "rt_ticks_%d.txt" % int(time.time()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)

    r = x.xMateRobot()
    r.connectToRobot(IP, local_ip(IP))
    out(step="connect", state=st(r), tickfile=path)
    if "on" not in str(r.powerState({})).lower():
        ec = {}
        r.setPowerState(True, ec)
        time.sleep(0.5)
        out(step="power_on", ec=ec, state=st(r))

    hold = [float(v) for v in list(r.jointPos({}))[:6]]
    out(step="hold", hold_deg=[round(v * 57.2958, 2) for v in hold])

    def cb():
        os.write(fd, b"%d\n" % time.monotonic_ns())
        return x.JointPosition([float(v) for v in hold])

    ec = {}
    r.setRtNetworkTolerance(TOL, ec)
    out(step="tolerance", pct=TOL, ec=ec)

    if USE_STATE:
        import datetime as _dt
        r.startReceiveRobotState(_dt.timedelta(milliseconds=MS),
                                 [x.RtSupportedFields.jointPos_m])
        out(step="start_recv_state", interval_ms=MS)

    ec = {}
    r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
    out(step="switch_rt", ec=ec, state=st(r))

    rt = r.getRtMotionController()
    rt.setControlLoopJoi(cb, 0, USE_STATE)
    out(step="set_loop", useStateDataInLoop=USE_STATE)
    rt.startMove(x.RtControllerMode.jointPosition)
    out(step="start_move")
    rt.startLoop(False)
    out(step="start_loop", secs=SECS)

    t0 = time.monotonic()
    while time.monotonic() - t0 < SECS:
        time.sleep(0.2)
    out(step="done", note="直接退出(不调 stopLoop, 收尾由 rt_back_nrt.py)")
    os.fsync(fd)
    os.close(fd)
    os._exit(0)                                                               # noqa: SLF001


if __name__ == "__main__":
    sys.exit(main())
