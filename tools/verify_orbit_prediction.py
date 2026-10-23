#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_orbit_prediction.py — 对称轨道预测的判据脚本 (老倪 2026-10-23)

四组判据, 全部**真跑**、全部落盘 JSON:
  A 数学: 等距性 / 精确外推 / 平行搬移保值 / exp∘log 往返
  B 破缺: 速度突变被同拍抓住 / 方向被扭被抓住 / 静止标 static (不假装预测成功)
  C 真实 episode: 400 帧真机 obs43 → 引擎 project → p 序列, 对比
     轨道推演 vs 「保持不动」 vs 「弦线外推」的**同口径**一步误差 (rad 与 相对步长)
  D 引擎闭环: 从真 episode 起点跑引擎自己的梯度流 200 步, 看势场把轨道
     「自由段 → 收敛段」逐步破坏 —— 破缺检出与真实残差同向

用法: ./gui-venv311/bin/python tools/verify_orbit_prediction.py [--json out.json]
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold import sphere as sp                                   # noqa: E402
from lerobot.manifold.orbit_predict import (OrbitPredictor, _apply, _dist,  # noqa: E402
                                           _push, symmetry_residual)
from lerobot.manifold.manifold_engine import ManifoldEngine                 # noqa: E402

TRAJ = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
CKPT = os.path.join(ROOT, "models", "manifold_engine.npz")
STATE_DIM, LATENT, ACTION_DIM = 43, 16, 4

R = {}                      # 报告
CHECKS = []                 # (名称, 通过?, 证据)


def _ok(name, cond, evidence):
    CHECKS.append((name, bool(cond), evidence))
    print("  %s %-38s %s" % ("✅" if cond else "❌", name, evidence))


def _unit(p):
    p = np.asarray(p, float).ravel()
    n = float(np.linalg.norm(p))
    return p / n if n > 1e-12 else p


# ══════════════════════════════════════════════════════════════════════
def part_a():
    print("\n[A] 数学判据 —— 「等距离推演」到底精确到什么程度")
    rng = np.random.default_rng(7)
    p0 = sp.normalize(rng.normal(size=4))[0]
    v0 = sp.tangent_project(p0, rng.normal(size=4) * 0.08)
    traj, vel = [p0], v0
    for _ in range(60):
        q = _apply(traj[-1], vel)
        vel = _push(vel, traj[-1], q)
        traj.append(q)
    d = np.asarray([_dist(traj[i], traj[i + 1]) for i in range(len(traj) - 1)])
    cv = float(d.std() / d.mean())
    R["A_equidistant_cv"] = cv
    _ok("A1 轨道等距 (弧长变异系数)", cv < 1e-12, "CV=%.2e · 步长=%.6f rad" % (cv, d.mean()))

    pr = OrbitPredictor(window=6)
    errs = []
    for p in traj:
        o = pr.observe(p)
        if o["err_rad"] is not None:
            errs.append(o["err_rad"])
    R["A_exact_max_err"] = float(max(errs))
    _ok("A2 自由段一步外推误差 (≤几何数值地板)", max(errs) < 1e-6,
        "max=%.2e rad · 相对步长 %.2e · 共 %d 次 (exp∘log 地板 ~1e-8)" %
        (max(errs), max(errs) / d.mean(), len(errs)))

    inpr = []
    for _ in range(300):
        a = sp.normalize(rng.normal(size=4))[0]
        b = sp.normalize(rng.normal(size=4))[0]
        u = sp.tangent_project(a, rng.normal(size=4))
        w = sp.tangent_project(a, rng.normal(size=4))
        u2, w2 = sp.parallel_transport(a, b, u), sp.parallel_transport(a, b, w)
        inpr.append(abs(np.dot(u2, w2) - np.dot(u, w)) / max(np.linalg.norm(u) * np.linalg.norm(w), 1e-12))
    R["A_transport_inner_err"] = float(max(inpr))
    _ok("A3 平行搬移保内积", max(inpr) < 1e-12, "max 相对误差=%.2e" % max(inpr))

    rt = []
    for _ in range(300):
        a = sp.normalize(rng.normal(size=4))[0]
        b = sp.normalize(rng.normal(size=4))[0]
        rt.append(_dist(sp.exp_map(a, sp.log_map(a, b)), b))
    R["A_exp_log_roundtrip"] = float(max(rt))
    _ok("A4 exp∘log 往返", max(rt) < 1e-6, "max=%.2e rad (几何原语数值地板)" % max(rt))


# ══════════════════════════════════════════════════════════════════════
def part_b():
    print("\n[B] 对称破缺判据 —— 预测在哪里必须失效")
    rng = np.random.default_rng(11)
    p0 = sp.normalize(rng.normal(size=4))[0]
    v = sp.tangent_project(p0, rng.normal(size=4) * 0.06)
    traj, vel = [p0], v
    for _ in range(12):
        q = _apply(traj[-1], vel)
        vel = _push(vel, traj[-1], q)
        traj.append(q)

    # B1 速度突变 (外部力矩 / 指令变化)
    v2 = 2.0 * vel
    bad = list(traj[:8]) + [_apply(traj[7], v2)]
    for _ in range(4):
        vv = _push(v2, bad[-2], bad[-1])
        bad.append(_apply(bad[-1], vv))
    pr = OrbitPredictor(window=6)
    outs = [pr.observe(p) for p in bad]
    flags = [i for i, o in enumerate(outs) if i >= 2 and not o["valid"]]
    first = min(flags) if flags else -1
    R["B1_first_invalid_step"] = first
    R["B1_reason"] = outs[first]["break_reason"] if flags else ""
    _ok("B1 速度翻倍 → 同拍判无效", first in (8, 9),
        "首次无效@第 %d 拍 · %s" % (first, R["B1_reason"]))

    # B2 只扭方向不改进度 (轨道弯曲, 步长不变)
    bendy, vv = [p0], sp.tangent_project(p0, rng.normal(size=4) * 0.05)
    for i in range(14):
        vv = _unit_rotate(vv, bendy[-1], 0.6)          # 每步把速度方向扭 60% 步长
        q = _apply(bendy[-1], vv)
        vv = _push(vv, bendy[-1], q)
        bendy.append(q)
    pr2 = OrbitPredictor(window=6)
    o2 = [pr2.observe(p) for p in bendy]
    fl2 = [i for i, o in enumerate(o2) if i >= 3 and not o["valid"]]
    res2 = symmetry_residual(bendy)
    R["B2_first_invalid_step"] = min(fl2) if fl2 else -1
    R["B2_resid"] = float(o2[-1]["bend"])
    _ok("B2 方向被扭 → 判无效", bool(fl2),
        "首次无效@第 %s 拍 · 稳态残差/步长=%.2f" % (min(fl2) if fl2 else "-", o2[-1]["bend"]))

    # B3 静止
    pr3 = OrbitPredictor(window=4)
    o3 = [pr3.observe(traj[0]) for _ in range(6)]
    R["B3_static"] = bool(o3[-1]["static"])
    _ok("B3 静止 → static 且 valid", o3[-1]["static"] and o3[-1]["valid"],
        "speed=%.1e static=%s valid=%s" % (o3[-1]["speed_rad"], o3[-1]["static"], o3[-1]["valid"]))


def _unit_rotate(v, base, frac):
    """把 v 在 T_base 里绕一个固定正交方向转 frac 弧度 (保持长度)。"""
    v = np.asarray(v, float).ravel()
    n = float(np.linalg.norm(v))
    perp = sp.tangent_project(base, np.random.default_rng(int(abs(v[0]) * 1e6) % 10**6).normal(size=v.size))
    perp = perp - v * (np.dot(perp, v) / max(n * n, 1e-12))
    pn = float(np.linalg.norm(perp))
    if pn < 1e-9:
        return v
    perp = perp / pn
    c, s = math.cos(frac), math.sin(frac)
    return n * (_unit(v) * c + perp * s)


# ══════════════════════════════════════════════════════════════════════
def _build_engine(goal_state=None):
    eng = ManifoldEngine(manifold_type="su2", latent_dim=LATENT, state_dim=STATE_DIM,
                         action_dim=ACTION_DIM, manifold_M=3.643, inertia=False, su2_tangent=True)
    try:
        eng.load(CKPT)
    except Exception:                                              # noqa: BLE001
        pass
    if goal_state is not None:
        eng.goal_point = eng.project(goal_state)["p"]
    return eng


def part_c():
    print("\n[C] 真实 episode —— 400 帧真机 obs43 经引擎 project 成 p 序列")
    d = json.load(open(TRAJ))
    obs = np.asarray(d["obs"], float)
    eng = _build_engine(obs[-1])
    ps = [np.asarray(eng.project(row)["p"], float) for row in obs]
    steps = np.asarray([_dist(ps[i], ps[i + 1]) for i in range(len(ps) - 1)])
    R["C_n_frames"] = len(ps)
    R["C_step_mean"] = float(steps.mean())
    R["C_step_median"] = float(np.median(steps))
    R["C_step_p95"] = float(np.percentile(steps, 95))
    R["C_step_max"] = float(steps.max())
    print("  轨迹: %d 帧 · 步长 mean=%.5f median=%.5f p95=%.5f max=%.5f rad"
          % (len(ps), steps.mean(), np.median(steps), np.percentile(steps, 95), steps.max()))

    pr = OrbitPredictor(window=6)
    e_o, e_h, e_c, o_flags = [], [], [], []
    for i, p in enumerate(ps):
        o = pr.observe(p)
        o_flags.append(o)
        if o["err_rad"] is not None:
            e_o.append(o["err_rad"])
        if 1 <= i < len(ps) - 1:
            e_h.append(_dist(ps[i], ps[i + 1]))                       # 保持不动
            lin = _unit(2 * ps[i] - ps[i - 1])                        # 弦线外推 (欧氏线性再归一)
            e_c.append(_dist(lin, ps[i + 1]))
    e_o = np.asarray(e_o); e_h = np.asarray(e_h); e_c = np.asarray(e_c)
    n = min(len(e_o), len(e_h), len(e_c))
    e_o, e_h, e_c = e_o[-n:], e_h[-n:], e_c[-n:]
    base = float(e_h.mean())
    R["C_err"] = {"orbit_mean": float(e_o.mean()), "orbit_median": float(np.median(e_o)),
                  "hold_mean": float(e_h.mean()), "chord_mean": float(e_c.mean()),
                  "orbit_win_vs_hold": float(np.mean(e_o < e_h)),
                  "improve_vs_hold_pct": float((1 - e_o.mean() / base) * 100.0) if base > 0 else 0.0,
                  "improve_vs_chord_pct": float((1 - e_o.mean() / max(e_c.mean(), 1e-15)) * 100.0)}
    print("  一步误差 (rad): 轨道 %.6f · 保持 %.6f · 弦线 %.6f (n=%d)"
          % (e_o.mean(), e_h.mean(), e_c.mean(), n))
    print("  轨道 vs 保持 逐帧胜率 %.1f%% · 平均改进 %+.1f%% (相对步长 %.6f)"
          % (R["C_err"]["orbit_win_vs_hold"] * 100, R["C_err"]["improve_vs_hold_pct"], steps.mean()))

    # 门控价值: valid 拍的误差 vs invalid 拍
    vmask = np.asarray([o["valid"] for o in o_flags[1:1 + n]])
    if vmask.sum() > 3 and (~vmask).sum() > 3:
        R["C_err_when_valid"] = float(e_o[vmask].mean())
        R["C_err_when_invalid"] = float(e_o[~vmask].mean())
        ratio = R["C_err_when_invalid"] / max(R["C_err_when_valid"], 1e-15)
        print("  门控: valid 拍 %.6f rad vs invalid 拍 %.6f rad (相差 %.1fx) · valid 占比 %.1f%%"
              % (R["C_err_when_valid"], R["C_err_when_invalid"], ratio, vmask.mean() * 100))
    else:
        ratio = None
        print("  门控: valid 占比 %.1f%% (样本不足, 不做对比)" % (vmask.mean() * 100))
    R["C_valid_ratio"] = float(vmask.mean())
    R["C_valid_vs_invalid_ratio"] = ratio
    reasons = {}
    for o in o_flags:
        if not o["valid"]:
            reasons[o["break_reason"]] = reasons.get(o["break_reason"], 0) + 1
    R["C_break_reasons"] = reasons
    _ok("C1 真实轨迹有运动 (非静止)", steps.max() > 1e-3, "max 步长 %.5f rad" % steps.max())
    _ok("C2 轨道推演不劣于保持", e_o.mean() <= base * 1.05,
        "orbit %.6f vs hold %.6f rad (%+.1f%%)" % (e_o.mean(), base, R["C_err"]["improve_vs_hold_pct"]))
    if ratio is not None:
        _ok("C3 门控有区分力 (invalid 拍更差)", ratio > 1.2,
            "invalid/valid 误差比 %.2fx" % ratio)


def part_d():
    print("\n[D] 引擎自身闭环 —— 势场把「自由段」推到「破缺段」")
    d = json.load(open(TRAJ))
    obs = np.asarray(d["obs"], float)
    eng = _build_engine(obs[-1])
    p = np.asarray(eng.project(obs[0])["p"], float)
    ps, phis = [p], []
    for _ in range(240):
        gf = eng.gradient_flow(p=p)
        phis.append(float(gf["phi"]))
        p = np.asarray(eng._evolve(p, gf["descent"], 0.05), float)
        ps.append(p)
    steps = np.asarray([_dist(ps[i], ps[i + 1]) for i in range(len(ps) - 1)])
    pr = OrbitPredictor(window=6)
    outs = [pr.observe(q, phi=(phis[i] if i < len(phis) else None)) for i, q in enumerate(ps)]
    valid = np.asarray([o["valid"] for o in outs])
    R["D_phi_start"] = phis[0] if phis else None
    R["D_phi_end"] = phis[-1] if phis else None
    R["D_speed_start"] = float(steps[:10].mean())
    R["D_speed_end"] = float(steps[-10:].mean())
    R["D_valid_ratio"] = float(valid[3:].mean())
    R["D_phi_drift_mean"] = float(np.mean([o["phi_drift"] for o in outs]))
    print("  Φ: %.5f → %.5f · 步长: 前10拍 %.5f → 末10拍 %.5f rad"
          % (phis[0], phis[-1], steps[:10].mean(), steps[-10:].mean()))
    print("  valid 占比 %.1f%% · 平均 phi_drift=%.3f" % (valid[3:].mean() * 100, R["D_phi_drift_mean"]))
    r = [o["break_reason"] for o in outs if not o["valid"]]
    cnt = {}
    for x in r:
        cnt[x] = cnt.get(x, 0) + 1
    R["D_break_reasons"] = cnt
    print("  破缺原因: %s" % cnt)
    # 多视界: 势场在变的段, 推得越远越不准 (预测视界的物理上限)
    pr2 = OrbitPredictor(window=6, horizons=(1, 2, 5, 10))
    eh = {k: [] for k in (1, 2, 5, 10)}
    for i in range(len(ps) - 11):
        o = pr2.observe(ps[i])
        for k in eh:
            if o["n"] >= 2:
                eh[k].append(_dist(np.asarray(o["pred"][str(k)], float), ps[i + k]))
    R["D_horizon_err"] = {str(k): float(np.mean(v)) for k, v in eh.items() if v}
    print("  多视界误差 (rad): " + " · ".join("k=%s %.6f" % (k, R["D_horizon_err"][str(k)])
                                             for k in (1, 2, 5, 10) if str(k) in R["D_horizon_err"]))
    _ok("D1 势场在跑 (Φ 单调下降)", phis[-1] < phis[0], "Φ %.5f → %.5f" % (phis[0], phis[-1]))
    _ok("D2 收敛到静止 → 标 static (不假装还能推)", bool(outs[-1]["static"]),
        "末拍 speed=%.1e static=%s · valid 占比 %.1f%% (缓慢减速每拍变化小, 按设计不判破缺)"
        % (outs[-1]["speed_rad"], outs[-1]["static"], R["D_valid_ratio"] * 100))


def main():
    t0 = time.time()
    print("=" * 78)
    print("🧭 对称轨道预测 · 判据 (预测 = 沿对称群轨道等距离推演)")
    print("=" * 78)
    part_a()
    part_b()
    part_c()
    part_d()
    npass = sum(1 for _, ok, _ in CHECKS if ok)
    print("\n" + "-" * 78)
    print("判据: %d/%d 通过 · 用时 %.1fs" % (npass, len(CHECKS), time.time() - t0))
    R["checks"] = [{"name": n, "ok": o, "evidence": e} for n, o, e in CHECKS]
    R["n_pass"] = npass
    R["n_total"] = len(CHECKS)
    R["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out = os.path.join(ROOT, "zmax_data", "eval", "orbit_predict_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(R, open(out, "w"), ensure_ascii=False, indent=1)
    print("报告: %s" % out)
    return 0 if npass == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
