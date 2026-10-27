#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sdk_clear_alarm.py —— 清控制器报警 / 复位运动队列 (moveReset)，**不运动**。

口径:
  · 只调 moveReset（清报警 + 清残余队列），不发运动、不切模式、不上电。
  · 急停(estop)是硬件安全回路，软件替代不了：控制器在 estop 下会拒绝复位，
    这里如实报 `estop_blocks=True`，让人去松急停按钮，而不是反复试。

用法:
  bash tools/rokae_sdk_run.sh --script sdk_clear_alarm.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")


def _snap(r):
    d = {}
    for k, fn in (("power", "powerState"), ("op", "operationState"), ("mode", "operateMode")):
        try:
            d[k] = str(getattr(r, fn)({}))
        except Exception:                                                    # noqa: BLE001
            d[k] = "?"
    return d


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    before = _snap(r)
    ec = {}
    try:
        r.moveReset(ec)
    except Exception as e:                                                   # noqa: BLE001
        ec = {"exception": str(e)[:200]}
    time.sleep(1.0)
    after = _snap(r)
    estop = "estop" in (before.get("power", "") + after.get("power", "")).lower()
    # ❗ec 形如 {"ec": 0, "message": "success"} —— 非空 dict 不代表失败, 只看 ec 是否为 0
    _ok = (int((ec or {}).get("ec", -1)) == 0) and not (ec or {}).get("exception")
    out = {"action": "moveReset", "before": before, "after": after, "ec": ec,
           "ok": _ok, "estop_blocks": estop,
           "hint": ("急停仍在 ⇒ 先物理松开急停按钮, 再跑一次本脚本 + 上电" if estop
                    else ("已清" if _ok else "复位未成功, 看 ec"))}
    print(json.dumps(out, ensure_ascii=False))
    try:
        r.disconnectFromRobot({})
    except Exception:                                                        # noqa: BLE001
        pass
    return 0 if (_ok and not estop) else 1


if __name__ == "__main__":
    raise SystemExit(main())
