#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 action 形状对账 (老倪 2026-11-15「这个 action 要改成跟真实轨迹 215 个点一样的 action」)

判据: **215 点回放那条 action 的字段集是基准**; 规划(plan) / 状态空间(ss) 两条必须
      ⊇ 215 的字段集, 且同名同单位同取整位数。多出来的只能是证据块(plan/align/u/pose...),
      不许出现"同样一个意思换了字段名"(x/y/z 写成 pose.x 之类)。

跑法: ./gui-venv311/bin/python tools/action_schema_parity.py
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right.state_space import action_bus as ab   # noqa: E402

EVIDENCE = {"plan", "align", "u", "pose", "needs_ik", "joints_target", "spec"}


def _kinds(v):
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    if isinstance(v, str):
        return "str"
    if isinstance(v, (list, tuple)):
        return "list"
    return type(v).__name__


def _rounding(v):
    """数值取整位数(2=mm, 4=关节deg, 6=四元数)。"""
    if not isinstance(v, float):
        return None
    s = repr(v)
    return len(s.split(".")[1]) if "." in s else 0


def main():
    t215 = ab.from_traj215(cursor=120)
    truth = ab.read_pose()
    if truth is None:
        truth = {"x": 665.16, "y": -29.03, "z": 296.10, "age_s": 0.01,
                 "qx": 0.766472, "qy": 0.075475, "qz": 0.615482, "qw": 0.167355}
    plan = ab.from_plan(
        [truth["x"] + 5.0, truth["y"], truth["z"]], quat=[truth["qx"], truth["qy"], truth["qz"], truth["qw"]],
        truth=truth, joints_now=[0.16, -0.06, -2.54, 1.45, 0.43, -0.70],
        seg={"kind": "move", "a": [truth["x"], truth["y"], truth["z"]],
             "b": [truth["x"] + 5.0, truth["y"], truth["z"]], "max_step_mm": 25.0},
        u=0.5, plan={"plan_id": "parity", "n_seg": 1}, why="parity check")
    ss = ab.from_ss([0.05, 0.0, 0.0, 0.6], dt=0.1, pose_now=truth,
                    joints_now=[0.16, -0.06, -2.54, 1.45, 0.43, -0.70])

    if not all((t215, plan, ss)):
        print("❌ 取不到 action: t215=%s plan=%s ss=%s" % (bool(t215), bool(plan), bool(ss)))
        return 1
    base = set(t215)
    rows, bad = [], 0
    for name, act in (("plan", plan), ("ss", ss)):
        miss = sorted(base - set(act))
        extra = sorted(set(act) - base)
        extra_ok = [k for k in extra if k not in EVIDENCE]
        if miss:
            bad += len(miss)
        if extra_ok:
            bad += len(extra_ok)
        rows.append((name, miss, extra_ok, extra))
    print("基准 = src=traj215 (215 点回放) · %d 个字段" % len(base))
    print("  " + ", ".join(sorted(base)))
    for name, miss, extra_bad, extra in rows:
        print("\n%s (src=%s, %d 字段)" % (name, (plan if name == "plan" else ss).get("src"), len(eval(name))))
        print("  缺 215 的字段 : %s" % (", ".join(miss) if miss else "无 ✅"))
        print("  非证据多余字段 : %s" % (", ".join(extra_bad) if extra_bad else "无 ✅"))
        print("  证据块(允许)   : %s" % (", ".join(sorted([k for k in extra if k in EVIDENCE])) or "无"))
        # 同名字段类型/量纲抽查
        for k in ("x", "y", "z", "a", "b", "c", "qx", "qw", "j1", "j6", "grip_mm", "i", "why", "ts"):
            if k in base and k in eval(name):
                kb, kv = _kinds(t215.get(k)), _kinds(eval(name).get(k))
                if kb != kv and not (kb == "num" and kv == "None"):
                    print("  ⚠ 类型不一致 %-8s 215=%s / %s=%s" % (k, kb, name, kv))
                    bad += 1
    # 关键口径硬校验
    pg = plan.get("pose") or {}
    if (pg.get("x"), pg.get("y"), pg.get("z")) != (plan.get("x"), plan.get("y"), plan.get("z")):
        print("  ⚠ plan.pose 与扁平 x/y/z 不一致")
        bad += 1
    if plan.get("a") is not None and _rounding(plan["x"]) != 2:
        print("  ⚠ plan 位置未按 2 位取整")
        bad += 1
    print("\n结论: %s (问题 %d 条)" % ("FAIL" if bad else "PASS · 三条 action 同形", bad))
    out = os.path.join(ROOT, "zmax_data", "reports", "action_schema_parity_%s.json"
                       % time.strftime("%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"base": sorted(base), "t215": t215, "plan": plan, "ss": ss, "bad": bad},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("报告:", out)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
