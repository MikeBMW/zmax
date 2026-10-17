#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚖ A/B (真物理 metaworld 路): `u_ff` 是否经过「SK01-08 + 物理约束闸」再给仿真器

解析引擎的 A/B 见 `tools/ab_l2_inline_gate.py`；本脚本走 `RealStateSpaceSim`（metaworld
`peg-insert-side-v3` 真物理 + MuJoCo），同 seed 同初值，只切换闸的接线：

  臂 A  ZMAX_L2_GATE=0  旧链：动作调制器按 STAGE_V_CAP 等比缩放
  臂 B  ZMAX_L2_GATE=1  新链：u_ff → SK01-08 段包络 + 五条物理约束 → 削后 u → 安全限幅 → env.step

判据（同解析路的四条，按真物理口径重报）：
  ① 逐段实际速度 ≤ 本段 v_cap（按 decide 实际用的段归因）
  ② 闸单拍开销 ≤ 10ms（闸本体微基准，与整引擎无关）
  ③ 削因不翻倍（内联闸调用次数 == 拍数）
  ④ 任务不回退（是否抓起/是否插入/插入深度/总步数）

用法:
  ./gui-venv311/bin/python tools/ab_l2_inline_gate_real.py --seeds 104 --steps 500
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

import numpy as np

os.environ.setdefault("MUJOCO_GL", "egl")
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "src"))

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def _run_one(gate_on: bool, seed: int, steps: int) -> dict:
    os.environ["ZMAX_L2_GATE"] = "1" if gate_on else "0"
    from lerobot.engine.runtime import RealStateSpaceSim  # noqa: PLC0415

    logs = []
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: logs.append(" ".join(map(str, a))))
    lim_holder = {}

    t0 = time.perf_counter()
    tr = sim.run(max_steps=int(steps))
    wall = time.perf_counter() - t0
    lim_holder["lim"] = getattr(sim, "lim", None)
    lim = lim_holder["lim"]
    # 🎯 项目自己的几何真值 (沿孔轴插入深度 depth_mm / 横向偏差 lateral_mm) — 判成功只看这个
    geo = None
    try:
        from lerobot.engine.runtime import ss_insert_metrics  # noqa: PLC0415
        geo = ss_insert_metrics(sim.env, sim._site_ph, sim.geom["hole"], sim.geom["goal"],
                                stage=(sim.sched.stage() if getattr(sim, "sched", None) else None),
                                grasped=getattr(sim, "grasped", None), step=-1)
    except Exception as _e:                                        # noqa: BLE001
        geo = {"err": f"{type(_e).__name__}: {_e}"}
    return {
        "gate_on": bool(getattr(sim, "l2_gate_on", False)),
        "limiter": lim is not None,
        "gate_dt_ms": round(float(getattr(sim.sched, "gate_dt", 0.0)) * 1000.0, 3),
        "tr": tr,
        "geo": geo,
        "wall_s": round(wall, 2),
        "n_cut": dict(getattr(lim, "n_cut", {}) or {}),
        "n_gate_calls": int(getattr(lim, "n", 0) or 0),
        "travel": {k: round(v, 4) for k, v in (getattr(lim, "travel", {}) or {}).items()},
        "v_cap_table": dict(getattr(sim.sched, "v_cap", {}) or {}),
        "log_tail": [x for x in logs if "⚖" in x or "⚠" in x][:3],
    }


def _summ(a: dict) -> dict:
    tr = a["tr"]
    base = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in tr.get("stage", [])]
    su = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in (tr.get("stage_u") or [])]
    st = su if len(su) == len(base) else base
    usat = np.asarray(tr.get("u_sat", []), dtype=float)
    caps = a["v_cap_table"]
    per = {}
    for s in STAGES:
        idx = [i for i, x in enumerate(st) if x == s]
        if not idx:
            per[s] = {"n": 0}
            continue
        per[s] = {"n": len(idx),
                  "u_sat_mean": round(float(usat[idx].mean()), 4),
                  "u_sat_max": round(float(usat[idx].max()), 4),
                  "v_cap": float(caps.get(s, 0.0)),
                  "over_cap_steps": int(sum(1 for i in idx if usat[i] > caps.get(s, 9.9) + 1e-9))}
    # 真物理任务指标
    peg = np.asarray(tr.get("peg", []), dtype=float) if tr.get("peg") else None
    depth = tr.get("insert_depth") or tr.get("mani_rem") or None
    lifted = float(np.max(peg[:, 2]) - peg[0, 2]) if (peg is not None and len(peg)) else None
    return {
        "n_steps": len(st),
        "t_end_s": round(float(tr["t"][-1]), 3) if tr.get("t") else 0.0,
        "stages_visited": [s for s in STAGES if any(x == s for x in st)],
        "done": bool(tr.get("done", [False])[-1]) if tr.get("done") else False,
        "final_dist_mm": round(float(tr["dist"][-1]) * 1000.0, 3) if tr.get("dist") else None,
        "peg_lift_mm": round(lifted * 1000.0, 1) if lifted is not None else None,
        # 🎯 项目口径几何真值 (不要用 mani_rem — 那是性能流形 d_axial, 不是沿孔轴插深)
        "geo_depth_mm": (a.get("geo") or {}).get("depth_mm"),
        "geo_lateral_mm": (a.get("geo") or {}).get("lateral_mm"),
        "geo_err": (a.get("geo") or {}).get("err"),
        "per_stage": per, "v_cap_table": caps,
        "n_cut": a["n_cut"], "n_gate_calls": a["n_gate_calls"], "wall_s": a["wall_s"],
        "gate_dt_ms": a.get("gate_dt_ms"),
        "gate_big_steps": int(sum(tr.get("gate_big") or [])),
        "gate_err_max": round(float(max(tr.get("gate_err") or [0.0])), 4),
        "log_tail": a["log_tail"],
    }


def _microbench() -> dict:
    from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter  # noqa: PLC0415
    lim = InertiaLimiter(dt=0.02)
    u = np.array([0.30, -0.20, 0.05, 1.0])
    v, a = np.zeros(3), np.zeros(3)
    for _ in range(200):
        g = lim.limit("接近", u, v_prev=v, a_prev=a)
        v = np.asarray(g["u"][:3])
    ts = []
    for _ in range(20000):
        t0 = time.perf_counter()
        g = lim.limit("接近", u, v_prev=v, a_prev=a)
        ts.append((time.perf_counter() - t0) * 1e6)
        v = np.asarray(g["u"][:3])
    ts.sort()
    return {"p50_us": round(ts[len(ts) // 2], 2), "p95_us": round(ts[int(len(ts) * .95)], 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="104")
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--json", default=os.path.join(REPO, "zmax_data", "eval", "ab_l2_inline_gate_real.json"))
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]

    out = {"ts": time.time(), "src": "tools/ab_l2_inline_gate_real.py",
           "provider": "metaworld peg-insert-side-v3 (真物理)", "steps_cap": a.steps,
           "seeds": seeds, "per_seed": {}}
    for sd in seeds:
        A = _run_one(False, sd, a.steps)
        B = _run_one(True, sd, a.steps)
        out["per_seed"][str(sd)] = {"A": _summ(A), "B": _summ(B)}
        print(f"\n【seed {sd}】A done={out['per_seed'][str(sd)]['A']['done']} "
              f"B done={out['per_seed'][str(sd)]['B']['done']}")
    mb = _microbench()
    out["limiter_microbench"] = mb

    # 判据
    v = {}
    ok1 = ok3 = ok4 = True
    reg4 = {}
    for sd, d in out["per_seed"].items():
        B, A0 = d["B"], d["A"]
        bad = {s: x for s, x in B["per_stage"].items() if x.get("n") and x.get("over_cap_steps", 0) > 0}
        if bad:
            ok1 = False
        if B["n_gate_calls"] != B["n_steps"]:
            ok3 = False
        # ④ 不回退: 走到的段数不比旧链少, 且几何插深(沿孔轴)不比旧链浅 1mm 以上
        bd = float(B.get("geo_depth_mm") or -9e9)
        ad = float(A0.get("geo_depth_mm") or -9e9)
        reg4[sd] = {"A_插深mm": ad, "B_插深mm": bd, "A_段数": len(A0["stages_visited"]),
                    "B_段数": len(B["stages_visited"]), "A_done": A0["done"], "B_done": B["done"]}
        if len(B["stages_visited"]) < len(A0["stages_visited"]) or bd < ad - 1.0:
            ok4 = False
        print(f"\nseed {sd} 臂B: 拍 {B['n_steps']} · done={B['done']} · 段 {'→'.join(B['stages_visited'])}")
        print(f"   削因 {B['n_cut']} · 闸调用 {B['n_gate_calls']} · big拍 {B['gate_big_steps']} · "
              f"抬头 {B['peg_lift_mm']}mm · 插深(几何) {B['geo_depth_mm']}mm · 横向 {B['geo_lateral_mm']}mm · "
              f"用时 {B['wall_s']}s")
        print(f"   {'段':<6}{'拍':>5}{'均值':>9}{'峰':>9}{'v_cap':>8}{'超cap':>7}")
        for s in STAGES:
            x = B["per_stage"].get(s) or {}
            if not x.get("n"):
                continue
            print(f"   {s:<6}{x['n']:>5}{x['u_sat_mean']:>9.4f}{x['u_sat_max']:>9.4f}{x['v_cap']:>8.3f}{x['over_cap_steps']:>7}")
        A2 = d["A"]
        print(f"   对照臂A: done={A2['done']} · 段 {'→'.join(A2['stages_visited'])} · "
              f"末端距 {A2['final_dist_mm']}mm · 用时 {A2['wall_s']}s")
    v["①段速度≤cap"] = {"PASS": ok1}
    v["②闸单拍≤10ms"] = {"PASS": mb["p95_us"] <= 10000, **mb}
    v["③削因不翻倍"] = {"PASS": ok3}
    v["④任务不回退"] = {"PASS": ok4, "逐seed": reg4}
    out["verdict"] = v
    out["all_pass"] = all(x["PASS"] for x in v.values())
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n" + "=" * 88)
    for k, d in v.items():
        print(f"{'✅' if d['PASS'] else '❌'} {k} {json.dumps({x: y for x, y in d.items() if x != 'PASS'}, ensure_ascii=False)}")
    print(f"总判定: {'✅ 全部 PASS' if out['all_pass'] else '❌ 有 FAIL'} · 落盘 {a.json}")
    return 0 if out["all_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
