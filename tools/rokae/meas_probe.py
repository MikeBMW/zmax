#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meas_probe.py —— 找"不抢 RCI 锁的高频实测关节位置"读法的探针(只读, 不发运动)。

背景(2026-11-21 实测): 在 RT 流式会话里从主线程调 `r.jointPos()` 会 **把 RT 回调饿死**
(实测 88s 里只有 422 拍 ≈ 4.8Hz), 因为 jointPos 走的是同一把 RCI 锁。
⇒ 高频读实测位置只能用 RT 状态缓冲: `startReceiveRobotState(1ms,[jointPos_m])` + `getStateData`。

本探针验证 ① 非 RT 模式下状态流能不能收 ② `PyTypeVectorDouble` 怎么构造/取值 ③ 实际能跑多快。
"""
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
    print(json.dumps({"connected": True, "ip": IP}))

    r.startReceiveRobotState(_dt.timedelta(milliseconds=1), [x.RtSupportedFields.jointPos_m])
    print(json.dumps({"state_recv": "started"}))

    variants = []
    try:
        variants.append(("PyTypeVectorDouble(6)", x.PyTypeVectorDouble(6)))
    except Exception as e:                                          # noqa: BLE001
        print(json.dumps({"ctor_size": "%s: %s" % (type(e).__name__, e)}))
    try:
        variants.append(("PyTypeVectorDouble()", x.PyTypeVectorDouble()))
    except Exception as e:                                          # noqa: BLE001
        print(json.dumps({"ctor_empty": "%s: %s" % (type(e).__name__, e)}))
    if not variants:
        print(json.dumps({"fatal": "PyTypeVectorDouble 两种构造都失败"}))
        return 2

    for name, vec in variants:
        ok, sample = 0, None
        t0 = time.time()
        err = None
        for _ in range(300):
            try:
                ec = r.getStateData("jointPos_m", vec, 6)
                vals = []
                for i in range(6):
                    vals.append(float(vec[i]))
                sample = vals
                ok += 1
            except Exception as e:                                  # noqa: BLE001
                err = "%s: %s" % (type(e).__name__, e)
                break
            time.sleep(0.002)
        el = time.time() - t0
        print(json.dumps({"variant": name, "ok": ok, "secs": round(el, 2),
                          "hz": round(ok / el, 1) if el > 0 else 0,
                          "sample": [round(v, 5) for v in sample] if sample else None,
                          "err": err}))
        if ok:
            return 0
    return 3


if __name__ == "__main__":
    sys.exit(main())
