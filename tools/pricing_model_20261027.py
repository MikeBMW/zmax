#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 光模块插拔工位 · 量产成本 / 定价 / 三方分成 模型 (2026-10-27)

真源:
  config/platform/zmax_cost_model.json   单套硬件逐项(给定) + 人工 + 产线口径
  zmax_data/runtime/traj/sim_insert.json (4 孔轮转: 先插满 → 拔一对·AOI·插同一对, 不插等待)
  右臂末端速度 = 左臂同口径: 左臂每循环 3.0s / 等效位移 1877mm ⇒ 626 mm/s
  夹爪动作同样按 120mm 等效折算(0.192s), 检测保持 0.8/0.5 s
输出: reports/pricing_20261027/metrics.json
"""
import json, os

REPO = "/home/ubuntu/zmax"
OUT = os.path.join(REPO, "reports", "pricing_20261027")
os.makedirs(OUT, exist_ok=True)

cm = json.load(open(os.path.join(REPO, "config/platform/zmax_cost_model.json"), encoding="utf-8"))
HW = {h["item"]: h["price"] for h in cm["hardware"]}
assert sum(HW.values()) == 203000, HW
NOW_PRICE = sum(HW.values()) + cm["software"]["price"]     # 现状套餐价 363,000

TIERS = [10, 100, 300, 500, 1000]
DISC = {   # [假设] 阶梯议价, 需供应商询价确认
    "机械臂":      [0.92, 0.78, 0.70, 0.66, 0.62],
    "域控":        [0.93, 0.82, 0.74, 0.70, 0.66],
    "头部相机":    [0.95, 0.86, 0.76, 0.72, 0.65],
    "腕部相机×2":  [0.95, 0.86, 0.76, 0.72, 0.65],
    "夹爪×2":      [0.95, 0.86, 0.76, 0.72, 0.65],
    "电源+结构件": [0.96, 0.90, 0.84, 0.80, 0.76],
}
SW_RND, PROGRAM_YEARS, AMORT_FLOOR = 6_000_000, 5, 60
IMPL = {10: 18000, 100: 13000, 300: 12000, 500: 11000, 1000: 10000}
MARGIN = {10: 0.35, 100: 0.38, 300: 0.40, 500: 0.40, 1000: 0.38}
LABOR = cm["labor"]["cost_per_person_year"]
HEADS = cm["line"]["stations"] * cm["line"]["shifts"] * cm["line"]["persons_per_shift"]
ANNUAL_SAVE = LABOR * HEADS
MAINT_RATE, SW_FEE, ETA = 0.03, 20000, 0.85
# 节拍真源 = /api/sim_insert (4 孔交替 + 60s 驻留): 稳态 30.0 s/个
_SI = json.load(open(os.path.join(REPO, "zmax_data/runtime/traj/sim_insert.json"), encoding="utf-8"))
TACT_TARGET = _SI["tact_steady_s"]                    # 目标口径(老倪: 跟左臂一样 3.00 s/个)
TACT_S = _SI.get("tact_reach_s") or TACT_TARGET       # 产能一律按「真机可达档」报, 不按目标档
BATCH_S = _SI.get("batch_reach_s") or _SI["total_t"]  # 14 个一批(可达档)
DWELL_S = _SI.get("dwell_required_s") or 0   # 0 = 本版不要求固定驻留(自然 19~62s)
N_HOLES = len(_SI["holes"])            # 4
HOURS_YEAR = 3750
TARGET_PAYBACK = 1.5

rows = []
for i, v in enumerate(TIERS):
    items = {k: round(p * DISC[k][i]) for k, p in HW.items()}
    bom = sum(items.values())
    amort = SW_RND / max(v * PROGRAM_YEARS, AMORT_FLOOR)
    impl = IMPL[v]
    cost = bom + amort + impl
    price_calc = cost / (1 - MARGIN[v])
    capped = price_calc > NOW_PRICE
    price = min(price_calc, NOW_PRICE)
    maint = price * MAINT_RATE
    pool = price - bom - amort                 # 毛利池(扣硬件+软件摊销)
    each = pool / 3
    ops_net = each - impl - maint              # 运营方扣现场实施与维保后
    sw_net = each + SW_FEE
    net = price + SW_FEE - bom - amort - impl - maint
    opex = maint + SW_FEE
    net_save = ANNUAL_SAVE * ETA - opex
    payback = price / net_save
    rows.append(dict(vol=v, bom=bom, bom_items=items, amort=round(amort), impl=impl,
                     cost=round(cost), price=round(price), capped=capped,
                     gross_margin=(price - cost) / price if price else 0,
                     maint=round(maint), pool=round(pool), each=round(each),
                     ops_net=round(ops_net), sw_net=round(sw_net),
                     net_save=round(net_save), payback=round(payback, 2),
                     floor35=round(cost / 0.65), ceiling=round(net_save * TARGET_PAYBACK),
                     npv5=round(-price + sum(net_save / 1.08 ** t for t in range(1, 6)))))

# 产能口径 = 「全流程 UPH」稳态循环块(两块相邻稳态轮次无缝平铺), 与页面浮层同一个数
_LOOP = _SI.get("loop") or {}
TACT_LOOP = float(_LOOP.get("tact_s") or TACT_S)
UPH_ACTUAL = float(_LOOP.get("uph") or (3600 / TACT_S))   # 仿真稳态(313.9)
# 定价/产能一律用老倪定的目标 300, 不用仿真值 314 —— 对外不夸大
UPH_TARGET = float(_SI.get("uph_target") or 300)
cap_h = UPH_TARGET
cap_year = cap_h * HOURS_YEAR
r500 = next(x for x in rows if x["vol"] == 500)
dep_unit = r500["price"] / (cap_year * 5)

PLAN = [10, 40, 100, 200, 300]
plan, cum = [], 0
for y, n in enumerate(PLAN, 1):
    tier = min(TIERS, key=lambda t: abs(t - n))
    r = next(x for x in rows if x["vol"] == tier)
    pool_tot = r["pool"] * n
    fee = cum * SW_FEE
    cum += n
    plan.append(dict(year=y, units=n, tier=tier, price=r["price"],
                     revenue=round(n * r["price"]), pool=round(pool_tot),
                     hw=round(pool_tot / 3), sw=round(pool_tot / 3 + fee),
                     ops=round(pool_tot / 3 - n * (r["impl"] + r["maint"])),
                     fee=fee, cum=cum))

model = dict(
    truth=dict(cost_model="config/platform/zmax_cost_model.json", hw_total=sum(HW.values()),
               sw_share=cm["software"]["price"], now_price=NOW_PRICE, labor=LABOR, heads=HEADS,
               annual_save=ANNUAL_SAVE, payback_now=round(NOW_PRICE / ANNUAL_SAVE, 2)),
    tact=dict(left=3.00, right=round(TACT_S, 2), overall=round(TACT_S, 2), bottleneck="右臂插拔",
              speed_profile=_SI.get("speed_profile"),
              batch_s=round(BATCH_S, 1), n_holes=N_HOLES, dwell_s=DWELL_S,
              dwell_natural=_SI.get("reach_dwell_s") or [_SI.get("dwell_min_s"), _SI.get("dwell_max_s")],
              cap_h=round(cap_h, 1), cap_year=round(cap_year),
              uph_actual=round(UPH_ACTUAL, 1), uph_target=UPH_TARGET,
              ng_ratio=_SI.get("ng_ratio"), yield_target=_SI.get("yield_target"),
              hours_year=HOURS_YEAR, dep_per_piece=round(dep_unit, 4)),
    rows=rows, plan=plan,
    assumptions=dict(sw_rnd=SW_RND, program_years=PROGRAM_YEARS, disc=DISC, impl=IMPL,
                     margin=MARGIN, maint=MAINT_RATE, sw_fee=SW_FEE, eta=ETA,
                     target_payback=TARGET_PAYBACK, npv_r=0.08),
)
json.dump(model, open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

print(f"节拍 左3.00/右{TACT_LOOP:.2f}s(循环) · {cap_h:.0f}个/h · {cap_year/1e4:.1f}万/年 · 折旧 {dep_unit:.3f}元/件")
print(f"{'台/年':>5} {'BOM':>8} {'摊销':>6} {'成本':>8} {'售价':>8} {'毛利%':>6} {'回本':>5} {'底价':>8} {'上限':>8} {'毛利池':>8} {'三方各':>7} {'运营净':>8}")
for r in rows:
    print(f"{r['vol']:>5} {r['bom']:>8,} {r['amort']:>6,} {r['cost']:>8,} {r['price']:>8,} "
          f"{r['gross_margin']*100:>5.0f}% {r['payback']:>5.2f} {r['floor35']:>8,} {r['ceiling']:>8,} "
          f"{r['pool']:>8,} {r['each']:>7,} {r['ops_net']:>8,}")
print()
for p in plan:
    print(f"Y{p['year']}: {p['units']:>3}台 · 营收 {p['revenue']/1e4:>5.0f}万 · 毛利池 {p['pool']/1e4:>5.0f}万 "
          f"· 硬件 {p['hw']/1e4:>5.0f} / 软件 {p['sw']/1e4:>5.0f} / 运营 {p['ops']/1e4:>5.0f} 万")
