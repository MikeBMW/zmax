#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 状态子空间的最优度规是否**不同** —— 这正是「结构化分层」科学的依据

老倪 2026-10-18 两个命题:
  ①「证明流形引擎的度规约束对模型的控制最有效」
  ②「结构化分层是合理科学的」

做法 (纯 CPU, 不占 GPU):
  把 39 维真状态按 3 维滑窗切成若干**物理子空间**, 每个子空间上分别用
  su2 (Fubini–Study) / sphere (球面) / euclidean (无约束) 建流形, 比同一势函数下
  「∇Φ 方向 vs 真实运动方向」的一致性 (cos)。

  若最优度规在各子空间之间**显著不同** ⇒ 不存在单一度规通吃 ⇒ 状态空间必须**分层**,
  每层/每子空间用自己的几何 —— 命题②由此成立 (而不是"因为听起来合理")。
  若 su2/sphere 在多数子空间上优于 euclidean ⇒ 命题① (度规约束有用) 成立。

跑: ./gui-venv311/bin/python tools/ab_manifold_subspace.py [--win 3] [--eps 30]
落盘: zmax_data/eval/ab_manifold_subspace.json
exit: 0 两命题都有证据 / 3 未成立
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.manifold_engine import ManifoldEngine  # noqa: E402

H5 = os.path.join(ROOT, "zmax_data", "stable-wm-cache", "datasets", "optical_insert_v6_disturb.h5")
TYPES = ["su2", "sphere", "euclidean"]
M = 3.643


def load(n_fit_ep: int, n_run_ep: int):
    import h5py
    with h5py.File(H5, "r") as f:
        obs = np.asarray(f["observation"], dtype=np.float64)
        off = np.asarray(f["ep_offset"], dtype=np.int64)
        ln = np.asarray(f["ep_len"], dtype=np.int64)
    eps = [obs[off[i]:off[i] + ln[i]] for i in range(len(ln)) if ln[i] > 5]
    return np.concatenate(eps[:n_fit_ep], axis=0), eps[n_fit_ep:n_fit_ep + n_run_ep]


def cos_consistency(mt: str, Xf: np.ndarray, epr: list, dim: int) -> float | None:
    """该子空间上: ∇Φ 与真实位移方向的一致性 (cos, 越高越好)。"""
    eng = ManifoldEngine(manifold_type=mt, latent_dim=max(2, dim), state_dim=dim,
                         action_dim=min(4, dim), manifold_M=M, inertia=False)
    try:
        eng.fit(Xf)
        if not eng.fitted:
            return None
    except Exception:                                                       # noqa: BLE001
        return None
    cs = []
    for ep in epr:
        try:
            eng.goal_point = np.asarray(eng.project(ep[-1])["p"], float).ravel()
        except Exception:                                                   # noqa: BLE001
            continue
        _m, _g = eng.metric, eng.goal_point
        pot = (lambda q, _m=_m, _g=_g: 0.5 * float(_m.distance(np.asarray(q, float).ravel(), _g)) ** 2)
        for i in range(len(ep) - 1):
            try:
                rec = eng.step(ep[i], potential_fn=pot, dt=0.1)
                z0 = np.asarray(rec["p"], float).ravel()
                z1 = np.asarray(eng.project(ep[i + 1])["p"], float).ravel()
                gr = np.asarray(rec["grad"], float).ravel()
            except Exception:                                               # noqa: BLE001
                break
            dm = z1 - z0
            if np.linalg.norm(dm) > 1e-9 and np.linalg.norm(gr) > 1e-9:
                cs.append(-float(np.dot(gr, dm) / (np.linalg.norm(gr) * np.linalg.norm(dm))))
    return round(float(np.mean(cs)), 4) if cs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--win", type=int, default=3, help="子空间宽度 (维)")
    ap.add_argument("--stride", type=int, default=3, help="滑窗步长")
    ap.add_argument("--eps", type=int, default=30)
    ap.add_argument("--run-eps", type=int, default=8)
    a = ap.parse_args()

    Xf_all, epr_all = load(a.eps, a.run_eps)
    D = Xf_all.shape[1]
    wins = list(range(0, max(1, D - a.win + 1), a.stride))
    print(f"状态 {D} 维 → {len(wins)} 个子空间 (宽 {a.win}) · 拟合 {len(Xf_all)} 帧 · 评估 {len(epr_all)} ep\n")
    print(f"{'子空间':>12s} {'su2':>8s} {'sphere':>8s} {'euclid':>8s}   最优")
    rows = []
    for i0 in wins:
        sl = slice(i0, i0 + a.win)
        Xf, epr = Xf_all[:, sl], [e[:, sl] for e in epr_all]
        r = {"dims": [i0, i0 + a.win - 1]}
        for mt in TYPES:
            r[mt] = cos_consistency(mt, Xf, epr, a.win)
        vals = {k: v for k, v in r.items() if k in TYPES and v is not None}
        r["best"] = max(vals, key=vals.get) if vals else None
        rows.append(r)
        arrow = lambda v: ("%8.4f" % v) if v is not None else "       -"   # noqa: E731
        print(f"  [{i0:2d}-{i0 + a.win - 1:2d}] {arrow(r['su2'])} {arrow(r['sphere'])} "
              f"{arrow(r['euclidean'])}   {r['best']}")

    ok = [r for r in rows if r["best"]]
    if not ok:
        print("\n❌ 没有有效子空间")
        return 3

    # ── 命题①: 度规约束 (su2/sphere) 是否优于无约束 euclidean ──────────────
    beat = sum(1 for r in ok
               if r["best"] in ("su2", "sphere")
               and r.get("euclidean") is not None
               and max(r.get("su2") or -9, r.get("sphere") or -9) > r["euclidean"])
    g1 = ("①度规约束在多数子空间优于无约束基线 (su2/sphere > euclidean)",
          beat * 2 > len(ok), f"{beat}/{len(ok)} 个子空间")

    # ── 命题②: 最优度规随子空间变化 ⇒ 单一度规通吃不成立 ⇒ 必须分层 ────────
    from collections import Counter
    cnt = Counter(r["best"] for r in ok)
    top, top_n = cnt.most_common(1)[0]
    uniformity = top_n / len(ok)
    g2 = ("②最优度规随子空间变化 (无单一度规通吃 → 分层有依据)",
          uniformity < 0.80, f"最优分布 {dict(cnt)} · 最集中 {top} 占 {uniformity:.0%}")

    # ── 命题②补充: su2 与 sphere 各自在部分子空间最优 (不同几何各有主场) ───
    g3 = ("③su2 与 sphere 都有自己最优的子空间 (异构几何并存)",
          cnt.get("su2", 0) > 0 and cnt.get("sphere", 0) > 0,
          f"su2 {cnt.get('su2', 0)} 个 / sphere {cnt.get('sphere', 0)} 个 / "
          f"euclid {cnt.get('euclidean', 0)} 个")

    print()
    n_pass = 0
    for name, cond, det in (g1, g2, g3):
        print(("✅ " if cond else "❌ ") + name + "  " + det)
        n_pass += int(bool(cond))

    out = os.path.join(ROOT, "zmax_data", "eval", "ab_manifold_subspace.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "win": a.win, "state_dim": D,
                   "rows": rows, "best_count": dict(cnt),
                   "gates": [{"判据": n, "过": c, "实测": d} for n, c, d in (g1, g2, g3)],
                   "PASS": n_pass}, f, ensure_ascii=False, indent=1)
    print(f"\n判据 {n_pass}/3 PASS · 落盘 {out}")
    return 0 if n_pass == 3 else 3


if __name__ == "__main__":
    sys.exit(main())
