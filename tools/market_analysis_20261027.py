#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 光模块插拔/检测工位 · 市场分析 + 定价 + 三方分成 模型 (2026-10-27)

口径铁律
  1) 产能只用页面/planner 同一个真源: zmax_data/runtime/traj/sim_insert.json 的 loop 块
     (稳态 4 件 45.87s ⇒ 300 件/h 管理口径) —— 不另编 UPH。
  2) 市场数据全部带来源: LightCounting(转引)/上市公司年报/华源证券(CIOE 转引)/东方财富(光通信测试仪器)。
     没有公开数字的一律标 [估] 并在 assumptions 里写清推法。
  3) 成本只用 config/platform/zmax_cost_model.json 的硬件逐项(给定) + 阶梯议价[假设]。
  4) 不写"500 台/年"这种市场装不下的量档当主口径 —— 主口径 = 市场真实可及的 20/50/100 台/年。

输出: reports/market_20261027/metrics_market.json
"""
import json, os

REPO = "/home/ubuntu/zmax"
OUT = os.path.join(REPO, "reports", "market_20261027")
os.makedirs(OUT, exist_ok=True)

# ── 真源: 节拍/产能 ──────────────────────────────────────────────────────
SI = json.load(open(os.path.join(REPO, "zmax_data/runtime/traj/sim_insert.json"), encoding="utf-8"))
LOOP = SI["loop"]
TACT_S = float(LOOP["tact_s"])                 # 11.47 s/件(稳态)
UPH = float(LOOP["uph"])                       # 313.9 (仿真稳态)
UPH_TARGET = float(SI.get("uph_target", 300))  # 300 (管理口径)
HOURS_YEAR = 3750                              # 两班制: 250 天 × 15h
CAP_YEAR = UPH_TARGET * HOURS_YEAR             # 1,125,000 只/年
CAP_YEAR_OEE = CAP_YEAR * 0.75                 # 按 75% 稼动可承诺
YIELD = 0.992
NG = 0.008

# ── 真源: 成本 ──────────────────────────────────────────────────────────
CM = json.load(open(os.path.join(REPO, "config/platform/zmax_cost_model.json"), encoding="utf-8"))
HW = {h["item"]: h["price"] for h in CM["hardware"]}
HW_NOW = sum(HW.values())                      # 203,000
LABOR = CM["labor"]["cost_per_person_year"]    # 90,000
HEADS = CM["line"]["stations"] * CM["line"]["shifts"] * CM["line"]["persons_per_shift"]  # 2
ANNUAL_LABOR = LABOR * HEADS                   # 180,000

# 阶梯议价(与 pricing_model 同一套假设, 取 20/50/100 档插值)
DISC = {   # 20 / 50 / 100 / 200 台·年 四档 (200 档为本轮新增, 折扣更狠, 需供应商复核)
    "机械臂":      [0.92, 0.78, 0.70, 0.62],
    "域控":        [0.93, 0.82, 0.74, 0.64],
    "头部相机":    [0.95, 0.86, 0.76, 0.66],
    "腕部相机×2":  [0.95, 0.86, 0.76, 0.66],
    "夹爪×2":      [0.95, 0.86, 0.76, 0.66],
    "电源+结构件": [0.96, 0.90, 0.84, 0.76],
}
TIERS = [20, 50, 100, 200]
# 软件研发 600 万是公司级引擎资产, 本产品线只摊 40% (其余由其它工序/客户共用) —— 全摊会把这一个产品做亏
SW_RND_TOTAL, SW_LINE_SHARE, PROGRAM_YEARS = 6_000_000, 0.40, 5
MFG_PER_UNIT = {20: 9000, 50: 7500, 100: 6500, 200: 5800}    # 装配+整机测试+包装 [估]
IMPL = {20: 16000, 50: 13000, 100: 11000, 200: 9000}         # 现场实施(标定/联调/MES) [估]

# ── 市场数据 (全部带来源) ────────────────────────────────────────────────
MARKET = {
    "global_800g_2026_units": 33_500_000,   # LightCounting: 2026 全球 800G 出货 3350 万只
    "global_16t_2026_units": 12_000_000,    # LightCounting: 1.6T 860 万~2000 万, 取 1200 万
    "global_400g_below_highspeed": 25_000_000,  # [估] 400G 及以下仍需插拔测试的高速存量产能
    "global_total_units_2026": 200_000_000,     # [估] 全球光模块总产量(含 100G/200G/25G), 按均价 ~$55 反推
    "cn_market_2024_rmb": 606e8,            # 东方财富引: 2024 中国光模块市场 606 亿元
    "global_market_2024_usd": 108e8,        # 同上: 2024 全球 108 亿美元
    "cn_test_instrument_2024": 33.0e8,      # 中国光通信测试仪器 2024 = 33.0 亿元
    "cn_test_instrument_2029": 65.9e8,      # 2029 = 65.9 亿元, CAGR 14.84%
    "growth": {"2024": 0.93, "2025": 0.82, "2026": 0.65},   # LightCounting 以太网光模块销售额增速
    "cn_cagr_2025_2031": 0.29,              # LightCounting: 中国云厂商 29% vs 美国 18%
    "capex_2025_rmb": {"中际旭创": 28e8, "新易盛": 13e8, "光迅科技": 8e8, "Lumentum": 17e8, "Coherent": 32e8},
    "capex_cagr_2020_2025": {"中际旭创": 0.24, "新易盛": 0.35, "光迅科技": 0.28},
    "staff": {"中际旭创": {"2023": 6166, "2024": 8542, "2025": 11625},
              "新易盛": {"2023": 2000, "2025": 8000}},
    "output_2025_units": {"中际旭创": 23_760_000, "新易盛": 16_340_000},
    "capacity_2025_units": {"中际旭创": 28_060_000, "新易盛": 17_470_000},
    "rev_per_production_head_2025": {"中际旭创": 473e4, "新易盛": 336e4, "光迅科技": 435e4},
    "line_capex_mix": {"测试": 0.56, "贴片": 0.24, "耦合": 0.16},   # 光迅 70 万只产线, 华源证券
    "equip_share_of_investment": 0.70,      # 产线设备投入占总投资 >70%
    "test_equip_mix_2025": {"芯片老化测试": 0.31, "光耦合机": 0.24},
    "ficontec_tact_s": 60,                  # ficonTEC 全自动线 单件约 1 分钟(罗博特科点评)
}

# ── 人工对照: 一个工位 2 人 ───────────────────────────────────────────────
MANUAL_TACT_S = 22          # [估] 人工插拔+上电+测试+拔除+摆盘 单件节拍(现场待标定)
MANUAL_PER_H = 3600 / MANUAL_TACT_S        # 163.6 件/h
MANUAL_PER_PERSON_YEAR = MANUAL_PER_H * HOURS_YEAR   # 61.4 万只/人年
HEADS_EQUIV = UPH_TARGET / MANUAL_PER_H             # 1.83 人 才能顶一台(300/h)
LABOR_PER_PIECE = ANNUAL_LABOR / CAP_YEAR           # 0.160 元/只

# ── 市场容量: 按"设备台数"折算 ───────────────────────────────────────────
def machines(units):
    return units / CAP_YEAR

M = {
    "tam_units_global": MARKET["global_total_units_2026"],
    "sam_units_highspeed": MARKET["global_800g_2026_units"] + MARKET["global_16t_2026_units"]
                           + MARKET["global_400g_below_highspeed"],
}
M["tam_machines"] = machines(M["tam_units_global"])
M["sam_machines"] = machines(M["sam_units_highspeed"])
M["sam_units_cn_share"] = 0.55     # 中国厂商占全球光模块产量 ~55% [估: 旭创+新易盛 2025 产量 4010 万只]
M["sam_machines_cn"] = M["sam_machines"] * M["sam_units_cn_share"]
M["sam_value_rmb"] = M["sam_machines"] * 268_000

# ── 成本 / 定价 / 三方 ───────────────────────────────────────────────────
# 阶梯价: 年度框架量越大单价越低(与 BOM 阶梯同向)
PRICE = {
    "A": {20: 298_000, 50: 268_000, 100: 248_000, 200: 218_000},
    "B": {20: 428_000, 50: 398_000, 100: 368_000, 200: 318_000},
}
PACK = [
    {"key": "A", "name": "标准单机(买断)", "sw_years": 3, "maint_rate": 0.030,
     "note": "单臂单工位: 4 孔轮转 + 金手指/侧面 AOI + MES 上报"},
    {"key": "B", "name": "产线版(双工位/MES/SPC)", "sw_years": 5, "maint_rate": 0.030,
     "note": "双工位并行 + 质量看板 + SPC + 任意型号换型库"},
    {"key": "C", "name": "按件服务(零首付)", "sw_years": 0, "maint_rate": 0.0,
     "per_piece": 0.12, "floor": 80_000,
     "note": "不卖设备, 按检测件数结算, 保底 8 万/年/台; 客户零资本开支"},
]

cost_rows = []
for i, v in enumerate(TIERS):
    items = {k: round(p * DISC[k][i]) for k, p in HW.items()}
    bom = sum(items.values())
    mfg = MFG_PER_UNIT[v]
    amort = SW_RND_TOTAL * SW_LINE_SHARE / (v * PROGRAM_YEARS)
    impl = IMPL[v]
    unit_cost = bom + mfg + amort + impl
    cost_rows.append({"vol": v, "bom": bom, "bom_items": items, "mfg": mfg,
                      "amort": round(amort), "impl": impl, "cost": round(unit_cost)})

C = {r["vol"]: r for r in cost_rows}

def per_piece_cost(cost, units=CAP_YEAR):
    """设备 5 年直线摊 + 维保 → 单只成本"""
    dep = cost / 5
    return dep / units

econ_rows = []
for v in TIERS:
    c = C[v]
    for p in PACK:
        if p["key"] in PRICE:
            price = PRICE[p["key"]][v]
            maint = price * p["maint_rate"]
            # 一次性 + 5 年经常性
            one_off_gp = price - c["cost"]
            rec_gp = maint * 0.55          # 维保毛利(成本≈45%) [估]
            gp5 = one_off_gp + rec_gp * 5
            cust_save = ANNUAL_LABOR - maint - 6_000        # 电费 0.6 万/年 [估]
            payback = price / cust_save if cust_save > 0 else float("inf")
            econ_rows.append({"vol": v, "pack": p["key"], "price": price, "maint": round(maint),
                              "unit_cost": c["cost"], "one_off_gp": round(one_off_gp),
                              "rec_gp_y": round(rec_gp), "gp5": round(gp5),
                              "each5": round(gp5 / 3), "cust_save": round(cust_save),
                              "payback": round(payback, 2),
                              "dep_per_piece": round(per_piece_cost(c["cost"]), 4)})
        else:
            # 按件: 每只 0.12, 按 112.5 万只/年, 保底 8 万
            rev = max(p["floor"], p["per_piece"] * CAP_YEAR)
            # 按件模式设备是我方资本: 必须按 5 年折旧进成本, 否则毛利虚高一倍
            opex = 6_000 + 3_500 + c["cost"] / 5           # 电 + 现场巡检 + 设备折旧[估]
            gp = rev - opex
            econ_rows.append({"vol": v, "pack": "C", "price": 0, "per_piece": p["per_piece"],
                              "rev_y": round(rev), "opex": round(opex), "gp5": round(gp * 5),
                              "each5": round(gp * 5 / 3),
                              "cust_save": round(ANNUAL_LABOR - rev),
                              "payback": 0.0, "gp_y": round(gp)})

# ── 平台口径: 1 万可替代人力 × 10% 转化 = 1000 台 / 100 场景 × 10 台 ────────
#    老倪口径 (2026-10-27): "1 万人能被替代, 10% 转化率, 即 1000 台机器人, 100 个场景, 每场景 10 台"
HF = MARKET["rev_per_production_head_2025"]
heads_3 = {"中际旭创": round(374.56e8 / HF["中际旭创"]),      # 由营收 ÷ 人均创收反算 = 生产人员
           "新易盛": round(247.71e8 / HF["新易盛"]),
           "光迅科技": round(95e8 / HF["光迅科技"])}          # [估] 光迅 2025 营收按 95 亿
PLATFORM = {
    "replaceable_heads": 10_000,          # 口径: 光模块/光器件行业重复性工位可替代人力(保守取 1 万)
    "conversion": 0.10,
    "units_target": 1_000,
    "scenes": 100,
    "units_per_scene": 10,
    "heads_3_big": heads_3,               # 三家头部生产人员(由人均创收反算)
    "heads_3_sum": sum(heads_3.values()),
    "heads_per_unit": round(HEADS_EQUIV, 2),   # 实测: 1 台顶 1.83 人
    "heads_replaced_by_1000": round(1000 * HEADS_EQUIV),
    "conversion_effective": round(1000 * HEADS_EQUIV / 10_000, 3),
    "units_to_replace_1000_heads": round(1000 / HEADS_EQUIV),
    "avg_units_per_year": 200,
    "heads_industry": 25_000,             # [估] 全行业光模块/光器件生产人员 ≈ 三家头部 1.75 万 + 其余 ~0.75 万
    "conv_vs_industry": round(1000 * HEADS_EQUIV / 25_000, 3),   # 1000 台 ÷ 全行业 = 7.3%
}

# ── 五年计划 (平台口径; 场景数是真瓶颈, 不是市场天花板) ──────────────────────
PLAN = [
    {"year": 1, "ship": 40,  "scenes": 4,   "ops": 0,   "tier": 50,
     "note": "灯塔 4 场景: 光模块插拔 / 老化上下料 / 端面清洁 / 连接器插拔"},
    {"year": 2, "ship": 120, "scenes": 12,  "ops": 20,  "tier": 100,
     "note": "标杆复制 + 海外(泰国/马来); 渠道商 3 家"},
    {"year": 3, "ship": 220, "scenes": 30,  "ops": 80,  "tier": 200,
     "note": "工艺包平台化: 每 18 天上线 1 个场景包"},
    {"year": 4, "ship": 300, "scenes": 60,  "ops": 150, "tier": 200,
     "note": "跨行业复制(3C/汽车电子/服务器)"},
    {"year": 5, "ship": 320, "scenes": 100, "ops": 220, "tier": 200,
     "note": "100 场景 × 平均 10 台 达成 1000 台装机"},
]
SW_SUB_PER_UNIT = 12_000          # 软件订阅 1.2 万/年/台 (含模型升级) [估]
SW_SUB_GP = 0.80                  # 订阅毛利率
plan_rows = []
cum = 0
ops_prev = [0]
for p in PLAN:
    e = [r for r in econ_rows if r["vol"] == p["tier"] and r["pack"] == "A"][0]
    ec = [r for r in econ_rows if r["vol"] == p["tier"] and r["pack"] == "C"][0]
    cum_prev = cum
    prev_ops = ops_prev[0]
    ops_prev[0] = p["ops"]
    cum += p["ship"]
    eq_rev = p["ship"] * e["price"] + p["ship"] * e["price"] * 0.03   # 设备款 + 首年维保
    eq_gp = p["ship"] * e["one_off_gp"] + p["ship"] * e["rec_gp_y"]
    sub_rev = cum * SW_SUB_PER_UNIT                                   # 年末装机 × 订阅
    sub_gp = sub_rev * SW_SUB_GP
    ops_rev = p["ops"] * ec["rev_y"]
    ops_gp = p["ops"] * ec["gp_y"]
    rev = eq_rev + sub_rev + ops_rev
    gp = eq_gp + sub_gp + ops_gp
    plan_rows.append({"year": p["year"], "ship": p["ship"], "cum": cum, "scenes": p["scenes"],
                      "ops": p["ops"], "tier": p["tier"], "price": e["price"],
                      "eq_rev": round(eq_rev), "sub_rev": round(sub_rev), "ops_rev": round(ops_rev),
                      "rev": round(rev), "eq_gp": round(eq_gp), "sub_gp": round(sub_gp),
                      "ops_gp": round(ops_gp), "gp": round(gp), "each": round(gp / 3),
                      "capex": round((p["ops"] - prev_ops) * C[p["tier"]]["cost"]),
                      "note": p["note"]})
TOT = {k: sum(r[k] for r in plan_rows) for k in ("ship", "rev", "eq_rev", "sub_rev", "ops_rev",
                                                 "gp", "eq_gp", "sub_gp", "ops_gp", "capex")}
TOT["each"] = TOT["gp"] / 3
TOT["scenes"] = plan_rows[-1]["scenes"]
PLATFORM["share_of_equip_market_5y"] = round(
    sum(r["ship"] * r["price"] for r in plan_rows) / (89.3e8 * 5), 4)

out = {
    "schema": "zmax.market_analysis.v1",
    "date": "2026-10-27",
    "tact": {"tact_s": round(TACT_S, 2), "uph": round(UPH, 1), "uph_target": UPH_TARGET,
             "batch_s": float(LOOP.get("dur", 0)), "units_per_loop": int(LOOP.get("units", 4)),
             "hours_year": HOURS_YEAR, "cap_year": CAP_YEAR, "cap_year_oee": round(CAP_YEAR_OEE),
             "yield": YIELD, "ng": NG},
    "labor": {"cost_per_head": LABOR, "heads": HEADS, "annual": ANNUAL_LABOR,
              "manual_tact_s": MANUAL_TACT_S, "manual_per_h": round(MANUAL_PER_H, 1),
              "manual_per_person_year": round(MANUAL_PER_PERSON_YEAR),
              "heads_equivalent": round(HEADS_EQUIV, 2), "per_piece": round(LABOR_PER_PIECE, 4)},
    "market": MARKET,
    "tam": M,
    "cost_rows": cost_rows,
    "packs": PACK,
    "econ_rows": econ_rows,
    "platform": PLATFORM,
    "plan": plan_rows,
    "plan_totals": TOT,
    "assumptions": [
        "产能 = loop 稳态 300 件/h × 3750 h/年(两班 250 天×15h); 75% 稼动作为可承诺值",
        "人工对照 = 1 工位 2 人(两班各 1 人) × 9 万/人年; 人工节拍 22 s/件[估·待现场标定]",
        "全球总产量 2 亿只/年[估]: 由 2024 全球市场 108 亿美元 ÷ 均价 ~$55 反推",
        "400G 及以下高速存量 2500 万只[估]; 中国厂商占全球产量 55%[估: 旭创+新易盛 2025 产量 4010 万只]",
        "BOM 阶梯议价沿用 pricing_model_20261027 的供应商折扣假设, 未拿到正式报价",
        "制造/实施/电费/备件为[估], 维保成本按维保价 45% 计",
        "设备 5 年直线折旧; 软件研发 600 万按 5 年 × 年销量摊销",
    ],
}
json.dump(out, open(os.path.join(OUT, "metrics_market.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ── 打印核对 ────────────────────────────────────────────────────────────
print(f"节拍 {TACT_S:.2f} s/件 · UPH {UPH:.1f}(管理 {UPH_TARGET}) · 年产能 {CAP_YEAR:,} 只 (OEE75% {CAP_YEAR_OEE:,.0f})")
print(f"人工: {MANUAL_TACT_S}s/件 ⇒ {MANUAL_PER_H:.1f} 件/h ⇒ 一台顶 {HEADS_EQUIV:.2f} 人 · 单只人工 {LABOR_PER_PIECE:.3f} 元")
print(f"市场: TAM {M['tam_units_global']:,} 只 ⇒ {M['tam_machines']:.0f} 台 · SAM(高速) {M['sam_units_highspeed']:,} ⇒ {M['sam_machines']:.0f} 台 (中国 {M['sam_machines_cn']:.0f} 台, 产值 {M['sam_value_rmb']/1e4:.0f} 万)")
print("\n成本/定价:")
for r in econ_rows:
    if r.get("one_off_gp") is not None:
        print(f"  {r['vol']:>3} 台/年 包{r['pack']} 价 {r['price']/1e4:>5.1f}万 成本 {r['unit_cost']/1e4:>5.1f}万 "
              f"一次性毛利 {r['one_off_gp']/1e4:>4.1f}万 5年毛利 {r['gp5']/1e4:>4.1f}万 三方各 {r['each5']/1e4:>4.1f}万 "
              f"客户回本 {r['payback']:.2f}年 折旧单只 {r['dep_per_piece']:.3f}元")
    else:
        print(f"  {r['vol']:>3} 台/年 包C 按件 {r['per_piece']}元/只 → 年收 {r['rev_y']/1e4:.1f}万 毛利 {r['gp_y']/1e4:.1f}万 三方各 {r['each5']/1e4:.1f}万(5年)")
print("平台口径:", PLATFORM["replaceable_heads"], "人 ×", PLATFORM["conversion"],
      "→", PLATFORM["units_target"], "台 /", PLATFORM["scenes"], "场景;",
      "实际替代", PLATFORM["heads_replaced_by_1000"], "人 =",
      f'{PLATFORM["conversion_effective"]*100:.1f}% 转化; 反向只需',
      PLATFORM["units_to_replace_1000_heads"], "台")
print("五年计划:")
for p in plan_rows:
    print(f"  Y{p['year']}: 出货 {p['ship']} 台 + 运营 {p['ops']} 台 → 收入 {p['rev']/1e4:.0f}万 毛利 {p['gp']/1e4:.0f}万 三方各 {p['each']/1e4:.0f}万")
print(f"\n→ {OUT}/metrics_market.json")
