#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""set_auto.py —— 把控制器从 jogging/manual 切回 automatic(idle)

为什么需要: RT 流式控制的入口要求 operation=idle/automatic;
点动(jogging)残留时 connect 后直接 "terminate called without an active exception" 退出。

用法: bash tools/rokae_sdk_run.sh --script set_auto.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x   # noqa: E402,N813

IP = "192.168.23.160"


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    out = {"before": str(r.operationState({})), "power": str(r.powerState({}))}
    tried = []
    # 依次尝试 SDK 暴露的几种切自动的入口(不同固件版本名字不同, 命中一个就够)
    for name, fn in (
        ("setOperationState", lambda: r.setOperationState(x.OperationState.automatic, {})),
        ("setOperationMode", lambda: r.setOperationMode(x.OperationMode.automatic, {})),
        ("setMotionControlMode", lambda: r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})),
    ):
        try:
            ec = {}
            fn()
            tried.append({"api": name, "ok": True})
            time.sleep(0.6)
            if "jog" not in str(r.operationState({})).lower():
                break
        except Exception as e:                                    # noqa: BLE001
            tried.append({"api": name, "ok": False, "err": "%s: %s" % (type(e).__name__, e)})
    out["tried"] = tried
    out["after"] = str(r.operationState({}))
    out["power_after"] = str(r.powerState({}))
    out["joints_deg"] = [round(__import__("math").degrees(v), 2) for v in list(r.jointPos({}))[:6]]
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
