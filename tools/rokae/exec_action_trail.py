#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exec_action_trail.py — 逐字执行动作规划节点产出的 action 轨迹(容器内跑)。

输入 /sdk/logs/action_trail_slot<N>.json  (由 tools/plan_grasp_trail.py 在宿主算好)
铁律: 执行器**不重算**轨迹/不重规划 —— 规划节点给什么位姿就走什么位姿(老倪 2026-11-15)。

环境变量:
  ZMAX_TRAIL_SLOT   槽号, 默认 3
  ZMAX_TRAIL_EXEC   1=真走 (默认 0 = 只打印, 不动)
  ZMAX_TRAIL_SPEED  mm/s, 默认取轨迹里的 speed
  ZMAX_TRAIL_TOL    到位容差 mm, 默认 1.0
  ZMAX_TRAIL_STOP_ON_FAIL  1=任一拍超差就停 (默认 1)
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

SLOT = int(os.environ.get("ZMAX_TRAIL_SLOT") or 3)
EXEC = str(os.environ.get("ZMAX_TRAIL_EXEC") or "0").strip() in ("1", "true", "yes")
TOL = float(os.environ.get("ZMAX_TRAIL_TOL") or 1.0)
STOP_FAIL = str(os.environ.get("ZMAX_TRAIL_STOP_ON_FAIL", "1")).strip() in ("1", "true", "yes")
HOLD_RPY = str(os.environ.get("ZMAX_TRAIL_HOLD_RPY", "1")).strip() not in ("0", "false", "no")
MINI = int(os.environ.get("ZMAX_TRAIL_MINI") or 0)          # 从第几拍开始(合爪后接着抬升)
MAXI = int(os.environ.get("ZMAX_TRAIL_MAXI") or 10 ** 6)    # 走到第几拍为止(合爪前停)
IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
TRAIL = "/sdk/logs/action_trail_slot%d.json" % SLOT

try:
    ev = json.load(open(TRAIL, encoding="utf-8"))
except Exception as e:                                                    # noqa: BLE001
    print("✗ 读不到轨迹 %s: %s" % (TRAIL, e))
    sys.exit(2)

steps = ev.get("steps") or []
spd = float(os.environ.get("ZMAX_TRAIL_SPEED") or ev.get("speed") or 15.0)
print("轨迹: slot=%s · %d 拍 · 速度 %.0fmm/s · %s" % (SLOT, len(steps), spd,
                                                     "真走" if EXEC else "DRY(不动)"), flush=True)
print("引导目标: %s" % json.dumps(ev.get("target_pose"), ensure_ascii=False)[:200], flush=True)

r = None
if EXEC:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检:", pw, md, op, flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足, 不动")
        sys.exit(3)
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
    r.moveReset({})


def rpy_of(q):
    if not q or None in q:
        return None
    qx, qy, qz, qw = [float(v) for v in q]
    return [math.atan2(2 * (qw * qx + qy * qz), 1 - 2 * (qx * qx + qy * qy)),
            math.asin(max(-1.0, min(1.0, 2 * (qw * qy - qz * qx)))),
            math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))]


def pose():
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    return [float(v) * 1000.0 for v in cp.trans], [float(v) for v in cp.rpy]


log = []
for s in steps:
    p = s.get("pos")
    if not p:
        continue
    _i = int(s.get("i") or 0)
    if _i < MINI or _i > MAXI:
        continue
    rp = rpy_of(s.get("quat"))
    rec = {"i": s.get("i"), "phase": s.get("phase"), "cmd": [round(float(v), 2) for v in p]}
    if not EXEC:
        print("[%02d] %-9s → %s  (dry)" % (s.get("i", -1), s.get("phase"), rec["cmd"]), flush=True)
        log.append(rec)
        continue
    cur, cur_r = pose()
    # 🔴 2026-11-22 教训: **不许把 quat 自己转成 rpy** —— 珞石 SDK 的 rpy 不是 ZYX 欧拉,
    #   实测按 ZYX 反解后第一拍就把腕部拧成 0.114,-1.44,2.925 (落点偏 69mm, 老倪"乱走")。
    #   默认: 姿态保持实测(每拍把当前 rpy 原样带回), 只有显式 ZMAX_TRAIL_HOLD_RPY=0 才用换算值。
    tgt_rpy = cur_r if HOLD_RPY else (rp or cur_r)
    r.moveReset({})
    r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in p], tgt_rpy), spd, -1),
                 x.PyString("T%02d" % int(s.get("i") or 0)), {})
    r.moveStart({})
    t0 = time.time()
    while time.time() - t0 < 45:
        time.sleep(0.15)
        c2, _ = pose()
        if max(abs(c2[i] - p[i]) for i in range(3)) < TOL:
            break
    c2, r2 = pose()
    d = max(abs(c2[i] - p[i]) for i in range(3))
    rec.update({"arrived": [round(v, 2) for v in c2], "d_mm": round(d, 2),
                "rpy": [round(v, 4) for v in r2]})
    log.append(rec)
    print("[%02d] %-9s → %s  到位 %s Δ%.2fmm" % (s.get("i", -1), s.get("phase"),
          rec["cmd"], rec["arrived"], d), flush=True)
    if d > TOL:
        msg = "✗ 第 %s 拍超差 %.2fmm > %.2f" % (s.get("i"), d, TOL)
        print(msg, flush=True)
        if STOP_FAIL:
            break

_want = len([s for s in steps if s.get("pos") and MINI <= int(s.get("i") or 0) <= MAXI])
out = {"slot": SLOT, "exec": EXEC, "speed": spd, "n": len(log), "want": _want,
       "done": (len(log) == _want), "log": log}
path = "/sdk/logs/action_trail_exec_%s_%d.json" % (time.strftime("%Y%m%d_%H%M%S"), SLOT)
try:
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)
    print("证据:", path)
except Exception as e:                                                    # noqa: BLE001
    print("证据写失败:", e)
print("结果: %s · 走了 %d/%d 拍" % ("完成" if out["done"] else "未完成", len(log), _want))
