#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan_grasp_trail.py — 在**宿主**上算出一条抓取 action 轨迹(不碰机器人), 给执行器逐拍照做。

为什么要拆: 容器(rokae_sdk_run)里没有 lerobot 的依赖(huggingface_hub 等), 而宿主 venv 里
  **没有** xcoresdk(那是 cpython-310 的厂家 .so)。⇒ 规划在宿主算(action trail),
  执行在容器里逐字照做(exec_action_trail.py), 两边都不重复算。

用法:
  ./gui-venv311/bin/python tools/plan_grasp_trail.py --slot 3 [--speed 15] [--lift 50]
输出:
  zmax_data/rokae_sdk/logs/action_trail_slot<slot>.json
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from lerobot.policies.left_right.state_space import plan_guide as PG      # noqa: E402
from lerobot.policies.left_right.state_space import motion_plan as MP     # noqa: E402

WS = {"x": (0.15, 1.05), "y": (-0.65, 1.15), "z": (0.005, 0.95)}


def guard_mm(p3):
    why, q = [], [float(v) for v in p3]
    for i, k in enumerate("xyz"):
        lo, hi = WS[k][0] * 1000.0, WS[k][1] * 1000.0
        if q[i] < lo:
            why.append("%s<%.0f" % (k, lo)); q[i] = lo
        elif q[i] > hi:
            why.append("%s>%.0f" % (k, hi)); q[i] = hi
    if q[2] < 5.0:
        why.append("z<台面+5"); q[2] = 5.0
    return q, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=3)
    ap.add_argument("--speed", type=float, default=15.0)
    ap.add_argument("--lift", type=float, default=50.0)
    ap.add_argument("--start", default="", help="起点 x,y,z (默认取 tcp_out/latest.json)")
    ap.add_argument("--maxstep", type=int, default=80)
    a = ap.parse_args()

    tp = PG.target_pose(slot_id=a.slot)
    if not tp.get("pos_mm"):
        print("✗ 引导没给目标位姿")
        return 4
    print("🎯 引导目标 slot=%s pos=%s grasp=%s pre=%s valid=%s" % (
        a.slot, tp.get("pos_mm"), tp.get("grasp_mm"), tp.get("pre_pos_mm"), tp.get("valid")))
    print("   姿态 quat(wxyz)=%s src=%s" % (tp.get("quat"), tp.get("quat_src")))

    start = None
    if a.start:
        start = [float(v) for v in a.start.split(",")[:3]]
    else:
        p = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")
        try:
            latest = json.load(open(p))
            p0 = latest.get("tcp") or latest.get("pos") or latest.get("b")
            if p0:
                start = [float(v) * (1000.0 if abs(float(p0[0])) < 5 else 1.0) for v in p0[:3]]
        except Exception:                                                 # noqa: BLE001
            start = None
    if not start:
        start = [464.3, 344.0, 136.2]
        print("⚠ 读不到 tcp_out/latest.json, 起点按 464.3,344,136.2 算")
    print("起点: %s" % [round(v, 1) for v in start])

    gv = {"tcp": tp.get("pos_mm"), "frame": "base_link", "src": "plan_guide.target_pose",
          "target_pose": tp, "quat": tp.get("quat")}
    steps, sim, phase = [], list(start), None
    for k in range(a.maxstep):
        # ⚠ 不要每拍清 _PLAN: 规划节点靠 plan_id 连续性推进同一张段表;
        #   每拍重建会从"当前点"重新派生 lift 段 ⇒ 模拟里一路往上爬 (实测爬到 z=952 被守护拦)
        MP._tcp_now = lambda s=list(sim): (list(s), 0.05)
        out = MP.run({"in1": {"value": gv}})
        act = out.get("action") or {}
        gp = out.get("grasp") or {}
        if act.get("x") is None:
            print("✗ 第 %d 拍没有 action" % k)
            break
        tgt = [act["x"], act["y"], act["z"]]
        g2, why = guard_mm(tgt)
        steps.append({"i": k, "phase": gp.get("phase"), "goal": out.get("goal_used"),
                      "pos": [round(float(v), 2) for v in tgt],
                      "quat": [act.get("qx"), act.get("qy"), act.get("qz"), act.get("qw")],
                      "grip": act.get("grip_act"), "guard_ok": not why, "guard_why": why,
                      "seg": "%s/%s" % ((act.get("plan") or {}).get("seg_i"),
                                        (act.get("plan") or {}).get("n_seg")),
                      "why": (act.get("why") or "")[-40:]})
        print("[%02d] %-9s %s → %s %s" % (k, gp.get("phase"), gp.get("phase") and out.get("goal_used"),
                                          [round(v, 1) for v in tgt], "OK" if not why else "GUARD!" + ",".join(why)))
        if why:
            break
        sim = tgt
        phase = gp.get("phase")
        if gp.get("grip"):
            break

    latch = None
    if steps:
        latch = list(steps[-1]["pos"])
        # 抓后抬升也要守单步 ≤25mm: 50mm 抬升拆成 2 拍, 否则"22/22 通过单步判据"就是假话
        left = float(a.lift)
        while left > 1e-6:
            dz = min(25.0, left)
            latch = [latch[0], latch[1], latch[2] + dz]
            steps.append({"i": len(steps), "phase": "lift", "pos": list(latch),
                          "quat": steps[-1]["quat"], "grip": "hold", "guard_ok": True, "guard_why": [],
                          "seg": "-", "why": "抓后抬升(单拍 ≤25mm)"})
            left -= dz

    ev = {"slot": a.slot, "speed": a.speed, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
          "target_pose": {k: tp.get(k) for k in ("pos_mm", "grasp_mm", "pre_pos_mm", "quat", "quat_src",
                                                "valid", "slot", "src", "sigma_mm")},
          "start": [round(float(v), 2) for v in start], "n_steps": len(steps),
          "final_phase": phase, "steps": steps}
    out_dir = os.path.expanduser("~/zmax/zmax_data/ss_live")   # 宿主可写(rokae_sdk/logs 是 root/容器的)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "action_trail_slot%d.json" % a.slot)
    json.dump(ev, open(path, "w"), ensure_ascii=False, indent=1)
    print("\n轨迹: %d 拍 · 末段 %s · 总长 %.1fmm" % (
        len(steps), phase,
        sum(((steps[i]["pos"][0] - steps[i - 1]["pos"][0]) ** 2 +
             (steps[i]["pos"][1] - steps[i - 1]["pos"][1]) ** 2 +
             (steps[i]["pos"][2] - steps[i - 1]["pos"][2]) ** 2) ** 0.5 for i in range(1, len(steps)))))
    print("写出:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
