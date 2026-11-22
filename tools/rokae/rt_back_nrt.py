#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_back_nrt.py —— 把控制器从 RtCommandMode 退回 NrtCommandMode (只切模式, 不发运动)

为什么要它: RT 会话被强杀(容器 kill / 主机掉网)后, 控制器会一直停在
OperationState.rtControlling, 此时 NRT 运动指令全部被拒("模式不满足")。
本脚本只做模式回退 + (可选)下电, 不做任何运动。

用法:
  bash tools/rokae_sdk_run.sh --script rt_back_nrt.py          # 只回退模式
  ZMAX_RT_POWEROFF=1 bash tools/rokae_sdk_run.sh --script rt_back_nrt.py   # 回退+下电
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


def main() -> int:
    r = x.xMateRobot()
    try:
        r.connectToRobot(IP, local_ip(IP))
    except Exception as e:                                                    # noqa: BLE001
        out(ok=False, why="连不上 %s: %s: %s" % (IP, type(e).__name__, e))
        return 2
    try:
        out(before={"power": str(r.powerState({})), "op": str(r.operationState({}))})
        ec = {}
        try:
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec)
        except Exception as e:                                                # noqa: BLE001
            out(set_nrt_exc="%s: %s" % (type(e).__name__, e), ec=ec)
        t0 = time.time()
        while time.time() - t0 < 8.0:
            if "rt" not in str(r.operationState({})).lower():
                break
            time.sleep(0.3)
        out(after_mode={"power": str(r.powerState({})), "op": str(r.operationState({})),
                        "set_nrt_ec": ec})
        if os.environ.get("ZMAX_RT_POWEROFF") == "1":
            ec2 = {}
            try:
                r.setPowerState(False, ec2)
            except Exception as e:                                            # noqa: BLE001
                out(poweroff_exc="%s: %s" % (type(e).__name__, e))
            time.sleep(0.5)
            out(after_poweroff={"power": str(r.powerState({})), "op": str(r.operationState({})),
                                "ec": ec2})
        return 0 if "rt" not in str(r.operationState({})).lower() else 1
    finally:
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
