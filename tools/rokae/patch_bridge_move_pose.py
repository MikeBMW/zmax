#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修 Orin 上 zmax_arm_sdk_bridge 的 /move_pose 真下发 (2026-10-25 实测 500 根因)

现象: dry=true 正常返回 delta_mm, dry=false 抛
  TypeError: moveAppend(): incompatible function arguments
根因: 旧 do_move 调 `r.moveAppend([x,y,z,qx,qy,qz,qw], speed, True, ct.endInRef, {})` —— 那是**不存在的重载**。
本 SDK (xCoreSDK_python) 只有 moveAppend(cmd, PyString, ec) 形态, cmd 必须是 MoveLCommand/MoveJCommand。
修法: 按 tools/rokae/sdk_ctl.py 里**实测走通过**的序列重写:
  CartesianPosition(xyz, rpy) → MoveLCommand(cp, speed, -1) → setDefaultSpeed/Zone/ConfOpt(False)
  → moveReset → moveAppend(mc, PyString(cmd_id), ec) → moveStart(ec)
保留 dry 语义与返回结构 (result.plan.delta_mm 不能变, 我的执行器拿它做预演对账)。
"""
import os
import shutil
import sys
import time

P = sys.argv[1] if len(sys.argv) > 1 else "/home/tashan/.zmax/arm/zmax_arm_sdk_bridge.py"

NEW = '''def do_move(p, q, speed=30.0, dry=True):
    r, ct = STATE["robot"], STATE["ct"]
    cur = _pose(r.cartPosture(ct.endInRef, {})) or []
    rpy = [float(v) for v in cur[3:6]] if len(cur) >= 6 else [0.0, 0.0, 0.0]
    plan = {"from": cur, "to": [p[0], p[1], p[2], q[0], q[1], q[2], q[3]], "speed": speed,
            "rpy_used": [round(v, 6) for v in rpy],
            "delta_mm": [round((p[i] - cur[i]) * 1000, 4) for i in range(3)] if len(cur) >= 3 else None}
    if dry:
        return {"dry": True, "plan": plan, "note": "仅计算; dry=false 才真下发"}
    # 2026-10-25: 旧实现用的 moveAppend(list, speed, True, ref, {}) 在本 SDK 不存在 ⇒ 500。
    # 现按 tools/rokae/sdk_ctl.py 实测口径: 命令对象 + PyString(cmdID) + ec。
    import xcoresdk_python as x                                               # type: ignore
    cp = x.CartesianPosition([float(p[0]), float(p[1]), float(p[2])], rpy)
    mc = x.MoveLCommand(cp, float(speed), -1)
    ec = {}
    r.setDefaultSpeed(float(speed), ec)
    plan["setDefaultSpeed_ec"] = dict(ec)
    ec = {}
    r.setDefaultZone(5, ec)
    plan["setDefaultZone_ec"] = dict(ec)
    ec = {}
    r.setDefaultConfOpt(False, ec)          # 报警 50021 修法①: 不强制 confData, 取离当前最近的解
    plan["setDefaultConfOpt_ec"] = dict(ec)
    ec = {}
    r.moveReset(ec)
    plan["moveReset_ec"] = dict(ec)
    cmd_id = "zmax_bridge_%d" % int(time.time() * 1000)
    ec = {}
    r.moveAppend(mc, x.PyString(cmd_id), ec)
    plan["moveAppend_ec"] = dict(ec)
    plan["cmd_id"] = cmd_id
    if ec.get("ec", 0) != 0:
        return {"dry": False, "sent": plan, "ok": False, "why": "moveAppend 报错 ec=%s" % ec}
    ec = {}
    r.moveStart(ec)
    plan["moveStart_ec"] = dict(ec)
    ok = ec.get("ec", 0) == 0
    return {"dry": False, "sent": plan, "ok": ok, "why": None if ok else "moveStart 报错"}


'''

src = open(P, encoding="utf-8").read()
if "xcoresdk_python as x" in src and "setDefaultConfOpt" in src:
    print("已经是修好的版本, 跳过")
    sys.exit(0)
i = src.find("def do_move(")
j = src.find("class H(", i)
if i < 0 or j < 0:
    print("定位失败: do_move=%d class_H=%d" % (i, j))
    sys.exit(2)
bak = P + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
shutil.copy2(P, bak)
open(P, "w", encoding="utf-8").write(src[:i] + NEW + src[j:])
print("已替换 do_move, 备份:", bak)
