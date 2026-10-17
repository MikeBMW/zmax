#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 判据: 真物理路的阶段目标 == 原子技能目标 + 现场修正项? (逐拍对照, 只读取证)

背景 (老倪 2026-10-16): 「仿真是不是通过原子任务输出的」「MoveIt 怎么选实际的原子任务动作」
第①项收尾: 真物理路 (metaworld) 的 `RealStateSpaceSim._stage_target()` 为什么不直接换成
技能类 `SK0x.next_target()` —— 因为那条路带**现场策略**:
  · `_grasp_dx()`   抓取自适应的横向修正 (视觉定位偏差)
  · `_grasp_gap_z`  夹爪-销高度差锁存
  · 两段式插入 / 螺旋搜索 (遇阻时走半径递增螺旋)
本工具不猜, 跑一遍真物理 A 臂, **逐拍同时算**「引擎目标」与「技能口目标」, 输出每段差值与归因。
零行为改变: monkeypatch 只记录, 原样返回引擎自己的目标。

用法: ./gui-venv311/bin/python tools/verify_skill_target_real.py [--seed 104] [--steps 500]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("MUJOCO_GL", "egl")

# 技能类 ref → 真物理路 ctx 键的语义映射 (写清楚, 不靠猜)
SEM = {
    "peg": "光模块抓握点 (_peg_cur / 真值 peg_grasp) + 现场 dx",
    "peg_xy_table": "当前末端 xy + (peg_z0 + lift + gap_z) —— 现场用锁存高度差",
    "hole_mouth": "孔口 + 2cm − 头/夹爪偏移",
    "hole": "孔底 − 头/夹爪偏移 (插入段②, 另有两段式+螺旋)",
    "point": "点位库",
    "rel": "当前位姿 + 轴偏移",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--json", default=os.path.join(REPO, "zmax_data", "eval", "verify_skill_target_real.json"))
    a = ap.parse_args()

    from lerobot.engine.runtime import RealStateSpaceSim, ss_insert_metrics
    import lerobot.policies.left_right.state_space.skills.atomic_skills as SK

    sim = RealStateSpaceSim(seed=a.seed, vision=False, mode="insert", log=lambda *x: None)
    rec = []
    _orig = sim._stage_target

    def _probe():
        tgt = _orig()                                  # 引擎目标 (原样返回, 零行为改变)
        try:
            st = sim.sched.stage()
            sk = SK.skill_for(st)
            g = sim.geom
            pg = getattr(sim, "_peg_cur", None)
            if pg is None:
                pg = g["peg_grasp"]
            # ⚠ head_off 的参考必须是「头 − 末端」 (引擎里的 off), 不是 geom["head_off"]
            #   (那是复位时的「头 − 抓握点」, 参考不同, 差 2cm 级)
            _off_head = np.asarray(sim.peg_head(), float) - np.asarray(sim.x, float).ravel()[:3]
            ctx = {"peg": np.asarray(pg, float),
                   "head_off": _off_head,
                   "table_z": float(g.get("peg_z0", 0.0)),
                   "hole_mouth": np.asarray(sim._hole_p(), float),
                   "hole": np.asarray(sim._goal_p(), float)}
            t = sk.next_target(ctx=ctx) if sk is not None else None
            if t is not None:
                d = np.asarray(t["xyz"], float) - np.asarray(tgt, float)
                rec.append({"stage": st, "ref": t["ref"],
                            "eng": [round(float(v), 5) for v in np.ravel(tgt)[:3]],
                            "sk": [round(float(v), 5) for v in t["xyz"]],
                            "d_mm": [round(float(v) * 1000, 2) for v in d],
                            "|d|mm": round(float(np.linalg.norm(d)) * 1000, 2)})
        except Exception as e:                          # noqa: BLE001
            rec.append({"stage": "?", "err": "%s: %s" % (type(e).__name__, e)})
        return tgt

    sim._stage_target = _probe
    tr = sim.run(max_steps=a.steps)
    geo = ss_insert_metrics(sim.env, sim._site_ph, sim.geom["hole"], sim.geom["goal"],
                            stage=sim.sched.stage(), grasped=getattr(sim, "grasped", None), step=-1)

    per = {}
    for r in rec:
        if "err" in r:
            per.setdefault("出错", []).append(r["err"])
            continue
        per.setdefault(r["stage"], []).append(r)
    out = {"seed": a.seed, "done": bool(tr["done"][-1]),
           "geo": {k: geo.get(k) for k in ("depth_mm", "lateral_mm", "z_err_mm") if k in geo},
           "stages": {}}
    print(f"seed={a.seed} done={bool(tr['done'][-1])} 插深={geo.get('depth_mm')} 横向={geo.get('lateral_mm')} 拍={len(rec)}")
    print(f"{'段':<8}{'拍':>5}{'|差|中位mm':>11}{'|差|maxmm':>11}  主角差分量 (mm) / 技能侧参考点")
    for st, rs in per.items():
        if st == "出错":
            print(f"出错: {rs[:2]}")
            continue
        mags = np.array([r["|d|mm"] for r in rs], float)
        dm = np.array([r["d_mm"] for r in rs], float)
        _mx = dm[int(np.argmax(mags))]
        out["stages"][st] = {"拍": len(rs), "|差|中位mm": float(np.median(mags)),
                             "|差|max_mm": float(mags.max()), "ref": rs[0]["ref"],
                             "语义": SEM.get(rs[0]["ref"], ""),
                             "零差拍数": int((mags < 1e-6).sum())}
        print(f"{st:<8}{len(rs):>5}{np.median(mags):>11.2f}{mags.max():>11.2f}"
              f"  {np.round(_mx, 2).tolist()} / {rs[0]['ref']}  零差 {int((mags < 1e-6).sum())}/{len(rs)}")

    # 判据: ①真物理目标都能被技能类解释 (无出错) ②"无现场修正"的段应零差
    v = {}
    v["①技能类能对每段给出目标"] = "出错" not in per and len(per) >= 3
    # 无现场策略的段: 技能口必须与引擎逐拍**零差** (接近/对位/下降 只有 dx, 转移只有头-爪偏移)
    _zero_stages = {"接近", "对位", "下降", "转移"} & set(out["stages"].keys())
    v["②无现场策略段 == 引擎目标 (零差)"] = all(
        out["stages"][s]["|差|max_mm"] < 1e-6 for s in _zero_stages) and bool(_zero_stages)
    # 差异只允许出现在有现场策略的段: 抓取(下探4mm)/抬起(锁存高度差)/插入(两段式+螺旋)
    v["③差异只出现在现场策略段 (抓取/抬起/插入)"] = all(
        out["stages"][s]["|差|max_mm"] < 1e-6
        for s in out["stages"] if s not in ("抓取", "抬起", "插入"))
    out["verdict"] = v
    out["all_pass"] = all(v.values())
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + "=" * 78)
    for k, ok in v.items():
        print(("✅ " if ok else "❌ ") + k)
    print(f"落盘: {a.json}")
    return 0 if out["all_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
