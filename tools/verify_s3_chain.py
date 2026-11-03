#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_s3_chain.py — 「逻辑条件 → 流形潜空间 → 预测 SU(2) 轨迹 → ω 指令」全链路实测

两种输入口径, 都能跑, 但**只有 ideal 是在役口径**:
  --ideal (默认)  ssobs 理想档 43D (geo_plan_impl.build_ideal_plan → ideal_obs.frame)
                  [0:3]手 [3]夹爪 [4:7]光模块 [36:39]目标/孔位  ← 与 su2.obs43_geometry 同口径
  --sim           metaworld 仿真 obs43
                  [0:3]手 [4:7]末端速度 [7:10]光模块 [36:39]阶段子目标  ← 与上面**不同**
                  直接喂 ssobs 会把"末端速度 − 阶段子目标"当成几何误差 (实测 ~500mm 假误差),
                  只作对照, 不作为在役读数

判据: ①群性质 ②多步预测误差(同阶段内) ③ω 限幅 ④解码自洽 ⑤实时性 ⑥几何误差随阶段收敛
产出 reports/s3_chain_report_<mode>.json + zmax_data/ss_live/s3_chain.jsonl
"""
import argparse
import collections
import json
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src"), os.path.join(REPO, "tools", "gui")):
    if p not in sys.path:
        sys.path.insert(0, p)

from lerobot.manifold.s3_chain import S3Chain, selftest                # noqa: E402
from lerobot.policies.left_right.state_space.su2 import (             # noqa: E402
    SU2Element, obs43_geometry)
import pose_caliper as pc                                            # noqa: E402

LIVE = os.path.join(REPO, "zmax_data", "ss_live")
OUT = os.path.join(REPO, "reports")


def frames_ideal(rate=10.0):
    """ssobs 理想档: 一个循环周期逐步取 43D (在役口径)"""
    from lerobot.engineering.nodes.geo_plan_impl import build_ideal_plan
    from lerobot.engineering.nodes import ideal_obs
    pl = build_ideal_plan()
    cyc = float(pl["cycle_s"])
    n = int(round(cyc * rate))
    for i in range(n):
        t = (i / rate) % cyc
        obs, meta = ideal_obs.frame(pl, t=t)
        yield i, np.asarray(obs, float), {
            "stage": str(meta.get("action") or ""), "label": str(meta.get("label") or ""),
            "plan": {"cycle_s": cyc, "uph": pl.get("uph"), "tact_s": pl.get("tact_s"),
                     "n_seg": pl.get("n_seg")}}


def frames_sim():
    """metaworld 仿真 obs43 (布局与 ssobs 不同, 只作对照)"""
    import state_space_sim as sss
    tr = sss.StateSpaceSim(log=None).run(io_every=10 ** 9)
    O = tr["obs"]
    for i in range(len(O)):
        st = str(tr["stage"][i]).replace("阶段 ", "").split("·")[0].strip()
        yield i, np.asarray(O[i], float), {
            "stage": st, "label": st,
            "frame_extra": {"mani_progress": tr["mani_progress"][i],
                            "mani_dperp": tr["mani_dperp"][i],
                            "mani_rem": tr["mani_rem"][i],
                            "u_sat": tr["u_sat"][i]}}


def run(mode="ideal", rate=10.0):
    ch = S3Chain(dt=1.0 / rate, horizon=8, omega_max=1.0)
    rows, qs, mss, resid, unit = [], [], [], [], 0.0
    qn_hat = []
    prev_stage, switches, plan = None, 0, {}
    for i, obs, meta in (frames_ideal(rate) if mode == "ideal" else frames_sim()):
        fr = {"stage": meta["stage"], **(meta.get("frame_extra") or {})}
        r = ch.step(fr, obs)
        if not r.get("ok"):
            rows.append({"i": i, "ok": False, "why": r.get("why")})
            continue
        plan = meta.get("plan") or plan
        q = np.asarray(r["exec_q"], float)
        qs.append(q)
        qn_hat.append(np.asarray(r["predict_next"]["q"], float))
        mss.append(r["ms"])
        unit = max(unit, abs(float(np.linalg.norm(q)) - 1.0))
        w = np.asarray(r["decode"]["omega_rad_s"][0], float)
        left = SU2Element.from_rotvec(w * ch.dt) * SU2Element(*q)
        q1 = np.asarray(r["predict"]["q"][0], float)
        resid.append(float(pc.s3_angle([left.w, left.x, left.y, left.z], q1)))
        sw = prev_stage is not None and meta["stage"] != prev_stage
        switches += int(sw)
        rows.append({"i": i, "ok": True, "stage": meta["stage"], "jump": sw,
                     "theta_deg": round(r["exec_theta_deg"], 3),
                     "geom_mm": round(float(np.linalg.norm(obs43_geometry(obs))) * 1000, 2),
                     "scene_theta_deg": round(r["scene_theta_deg"], 3),
                     "steps_needed": r["predict"]["steps_needed"], "eta_s": r["predict"]["eta_s"],
                     "omega0": round(float(r["decode"]["omega_norm_rad_s"][0]), 4),
                     "clamped": bool(r["decode"]["clamped"]), "ms": r["ms"]})
        prev_stage = meta["stage"]
    # 多步预测误差: 第 i 帧预测第 k 步 ↔ 第 i+k 帧真实群点 (同阶段内才算平滑指标)
    pred = {}
    for k in (1, 3, 8):
        same, jump = [], []
        for i in range(len(qs) - k):
            if not rows[i].get("ok"):
                continue
            qh = np.asarray(ch.predict(qs[i])["q"][k - 1], float)
            e = math.degrees(pc.s3_angle(qh, qs[i + k]))
            seg = {rows[j].get("stage") for j in range(i, i + k + 1) if rows[j].get("ok")}
            (jump if len(seg) > 1 else same).append(e)
        pred["+%d" % k] = {"same_stage_median_deg": round(float(np.median(same)), 3) if same else None,
                           "n": len(same),
                           "cross_stage_median_deg": round(float(np.median(jump)), 3) if jump else None,
                           "cross_n": len(jump)}
    ok = [r for r in rows if r.get("ok")]
    # 状态预测 (predict_next) 的 1 步误差 vs 零阶保持基线 (同阶段)
    pn_same, pn_cross, zoh_same = [], [], []
    for i in range(len(qs) - 1):
        if not rows[i].get("ok"):
            continue
        e = math.degrees(pc.s3_angle(qn_hat[i], qs[i + 1]))
        z = math.degrees(pc.s3_angle(qs[i], qs[i + 1]))
        same = rows[i].get("stage") == rows[i + 1].get("stage")
        (pn_same if same else pn_cross).append(e)
        if same:
            zoh_same.append(z)
    pred_next = {"same_stage": {"median_deg": round(float(np.median(pn_same)), 3) if pn_same else None,
                                "mean_deg": round(float(np.mean(pn_same)), 3) if pn_same else None,
                                "n": len(pn_same)},
                 "cross_stage": {"median_deg": round(float(np.median(pn_cross)), 3) if pn_cross else None,
                                 "n": len(pn_cross)},
                 "zoh_baseline_median_deg": round(float(np.median(zoh_same)), 3) if zoh_same else None,
                 "not_worse_than_zoh_ratio": round(float(np.mean(np.asarray(pn_same) <= np.asarray(zoh_same) + 1e-9)), 3)
                 if pn_same and zoh_same else None}
    ms_a = np.asarray(mss, float) if mss else np.array([0.0])
    by_stage = collections.OrderedDict()
    for r in ok:
        by_stage.setdefault(r["stage"], []).append(r)
    rep = {
        "mode": mode, "plan": plan,
        "selftest": selftest(200),
        "frames": len(rows), "ok_frames": len(ok), "stage_switches": switches,
        "ms": {"p50": round(float(np.percentile(ms_a, 50)), 3),
               "p95": round(float(np.percentile(ms_a, 95)), 3),
               "max": round(float(ms_a.max()), 3)},
        "unit_norm_max_err": unit,
        "decode_residual_rad": {"max": float(np.max(resid)) if resid else None,
                                "mean": float(np.mean(resid)) if resid else None},
        "pred_error": pred,
        "pred_next": pred_next,
        "omega_over_limit_frames": sum(1 for r in ok if r["clamped"]),
        "stage_summary": {s: {"n": len(v),
                              "theta_deg_mean": round(float(np.mean([x["theta_deg"] for x in v])), 2),
                              "geom_mm_mean": round(float(np.mean([x["geom_mm"] for x in v])), 2),
                              "scene_theta_deg_mean": round(float(np.mean([x["scene_theta_deg"] for x in v])), 2),
                              "omega0_mean": round(float(np.mean([x["omega0"] for x in v])), 3),
                              "eta_s_max": max(x["eta_s"] for x in v)}
                          for s, v in by_stage.items()},
    }
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(LIVE, exist_ok=True)
    with open(os.path.join(OUT, "s3_chain_report_%s.json" % mode), "w", encoding="utf-8") as f:
        json.dump({**rep, "sample": rows[:3] + rows[-3:]}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(LIVE, "s3_chain.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="用仿真 obs43 对照 (布局不同, 非在役口径)")
    ap.add_argument("--rate", type=float, default=10.0)
    a = ap.parse_args()
    rep = run("sim" if a.sim else "ideal", a.rate)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("\n报告: %s" % os.path.join(OUT, "s3_chain_report_%s.json" % rep["mode"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
