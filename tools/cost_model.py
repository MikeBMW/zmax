#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单套成本 / 回本测算 (Z-MAX 唯一算法真源, 无 Qt 依赖)。

为什么单独一个模块: 配置中心「💰 成本/报价」页、画布「成本」节点、立项文档导出器
三处要**同一套公式与同一个真源**, 各写一份必然出现"页面 36.3 万、文档 34.8 万"。

真源: config/platform/zmax_cost_model.json (硬件逐项 + 软件 + 人力 + 产线规模)
口径 (老倪 2026-10-19):
  单套投入 = 硬件合计 + 软件
  年节省   = 工位数 × 班次 × 每班人数 × 人力成本/人·年
  静态回本 = 单套投入 ÷ 年节省        (不计折现、不计质量损耗与增产)
替代臂方案 = 单套投入 − 降本额 (只换臂, 其余不变)

CLI:
  python3 tools/cost_model.py                       # 默认档位算一遍 (与页面同值)
  python3 tools/cost_model.py --stations 2 --shifts 2
  python3 tools/cost_model.py --json                # 给节点/文档吃
  python3 tools/cost_model.py --save-line --stations 2 --shifts 2 --persons 1 --labor 90000
"""
import argparse
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUTH = os.path.join(ROOT, "config", "platform", "zmax_cost_model.json")


def _r2(x):
    return round(float(x) + 1e-12, 2)


def load(path=None):
    p = path or TRUTH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def hardware_total(d):
    return float(sum(float(it.get("price") or 0) for it in (d.get("hardware") or [])))


def estimate(d=None, stations=None, shifts=None, persons_per_shift=None,
             labor_per_person_year=None, software=None, alt_arm_saving=None,
             hardware=None, alt_arm=False):
    """算一套 (单工位口径可扩到 N 工位)。未给的量一律取真源, 不写死默认。"""
    d = d if d is not None else load()
    line = d.get("line") or {}
    st = int(stations if stations is not None else line.get("stations", 1))
    sh = int(shifts if shifts is not None else line.get("shifts", 2))
    pp = int(persons_per_shift if persons_per_shift is not None
             else line.get("persons_per_shift", 1))
    lab = float(labor_per_person_year if labor_per_person_year is not None
                else (d.get("labor") or {}).get("cost_per_person_year", 0))
    hw = float(hardware if hardware is not None else hardware_total(d))
    sw = float(software if software is not None
               else (d.get("software") or {}).get("price", 0))
    alt = float(alt_arm_saving if alt_arm_saving is not None
                else (d.get("alt_arm") or {}).get("saving", 0))

    total = hw + sw
    annual = st * sh * pp * lab
    payback = (total / annual) if annual > 0 else None
    total_alt = total - alt
    payback_alt = (total_alt / annual) if annual > 0 else None

    return {
        "stations": st, "shifts": sh, "persons_per_shift": pp,
        "heads": st * sh * pp,
        "labor_per_person_year": lab,
        "hardware": hw, "software": sw,
        "total": (total_alt if alt_arm else total),
        "total_first": total,
        "total_alt": total_alt,
        "annual_save": annual,
        "payback_years": _r2(payback) if payback is not None else None,
        "payback_years_alt": _r2(payback_alt) if payback_alt is not None else None,
        "alt_arm_saving": alt,
        "scheme": "替代力控臂" if alt_arm else (d.get("hardware_arm_label") or "第一期"),
        "formula": "%.1f万 ÷ %.1f万 = %s 年" % (
            total / 1e4, annual / 1e4,
            ("%.2f" % payback) if payback is not None else "—"),
        "truth": TRUTH,
        "truth_mtime": time.strftime("%m-%d %H:%M",
                                     time.localtime(os.path.getmtime(TRUTH)))
        if os.path.exists(TRUTH) else "—",
    }


def save_line(stations=None, shifts=None, persons_per_shift=None,
              labor_per_person_year=None, software=None, alt_arm_saving=None,
              path=None):
    """只改 line/labor.cost_per_person_year/software.price/alt_arm.saving 四个假设, 其余不动。

    铁律: 读-改-写单键 + 备份 + 回读校验 (别整表重写, 也别只信自己写的日志)。
    """
    p = path or TRUTH
    d = load(p)
    if stations is not None:
        d.setdefault("line", {})["stations"] = int(stations)
    if shifts is not None:
        d.setdefault("line", {})["shifts"] = int(shifts)
    if persons_per_shift is not None:
        d.setdefault("line", {})["persons_per_shift"] = int(persons_per_shift)
    if labor_per_person_year is not None:
        d.setdefault("labor", {})["cost_per_person_year"] = float(labor_per_person_year)
    if software is not None:
        d.setdefault("software", {})["price"] = float(software)
    if alt_arm_saving is not None:
        d.setdefault("alt_arm", {})["saving"] = float(alt_arm_saving)
    d["updated"] = time.strftime("%Y-%m-%d %H:%M")

    bak = p + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(p, bak)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)

    back = load(p)                                   # 回读: 写进去的必须真在盘上
    ok = ((stations is None or back["line"]["stations"] == int(stations))
          and (shifts is None or back["line"]["shifts"] == int(shifts))
          and (persons_per_shift is None or back["line"]["persons_per_shift"] == int(persons_per_shift)))
    return {"ok": bool(ok), "path": p, "backup": bak,
            "line": back.get("line"), "labor": back.get("labor")}


def main():
    ap = argparse.ArgumentParser(description="单套成本/回本测算")
    ap.add_argument("--stations", type=int)
    ap.add_argument("--shifts", type=int)
    ap.add_argument("--persons", type=int, dest="persons_per_shift")
    ap.add_argument("--labor", type=float, dest="labor_per_person_year")
    ap.add_argument("--software", type=float)
    ap.add_argument("--alt-saving", type=float, dest="alt_arm_saving")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save-line", action="store_true")
    a = ap.parse_args()

    if a.save_line:
        r = save_line(a.stations, a.shifts, a.persons_per_shift,
                      a.labor_per_person_year, a.software, a.alt_arm_saving)
        print(("✅ 已写回真源 " if r["ok"] else "❌ 回读不一致 ") + r["path"])
        print("   备份:", r["backup"])
        print("   line=%s labor=%s" % (r["line"], r["labor"]))
        return 0 if r["ok"] else 2

    e = estimate(stations=a.stations, shifts=a.shifts,
                 persons_per_shift=a.persons_per_shift,
                 labor_per_person_year=a.labor_per_person_year,
                 software=a.software, alt_arm_saving=a.alt_arm_saving)
    if a.json:
        print(json.dumps(e, ensure_ascii=False, indent=1))
        return 0
    print("单套成本 (%s)  真源 %s @ %s" % (e["scheme"], e["truth"], e["truth_mtime"]))
    print("  硬件 %.1f 万 + 软件 %.1f 万 = 单套 %.1f 万" % (
        e["hardware"] / 1e4, e["software"] / 1e4, e["total_first"] / 1e4))
    print("  产线 %d 工位 × %d 班 × %d 人/班 = %d 人 · %.1f 万/人·年 ⇒ 年节省 %.1f 万" % (
        e["stations"], e["shifts"], e["persons_per_shift"], e["heads"],
        e["labor_per_person_year"] / 1e4, e["annual_save"] / 1e4))
    print("  静态回本 %s 年   (%s)" % (e["payback_years"], e["formula"]))
    print("  替代力控臂: 单套 %.1f 万 (降 %.1f 万) ⇒ 回本 %s 年" % (
        e["total_alt"] / 1e4, e["alt_arm_saving"] / 1e4, e["payback_years_alt"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
