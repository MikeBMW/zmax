#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meas_probe2.py —— getStateData 的取值方式试验(只读, 不发运动)。"""
from __future__ import annotations

import json
import os
import socket
import sys
import time

sys.path.insert(0, "/sdk")
import datetime as _dt
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"


def local_ip(ip: str) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((ip, 1))
    lip = s.getsockname()[0]
    s.close()
    return lip


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP, local_ip(IP))
    r.startReceiveRobotState(_dt.timedelta(milliseconds=1), [x.RtSupportedFields.jointPos_m])
    time.sleep(0.3)
    print(json.dumps({"connected": True}))
    print(json.dumps({"jointPos_rad": [round(v, 5) for v in r.jointPos({})[:6]]}))

    vec = x.PyTypeVectorDouble([0.0] * 6)
    for name, fn in (
        ("list(vec)", lambda: list(vec)),
        ("len+index", lambda: [vec[i] for i in range(len(vec))]),
        ("append_style", lambda: (vec.append(0.0), list(vec))[1]),
    ):
        try:
            print(json.dumps({"read": name, "ok": True, "val": [round(float(v), 5) for v in fn()]}))
        except Exception as e:                                      # noqa: BLE001
            print(json.dumps({"read": name, "ok": False, "err": "%s: %s" % (type(e).__name__, e)}))

    ret = None
    try:
        ret = r.getStateData("jointPos_m", vec, 6)
    except Exception as e:                                          # noqa: BLE001
        print(json.dumps({"getStateData": "exc", "err": "%s: %s" % (type(e).__name__, e)}))
    print(json.dumps({"getStateData_ret": ret if isinstance(ret, (int, float)) else str(ret)[:60]}))
    try:
        print(json.dumps({"after": [round(float(v), 5) for v in list(vec)]}))
    except Exception as e:                                          # noqa: BLE001
        print(json.dumps({"after": "exc", "err": "%s: %s" % (type(e).__name__, e)}))

    # 最高能跑多快(纯读状态缓冲, 不碰 RCI 锁)
    ok, t0 = 0, time.time()
    for _ in range(600):
        try:
            r.getStateData("jointPos_m", vec, 6)
            ok += 1
        except Exception:                                           # noqa: BLE001
            break
        time.sleep(0.001)
    el = time.time() - t0
    print(json.dumps({"hz": round(ok / el, 1) if el else 0, "n": ok}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
