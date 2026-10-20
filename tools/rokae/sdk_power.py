#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdk_power.py —— 上电/下电 (xCoreSDK setPowerState)。只发电源状态, 不发任何运动。

为什么单独一条: 2026-10-20 现场实测 —— 控制器 `PowerState.off` 时**所有运动指令都被拒**,
   sdk_ctl 只会报 `ABORT 前置条件不满足: 上电状态不是 on`, 看起来像"奇异点/不动";
   实际是没上电。上电后同一 pose 的 move-rel 立刻 PASS。

用法:
  bash tools/rokae_sdk_run.sh --script sdk_power.py --on
  bash tools/rokae_sdk_run.sh --script sdk_power.py --off
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def main() -> int:
    on = "--on" in sys.argv
    r = x.xMateRobot()
    r.connectToRobot(IP)
    before = str(r.powerState({}))
    ec = {}
    r.setPowerState(bool(on), ec)
    for _ in range(20):
        time.sleep(0.3)
        if str(r.powerState({})) == str(x.PowerState.on if on else x.PowerState.off):
            break
    after = str(r.powerState({}))
    print(json.dumps({"action": "on" if on else "off", "before": before, "after": after,
                      "ec": ec, "op": str(r.operationState({}))}, ensure_ascii=False))
    try:
        r.disconnectFromRobot({})
    except Exception:  # noqa: BLE001
        pass
    return 0 if str(after).endswith(("on" if on else "off")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
