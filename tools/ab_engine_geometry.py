#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ab_engine_geometry.py — 用**引擎真身**跑几何完备性 A/B (2026-10-19)

四档, 同轨迹同目标同增益, 只改两个开关:
    A 基线      phi_metric=0 su2_tangent=0   (旧行为)
    B +度规势   phi_metric=1 su2_tangent=0
    C +切投影   phi_metric=0 su2_tangent=1
    D 两者都开  phi_metric=1 su2_tangent=1

在 su2 流形上, 用真轨迹 (optical_insert_v6_disturb.h5) 的相邻帧位移当真值, 量:
  ① 方向一致性  cos(−∇Φ, 真位移切向)   越高越好 (选对下降方向)
  ② 法向泄漏    |⟨∇Φ,p⟩|/(‖∇Φ‖‖p‖)    越低越好 (白做的功)
  ③ 收敛步数    沿 −∇Φ 走到 Φ<1e-3 的拍数  越少越好
  ④ 单调率      Φ 不减的拍占比          越高越好 (李雅普诺夫保证)

用法: ./gui-venv311/bin/python tools/ab_engine_geometry.py [--k 5] [--eps 200]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.manifold_engine import ManifoldEngine  # noqa: E402

H5 = os.path.join(ROOT, "zmax_data/stable-wm-cache/datasets/optical_insert_v6_disturb.h5")


def load_obs(h5_path: str, limit: int | None = None) -> np.ndarray:
    """读真轨迹 obs。兼容 (N,D) 或结构化 episode。"""
    import h5py

    with h5py.File(h5_path, "r") as f:
        keys = [k for k in f.keys()]
        cand = None
        for name in ("obs", "observations", "state", "states"):
            if name in f:
                cand = name
                break
        if cand is None:
            for k in keys:
                it = f[k]
                if hasattr(it, "shape") and it.ndim >= 2 and it.shape[-1] >= 20:
                    cand = k
                    break
        if cand is None:
            raise RuntimeError("找不到 obs 数据集, 顶层键=%s" % keys[:12])
        arr = np.asarray(f[cand][()], float)
    if arr.ndim == 3:
        arr = arr.reshape(-1, arr.shape[-1])
    arr = arr[:, :39] if arr.shape[1] > 39 else arr
    # 去掉全零/常量行 (占位帧)
    keep = np.asarray([np.std(r) > 1e-9 for r in arr])
    arr = arr[keep]
    return arr[:limit] if limit else arr


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def build(phi_metric: bool, su2_tangent: bool, state_dim: int) -> ManifoldEngine:
    e = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=state_dim,
                       action_dim=4, homeostasis=False,
                       phi_metric=phi_metric, su2_tangent=su2_tangent)
    return e


ARMS = [
    ("A 基线(旧)", False, False),
    ("B +度规势", True, False),
    ("C +切投影", False, True),
    ("D 两者都开", True, True),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5, help="目标取第 t+k 帧 (跳步, 避免目标=自身)")
    ap.add_argument("--eps", type=int, default=200, help="用多少段轨迹")
    ap.add_argument("--steps", type=int, default=40, help="收敛步数上限")
    a = ap.parse_args()

    obs = load_obs(H5)
    print("真轨迹 %s" % H5)
    print("  可用帧 %d · 维数 %d" % (obs.shape[0], obs.shape[1]))
    if obs.shape[0] < a.k + 10:
        print("❌ 帧数不足")
        return 1

    # ── 共享 encoder: 四档必须用**同一个** PCA, 否则不是同口径 ──
    base = build(False, False, obs.shape[1])
    fit_info = base.fit(obs, None)
    print("  encoder: latent=%d · 解释方差和=%s · 样本=%s"
          % (int(base.encoder.latent_dim),
             fit_info.get("explained_var_sum") if isinstance(fit_info, dict) else "—",
             fit_info.get("n_samples") if isinstance(fit_info, dict) else "—"))

    idx = np.linspace(0, obs.shape[0] - a.k - 1, min(a.eps, obs.shape[0] - a.k - 1)).astype(int)
    rows = {}
    for name, phi_m, su2_t in ARMS:
        eng = build(phi_m, su2_t, obs.shape[1])
        for attr in ("mu", "W", "latent_dim", "n_fit", "lift"):
            if hasattr(base.encoder, attr):
                setattr(eng.encoder, attr, getattr(base.encoder, attr))
        eng.fitted = True

        cos_l, leak_l, conv_l, mono_l, cos_raw_l = [], [], [], [], []
        for t in idx:
            r0 = eng.project(obs[t])
            r1 = eng.project(obs[t + a.k])
            p, goal = np.asarray(r0["p"], float), np.asarray(r1["p"], float)
            eng.current_manifold_point = p
            eng.goal_point = goal
            gf = eng.gradient_flow()
            grad = np.asarray(gf["grad"], float)
            ng = float(np.linalg.norm(grad))
            if ng < 1e-12:
                continue
            # 法向泄漏
            leak_l.append(abs(float(np.dot(grad, p))) / (ng * float(np.linalg.norm(p)) + 1e-12))
            # ── 割线参照对照 (2026-10-20) ──
            #   ⚠️ 这里用**未投影**的 p→goal (欧氏割线) 作参照。在球面流形上正确的目标方向是
            #   切空间里的测地线方向 (= 下面投影后的 to_goal), 割线不是测地线 ⇒ cos_raw **不是**
            #   "无偏真值", 不能拿它推翻原版结论。它唯一的用途: 量化「被投影掉的切向分量」
            #   = 割线与切线夹角。本轮实测 A 臂 cos_raw=1.0000 / C 臂 cos_raw=0.8010
            #   ⇒ 梯度本来就是欧氏割线方向, 投影代价 cos≈0.80。
            #   结论判定仍以原版 cos (切线参照) 为准。
            tg_raw = goal - p
            ntr = float(np.linalg.norm(tg_raw))
            if ntr > 1e-12:
                cos_raw_l.append(-float(np.dot(grad, tg_raw)) / (ng * ntr))
            # 真位移方向: p→goal 在切空间的投影
            to_goal = goal - p
            to_goal = to_goal - p * float(np.dot(to_goal, p)) / max(float(np.dot(p, p)), 1e-12)
            nt = float(np.linalg.norm(to_goal))
            if nt > 1e-12:
                cos_l.append(-float(np.dot(grad, to_goal)) / (ng * nt))
            # 收敛步数 (沿 −∇Φ, 球面 retraction)
            cur, phi_prev, nstep, viol = p.copy(), float(gf["phi"]), 0, 0
            for _ in range(a.steps):
                eng.current_manifold_point = cur
                g2 = eng.gradient_flow()
                nstep += 1
                phi_now = float(g2["phi"])
                if phi_now > phi_prev + 1e-9:
                    viol += 1
                phi_prev = phi_now
                if phi_now < 1e-3:
                    break
                cur = unit(cur + np.asarray(g2["descent"], float) * 0.05)
            conv_l.append(nstep)
            mono_l.append(1.0 - viol / max(nstep, 1))

        rows[name] = {
            "cos": float(np.mean(cos_l)) if cos_l else 0.0,
            "cos_raw": float(np.mean(cos_raw_l)) if cos_raw_l else 0.0,
            "leak": float(np.mean(leak_l)) if leak_l else 0.0,
            "conv": float(np.mean(conv_l)) if conv_l else 0.0,
            "mono": float(np.mean(mono_l)) if mono_l else 0.0,
            "n": len(cos_l),
        }
        print("  %-12s cos=%.4f (无偏raw=%.4f) · 泄漏=%.4f · 收敛拍=%.1f · 单调率=%.3f (n=%d)"
              % (name, rows[name]["cos"], rows[name]["cos_raw"], rows[name]["leak"],
                 rows[name]["conv"], rows[name]["mono"], rows[name]["n"]))

    # ── 判据 ──
    print("\n" + "=" * 84)
    print("判据")
    print("=" * 84)
    base_r, d_r = rows["A 基线(旧)"], rows["D 两者都开"]
    checks = [
        ("① 方向一致性提升", d_r["cos"] > base_r["cos"] + 0.01,
         "D %.4f > A %.4f (+%.4f)" % (d_r["cos"], base_r["cos"], d_r["cos"] - base_r["cos"])),
        ("② 法向泄漏下降", d_r["leak"] < base_r["leak"] * 0.5,
         "D %.4f < A %.4f 的一半" % (d_r["leak"], base_r["leak"])),
        ("③ 收敛更快或持平", d_r["conv"] <= base_r["conv"] + 1e-9,
         "D %.1f 拍 vs A %.1f 拍" % (d_r["conv"], base_r["conv"])),
        ("④ 单调率不劣化", d_r["mono"] >= base_r["mono"] - 1e-6,
         "D %.3f vs A %.3f" % (d_r["mono"], base_r["mono"])),
        ("⑤ 度规势单独有效(B>A)", rows["B +度规势"]["cos"] > base_r["cos"],
         "B %.4f vs A %.4f" % (rows["B +度规势"]["cos"], base_r["cos"])),
        ("⑥ 切投影单独有效(C>A)", rows["C +切投影"]["leak"] < base_r["leak"] * 0.5,
         "C 泄漏 %.4f vs A %.4f" % (rows["C +切投影"]["leak"], base_r["leak"])),
    ]
    npass = 0
    for nm, ok, det in checks:
        print("  %s %-24s %s" % ("✅" if ok else "❌", nm, det))
        npass += int(ok)
    print("-" * 84)
    print("  PASS %d / FAIL %d" % (npass, len(checks) - npass))
    out = os.path.join(ROOT, "reports/ab_engine_geometry.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"arms": rows, "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks],
                   "k": a.k, "eps": len(idx)}, f, ensure_ascii=False, indent=2)
    print("  报告 %s" % out)
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
