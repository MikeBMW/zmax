#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""estop_recover.py —— 尽力用软件清 EStop 残留 (碰撞检测掉电后 setPowerState 报 -3 的情况)

顺序: clearServoAlarm → moveReset → (切 RT) automaticErrorRecovery → (回 NRT) → setPowerState(True)
全部只清报警/上电, 不下发任何运动。若仍报 -3, 只能示教器复位或控制器断电重启。

用法: bash tools/rokae_sdk_run.sh --script estop_recover.py
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
    r = x.xMateRobot()
    r.connectToRobot(IP, local_ip(IP))
    try:
        out(step="connect", state=st(r))

        for name, fn in (("clearServoAlarm", lambda: r.clearServoAlarm({})),
                         ("moveReset", lambda: r.moveReset({}))):
            try:
                out(step=name, ret=str(fn()))
            except Exception as e:                                            # noqa: BLE001
                out(step=name, exc="%s: %s" % (type(e).__name__, e))

        ec = {}
        try:
            r.setPowerState(True, ec)
        except Exception as e:                                                # noqa: BLE001
            ec = {"exc": "%s: %s" % (type(e).__name__, e)}
        time.sleep(0.6)
        out(step="power_on_after_clear", ec=ec, state=st(r))
        if "on" in str(r.powerState({})).lower():
            out(ok=True, how="clearServoAlarm+moveReset")
            return 0

        ec = {}
        r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
        out(step="switch_rt", ec=ec, op=str(r.operationState({})))
        try:
            rt = r.getRtMotionController()
            ec2 = {}
            rt.automaticErrorRecovery(ec2)
            out(step="automaticErrorRecovery", ec=ec2)
        except Exception as e:                                                # noqa: BLE001
            out(step="automaticErrorRecovery_exc", why="%s: %s" % (type(e).__name__, e))
        try:
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        except Exception as e:                                                # noqa: BLE001
            out(step="back_nrt_exc", why=str(e))
        time.sleep(0.6)

        ec = {}
        try:
            r.setPowerState(True, ec)
        except Exception as e:                                                # noqa: BLE001
            ec = {"exc": "%s: %s" % (type(e).__name__, e)}
        time.sleep(0.6)
        out(step="power_on_after_rt_recover", ec=ec, state=st(r))
        ok = "on" in str(r.powerState({})).lower()
        out(ok=ok, how="rt.automaticErrorRecovery" if ok else
            "失败: 需示教器复位或控制器断电重启", state=st(r))
        return 0 if ok else 1
    finally:
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
