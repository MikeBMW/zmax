#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_recover.py — 清伺服报警/急停残留 + 上电 (arm_power.py 失败后的恢复入口)

为什么需要: RT 流式试验触发控制器 kCollision ⇒ 控制器进 EStop 态,
arm_power.py 直接 setPowerState(on) 会返回 -3 "The robot is in EStop state, please recover."
必须先用 clearServoAlarm() + moveReset() 清掉, 再上电。

只调 clearServoAlarm/moveReset/setPowerState, 不发运动指令。
用法: bash tools/rokae_sdk_run.sh --script arm_recover.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def main():
    r = x.xMateRobot()
    r.connectToRobot(IP)
    j0 = [round(v * 57.2958, 2) for v in r.jointPos({})][:6]
    out(before={"power": str(r.powerState({})), "op": str(r.operationState({})), "joints_deg": j0})
    for step, fn in (("clearServoAlarm", lambda: r.clearServoAlarm({})),
                     ("moveReset", lambda: r.moveReset({})),
                     ("powerOn", lambda: r.setPowerState(True, {}))):
        try:
            ec = {}
            fn()
            out(**{step: "ok"})
        except Exception as e:                                           # noqa: BLE001
            out(**{step: "%s: %s" % (type(e).__name__, e)})
        time.sleep(0.4)
    time.sleep(0.5)
    j1 = [round(v * 57.2958, 2) for v in r.jointPos({})][:6]
    out(after={"power": str(r.powerState({})), "op": str(r.operationState({})), "joints_deg": j1,
               "moved_deg": round(max(abs(a - b) for a, b in zip(j0, j1)), 3) if len(j0) == 6 else None})
    try:
        r.disconnectFromRobot({})
    except Exception:                                                    # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
