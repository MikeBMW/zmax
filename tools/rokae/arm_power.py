#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_power.py —— 真机上下电(最小动作, 只改 power, 不发运动指令)

为什么需要它: 2026-11-15 连续回放实测时控制器进了 PowerState.off,
  而 sdk_ctl.py 只读状态没有上电入口, SDK 里是 setPowerState(on, ec)。

安全:
  · 只调 setPowerState, 不发任何 move* 指令 ⇒ 臂不会动
  · 上电前打印当前关节角, 让人确认姿态没变
  · 下电前同样打印, 便于留证

用法(容器内):
  bash tools/rokae_sdk_run.sh --script arm_power.py on
  bash tools/rokae_sdk_run.sh --script arm_power.py off
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def joints(r):
    v = r.jointPos({})
    if isinstance(v, dict):
        for k in ("jointPos", "joint", "values", "data"):
            if k in v:
                v = v[k]
                break
        else:
            v = list(v.values())[0]
    return [float(t) for t in list(v)[:6]]


def main() -> int:
    want = [a for a in sys.argv[1:] if a.lower() in ("on", "off")]
    on = bool(want) and want[0].lower() == "on"
    out = {"ok": False, "action": "power_" + ("on" if on else "off"), "ip": IP}

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                                    # noqa: BLE001
        out["why"] = "连不上 %s: %s: %s" % (IP, type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        return 2

    def _disc():
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass

    try:
        out["power_before"] = str(r.powerState({}))
        out["op_before"] = str(r.operationState({}))
        out["joints_deg"] = [round(math.degrees(v), 2) for v in joints(r)]
    except Exception as e:                                                    # noqa: BLE001
        out["why"] = "读状态失败: %s: %s" % (type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 2

    if on and "on" in out["power_before"].lower():
        out["ok"] = True
        out["why"] = "已经是 on, 无需上电"
        out["power_after"] = out["power_before"]
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 0
    if (not on) and "off" in out["power_before"].lower():
        out["ok"] = True
        out["why"] = "已经是 off, 无需下电"
        out["power_after"] = out["power_before"]
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 0

    try:
        ec = {}
        r.setPowerState(bool(on), ec)
        out["ec"] = ec
    except Exception as e:                                                    # noqa: BLE001
        out["why"] = "setPowerState 异常: %s: %s" % (type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 1

    # 等状态翻转(最多 20s)
    t0 = time.time()
    pw = out["power_before"]
    while time.time() - t0 < 20.0:
        time.sleep(0.5)
        try:
            pw = str(r.powerState({}))
        except Exception:                                                     # noqa: BLE001
            continue
        if on and "on" in pw.lower():
            break
        if (not on) and "off" in pw.lower():
            break
    out["power_after"] = pw
    out["op_after"] = str(r.operationState({}))
    try:
        out["joints_after_deg"] = [round(math.degrees(v), 2) for v in joints(r)]
    except Exception:                                                         # noqa: BLE001
        pass
    out["secs"] = round(time.time() - t0, 1)
    out["ok"] = ("on" in pw.lower()) if on else ("off" in pw.lower())
    out["why"] = ("上电成功" if on else "下电成功") if out["ok"] else ("状态未翻转, 仍是 %s" % pw)
    print(json.dumps(out, ensure_ascii=False))
    _disc()
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
