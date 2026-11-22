#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""path_probe.py —— 探控制器「路径录制/回放」API 的可用前置条件 (默认不运动)

背景: startRecordPath(900) 在 power=on / op=idle / automatic 下被拒
      {ec:-18, message:'task_space unsupported operation'}
本脚本按多个候选前置条件逐个试, 打印每个 ec, 找出哪种状态被接受。
⚠️ 只有 --with-move 才会下发一条 ~0.05° 的微动; 默认全程零运动。

用法:
  bash tools/rokae_sdk_run.sh --script path_probe.py
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


def st(r):
    return {"power": str(r.powerState({})), "op": str(r.operationState({})),
            "operate": str(r.operateMode({}))}


def jpos(r):
    return [float(v) for v in list(r.jointPos({}))[:6]]


def try_call(tag, fn):
    ec = {}
    try:
        fn(ec)
        out(**{tag: ec, "accepted": ec.get("ec", 0) == 0})
        return ec.get("ec", 0) == 0
    except Exception as e:                                                    # noqa: BLE001
        out(**{tag: {"exc": "%s: %s" % (type(e).__name__, e), "ec": ec}, "accepted": False})
        return False


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP, local_ip(IP))
    try:
        out(state=st(r), joints_deg=[round(v * 57.2958, 2) for v in jpos(r)])
        out(has=["startRecordPath", "stopRecordPath", "cancelRecordPath",
                 "saveRecordPath", "replayPath", "queryPathLists"][:0] or "see-calls")

        # 0 基线: 直接录
        ok = try_call("rec_baseline", lambda ec: r.startRecordPath(60, ec))
        if ok:
            try_call("stop_baseline", lambda ec: r.stopRecordPath(ec))
            try_call("save_baseline", lambda ec: r.saveRecordPath("probe_base", ec))
            out(paths=_paths(r))
            return 0

        # 1 moveReset 之后
        try:
            r.moveReset({})
        except Exception as e:                                                # noqa: BLE001
            out(moveReset_exc=str(e))
        ok = try_call("rec_after_moveReset", lambda ec: r.startRecordPath(60, ec))
        if ok:
            try_call("stop1", lambda ec: r.stopRecordPath(ec))
            try_call("save1", lambda ec: r.saveRecordPath("probe_mr", ec))
            out(paths=_paths(r))
            return 0

        # 2 先切 NrtCommandMode(显式) 再录
        try_call("set_nrt", lambda ec: r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ec))
        ok = try_call("rec_after_setnrt", lambda ec: r.startRecordPath(60, ec))
        if ok:
            try_call("stop2", lambda ec: r.stopRecordPath(ec))
            try_call("save2", lambda ec: r.saveRecordPath("probe_nrt", ec))
            out(paths=_paths(r))
            return 0

        # 3 看已有路径列表本身能不能读 (API 是否整体可用)
        out(paths=_paths(r))

        # 4 replay 一个不存在的名字, 看报错是否也是 -18 (区分"功能不支持" vs "前置不对")
        try_call("replay_missing", lambda ec: r.replayPath("__nope__", 1.0, ec))

        # 5 cancelRecordPath / removePath 探测
        try_call("cancel_rec", lambda ec: r.cancelRecordPath(ec))

        out(note="所有录制前置都被拒 ⇒ 该控制器/固件不支持 NRT 路径录制, 或需示教器侧开启")
        return 0
    finally:
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass


def _paths(r):
    ec = {}
    try:
        lst = r.queryPathLists(ec)
        return {"ec": ec, "paths": list(lst) if lst is not None else []}
    except Exception as e:                                                    # noqa: BLE001
        return {"exc": "%s: %s" % (type(e).__name__, e)}


if __name__ == "__main__":
    sys.exit(main())
