#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三档目标成本 → 建议利润空间 → 三方分成 (唯一算法)。

老倪 2026-10-28: 「基础型 硬件成本 15 万单臂、软件 5 万; 精密型 硬件 20 万双臂、软件 10 万;
专业型 硬件 22 万双臂高算力高带宽、软件 15 万。按这个目标重新分成; 销售给出建议利润空间, 不要定售价」

所以这里算的是:
  单套成本 = 目标硬件成本 + 目标软件成本
  建议报价区间 = 成本 / (1 − 毛利空间), 给下限/中值/上限三个数, 不给单一售价
  三方分成 = 按硬件毛利 / 软件毛利 / 运营毛利的年度贡献占比
另给「目标成本 vs 现估成本」的降本缺口, 让销售知道还有多少水分要挤。

跑法: python3 tools/targets_model.py [--json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cost_model import build_tiers  # noqa: E402

SPEC = os.path.join(HERE, "spec", "cost_targets.json")


def _quote(cost, m):
    """按毛利率 m(%) 反推报价。"""
    return cost / (1.0 - m / 100.0) if m < 100 else cost


def build_targets():
    spec = json.load(open(SPEC, encoding="utf-8"))
    asum = spec["assumptions"]
    n = asum["units_per_year"]
    cost = build_tiers()
    T = {t["id"]: t for t in cost["tiers"]}
    out = []
    for k in ("A", "B", "C"):
        t = spec["tiers"][k]
        cur = T[k]
        hw, sw = float(t["hw_cost"]), float(t["sw_cost"])
        base = hw + sw
        hmin, hmax = t["hw_margin"]
        smin, smax = t["sw_margin"]
        hmid, smid = (hmin + hmax) / 2.0, (smin + smax) / 2.0
        # 报价区间: 全部取下限 / 全部取中值 / 全部取上限
        p_lo = _quote(hw, hmin) + _quote(sw, smin)
        p_mid = _quote(hw, hmid) + _quote(sw, smid)
        p_hi = _quote(hw, hmax) + _quote(sw, smax)
        g_hw = _quote(hw, hmid) - hw
        g_sw = _quote(sw, smid) - sw
        g_mid = g_hw + g_sw
        op_per = cur["ops_fee_per_piece"] * cur["pieces_year"]
        g_op = op_per * asum["op_margin_pct"] / 100.0
        # 老倪此前定的上限只当「客户可接受红线」: 报价被红线压住时, 毛利按比例缩水
        cap = cur["price_cap"]
        price_rec = min(p_mid, cap)
        capped = p_mid > cap
        factor = min(1.0, (cap - base) / g_mid) if g_mid > 0 else 1.0
        hw_g, sw_g = g_hw * factor, g_sw * factor
        # 年度口径 (n 套): 硬件与软件随套数, 运营随每套每年
        y = {"hw": hw_g * n, "sw": sw_g * n, "op": g_op * n}
        tot = y["hw"] + y["sw"] + y["op"]
        pct = {kk: 100.0 * y[kk] / tot for kk in ("hw", "sw", "op")} if tot else {}
        out.append({
            "id": k, "name": t["name"], "arms": t["arms"], "compute": t["compute"],
            "hw_desc": t["hw_desc"], "sw_desc": t["sw_desc"],
            "hw_cost": hw, "sw_cost": sw, "cost_total": base,
            "hw_margin": [hmin, hmax], "sw_margin": [smin, smax],
            "hw_mid": hmid, "sw_mid": smid,
            "price_lo": p_lo, "price_mid": p_mid, "price_hi": p_hi,
            "gross_hw": g_hw, "gross_sw": g_sw, "gross_mid": g_mid,
            "gross_pct_mid": 100.0 * g_mid / p_mid if p_mid else 0.0,
            "gross_pct_lo": 100.0 * (_quote(hw, hmin) + _quote(sw, smin) - base) / p_lo if p_lo else 0.0,
            "gross_pct_hi": 100.0 * (_quote(hw, hmax) + _quote(sw, smax) - base) / p_hi if p_hi else 0.0,
            "sw_share_of_cost": 100.0 * sw / base if base else 0.0,
            "gap_to_bom": cur["capex"] - hw,                 # 现估硬件成本 − 目标, 正数=要降的本
            "bom_capex": cur["capex"], "bom_nre": cur["nre_sum"],
            "ops_year": op_per, "gross_op_year": g_op,
            "year": y,
            "cap_ref": cap, "price_rec": price_rec, "capped": capped,
            "pct_at_cap": 100.0 * (cap - base) / cap if cap else 0.0,
            "gross_hw_capped": hw_g, "gross_sw_capped": sw_g,
            "pct_capped": pct,
            "pieces_year": cur["pieces_year"],
            "unit_cost": (base + cur["opex_year"]) / cur["pieces_year"] if cur["pieces_year"] else 0.0,
        })
    return {"assumptions": asum, "tiers": out, "cost": cost}


def main():
    r = build_targets()
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in r.items() if k != "cost"}, ensure_ascii=False, indent=1))
        return 0
    print("每年按 %d 套/档摊 (假设) · 运营毛利 %.0f%% · 只给建议利润空间, 不定售价"
          % (r["assumptions"]["units_per_year"], r["assumptions"]["op_margin_pct"]))
    print("%-4s %-6s %-5s %8s %8s %8s %18s %12s %s" % (
        "档位", "名称", "臂", "硬件成本", "软件成本", "单套成本", "建议报价区间(万)", "建议毛利空间", "分成 硬件/软件/运营"))
    for t in r["tiers"]:
        print("%-4s %-6s %-5s %7.0f万 %7.0f万 %7.0f万  %5.1f ~ %5.1f (中 %4.1f) %5.1f%%~%5.1f%%   %.1f / %.1f / %.1f" % (
            t["id"], t["name"], t["arms"], t["hw_cost"] / 1e4, t["sw_cost"] / 1e4, t["cost_total"] / 1e4,
            t["price_lo"] / 1e4, t["price_hi"] / 1e4, t["price_mid"] / 1e4,
            t["gross_pct_lo"], t["gross_pct_hi"], t["pct_capped"]["hw"], t["pct_capped"]["sw"], t["pct_capped"]["op"]))
        print("     建议报价 %.1f 万%s · 红线 %.0f 万 → 实际毛利 %.1f%% (%s)"
              % (t["price_rec"] / 1e4, " (顶格)" if t["capped"] else "", t["cap_ref"] / 1e4,
                 t["pct_at_cap"], "受红线约束" if t["capped"] else "未触红线"))
        print("     硬件毛利 %.1f~%.1f%% · 软件毛利 %.1f~%.1f%% · 比现估硬件成本低 %.1f 万 (要降的本)"
              % (t["hw_margin"][0], t["hw_margin"][1], t["sw_margin"][0], t["sw_margin"][1],
                 t["gap_to_bom"] / 1e4))
    return 0


if __name__ == "__main__":
    sys.exit(main())
