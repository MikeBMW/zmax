#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_action_plan.py — 由**动作规划节点(n_moveit)**输出的 action 驱动真机, 完成一个抓取序列。

口径(老倪 2026-11-22): 「根据规划引导输出的目标位姿, 动作规划给出 action 抓取」「由动作规划执行」
  ① 引导:  plan_guide.target_pose(slot) → 唯一目标位姿(位置/姿态/预抓点)
  ② 守护:  safety_limit_impl 的守卫盒子(工作空间/单步/台面) —— 能导入就用真节点, 导不进用同口径本地判
  ③ 规划:  motion_plan.run({in1:{value:{target_pose}}}) → action(位姿口径) + 三段 phase
  ④ 执行:  把 action 的位姿用 MoveJ 走一小步, 到位后下一拍再规划 —— **每拍都重新规划**, 不是一次性下发
  ⑤ 收口:  phase=grip 时停手, 夹爪由调用方(宿主)按已验证通道合上

环境变量:
  ZMAX_PLAN_SLOT     槽号, 默认 3
  ZMAX_PLAN_DRYRUN   1=只算不走(默认), 0=真走
  ZMAX_PLAN_SPEED    mm/s, 默认 15
  ZMAX_PLAN_MAXSTEP  最多几拍, 默认 60
  ZMAX_PLAN_LIFT     抓完抬升 mm, 默认 50 (0=不抬)
"""
import json
import os
import sys
import time

sys.path.insert(0, "/sdk")
sys.path.insert(0, "/src")
import xcoresdk_python as x  # noqa: E402

from lerobot.policies.left_right.state_space import plan_guide as PG   # noqa: E402
from lerobot.policies.left_right.state_space import motion_plan as MP  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SLOT = int(os.environ.get("ZMAX_PLAN_SLOT") or 3)
DRY = str(os.environ.get("ZMAX_PLAN_DRYRUN", "1")).strip() not in ("0", "false", "no")
SPEED = float(os.environ.get("ZMAX_PLAN_SPEED") or 15)
MAXSTEP = int(os.environ.get("ZMAX_PLAN_MAXSTEP") or 60)
LIFT = float(os.environ.get("ZMAX_PLAN_LIFT") or 50.0)

WS = {"x": (0.15, 1.05), "y": (-0.65, 1.15), "z": (0.005, 0.95)}


def guard_mm(p3):
    """与 🛡 位姿守护 同口径的盒子判: 工作空间 + 台面 +5mm。"""
    why = []
    q = [float(v) for v in p3]
    for i, k in enumerate("xyz"):
        lo, hi = WS[k][0] * 1000.0, WS[k][1] * 1000.0
        if q[i] < lo:
            why.append("%s<%.0f" % (k, lo)); q[i] = lo
        elif q[i] > hi:
            why.append("%s>%.0f" % (k, hi)); q[i] = hi
    if q[2] < 5.0:
        why.append("z<台面+5"); q[2] = 5.0
    return q, why


r = x.xMateRobot()
r.connectToRobot(IP)
pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
print("自检:", pw, md, op, flush=True)
if (not DRY) and ("on" not in pw or "automatic" not in md or "idle" not in op):
    print("✗ 前置不满足, 不动")
    sys.exit(3)


def pose():
    cp = r.cartPosture(x.CoordinateType.endInRef, {})
    return ([float(v) * 1000.0 for v in cp.trans], [float(v) for v in cp.rpy])


tp = PG.target_pose(slot_id=SLOT)
if not tp.get("pos_mm"):
    print("✗ 引导没给出目标位姿")
    sys.exit(4)
print("🎯 引导目标: pos %s · grasp %s · pre %s · quat %s · valid=%s"
      % (tp.get("pos_mm"), tp.get("grasp_mm"), tp.get("pre_pos_mm"),
         None if not tp.get("quat") else [round(v, 4) for v in tp["quat"]], tp.get("valid")), flush=True)

gv = {"tcp": tp.get("pos_mm"), "frame": "base_link", "src": "plan_guide.target_pose",
      "target_pose": tp, "quat": tp.get("quat")}

trace = []
if not DRY:
    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
    r.moveReset({})

sim = None   # dry-run: 用上一拍 action 当作"真值"往前推
phase = None
for k in range(MAXSTEP):
    if DRY:
        start = sim if sim is not None else [464.3, 344.0, 136.2]
        age = 0.05
    else:
        start, rpy_now = pose()
        age = 0.05
    MP._tcp_now = lambda s=start, a=age: (list(s), a)
    out = MP.run({"in1": {"value": gv}})
    act = out.get("action") or {}
    gp = out.get("grasp") or {}
    target = [act.get("x"), act.get("y"), act.get("z")]
    if None in target:
        print("✗ 第 %d 拍没有 action" % k)
        break
    g2, why = guard_mm(target)
    rec = {"i": k, "phase": gp.get("phase"), "goal": out.get("goal_used"),
           "act": [round(float(v), 2) for v in target],
           "guard_ok": not why, "guard_why": why,
           "quat": [act.get("qx"), act.get("qy"), act.get("qz"), act.get("qw")],
           "grip": act.get("grip_act"), "seg": "%s/%s" % (act.get("plan", {}).get("seg_i"), act.get("plan", {}).get("n_seg"))}
    trace.append(rec)
    print("[%02d] %-9s goal=%s act=%s %s %s" % (k, gp.get("phase"), out.get("goal_used"),
          rec["act"], "guard-ok" if rec["guard_ok"] else ("guard!" + ",".join(why)), rec["grip"]), flush=True)
    if why:
        print("✗ 守护拦下, 停")
        break
    if DRY:
        sim = target
    else:
        q = act
        rpy_t = None
        if None not in (q.get("qx"), q.get("qy"), q.get("qz"), q.get("qw")):
            # 四元数 → rpy (只用于 MoveJ 的姿态目标, 口径与 SDK 的 rpy 一致: ZYX)
            import math
            qw, qx, qy, qz = q["qw"], q["qx"], q["qy"], q["qz"]
            rpy_t = [math.atan2(2 * (qw * qx + qy * qz), 1 - 2 * (qx * qx + qy * qy)),
                     math.asin(max(-1.0, min(1.0, 2 * (qw * qy - qz * qx)))),
                     math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))]
        r.moveReset({})
        r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in target],
                                                        rpy_t or rpy_now), SPEED, -1),
                     x.PyString("ACT%02d" % k), {})
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 40:
            time.sleep(0.15)
            p, rr = pose()
            if max(abs(p[i] - target[i]) for i in range(3)) < 0.6:
                break
        p, rr = pose()
        rec["arrived"] = [round(v, 2) for v in p]
        rec["d_mm"] = round(max(abs(p[i] - target[i]) for i in range(3)), 2)
        if rec["d_mm"] > 2.0:
            print("✗ 第 %d 拍没到位 (%.1fmm), 停" % (k, rec["d_mm"]))
            break
    phase = gp.get("phase")
    if gp.get("grip"):
        print("✋ 到抓取点, 该合爪了 (phase=%s)" % phase)
        break

# 抓完抬升 (仅真走且已到抓取点)
if (not DRY) and phase in ("grip", "done") and LIFT > 0:
    p, rp = pose()
    tgt = [p[0], p[1], p[2] + LIFT]
    print("⬆ 抬升 %.0fmm → %s" % (LIFT, [round(v, 1) for v in tgt]), flush=True)
    r.moveReset({})
    r.moveAppend(x.MoveJCommand(x.CartesianPosition([v / 1000.0 for v in tgt], rp), 20, -1),
                 x.PyString("LIFT"), {})
    r.moveStart({})

ev = {"slot": SLOT, "dry": DRY, "speed": SPEED, "target_pose": {k: tp.get(k) for k in
      ("pos_mm", "grasp_mm", "pre_pos_mm", "quat", "valid", "slot", "src")},
      "n_steps": len(trace), "final_phase": phase, "trace": trace}
path = "/sdk/logs/action_plan_%s.json" % time.strftime("%Y%m%d_%H%M%S")
try:
    json.dump(ev, open(path, "w"), ensure_ascii=False, indent=1)
    print("证据:", path)
except Exception as e:                                                    # noqa: BLE001
    print("证据写失败:", e)
print("结果: %s · %d 拍 · 末段 phase=%s" % ("DRY-RUN(未动)" if DRY else "已执行", len(trace), phase))
