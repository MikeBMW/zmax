#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报价/ROI 边界矩阵 —— 只读唯一依据, 不写盘。

用法:
  python3 quote_matrix.py                       # 用默认唯一依据 + 内置假设
  python3 quote_matrix.py --labor 9,12,15 --margin 0.30 --manual-ct 9
  python3 quote_matrix.py --json                # 给页面/文档吃

口径:
  eta      = eta_struct(task) * success * uptime * min(1, manual_ct / ct)
  annual   = eta * heads * labor_per_year
  opex     = capex * maintenance_rate + retrain_per_year
  net      = annual - opex
  payback  = (capex + nre) / net
  floor    = mycost / (1 - margin)          mycost = hw*stations + sw_cost + nre
  ceiling  = net * target_payback_years
"""
import argparse
import json
import os
import sys

W = 1e4


def m(x):
    return "%.1f" % (x / W)


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def _default_truth():
    root = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
    cost = _first_existing([
        os.path.join(root, "config/platform/zmax_cost_model.json"),
        os.path.join(root, "defaults/config/platform/zmax_cost_model.json"),
    ])
    bom = _first_existing([
        os.path.join(root, "config/platform/zmax_project_bom.json"),
        os.path.join(root, "defaults/config/platform/zmax_project_bom.json"),
    ])
    return cost, bom


# 任务配置: (工位数, 班次, 人/班, 型号数, eta_struct)
TASKS = {
    "1工位·1型号·1班": (1, 1, 1, 1, 0.85),
    "1工位·1型号·2班": (1, 2, 1, 1, 0.80),
    "1工位·12型号·2班": (1, 2, 1, 12, 0.65),
    "3工位·12型号·2班": (3, 2, 1, 12, 0.65),
    "3工位·12型号·3班": (3, 3, 1, 12, 0.62),
}

# 性能配置: (CT s, 成功率, uptime) —— 阶段目标值, 不是实测
PERF = {
    "EVT": (22.5, 0.90, 0.85),
    "DVT": (8.0, 0.95, 0.92),
    "PVT": (3.15, 0.99, 0.96),
}

# 模型配置: 档位 -> (域控价, 软件价, 复训万/年)。档位系数未入唯一依据前按假设处理。
MODEL = {
    "550A": (35000, 120000, 2.0),
    "550B": (55000, 160000, 3.0),
    "550C": (55000, 200000, 4.0),
}

SW_COST = 60000.0          # 软件研发摊销 (假设)
NRE_BASE = 12.0 * W        # 实施基线 (假设)
NRE_PER_VARIANT = 2.0 * W  # 每型号实施 (假设)
NRE_STATION_GROWTH = 0.15  # 每多一个工位的实施增幅 (假设)


def hw_per_station(cost_model, compute_price):
    total = 0.0
    for item in cost_model.get("hardware") or []:
        price = float(item.get("price") or 0)
        if item.get("item") == "域控":
            price = float(compute_price)
        total += price
    return total


def estimate(cost_model, bom, model, task, perf, manual_ct, labor, margin, target_pb):
    compute_price, software, retrain = MODEL[model]
    stations, shifts, per_shift, variants, eta_struct = TASKS[task]
    ct, success, uptime = PERF[perf]

    hw = hw_per_station(cost_model, compute_price)
    capex = hw * stations + software
    nre = (NRE_BASE + NRE_PER_VARIANT * variants) * (1 + NRE_STATION_GROWTH * (stations - 1))
    headcount = stations * shifts * per_shift
    eta = eta_struct * success * uptime * min(1.0, manual_ct / ct)
    annual = eta * headcount * labor * W
    maintenance = float((bom.get("roi") or {}).get("maintenance_rate", 0.05))
    opex = capex * maintenance + retrain * W
    net = annual - opex
    mycost = hw * stations + SW_COST + nre
    floor = mycost / (1 - margin)
    ceiling = net * target_pb
    return {
        "model": model, "task": task, "perf": perf, "labor": labor,
        "eta": round(eta, 4), "headcount": headcount,
        "annual": round(annual, 2), "opex": round(opex, 2), "net": round(net, 2),
        "capex": round(capex, 2), "nre": round(nre, 2),
        "payback": round((capex + nre) / net, 2) if net > 0 else None,
        "mycost": round(mycost, 2), "floor": round(floor, 2), "ceiling": round(ceiling, 2),
        "deal": bool(floor <= ceiling),
    }


def main():
    ap = argparse.ArgumentParser(description="报价/ROI 边界矩阵 (只读唯一依据)")
    ap.add_argument("--cost-model", default=None)
    ap.add_argument("--bom", default=None)
    ap.add_argument("--manual-ct", type=float, default=9.0, help="人工单颗 CT (假设)")
    ap.add_argument("--labor", default="9,12,15", help="人力成本 万/人年, 逗号分隔")
    ap.add_argument("--margin", type=float, default=0.30, help="我方目标毛利率")
    ap.add_argument("--target-payback", type=float, default=2.0, help="客户目标回本年限")
    ap.add_argument("--model", default="550B")
    ap.add_argument("--perf", default="PVT")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cost_path, bom_path = _default_truth()
    cost_path = args.cost_model or cost_path
    bom_path = args.bom or bom_path
    if not cost_path or not bom_path:
        print("⛔ 找不到唯一依据, 用 --cost-model/--bom 指定", file=sys.stderr)
        return 2

    cost_model = json.load(open(cost_path, encoding="utf-8"))
    bom = json.load(open(bom_path, encoding="utf-8"))
    labors = [float(x) for x in args.labor.split(",") if x.strip()]

    rows = []
    for task in TASKS:
        for labor in labors:
            rows.append(estimate(cost_model, bom, args.model, task, args.perf,
                                 args.manual_ct, labor, args.margin, args.target_payback))

    if args.json:
        print(json.dumps({"cost_model": cost_path, "bom": bom_path, "rows": rows},
                         ensure_ascii=False, indent=1))
        return 0

    print("唯一依据: %s" % cost_path)
    print("      %s" % bom_path)
    print("假设: 人工CT %.1fs · 结构人效 %s · NRE %.0f万+%.0f万/型号 · 软件摊销 %.0f万 · 毛利 %.0f%% · 客户目标 %.0f年"
          % (args.manual_ct, "/".join("%.2f" % TASKS[k][4] for k in TASKS),
             NRE_BASE / W, NRE_PER_VARIANT / W, SW_COST / W, args.margin * 100, args.target_payback))
    print("性能: %s (阶段目标值, 非实测)" % args.perf)
    print("")
    print("%-18s %-6s %6s %6s %6s %6s %7s %s"
          % ("配置", "人力", "净万", "成本万", "底价万", "上限万", "回本年", "判定"))
    for row in rows:
        print("%-18s %-6.0f %6s %6s %6s %6s %7s %s"
              % (row["task"], row["labor"], m(row["net"]), m(row["mycost"]),
                 m(row["floor"]), m(row["ceiling"]),
                 ("%.2f" % row["payback"]) if row["payback"] is not None else "—",
                 "可谈" if row["deal"] else "空区间"))
    print("")
    print("提示: 单工位单班在 9~12 万/人年 + 30% 毛利下通常空区间; 先找可谈窗口再报价。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
