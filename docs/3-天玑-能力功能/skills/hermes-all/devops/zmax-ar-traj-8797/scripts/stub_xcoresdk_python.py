#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""假 xcoresdk_python —— 离线验证「逐点走关节角真值」脚本的全部闸门，不连真机。

用法：把本文件放到一个目录里（如 /tmp/stub_sdk/），然后
    ZMAX_SDK_DIR=/tmp/stub_sdk ZMAX_STEP_CMD=/tmp/cmd.json ZMAX_ROBOT_IP=10.0.0.9 \
      python tools/rokae/arm_step_traj.py [--dry]

开关（环境变量）：
    STUB_J0='[r1..r6]'   初始关节角(rad) —— 用来复现「停在第 N 点后回点 1 的跳变超限」
    STUB_POWER=PowerState.power_off   前置闸
    STUB_OP=OperationState.moving     前置闸 / 非 idle
    STUB_STUCK=1         下发后不动 ⇒ 验到位超时即停
    STUB_REJECT=1        moveAppend 返回 ec≠0 ⇒ 验控制器拒发即停
    STUB_FAIL_CONNECT=1  连不上 ⇒ 验断链文案

cmd.json 格式：{"frames": [[6 轴 rad], ...], "n": N, "speed": 20.0, "dwell_ms": 0}
"""
import json as _json
import os

STATE = {
    "j": [float(v) for v in _json.loads(os.environ.get("STUB_J0", "[0,0,0,0,0,0]"))],
    "power": os.environ.get("STUB_POWER", "PowerState.power_on"),
    "op": os.environ.get("STUB_OP", "OperationState.idle"),
    "reject": bool(os.environ.get("STUB_REJECT")),
    "stuck": bool(os.environ.get("STUB_STUCK")),
    "pending": None,
}


class JointPosition(object):
    def __init__(self, vals):
        self.vals = [float(v) for v in vals]


class PyString(object):
    def __init__(self, s):
        self.s = s


class MoveAbsJCommand(object):
    def __init__(self, jp, speed, opt):
        self.jp = jp
        self.speed = speed


class xMateRobot(object):
    def connectToRobot(self, ip):
        if os.environ.get("STUB_FAIL_CONNECT"):
            raise RuntimeError("stub: 连不上 %s" % ip)
        return True

    def disconnectFromRobot(self, *a):
        return True

    def powerState(self, *a):
        return STATE["power"]

    def operationState(self, *a):
        return STATE["op"]

    def jointPos(self, *a):
        return {"jointPos": list(STATE["j"])}

    def moveReset(self, *a):
        return True

    def moveAppend(self, cmds, name, ec):
        if STATE["reject"]:
            ec["ec"] = 50113
            return
        STATE["pending"] = list(cmds[0].jp.vals)
        ec["ec"] = 0

    def moveStart(self, *a):
        if not STATE["stuck"] and STATE["pending"]:
            STATE["j"] = list(STATE["pending"])
        return True
