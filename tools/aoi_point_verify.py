#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AOI 点标记 · 三源对账器 (老倪现场示教时逐点核验用)。

用法: gui-venv311/bin/python tools/aoi_point_verify.py 侧面点1 [侧面点2 ...]

三源:
  ① 配置中心读的 AOI 台账  reports/aoi_points/<点名>.json   (8793 标记模式写, 经 record_point_sdk.py)
  ② L2 技能库              data/skills/l2_atomic/taught_points.json
  ③ 我独立录的示教路径      zmax_data/aoi_teach/session_*.jsonl (20Hz, 位姿唯一依据 xcoresdk endInRef 直采)

判据: ①② 值一致 + 时间戳是本次(近 30 分钟内) + ③ 在同一时刻的位姿与①② 偏差 ≤1mm。
任一条不满足 ⇒ 打印 ❌ 并给出原因(不臆断通过)。
"""
import datetime
import glob
import json
import os
import sys
import time

CST = datetime.timezone(datetime.timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as fh:
        return json.load(fh)


def _pos_of(d):
    p = (d or {}).get("pos") or (d or {}).get("xyz") or []
    try:
        return [float(x) for x in p[:3]]
    except Exception:
        return []


def _epoch(s):
    try:
        return datetime.datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST).timestamp()
    except Exception:
        try:
            return float(s)
        except Exception:
            return None


def check(name, session=None, fresh_s=1800.0):
    led_p = "reports/aoi_points/%s.json" % name
    out = {"point": name, "ok": False, "why": [], "evidence": {}}
    if not os.path.exists(os.path.join(ROOT, led_p)):
        out["why"].append("台账不存在: %s" % led_p)
        return out
    led = _load(led_p)
    tp = _load("data/skills/l2_atomic/taught_points.json")
    pts = tp.get("points") or tp
    sk = pts.get(name) or {}
    lp, sp = _pos_of(led), _pos_of(sk)
    lt = led.get("recorded_at") or led.get("ts")
    te = _epoch(lt)
    out["evidence"]["ledger"] = {"pos": lp, "recorded_at": str(lt), "src": led.get("source")}
    out["evidence"]["skill_lib"] = {"pos": sp}
    if not lp or not sp:
        out["why"].append("台账或技能库缺 pos (台账 %d 维 / 库 %d 维)" % (len(lp), len(sp)))
    else:
        dv = max(abs(a - b) for a, b in zip(lp, sp))
        out["evidence"]["two_lib_delta_m"] = dv
        if dv > 1e-9:
            out["why"].append("两库不一致, 最大偏差 %.3g m" % dv)
    if te is None:
        out["why"].append("台账时间戳无法解析: %r" % lt)
    else:
        age = time.time() - te
        out["evidence"]["age_s"] = round(age, 1)
        if age > fresh_s:
            out["why"].append("台账陈旧: 录于 %s (%.0f 分钟前)" % (lt, age / 60.0))
        elif age < -60:
            out["why"].append("台账时间戳在未来: %s" % lt)
    # ③ 独立路径对账
    fs = [session] if session else sorted(glob.glob(os.path.join(ROOT, "zmax_data/aoi_teach/session_*.jsonl")))
    best = None
    for fp in fs:
        if not fp or not os.path.exists(fp if os.path.isabs(fp) else os.path.join(ROOT, fp)):
            continue
        fp = fp if os.path.isabs(fp) else os.path.join(ROOT, fp)
        with open(fp, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln.startswith("{"):
                    continue
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                t = r.get("t")
                if t is None or te is None:
                    continue
                d = abs(float(t) - te)
                if best is None or d < best[0]:
                    best = (d, r)
    if best is None:
        out["evidence"]["path"] = "无可用路径记录 (会话文件缺失/时间戳不可比)"
        out["why"].append("没有独立路径可比: 会话记录缺失")
    else:
        d, r = best
        xyz = [float(x) for x in (r.get("xyz") or [])[:3]]
        dd = max(abs(a - b) for a, b in zip(xyz, lp)) if (xyz and lp) else -1.0
        out["evidence"]["path"] = {"dt_s": round(d, 3), "xyz": xyz,
                                   "max_delta_m": dd,
                                   "mesh": ("%.3f mm" % (1000 * dd)) if dd >= 0 else "n/a"}
        if lp and dd < 0:
            out["why"].append("路径帧缺 xyz")
        elif lp and dd > 1e-3:
            out["why"].append("独立路径与标记点偏差 %.1f mm > 1mm" % (1000 * dd))
        elif lp and d > 1.0:
            out["why"].append("独立路径最近帧时间差 %.2fs (>1s, 无法确认同刻)" % d)
    out["ok"] = not out["why"]
    return out


def main(argv):
    names = [a for a in argv[1:] if not a.startswith("-")] or ["侧面点0"]
    allok = True
    for nm in names:
        r = check(nm)
        ev = r["evidence"]
        print("─" * 86)
        print("%s %s   %s" % ("✅" if r["ok"] else "❌", nm, "三源一致" if r["ok"] else "; ".join(r["why"])))
        if ev.get("ledger"):
            print("   ① AOI 台账   %s   录于 %s" % (["%.5f" % x for x in ev["ledger"]["pos"]], ev["ledger"]["recorded_at"]))
        if ev.get("skill_lib"):
            print("   ② L2 技能库  %s   (与①偏差 %s)"
                  % (["%.5f" % x for x in ev["skill_lib"]["pos"]], ev.get("two_lib_delta_m")))
        p = ev.get("path")
        if isinstance(p, dict):
            print("   ③ 独立路径   dt=%.2fs  %s   偏差 %s" % (p["dt_s"], ["%.5f" % x for x in p["xyz"]], p["mesh"]))
        elif p:
            print("   ③ 独立路径   %s" % p)
        allok = allok and r["ok"]
    print("─" * 86)
    print("结论: %s" % ("全部通过" if allok else "有未通过项(见上)"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
