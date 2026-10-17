#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚖ jerk_max 上限倍率扫描 (真物理 metaworld) — 定位「物理闸③加加速度」把插孔掐死的临界倍率

2026-10-16 实测 (seed104, 500 步): ×1 = 未插入 (−2.3mm) · ×2 = 完成 64.9mm · ×4 起与不开闸逐位一致。
结论: 标定 jerk_max 偏小 2~4 倍; 它是"平顺性 vs 贴合精度"的权衡, 不是越小越安全。

用法:
  ./gui-venv311/bin/python tools/sweep_l2_gate_jerk.py --seed 104 --steps 500
  ./gui-venv311/bin/python tools/sweep_l2_gate_jerk.py --xs 1,2,3,4,0
"""
import argparse
import os, sys, json
os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, os.path.join(os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax"), "src"))
_ap = argparse.ArgumentParser()
_ap.add_argument("--seed", type=int, default=104)
_ap.add_argument("--steps", type=int, default=500)
_ap.add_argument("--xs", default="1,2,4,8,16,0")
_A = _ap.parse_args()
rows = []
for x in [float(v) for v in _A.xs.split(",") if v.strip()]:
    os.environ["ZMAX_L2_GATE"] = "1"
    os.environ["ZMAX_GATE_SKIP"] = ""
    os.environ["ZMAX_GATE_JERK_X"] = str(x)
    for m in [k for k in list(sys.modules) if k.startswith("lerobot.engine") or "physics_constraints" in k]:
        del sys.modules[m]
    from lerobot.engine.runtime import RealStateSpaceSim, ss_insert_metrics
    sim = RealStateSpaceSim(seed=_A.seed, vision=False, mode="insert", log=lambda *a: None)
    tr = sim.run(max_steps=int(_A.steps))
    geo = ss_insert_metrics(sim.env, sim._site_ph, sim.geom["hole"], sim.geom["goal"],
                            stage=sim.sched.stage(), grasped=getattr(sim, "grasped", None), step=-1)
    lim = sim.lim
    r = {"jerk_x": x, "done": bool(tr["done"][-1]), "steps": len(tr.get("stage_u") or tr["stage"]),
         "depth_mm": geo.get("depth_mm"), "lateral_mm": geo.get("lateral_mm"),
         "n_cut": dict(lim.n_cut), "n": lim.n}
    rows.append(r)
    print(f"jerk×{x:<5} done={r['done']} 拍={r['steps']} 插深={r['depth_mm']}mm 横向={r['lateral_mm']}mm 削={r['n_cut']}", flush=True)
json.dump(rows, open("/home/ubuntu/zmax/zmax_data/eval/jerk_sweep.json","w"), ensure_ascii=False, indent=1)