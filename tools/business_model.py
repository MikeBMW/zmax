#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商业模式推导 (Z-MAX 唯一算法唯一依据, 无 Qt 依赖)。

为什么单独一个模块: 配置中心「🧩 商业模式」页、文档导出、以后的投标/立项材料
必须**同一套公式与同一个唯一依据**, 各写一份必然出现"页面 3 阶段价 42 万、文档 39 万"。

输入唯一依据 (只存输入, 派生值一律不落盘):
  config/platform/zmax_cost_model.json     ← 硬件/软件/人力/产线 (成本结构)
  config/platform/zmax_business_model.json ← 学习率/毛利率/回本年限/NRE/η 系数 (假设, 带标签)
成本与回本由 tools/cost_model.py 现算, 本模块只在它的结果上做商业模式推理。

口径 (老倪 2026-10-19 商业模式口径: 成本结构定定价空间 · 价值分配定利益格局 · 风险承担定推进速度):
  固定成本 = 软件研发 + NRE          (前期投入, 靠规模摊薄)
  变动成本 = 硬件 × 学习曲线         (每台交付消耗)
  人效 η   = η_struct × 成功率 × uptime × min(1, 人工CT / 机器CT)
  成交区间 floor = 单位成本/(1−目标毛利率) ≤ ceiling = 客户净年省 × 客户目标回本
  三阶段   S1 验证 0 元 (我方承担风险) → S2 试用 解决方案费 → S3 批量 学习曲线后单价

CLI:
  python3 tools/business_model.py                  # 终端三行结论 + 分层口径
  python3 tools/business_model.py --json           # 给页面/节点/文档吃
  python3 tools/business_model.py --md             # 对外提案 (markdown)
  python3 tools/business_model.py --md --out /tmp/bm.md
  python3 tools/business_model.py --eta 0.9 --units 20   # 覆盖单个假设试算 (不落盘)
"""
import argparse
import json
import math
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST_TRUTH = os.path.join(ROOT, "config", "platform", "zmax_cost_model.json")
TRUTH = os.path.join(ROOT, "config", "platform", "zmax_business_model.json")

DERIVED_KEYS = ("total", "unit_cost", "price", "floor", "ceiling", "payback", "margin",
                "phases", "mode", "recommend", "learning", "risk", "value_split")


def _w(x):
    """元 → 万元字符串"""
    return "%.1f" % (float(x) / 1e4)


def _r(x, n=2):
    return round(float(x) + 1e-12, n)


def load(path=None):
    with open(path or TRUTH, encoding="utf-8") as f:
        return json.load(f)


def inputs(d=None, **over):
    """把唯一依据的 inputs{value,...} 摊平成 {k: value}; over 覆盖用于试算 (不写盘)。"""
    d = d if d is not None else load()
    out = {k: v.get("value") for k, v in (d.get("inputs") or {}).items()}
    meta = {k: {"label": v.get("label"), "source": v.get("source"), "unit": v.get("unit")}
            for k, v in (d.get("inputs") or {}).items()}
    out.update({k: v for k, v in over.items() if v is not None})
    return out, meta


# ─────────────────────── 成本结构 ───────────────────────
def learning_factor(n, rate):
    """累计第 n 台的变动成本乘子: n^log2(1−rate)。n=1 → 1.0, 单调递减。"""
    n = max(1.0, float(n))
    return n ** (math.log2(max(1e-6, 1.0 - float(rate))))


def unit_cost(n, cost, i, planned=None):
    """定价口径单台成本 = 硬件×学习曲线 + 软件研发/计划摊销台数。

    研发按**计划台数**摊 (默认 amortize_units), 而不是按当前这一单摊 ——
    否则"试用 2 台"会被摊成 30 万/台研发, 报价直接失真。
    """
    n = max(1, int(n))
    hw = float(cost["hardware"])
    lr = float(i["learning_rate"])
    planned = int(planned or i["amortize_units"]) or 1
    return hw * learning_factor(n, lr) + float(i["software_dev_total"]) / max(1, planned)


def unit_cost_actual(n, cost, i):
    """实际规模口径单台成本 = 硬件×学习曲线 + 软件研发/实际台数 (规模阈值判据用)。"""
    n = max(1, int(n))
    hw = float(cost["hardware"])
    lr = float(i["learning_rate"])
    return hw * learning_factor(n, lr) + float(i["software_dev_total"]) / n


def eta_of(i):
    ct_ratio = min(1.0, float(i["ct_manual_s"]) / max(1e-9, float(i["ct_machine_s"])))
    return (float(i["eta_struct"]) * float(i["success_rate"])
            * float(i["uptime"]) * ct_ratio), ct_ratio


def layered(cost, i):
    """四层口径 (A 上限 / B +OPEX / C +人效 / D +NRE): 客户侧真实回本。"""
    eta, ct_ratio = eta_of(i)
    heads = int(cost["heads"])
    labor = float(cost["labor_per_person_year"])
    price = float(cost["total_first"])
    nre = float(i["nre_person_days"]) * float(i["person_day_price"])
    opex = float(i["maint_rate"]) * price + float(i["retrain_per_year"]) + float(i["software_fee_per_year"])

    a_save = heads * labor
    c_save = eta * heads * labor
    net_c = max(1e-9, c_save - opex)
    return {
        "eta": _r(eta, 4), "ct_ratio": _r(ct_ratio, 3),
        "heads": heads, "price": price, "nre": nre, "opex": opex,
        "a_save": a_save, "c_save": c_save, "net_c": net_c,
        "A_payback": _r(price / a_save) if a_save > 0 else None,
        "B_payback": _r(price / max(1e-9, a_save - opex)),
        "C_payback": _r(price / net_c),
        "D_payback": _r((price + nre) / net_c),
        "assumptions_A": "人效 1.0 · 零 OPEX · 零 NRE (上限参考, 不得对外当承诺)",
    }


def deal_range(cost, i, units=None):
    """成交区间: floor (我方成本+毛利) vs ceiling (客户净年省 × 目标回本)。"""
    lay = layered(cost, i)
    n = int(units or i["s3_units"])
    uc = unit_cost(n, cost, i)
    floor = uc / max(1e-9, 1.0 - float(i["target_margin"]))
    t = float(i["customer_target_payback"])
    # ceiling 与价格互相依赖 (OPEX 按售价比例): P = T(A−retrain−swfee) / (1 + T×maint)
    ceiling = (t * (lay["c_save"] - float(i["retrain_per_year"]) - float(i["software_fee_per_year"]))
               / (1.0 + t * float(i["maint_rate"])))
    ceiling = max(0.0, ceiling)
    return {
        "units": n, "unit_cost": uc, "floor": floor, "ceiling": ceiling,
        "ok": bool(floor <= ceiling),
        "gap": ceiling - floor,
        "gap_years": _r((ceiling - floor) / max(1e-9, lay["net_c"]) / max(1, n)) if lay["net_c"] > 0 else None,
        "rule": "可谈 ⟺ floor ≤ ceiling; 不成立改配置 (多工位/三班/换臂/降档), 不降价",
    }


# ─────────────────────── 规模阈值 ───────────────────────
def scale_threshold(cost, i, cap=500, ceiling=None):
    """把单价压到客户上限以内的最小台数 (规模阈值); 达不到返回 None。"""
    if ceiling is None:
        ceiling = deal_range(cost, i)["ceiling"]
    m = float(i["target_margin"])
    for n in range(1, cap + 1):
        price = unit_cost_actual(n, cost, i) / max(1e-9, 1.0 - m)
        if price <= ceiling:
            return {"units": n, "price": price, "ceiling": ceiling,
                    "unit_cost": unit_cost_actual(n, cost, i)}
    return None


def breakeven_configs(cost, i, stations=(1, 2, 3, 4, 6, 8), shifts=(1, 2, 3), cap_stations=8):
    """「改配置不降价」的量化出口: 哪些 工位×班 组合能让 floor ≤ ceiling。

    只用成本唯一依据里的人力单价与每班人数, 换 heads 重算客户净年省与上限。
    """
    labor = float(cost["labor_per_person_year"])
    persons = int(cost["persons_per_shift"])
    eta, _ = eta_of(i)
    m = float(i["target_margin"])
    t = float(i["customer_target_payback"])
    uc = unit_cost(int(i["s3_units"]), cost, i)
    floor = uc / max(1e-9, 1.0 - m)
    out = []
    for st in stations:
        for sh in shifts:
            heads = st * sh * persons
            eff = eta * heads * labor
            ceiling = max(0.0, (t * (eff - float(i["retrain_per_year"]) - float(i["software_fee_per_year"]))
                                / (1.0 + t * float(i["maint_rate"]))))
            out.append({"stations": st, "shifts": sh, "heads": heads,
                        "ceiling": ceiling, "ok": bool(floor <= ceiling),
                        "annual_save": eff, "floor": floor})
    return {"floor": floor, "rows": out,
            "ok_count": sum(1 for r in out if r["ok"]),
            "best": max(out, key=lambda r: r["ceiling"]) if out else None,
            "rule": "多工位摊软件与 NRE 是第一杠杆, 三班放大 heads 是第二"}


# ─────────────────────── 三阶段定价 ───────────────────────
def phases(cost, i):
    lay = layered(cost, i)
    lr = float(i["learning_rate"])
    m = float(i["target_margin"])
    s1, s2, s3 = int(i["s1_units"]), int(i["s2_units"]), int(i["s3_units"])

    s1_cost = float(cost["hardware"]) * learning_factor(1, lr) + lay["nre"]   # 增量现金: 样机 + 实施
    s2_unit = unit_cost(s2, cost, i)
    s2_price = s2_unit * s2 / max(1e-9, 1.0 - m) + lay["nre"]     # 试用: 成本 + 毛利 + 实施
    s3_unit = unit_cost(s3, cost, i)
    s3_price = s3_unit / max(1e-9, 1.0 - m)
    s3_marginal = float(cost["hardware"]) * learning_factor(s3, lr)   # 复制台边际成本
    return [
        {"stage": "S1 验证", "units": s1, "fee": 0.0, "basis": "不收费, 供应商承担验证风险",
         "ours_cost": s1_cost, "price": 0.0,
         "risk": "我方增量现金: 样机 + 实施 NRE = %s 万 (研发投入已发生, 不重复计)" % _w(s1_cost),
         "decision": "客户零决策压力; 换取现场数据与工艺确认"},
        {"stage": "S2 试用", "units": s2, "fee": s2_price, "basis": "按场景收解决方案费 (已验证价值)",
         "ours_cost": s2_unit * s2, "price": s2_price,
         "risk": "我方: 交付/培训/调试 %s 万 (内部化切换成本)" % _w(
             float(i["switch_cost_per_unit"]) * float(i["internalize_ratio"]) * s2),
         "decision": "客户只承担当期已验证范围内的费用"},
        {"stage": "S3 批量", "units": s3, "fee": s3_price, "basis": "按台批量报价, 规模摊薄固定成本",
         "ours_cost": s3_unit * s3, "price": s3_price, "unit_price": s3_price,
         "total": s3_price * s3 + lay["nre"], "marginal_cost": s3_marginal,
         "margin_copy": _r(1.0 - s3_marginal / max(1e-9, s3_price), 3),
         "risk": "我方: 产能与交付节奏; 客户: 规模承诺",
         "decision": "ROI 用真实运行数据测算, 不用假设数据"},
    ]


# ─────────────────────── 价值分配 / 风险 ───────────────────────
def copy_margin(cost, i, price=None, units=None):
    """复制台毛利 = 1 − 边际硬件成本/报价; 边际成本按学习曲线在批量台数处取值。"""
    n = int(units or i["s3_units"])
    marginal = float(cost["hardware"]) * learning_factor(n, i["learning_rate"])
    p = float(price if price is not None else cost["total_first"])
    return _r(1.0 - marginal / max(1e-9, p), 3), marginal


def value_split(cost, i):
    lay = layered(cost, i)
    price = float(cost["total_first"])
    ch = float(i["channel_share"])
    mg, marginal = copy_margin(cost, i, price)
    return [
        {"who": "客户", "item": "年净省 (扣 OPEX)", "amount": lay["net_c"],
         "note": "真实当期收益, 回本 %.1f 年" % (price / max(1e-9, lay["net_c"]))},
        {"who": "我方", "item": "单台毛利 (复制台)", "amount": price * (1 - ch) - marginal,
         "note": "售价 %s 万×(1−渠道) − 边际硬件 %s 万 = 毛利 %.0f%%"
                 % (_w(price), _w(marginal), mg * 100)},
        {"who": "渠道/集成商", "item": "分成", "amount": price * ch,
         "note": "渠道份额 %.0f%% (掌握客户关系这个稀缺环节)" % (ch * 100)},
        {"who": "稀缺环节", "item": "谁拿利润", "amount": None,
         "note": "力控臂是真成本大头 (%.1f 万/台) ⇒ 换臂比砍软件有效; 首台毛利≈0, 利润在复制台"
                 % (cost["hardware"] / 1e4)},
    ]


def risk_split(cost, i):
    return [
        {"phase": "S1 验证", "ours": "样机成本 + 实施 NRE + 工艺不确定性",
         "customer": "场地/来料/人员配合", "cash": "我方现金流出, 无收入"},
        {"phase": "S2 试用", "ours": "交付/培训/调试 (切换成本内部化)",
         "customer": "按场景付解决方案费", "cash": "覆盖成本 + 毛利"},
        {"phase": "S3 批量", "ours": "产能与交付节奏", "customer": "规模承诺与验收",
         "cash": "复制台边际毛利 + 软件年费"},
    ]


# ─────────────────────── 模式推荐 ───────────────────────
def modes(cost, i):
    lay = layered(cost, i)
    d = deal_range(cost, i)
    st = int(cost["stations"])
    price = float(cost["total_first"])
    sw = float(cost["software"])
    fee = float(i["software_fee_per_year"])
    eta = lay["eta"]
    mg, marginal = copy_margin(cost, i, price)
    out = []

    # ① 买断整线
    out.append({
        "mode": "买断 (整线)", "price": price * st, "per_unit": price,
        "cond": "工位 ≥3 且三班优先", "fit": st >= 3,
        "margin": mg,
        "note": "唯一能吃满复制毛利的形态 (当前工位 %d)" % st,
    })
    # ② 买断 + 软件订阅
    out.append({
        "mode": "买断 + 软件订阅", "price": price, "per_unit": price,
        "cond": "POC 期首选", "fit": True,
        "annual_fee": fee, "margin": mg,
        "note": "硬件按成本+验收对赌, 软件按年费 %s 万 ⇒ 降客户 CAPEX、给我方经常性收入" % _w(fee),
    })
    # ③ RaaS 按工位月费
    months = 36.0
    monthly = price / max(1e-9, (1 - float(i["target_margin"]))) / months
    out.append({
        "mode": "RaaS (按工位月费)", "price": monthly * months, "per_unit": price,
        "cond": "η ≥0.9 且多工位才自持; 否则交融资租赁", "fit": (eta >= 0.9 and st >= 3),
        "monthly": monthly, "margin": None,
        "note": "月费 %s 元/工位 (36 期回收, η=%.2f %s自持)" % (
            "{:,.0f}".format(monthly), eta, "可" if (eta >= 0.9 and st >= 3) else "不可"),
    })
    # ④ 按颗
    sec_per_year = float(i["work_hours_per_year"]) * 3600
    parts_year = sec_per_year / max(1e-9, float(i["ct_machine_s"]))
    labor_per_part = float(cost["labor_per_person_year"]) / max(1e-9, parts_year)
    out.append({
        "mode": "按颗计价", "price": None, "per_unit": None,
        "cond": "超大产量或多工位阶梯价", "fit": False,
        "per_part": labor_per_part, "parts_per_year": parts_year,
        "note": "人工成本 %.3f 元/颗 (CT=%.1fs 目标值, 未实测) ⇒ 单工位年流水 %s 万" % (
            labor_per_part, float(i["ct_machine_s"]), _w(labor_per_part * parts_year)),
    })
    # ⑤ 软件授权 / 能力包
    out.append({
        "mode": "软件授权 / 能力包", "price": sw, "per_unit": sw,
        "cond": "硬件客户自购 (被硬件成本拖死 / 竞标)", "fit": True,
        "margin": None,
        "note": "软件按 %s 万授权 (含三年), 硬件让给集成商; 毛利最高" % _w(sw),
    })

    rec = next((m["mode"] for m in out if m["mode"] == "买断 + 软件订阅"), out[0]["mode"])
    if st >= 3 and eta >= 0.9:
        rec = "买断 (整线)"
    elif not d["ok"]:
        rec = "软件授权 / 能力包"
    return {"options": out, "recommend": rec,
            "rule": "模式按 η 与工位数选, 不按客户偏好选"}


def derive(cost=None, d=None, **over):
    """全量推导。cost 为空则调 cost_model 现算 (保持与成本页同源)。"""
    if cost is None:
        import cost_model
        cost = cost_model.estimate(cost_model.load())
    i, meta = inputs(d, **over)
    lay = layered(cost, i)
    dr = deal_range(cost, i)
    th = scale_threshold(cost, i, ceiling=dr["ceiling"])
    ph = phases(cost, i)
    md = modes(cost, i)
    return {
        "schema": "zmax.business_model.derived",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "truth": {"cost": COST_TRUTH, "business": TRUTH,
                  "business_mtime": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(TRUTH)))
                  if os.path.exists(TRUTH) else "—"},
        "inputs": i, "labels": meta,
        "cost_structure": {
            "hardware_variable": float(cost["hardware"]),
            "software_price": float(cost["software"]),
            "fixed_total": float(i["software_dev_total"]) + lay["nre"],
            "software_dev": float(i["software_dev_total"]),
            "nre": lay["nre"],
            "learning_rate": float(i["learning_rate"]),
            "first_unit_cost": unit_cost(1, cost, i),
            "unit_cost_10": unit_cost(10, cost, i),
            "lc_10": _r(learning_factor(10, i["learning_rate"]), 3),
            "logic": "固定成本靠规模摊薄; 规模上不去, 单价下不来",
        },
        "layered": lay, "deal": dr, "threshold": th,
        "configs": breakeven_configs(cost, i),
        "phases": ph, "modes": md,
        "value_split": value_split(cost, i),
        "risk_split": risk_split(cost, i),
        "profit_where": "利润在复制台, 不在首台 (首台按成本价 + 验收对赌)",
        "summary_line": "客户真实回本 %s 年 (D 口径) · 成交%s · 推荐 %s" % (
            lay["D_payback"], "区间成立" if dr["ok"] else "区间不成立", md["recommend"]),
    }


# ─────────────────────── 导出 ───────────────────────
def to_tsv(e):
    L = ["项\t值"]
    L.append("人效 η\t%.3f" % e["layered"]["eta"])
    L.append("A 上限回本 (年)\t%s" % e["layered"]["A_payback"])
    L.append("C +人效回本 (年)\t%s" % e["layered"]["C_payback"])
    L.append("D +NRE 真实回本 (年)\t%s" % e["layered"]["D_payback"])
    L.append("底价 floor (元)\t%d" % int(e["deal"]["floor"]))
    L.append("客户上限 ceiling (元)\t%d" % int(e["deal"]["ceiling"]))
    L.append("成交区间\t%s" % ("成立" if e["deal"]["ok"] else "不成立"))
    for p in e["phases"]:
        L.append("%s (%d 台) 报价 (元)\t%d" % (p["stage"], p["units"], int(p["price"])))
    L.append("推荐模式\t%s" % e["modes"]["recommend"])
    return "\n".join(L) + "\n"


def to_markdown(e):
    lay, dr, th = e["layered"], e["deal"], e["threshold"]
    L = ["# Z-MAX 商业模式推导", "",
         "生成 %s ｜ 唯一依据 %s + %s" % (e["generated"],
                                     os.path.basename(e["truth"]["cost"]),
                                     os.path.basename(e["truth"]["business"])), "",
         "## 一、成本结构", "",
         "| 项 | 值 | 说明 |", "|---|---|---|",
         "| 变动成本 (硬件/台) | %s 万 | 随学习曲线下降 (10 台乘子 %s) |" % (
             _w(e["cost_structure"]["hardware_variable"]), e["cost_structure"]["lc_10"]),
         "| 固定成本 | %s 万 | 软件研发 %s 万 + NRE %s 万 |" % (
             _w(e["cost_structure"]["fixed_total"]),
             _w(e["cost_structure"]["software_dev"]), _w(e["cost_structure"]["nre"])),
         "| 首台单位成本 | %s 万 | 含全部固定成本 |" % _w(e["cost_structure"]["first_unit_cost"]),
         "| 10 台平均单位成本 | %s 万 | 规模摊薄后 |" % _w(e["cost_structure"]["unit_cost_10"]),
         "", "## 二、分层口径 (客户真实回本)", "",
         "| 口径 | 回本 | 含义 |", "|---|---|---|",
         "| A 上限 | %s 年 | %s |" % (lay["A_payback"], lay["assumptions_A"]),
         "| B +OPEX | %s 年 | 扣维护/复训/软件年费 |" % lay["B_payback"],
         "| C +人效 | %s 年 | η=%.3f (结构 %.2f × 成功率 %.2f × uptime %.2f × CT比 %.2f) |" % (
             lay["C_payback"], lay["eta"], e["inputs"]["eta_struct"], e["inputs"]["success_rate"],
             e["inputs"]["uptime"], lay["ct_ratio"]),
         "| **D +NRE** | **%s 年** | 客户真实投入 (含实施 %s 万) |" % (lay["D_payback"], _w(lay["nre"])),
         "", "## 三、成交区间", "",
         "- 底价 floor = 单位成本/(1−目标毛利 %.0f%%) = **%s 万**" % (
             e["inputs"]["target_margin"] * 100, _w(dr["floor"])),
         "- 客户上限 ceiling = 净年省 %s 万 × 目标回本 %.1f 年 = **%s 万**" % (
             _w(lay["net_c"]), e["inputs"]["customer_target_payback"], _w(dr["ceiling"])),
         "- 判定: **%s** (可谈空间 %s 万)" % ("成立" if dr["ok"] else "不成立", _w(dr["gap"])),
         "- 规模阈值: %s" % ("%d 台后单价进入客户区间" % th["units"] if th else "500 台内仍不成立 ⇒ 改配置, 不降价"),
         "", "### 改配置的量化出口 (不降价)", "",
         "| 工位 | 班 | 人 | 客户净年省 | ceiling | 判定 |", "|---|---|---|---|---|---|"]
    for r in e["configs"]["rows"]:
        L.append("| %d | %d | %d | %s 万 | %s 万 | %s |" % (
            r["stations"], r["shifts"], r["heads"], _w(r["annual_save"]),
            _w(r["ceiling"]), "✅ 可成交" if r["ok"] else "❌ 不成立"))
    L += ["", "> %s (成立组合 %d/%d)" % (e["configs"]["rule"], e["configs"]["ok_count"],
                                        len(e["configs"]["rows"])),
         "", "## 四、三阶段定价", "",
         "| 阶段 | 台数 | 报价 | 我方承担 | 客户决策 |", "|---|---|---|---|---|"]
    for p in e["phases"]:
        L.append("| %s | %d | %s | %s | %s |" % (
            p["stage"], p["units"],
            "0 (不收费)" if p["price"] == 0 else "%s 万" % _w(p["price"]),
            p["risk"], p["decision"]))
    L += ["", "## 五、模式推荐", "", "推荐: **%s** (%s)" % (
        e["modes"]["recommend"], e["modes"]["rule"]), "",
        "| 模式 | 报价 | 毛利 | 成立条件 | 数字 |", "|---|---|---|---|---|"]
    for m in e["modes"]["options"]:
        price = ("%s 万" % _w(m["price"])) if m.get("price") else ("%.3f 元/颗" % m["per_part"])
        L.append("| %s | %s | %s | %s | %s |" % (
            m["mode"], price,
            ("%.0f%%" % (m["margin"] * 100)) if m.get("margin") is not None else "—",
            m["cond"] + (" ✅" if m["fit"] else " ❌"), m["note"]))
    L += ["", "## 六、价值与风险分配", "",
          "| 谁 | 项目 | 金额 | 说明 |", "|---|---|---|---|"]
    for v in e["value_split"]:
        L.append("| %s | %s | %s | %s |" % (
            v["who"], v["item"],
            ("%s 万" % _w(v["amount"])) if v["amount"] is not None else "—", v["note"]))
    L += ["", "| 阶段 | 我方承担 | 客户承担 | 现金流 |", "|---|---|---|---|"]
    for r in e["risk_split"]:
        L.append("| %s | %s | %s | %s |" % (r["phase"], r["ours"], r["customer"], r["cash"]))
    L += ["", "> 标签: %s" % " · ".join("%s=%s" % (k, v["label"]) for k, v in e["labels"].items() if v["label"]),
          "> 未实测系数不得作为对外承诺 (性能目标值见 config/platform/zmax_perf_spec.json)。", ""]
    return "\n".join(L)


def save_inputs(**over):
    """只改 4 个业务假设 (目标毛利率/客户目标回本/批量台数/人效结构系数), 其余不动。

    铁律: 读-改-写单键 + 备份 + 回读校验 (派生值永不落盘)。
    """
    keys = {k: v for k, v in over.items() if v is not None}
    if not keys:
        return {"ok": True, "path": TRUTH, "changed": []}
    d = load()
    for k, v in keys.items():
        if k not in (d.get("inputs") or {}):
            raise KeyError("唯一依据无此假设键: %s" % k)
        d["inputs"][k]["value"] = float(v) if isinstance(d["inputs"][k]["value"], float) else int(v)
    d["updated"] = time.strftime("%Y-%m-%d %H:%M")

    bak = TRUTH + ".bak_" + time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(TRUTH, bak)
    tmp = TRUTH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TRUTH)

    back = load()
    ok = all(abs(float(back["inputs"][k]["value"]) - float(v)) < 1e-9 for k, v in keys.items())
    return {"ok": bool(ok), "path": TRUTH, "backup": bak, "changed": sorted(keys)}


def export(e, out_dir=None, stamp=None):
    out_dir = out_dir or os.path.join(ROOT, "zmax_data", "business")
    os.makedirs(out_dir, exist_ok=True)
    ts = stamp or time.strftime("%Y%m%d_%H%M%S")
    pj = os.path.join(out_dir, "business_model_%s.json" % ts)
    pm = os.path.join(out_dir, "business_model_%s.md" % ts)
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    with open(pm, "w", encoding="utf-8") as f:
        f.write(to_markdown(e))
    return {"json": pj, "md": pm}


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 商业模式推导")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--eta", type=float, dest="eta_struct")
    ap.add_argument("--units", type=int, dest="s3_units")
    ap.add_argument("--margin", type=float, dest="target_margin")
    a = ap.parse_args()

    e = derive(**{k: v for k, v in (("eta_struct", a.eta_struct), ("s3_units", a.s3_units),
                                    ("target_margin", a.target_margin)) if v is not None})
    if a.json:
        print(json.dumps(e, ensure_ascii=False, indent=1))
        return 0
    if a.md:
        txt = to_markdown(e)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(txt)
            print("✅ 已写 %s (%d 字)" % (a.out, len(txt)))
        else:
            print(txt)
        return 0

    lay, dr = e["layered"], e["deal"]
    print("Z-MAX 商业模式推导   唯一依据 %s @ %s" % (os.path.basename(TRUTH), e["truth"]["business_mtime"]))
    print("  人效 η %.3f ⇒ 客户真实回本 D 口径 %s 年 (A 上限 %.2f 年, 不得对外当承诺)"
          % (lay["eta"], lay["D_payback"], lay["A_payback"]))
    print("  成交区间 floor %s 万 ≤ ceiling %s 万 : %s"
          % (_w(dr["floor"]), _w(dr["ceiling"]), "成立" if dr["ok"] else "不成立 (改配置, 不降价)"))
    for p in e["phases"]:
        print("  %s %d 台: %s" % (p["stage"], p["units"],
                                  "0 元 (我方承担 %s 万)" % _w(p["ours_cost"]) if p["price"] == 0
                                  else "%s 万 (复制毛利 %s)" % (_w(p["price"]),
                                                              ("%.0f%%" % (p["margin_copy"] * 100))
                                                              if p.get("margin_copy") is not None else "—")))
    print("  推荐模式: %s" % e["modes"]["recommend"])
    print("  %s" % e["summary_line"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
