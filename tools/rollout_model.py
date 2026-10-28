#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场策略 → 三阶段单位经济与分成 (唯一算法)。

读 tools/spec/rollout.json (阶段参数 / 免费期 / 分成偏好) + cost_model.build_tiers() (成本与售价),
逐月模拟客户现金流算回本, 并按档位定价分成 + 阶段偏好给出三方占比。
配置中心页面、立项报告、PPT 都调这里, 不各存一份数字。

跑法: python3 tools/rollout_model.py [--json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cost_model import build_tiers  # noqa: E402

SPEC = os.path.join(HERE, "spec", "rollout.json")


def _norm3(hw, sw, op):
    t = hw + sw + op
    return {"hw": 100.0 * hw / t, "sw": 100.0 * sw / t, "op": 100.0 * op / t}


def _payback_months(invest, labor_month, fee_month, free_months, cap=180):
    """逐月走现金流: 免费期内不付软件与运营费, 但人工照省。返回回本月数 (None = 期内不回本)。"""
    cum = -invest
    for m in range(1, cap + 1):
        pay = 0.0 if m <= free_months else fee_month
        cum += labor_month - pay
        if cum >= 0:
            return m
    return None


def build_rollout():
    spec = json.load(open(SPEC, encoding="utf-8"))
    d = build_tiers()
    T = {t["id"]: t for t in d["tiers"]}
    ppy = spec["labor"]["per_person_year"]
    out = []
    for ph in spec["phases"]:
        t = T[ph["tier"]]
        pieces = t["pieces_year"]
        invest = t["price_set"]                     # 客户实付 = 设备价; 未吸收 NRE 厂家自担
        labor = ph["persons"] * ppy
        lic_y = t["license_per_piece"] * pieces + t["license_upfront"] / t["nre_years"]
        ops_y = t["ops_fee_per_piece"] * pieces
        fee_y = lic_y + ops_y
        r = ph.get("reuse") or {}
        reuse_y = 0.0
        if r:
            tgt = T[r.get("tier", ph["tier"])]
            reuse_y = r["new_scenes_per_year"] * tgt["nre_sum"] * r["reuse_ratio"]
        net_steady = labor + reuse_y - fee_y
        free = ph.get("free_months", 0)
        pm_nofree = _payback_months(invest, (labor + reuse_y) / 12.0, fee_y / 12.0, 0)
        pm = _payback_months(invest, (labor + reuse_y) / 12.0, fee_y / 12.0, free)
        y1 = labor - (0.0 if free >= 12 else fee_y * max(0, 12 - free) / 12.0)
        base = d["split"][ph["tier"]]["s4_priced"]["pct"]
        bias = ph.get("split_bias") or {}
        adj = {k: base[k] + float(bias.get(k, 0.0)) for k in ("hw", "sw", "op")}
        pct = _norm3(adj["hw"], adj["sw"], adj["op"])
        out.append({
            "key": ph["key"], "name": ph["name"], "tier": ph["tier"], "tier_name": t["name"],
            "months": ph["months"], "persons": ph["persons"], "free_months": free,
            "scenes_gate": ph["scenes_gate"], "gate_note": ph["gate_note"],
            "why": ph["why"], "bias_note": ph["bias_note"],
            "price": invest, "labor_year": labor,
            "license_year": lic_y, "ops_year": ops_y, "pay_year": fee_y,
            "net_save_year": net_steady, "net_save_year1": y1 + reuse_y,
            "reuse_year": reuse_y, "payback_months_nofree": pm_nofree,
            "payback_months": pm,
            "payback_years": (pm / 12.0) if pm else None,
            "pct": pct, "pct_base": base,
            "gross_hw": t["hw_gross"], "gap_nre": t["gap_nre"],
        })
    return {"labor_per_person_year": ppy, "phases": out, "tiers": T, "cost": d,
            "policy_note": spec.get("policy_note", "")}


def main():
    r = build_rollout()
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in r.items() if k not in ("tiers", "cost")},
                         ensure_ascii=False, indent=1))
        return 0
    print("人工口径: 每人每年 %.0f 万 · 分成按档位定价分成再按阶段偏好微调" % (r["labor_per_person_year"] / 1e4))
    print("%-3s %-15s %-4s %3s %7s %6s %7s %7s %6s %6s %6s  %s" % (
        "阶段", "名称", "档位", "人数", "客户投入", "免费用", "人工/年", "复用收益", "净省", "无让利", "让利后", "分成 硬件/软件/运营"))
    for p in r["phases"]:
        print("%-3s %-15s %-4s %2d人 %6.1f万 %5d月 %5.1f万 %6.1f万 %6.1f万 %5.2f年 %5.2f年  %.1f / %.1f / %.1f" % (
            p["key"], p["name"], p["tier"], p["persons"], p["price"] / 1e4, p["free_months"],
            p["labor_year"] / 1e4, p["reuse_year"] / 1e4, p["net_save_year"] / 1e4,
            (p["payback_months_nofree"] or 999) / 12.0, (p["payback_months"] or 999) / 12.0,
            p["pct"]["hw"], p["pct"]["sw"], p["pct"]["op"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
