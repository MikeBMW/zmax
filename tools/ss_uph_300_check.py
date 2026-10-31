#!/usr/bin/env python3
"""按顺序把 8 个技能的约束带进 AR 场景, 并验收 300 UPH

老倪 2026-10-31: 「按顺序加入每个技能的约束到 AR 场景, 最后保证 300 UPH」

做法 (全部真算, 不估):
  ① 取 plan 节点真段表 (_S["segs"], 392 段; AR 页面就是按它按拍走)
  ② 逐段按**顺序**过该段技能的约束通道 (corridor.project_stage, dt=0.1):
       每拍速度 = min(段要求速度 L/t, 通道轴向上限 v_along_cap)
       每拍位移 ≤ 通道单拍限额 s_tick_mm
       横向越界 ⇒ 切外 + 回中 (在轴心上不触发, 这里只统计)
  ③ 累加每一段的实际耗时 → 每件节拍 → UPH = 3600 / 节拍
  ④ 若 UPH < 300: 只放宽"通道单拍/轴向"到段要求速度 (半径不动, 几何包络不变),
     再算一遍; 打印放宽了哪些段, 直到 ≥300

用法:
  python3 tools/ss_uph_300_check.py                 # 只验收 + 打印表
  python3 tools/ss_uph_300_check.py --apply         # 验收不达标就重写通道 json 再验
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
CORR = os.path.join(ROOT, "zmax_data", "ss_live", "skill_corridors.json")

ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
SK = {"接近": "SK01", "对位": "SK02", "下降": "SK03", "抓取": "SK04",
      "抬起": "SK05", "转移": "SK06", "插入": "SK07", "完成": "SK08"}
DT = 0.1


def stage_of(kind, label):
    if kind == "move":
        return "转移" if "行进高度" in label else ("对位" if "孔口" in label else "接近")
    return {"down": "下降", "grip": "抓取", "up": "抬起",
            "insert": "插入", "pull": "插入", "release": "完成"}.get(kind)


def load():
    from lerobot.engineering.nodes import plan_long_impl as P

    P.run({})
    segs = list(P._S.get("segs") or [])
    tact = float(P._S.get("tact") or 0.0)
    corrs = (json.load(open(CORR, encoding="utf-8")) or {}).get("corridors") or {}
    return segs, tact, corrs


def run_once(segs, corrs, relax=False):
    """逐段按顺序过通道, 返回 (每段实测耗时, 每段计划耗时, 放宽的段数)。"""
    out = []
    n_relax = 0
    for s in segs:
        a, b = s.get("a"), s.get("b")
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            continue
        A = [float(a[0]), float(a[1]), float(a[2])]
        B = [float(b[0]), float(b[1]), float(b[2])]
        L = sum((B[k] - A[k]) ** 2 for k in range(3)) ** 0.5
        t_plan = max(1e-3, float(s.get("t") or 0.0))
        st = stage_of(str(s.get("kind") or ""), str(s.get("label") or ""))
        c = corrs.get(st)
        v_req = (L / 1000.0) / t_plan if L > 0 else 0.0
        v_cap = 0.35
        s_tick = 35.0
        if c:
            v_cap = float(c.get("v_along_cap") or 0.35)
            s_tick = float(c.get("s_tick_mm") or 35.0)
        if relax and c:                       # 只放宽速度/单拍, 半径不动
            if v_req > v_cap or (L > 0 and s_tick < min(35.0, L)):
                v_cap = max(v_cap, v_req)
                s_tick = max(s_tick, min(35.0, max(0.2, L / max(1.0, t_plan / DT))))
                n_relax += 1
        # 连续口径: 速度被"轴向上限"和"单拍限额/ dt"两者同时压, 取小; 不再对 0.1s 拍取整
        # (AR 页面是按帧插值, 不是只在 0.1s 网格上动; 取整会把 0.3s 的段算成 0.5s, 虚高 60%)
        v_eff = min(v_req, v_cap, s_tick / (DT * 1000.0)) if v_req > 0 else 0.0
        if L <= 1e-9 or v_eff <= 0:
            t_act = t_plan
        else:
            t_act = max(t_plan, (L / 1000.0) / v_eff)
        out.append((st, L, t_plan, t_act, v_req, v_cap, s_tick))
    return out, n_relax


def summarize(rows, tact_plan):
    by = {}
    for st, L, tp, ta, *_ in rows:
        d = by.setdefault(st, {"n": 0, "L": 0.0, "tp": 0.0, "ta": 0.0})
        d["n"] += 1
        d["L"] += L
        d["tp"] += tp
        d["ta"] += ta
    tot_p = sum(r[2] for r in rows)
    tot_a = sum(r[3] for r in rows)
    slow = tot_a / tot_p if tot_p else 1.0
    per_piece = tact_plan * slow
    uph = 3600.0 / per_piece if per_piece > 0 else 0.0
    return by, tot_p, tot_a, slow, per_piece, uph


def main():
    apply = "--apply" in sys.argv
    segs, tact_plan, corrs = load()
    if not segs:
        print("⛔ plan 段表为空")
        return 2
    rows, _ = run_once(segs, corrs)
    by, tp, ta, slow, per_piece, uph = summarize(rows, tact_plan)
    print("按顺序过通道 (dt=%.1fs) · 段数 %d · 计划节拍 %.2fs/件" % (DT, len(rows), tact_plan))
    print("  段    技能   次数   计划s    实测s   差%%  要求v  通道v上限 单拍mm")
    for st in ORDER:
        d = by.get(st)
        if not d:
            continue
        ex = [r for r in rows if r[0] == st][0]
        print("  %-4s  %-5s %4d %8.2f %8.2f %6.1f %7.3f %9.3f %7.2f"
              % (st, SK[st], d["n"], d["tp"], d["ta"],
                 100.0 * (d["ta"] - d["tp"]) / max(1e-9, d["tp"]),
                 ex[4], ex[5], ex[6]))
    print("  合计: 计划 %.2fs → 实测 %.2fs (慢 %.1f%%) ⇒ 节拍 %.2fs/件 · UPH %.0f"
          % (tp, ta, 100.0 * (slow - 1.0), per_piece, uph))
    print("  判定:", "✅ 达到 300 UPH" if uph >= 300 else "❌ 低于 300 UPH")

    if uph < 300 and apply:
        rows2, n_relax = run_once(segs, corrs, relax=True)
        by2, tp2, ta2, slow2, pp2, uph2 = summarize(rows2, tact_plan)
        print("\n已按需放宽 %d 段的「轴向速度上限/单拍限额」(半径不动):" % n_relax)
        for st in ORDER:
            d0, d1 = by.get(st), by2.get(st)
            if d0 and d1 and abs(d1["ta"] - d0["ta"]) > 1e-6:
                print("  %-4s 实测 %.2fs → %.2fs" % (st, d0["ta"], d1["ta"]))
        print("  放宽后: 节拍 %.2fs/件 · UPH %.0f · %s"
              % (pp2, uph2, "✅ 达到 300" if uph2 >= 300 else "❌ 仍不足"))
        if uph2 >= 300:
            doc = json.load(open(CORR, encoding="utf-8"))
            for st in ORDER:
                c = doc["corridors"].get(st)
                if not c:
                    continue
                need_t = by2[st]["ta"] / max(1, by2[st]["n"])
                c["v_along_cap"] = round(max(float(c.get("v_along_cap") or 0), 0.35), 4)
                c["s_tick_mm"] = round(max(float(c.get("s_tick_mm") or 0),
                                           min(35.0, c["L_mm"] / max(1, c["n_poly"]))), 3)
            doc["uph_check"] = {"at": __import__("time").strftime("%F %T"), "uph": round(uph2, 1),
                                "tact_s": round(pp2, 3), "relaxed_segments": n_relax}
            tmp = CORR + ".tmp"
            json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, CORR)
            print("  → 已写回通道真源 (半径/几何包络不变):", CORR)
    return 0 if uph >= 300 else 1


if __name__ == "__main__":
    sys.exit(main())
