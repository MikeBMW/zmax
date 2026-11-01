#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐动作对比: 固定轨迹(fixed_cycle.json) ⇄ 全流程UPH段表(/api/sim_insert) ⇄ 链生成器(cycle_plan)

老倪 2026-11-01: 「按照原来的 全流程UPH的动作，你每个动作都做个对比，保证动作与固定轨迹一致」

三份东西:
  A 全流程 UPH = GET /api/sim_insert 的稳态窗口 (loop.ks) 段表 —— 页面上"全流程"播的就是它
  F 固定轨迹   = zmax_data/ss_live/fixed_cycle.json (n_moveit 理想档, 只把每段时长按理想剖面重算)
  B 链生成器   = middleware/nodes/cycle_plan.build() —— 状态空间执行器真正跑的 392 段

判据:
  ① F 与 A **逐段逐字**一致 (kind + a + b), 112/112
  ② A ⊂ B (A 的每个点都能在 B 里找到, 容差 0.5mm) —— 同一生成器, 固定轨迹不是另造一套
  ③ 每段只差时间: 几何一致、t 可能不同 (理想档重计时) —— 逐段列出 Δt
用法: ./gui-venv311/bin/python tools/compare_fixed_cycle_vs_fullflow.py [--json out.json] [--rows]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request

ROOT = "/home/ubuntu/zmax"
API = "http://127.0.0.1:8797/api/sim_insert"
FC = ROOT + "/zmax_data/ss_live/fixed_cycle.json"
TOL = 0.5          # mm


def load_A():
    d = json.load(urllib.request.urlopen(API, timeout=8))
    P, L = d["plan"], d["loop"]
    ks = L["ks"]
    i0 = next(i for i, s in enumerate(P) if s["k"] == ks[0])
    i1 = max(i for i, s in enumerate(P) if s["k"] == ks[1])
    return P[i0:i1 + 1], d


def load_F():
    return json.load(open(FC, encoding="utf-8"))


def load_B():
    sys.path[:0] = [ROOT, ROOT + "/src"]
    from lerobot.engineering.nodes import cycle_plan as CP      # noqa: PLC0415
    b = CP.build()
    return b.get("plan") or b.get("segments") or []


def key(s):
    return (s.get("kind") or s.get("k"),
            tuple(round(float(x), 1) for x in s["a"]),
            tuple(round(float(x), 1) for x in s["b"]))


def near(p, pts):
    return any(math.dist(p, q) <= TOL for q in pts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--rows", action="store_true", help="打印全部 112 段明细")
    a = ap.parse_args()

    A, raw = load_A()
    F = load_F()
    B = load_B()
    frows = F["rows"]

    print("=== 三份来源 ===")
    print("  A 全流程UPH 段表窗口 : %d 段 (cfg_sha %s, loop.ks=%s)" %
          (len(A), raw.get("cfg_sha"), raw["loop"]["ks"]))
    print("  F 固定轨迹 fixed_cycle: %d 段 · 循环 %.2fs · 节拍 %.3fs · %.1f UPH" %
          (len(frows), F["cycle_s"], F["tact_s"], F["uph"]))
    print("  B 链生成器 cycle_plan : %d 段 · 合计 %.2fs" %
          (len(B), sum(float(s.get("t") or 0) for s in B)))

    # ① 逐段逐字
    n = min(len(A), len(frows))
    same = 0
    diffs = []
    for i in range(n):
        sa, sf = A[i], frows[i]
        ok = (sa["kind"] == sf["kind"] and
              [round(float(x), 1) for x in sa["a"]] == [round(float(x), 1) for x in sf["a"]] and
              [round(float(x), 1) for x in sa["b"]] == [round(float(x), 1) for x in sf["b"]])
        if ok:
            same += 1
        else:
            diffs.append((i + 1, sa["kind"], sf["kind"], sa["a"], sf["a"], sa["b"], sf["b"]))
    print("\n① 固定轨迹 ⇄ 全流程: 逐段一致 %d/%d %s" % (same, n, "✓" if same == n == len(frows) else "✗"))
    for d in diffs[:5]:
        print("   段%d %s vs %s  a=%s/%s b=%s/%s" % d)

    # ② A ⊂ B
    BP = set()
    for s in B:
        BP.add(tuple(round(float(x), 1) for x in s["a"]))
        BP.add(tuple(round(float(x), 1) for x in s["b"]))
    missed = []
    for s in A:
        for f in ("a", "b"):
            p = tuple(round(float(x), 1) for x in s[f])
            if not near(p, BP):
                missed.append((s["kind"], s.get("label"), p))
    print("② 全流程的点是否都在链生成器里: 缺 %d 个 %s" % (len(missed), "✓" if not missed else "✗"))
    for m in missed[:6]:
        print("   ", m)

    # ③ 逐动作 Δt
    tot_old = sum(float(s["t"]) for s in A)
    tot_new = sum(float(r["t"]) for r in frows)
    rows = []
    for i, (sa, sf) in enumerate(zip(A, frows), start=1):
        rows.append(dict(i=i, kind=sa["kind"], label=sa.get("label"),
                         a=sa["a"], b=sa["b"],
                         len_mm=round(math.dist(sa["a"], sa["b"]), 1),
                         t_fullflow=round(float(sa["t"]), 3),
                         t_fixed=round(float(sf["t"]), 3),
                         dt=round(float(sf["t"]) - float(sa["t"]), 3)))
    rows.sort(key=lambda r: r["t_fullflow"] - r["t_fixed"])
    print("\n③ 只差时间: 全流程合计 %.2fs → 固定轨迹 %.2fs (省 %.2fs)" %
          (tot_old, tot_new, tot_old - tot_new))
    print("   压得最多的 8 个动作 (原 → 理想):")
    for r in rows[:8]:
        print("   #%-3d %-26s %6.1fmm  %6.2f → %5.2f s (%+.2f)" %
              (r["i"], (r["label"] or r["kind"])[:26], r["len_mm"],
               r["t_fullflow"], r["t_fixed"], r["dt"]))
    print("   反而变长的 5 个动作:")
    for r in rows[-5:]:
        print("   #%-3d %-26s %6.1fmm  %6.2f → %5.2f s (%+.2f)" %
              (r["i"], (r["label"] or r["kind"])[:26], r["len_mm"],
               r["t_fullflow"], r["t_fixed"], r["dt"]))
    if a.rows:
        print("\n--- 全部 %d 段 ---" % len(rows))
        for r in sorted(rows, key=lambda x: x["i"]):
            print("  #%-3d %-9s %-26s a=%s b=%s %6.1fmm  t %5.2f → %5.2f" %
                  (r["i"], r["kind"], (r["label"] or "")[:26], r["a"], r["b"],
                   r["len_mm"], r["t_fullflow"], r["t_fixed"]))

    verdict = (same == n == len(frows)) and not missed
    print("\n结论: %s —— 固定轨迹与全流程UPH 的动作(kind/起点/终点)逐段完全一致, 差异只在每段时长。" %
          ("一致 ✓" if verdict else "不一致 ✗"))
    if a.json:
        json.dump(dict(ok=verdict, a_seg=len(A), f_seg=len(frows), b_seg=len(B),
                       same_seg=same, missing_in_chain=len(missed),
                       t_fullflow_s=round(tot_old, 3), t_fixed_s=round(tot_new, 3),
                       tact_fullflow_s=round(tot_old / raw["loop"]["mods"], 3),
                       tact_fixed_s=round(tot_new / raw["loop"]["mods"], 3),
                       rows=sorted(rows, key=lambda x: x["i"])),
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("明细已写 %s" % a.json)
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
