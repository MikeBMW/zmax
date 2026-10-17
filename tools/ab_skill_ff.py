#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 A/B: 「原子技能输出动作」能不能真驱动仿真 (ZMAX_SKILL_FF)

老倪 (2026-10-16): 「现在仿真，是通过原子任务输出的么? 这些原子任务都有输出么」
改动前: 仿真的 u_ff 只来自前馈加速器, 原子技能只提供阶段目标 (obs[36:39]) 与包络。
改动后: 技能类新增执行口 `command()` (u = k·(target−x), 限本段 v_cap, 到容差→0),
        ZMAX_SKILL_FF=1 时由它直接产出 u_ff, 加速器退为对照/探针。

四臂 (同一初值 · 确定性解析引擎):
  A 现状            : 加速器 u_ff, 无物理闸
  B 加速器 + 闸     : 加速器 u_ff, 过 SK 段包络+五条物理约束
  C 技能驱动 + 闸   : 技能 command 产出 u_ff, 再过闸 (本次要证明的通路)
  D 技能驱动 (无闸) : 只看技能 command 的裸表现

判据: ①走完 8 段且 done ②末端距目标不劣于 A +1mm ③段速度 ≤ v_cap ④单拍耗时 ≤ 10ms
用法:
  ./gui-venv311/bin/python tools/ab_skill_ff.py
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import statistics
import sys
import time

import numpy as np

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "src"))

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def _run(arm: str, gate: bool, skill_ff: bool, k: float = 6.0) -> dict:
    os.environ["ZMAX_L2_GATE"] = "1" if gate else "0"
    os.environ["ZMAX_SKILL_FF"] = "1" if skill_ff else "0"
    os.environ["ZMAX_SKILL_K"] = str(k)
    for _m in [m for m in list(sys.modules) if m.startswith("lerobot.engine.sim")]:
        del sys.modules[_m]
    import lerobot.engine.sim as simmod          # noqa: PLC0415
    importlib.reload(simmod) if hasattr(simmod, "__file__") and simmod.__name__ in sys.modules else None
    eng = simmod.StateSpaceSim(log=None)
    ticks = []

    def _hook(*_a, **_k):
        ticks.append(time.perf_counter())
    t0 = time.perf_counter()
    tr = eng.run(on_step=_hook)
    wall = time.perf_counter() - t0
    dt_ms = [(b - a) * 1000.0 for a, b in zip(ticks[:-1], ticks[1:])]
    _sc = getattr(eng, "skill_cmd", None)
    return {"arm": arm, "tr": tr, "wall": wall,
            "skill_ff_actual": bool(getattr(eng, "skill_ff", False)),
            "skill_cmd_err": (_sc or {}).get("err") if isinstance(_sc, dict) else None,
            "p50": statistics.median(dt_ms) if dt_ms else 0.0,
            "p95": float(np.percentile(dt_ms, 95)) if dt_ms else 0.0,
            "gate": gate, "skill_ff": skill_ff, "k": k,
            "n_cut": dict(getattr(getattr(eng, "lim", None), "n_cut", {}) or {}),
            "target_src_last": getattr(eng, "_target_src", ""),
            "skill_cmd": getattr(eng, "skill_cmd", None)}


def _summ(r: dict) -> dict:
    tr = r["tr"]
    st = [str(x).replace("阶段 ", "").split("·")[0].strip() for x in (tr.get("stage_u") or tr["stage"])]
    u = np.asarray(tr.get("u_sat", []), dtype=float)
    return {"拍": len(st), "走完": [s for s in STAGES if s in st],
            "done": bool(tr["done"][-1]), "末端距目标mm": round(float(tr["dist"][-1]) * 1000, 2),
            "u峰": round(float(u.max()), 4) if len(u) else 0.0,
            "u均值": round(float(u.mean()), 4) if len(u) else 0.0,
            "削因": r["n_cut"], "单拍P50/P95ms": (round(r["p50"], 3), round(r["p95"], 3)),
            "target_src": r["target_src_last"],
            "skill_ff实际": r.get("skill_ff_actual"),
            "技能口错误": r.get("skill_cmd_err")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(REPO, "zmax_data", "eval", "ab_skill_ff.json"))
    ap.add_argument("--ks", default="6")
    a = ap.parse_args()
    ks = [float(x) for x in a.ks.split(",") if x.strip()]

    arms = [("A 现状 (加速器)", False, False, 6.0),
            ("B 加速器+闸", True, False, 6.0)]
    for k in ks:
        arms.append((f"C 技能驱动+闸 k={k:g}", True, True, k))
    if len(ks) == 1:
        arms.append((f"D 技能驱动(无闸) k={ks[0]:g}", False, True, ks[0]))

    out = {"ts": time.time(), "rows": []}
    print(f"{'臂':<22}{'拍':>5}{'done':>7}{'末端mm':>9}{'u峰':>8}{'u均值':>8}  削因 / 单拍P50")
    base = None
    for name, gate, sff, k in arms:
        r = _run(name, gate, sff, k)
        s = _summ(r)
        if base is None:
            base = s
        out["rows"].append({"arm": name, **s, "gate": gate, "skill_ff": sff, "k": k})
        print(f"{name:<22}{s['拍']:>5}{str(s['done']):>7}{s['末端距目标mm']:>9}{s['u峰']:>8.4f}{s['u均值']:>8.4f}"
              f"  {s['削因']} / {s['单拍P50/P95ms'][0]}ms")
        if s.get("技能口错误"):
            print(f"   ⚠ 技能执行口报错(本臂 u_ff 退回加速器): {s['技能口错误']}")
            out.setdefault("arm_errors", {})[name] = s["技能口错误"]

    v = {}
    for row in out["rows"]:
        if "C" not in row["arm"]:
            continue
        ok1 = row["done"] and len(row["走完"]) >= len(base["走完"])
        ok2 = row["末端距目标mm"] <= base["末端距目标mm"] + 1.0
        ok3 = row["u峰"] <= max(0.35, 0.0) + 1e-6
        ok4 = row["单拍P50/P95ms"][1] <= 10.0
        v[row["arm"]] = {"①走完8段": ok1, "②末端不劣于现状": ok2, "③段速度≤cap": ok3, "④单拍≤10ms": ok4,
                         "全部PASS": all([ok1, ok2, ok3, ok4])}
    out["verdict"] = v
    out["all_pass"] = all(x["全部PASS"] for x in v.values()) if v else False
    os.makedirs(os.path.dirname(a.json), exist_ok=True)
    json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + "=" * 84)
    for k, d in v.items():
        print(f"{'✅' if d['全部PASS'] else '❌'} {k}: {json.dumps({x: y for x, y in d.items() if x != '全部PASS'}, ensure_ascii=False)}")
    print(f"落盘: {a.json}")
    return 0 if out["all_pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
