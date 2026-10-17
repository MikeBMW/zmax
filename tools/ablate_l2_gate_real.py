#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔬 消融: 真物理路上「u_ff 过物理闸」的回退是哪条约束造成的 (seed 固定, 单臂)

背景: `tools/ab_l2_inline_gate_real.py` 测出 seed104 旧链插深 64.3mm(插入完成) → 新链 −2.3mm(未插入)。
本脚本在同一 seed 上逐条关掉约束 (ZMAX_GATE_SKIP) 复现, 定位真凶。

用法:
  ./gui-venv311/bin/python tools/ablate_l2_gate_real.py --seed 104 --steps 500
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("MUJOCO_GL", "egl")
REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "src"))


def run(skip: str, seed: int, steps: int, gate: bool = True) -> dict:
    os.environ["ZMAX_L2_GATE"] = "1" if gate else "0"
    os.environ["ZMAX_GATE_SKIP"] = skip
    os.environ.pop("ZMAX_GATE_DT", None)
    for m in [k for k in list(sys.modules) if k.startswith("lerobot.engine") or "physics_constraints" in k]:
        del sys.modules[m]                       # 环境变量读在 import/构造里 → 逐臂重载
    from lerobot.engine.runtime import RealStateSpaceSim, ss_insert_metrics  # noqa: PLC0415

    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda *a: None)
    tr = sim.run(max_steps=int(steps))
    try:
        geo = ss_insert_metrics(sim.env, sim._site_ph, sim.geom["hole"], sim.geom["goal"],
                                stage=sim.sched.stage(), grasped=getattr(sim, "grasped", None), step=-1)
    except Exception as e:                                              # noqa: BLE001
        geo = {"err": f"{type(e).__name__}: {e}"}
    lim = getattr(sim, "lim", None)
    st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in (tr.get("stage_u") or tr.get("stage") or [])]
    return {"skip": skip or "(无/五条全开)", "gate": bool(getattr(sim, "l2_gate_on", False)),
            "done": bool(tr["done"][-1]) if tr.get("done") else False,
            "steps": len(st), "stages": sorted(set(st), key=st.index),
            "geo_depth_mm": geo.get("depth_mm"), "geo_lateral_mm": geo.get("lateral_mm"),
            "n_cut": dict(getattr(lim, "n_cut", {}) or {}),
            "n_gate": int(getattr(lim, "n", 0) or 0), "err": geo.get("err")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--json", default=os.path.join(REPO, "zmax_data", "eval", "ablate_l2_gate_real.json"))
    a = ap.parse_args()
    cases = [("", False),                              # 旧链 (对照)
             ("", True),                               # 五条全开
             ("加加速度", True), ("加速度", True), ("位移", True), ("速度", True),
             ("加加速度,加速度", True)]
    out = {"ts": time.time(), "seed": a.seed, "steps": a.steps, "rows": []}
    print(f"🔬 消融 seed={a.seed} steps={a.steps} (真物理 metaworld)")
    print(f"{'跳过约束':<18}{'闸':>4}{'complete':>9}{'拍':>5}{'插深mm':>9}{'横向mm':>8}  削因")
    for skip, gate in cases:
        r = run(skip, a.seed, a.steps, gate)
        out["rows"].append(r)
        print(f"{r['skip']:<18}{'ON' if r['gate'] else 'OFF':>4}{str(r['done']):>9}{r['steps']:>5}"
              f"{str(r['geo_depth_mm']):>9}{str(r['geo_lateral_mm']):>8}  {r['n_cut']}")
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"落盘: {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
