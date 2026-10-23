#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""symmetry_evolve.py — Intel 550C 上常驻的「对称性理解」自主进化 (老倪 2026-10-23)

目标不是检测器 mAP，而是**流形引擎的对称性理解本身**：让
  · 沿对称群轨道的等距推演**更准**（valid 拍的一步误差 / 步长）
  · **覆盖更多**（valid 比例高：能推的地方都推到）
  · **破缺抓得准**（判无效的那些拍, 确实是不该外推的拍）
三者在同一条基因组上互相拉扯 ⇒ 用进化搜索找最优点。

基因组（全部是引擎真参数，不加新算法）:
  window · drift_tol · accel_tol · bend_tol · phi_tol · lookahead(k) · engine M
数据（同源，不造假）:
  · 真实：ss_traj_last.json 400 帧真机 obs43 → 引擎 project → p 序列（滑窗切片）
  · 引擎自生成：随机起点/随机目标的梯度流轨迹（引擎自己的动力学）
评分（越大越好）:
  score = cov·(1−min(err_rel,1)) + 0.4·break_prec − 0.5·max(0, 0.30−cov)
  err_rel = median(valid 拍一步误差)/median(步长)   break_prec = 判无效拍中真实误差>2×中位步长的比例

输出: /home/intel/evolve/symmetry_ledger.jsonl (每代一行) + symmetry_best.json (当前最优基因组)
用法: python3 tools/symmetry_evolve.py [--gens N] [--pop K] [--once]
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time

import numpy as np

SRC = "/home/intel/zmax_map/src"
TOOLS = "/home/intel/zmax_map/tools"
REPO = "/home/intel/zmax_map"
WORK = os.environ.get("EVO_WORK", "/home/intel/evolve")
sys.path.insert(0, SRC)
sys.path.insert(0, TOOLS)

from lerobot.manifold.orbit_predict import OrbitPredictor, _dist   # noqa: E402
from lerobot.manifold.manifold_engine import ManifoldEngine        # noqa: E402

TRAJ = os.path.join(REPO, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
CKPT = os.path.join(REPO, "models", "manifold_engine.npz")
LEDGER = os.path.join(WORK, "symmetry_ledger.jsonl")
BEST = os.path.join(WORK, "symmetry_best.json")

# 基因组边界 (min, max, is_log)
# 只进化**部署口径下真能改的东西**:
#   · M 固定在常驻引擎实际用的 3.643 (否则阈值是给另一个引擎调的 → 采纳后对不上)
#   · lookahead 由 ZMAX_ORBIT_LOOKAHEAD 定 (实测 E1: k=1 动作误差 −64.4%), 不进基因组 (否则无选择压力的维度在乱走)
DEPLOY_M = float(os.environ.get("SYM_DEPLOY_M", "3.643"))
BOUNDS = {
    "window": (3, 14, False),
    "drift_tol": (0.2, 6.0, True),
    "accel_tol": (0.15, 6.0, True),
    "bend_tol": (0.15, 6.0, True),
    "phi_tol": (0.10, 3.0, True),
}

_ENG: dict[float, ManifoldEngine] = {}


def engine(M: float) -> ManifoldEngine:
    key = round(float(M), 3)
    if key not in _ENG:
        e = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                           manifold_M=key, inertia=False, su2_tangent=True)
        try:
            e.load(CKPT)
        except Exception:                                                # noqa: BLE001
            pass
        _ENG[key] = e
    return _ENG[key]


def real_ps(M: float):
    d = json.load(open(TRAJ))
    obs = np.asarray(d["obs"], float)
    e = engine(M)
    pts = [np.asarray(e.project(r)["p"], float) for r in obs]
    return pts


def engine_trajs(M: float, n=4, steps=90, seed=0):
    """引擎自生成轨迹: 随机起点 + 随机目标, 跑它自己的梯度流。"""
    rng = np.random.default_rng(seed)
    e = engine(M)
    out = []
    for _ in range(n):
        p0 = e.project(np.zeros(43))["p"]
        p0 = np.asarray(p0, float)
        # 随机起点: 在 p0 附近做一次随机导航步
        p0 = np.asarray(e.navigator.step(p0, rng.normal(size=p0.size) * 0.6, 1.0), float)
        goal = np.asarray(e.navigator.step(p0, rng.normal(size=p0.size) * 1.2, 1.0), float)
        e.goal_point = goal
        ps, p = [p0], p0
        for _ in range(steps):
            gf = e.gradient_flow(p=p)
            p = np.asarray(e._evolve(p, gf["descent"], 0.05), float)
            ps.append(p)
        out.append(ps)
    return out


def windows(ps, w=60, hop=30):
    return [ps[i:i + w] for i in range(0, max(1, len(ps) - w + 1), hop)]


_BANK: dict = {}


def bank(M: float):
    key = round(float(M), 3)
    if key not in _BANK:
        ps = real_ps(M)
        tr = [ps] + engine_trajs(M, seed=17)
        segs = []
        for t in tr:
            segs += windows(t)
        _BANK[key] = segs
    return _BANK[key]


def evaluate(g: dict) -> dict:
    segs = bank(g.get("M", DEPLOY_M))
    pr = OrbitPredictor(window=int(g["window"]), drift_tol=g["drift_tol"],
                        accel_tol=g["accel_tol"], bend_tol=g["bend_tol"], phi_tol=g["phi_tol"],
                        horizons=(1, 2, 5), manifold="sphere")
    flags, errs, steps = [], [], []
    for seg in segs:
        pr.reset()
        prev = None
        for i, p in enumerate(seg):
            o = pr.observe(p)
            if i + 1 < len(seg):
                steps.append(_dist(p, seg[i + 1]))
            if o["err_rad"] is not None:
                errs.append(o["err_rad"])
                flags.append(o["valid"])
        if prev is not None:
            pass
    if not steps or not errs:
        return {"score": -1.0, "cov": 0.0, "err_rel": 1.0, "break_prec": 0.0, "n": 0}
    n = min(len(errs), len(flags))
    errs, flags = np.asarray(errs[-n:]), np.asarray(flags[-n:], bool)
    med_step = float(np.median(steps)) or 1e-12
    cov = float(flags.mean())
    err_rel = float(np.median(errs[flags]) / med_step) if flags.any() else 1.0
    thr = 2.0 * med_step
    # ⚠ 破缺精度必须要求**真的抓到过破缺**: 原先"没有 invalid 拍就给 1.0" ⇒ 搜索学会
    #   "什么都不判无效" 白拿 0.4 分 (实测 cov 0.99 的退化基因组)。现在: 判无效的拍少于
    #   样本 3% (且 <5 个) 记 0 分 —— 没有破缺检测能力就不给分。
    n_inv = int((~flags).sum())
    if n_inv >= max(5, int(0.03 * n)):
        bp = float(np.mean(errs[~flags] > thr))
    else:
        bp = 0.0
    score = cov * (1.0 - min(err_rel, 1.0)) + 0.4 * bp - 0.5 * max(0.0, 0.30 - cov)
    return {"score": round(score, 6), "cov": round(cov, 4), "err_rel": round(err_rel, 5),
            "break_prec": round(bp, 4), "n": int(n), "med_step": round(med_step, 6)}


def write_best(genome: dict, metrics: dict, gen: int, run_id: str) -> None:
    """只有**全局**更优才写 symmetry_best.json —— 多路并行时每路各有各的 best,
    不加这道闸就会被某一路的较差结果覆盖掉全局最优 (实测踩到: 台账 max 1.1664 / 文件只有 1.1286)。"""
    try:
        cur = json.load(open(BEST))
        if float((cur.get("metrics") or {}).get("score") or -9) >= float(metrics["score"]):
            return
    except Exception:                                                    # noqa: BLE001
        pass
    tmp = BEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"at": time.strftime("%F %T"), "run": run_id, "generation": gen,
                   "genome": genome, "metrics": metrics}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BEST)


def sample(rng: random.Random) -> dict:
    g = {}
    for k, (lo, hi, islog) in BOUNDS.items():
        if k in ("window", "lookahead"):
            g[k] = rng.randint(int(lo), int(hi))
        elif islog:
            g[k] = round(math.exp(rng.uniform(math.log(lo), math.log(hi))), 4)
        else:
            g[k] = round(rng.uniform(lo, hi), 4)
    return g


def mutate(g: dict, rng: random.Random, sigma: float) -> dict:
    out = dict(g)
    for k, (lo, hi, islog) in BOUNDS.items():
        if rng.random() < 0.45:
            if k in ("window", "lookahead"):
                out[k] = int(min(hi, max(lo, out[k] + rng.choice([-2, -1, 1, 2]))))
            elif islog:
                v = out[k] * math.exp(rng.gauss(0, sigma))
                out[k] = round(min(hi, max(lo, v)), 4)
            else:
                v = out[k] + rng.gauss(0, sigma)
                out[k] = round(min(hi, max(lo, v)), 4)
    return out


def main():
    gens = 40
    pop_n = 18
    once = "--once" in sys.argv
    if "--gens" in sys.argv:
        gens = int(sys.argv[sys.argv.index("--gens") + 1])
    if "--pop" in sys.argv:
        pop_n = int(sys.argv[sys.argv.index("--pop") + 1])
    os.makedirs(WORK, exist_ok=True)
    rng = random.Random(int(time.time()) % 100000)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    # 起点: 当前引擎默认参数 (不是随机乱找)
    seed = {"window": 6, "drift_tol": 1.0, "accel_tol": 0.6, "bend_tol": 0.5, "phi_tol": 0.5}
    pop = [seed] + [sample(rng) for _ in range(pop_n - 1)]
    best = None
    for gen in range(1, gens + 1):
        scored = [(evaluate(g), g) for g in pop]
        scored.sort(key=lambda t: -t[0]["score"])
        if best is None or scored[0][0]["score"] > best[0]["score"]:
            best = (scored[0][0], dict(scored[0][1]))
            write_best(best[1], best[0], gen, run_id)
        rec = {"at": time.strftime("%F %T"), "run": run_id, "gen": gen,
               "best_score": best[0]["score"], "best": best[1], "best_metrics": best[0],
               "gen_best_score": scored[0][0]["score"], "gen_best": scored[0][1],
               "population": [{"g": g, "m": m} for m, g in scored[:3]]}
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("[sym-evolve %s] gen%d best=%.4f cov=%.2f err_rel=%.3f bp=%.2f genome=%s"
              % (run_id, gen, best[0]["score"], best[0]["cov"], best[0]["err_rel"],
                 best[0]["break_prec"], best[1]), flush=True)
        elite = [g for _m, g in scored[:4]]
        sigma = max(0.08, 0.5 * (1.0 - gen / float(gens)))
        pop = list(elite)
        while len(pop) < pop_n:
            pop.append(mutate(rng.choice(elite), rng, sigma))
        if once and gen >= 1:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
