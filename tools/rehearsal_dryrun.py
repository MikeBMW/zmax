#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 真机演练(干跑) — 用引擎真跑一遍插入全流程, 产出**将要下发**的信号报文, 但一律不发布

老倪: "要在真机器人演练信号（不用真发信号）"

本脚本只做三件事:
  1. 用真引擎 (RealStateSpaceSim) 跑一条完整插入轨迹 → 每步得到真实六层输出
  2. 把"真要下发时的信号报文"按 topic 逐条写成 JSONL (含 ts/stage/payload/dry_run=true)
  3. 汇总成 summary.json (阶段时长/最大速度/最大接触力/节拍), 供 PPT 与原型验收引用

红线: **没有任何 socket / DDS / ROS / HTTP 发送**, 只有文件写入; dry_run 字段恒为 true。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("STABLEWM_HOME", f"{ROOT}/zmax_data/stable-wm-cache")
os.environ.setdefault("LOCAL_DATASET_DIR", f"{ROOT}/zmax_data/stable-wm-cache")
sys.path.insert(0, f"{ROOT}/tools")
sys.path.insert(0, f"{ROOT}/tools/gui")
sys.path.insert(0, f"{ROOT}/src")

# 真实消息口径 (与产线 topic 一一对应; 只写文件不发布)
TOPICS = {
    "state": "/ss/state",              # 18 维本帧状态
    "twist": "/robot/move_p_twist",    # 末端速度指令 (m/s)
    "gripper": "/robot/gripper_cmd",   # 夹爪开度指令
    "stage": "/ss/stage",              # 八阶段
    "force": "/robot/force_torque",    # 接触力 (归一化)
    "latent": "/ss/latent",            # L4 潜空间
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--steps", type=int, default=1200)
    ap.add_argument("--mode", default="insert")
    ap.add_argument("--outdir", default=f"{ROOT}/zmax_data/deliverables/rehearsal")
    a = ap.parse_args()

    from state_space_sim_real import RealStateSpaceSim                # noqa: PLC0415

    os.makedirs(a.outdir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode=a.mode, log=lambda *x: None)
    tr = sim.run(max_steps=a.steps)
    n = len(tr.get("t", []) or [])
    t = np.asarray(tr.get("t", np.arange(n)), float)
    stage = tr.get("stage", [""] * n)
    x = np.asarray(tr.get("x", []), float)
    grip = np.asarray(tr.get("gripper", []), float)
    force = np.asarray(tr.get("force", []), float)
    u_exec = np.asarray(tr.get("u_exec_vec", tr.get("u_sat_vec", [])), float)
    obs = np.asarray(tr.get("obs", []), float)

    lines = []
    for i in range(n):
        tw = u_exec[i][:3].tolist() if u_exec.ndim == 2 and u_exec.shape[1] >= 3 else [0.0, 0.0, 0.0]
        g = float(grip[i]) if i < len(grip) else 0.0
        fz = float(force[i]) if i < len(force) else 0.0
        st = str(stage[i]) if i < len(stage) else ""
        rec = {
            "ts": round(float(t[i]), 4), "stage": st, "dry_run": True,
            "payload": {
                TOPICS["twist"]: [round(v, 6) for v in tw],
                TOPICS["gripper"]: round(g, 6),
                TOPICS["force"]: round(fz, 6),
                TOPICS["state"]: [round(float(v), 5) for v in obs[i][:18]] if obs.ndim == 2 else [],
                TOPICS["stage"]: st,
            },
        }
        lines.append(rec)
    jl = os.path.join(a.outdir, f"rehearsal_{stamp}.jsonl")
    with open(jl, "w", encoding="utf-8") as fh:
        for r in lines:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 阶段时长
    seg = {}
    for i in range(1, n):
        s = str(stage[i - 1])
        seg[s] = seg.get(s, 0.0) + float(t[i] - t[i - 1])
    v = np.linalg.norm(u_exec[:, :3], axis=1) if u_exec.ndim == 2 and u_exec.shape[1] >= 3 else np.zeros(n)
    summ = {
        "ts": stamp, "seed": a.seed, "mode": a.mode, "dry_run": True,
        "frames": n, "sim_seconds": round(float(t[-1] - t[0]), 3) if n else 0,
        "done": bool(tr.get("done", [False])[-1]),
        "stage_seconds": {k: round(v_, 3) for k, v_ in seg.items()},
        "max_twist_mps": round(float(v.max()), 4) if n else 0.0,
        "max_force_norm": round(float(force.max()), 4) if len(force) else 0.0,
        "force_nonzero_frames": int((force > 0).sum()) if len(force) else 0,
        "gripper_close_frame": int(np.argmax(grip > 0.5)) if len(grip) and (grip > 0.5).any() else -1,
        "topics": TOPICS,
        "signals_written": len(lines),
        "signals_published": 0,
        "jsonl": jl,
    }
    sj = os.path.join(a.outdir, f"rehearsal_{stamp}_summary.json")
    json.dump(summ, open(sj, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("REHEARSAL " + json.dumps(summ, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
