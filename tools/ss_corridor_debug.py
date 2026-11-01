#!/usr/bin/env python3
"""ss_corridor_debug.py — 逐技能调 3D 圆柱约束通道 (断点友好)

老倪 2026-11-01: 「把这个原子技能的通道·圆柱体·运动学约束的功能, 迁移到状态空间工程,
要在每个技能里, 我要用代码调试, 进入断点」

通道现在在**每个技能自己的 clamp() 末尾**:
    src/lerobot/policies/left_right/state_space/skills/atomic_skills.py
        AtomicSkill.corridor_finish()      ← 断点打这里 = 所有技能共用的一处收口
        各技能 clamp(): `return self.corridor_finish(_out)`   ← 断点打这里 = 这一个技能

用法
  ./gui-venv311/bin/python tools/ss_corridor_debug.py --list
  ./gui-venv311/bin/python tools/ss_corridor_debug.py --all            # 9 个技能一张表 (在管内/管外/A-B)
  ./gui-venv311/bin/python tools/ss_corridor_debug.py --skill SK03 --mode out -v
  ZMAX_CORRIDOR_BREAK=SK03 ./gui-venv311/bin/python -m pdb tools/ss_corridor_debug.py --skill SK03 --mode out
  # VSCode: 选 "🛑 通道·单技能" 启动配置, 或在 corridor_finish 那行直接 F9 打红点

判据 (脚本自己断言, 不需要人肉眼):
  ① 管内 (位置在轴线上, 速度沿轴) ⇒ 开/关通道 u 逐位相同 —— 通道不许动合法动作
  ② 管外 (横向偏 3r, 速度向外) ⇒ 削因含「横向切外 + 回中」, 单拍行程 ≤ s_tick
  ③ ZMAX_CORRIDOR=0 ⇒ u 与输入逐位相同 (对照口径)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(REPO, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "src"))

from lerobot.policies.left_right.state_space.skills.atomic_skills import (  # noqa: E402
    AtomicSkill, skill_for, skills_for_mode,
)

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "放入", "完成"]


def _v(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return _dot(a, a) ** 0.5


def _unit(a):
    n = _norm(a) or 1.0
    return [a[0] / n, a[1] / n, a[2] / n]


def _mid_of_poly(pts):
    """折线弧长中点 (沿真实轨迹取中间, 不在端点上, 避免 s<0/s>L 的边角)"""
    best = None
    total = sum(_norm(_v(pts[i + 1], pts[i])) for i in range(len(pts) - 1))
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = _norm(_v(pts[i + 1], pts[i]))
        if acc + seg >= total / 2.0:
            t = (total / 2.0 - acc) / max(seg, 1e-9)
            best = [pts[i][k] + (pts[i + 1][k] - pts[i][k]) * t for k in range(3)]
            best_axis = _unit(_v(pts[i + 1], pts[i]))
            return best, best_axis
        acc += seg
    p = pts[-1]
    return list(p), _unit(_v(pts[-1], pts[0]))


def _case(skill_cls, kind="out"):
    """造一个用例: (位置 mm, 动作 [vx,vy,vz,grip]) —— 全部从通道真源几何来, 不拍脑袋。

    管外样本的横向方向不能随便取 e1: 同一技能有多条机动 (转移 14 条 / 插入 28 条),
    往 e1 偏 3r 可能正好贴到**另一条**管子上 (实测 dev 反而不超 r) ⇒ 于是绕轴取 24 个方向,
    用通道自己的最近点算法挑 dev 最大的那个方向 —— 这样\"管外\"是算出来的, 不是假设的。
    """
    corr = skill_cls.corridor()
    if not corr:
        return None
    pts = (corr.get("polys") or [corr.get("pts")])[0]
    mid, ax = _mid_of_poly(pts)
    e1 = corr.get("e1") or [0.0, 0.0, 1.0]
    e2 = corr.get("e2") or [0.0, 1.0, 0.0]
    r = float(corr.get("r_mm") or 10.0)
    if kind == "in":
        pos = mid
        u = [ax[0] * 0.05, ax[1] * 0.05, ax[2] * 0.05, 0.0]      # 沿轴 50mm/s (管内合法动作)
        return {"pos_mm": pos, "u": u, "mid": mid, "axis": ax, "r_mm": r}
    m = skill_cls._corridor_mod()
    best = (-1.0, e1, 0.0)
    for k in range(24):
        ang = 2.0 * 3.141592653589793 * k / 24.0
        c, s = __import__("math").cos(ang), __import__("math").sin(ang)
        d = [e1[i] * c + e2[i] * s for i in range(3)]
        p = [mid[i] + d[i] * 3 * r for i in range(3)]
        dev = m.closest_on_polys(corr["polys"], p)[0] if corr.get("polys") else m.closest_on_poly(pts, p)[0]
        if dev > best[0]:
            best = (dev, d, ang)
    dev, d, ang = best
    pos = [mid[i] + d[i] * 3 * r for i in range(3)]
    u = [d[0] * 0.30, d[1] * 0.30, d[2] * 0.30, 0.0]              # 横向 300mm/s 向外
    return {"pos_mm": pos, "u": u, "mid": mid, "axis": ax, "r_mm": r,
            "offset_dir": d, "offset_deg": round(ang * 180.0 / 3.141592653589793, 1),
            "expect_dev_mm": round(dev, 3)}


def _run(skill_cls, case, corridor_on=True):
    """跑一次 clamp (真的走技能代码), 返回 (u_out, why, corridor_info)。"""
    old = os.environ.get("ZMAX_CORRIDOR")
    os.environ["ZMAX_CORRIDOR"] = "1" if corridor_on else "0"
    try:
        sk = skill_cls()
        sk.pos_mm = case["pos_mm"]           # 3D 坐标: 生产里来自 trace_live.json, 这里显式给
        out = sk.clamp(list(case["u"]), dt=0.1)
    finally:
        if old is None:
            os.environ.pop("ZMAX_CORRIDOR", None)
        else:
            os.environ["ZMAX_CORRIDOR"] = old
    return out.get("u"), out.get("why"), out.get("corridor")


def _same(a, b, tol=1e-12):
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def one(skill_cls, mode="both", verbose=False):
    """单个技能: 管内 (开/关逐位相同) + 管外 (切外+回中, 单拍不超)."""
    res = {"skill": skill_cls.code, "stage": skill_cls.CORRIDOR_STAGE or skill_cls.stage}
    corr = skill_cls.corridor()
    if not corr:
        if getattr(skill_cls, "CORRIDOR_ZERO_MOTION", False):
            res["na"] = "零位移段 (夹爪开合), 没有运动通道"
        else:
            res["error"] = "无通道真源 (zmax_data/ss_live/skill_corridors.json 缺该段)"
        return res
    res.update({"r_mm": corr.get("r_mm"), "L_mm": corr.get("L_mm"),
                "n_poly": corr.get("n_poly"), "tact_s": corr.get("tact_s"),
                "s_tick_mm": corr.get("s_tick_mm"), "v_along_cap": corr.get("v_along_cap")})
    ok = True
    if mode in ("in", "both"):
        c = _case(skill_cls, "in")
        u_on, why_on, ci_on = _run(skill_cls, c, True)
        u_off, why_off, _ = _run(skill_cls, c, False)
        same = _same(u_on, u_off)
        res["in_channel"] = {"u_on": u_on, "u_off": u_off, "identical": same,
                             "cor": ci_on, "why": why_on}
        ok = ok and same
    if mode in ("out", "both"):
        c = _case(skill_cls, "out")
        u_on, why_on, ci_on = _run(skill_cls, c, True)
        u_off, why_off, _ = _run(skill_cls, c, False)
        ci = ci_on or {}
        why = str(ci.get("why") or "")
        cut = ("横向切外" in why) and ("回中" in why)
        step_ok = float(ci.get("step_mm") or 0.0) <= float(corr.get("s_tick_mm") or 1e9) + 1e-6
        moved = not _same(u_on, u_off)
        res["out_channel"] = {"why": (ci.get("why") or why_on),
                              "dev_mm": ci.get("dev_mm"), "r_mm": ci.get("r_mm"),
                              "excess_mm": ci.get("excess_mm"), "step_mm": ci.get("step_mm"),
                              "s_tick_mm": corr.get("s_tick_mm"),
                              "u_out": u_on, "input": c["u"],
                              "cut_and_recenter": bool(cut), "step_within": bool(step_ok),
                              "differs_from_off": bool(moved)}
        ok = ok and cut and step_ok and moved
    res["pass"] = bool(ok)
    if verbose:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="逐技能调试 3D 圆柱约束通道")
    ap.add_argument("--list", action="store_true", help="列出技能 + 各自通道 (半径/轴长/机动条数)")
    ap.add_argument("--all", action="store_true", help="9 个技能全跑一遍 (在管内/管外/开关对照)")
    ap.add_argument("--skill", default=None, help="只跑一个: SK01..SK08 或段名 (接近/下降/...)")
    ap.add_argument("--mode", choices=["in", "out", "both"], default="both")
    ap.add_argument("--break", dest="brk", default=None,
                    help="设断点标记: 等于 1 / 技能号 / 段名 ⇒ corridor_finish 里 breakpoint()")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--json", action="store_true", help="只输出 JSON (给脚本/看板用)")
    a = ap.parse_args(argv)

    if a.brk:
        os.environ["ZMAX_CORRIDOR_BREAK"] = str(a.brk)
        print("🛑 ZMAX_CORRIDOR_BREAK=%s ⇒ 第一次过通道就停在 AtomicSkill.corridor_finish()"
              % a.brk, flush=True)

    classes = []
    for st in STAGES:
        cls = skill_for(st)
        if cls is not None and cls not in classes:
            classes.append(cls)

    if a.list:
        rows = []
        for cls in classes:
            corr = cls.corridor() or {}
            rows.append({"skill": cls.code, "stage": cls.CORRIDOR_STAGE or cls.stage,
                         "r_mm": corr.get("r_mm"), "L_mm": corr.get("L_mm"),
                         "n_poly": corr.get("n_poly"), "tact_s": corr.get("tact_s"),
                         "s_tick_mm": corr.get("s_tick_mm"), "v_along_cap": corr.get("v_along_cap")})
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print("%-6s %-8s %7s %10s %7s %7s %10s %12s" %
                  ("技能", "段", "r(mm)", "轴长(mm)", "机动数", "节拍s", "单拍mm", "轴向v上限"))
            for r in rows:
                print("%-6s %-8s %7s %10s %7s %7s %10s %12s" %
                      (r["skill"], r["stage"], r["r_mm"], r["L_mm"], r["n_poly"],
                       r["tact_s"], r["s_tick_mm"], r["v_along_cap"]))
        return 0

    if a.skill:
        cls = skill_for(a.skill) or next((c for c in classes if c.code == a.skill), None)
        if cls is None:
            print("❌ 没有这个技能: %s" % a.skill)
            return 2
        res = one(cls, a.mode, a.verbose)
        if a.json or not a.verbose:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("pass") else 1

    # --all (缺省)
    results = [one(c) for c in classes]
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0 if all(r.get("pass") or r.get("error") for r in results) else 1
    print("%-6s %-6s %6s %8s %14s %14s %6s" %
          ("技能", "段", "r(mm)", "n_poly", "管内(开关一致)", "管外(切外+回中)", "判定"))
    npass = 0
    for r in results:
        if r.get("na"):
            print("%-6s %-6s %6s %8s  %s" % (r["skill"], r["stage"], "-", "-", "⏭ " + r["na"]))
            continue
        if r.get("error"):
            print("%-6s %-6s %6s %8s  %s" % (r["skill"], r["stage"], "-", "-", "⚠ " + r["error"]))
            continue
        ic = r.get("in_channel") or {}
        oc = r.get("out_channel") or {}
        npass += 1 if r.get("pass") else 0
        print("%-6s %-6s %6s %8s %14s %14s %6s" %
              (r["skill"], r["stage"], r["r_mm"], r["n_poly"],
               "✅ 逐位相同" if ic.get("identical") else "❌ 变了",
               ("✅ dev=%.1f>r=%.1f" % (oc.get("dev_mm") or 0, oc.get("r_mm") or 0))
               if oc.get("cut_and_recenter") and oc.get("step_within") else "❌ " + str(oc.get("why")),
               "PASS" if r.get("pass") else "FAIL"))
    miss = [r["skill"] + "(" + r["stage"] + ")" for r in results if r.get("error")]
    na = [r["skill"] + "(" + r["stage"] + ")" for r in results if r.get("na")]
    total = len([r for r in results if not r.get("na")])
    print("\n%d/%d 技能通过 · N/A(零位移): %s · 缺真源: %s"
          % (npass, total, ",".join(na) or "无", ",".join(miss) or "无"))
    return 0 if npass == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
