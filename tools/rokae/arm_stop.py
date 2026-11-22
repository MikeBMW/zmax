#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_stop.py —— 立刻停掉控制器里排队的运动(MoveAbsJ 队列会跨客户端存活)

场景: 回放脚本被 kill 之后, 臂还在动 —— 因为 `moveAppend` 下发的指令序列
      在**控制器内部排队**, 客户端断开不会清队列。必须由新会话发 moveStop。
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def main() -> int:
    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                               # noqa: BLE001
        out(ok=False, why="连不上 %s: %s" % (IP, e))
        return 2
    res = {}
    for name, fn in (("moveStop", getattr(r, "moveStop", None)),
                     ("movePause", getattr(r, "movePause", None)),
                     ("moveReset", getattr(r, "moveReset", None))):
        if fn is None:
            res[name] = "no-api"
            continue
        try:
            ec = {}
            fn(ec) if name != "moveReset" else fn({})
            res[name] = ec or "ok"
        except Exception as e:                                           # noqa: BLE001
            res[name] = "%s: %s" % (type(e).__name__, e)
    time.sleep(0.5)
    try:
        jp = r.jointPos({})
        if isinstance(jp, dict):
            for k in ("jointPos", "joint", "values", "data"):
                if k in jp:
                    jp = jp[k]
                    break
        res["joints_deg"] = [round(float(v) * 57.29577951308232, 2) for v in list(jp)[:6]]
    except Exception as e:                                               # noqa: BLE001
        res["joints_deg"] = "err: %s" % e
    out(ok=True, action="arm_stop", **res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
