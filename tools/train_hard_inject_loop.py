#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_hard_inject_loop.py — 硬注入自主训练闭环（ZMP-2026-020）

闭环六段
--------
① 数据      构造/加载训练与评估集（可选真轨迹，默认受控合成）
② 训练      三种损失对照：isotropic / metric / hybrid
③ 评估      轴向与径向误差分别统计（不能只看总损失）
④ 门禁      轴向改善达标 且 径向不退化 才放行；否则拒绝导出
⑤ 导出      权重 + 报告(json)，写入 zmax_data/hard_inject/
⑥ 回读      重新加载导出的权重并复算指标，与导出前逐位对齐

为什么必须分轴向/径向评估
--------------------------
总损失下降 ≠ 任务变好。马氏加权在容量受限时会让总损失下降、
但径向误差爆炸（实测 +948%）。只看 loss 会把这种模型当成好模型放行。

门禁逻辑
--------
- 轴向误差相对基线改善 ≥ min_gain（默认 5%）；或 baseline 已足够好时放行
- 径向误差相对基线退化 ≤ max_regress（默认 15%）
- 两条任一不满足 ⇒ 拒绝导出，退出码 2

用法
----
  gui-venv311/bin/python tools/train_hard_inject_loop.py                 # 合成数据快速闭环
  gui-venv311/bin/python tools/train_hard_inject_loop.py --hidden 64 --steps 1500
  gui-venv311/bin/python tools/train_hard_inject_loop.py --traj <path.json>   # 接真轨迹
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

from lerobot.policies.manifold.metric_inject import (  # noqa: E402
    metric_flow_loss, isotropic_flow_loss, metric_matrix,
)

OUT_DIR = os.path.join(ROOT, "zmax_data", "hard_inject")
AXIS = np.array([0.0, 0.0, 1.0])
SIG_T, SIG_N = 0.30, 6.00


# ══ ① 数据 ══════════════════════════════════════════════════════════
def load_real_traj(path: str):
    """从真轨迹取 (obs → 动作)。obs_dim 43、动作取 u_exec_vec 前 3 维。"""
    d = json.load(open(path, encoding="utf-8"))
    obs = np.asarray(d.get("obs") or [], dtype=np.float32)
    u = np.asarray(d.get("u_exec_vec") or [], dtype=np.float32)
    if obs.size == 0 or u.size == 0:
        raise ValueError("轨迹缺 obs 或 u_exec_vec")
    n = min(len(obs), len(u))
    obs, u = obs[:n], u[:n, :3]
    # 只用前 16 个 obs 维度做输入(避免维度爆炸, 也足够代表几何状态)
    X = obs[:, :16]
    # 标记哪些点是径向/轴向(用动作的 z 分量近似轴向)
    return X, u, "traj"


def synth(n, seed=0):
    """受控合成任务：轴向主导、径向需精细。

    刻意让轴向与径向的**信号强度不同**，才能暴露加权损失的差异。
    """
    rng = np.random.RandomState(seed)
    x = rng.randn(n, 3).astype(np.float32) * np.array([0.5, 0.5, 3.0], dtype=np.float32)
    v = np.stack([-0.8 * x[:, 0], -0.8 * x[:, 1], -0.6 * x[:, 2]], axis=1)
    return x, v.astype(np.float32), "synth"


# ══ ② 训练 ══════════════════════════════════════════════════════════
def build_model(in_dim: int, hidden: int, torch, nn):
    class MLP(nn.Module):
        def __init__(s):
            super().__init__()
            s.net = nn.Sequential(nn.Linear(in_dim, hidden), nn.SiLU(),
                                  nn.Linear(hidden, hidden), nn.SiLU(),
                                  nn.Linear(hidden, 3))
        def forward(s, x):
            return s.net(x)
    return MLP()


def train_one(mode, X, V, hidden, steps, lr, noise, torch, nn):
    """mode: isotropic | metric | hybrid"""
    torch.manual_seed(1)
    m = build_model(X.shape[1], hidden, torch, nn)
    opt = torch.optim.Adam(m.parameters(), lr=lr)
    Xt = torch.from_numpy(X)
    Pt = torch.tensor(np.eye(3) - np.outer(AXIS, AXIS), dtype=torch.float32)
    M_t = torch.tensor(metric_matrix(AXIS, SIG_T, SIG_N), dtype=torch.float32)
    lam = 10.0 if mode == "hybrid" else 0.0
    last = None
    for _ in range(steps):
        idx = torch.randint(0, Xt.shape[0], (min(256, Xt.shape[0]),))
        xb = Xt[idx]
        # ⚠️ 噪声必须与 xb 同 dtype，否则 float64×float32 报错
        vb = torch.from_numpy(V)[idx] + torch.randn(len(idx), 3) * noise
        pred = m(xb)
        e = pred - vb
        if mode == "isotropic":
            loss = (e ** 2).sum(1).mean()
        else:
            loss = torch.einsum("bi,ij,bj->b", e, M_t, e).mean()
            if lam > 0:
                er = e @ Pt.T
                loss = loss + lam * (er ** 2).sum(1).mean()
        opt.zero_grad(); loss.backward(); opt.step()
        last = float(loss.item())
    return m, last


# ══ ③ 评估 ══════════════════════════════════════════════════════════
def evaluate(m, X, V, torch):
    with torch.no_grad():
        pred = m(torch.from_numpy(X)).numpy()
    e = pred - V
    axial = float(np.abs(e[:, 2]).mean())
    radial = float(np.hypot(e[:, 0], e[:, 1]).mean())
    total = float(np.sqrt((e ** 2).mean()))
    return {"axial": axial, "radial": radial, "rmse": total}


# ══ 主流程 ══════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--noise", type=float, default=0.15)
    ap.add_argument("--traj", default=None, help="真轨迹 json（默认用受控合成数据）")
    ap.add_argument("--min-gain", type=float, default=0.05, help="轴向最小改善比例")
    ap.add_argument("--max-regress", type=float, default=0.15, help="径向最大允许退化比例")
    args = ap.parse_args()

    try:
        import torch
        import torch.nn as nn
    except Exception as e:                                               # noqa: BLE001
        print("✗ torch 不可用: %s" % e)
        return 3

    t0 = time.time()
    print("=" * 80)
    print("硬注入自主训练闭环（ZMP-2026-020）")
    print("=" * 80)

    # ① 数据
    if args.traj:
        Xtr, Vtr, src = load_real_traj(args.traj)
        Xev, Vev = Xtr[-max(200, len(Xtr) // 5):], Vtr[-max(200, len(Xtr) // 5):]
        print("\n[①] 数据: %s  train=%s eval=%s  (真轨迹)"
              % (os.path.basename(args.traj), Xtr.shape, Xev.shape))
    else:
        Xtr, Vtr, src = synth(20000, seed=0)
        Xev, Vev, _ = synth(4000, seed=7)
        print("\n[①] 数据: 受控合成  train=%s eval=%s" % (Xtr.shape, Xev.shape))

    # ② 训练三种损失
    print("\n[②] 训练（hidden=%d steps=%d）" % (args.hidden, args.steps))
    models = {}
    for mode in ("isotropic", "metric", "hybrid"):
        t = time.time()
        m, l = train_one(mode, Xtr, Vtr, args.hidden, args.steps, args.lr, args.noise, torch, nn)
        models[mode] = (m, l)
        print("     %-10s 训练损失 %.6f   用时 %.1fs" % (mode, l, time.time() - t))

    # ③ 评估
    print("\n[③] 评估（轴向/径向分开看，不能只看总损失）")
    ev = {}
    for mode, (m, _) in models.items():
        r = evaluate(m, Xev, Vev, torch)
        ev[mode] = r
        print("     %-10s 轴向 %.5f   径向 %.5f   rmse %.5f"
              % (mode, r["axial"], r["radial"], r["rmse"]))

    base = ev["isotropic"]
    print("\n     相对各向同性基线：")
    best = None
    for mode in ("metric", "hybrid"):
        r = ev[mode]
        ga = 1 - r["axial"] / max(base["axial"], 1e-12)
        gr = r["radial"] / max(base["radial"], 1e-12) - 1
        print("     %-10s 轴向改进 %+6.2f%%   径向变化 %+7.2f%%" % (mode, 100 * ga, 100 * gr))
        score = ga - max(0.0, gr)
        if best is None or score > best[1]:
            best = (mode, score, ga, gr)

    # ④ 门禁
    mode, _, ga, gr = best
    print("\n[④] 门禁判定（候选=%s）" % mode)
    ok_gain = ga >= args.min_gain
    ok_reg = gr <= args.max_regress
    print("     轴向改善 %.2f%% ≥ %.0f%% ? %s" % (100 * ga, 100 * args.min_gain,
                                                "✓" if ok_gain else "✗"))
    print("     径向退化 %.2f%% ≤ %.0f%% ? %s" % (100 * gr, 100 * args.max_regress,
                                                "✓" if ok_reg else "✗"))
    if not (ok_gain and ok_reg):
        print("\n     ✗ 门禁未通过 —— 拒绝导出。")
        print("       （这是设计的正常行为：宁可不出模型，也不放一个径向崩掉的模型进产线）")
        rep = {"passed": False, "candidate": mode, "eval": ev, "gate":
               {"axial_gain": ga, "radial_regress": gr,
                "min_gain": args.min_gain, "max_regress": args.max_regress},
               "data_src": src, "hidden": args.hidden, "steps": args.steps,
               "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        os.makedirs(OUT_DIR, exist_ok=True)
        pp = os.path.join(OUT_DIR, "train_report_rejected.json")
        json.dump(rep, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("       报告已存 %s" % pp)
        return 2

    # ⑤ 导出
    print("\n[⑤] 导出")
    os.makedirs(OUT_DIR, exist_ok=True)
    m = models[mode][0]
    ckpt = os.path.join(OUT_DIR, "policy_%s.pt" % mode)
    torch.save({"state_dict": m.state_dict(), "mode": mode,
                "in_dim": int(Xtr.shape[1]), "hidden": args.hidden,
                "sigma_t": SIG_T, "sigma_n": SIG_N, "axis": AXIS.tolist(),
                "eval": ev[mode]}, ckpt)
    print("     权重 %s (%d B)" % (ckpt, os.path.getsize(ckpt)))

    # ⑥ 回读复算
    print("\n[⑥] 回读校验（重新加载并复算，必须与导出前一致）")
    ck = torch.load(ckpt, map_location="cpu", weights_only=False)
    m2 = build_model(ck["in_dim"], ck["hidden"], torch, nn)
    m2.load_state_dict(ck["state_dict"]); m2.eval()
    r2 = evaluate(m2, Xev, Vev, torch)
    d_ax = abs(r2["axial"] - ev[mode]["axial"])
    d_rd = abs(r2["radial"] - ev[mode]["radial"])
    print("     回读: 轴向 %.5f (Δ%.2e)  径向 %.5f (Δ%.2e)"
          % (r2["axial"], d_ax, r2["radial"], d_rd))
    ok_round = d_ax < 1e-6 and d_rd < 1e-6
    print("     逐位对齐: %s" % ("✓" if ok_round else "✗"))

    rep = {"passed": bool(ok_round), "candidate": mode, "eval": ev,
           "gate": {"axial_gain": ga, "radial_regress": gr,
                    "min_gain": args.min_gain, "max_regress": args.max_regress},
           "roundtrip": {"axial": r2["axial"], "radial": r2["radial"],
                         "aligned": ok_round},
           "data_src": src, "hidden": args.hidden, "steps": args.steps,
           "ckpt": os.path.relpath(ckpt, ROOT), "elapsed_s": round(time.time() - t0, 1),
           "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    pp = os.path.join(OUT_DIR, "train_report.json")
    json.dump(rep, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("     报告 %s" % pp)

    print("\n" + "=" * 80)
    print("闭环 %s   用时 %.1fs" % ("PASS" if ok_round else "FAIL", time.time() - t0))
    print("=" * 80)
    return 0 if ok_round else 1


if __name__ == "__main__":
    sys.exit(main())
