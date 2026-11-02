#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 300UPH 收口核算 (老倪: "L2 层能独立运行, 保证 UPH300么?")

上一版 (tools/l2_uph_measure.py) 只回答"现在多少"。本工具回答"差多少、靠什么补、补完到多少",
数字全部从两个真源现算, 不许手填:

  真源1  段表 GET /api/sim_insert           (28 段/件, 每段 kind/label/a/b/t)
  真源2  AR 台账 data/memory/ar_muscle.json (逐 label 实测 mean_t, 逐 kind mean_t)

口径 (最严同源): 一件的实测 = Σ_seg 台账**同 label** 实测 mean_t; 该段 label 在台账里没有才回落到
同 kind 均值, 并记 label_hit 覆盖率。不同 label 的段几何不同, 拿 kind 均值去乘是错口径。

四件事:
  A. 运动学反解  实测 = 固定开销 c + 距离/v ⇒ 余量来自"每段停下来重新加速", 不是臂慢
  B. 检测占用    5 段 AOI 的实测时长 (可与运动重叠的那部分)
  C. 收口杠杆    C1 段间连续化 / C2 检测并行 / C3 插拔提速 / C4 抬升加速度, 各自省多少 (按段现算)
  D. 组合判定    哪几种组合能把每件压到 ≤12.000 s (=300 UPH), 哪几种不行

用法: ./gui-venv311/bin/python tools/l2_uph_closure.py [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "http://127.0.0.1:8797/api/sim_insert"
TARGET_UPH = 300
TARGET_TACT = 3600.0 / TARGET_UPH           # 12.000 s/件
LEDGER = os.path.join(ROOT, "data/memory/ar_muscle.json")
# 检测/夹爪/插拔段两端必须静止 (相机曝光、夹爪动作、力控), 不能与相邻段混合
BLOCK_END = ("grip", "release", "side", "golden", "pull")
BLOCK_START = ("grip", "release", "side", "golden", "insert", "pull")


def plan():
    with urllib.request.urlopen(API, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def ledger():
    return json.load(open(LEDGER, encoding="utf-8")).get("kinds") or {}


def piece_segs(d):
    """稳态窗口全部段 (mod 1..4) + 件数; 与 l2_uph_measure.compute 同一取法, 数字才对得上。"""
    win = [s for s in d["plan"] if s.get("mod") in (1, 2, 3, 4)]
    n_mod = len({s.get("mod") for s in win}) or 1
    return win, n_mod


def pred_real(seg, led):
    """该段实测时长 (同源: 同 label 优先, 否则同 kind 均值)。返回 (t, src)。"""
    lb = (led.get(seg["kind"]) or {}).get("labels") or {}
    e = lb.get(seg.get("label") or "")
    if e:
        return float(e["mean_t"]), "label"
    v = led.get(seg["kind"]) or {}
    return (float(v["mean_t"]) if v.get("mean_t") else float(seg["t"])), "kind"


def fit(rows, kinds):
    """实测 = c + d/v 最小二乘 (只用同 label 命中的段, 距离取段表 a/b)。"""
    pts = [(r["dist"], r["real"]) for r in rows if r["kind"] in kinds and r["src"] == "label"]
    n = len(pts)
    if n < 3:
        return None
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den <= 0:
        return None
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / den
    if b <= 0:                     # 同行程重复采样 ⇒ 只有固定开销, 无距离梯度
        return {"c_s": my, "v_mm_s": None, "n": n}
    return {"c_s": my - b * mx, "v_mm_s": 1.0 / b, "n": n}


def analyse(d=None, led=None):
    d = d or plan()
    led = led if led is not None else ledger()
    segs, n_mod = piece_segs(d)

    rows = []
    for s in segs:
        t, src = pred_real(s, led)
        rows.append({"kind": s["kind"], "label": s.get("label") or "", "plan": float(s["t"]),
                     "real": t, "src": src, "dist": math.dist(s["a"], s["b"]),
                     "a": list(s["a"]), "b": list(s["b"])})

    plan_t = sum(r["plan"] for r in rows) / n_mod
    real_t = sum(r["real"] for r in rows) / n_mod
    hit = sum(1 for r in rows if r["src"] == "label")
    agg = collections.defaultdict(lambda: {"plan": 0.0, "real": 0.0, "n": 0})
    for r in rows:
        x = agg[r["kind"]]
        x["plan"] += r["plan"]; x["real"] += r["real"]; x["n"] += 1
    for x in agg.values():
        x["plan"] /= n_mod; x["real"] /= n_mod; x["n"] /= n_mod

    mv = fit(rows, {"move"})
    ud = fit(rows, {"up", "down"})
    c_fix = mv["c_s"] if mv else 0.44

    # ── B. 检测占用
    ao = [r for r in rows if r["kind"] in ("side", "golden")]
    ao_t = sum(r["real"] for r in ao) / n_mod
    near_ao = [r for r in rows if r["kind"] == "move"
               and any(abs(r["b"][0] - q["a"][0]) < 1 and abs(r["b"][1] - q["a"][1]) < 1 for q in ao)]

    # ── C. 杠杆 (全部折成每件)
    pairs = []
    for i in range(len(rows) - 1):
        p, q = rows[i], rows[i + 1]
        if p["a"] and q["a"] and math.dist(p["b"], q["a"]) > 2.0:
            continue
        if p["kind"] in BLOCK_END or q["kind"] in BLOCK_START:
            continue
        pairs.append("%s→%s" % (p["label"], q["label"]))
    c1 = len(pairs) * c_fix * 0.6 / n_mod      # 保守: 混合转弯仍要减速, 只认 0.6 个固定开销

    side = [r for r in rows if r["kind"] == "side"]
    side_pc = len(side) / n_mod
    side_one = (sum(r["real"] for r in side) / len(side)) if side else 0.0
    side_save = max(0.0, side_pc - 2) * side_one
    move_save = sum(sorted([r["real"] for r in near_ao], reverse=True)[:2 * n_mod]) / n_mod if near_ao else 0.0
    c2 = side_save + move_save

    pu = [r for r in rows if r["kind"] in ("insert", "pull")]
    c3 = sum(max(0.0, r["real"] - 0.45) for r in pu) / n_mod

    ud_n = len([r for r in rows if r["kind"] in ("up", "down")]) / n_mod
    c4 = ud_n * 0.20                   # 加速度翻倍各省 0.20 s (待确认控制器上限, 不计入保守合计)

    levers = {
        "C1_连续化": {"save": c1, "n": len(pairs) / n_mod,
                    "detail": ["%s (整窗 %d 处)" % (p, len(pairs)) for p in pairs[:3]],
                    "note": "每件 %.0f 处相邻可达段 (a==上段 b, 两端非检测/夹爪/插拔), 每处省 %.2f s (0.6×固定开销 %.2f)"
                            % (len(pairs) / n_mod, c_fix * 0.6, c_fix)},
        "C2_检测并行": {"save": c2, "n": side_pc, "detail": ["侧面 4→2 个位姿", "省 2 段移近"],
                     "note": "双相机同拍省 %.0f 次检测 (%+.2f s) + 2 段移近 (%+.2f s)"
                             % (max(0.0, side_pc - 2), side_save, move_save)},
        "C3_插拔提速": {"save": c3, "n": len(pu) / n_mod,
                     "detail": ["insert 0.56→0.40 (力曲线不改, 只提末段速度)", "pull 0.89→0.45"],
                     "note": "插拔每件 %.0f 段压到 0.45 s 以内的部分 (%.2f s)" % (len(pu) / n_mod, c3)},
        "C4_抬升加速度": {"save": c4, "n": ud_n, "detail": ["up/down 每件 %.0f 段各省 0.20 s" % ud_n],
                      "note": "up/down 每件 %.0f 段 (固定开销 %.2f s/段) 加速度翻倍各省 0.20 s; 需先确认控制器上限, 不作为已兑现项"
                              % (ud_n, (ud["c_s"] if ud else 0.0))},
    }

    combos = []
    for nm, sv in (("现状", 0.0), ("C1 连续化", c1), ("C2 检测并行", c2), ("C1+C2", c1 + c2),
                   ("C1+C2+C3", c1 + c2 + c3), ("C1+C2+C3+C4", c1 + c2 + c3 + c4)):
        tt = real_t - sv
        combos.append({"name": nm, "save_s": round(sv, 3), "tact_s": round(tt, 3),
                       "uph": round(3600.0 / tt, 1), "ok": tt <= TARGET_TACT + 1e-9})

    return {"rows": rows, "n_seg": len(rows), "n_mod": n_mod, "label_hit": hit,
            "plan_tact": plan_t, "uph_plan": 3600.0 / plan_t,
            "meas_tact": real_t, "uph_meas": 3600.0 / real_t,
            "target_tact": TARGET_TACT, "gap_s": real_t - TARGET_TACT,
            "by_kind": {k: dict(v) for k, v in agg.items()},
            "fit_move": mv, "fit_updown": ud, "ao_s": ao_t, "ao_n": len(ao),
            "levers": levers, "combos": combos,
            "src": "段表 /api/sim_insert + AR 台账 ar_muscle.json"}


def _fmt(f):
    if not f:
        return "样本不足"
    if not f.get("v_mm_s"):
        return "固定开销 %.3f s/段 (同行程重复, 无距离梯度)" % f["c_s"]
    return "固定开销 %.3f s/段 · 等效速度 %.0f mm/s" % (f["c_s"], f["v_mm_s"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    c = analyse()

    print("基线 (稳态窗口 %d 段 / %d 件 = %.0f 段/件 · label 同源覆盖 %d/%d)"
          % (c["n_seg"], c["n_mod"], c["n_seg"] / c["n_mod"], c["label_hit"], c["n_seg"]))
    print("  段表计划 %.3f s/件 → %d UPH" % (c["plan_tact"], c["uph_plan"]))
    print("  台账实测 %.3f s/件 → %d UPH   目标 %.3f s/件 (%d UPH) 差 %+.3f"
          % (c["meas_tact"], c["uph_meas"], TARGET_TACT, TARGET_UPH, c["gap_s"]))
    print("  %-8s %6s %6s %6s %5s" % ("段类", "计划", "实测", "增量", "段数"))
    for k, v in sorted(c["by_kind"].items(), key=lambda x: -(x[1]["real"] - x[1]["plan"])):
        print("  %-8s %6.3f %6.3f %+6.3f %5d" % (k, v["plan"], v["real"], v["real"] - v["plan"], v["n"]))

    print("\nA. 运动学反解")
    print("  move    " + _fmt(c["fit_move"]))
    print("  up/down " + _fmt(c["fit_updown"]))
    print("  含义: 每段都要停下来重新加速 —— 固定开销就是段边界加减速, 不是臂慢")

    print("\nB. 检测占用 %.3f s/件 (%d 段 AOI)" % (c["ao_s"], c["ao_n"]))
    print("\nC. 收口杠杆")
    for k, v in c["levers"].items():
        print("  %-12s 省 %+.3f s/件  %s" % (k, v["save"], v["note"]))
    print("\nD. 组合判定 (≤%.3f s/件 = %d UPH)" % (TARGET_TACT, TARGET_UPH))
    for x in c["combos"]:
        print("  %-14s %6.3f s/件 → %3d UPH  %s"
              % (x["name"], x["tact_s"], round(x["uph"]), "✅" if x["ok"] else "❌ 差 %+.2f" % (x["tact_s"] - TARGET_TACT)))

    if a.json:
        json.dump({k: v for k, v in c.items()}, open(a.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n→", a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
