#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 独立运行 + UPH 实测核算 (老倪: "L2 层能独立运行, 保证 UPH300 么?")

两项分开量, 不给一个含糊的"能":
  A. 独立运行  引擎 cap=l2 单跑 (无 L3 编排): 走完整件循环? 步数/快通道命中/用时
  B. UPH       节拍 = 段表逐段求和 / 4 件; 两个口径都算:
                计划口径   = 段表 t (按速度上限/加速度规划出来的)
                实测口径   = 段表 t × (AR 台账 mean_t / plan_t)  ← 现场真跑的段时长
               300 UPH 需要 ≤12.000 s/件; 差额按段类归因 (谁吃掉余量)

用法: ./gui-venv311/bin/python tools/l2_uph_measure.py [--seed 104] [--no-run] [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("MUJOCO_GL", os.environ.get("MUJOCO_GL", "egl"))
_CACHE = os.environ.get("STABLEWM_HOME", "/home/ubuntu/zmax/zmax_data/stable-wm-cache")
if os.path.isdir(_CACHE):
    os.environ.setdefault("STABLEWM_HOME", _CACHE)
    os.environ.setdefault("LOCAL_DATASET_DIR", _CACHE)

API = "http://127.0.0.1:8797/api/sim_insert"
TARGET_UPH = 300
TARGET_TACT = 3600.0 / TARGET_UPH          # 12.000 s/件


def plan_from_api():
    with urllib.request.urlopen(API, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def run_l2(seed):
    from state_space_sim_real import RealStateSpaceSim
    logs, stages = [], []
    sim = RealStateSpaceSim(seed=seed, vision=False, mode="insert", log=lambda s: logs.append(str(s)))
    sim._frame_sink = lambda s, a, o: stages.append(str(s.sched.stage()))
    tr = sim.run(max_steps=900, cap="l2")          # cap=l2: 只跑 L2, 无 L3 编排
    return {"done": bool(tr["done"][-1]) if tr.get("done") else False,
            "steps": len(tr.get("t") or []),
            "mm_hits": int(getattr(sim, "_mm_hits", 0) or 0),
            "stages": list(dict.fromkeys([s for s in stages if s])),
            "muscle_log": [l for l in logs if "肌肉记忆快通道" in l][:2]}



# ───────────────────────────────────────────────── 节拍核算 (页面/自检共用同一函数)
def compute(d=None, led=None):
    """段表 + 台账 → 每件节拍两口径 (计划 / 实测)。页面与自检都调这个, 不许各写一套。

    实测口径: 段表每段 t × (台账 mean_t ÷ 段表同类平均计划 t) —— 保留每段的几何差异,
    只把「这一类段实测比计划慢多少」乘回去。
    """
    d = d or plan_from_api()
    plan = d["plan"]
    if led is None:
        led = json.load(open(os.path.join(ROOT, "data/memory/ar_muscle.json"), encoding="utf-8"))["kinds"]
    win = [x for x in plan if x.get("mod") in (1, 2, 3, 4)]
    nmod = len({x.get("mod") for x in win}) or 1
    by = collections.defaultdict(lambda: {"t": 0.0, "n": 0})
    for x in win:
        a = by[x["kind"]]
        a["t"] += float(x["t"])
        a["n"] += 1
    ratio = {}
    for k, a in by.items():
        mean_plan = a["t"] / a["n"] if a["n"] else 0
        m = (led.get(k) or {}).get("mean_t")
        ratio[k] = (m / mean_plan) if (m and mean_plan) else 1.0
    tp = sum(a["t"] for a in by.values()) / nmod
    tm = sum(a["t"] * ratio[k] for k, a in by.items()) / nmod
    rows = []
    for k, a in by.items():
        rows.append({"kind": k, "plan_per_pc": a["t"] / nmod, "meas_per_pc": a["t"] * ratio[k] / nmod,
                     "delta": a["t"] * (ratio[k] - 1) / nmod, "segs_per_pc": a["n"] / nmod,
                     "n": (led.get(k) or {}).get("n"), "mean_t": (led.get(k) or {}).get("mean_t"),
                     "ratio": ratio[k]})
    rows.sort(key=lambda r: -r["delta"])
    return {"plan_tact": tp, "meas_tact": tm, "uph_plan": 3600.0 / tp, "uph_meas": 3600.0 / tm,
            "target_tact": TARGET_TACT, "gap": tm - TARGET_TACT, "rows": rows,
            "n_seg": len(win), "n_mod": nmod, "loop": d.get("loop") or {}, "ratio": ratio}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--no-run", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    out = {}
    if not a.no_run:
        r = run_l2(a.seed)
        out["l2_standalone"] = r
        need = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
        missing = [s for s in need if s not in r["stages"]]
        print("A. L2 独立运行 (cap=l2, seed %d): done=%s · %d 步 · 快通道 %d 帧"
              % (a.seed, r["done"], r["steps"], r["mm_hits"]))
        print("   阶段: %s" % " → ".join(r["stages"]))
        print("   判据: 走完整件七段 %s" % ("✅" if not missing else "❌ 缺 %s" % missing))
        out["l2_ok"] = bool(r["done"] and not missing)

    d = plan_from_api()
    plan, loop = d["plan"], d.get("loop") or {}
    led = json.load(open(os.path.join(ROOT, "data/memory/ar_muscle.json"), encoding="utf-8"))["kinds"]

    def ratio(k):
        m, p = (led.get(k) or {}).get("mean_t"), (led.get(k) or {}).get("plan_t")
        return (m / p) if (m and p) else 1.0

    win = [s for s in plan if s.get("mod") in (1, 2, 3, 4)]
    n_mod = len({s.get("mod") for s in win}) or 1
    tp = sum(float(s["t"]) for s in win)
    tm = sum(float(s["t"]) * ratio(s["kind"]) for s in win)
    tact_p, tact_m = tp / n_mod, tm / n_mod
    uph_p, uph_m = 3600.0 / tact_p, 3600.0 / tact_m

    agg = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for s in win:
        x = agg[s["kind"]]; x[0] += float(s["t"]) / n_mod; x[1] += float(s["t"]) * ratio(s["kind"]) / n_mod; x[2] += 1
    gaps = sorted(((k, v[1] - v[0]) for k, v in agg.items()), key=lambda x: -x[1])

    print("\nB. 节拍 / UPH (段表 %d 段 · 窗口 %d 件 · 每件 %d 段)" % (len(plan), n_mod, len(win) // n_mod))
    print("   计划口径: %.3f s/件 → %d UPH   (段表本身: %.3fs / %s 件, tact_s=%.3f)"
          % (tact_p, uph_p, loop.get("dur", 0), loop.get("mods", 0), loop.get("tact_s", 0)))
    print("   实测口径: %.3f s/件 → %d UPH   (AR 台账 mean_t 代回每段)"
          % (tact_m, uph_m))
    print("   目标 300 UPH ⇒ ≤ %.3f s/件 · 实测口径差 %+.3f s/件" % (TARGET_TACT, tact_m - TARGET_TACT))
    print("   余量归因 (每件增量, 谁吃掉的):")
    for k, g in gaps[:5]:
        print("      %-8s %+.3f s   (计划 %.2f → 实测 %.2f, %d 段/件)"
              % (k, g, agg[k][0], agg[k][1], agg[k][2] // n_mod))
    out.update({"tact_plan": round(tact_p, 4), "uph_plan": round(uph_p, 1),
                "tact_measured": round(tact_m, 4), "uph_measured": round(uph_m, 1),
                "target_tact": TARGET_TACT, "gap_s_per_pc": round(tact_m - TARGET_TACT, 4),
                "attribution": [{"kind": k, "delta_s": round(g, 3)} for k, g in gaps],
                "uph300_plan": bool(uph_p >= TARGET_UPH), "uph300_measured": bool(uph_m >= TARGET_UPH)})
    print("\n结论: 独立运行 %s · 计划口径 300UPH %s · 实测口径 300UPH %s"
          % ("✅" if out.get("l2_ok", True) else "❌",
             "✅" if out["uph300_plan"] else "❌", "✅" if out["uph300_measured"] else "❌"))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("→", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
