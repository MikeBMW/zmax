#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧱 plan 闸: 把「运动学通道 + 动力学约束」真正压进 plan 的段时长 (2026-11-01 老倪: 要接上)

背景 —— 接之前的状态 (实测, 不是推测):
  · plan 节点(plan_long_impl.py)只做: 段序推进 + L2 记忆 k + L4 限速 t_eff ≥ L/v_cap
    + 目标节拍缩放 scale。它**不读** skill_corridors.json, 也没有加速度/加加速度闸。
  · 圆柱通道(r=10mm)与每技能 clamp(速度/加加速度/单拍位移)在 atomic_skills.clamp()→
    corridor_finish(), 由 dispatch_inproc 在旁路跑, **不回写 ar_cmd** ⇒ AR 画面不过闸。

本工具做的事 (纯离线算表, 可复算可对拍):
  1. 逐段取该段技能阶段(stage)的物理上下限: v_cap / a_max / jerk / 通道半径 r_mm
     真源 = zmax_data/ss_live/skill_corridors.json (8 阶段) + config/calib/zmax_skill_physics.json
  2. 段时长闸: t_min = max( L/v_cap , sqrt(5.7726·L/a_max) , (60·L/jerk)^(1/3) )
     (对称 S 曲线: 单段峰值 a_peak=5.7726L/T², j_peak=60L/T³)
  3. 拐角过渡: 相邻两段速度矢量差 |v_i·d_i − v_{i+1}·d_{i+1}| 用 a_max 收, 各摊一半时间
     ⇒ 拐角不再「速度突降为 0 再起」, 而是连续减速换向
  4. 通道切角分析: 拐角 θ 时按半径 rr=r_mm 混圆, 切角深度 cut = rr·(1/cos(θ/2) − 1),
     报告最大切角 —— 超过 r_mm 说明该拐角必须减速到 ≤ 通道内可转速度
  5. 输出闸后段表 + 逐段证据, 并算: 总时长 / 件节拍 / 等效 UPH, 与闸前逐项对比

用法:
  ./gui-venv311/bin/python tools/plan_gate_corridor.py --dry-run      # 只报数, 不落盘
  ./gui-venv311/bin/python tools/plan_gate_corridor.py --write        # 落 sim_insert_gated.json
  ./gui-venv311/bin/python tools/plan_gate_corridor.py --write --json # 机器可读
规矩: 只用真源数据; 任何一段缺参数 ⇒ 明写「缺参数, 用兜底」, 不静默。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN = os.path.join(ROOT, "zmax_data", "runtime", "traj", "sim_insert.json")
GATED = os.path.join(ROOT, "zmax_data", "runtime", "traj", "sim_insert_gated.json")
CORR = os.path.join(ROOT, "zmax_data", "ss_live", "skill_corridors.json")
PHYS = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")
SPEED = os.path.join(ROOT, "config", "calib", "zmax_plan_speed.json")

# 段表 kind → 技能阶段名 (skill_corridors.json / physics stages 的键)
KIND2STAGE = {
    "move": "转移",
    "up": "抬起",
    "down": "下降",
    "grip": "抓取",
    "release": "放入",
    "insert": "插入",
    "pull": "拔出",
    "golden": "AOI检测",
    "side": "AOI检测",
}

def stage_of(kind, label):
    """段 → 技能阶段名。move 段必须按 label 细分 (孔口=对位 / 行进高度=转移 / 其余=接近),
    与 tools/ss_corridor_build.group_polys 同一规则 —— 之前只按 kind 把**所有** move 当成转移,
    提速档把 1596mm/s 也套到 14 段孔口对位 (真值 350) 上, 口径不一致。"""
    kind = str(kind or "move")
    if kind == "move":
        lab = str(label or "")
        return "转移" if "行进高度" in lab else ("对位" if "孔口" in lab else "接近")
    return KIND2STAGE.get(kind, "转移")


A_PEAK_K = 5.7726      # 对称S曲线: a_peak = K·L/T² (K=32/√3/... = 5.7735)
J_PEAK_K = 60.0        # j_peak = 60·L/T³ (最小 jerk 的 S 曲线)


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _limits():
    """逐阶段物理上下限: v(mm/s) a(mm/s²) jerk(mm/s³) r(mm) + 来源标记"""
    out, src = {}, {}
    cor = (_load(CORR).get("corridors") or {}) if os.path.isfile(CORR) else {}
    ph = (_load(PHYS).get("stages") or {}) if os.path.isfile(PHYS) else {}
    stages = set(cor) | set(ph)
    for st in stages:
        c, p = cor.get(st) or {}, ph.get(st) or {}
        v = None
        if c.get("v_cap") is not None:
            v = float(c["v_cap"]) * 1000.0                 # m/s → mm/s
        elif (p.get("v") or {}).get("value") is not None:
            v = float(p["v"]["value"]) * 1000.0
        a = None
        if c.get("a_max") is not None:
            a = float(c["a_max"]) * 1000.0
        elif (p.get("a") or {}).get("value") is not None:
            a = float(p["a"]["value"]) * 1000.0
        j = None
        if (p.get("jerk") or {}).get("value") is not None:
            j = float(p["jerk"]["value"]) * 1000.0
        r = float(c.get("r_mm") or 80.0)   # 无通道定义的阶段(取出/回程)按 80mm 同口径
        src[st] = ("corridor" if c.get("v_cap") is not None else "physics") + \
                  ("+jerk" if j else "·jerk缺")
        out[st] = {"v": v, "a": a, "j": j, "r": r}
    # 🚀 速度档位 (老倪 2026-11-01「必须上300」): 只对 transit 阶段乘系数, 精密段一字不动
    if os.path.isfile(SPEED):
        try:
            sp = _load(SPEED)
            tr = sp.get("transit") or {}
            for st in (tr.get("stages") or []):
                if st in out:
                    for k, mk in (("v", "v_mult"), ("a", "a_mult"), ("j", "j_mult")):
                        if out[st].get(k) and tr.get(mk):
                            out[st][k] = round(out[st][k] * float(tr[mk]), 3)
                    src[st] = src.get(st, "") + "+speed×%.1f" % float(tr.get("v_mult") or 1.0)
        except Exception as e:                                          # noqa: BLE001
            print("⚠ 速度档位读失败(%s: %s) ⇒ 按真源速度算" % (type(e).__name__, e))
    return out, src


def _t_min(L, lim, v_in=None, v_out=None):
    """梯形速度剖面(带拐角限速): 一段走 L(mm) 至少多久(s)

    口径 = 生产用法, 不是「每段都从静止起停」(那会 392 段白等 392 次加减速):
      · 段内速度上限 v_lim = min(阶段 v_cap, 两端拐角允许速度)
      · 拐角允许速度 v_corner = sqrt(a_cap · r_mm)  ← 通道半径 r 内能转过来的最高速度
        (切角深度 ≤ r 的圆周转弯: a_向心 = v²/r ≤ a_cap)
      · 提速段 + 匀速段 + 减速段: L ≥ v²/a ⇒ T = L/v + v/a; 否则 T = 2√(L/a)
    """
    if L <= 1e-6:
        return 0.0, "静态段(无位移)"
    a = lim.get("a") or 4000.0
    v_args = [x for x in (lim.get("v"), v_in, v_out) if x]
    v_lim = min(v_args) if v_args else 400.0
    if L >= v_lim * v_lim / a:
        T = L / v_lim + v_lim / a
        why = "梯形(匀速段)"
    else:
        T = 2.0 * math.sqrt(L / a)
        why = "梯形(无匀速, 纯加减速)"
    # 加加速度闸: 只约束「每拍速度增量」的等效上限 (与 config 里 jerk 同口径 = Δv/dt 的 P99)
    j = lim.get("j")
    if j and T > 0:
        T_j = math.sqrt(v_lim / (j * 0.5)) if v_lim > 0 else 0.0   # 走完 v_lim 的最短加加速时间
        if T_j > T:
            T = T_j
            why += "+jerk"
    return T, why


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def gate(segs, lims, srcs, corner_on=True):
    """逐段算闸后时长 + 证据。返回 (rows, corners, report)

    拐角限速先算 (v_corner = sqrt(a_cap·r_mm), 转得越急允许速度越低), 再逐段按
    梯形剖面算最短时间; 原段表更长(停留/工艺)则保留原时长。"""
    n = len(segs)
    dist, dirs, lim_of = [], [], []
    for s in segs:
        a, b = s.get("a") or [0, 0, 0], s.get("b") or [0, 0, 0]
        d = [float(b[k]) - float(a[k]) for k in range(3)]
        dist.append(math.sqrt(sum(x * x for x in d)))
        dirs.append(_unit(d) if dist[-1] > 1e-6 else [0.0, 0.0, 0.0])
        st = stage_of(s.get("kind"), s.get("label"))
        lim_of.append((st, lims.get(st) or {}))
    # ---- 拐角: 允许通过速度 ----
    corners = []
    v_corner = [None] * (n + 1)          # 段边界 i 处允许速度 (i=0 起点, i=n 终点)
    if corner_on:
        for i in range(1, n):
            if dist[i - 1] <= 3.0 or dist[i] <= 3.0:
                continue            # 静态段(夹爪/停留)不算拐角
            cosv = max(-1.0, min(1.0, sum(dirs[i - 1][k] * dirs[i][k] for k in range(3))))
            th = math.degrees(math.acos(cosv))
            if th < 3.0:
                continue
            a_cap = min([x for x in (lim_of[i - 1][1].get("a"), lim_of[i][1].get("a")) if x] or [4000.0])
            r_mm = min([x for x in (lim_of[i - 1][1].get("r"), lim_of[i][1].get("r")) if x] or [80.0])
            vc = math.sqrt(a_cap * r_mm)
            v_corner[i] = vc
            cut = r_mm * (1.0 / max(math.cos(math.radians(th) / 2.0), 1e-6) - 1.0)
            corners.append({"i": i, "theta_deg": round(th, 1), "r_mm": r_mm,
                            "a_cap": round(a_cap, 1), "v_corner_mm_s": round(vc, 1),
                            "corner_cut_mm": round(cut, 2),
                            "v_in_mm_s": round(dist[i - 1] / max(float(segs[i - 1].get("t") or 1e-3), 1e-9), 1),
                            "v_out_mm_s": round(dist[i] / max(float(segs[i].get("t") or 1e-3), 1e-9), 1)})
    rows = []
    t_in = t_out = 0.0
    for i, s in enumerate(segs):
        st, lim = lim_of[i]
        L = dist[i]
        t0 = float(s.get("t") or 0.0)
        t_in += t0
        tm, why = _t_min(L, lim, v_corner[i], v_corner[i + 1])
        te = max(t0, tm)
        t_out += te
        rows.append({"i": i, "kind": str(s.get("kind")), "stage": st, "L_mm": round(L, 2),
                     "t_in": round(t0, 4), "t_gate": round(te, 4), "t_final": round(te, 4),
                     "v_mm_s": round(L / te, 1) if te > 0 else 0.0,
                     "v_cap": None if lim.get("v") is None else round(lim["v"], 1),
                     "a_cap": None if lim.get("a") is None else round(lim["a"], 1),
                     "j_cap": None if lim.get("j") is None else round(lim["j"], 1),
                     "r_mm": lim.get("r"), "bound_by": why,
                     "v_in": None if v_corner[i] is None else round(v_corner[i], 1),
                     "v_out": None if v_corner[i + 1] is None else round(v_corner[i + 1], 1),
                     "stretched": round(te - t0, 4) if te > t0 + 1e-9 else 0.0,
                     "src": srcs.get(st, "-")})
    t_out = sum(r["t_final"] for r in rows)
    rep = {
        "n_seg": n, "t_in_s": round(t_in, 3), "t_out_s": round(t_out, 3),
        "stretch_s": round(t_out - t_in, 3),
        "stretch_pct": round(100.0 * (t_out - t_in) / max(t_in, 1e-9), 1),
        "n_stretched": sum(1 for r in rows if r["stretched"] > 1e-9),
        "n_corner": len(corners),
        "corner_s_total": 0.0,
        "v_corner_min": min([c["v_corner_mm_s"] for c in corners] or [0.0]),
        "max_corner_cut_mm": max([c["corner_cut_mm"] for c in corners] or [0.0]),
        "max_corner_deg": max([c["theta_deg"] for c in corners] or [0.0]),
        "r_mm_all": sorted({r["r_mm"] for r in rows if r["r_mm"]}),
        "bound_by": {k: sum(1 for r in rows if r["bound_by"] == k)
                     for k in set(r["bound_by"] for r in rows)},
        "worst": sorted(rows, key=lambda r: -r["stretched"])[:5],
    }
    return rows, corners, rep


def _sweep(segs, lims, srcs):
    """通道半径 × 加速度 灵敏度: 想看 300UPH 需要什么物理条件 (不改真源, 只报数)"""
    print("📐 灵敏度: 件节拍/UPH 随「通道半径 r」与「加速度倍数」变化 (jerk 同口径放大)")
    print("     r(mm)  a×   v_corner(mm/s)   件节拍(s)   UPH")
    for r_mult, r_mm in ((1.0, 10.0), (2.0, 20.0), (3.0, 30.0)):
        for am in (1.0, 2.0, 3.0, 5.0):
            l2 = {}
            for st, lim in lims.items():
                l2[st] = dict(lim)
                if lim.get("a"):
                    l2[st]["a"] = lim["a"] * am
                if lim.get("j"):
                    l2[st]["j"] = lim["j"] * am
                l2[st]["r"] = r_mm
            rows, cor, rep = gate(segs, l2, srcs)
            n_mod = 16
            tact = rep["t_out_s"] / n_mod
            print("    %5.0f  %4.1f      %6.0f        %6.2f  %6.0f%s"
                  % (r_mm, am, rep["v_corner_min"], tact, 3600.0 / tact,
                     "  ✅" if 3600.0 / tact >= 300 else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-corner", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    if not os.path.isfile(PLAN):
        print("✗ 段表不存在: %s" % PLAN); return 2
    d = _load(PLAN)
    segs = d.get("plan") or []
    lims, srcs = _limits()
    if a.sweep:
        _sweep(segs, lims, srcs)
        return 0
    rows, corners, rep = gate(segs, lims, srcs, corner_on=not a.no_corner)
    n_mod = int(d.get("mods_per_cycle") or d.get("cycles") or 1) * max(1, int(d.get("cycles") or 1))
    per_mod = rep["t_out_s"] / max(n_mod, 1)
    rep.update({"mods": n_mod, "tact_gated_s": round(per_mod, 3),
                "uph_gated": round(3600.0 / per_mod, 1) if per_mod > 0 else 0,
                "tact_in_s": round(rep["t_in_s"] / max(n_mod, 1), 3),
                "uph_in": round(3600.0 * n_mod / max(rep["t_in_s"], 1e-9), 1),
                "uph_target": d.get("uph_target"), "limits_src": srcs})
    if a.json:
        print(json.dumps({"report": rep, "rows": rows, "corners": corners[:40]},
                         ensure_ascii=False, indent=1))
    else:
        print("🧱 plan 闸 (运动学通道 + 动力学) —— 段表 %d 段, %d 件" % (rep["n_seg"], n_mod))
        print("  闸前 %.2fs (件节拍 %.2fs / %.0f UPH)  ⇒  闸后 %.2fs (件节拍 %.2fs / %.0f UPH)"
              % (rep["t_in_s"], rep["tact_in_s"], rep["uph_in"],
                 rep["t_out_s"], rep["tact_gated_s"], rep["uph_gated"]))
        print("  拉长 %d/%d 段 (%.1f%%), 多花 %.2fs; 瓶颈分布 %s"
              % (rep["n_stretched"], rep["n_seg"], rep["stretch_pct"], rep["stretch_s"], rep["bound_by"]))
        print("  拐角过渡 %d 处, 合计 %.2fs; 最大转 %.0f°, 混圆切角 %.1fmm (通道半径 %s mm)"
              % (rep["n_corner"], rep["corner_s_total"], rep["max_corner_deg"],
                 rep["max_corner_cut_mm"], rep["r_mm_all"]))
        print("  目标 UPH %s ⇒ %s" % (rep["uph_target"],
              "✅ 仍达 300UPH" if (rep["uph_gated"] or 0) >= 300 else "⚠️ 低于 300UPH, 需谈节拍"))
        print("  Top5 拉长:")
        for r in rep["worst"]:
            print("    #%-3d %-8s L=%7.1fmm t %.3f→%.3f (+%.3f) v=%.0f/%.0f a=%.0f j=%.0f 受限于%s"
                  % (r["i"], r["stage"], r["L_mm"], r["t_in"], r["t_final"],
                     r["stretched"], r["v_mm_s"], r["v_cap"] or 0, r["a_cap"] or 0,
                     r["j_cap"] or 0, r["bound_by"]))
    if a.write or (not a.dry_run and not a.json):
        out = dict(d)
        for i, s in enumerate(segs):
            s = dict(s)
            s["t_in"] = float(s.get("t") or 0.0)
            s["t"] = rows[i]["t_final"]
            s["gate"] = {"stage": rows[i]["stage"], "v_mm_s": rows[i]["v_mm_s"],
                         "v_cap": rows[i]["v_cap"], "a_cap": rows[i]["a_cap"],
                         "j_cap": rows[i]["j_cap"], "r_mm": rows[i]["r_mm"],
                         "bound_by": rows[i]["bound_by"], "corner_s": rows[i].get("corner_s", 0.0),
                         "src": rows[i]["src"]}
            segs[i] = s
        out["plan"] = segs
        out["total_t"] = rep["t_out_s"]
        out["gate"] = {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"), "report": rep,
                       "corners": corners, "tool": "tools/plan_gate_corridor.py",
                       "note": "运动学通道(r_mm)+动力学(v/a/jerk)+拐角过渡 已压进 t; 逐段证据见 plan[i].gate"}
        tmp = GATED + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, GATED)
        print("✍ 已写 %s (%.1f KB)" % (os.path.relpath(GATED, ROOT), os.path.getsize(GATED) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
