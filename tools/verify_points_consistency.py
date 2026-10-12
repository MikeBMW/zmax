#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_points_consistency.py — 点位「全局一致」体检 (老倪 2026-10-12: 「要实时更新数据库, 全局数据要保持一致」)

一个物理点在三处出现, 必须同值:
  ① AOI 台账   reports/aoi_points/<点名>.json     ← 配置中心的真源(task_build 只读它)
  ② L2 技能库  data/skills/l2_atomic/taught_points.json   ← L2.goto_* 技能实际回的点
  ③ 空间点库   data/skills/l2_atomic/space_points.json    ← 8793 空间点1~8(独立库, 只比它自己)
  ④ 任务配置   config/tasks/tasks.json 的 TASK-07-AOI overrides.pt.<点名>  ← 配置中心显示的值

判据: ①② 位置差 ≤ 1e-5 m; ④ 里的 x/y/z 与 ① 逐位相符(6 位小数) —— **姿态 a b c 也要逐位相符**;
     台账里的点都能在 ④ 找到(反之亦然)。
用法: gui-venv311/bin/python tools/verify_points_consistency.py [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "reports/aoi_points")
TAUGHT = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
SPACE = os.path.join(ROOT, "data/skills/l2_atomic/space_points.json")
TASKS = os.path.join(ROOT, "config/tasks/tasks.json")
TOL_M = 1e-5


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                           # noqa: BLE001
        return d


def _dist(a, b):
    try:
        return max(abs(float(a[i]) - float(b[i])) for i in range(3))
    except Exception:                                                           # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rows, bad = [], []

    # ① 台账
    led = {}
    try:
        for fn in sorted(os.listdir(LEDGER)):
            if not fn.endswith(".json"):
                continue
            j = _j(os.path.join(LEDGER, fn)) or {}
            pos = j.get("pos") or []
            if len(pos) == 3:
                led[j.get("point") or fn[:-5]] = {"pos": pos, "t": j.get("recorded_at"),
                                                  "abc": j.get("abc"), "quat": j.get("quat"),
                                                  "src": "reports/aoi_points/%s" % fn}
    except OSError:
        pass
    # ② L2 技能库
    tp = (_j(TAUGHT, {}) or {}).get("points") or {}
    # ③ 空间点库
    sp = (_j(SPACE, {}) or {}).get("points") or {}
    # ④ 任务配置
    ov = {}
    for t in ((_j(TASKS, {}) or {}).get("tasks") or []):
        if t.get("task_id") == "TASK-07-AOI":
            ov = t.get("overrides") or {}
    pat = re.compile(r"x=(-?[\d.]+)\s+y=(-?[\d.]+)\s+z=(-?[\d.]+)")

    import pt_pose as _pp                                                   # 姿态唯一口径
    pat_abc = re.compile(r"a=(-?[\d.]+)\s+b=(-?[\d.]+)\s+c=(-?[\d.]+)")

    def _abc_of(rec):
        try:
            _v = _pp.rec_abc(rec)
            return ("%.3f|%.3f|%.3f" % (_v[0], _v[1], _v[2])) if _v else ""
        except Exception:                                                   # noqa: BLE001
            return ""

    for name, v in sorted(led.items()):
        r = {"point": name, "ledger": v["pos"], "taught": (tp.get(name) or {}).get("pos")}
        d12 = _dist(v["pos"], r["taught"]) if r["taught"] else None
        r["ledger_vs_taught_m"] = d12
        cfg = ov.get("pt." + name)
        m = pat.search(str(cfg or ""))
        r["in_config"] = bool(m)
        r["config_vs_ledger"] = (("x=%.6f y=%.6f z=%.6f" % tuple(v["pos"][:3])) == m.group(0).strip()
                                 if m else None)
        # 姿态 a b c: 台账(或它没存 abc 就从 quat 现算) 必须与配置里那串逐位相符
        _labc = _abc_of(v)
        _mabc = pat_abc.search(str(cfg or ""))
        r["abc_ledger"] = _labc
        r["abc_in_config"] = bool(_mabc)
        r["config_vs_ledger_abc"] = (("%s|%s|%s" % (_mabc.group(1), _mabc.group(2), _mabc.group(3))) == _labc
                                     if (_mabc and _labc) else None)
        rows.append(r)
        if _labc and (not _mabc):
            bad.append("%s: 配置里没有姿态 a b c(老倪: 6 个数字都要有)" % name)
        elif _labc and _mabc and not r["config_vs_ledger_abc"]:
            bad.append("%s: 姿态与台账不符(配置 %s vs 台账 %s)" % (name, _mabc.group(0), _labc))
        if d12 is None or d12 > TOL_M:
            bad.append("%s: 台账≠L2库(差 %s m)" % (name, d12))
        if not m:
            bad.append("%s: 台账里有, 任务配置里没有(配置中心看不到)" % name)
        elif not r["config_vs_ledger"]:
            bad.append("%s: 配置里的值与台账不符(%s vs 台账 %s)" % (name, cfg, v["pos"]))

    # 空间点(独立库)也要在配置里 —— 位置 + 姿态 a b c 都要
    for k, v in sorted(sp.items()):
        nm = ("空间点" + str(k)[5:]) if str(k).startswith("space") else str(k)
        cfg = ov.get("pt." + nm)
        m = pat.search(str(cfg or ""))
        mabc = pat_abc.search(str(cfg or ""))
        pos = v.get("pos") or []
        ok = bool(m) and len(pos) == 3 and m.group(0).strip() == ("x=%.6f y=%.6f z=%.6f" % tuple(pos[:3]))
        _labc = _abc_of(v)
        okabc = bool(mabc) and bool(_labc) and (
            ("%s|%s|%s" % (mabc.group(1), mabc.group(2), mabc.group(3))) == _labc)
        rows.append({"point": nm, "space": pos, "abc_space": _labc, "in_config": bool(m),
                     "config_vs_space": ok, "config_vs_space_abc": okabc})
        if not ok:
            bad.append("%s: 空间点库≠配置(%s vs %s)" % (nm, cfg, pos))
        if not okabc:
            bad.append("%s: 空间点姿态≠配置(%s vs 库 %s)" % (nm, (mabc.group(0) if mabc else "缺"), _labc))

    if a.json:
        print(json.dumps({"rows": rows, "bad": bad, "n": len(rows)}, ensure_ascii=False, indent=1))
    else:
        print("点位全局一致体检 —— 台账 %s · L2库 %s · 空间点库 %s · 配置 %s"
              % ("reports/aoi_points", "taught_points.json", "space_points.json", "tasks.json"))
        for r in rows:
            if "ledger" in r:
                print("  %-8s 台账 %s abc=%s · L2库差 %s m · 配置 %s"
                      % (r["point"], r["ledger"], r.get("abc_ledger") or "—", r["ledger_vs_taught_m"],
                         "✅同值" if (r.get("config_vs_ledger") and r.get("config_vs_ledger_abc") is not False)
                         else ("缺" if not r["in_config"] else "✗不符")))
            else:
                print("  %-8s 空间点 %s abc=%s · 配置 %s"
                      % (r["point"], r["space"], r.get("abc_space") or "—",
                         "✅同值(位置+姿态)" if (r.get("config_vs_space") and r.get("config_vs_space_abc"))
                         else "✗"))
        print("\n=== %s (共 %d 个点 · 问题 %d) ==="
              % ("✅ 全部一致" if not bad else "⛔ 有不一致", len(rows), len(bad)))
        for b in bad:
            print("   ⛔ " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
