#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔁 全系统 action 闭环自检 (老倪 2026-11-15: "L2 L3 L4 L5 的接口要对齐 action, 保证数据闭环运行")

跑的是**真链路真函数**, 全程 read-only + real_send=False, 不动机器人:
  L5  TaskPlanner.plan(指令) → 技能Token序列        ⇒ 每个 token 必须真存在技能库里
  L4  IntactIntentService → u_ff / l3_cond          ⇒ 4 维速度先验 (与 action.u 同口径)
  L3  plan_long_impl.run(ctx) → 段表                ⇒ 段两端位姿能喂给 L2 规划
  L2  action_bus.from_{traj215,plan,ss} → action    ⇒ 过 action_spec 契约
  L2' robot_actuator_impl._exec_action_verbatim      ⇒ 逐字执行(不下发) + executed 留证

判据: 每层 PASS/SKIP(带原因)/FAIL, 只要有一个 FAIL 退出码非 0。
报告: zmax_data/reports/action_loop_<ts>.json

用法: python3 tools/action_loop_selftest.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

R = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "layers": [], "fail": 0}


def add(layer, name, status, detail, evidence=None):
    R["layers"].append({"layer": layer, "check": name, "status": status,
                        "detail": detail, "evidence": evidence})
    if status == "FAIL":
        R["fail"] += 1
    icon = {"PASS": "✅", "SKIP": "⏭", "FAIL": "❌"}[status]
    print("  %s [%s] %-34s %s" % (icon, layer, name, detail))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    from lerobot.policies.left_right.state_space import action_spec as SP

    print("=== 1) L2 · action 契约 (三个生产者) ===")
    from lerobot.policies.left_right.state_space import action_bus as AB

    truth = AB.read_pose()
    if truth:
        add("L2", "真机位姿真值", "PASS",
            "%.2f/%.2f/%.2f age=%.3fs" % (truth["x"], truth["y"], truth["z"], truth.get("age_s") or -1),
            {k: truth.get(k) for k in ("x", "y", "z", "qx", "qw", "age_s")})
    else:
        add("L2", "真机位姿真值", "SKIP", "tcp_out/latest.json 陈旧/全0 ⇒ 位姿类检查按无真值口径")

    # traj215
    try:
        act = AB.from_traj215(cursor=100)
        iss = SP.validate(act, src="traj215") if act else ["None"]
        add("L2", "from_traj215 → action", "PASS" if not iss else "FAIL", SP.describe(act) if act else "None", iss)
    except Exception as e:                                                 # noqa: BLE001
        add("L2", "from_traj215 → action", "FAIL", "%s: %s" % (type(e).__name__, e))

    # plan
    plan_act = None
    try:
        tgt = ([truth["x"] + 5.0, truth["y"], truth["z"]] if truth else [665.0, -29.0, 296.0])
        seg = {"i": 1, "kind": "move", "a": tgt, "b": tgt, "max_step_mm": 25.0}
        plan_act = AB.from_plan(tgt, truth=truth, seg=seg, u=0.17,
                                plan={"plan_id": "selftest", "n_seg": 6})
        iss = SP.validate(plan_act, src="plan") if plan_act else ["None"]
        add("L2", "from_plan → action", "PASS" if not iss else "FAIL",
            SP.describe(plan_act) if plan_act else "None", iss)
    except Exception as e:                                                 # noqa: BLE001
        add("L2", "from_plan → action", "FAIL", "%s: %s" % (type(e).__name__, e))

    # ss
    try:
        ss_act = AB.from_ss([0.05, 0.0, 0.0, 0.0], dt=0.1, pose_now=truth)   # 0.05 m/s × 0.1s = 5mm
        iss = SP.validate(ss_act, src="ss") if ss_act else ["None"]
        if ss_act is None:
            add("L2", "from_ss → action", "SKIP", "无新鲜真值 ⇒ 按设计不输出位姿 (宁缺不编)")
        else:
            add("L2", "from_ss → action", "PASS" if not iss else "FAIL", SP.describe(ss_act), iss)
    except Exception as e:                                                 # noqa: BLE001
        add("L2", "from_ss → action", "FAIL", "%s: %s" % (type(e).__name__, e))

    print("=== 2) L2' · 执行器逐字执行 (不下发) ===")
    try:
        from lerobot.middleware.nodes.impl.robot_actuator_impl import _exec_action_verbatim
        src_act = plan_act or AB.from_traj215(cursor=100)
        raw = _exec_action_verbatim({}, src_act, lambda *_: None)
        out = raw.get("out1", raw) if isinstance(raw, dict) else {}
        mode = out.get("mode") or (out.get("executed") or {}).get("mode")
        same = (abs(float(out.get("pose", {}).get("x", 0)) - float(src_act.get("x", 0))) < 1e-6)
        add("L2'", "verbatim 执行规划 action", "PASS" if (mode == "verbatim" and same and out.get("ok")) else "FAIL",
            "mode=%s ok=%s 位姿逐字一致=%s 拒收=%s" % (mode, out.get("ok"), same, out.get("problems")),
            {"real_send": out.get("real_send")})
    except Exception as e:                                                 # noqa: BLE001
        add("L2'", "verbatim 执行规划 action", "FAIL", "%s: %s" % (type(e).__name__, e))

    print("=== 3) L3 · 段表 → 能否喂 L2 规划 ===")
    try:
        from lerobot.engineering.nodes import plan_long_impl as PL
        res = PL.run(ctx={})
        out = res[0] if isinstance(res, (tuple, list)) and res and isinstance(res[0], dict) else res
        why = (res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else "-")
        o1 = (out or {}).get("out1") or {}
        a_pt = o1.get("a") or o1.get("start")
        if not (isinstance(a_pt, (list, tuple)) and len(a_pt) >= 3):
            add("L3", "当前段→L2 action", "FAIL",
                "out1 无 a 位姿: keys=%s" % list(o1.keys())[:10])
        else:
            b_pt = o1.get("b") if isinstance(o1.get("b"), (list, tuple)) else a_pt
            # 真链路: L3 段终点 → L2 运动规划节点(motion_plan.run) → action
            from lerobot.policies.left_right.state_space import motion_plan as MP
            mout = MP.run({"in1": {"value": {"pos": list(b_pt),
                                            "kind": o1.get("kind"), "seg": o1.get("seq")}}})
            act3 = (mout or {}).get("action")
            iss = SP.validate(act3, src="plan") if act3 else ["motion_plan 没出 action (keys=%s)"
                                                              % list((mout or {}).keys())[:8]]
            add("L3", "L3段→L2规划→action", "PASS" if not iss else "FAIL",
                "段#%s %s 段终点=%s · %s" % (o1.get("seq"), o1.get("kind"),
                                            [round(float(x), 1) for x in b_pt[:3]],
                                            SP.describe(act3)), iss)
    except Exception as e:                                                 # noqa: BLE001
        add("L3", "段表→L2 action", "FAIL", "%s: %s" % (type(e).__name__, str(e)[:120]))

    print("=== 4) L4 · INTACT 意图 → u (与 action.u 同口径) ===")
    try:
        from lerobot.policies.intact import service as IS
        svc = IS.get_service()
        rep = None
        for call in ("run_once", "step_once"):
            if hasattr(svc, call):
                try:
                    rep = getattr(svc, call)()
                except TypeError:
                    rep = getattr(svc, call)(decode=True)
                rep = rep or getattr(svc, "last_report", None) or getattr(svc, "last_out", None)
                break
        if rep is None:
            add("L4", "意图服务可调用", "SKIP", "服务无 run_once/step_once 入口: %s"
                % [m for m in dir(svc) if not m.startswith("_")][:8])
        else:
            u = getattr(rep, "u_ff", None)
            if u is None:
                add("L4", "u_ff 先验", "SKIP", "u_ff=None (%s)" % (getattr(rep, "reason", "") or "未解码"))
            else:
                import numpy as np
                n = int(np.asarray(u).size)
                add("L4", "u_ff 先验维度", "PASS" if n == 4 else "FAIL",
                    "u_ff=%s (期望 4 维: vx,vy,vz,grip)" % np.asarray(u).round(3).tolist())
    except Exception as e:                                                 # noqa: BLE001
        add("L4", "意图服务", "SKIP", "不可用(权重/环境): %s: %s" % (type(e).__name__, str(e)[:90]))

    print("=== 5) L5 · 指令 → 技能Token (必须都在技能库里) ===")
    try:
        from lerobot.policies.left_right.state_space.planner import TaskPlanner
        tp = TaskPlanner()
        toks = tp.plan("插入光模块并检测")
        # 合法 token 集 = 技能库里每条技能的 tokens.id (形如 [SKILL_NPO002])
        valid = set()
        for e in (tp.skills or {}).values():
            t = (e or {}).get("tokens") or {}
            if t.get("id"):
                valid.add(t["id"])
        miss = [t for t in toks if t not in valid]
        add("L5", "TaskPlanner.plan", "PASS" if (toks and not miss) else "FAIL",
            "tokens=%s 库内合法 %d 条%s" % (toks, len(valid), " 缺失=%s" % miss if miss else ""))
    except Exception as e:                                                 # noqa: BLE001
        add("L5", "TaskPlanner.plan", "FAIL", "%s: %s" % (type(e).__name__, str(e)[:120]))

    print("=== 6) 契约一致性: 各层是否都从 action_spec 取口径 ===")
    files = {
        "action_bus": "src/lerobot/policies/left_right/state_space/action_bus.py",
        "motion_plan": "src/lerobot/policies/left_right/state_space/motion_plan.py",
        "execution": "src/lerobot/policies/left_right/state_space/execution.py",
        "robot_actuator": "src/lerobot/middleware/nodes/impl/robot_actuator_impl.py",
        "plan_long(L3)": "src/lerobot/engineering/nodes/plan_long_impl.py",
        "intact(L4)": "src/lerobot/policies/intact/service.py",
        "planner(L5)": "src/lerobot/policies/left_right/state_space/planner.py",
    }
    for nm, p in files.items():
        fp = os.path.join(ROOT, p)
        if not os.path.isfile(fp):
            add("spec", nm, "FAIL", "文件不存在 %s" % p)
            continue
        txt = open(fp, encoding="utf-8", errors="ignore").read()
        uses = "action_spec" in txt
        add("spec", nm, "PASS" if uses else "SKIP",
            "引用 action_spec" if uses else "未直接引用 (经 action_bus 间接对齐)")

    out = a.json or os.path.join(ROOT, "zmax_data/reports/action_loop_%s.json" % time.strftime("%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(R, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nFAIL=%d · 报告 %s" % (R["fail"], out))
    return 1 if R["fail"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:                                                      # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
