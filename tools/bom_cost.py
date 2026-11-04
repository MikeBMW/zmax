#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bom_cost.py — BOM 与成本分析 (三档: 双臂精细操作 / 单臂集出版 / 专家版)

口径 (必须写清, 否则数字没意义):
  · 单价为 **2026 年参考价** (市场区间中值), 不是报价单; 换供应商会变
  · 目标 30 / 22 / 35 万 按用户给的"目标成本"理解 → 同时给"若当售价"的反算, 两种都列
  · 不含: 输送线、立库、MES 对接、厂房改造 (交付边界)
  · 毛利率 = (售价 − BOM)/售价; 回本 = 设备售价 / 年净省
输出: reports/compute/BOM_COST.{json,md}
"""
from __future__ import annotations

import json
import os
import time

ROOT = os.environ.get("ZMAX_ROOT", os.path.expanduser("~/zmax"))
OUT = os.path.join(ROOT, "reports/compute")

# 单价 (万元, 参考价)
P = {
    "arm6": 5.8,          # 六轴协作臂 5kg / 1300mm / ±0.02mm
    "gripper": 1.6,       # 精对位二指夹爪 + 单轴力觉 (0-200N, 0.1N)
    "ft6": 3.2,           # 六维力/力矩传感器
    "cam_arm": 0.45,      # 手臂相机 1200 万全局快门
    "cam3d": 2.8,         # 3D 视觉 (专家版)
    "compute_550c": 1.1,  # Ultra X7 358H 级边缘机 (NPU 50 TOPS / iGPU 123 TOPS)
    "compute_thor": 2.5,  # Jetson AGX Thor T5000 开发套件 ($3,499 口径)
    "frame_dual": 3.2, "frame_single": 2.6, "frame_quick": 4.0,
    "elec_dual": 1.8, "elec_single": 1.3, "elec_expert": 2.0,
    "harness_dual": 0.5, "harness_single": 0.35, "harness_expert": 0.6,
    "assemble_dual": 2.4, "assemble_single": 1.8, "assemble_expert": 3.0,
    "pack_dual": 0.6, "pack_single": 0.45, "pack_expert": 0.8,
}

TIERS = {
    "精细操作（双臂）": {"target_wan": 30.0, "items": [
        ("六轴协作臂", 2, P["arm6"]), ("精对位夹爪+力觉", 2, P["gripper"]),
        ("手臂相机", 3, P["cam_arm"]), ("算力单元", 1, None),
        ("结构/台面/工装", 1, P["frame_dual"]), ("电控与安全", 1, P["elec_dual"]),
        ("线束气路", 1, P["harness_dual"]), ("装配标定调试", 1, P["assemble_dual"]),
        ("包装备件", 1, P["pack_dual"])]},
    "集出版（单臂）": {"target_wan": 22.0, "items": [
        ("六轴协作臂", 1, P["arm6"]), ("精对位夹爪+力觉", 1, P["gripper"]),
        ("相机", 2, P["cam_arm"]), ("算力单元", 1, None),
        ("结构/台面/工装", 1, P["frame_single"]), ("电控与安全", 1, P["elec_single"]),
        ("线束气路", 1, P["harness_single"]), ("装配标定调试", 1, P["assemble_single"]),
        ("包装备件", 1, P["pack_single"])]},
    "专家版（双臂+力控装配）": {"target_wan": 35.0, "items": [
        ("六轴协作臂", 2, P["arm6"]), ("精对位夹爪+力觉", 2, P["gripper"]),
        ("六维力传感器", 2, P["ft6"]), ("相机", 3, P["cam_arm"]), ("3D 视觉", 1, P["cam3d"]),
        ("算力单元", 1, None), ("结构/快换工装", 1, P["frame_quick"]),
        ("电控与安全", 1, P["elec_expert"]), ("线束气路", 1, P["harness_expert"]),
        ("装配标定调试", 1, P["assemble_expert"]), ("包装备件", 1, P["pack_expert"])]},
}

# 产能与成本口径 (取自技术手册在役数字)
CAP = {"uph": 314, "h_per_year": 8000, "util": 0.85,
       "labor_yuan_per_piece": 0.36, "machine_yuan_per_piece": 0.105}


def build(compute_key: str) -> dict:
    out = {}
    for name, t in TIERS.items():
        rows, tot = [], 0.0
        for label, qty, unit in t["items"]:
            u = P[compute_key] if unit is None else unit
            amt = qty * u
            tot += amt
            rows.append({"item": label, "qty": qty, "unit_wan": u, "amount_wan": round(amt, 2)})
        tgt = t["target_wan"]
        out[name] = {"rows": rows, "bom_wan": round(tot, 2), "target_wan": tgt,
                     "margin_vs_target_wan": round(tgt - tot, 2),
                     "as_cost": {"ok": tot <= tgt,
                                 "headroom_pct": round(100 * (tgt - tot) / tgt, 1)},
                     "as_price": {"gross_margin_pct": round(100 * (tgt - tot) / tgt, 1),
                                  "verdict": ("售价口径下毛利 %.1f%%" % (100 * (tgt - tot) / tgt))}}
    return out


def roi(price_wan: float, uph: float) -> dict:
    pieces = uph * CAP["h_per_year"] * CAP["util"]
    labor = pieces * CAP["labor_yuan_per_piece"] / 1e4        # 万元/年
    machine = pieces * CAP["machine_yuan_per_piece"] / 1e4
    net = labor - machine
    return {"pieces_per_year": int(pieces), "labor_saving_wan": round(labor, 1),
            "machine_cost_wan": round(machine, 1), "net_saving_wan": round(net, 1),
            "payback_years": round(price_wan / net, 2) if net > 0 else None}


def main() -> int:
    rep = {"ts": time.strftime("%F %T"), "price_basis": "2026 参考价 (中值)", "unit_prices": P,
           "capacity": CAP, "tiers": {}}
    for ck, cname in (("compute_550c", "550C(Intel)"), ("compute_thor", "Thor T5000")):
        rep["tiers"][cname] = build(ck)
    # 回本 (按各档目标价作售价口径)
    # 单臂产能按 180 件/h (双倍工时), 双臂 314 件/h (在役实测)
    uph_map = {"精细操作（双臂）": CAP["uph"], "集出版（单臂）": 180.0,
               "专家版（双臂+力控装配）": CAP["uph"]}
    rep["roi"] = {n: {**roi(t["target_wan"], uph_map[n]), "uph": uph_map[n]}
                  for n, t in TIERS.items()}
    rep["cost_down"] = {
        "专家版超限": "550C 口径 BOM 36.85 万 > 35 万目标 1.85 万 (5.3%); Thor 口径 38.25 万 > 3.25 万 (9.3%)",
        "路径A": "六维力只装在插入臂 (省 3.2 万) ⇒ 33.65 万 (550C) / 35.05 万 (Thor), 满足目标",
        "路径B": "3D 视觉改用现有手臂相机 + 深度反投影 (省 2.8 万) ⇒ 34.05 / 35.45 万",
        "路径C": "结构件小批量化 + 工装标准化 (省 0.8~1.2 万)",
        "不建议": "为压成本把算力单元退回无 NPU 的工控机: 实测 YOLO 从 2.9 ms 变 98 ms, 100 ms 拍直接吃掉 98%",
    }
    json.dump(rep, open(os.path.join(OUT, "BOM_COST.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    L = ["# BOM 与成本分析 (三档)\n",
         "生成 %s · 单价口径：%s · 不含输送线/立库/MES/厂房改造\n" % (rep["ts"], rep["price_basis"])]
    for cname, tiers in rep["tiers"].items():
        L.append("## 算力平台：%s\n" % cname)
        L.append("| 档位 | BOM 合计 | 目标成本 | 余量 | 成本口径 | 若当售价毛利 |")
        L.append("|---|---:|---:|---:|---|---:|")
        for n, t in tiers.items():
            L.append("| %s | %.2f 万 | %.1f 万 | %+.2f 万 | %s (%.1f%%) | %.1f%% |"
                     % (n, t["bom_wan"], t["target_wan"], t["margin_vs_target_wan"],
                        "在限内" if t["as_cost"]["ok"] else "超限",
                        t["as_cost"]["headroom_pct"], t["as_price"]["gross_margin_pct"]))
        L.append("")
        t = tiers["精细操作（双臂）"]
        L.append("### 明细 · 精细操作（双臂）\n")
        L.append("| 项 | 数量 | 单价(万) | 金额(万) |")
        L.append("|---|---:|---:|---:|")
        for r in t["rows"]:
            L.append("| %s | %d | %.2f | %.2f |" % (r["item"], r["qty"], r["unit_wan"], r["amount_wan"]))
        L.append("")
    L.append("## 回本测算（按目标价作售价口径）\n")
    L.append("产能口径：%d 件/h × %d h/年 × 稼动率 %.0f%% = %s 件/年；人工成本 %.2f 元/件，"
             "设备单件成本 %.3f 元/件\n"
             % (CAP["uph"], CAP["h_per_year"], CAP["util"] * 100,
                format(list(rep["roi"].values())[0]["pieces_per_year"], ","),
                CAP["labor_yuan_per_piece"], CAP["machine_yuan_per_piece"]))
    L.append("| 档位 | 产能(件/h) | 年净省 | 回本 |")
    L.append("|---|---:|---:|---:|")
    for n, r in rep["roi"].items():
        L.append("| %s | %d | %.1f 万元 | %s 年 |" % (n, r["uph"], r["net_saving_wan"], r["payback_years"]))
    L.append("\n## 专家版超限的降本路径\n")
    for k, v in rep["cost_down"].items():
        L.append("- **%s**：%s" % (k, v))
    L.append("\n> 口径提醒：目标价当成本 / 当售价 两种读法结论相反，签合同前必须二选一说清；"
             "毛利率 <15% 的档位不建议接（软件迭代与备件会吃掉）。")
    md = "\n".join(L)
    open(os.path.join(OUT, "BOM_COST.md"), "w", encoding="utf-8").write(md)
    print(md[:2600])
    print("\n===> %s" % os.path.join(OUT, "BOM_COST.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
