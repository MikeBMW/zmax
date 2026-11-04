#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔁 V6 产物 → 引擎 A/B 单臂跑手 (真接管判据: st["w"]>0 且 st["src"]=intact)

判据 (技能 zmax-joint-training-deploy 钉的死标准):
  挂上节点 ≠ 真接管。唯一铁证 = 引擎 _l4_stats["w"] > 0 (=0 就是假接入)。
  还要看 done 与步数是否不回退。

用法 (必须用 gui-venv311, 且引擎读 env 在 import 时):
  # A 臂: 我们的 ckpt 接管
  INTACT_POLICY=joint_v6 INTACT_RUNTIME=root SS_L4_INTACT=1 \
    gui-venv311/bin/python tools/ab_v6_engine.py --arm A --ckpt joint_v6 --seed 104 --steps 1200
  # B 臂: 基线 (不挂节点)
  gui-venv311/bin/python tools/ab_v6_engine.py --arm B --seed 104 --steps 1200
输出: 一行 JSON (arm/src/w/steps/done/...)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("STABLEWM_HOME", f"{ROOT}/zmax_data/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", f"{ROOT}/zmax_data/stable-wm-cache")
sys.path.insert(0, f"{ROOT}/src")
sys.path.insert(0, f"{ROOT}/tools/gui")
sys.path.insert(0, f"{ROOT}/tools")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["A", "B"], required=True)
    ap.add_argument("--ckpt", default="joint_v6")
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--steps", type=int, default=1200)
    ap.add_argument("--mode", default="insert")
    a = ap.parse_args()

    from state_space_sim_real import RealStateSpaceSim                # noqa: PLC0415

    t0 = time.time()
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=lambda *x: None)
    attached = None
    if a.arm == "A":
        from lerobot.manifold.intact_node import IntactNode          # noqa: PLC0415
        attached = sim.attach_intact(IntactNode(horizon=8), None)
    tr = sim.run(max_steps=a.steps)
    st = getattr(sim, "_l4_stats", {}) or {}
    w = float(st.get("w", 0.0) or 0.0)
    res = {
        "arm": a.arm, "ckpt": a.ckpt if a.arm == "A" else None, "seed": a.seed,
        "mode": a.mode, "steps": len(tr.get("t", [])),
        "done": bool(tr.get("done", [False])[-1]),
        "src": st.get("src"), "w": w,
        "calls": st.get("calls"), "refused": st.get("refused"),
        "w_positive": w > 0.0,
        "attached": bool(attached) if a.arm == "A" else None,
        "secs": round(time.time() - t0, 1),
    }
    print("RESULT " + json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
