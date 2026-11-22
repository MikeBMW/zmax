#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dump_layers_v2.py — 用**新真源**(239 点 v2 轨迹) 落盘五流形状态真值 layers_239.json。

为什么单独一支脚本: `se3_layers.dump_layers()` 里输出名写死 `layers_215.json`,
换表时顺手覆盖 215 的留存就是改历史。这里只读 v2 三件套:
  · real_traj_joints_v2.json  (239 点 TCP+关节, 动作真源)
  · traj_phase_v2.json        (弧长相位 s)
  · traj_hopf_v2.json         (n/φ 参考)
输出: zmax_data/se3_layers/layers_239.json + selftest_239.json, 不碰 215 的任何文件。

判据 (不过就 raise, 不静默降级):
  project_residual ≤ 1e-8 · geodesic_half_rel ≤ 1e-6 · hopf_roundtrip ≤ 1e-5° ·
  n_vs_Rcol ≤ 1e-5° · 相位 back_steps == 0 · 首尾闭合误差 < 5e-3
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from lerobot.manifold.se3_layers import SE3Layered  # noqa: E402

TRAJ = ROOT / "zmax_data/rokae_sdk/real_traj_joints_v2q.json"   # v2 + q(rpy→quat), 动作真源仍是 v2
PHASE_SRC = ROOT / "zmax_data/rokae_sdk/traj_phase_v2.json"
PHASE = ROOT / "zmax_data/rokae_sdk/traj_phase_v2_loop.json"   # S¹ 口径: 闭环相位, s_last<1
HOPF = ROOT / "zmax_data/rokae_sdk/traj_hopf_v2.json"
OUTDIR = ROOT / "zmax_data/se3_layers"
OUT = OUTDIR / "layers_239.json"
ST = OUTDIR / "selftest_239.json"


def _loop_phase() -> dict:
    """把 s 按**闭环**归一: s_i = cum_i / (cum_last + 收口间距)。

    traj_phase_v2.json 的末帧 s 正好 = 1.0, 而 S¹ 要求 s∈[0,1) —— 1.0 ≡ 0 会被
    se3_layers 判成“相位回退 1 步 + 闭合误差 1.0”。215 表当年用的是 0.999503
    (即分母含收口段), 这里按同一口径重算, 不是随手缩一下。
    """
    import math
    fr = json.load(open(TRAJ))["frames"]
    cum = [0.0]
    for a, b in zip(fr, fr[1:]):
        cum.append(cum[-1] + math.dist(a["p"], b["p"]) * 1000.0)
    gap = math.dist(fr[-1]["p"], fr[0]["p"]) * 1000.0
    L = cum[-1] + gap
    rows = [{"i": i, "s": round(c / L, 6), "prog": round(c, 3), "su": round(c, 3),
             "s_mm": round(c, 3), "ds_mm": round(c - cum[i - 1], 3) if i else 0.0,
             "t": fr[i].get("t", 0.0)} for i, c in enumerate(cum)]
    doc = {"frames": rows, "summary": {"n_frames": len(rows), "len_mm": round(L, 3),
           "loop_gap_mm": round(gap, 3), "src": str(TRAJ),
           "note": "闭环相位口径: 分母含收口段 ⇒ s_last<1 (S¹ 合法)"}}
    tmp = PHASE.with_suffix(".tmp")
    json.dump(doc, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, PHASE)
    return doc


def main() -> int:
    _loop_phase()
    for p in (TRAJ, PHASE, HOPF):
        if not p.exists():
            raise SystemExit(f"缺文件: {p}")
    L = SE3Layered(traj=TRAJ, phase=PHASE, hopf_ref=HOPF)
    n = len(L.frames())
    if n != 239:
        raise SystemExit(f"帧数不是 239 而是 {n} — 真源不对, 停")

    st = L.selftest()
    c = st["criteria"]
    proj = max(c["project_residual_worst"].values())
    geo = max(c["geodesic_half_rel_err"].values())
    hopf = c["hopf_roundtrip_deg_max"]
    nerr = c["n_vs_Rcol_deg_max"]
    back = c["phase"]["back_steps"]
    clos = c["phase"]["closure_err"]
    print(json.dumps({"n": n, "proj": proj, "geo": geo, "hopf_deg": hopf,
                      "n_vs_Rcol_deg": nerr, "phase_back": back,
                      "closure_err": clos, "M": st["M"]}, ensure_ascii=False))
    fails = []
    if proj > 1e-8: fails.append(f"project_residual {proj}")
    if geo > 1e-6: fails.append(f"geodesic_half_rel {geo}")
    if hopf > 1e-5: fails.append(f"hopf_roundtrip {hopf}")
    if nerr > 1e-5: fails.append(f"n_vs_Rcol {nerr}")
    if back != 0: fails.append(f"phase back_steps {back}")
    if clos > 5e-3: fails.append(f"closure_err {clos}")
    if fails:
        raise SystemExit("判据不过: " + "; ".join(fails))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n):
        s = L.snapshot(i)
        rows.append({"i": i, "A_mm": s["A"]["mm"], "B_n": s["B"]["n"],
                     "C_q": s["C"]["q"], "C_theta_deg": s["C"]["theta_deg"],
                     "D_phi_deg": s["D"]["phi_deg"], "E_s": s["E"]["s"], "TQ": s["TQ"]})
    doc = {"src": str(TRAJ), "n": n,
           "convention": "X=(p∈ℝ³, n∈S², φ∈S¹, q̇∈TQ, s∈S¹); q=(x,y,z,w); n=R·e₃",
           "layers": st["layers"], "M": st["M"], "frames": rows,
           "from": "real_traj_joints_v2.json (239 点真机回放真源)",
           "dump_src": "tools/dump_layers_v2.py"}
    tmp = OUT.with_suffix(".tmp")
    json.dump(doc, open(tmp, "w"), ensure_ascii=False)
    os.replace(tmp, OUT)
    json.dump(st, open(ST, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "out": str(OUT), "n": n,
                      "E_s_first": rows[0]["E_s"], "E_s_last": rows[-1]["E_s"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
