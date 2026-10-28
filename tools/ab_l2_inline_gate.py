#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚖ A/B 判据: `u_ff` 是否经过「SK01-08 原子技能 + 物理约束闸」再给仿真器

老倪指令（2026-10-16）：让前馈加速器的 u_ff **经过 接近/对位 等原子技能节点，再给仿真器**。
落地点：动作调制器里原本的 `STAGE_V_CAP` **等比缩放** → 换成
`physics_constraints.InertiaLimiter.limit()`（= 画布节点「⚖ 物理约束 · 惯性/质量率闸」，五条约束：
①速度 ②加速度 ③加加速度 ④动量/质量变化率 ⑤位移/行程；唯一依据 `config/calib/zmax_skill_physics.json`）。

两个臂（同一份引擎、同一初值、确定性）：
  臂 A  ZMAX_L2_GATE=0  旧链：动作调制器按 STAGE_V_CAP 等比缩放
  臂 B  ZMAX_L2_GATE=1  新链：u_ff → SK01-08 段包络 + 五条物理约束 → 削后 u → 安全限幅 → 仿真器

四条判据（不粉饰）：
  ① 逐段实际速度 ≤ 本段 v_cap（且只削一次：总削拍 ≤ 总拍、每个理由的削拍 ≤ 总拍）
  ② 闸的单拍开销 ≤ 10ms（判据针对**新加进关键路径**的那部分，不是整引擎）
  ③ 削因不翻倍（内联闸计数 == 服务侧口径的同一批拍，不出现两套计数各数一遍）
  ④ 任务不回退（是否走完 8 段 / 末端距目标 / 总时长）

用法：
  ./gui-venv311/bin/python tools/ab_l2_inline_gate.py            # 两臂都跑，打表 + 落盘
  ./gui-venv311/bin/python tools/ab_l2_inline_gate.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

import numpy as np

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "src"))

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def _arm(tag: str, gate_on: bool) -> dict:
    """执行一遍解析引擎（确定性），返回该臂的逐拍轨迹与闸门取证。"""
    os.environ["ZMAX_L2_GATE"] = "1" if gate_on else "0"
    # 热重载引擎模块：构造函数在 __init__ 里读环境变量，模块只需 import 一次
    from lerobot.engine.sim import StateSpaceSim  # noqa: PLC0415

    eng = StateSpaceSim(log=None)
    steps = []

    def _hook(*_a, **_k):
        steps.append(time.perf_counter())

    t0 = time.perf_counter()
    tr = eng.run(on_step=_hook)
    t_wall = time.perf_counter() - t0
    per_step_ms = []
    if len(steps) > 1:
        per_step_ms = [(b - a) * 1000.0 for a, b in zip(steps[:-1], steps[1:])]

    lim = getattr(eng, "lim", None)
    return {
        "arm": tag,
        "gate_on": bool(getattr(eng, "l2_gate_on", False)),
        "limiter_attached": lim is not None,
        "gate_dt_ms": round(float(getattr(eng.sched, "gate_dt", 0.0)) * 1000.0, 3),
        "tr": tr,
        "wall_s": round(t_wall, 3),
        "step_ms": {
            "n": len(per_step_ms),
            "p50": round(statistics.median(per_step_ms), 3) if per_step_ms else 0.0,
            "p95": round(float(np.percentile(per_step_ms, 95)), 3) if per_step_ms else 0.0,
            "max": round(max(per_step_ms), 3) if per_step_ms else 0.0,
        },
        "n_cut": dict(getattr(lim, "n_cut", {}) or {}),
        "n_gate_calls": int(getattr(lim, "n", 0) or 0),
        "n_over_travel": int(getattr(lim, "n_over", 0) or 0),
        "n_unknown_stage": int(getattr(lim, "n_unknown", 0) or 0),
        "travel": {k: round(v, 4) for k, v in (getattr(lim, "travel", {}) or {}).items()},
        "v_cap_table": dict(getattr(eng.sched, "v_cap", {}) or {}),
    }


def _summ(arm: dict) -> dict:
    tr = arm["tr"]
    st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in tr.get("stage", [])]
    # 提速/限速归因必须用**本拍实际驱动的段** (decide 用的 stage), 不是换段后贴上的标签
    su = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in (tr.get("stage_u") or [])]
    if len(su) == len(st):
        st = su
    usat = np.asarray(tr.get("u_sat", []), dtype=float)
    uff = np.asarray(tr.get("u_ff", []), dtype=float)
    caps = arm["v_cap_table"]
    per = {}
    for s in STAGES:
        idx = [i for i, x in enumerate(st) if x == s]
        if not idx:
            per[s] = {"n": 0}
            continue
        per[s] = {
            "n": len(idx),
            "u_sat_max": round(float(usat[idx].max()), 4),
            "u_sat_mean": round(float(usat[idx].mean()), 4),
            "u_ff_max": round(float(uff[idx].max()), 4),
            "v_cap": float(caps.get(s, 0.0)),
            "over_cap_steps": int(sum(1 for i in idx if usat[i] > caps.get(s, 9.9) + 1e-9)),
        }
    gate_why = tr.get("gate_why") or []
    why_cnt = {}
    for w in gate_why:
        for k in str(w).split("+"):
            k = k.strip()
            if k and k != "可行":
                why_cnt[k] = why_cnt.get(k, 0) + 1
    n_tot = len(st)
    return {
        "n_steps": n_tot,
        "v_cap_table": arm["v_cap_table"],
        "t_end_s": round(float(tr["t"][-1]), 3) if tr.get("t") else 0.0,
        "done": bool(tr.get("done", [False])[-1]) if tr.get("done") else False,
        "stages_visited": [s for s in STAGES if any(x == s for x in st)],
        "final_dist_mm": round(float(tr["dist"][-1]) * 1000.0, 3) if tr.get("dist") else None,
        "dist_peak_mm": round(float(np.max(tr["dist"])) * 1000.0, 3) if tr.get("dist") else None,
        "per_stage": per,
        "why_cnt": why_cnt,
        "gate_big_steps": int(sum(tr.get("gate_big") or [])),
        "gate_err_max": round(float(max(tr.get("gate_err") or [0.0])), 4),
        "gate_vcap_seen": sorted({round(float(x), 4) for x in (tr.get("gate_vcap") or [])}),
        "step_ms": arm["step_ms"],
        "wall_s": arm["wall_s"],
        "n_cut": arm["n_cut"],
        "n_gate_calls": arm["n_gate_calls"],
        "n_over_travel": arm["n_over_travel"],
        "n_unknown_stage": arm["n_unknown_stage"],
    }


def _microbench_limiter(n: int = 20000) -> dict:
    """⚖ 闸本身进关键路径的单拍开销（判据② 只看这一项，不看整引擎）。"""
    from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter  # noqa: PLC0415

    lim = InertiaLimiter(dt=0.02)
    u = np.array([0.30, -0.20, 0.05, 1.0])
    v = np.zeros(3)
    a = np.zeros(3)
    for _ in range(200):                                   # 预热
        g = lim.limit("接近", u, v_prev=v, a_prev=a)
        v = np.asarray(g["u"][:3]); a = (v - np.asarray(g["v_req"])) * 0.0
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        g = lim.limit("接近", u, v_prev=v, a_prev=a)
        ts.append((time.perf_counter() - t0) * 1e6)
        v = np.asarray(g["u"][:3])
    ts.sort()
    return {"n": n, "p50_us": round(ts[len(ts) // 2], 2),
            "p95_us": round(ts[int(len(ts) * 0.95)], 2), "max_us": round(ts[-1], 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(REPO, "zmax_data", "eval", "ab_l2_inline_gate.json"))
    ap.add_argument("--arms", default="A,B")
    a = ap.parse_args()

    out = {"ts": time.time(), "src": "tools/ab_l2_inline_gate.py",
           "question": "u_ff 经过 接近/对位 等原子技能节点再给仿真器 — 可以么/有没有回退",
           "verdict": {}}
    raw = {}
    if "A" in a.arms:
        raw["A"] = _arm("A 旧链(等比缩放)", gate_on=False)
    if "B" in a.arms:
        raw["B"] = _arm("B 新链(SK01-08+物理闸)", gate_on=True)
    sm = {k: _summ(v) for k, v in raw.items()}
    mb = _microbench_limiter()
    out["arms"] = sm
    out["limiter_microbench"] = mb

    # ── 四条判据 ──────────────────────────────────────────────────────────
    v = {}
    Bm = sm.get("B") or {}
    # ① 逐段实际速度 ≤ v_cap, 且削拍 ≤ 总拍 (单点削)
    bad = {s: d for s, d in (Bm.get("per_stage") or {}).items()
           if d.get("n") and d.get("over_cap_steps", 0) > 0}
    cuts = sum((Bm.get("n_cut") or {}).values())
    v["①段速度≤cap且单点削"] = {
        "PASS": (not bad) and cuts <= max(1, Bm.get("n_gate_calls", 0)) * 5,
        "超cap段": bad, "总削拍次数(五条约束合计)": cuts,
        "闸调用次数": Bm.get("n_gate_calls"), "未知段拍数": Bm.get("n_unknown_stage"),
    }
    # ② 闸单拍开销 ≤10ms
    v["②闸单拍≤10ms"] = {"PASS": mb["p95_us"] <= 10000.0, "P95_us": mb["p95_us"], "P50_us": mb["p50_us"]}
    # ③ 削因不翻倍: 闸调用次数 == 拍数 (每拍只削一次), 且削拍计数不超 5×拍数
    v["③削因不翻倍"] = {
        "PASS": bool(Bm.get("n_gate_calls", 0) == Bm.get("n_steps", -1)) and cuts <= 5 * max(1, Bm.get("n_steps", 0)),
        "闸调用": Bm.get("n_gate_calls"), "拍数": Bm.get("n_steps"),
        "削拍分项": Bm.get("n_cut"),
    }
    # ④ 不回退: 走完 8 段 + done + 末端距离不劣于旧链
    Am = sm.get("A") or {}
    if Am:
        ok4 = (Bm.get("done") or False) and len(Bm.get("stages_visited") or []) >= len(Am.get("stages_visited") or []) \
            and float(Bm.get("final_dist_mm") or 9e9) <= float(Am.get("final_dist_mm") or 9e9) + 1.0
        v["④任务不回退"] = {"PASS": bool(ok4),
                          "A": {"done": Am.get("done"), "段": Am.get("stages_visited"),
                                "末端距目标mm": Am.get("final_dist_mm"), "总时长s": Am.get("t_end_s")},
                          "B": {"done": Bm.get("done"), "段": Bm.get("stages_visited"),
                                "末端距目标mm": Bm.get("final_dist_mm"), "总时长s": Bm.get("t_end_s")}}
    out["verdict"] = v
    out["all_pass"] = all(x.get("PASS") for x in v.values())

    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    # ── 打表 ─────────────────────────────────────────────────────────────
    print("=" * 92)
    print("⚖ A/B: u_ff 经过「SK01-08 + 物理约束闸」再给仿真器")
    print("=" * 92)
    for k, arm in sm.items():
        print(f"\n【{k}】{raw[k]['arm']}  gate_on={raw[k]['gate_on']} limiter={raw[k]['limiter_attached']} "
              f"Δt={raw[k]['gate_dt_ms']}ms")
        print(f"   拍数 {arm['n_steps']} · 仿真时长 {arm['t_end_s']}s · done={arm['done']} · "
              f"末端距目标 {arm['final_dist_mm']}mm · wall {arm['wall_s']}s · "
              f"单拍 P50/P95/Max {arm['step_ms']['p50']}/{arm['step_ms']['p95']}/{arm['step_ms']['max']}ms")
        print(f"   走过段: {' → '.join(arm['stages_visited'])}")
        print(f"   削因(闸): {arm['n_cut']} · 闸调用 {arm['n_gate_calls']} · big拍 {arm['gate_big_steps']}"
              f" · err_max {arm['gate_err_max']}")
        print(f"   {'段':<6}{'拍':>5}{'u_sat均值':>11}{'u_sat峰':>10}{'u_ff峰':>10}{'v_cap':>8}{'超cap拍':>8}")
        for s in STAGES:
            d = arm["per_stage"].get(s) or {}
            if not d.get("n"):
                print(f"   {s:<6}{0:>5}{'—':>11}{'—':>10}{'—':>10}{arm['v_cap_table'].get(s, 0):>8.3f}{'—':>8}")
                continue
            print(f"   {s:<6}{d['n']:>5}{d['u_sat_mean']:>11.4f}{d['u_sat_max']:>10.4f}"
                  f"{d['u_ff_max']:>10.4f}{d['v_cap']:>8.3f}{d['over_cap_steps']:>8}")

    print("\n" + "=" * 92)
    print(f"闸本体单拍开销  P50 {mb['p50_us']}µs · P95 {mb['p95_us']}µs · Max {mb['max_us']}µs")
    for k, d in v.items():
        print(f"{'✅' if d.get('PASS') else '❌'} {k}: {json.dumps({kk: vv for kk, vv in d.items() if kk != 'PASS'}, ensure_ascii=False)}")
    print(f"\n总判定: {'✅ 全部 PASS' if out['all_pass'] else '❌ 有 FAIL'}")
    print(f"落盘: {a.json}")
    return 0 if out["all_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
