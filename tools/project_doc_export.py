#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目立项文档导出器 — 数据驱动 (BOM 挂功能 / 成本自动核算 / ROI 由性能指标算)

真源 (三份文档同源):
  · config/platform/zmax_project_bom.json   ← BOM/降本/人力/商务/ROI/市场 条款
  · data/database/zmax/zmax_engineering.db  ← 功能清单/能力/指标 (BOM 的 links 必须命中这里)
  · config/platform/zmax_data_governance.json ← 合作协议

用法:
  python3 tools/project_doc_export.py            # 导出 Word 立项文档 (+JSON/manifest)
  python3 tools/project_doc_export.py --check    # 只算账: BOM 功能关联 + 成本对账 + ROI
"""
import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sor_export import _font, footer_pagenum, h, page_setup, para, sha, table  # noqa: E402

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOM = os.path.join(ROOT, "config", "platform", "zmax_project_bom.json")
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
DBC = os.path.join(ROOT, "feature.dbc")
OUT_ROOT = os.path.join(ROOT, "outputs", "project_docs")
DOC_NO = "PRJ-TH-TRAY-" + time.strftime("%Y%m%d")
VERSION = "v1.0"
CN = "微软雅黑"

ABBR = [
    ("AOI", "Automated Optical Inspection", "自动光学检测"),
    ("COC", "Chip on Carrier", "芯片贴装 (光通信芯片贴装产线)"),
    ("CT", "Cycle Time", "节拍时间"),
    ("EMC/EMI/EMS", "Electromagnetic Compatibility/Interference/Susceptibility", "电磁兼容/发射/抗扰"),
    ("ESD", "Electrostatic Discharge", "静电放电"),
    ("GFLOPS", "Giga Floating-point Operations Per Second", "每秒十亿次浮点运算"),
    ("HMI", "Human Machine Interface", "人机界面"),
    ("MES", "Manufacturing Execution System", "制造执行系统"),
    ("POC", "Proof of Concept", "概念验证"),
    ("ROI", "Return on Investment", "投资回报分析"),
    ("TOPS", "Tera Operations Per Second", "每秒万亿次运算"),
    ("Tray", "—", "托盘式载具"),
    ("UPH", "Units Per Hour", "每小时产出"),
    ("EVT/DVT/PVT", "Engineering/Design/Production Validation Test", "工程/设计/生产验证阶段"),
    ("SOR", "Supplier/Owner Requirements", "需求规格说明书 (供应商交付)"),
]


def money(x):
    return "%.2f 万" % (x / 10000.0) if abs(x) >= 10000 else "%.0f 元" % x


def db_facts():
    """工程库事实: 功能/能力/指标 — 供 BOM links 校验与文档引用。"""
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    fns = {r["fn_id"]: r["name"] for r in c.execute("select fn_id,name from functions where system_id='sys1'")}
    pfs = {r["pf_id"]: r["title"] for r in c.execute("select pf_id,title from product_features")}
    caps = set()
    for ln in open(DBC, encoding="utf-8"):
        if ln.startswith("BO_ "):
            caps.add(ln.split(":", 1)[0].replace("BO_ ", "").strip())
    params = {r["param_id"] for r in c.execute("select param_id from params")}
    return fns, pfs, caps, params


def check_links(bom, fns, pfs, caps, params):
    """每个 BOM 项挂的功能/能力必须真实存在 (含 BO_ 前缀精确匹配); 返回 (通过, 悬空, 覆盖)。"""
    ok, dangling, covered = [], [], set()
    for it in bom["items"]:
        for lk in it["links"]:
            hit = (lk in fns or lk in pfs or lk in params
                   or any(c.startswith(lk.replace("BO_ ", "")) for c in caps))
            (ok if hit else dangling).append((it["id"], lk))
            if hit:
                covered.add(lk)
    # 反向覆盖: Sys-1 功能节点是否都有 BOM 支撑
    uncovered = [f for f in fns if f not in covered]
    return ok, dangling, covered, uncovered


def compute(root):
    """成本/收益/ROI 计算 —— 输入是整份 BOM 真源 (含 bom/labor/commercial/roi 各段)。"""
    bom, labor_s, com, roi = root["bom"], root["labor"], root["commercial"], root["roi"]
    items = bom["items"]
    base = sum(i["qty"] * i["price"] for i in items)
    cd = sum(c["save"] for c in bom["costdown"])
    disc = bom["bulk_discount"]
    prod = base * bom["mass_production_factor"]          # 生产期: 行业通用件替代
    mass = prod * disc                                    # 量产期: 再叠批量价
    cd_scenario = (base - cd) * disc                      # 降本路径全部落地后的量产期 (相对样机 BOM)
    tgt = bom["stage_targets"]
    labor = sum(x["pm"] for x in labor_s["internal"]) * labor_s["cost_per_pm"]
    price = com["price_schedule"][com["price_used"]]
    rev = {str(y): com["volume"][str(y)] * price.get(str(y), 0) for y in com["volume"]}
    tot_vol = sum(com["volume"].values())
    gross = sum(rev.values()) - mass * tot_vol - labor
    annual = roi["efficiency_ratio"] * roi["labor_cost_per_year"] * roi["shifts"]
    maint = price["2027"] * roi["maintenance_rate"]
    net = annual - maint
    payback = price["2027"] / net
    be = net * roi["target_payback_years"]
    return dict(base=base, costdown=cd, prod=prod, mass=mass, cd_scenario=cd_scenario, labor=labor, rev=rev,
                gross=gross, total_volume=tot_vol, annual=annual, maint=maint, net=net,
                payback=payback, breakeven=be, targets=tgt, price=price)


def cmd_check(bom=None):
    bom = bom or json.load(open(BOM, encoding="utf-8"))
    bs, bl, ro, cm = bom["bom"], bom["labor"], bom["roi"], bom["commercial"]
    fns, pfs, caps, params = db_facts()
    ok, dangling, covered, uncovered = check_links(bom["bom"], fns, pfs, caps, params)
    r = compute(bom)
    print("═══ BOM × 功能配置 关联校验 ═══")
    print("  BOM 项 %d · 挂载关系 %d 条 · 命中工程库/feature.dbc %d · 悬空 %d"
          % (len(bs["items"]), len(ok) + len(dangling), len(ok), len(dangling)))
    for i, lk in dangling:
        print("   ❌ 悬空: %s → %s" % (i, lk))
    print("  Sys-1 功能覆盖: 被 BOM 支撑 %d/%d" % (len(set(fns) & covered), len(fns)))
    for f in uncovered:
        print("   ⚠️ 无 BOM 支撑: %s %s" % (f, fns[f]))
    print("\n═══ 成本核算 (元) ═══")
    print("  样机期 BOM          %10s  (文档口径 %s)" % (money(r["base"]), money(r["targets"]["样机期"])))
    print("  生产期 (通用件 ×%.2f)  %10s  (文档口径 %s)"
          % (bs["mass_production_factor"], money(r["prod"]), money(r["targets"]["生产期"])))
    print("  量产期 (再叠批量价 %.0f%%) %9s  (文档口径 %s)"
          % (bs["bulk_discount"] * 100, money(r["mass"]), money(r["targets"]["量产期"])))
    print("  降本路径(建议, %s) 若全落地 → 量产期 %s" % (money(r["costdown"]), money(r["cd_scenario"])))
    print("  开发人力 (内部 %d 人月 × %s) %s"
          % (sum(x["pm"] for x in bl["internal"]), money(bl["cost_per_pm"]), money(r["labor"])))
    print("  合同额(3 年 %d 台)   %10s   毛利粗算(=收入−量产成本−人力) %s"
          % (r["total_volume"], money(sum(r["rev"].values())), money(r["gross"])))
    print("\n═══ 买方 ROI (由性能指标驱动) ═══")
    print("  人效比 %.2f × 人工成本 %s/人年 × %d 班 = 年节省 %s"
          % (ro["efficiency_ratio"], money(ro["labor_cost_per_year"]),
             ro["shifts"], money(r["annual"])))
    print("  减维护(售价×%.0f%%) %s → 净年节省 %s" % (ro["maintenance_rate"] * 100,
                                                    money(r["maint"]), money(r["net"])))
    print("  回收期 = 售价 %s / 净年节省 = %.2f 年 (客户目标 ≤%.0f 年)"
          % (money(ro.get("price_for_roi", r["price"]["2027"])), r["payback"],
             ro["target_payback_years"]))
    print("  盈亏平衡售价 = 净年节省 × %.0f 年 = %s (文档口径 %s ⇒ %s)"
          % (ro["target_payback_years"], money(r["breakeven"]),
             money(ro["doc_break_even_price"]),
             "差异需市场确认假设" if abs(r["breakeven"] - ro["doc_break_even_price"]) > 20000 else "一致"))
    fails = (len(dangling) > 0 or abs(r["base"] - r["targets"]["样机期"]) > 5000
             or abs(r["prod"] - r["targets"]["生产期"]) > 5000
             or abs(r["mass"] - r["targets"]["量产期"]) > 5000)
    print("\n%s" % ("⛔ 有未闭合项 (见上)" if fails else "✅ 关联与对账全通过"))
    return 0 if not fails else 1


def build_doc(bom, r, ok, dangling, covered, uncovered):
    prj, db_fns = bom["project"], db_facts()[0]
    bs_factor = bom["bom"]["mass_production_factor"]
    bm = bom["bom"]
    doc = page_setup(Document(), margins=(2.0, 1.8))
    footer_pagenum(doc, "%s · %s            " % (DOC_NO, VERSION))
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(t.add_run("泰国模块摆料项目 · 立项文档"), size=22, bold=True)
    para(doc, "项目: %s" % prj["name"], size=11)
    para(doc, "客户: %s · 现场: %s" % (prj["customer_block"], prj["site"]), size=11)
    para(doc, "文档编号: %s · 版本 %s · 数据源: 单一工程库 + BOM 真源 (配置中心导出, %s)"
         % (DOC_NO, VERSION, time.strftime("%Y-%m-%d %H:%M")), size=10)

    h(doc, "0. 文档信息", 1)
    table(doc, ["版本", "日期", "作者", "变更说明"],
          [[v["ver"], v["date"], v["author"], v["change"]] for v in prj["doc_versions"]],
          widths=[1.8, 2.4, 2.4, 9.4])

    h(doc, "1. 市场评估", 1)
    para(doc, "1.1 项目需求来源")
    para(doc, bom["market"]["source"] + " —— " + bom["market"]["scene"])
    para(doc, "1.2 POC 验收标准")
    para(doc, bom["market"]["acceptance"])
    para(doc, "阶段核心指标 (与配置中心性能指标同源):")
    table(doc, ["节点", "负责人", "截止", "指标"],
          [[m["name"], m["owner"], m["due"], m["metrics"]] for m in prj["milestones"]],
          widths=[4.6, 2.0, 2.2, 7.2])
    para(doc, "1.3 单台金额 / 1.4 合同金额")
    para(doc, "首台 POC 按 %s 轮式双臂 %s(未税) 定合同额; 形态变更为 Z100LFd 后价格待重谈。"
         % (bom["commercial"]["price_used"], money(bom["commercial"]["poc_price"])))
    para(doc, "1.5 销量预测与售价")
    table(doc, ["年份", "预期销量", "轮式双臂售价", "固定双臂售价"],
          [[y, bom["commercial"]["volume"][y], money(bom["commercial"]["price_schedule"]["轮式双臂"][y]),
            money(bom["commercial"]["price_schedule"]["固定双臂"][y])] for y in ("2026", "2027", "2028")],
          widths=[2.4, 3.0, 4.4, 4.4])
    para(doc, bom["commercial"]["volume_note"], size=9)
    para(doc, "1.6 竞品分析 / 1.7 当前状态")
    para(doc, "竞品: %s" % bom["market"]["competitor"])
    para(doc, "状态: %s" % bom["market"]["status"])

    h(doc, "2. 产品/项目评估", 1)
    para(doc, "2.1 项目描述: %s" % prj["name"])
    para(doc, "2.2 场景分析与解决方案: 固定双臂作业, 将 12+ 种型号光模块从来料周转盒逐颗逐层摆入 EEPROM 测试设备空 Tray 盘;"
              "视觉引导 + 力控柔顺抓取 + 真空防静电无痕吸盘; 五步取放循环 (多型号识别 → 力触抓取 → 搬运 → 视觉二次定位入槽 → 到位检测)。")
    para(doc, "2.2.1 产品形态: 人形上身 + 升降立柱 + 可移动被动轮 (Z100LFd)。")
    para(doc, "2.3 产品定义 FL 要点: 单臂负载 7kg / 场景实需 5kg / 腰部俯仰扩大作业范围 / 市电直供 / 底部万向轮可推;")
    para(doc, "ESD: 表面电阻 %s, 摩擦电压 %s, 接地电阻 %s。"
         % (bom["esd"]["surface_resistance"], bom["esd"]["friction_voltage"], bom["esd"]["grounding"]), size=10)
    para(doc, "2.4 进度与分工")
    table(doc, ["岗位", "姓名"], [[x["role"], x["who"]] for x in prj["team"]], widths=[6.0, 9.0])

    h(doc, "3. 研发评估", 1)
    para(doc, "3.1 技术可行性: 结构 (固定式底盘+顶升 → 垂直升降 0–450mm → 胸部/腰部俯仰旋转 → 六轴协作臂 CR7 ×2 → 头部双目);"
              "电气 (整机硬件方案, ESD/接地按 2.3 要求); 软件 (L3 动作执行: VLA-T + Z-Flow, 见 System 1 功能清单)。")
    para(doc, "3.2 研发成员分工")
    table(doc, ["岗位", "姓名"], [[x["role"], x["who"]] for x in prj["team_dev"]], widths=[6.0, 9.0])
    para(doc, "3.3 风险项")
    table(doc, ["风险项", "应对措施", "负责人"],
          [[x["risk"], x["action"], x["owner"]] for x in prj["risks"]],
          widths=[5.2, 7.6, 2.2])

    h(doc, "4. 财务评估", 1)
    para(doc, "4.1 BOM 明细 (每项都挂到功能/能力 —— 改功能清单即知 BOM 影响面)", bold=True)
    table(doc, ["编号", "名称", "数量", "单价", "小计", "关联功能/能力", "备注"],
          [[i["id"], i["name"], "%s%s" % (i["qty"], i["unit"]), money(i["price"]),
            money(i["qty"] * i["price"]), " · ".join(i["links"]), i["note"]] for i in bm["items"]],
          widths=[1.2, 3.4, 1.2, 1.6, 1.6, 4.2, 3.6])
    para(doc, "单价口径: %s" % bom["bom"]["price_status"], size=9)
    para(doc, "4.1.1 成本汇总与文档口径对账", bold=True)
    table(doc, ["阶段", "本工具核算", "文档口径", "差异"],
          [["样机期 BOM", money(r["base"]), money(r["targets"]["样机期"]), money(r["base"] - r["targets"]["样机期"])],
           ["生产期 (通用件 ×%.2f)" % bs_factor, money(r["prod"]), money(r["targets"]["生产期"]), money(r["prod"] - r["targets"]["生产期"])],
           ["量产期 (再叠批量价 %.0f%%)" % (bm["bulk_discount"] * 100), money(r["mass"]), money(r["targets"]["量产期"]), money(r["mass"] - r["targets"]["量产期"])],
           ["(建议路径) 降本 %s 全落地" % money(r["costdown"]), money(r["cd_scenario"]), "—", "—"]],
          widths=[4.2, 3.6, 3.6, 3.6])
    para(doc, "4.1.2 量产降本路径", bold=True)
    table(doc, ["编号", "降本项", "降本空间", "阶段", "关联 BOM", "说明"],
          [[c["id"], c["name"], money(c["save"]), c["stage"], " · ".join(c["applies_to"]), c["note"]]
           for c in bm["costdown"]], widths=[1.2, 4.4, 2.0, 1.8, 2.2, 3.4])
    para(doc, "4.2 定制开发人力成本: 内部 %d 人月 × %s = %s (%s); 新增招聘: %s"
         % (sum(x["pm"] for x in bom["labor"]["internal"]), money(bom["labor"]["cost_per_pm"]), money(r["labor"]),
            bom["labor"]["cost_status"], "、".join("%s%d 人" % (h_["role"], h_["count"]) for h_ in bom["labor"]["new_hires"])),
         size=10)
    for x in bom["labor"]["internal"]:
        para(doc, "   %d 年: %d 人月 — %s" % (x["year"], x["pm"], x["note"]), size=10)
    para(doc, "4.3 成本收益粗算: 3 年销量 %d 台, 收入 %s, 减量产成本 %s 与人力 %s ⇒ 毛利粗算 %s (不含研发固定成本分摊)"
         % (r["total_volume"], money(sum(r["rev"].values())), money(r["mass"] * r["total_volume"]),
            money(r["labor"]), money(r["gross"])))
    para(doc, "4.4 买方 ROI (由性能指标/人效比计算)", bold=True)
    para(doc, "公式: %s" % bom["roi"]["formula"], size=9)
    table(doc, ["项", "值", "来源/假设"],
          [["人效比", "%.2f" % bom["roi"]["efficiency_ratio"], "文档口径"],
           ["人工综合成本", "%s /人年" % money(bom["roi"]["labor_cost_per_year"]), bom["roi"]["labor_cost_status"]],
           ["班次", "%d" % bom["roi"]["shifts"], "假设"],
           ["年节省", money(r["annual"]), "= 人效比 × 人工成本 × 班次"],
           ["维护费", money(r["maint"]), "= 售价 × %.0f%%" % (bom["roi"]["maintenance_rate"] * 100)],
           ["净年节省", money(r["net"]), "= 年节省 − 维护费"],
           ["回收期", "%.2f 年" % r["payback"], "= 售价 / 净年节省 (客户目标 ≤%.0f 年)"
            % bom["roi"]["target_payback_years"]],
           ["盈亏平衡售价", money(r["breakeven"]), "= 净年节省 × 目标回收期; 文档口径 %s"
            % money(bom["roi"]["doc_break_even_price"])]],
          widths=[3.0, 3.6, 8.4])

    h(doc, "5. 项目立项评审表", 1)
    table(doc, ["评审项", "结论", "依据"],
          [["市场", "通过 (独家评估场景)", "1.1–1.7"],
           ["产品/项目", "通过 (形态变更待客户确认)", "2.1–2.4"],
           ["研发", "条件通过 (人力 +6 人; 节拍风险)", "3.1–3.3"],
           ["财务", "条件通过 (样机期 %s; 客户 ROI 需售价降至 %s)" % (money(r["base"]), money(r["breakeven"])),
            "4.1–4.4"],
           ["BOM × 功能关联", "%s (悬空 %d)" % ("通过" if not dangling else "有悬空", len(dangling)),
            "4.1 关联列 + 工程库校验"]],
          widths=[3.0, 6.6, 5.4])

    h(doc, "6. 附录", 1)
    para(doc, "6.1 缩略语")
    table(doc, ["缩略语", "全称", "说明"], [list(a) for a in ABBR], widths=[2.6, 7.4, 5.0])
    para(doc, "6.2 问题收集记录: (项目周会逐条累积)", size=10)
    para(doc, "6.3 数据来源与可复现: 工程库 %s (sha256 %s…) · BOM 真源 config/platform/zmax_project_bom.json · "
              "功能/指标/能力取自同一库, 与 SOR、合作协议同源。"
         % (os.path.relpath(DB, ROOT), sha(DB)[:16]), size=9)
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    bom = json.load(open(BOM, encoding="utf-8"))
    if a.check:
        return cmd_check(bom)
    fns, pfs, caps, params = db_facts()
    ok, dangling, covered, uncovered = check_links(bom["bom"], fns, pfs, caps, params)
    r = compute(bom)
    doc = build_doc(bom, r, ok, dangling, covered, uncovered)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_ROOT, ts)
    os.makedirs(out, exist_ok=True)
    base = "%s_%s" % (DOC_NO, VERSION)
    fp = os.path.join(out, base + ".docx")
    doc.save(fp)
    jp = os.path.join(out, base + ".json")
    json.dump({"doc_no": DOC_NO, "version": VERSION, "project": bom["project"]["name"],
               "bom": bom["bom"], "computed": r, "linkage": {"hit": len(ok), "dangling": dangling,
                                                             "sys1_covered": sorted(set(fns) & covered)},
               "labor": bom["labor"], "commercial": bom["commercial"], "roi": bom["roi"],
               "market": bom["market"], "esd": bom["esd"]},
              open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    man = {"doc_no": DOC_NO, "version": VERSION, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "sources": {"engineering_db": os.path.relpath(DB, ROOT), "engineering_db_sha256": sha(DB),
                       "bom_source": os.path.relpath(BOM, ROOT), "bom_sha256": sha(BOM),
                       "feature_dbc_sha256": sha(DBC),
                       "governance": "config/platform/zmax_data_governance.json"},
           "computed": r,
           "files": {os.path.basename(fp): {"bytes": os.path.getsize(fp), "sha256": sha(fp)},
                     os.path.basename(jp): {"bytes": os.path.getsize(jp), "sha256": sha(jp)}}}
    json.dump(man, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("✅ 项目立项文档 (Word): %s" % fp)
    print("   大小 %.1f KB · 章节 0–6 · BOM %d 项 (挂载 %d 条, 悬空 %d) · 样机期 %s / 量产期 %s · 回收期 %.2f 年"
          % (os.path.getsize(fp) / 1024.0, len(bom["bom"]["items"]), len(ok), len(dangling),
             money(r["base"]), money(r["mass"]), r["payback"]))
    print("   目录: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
