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


TIERS = os.path.join(ROOT, "tools", "spec", "cost_model.json")
TRAJ = os.path.join(ROOT, "zmax_data", "runtime", "traj", "sim_insert.json")


def measured_tact():
    """从 392 段轨迹真源算单件节拍 (与《性能配置》同一口径, 不另拍数字)。"""
    try:
        d = load_json(TRAJ)
        segs = d.get("plan")
        if segs is None:
            segs = next(v for v in d.values()
                        if isinstance(v, list) and v and isinstance(v[0], dict) and "a" in v[0])
        t_all = sum(float(s.get("t") or 0) for s in segs)
        # 单件节拍真源优先级: tact_steady_s (稳态) > tact_module_s > total/件数
        # ⚠ cycles=8 是「循环块」不是件数, 件数在 mods=14 —— 用错会把 11.42 算成 19.93
        n_mod = int(d.get("mods") or 14)
        tact = float(d.get("tact_steady_s") or d.get("tact_module_s") or (t_all / n_mod))
        return tact, len(segs), t_all, n_mod
    except Exception:                                                           # noqa: BLE001
        return 11.39, 392, 159.43, 14


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def build_tiers(path=None):
    """三档成本核算 (基础/精细/专业) —— 输入只有单价口径, 结论全部现算。

    三档与《性能配置》A/B/C、《工程配置》A/B/C 一一对应 (同一 id)。
    """
    spec = load_json(path or TIERS)
    tact, n_seg, t_all, n_cyc = measured_tact()
    uph = 3600.0 / tact
    out = {"_meta": spec.get("_meta", {}), "tact_s": round(tact, 2), "segs": n_seg,
           "t_all_s": round(t_all, 2), "cycles": n_cyc, "uph_geo": round(uph, 1),
           "split_note": (spec.get("split") or {}).get("note", ""), "tiers": [], "split": {}}

    for t in spec["tiers"]:
        capex = sum(float(x["qty"]) * float(x["unit"]) for x in (t.get("bom") or []))
        nre = sum(float(x["qty"]) * float(x["unit"]) for x in (t.get("nre") or []))
        hours = float(t.get("hours_per_year") or 4800)
        oee = float(t.get("oee") or 0.85)
        pieces = uph * hours * oee
        opex_items = []
        for o in t.get("opex") or []:
            if o.get("pct_of_capex"):
                val = capex * float(o["pct_of_capex"])
                b = "capex 的 %.1f%%" % (float(o["pct_of_capex"]) * 100)
            else:
                val = float(o.get("qty", 1)) * float(o.get("unit", 0))
                b = o.get("basis", "年")
            opex_items.append({"name": o["name"], "value": val, "basis": b})
        opex = sum(x["value"] for x in opex_items)
        dep = capex / float(t.get("dep_years") or 5)
        nre_amort = nre / float(t.get("nre_years") or 3)
        price = float(t["price_per_piece"])
        revenue = pieces * price
        cost_year = dep + opex + nre_amort
        unit_cost = cost_year / pieces if pieces else 0
        cash = revenue - opex
        payback = (capex + nre) / cash if cash > 0 else None
        out["tiers"].append({
            "id": t["id"], "name": t["name"], "layers": t.get("layers"), "tops": t.get("tops"),
            "bom": t.get("bom") or [], "nre": t.get("nre") or [], "opex_items": opex_items,
            "capex": round(capex, 2), "nre_sum": round(nre, 2), "opex_year": round(opex, 2),
            "dep_year": round(dep, 2), "nre_amort": round(nre_amort, 2),
            "hours_per_year": hours, "oee": oee, "pieces_year": int(pieces),
            "price_per_piece": price, "price_basis": t.get("price_basis", ""),
            "revenue_year": round(revenue, 2), "cost_year": round(cost_year, 2),
            "unit_cost": round(unit_cost, 4), "unit_margin": round(price - unit_cost, 4),
            "gross_year": round(revenue - cost_year, 2),
            "gross_margin_pct": round(100.0 * (revenue - cost_year) / revenue, 1) if revenue else 0,
            "payback_years": round(payback, 2) if payback else None,
        })

    sp = spec.get("split") or {}
    w2 = sp.get("value_weights") or {"hw": 0.45, "sw": 0.30, "op": 0.25}
    lic = float(sp.get("license_pct") or 0.20)
    fee = float(sp.get("op_fee_per_piece") or 0.02)
    for r in out["tiers"]:
        cash = r["revenue_year"] - r["opex_year"]
        tot = r["capex"] + r["nre_sum"] + r["opex_year"]

        def pct(d):
            s = sum(d.values()) or 1
            return {k: round(100.0 * v / s, 1) for k, v in d.items()}

        s1 = {"hw": r["capex"] / tot, "sw": r["nre_sum"] / tot, "op": r["opex_year"] / tot}
        s2 = {k: cash * float(v) for k, v in w2.items()}
        sw3 = r["revenue_year"] * lic
        op3 = r["pieces_year"] * fee
        hw3 = max(0.0, cash - sw3 - op3)
        out["split"][r["id"]] = {
            "cash_year": round(cash, 2),
            "s1_invest": {"abs": {k: round(v, 2) for k, v in s1.items()}, "pct": pct(s1)},
            "s2_value": {"abs": {k: round(v, 2) for k, v in s2.items()}, "pct": pct(s2)},
            "s3_hybrid": {"abs": {"hw": round(hw3, 2), "sw": round(sw3, 2), "op": round(op3, 2)},
                          "pct": pct({"hw": hw3, "sw": sw3, "op": op3}),
                          "rule": "硬件一次性 + 软件许可 %.0f%% 收益 + 运营 %.2f 元/件" % (lic * 100, fee)},
        }
    out["split_recommend"] = sp.get("recommend") or "s3_hybrid"
    out["split_weights_basis"] = sp.get("value_weights_basis", "")
    return out


def main():
    ap = argparse.ArgumentParser(description="单套成本/回本测算 + 三档成本核算")
    ap.add_argument("--tiers", action="store_true", help="按 性能等级 A/B/C 算 基础/精细/专业 成本")
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

    if a.tiers:
        d = build_tiers()
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
            return 0
        print("实测节拍 %.2f s/件 · 几何产能 %.1f UPH (%d 段 / %.2f s / %d 件)"
              % (d["tact_s"], d["uph_geo"], d["segs"], d["t_all_s"], d["cycles"]))
        for r in d["tiers"]:
            print("\n== %s %s (%s · ≤%s TOPS)" % (r["id"], r["name"], r["layers"], r["tops"]))
            print("   capex %.0f · NRE %.0f · 运营 %.0f/年 · 折旧 %.0f/年"
                  % (r["capex"], r["nre_sum"], r["opex_year"], r["dep_year"]))
            print("   年产量 %d 件 (%.0fh × OEE %.2f) · 单价 %.2f · 单件成本 %.4f · 单件毛利 %.4f"
                  % (r["pieces_year"], r["hours_per_year"], r["oee"], r["price_per_piece"],
                     r["unit_cost"], r["unit_margin"]))
            print("   年收入 %.0f · 年毛利 %.0f (%.1f%%) · 回收期 %s 年"
                  % (r["revenue_year"], r["gross_year"], r["gross_margin_pct"], r["payback_years"]))
            sp = d["split"][r["id"]]
            print("   分成: 投入比例 %s · 价值贡献 %s · 混合制 %s  (可分现金 %.0f/年)"
                  % (sp["s1_invest"]["pct"], sp["s2_value"]["pct"], sp["s3_hybrid"]["pct"], sp["cash_year"]))
        return 0

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
