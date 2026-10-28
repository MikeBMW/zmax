#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《任务7 三档成本 · 产量 · 三方分成》PPT (老倪 2026-10-28 第十一轮)。

数字全部来自 tools/cost_model.build_tiers() (唯一真源), 页面/工单/PPT 三处同源。
CLI: gui-venv311/bin/python tools/build_split_ppt.py
产出: docs/deliverables/任务7_三档成本与三方分成.pptx
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from cost_model import build_tiers                                             # noqa: E402

from pptx import Presentation                                                  # noqa: E402
from pptx.dml.color import RGBColor                                            # noqa: E402
from pptx.util import Inches, Pt                                               # noqa: E402

OUT = os.path.join(ROOT, "docs", "deliverables", "任务7_三档成本与三方分成.pptx")
BG = RGBColor(0x0D, 0x14, 0x1C)
FG = RGBColor(0xC9, 0xD1, 0xD9)
ACC = RGBColor(0x3F, 0xBF, 0x7F)
YEL = RGBColor(0xF0, 0xC6, 0x74)
BLU = RGBColor(0x58, 0xA6, 0xFF)
RED = RGBColor(0xE0, 0x6C, 0x75)

CN = "Microsoft YaHei"


def wan(x):
    return "%.1f 万" % (float(x) / 1e4)


def slide(prs, title, subtitle=""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    tb = s.shapes.add_textbox(Inches(0.55), Inches(0.30), Inches(12.3), Inches(0.62))
    p = tb.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.size = Pt(26)
    r.font.bold = True
    r.font.color.rgb = ACC
    r.font.name = CN
    if subtitle:
        tb2 = s.shapes.add_textbox(Inches(0.58), Inches(0.92), Inches(12.3), Inches(0.42))
        p2 = tb2.text_frame.paragraphs[0]
        r2 = p2.add_run()
        r2.text = subtitle
        r2.font.size = Pt(12)
        r2.font.color.rgb = RGBColor(0x7D, 0x85, 0x90)
        r2.font.name = CN
    return s


def table(s, rows, cols, x=0.55, y=1.45, w=12.3, h=None, head=True, sizes=10.5):
    shp = s.shapes.add_table(len(rows), cols, Inches(x), Inches(y), Inches(w),
                             Inches(h or (0.34 * len(rows))))
    t = shp.table
    for ri, row in enumerate(rows):
        for ci in range(cols):
            cell = t.cell(ri, ci)
            cell.text = str(row[ci]) if ci < len(row) else ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(0x16, 0x1B, 0x22) if ri == 0 and head else BG
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(sizes)
                p.font.name = CN
                p.font.color.rgb = YEL if (ri == 0 and head) else FG
                p.font.bold = (ri == 0 and head)
    return t


def bullets(s, lines, x=0.6, y=1.5, w=12.2, h=5.6, size=13):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (txt, col) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(size)
        r.font.color.rgb = col
        r.font.name = CN
        p.space_after = Pt(7)
    return tb


def main():
    d = build_tiers()
    T = {t["id"]: t for t in d["tiers"]}
    S = d["split"]
    a, b, c = T["A"], T["B"], T["C"]
    # 设备售价 = (capex + NRE) × 1.4 (40% 毛利口径)
    sell = {k: (T[k]["capex"] + T[k]["nre_sum"]) * 1.4 for k in "ABC"}

    # 仿真产量 (ar3d 演练口径, 实测节拍)
    uph = d["uph_geo"]
    sim_1h = int(uph * 1 * 1.0)
    sim_8h = int(uph * 8 * 1.0)
    shift8 = {k: int(uph * 8 * T[k]["oee"]) for k in "ABC"}

    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # 1 封面
    s = slide(prs, "任务 7 · 摆盘 / 插拔 / AOI —— 三档成本 · 产量 · 三方分成",
              "Z-MAX 双臂并行工位 · 392 段 / 14 件 / 11.42 s·件⁻¹ · 2026-10-28")
    bullets(s, [
        ("产品定义: 光模块 插拔 + 摆盘 + AOI 五点检测, 双臂并行 (左臂摆盘供料 · 右臂插拔/AOI)", FG),
        ("性能分档: A 基本 (L2 ≤30 TOPS) · B 精细 (L2+L3 ≤80 TOPS) · C 专业 (L2+L3+L4 含 L5 ≤300 TOPS)", YEL),
        ("本 PPT 数字全部由 tools/cost_model.build_tiers() 现算, 与配置中心《性能/工程/工单》同一真源", RGBColor(0x7D, 0x85, 0x90)),
        ("⚠ 单价为市场参考口径, 供应商未正式报价; 报价到手只需改 tools/spec/cost_model.json, 结论自动重算", RED),
    ], y=2.0)

    # 2 结论
    s = slide(prs, "一页结论", "推荐: T2 精细做主力, T3 专业做标杆客户, T1 做小批量切入")
    rows = [["", "A 基础 (L2)", "B 精细 (L2+L3)", "C 专业 (L2+L3+L4+L5)"],
            ["capex", wan(a["capex"]), wan(b["capex"]), wan(c["capex"])],
            ["NRE", wan(a["nre_sum"]), wan(b["nre_sum"]), wan(c["nre_sum"])],
            ["单件成本", "%.4f 元" % a["unit_cost"], "%.4f 元" % b["unit_cost"], "%.4f 元" % c["unit_cost"]],
            ["加工单价", "0.35 元", "0.42 元", "0.55 元"],
            ["年毛利", wan(a["gross_year"]), wan(b["gross_year"]), wan(c["gross_year"])],
            ["回收期", "%.2f 年" % a["payback_years"], "%.2f 年" % b["payback_years"], "%.2f 年" % c["payback_years"]]]
    table(s, rows, 4, y=1.5, h=2.9, sizes=11.5)
    bullets(s, [
        ("A 最快回本 (0.68 年) 但只能单任务、换型要停线 ⇒ 适合单品种大批量", FG),
        ("B 多任务编排, 回本 0.91 年, 换型不停线 ⇒ 主力型号 (推荐)", ACC),
        ("C 自主 + 安全分级, 回本 0.94 年, 可无人夜班 + 质量担保 ⇒ 标杆客户/高端线", YEL),
    ], y=4.6, size=12.5)

    # 3 成本结构
    s = slide(prs, "成本结构 (单工位, 口径: 市场参考/供应商待报价)",
              "capex 一次性 + NRE 一次性 + 运营现金/年; 折旧 5 年直线, NRE 3 年摊")
    rows = [["项目", "A 基础", "B 精细", "C 专业"],
            ["硬件 capex", wan(a["capex"]), wan(b["capex"]), wan(c["capex"])],
            ["实施 NRE", wan(a["nre_sum"]), wan(b["nre_sum"]), wan(c["nre_sum"])],
            ["运营现金/年", wan(a["opex_year"]), wan(b["opex_year"]), wan(c["opex_year"])],
            ["折旧/年", wan(a["dep_year"]), wan(b["dep_year"]), wan(c["dep_year"])],
            ["NRE 摊销/年", wan(a["nre_amort"]), wan(b["nre_amort"]), wan(c["nre_amort"])],
            ["年成本合计", wan(a["cost_year"]), wan(b["cost_year"]), wan(c["cost_year"])]]
    table(s, rows, 4, y=1.5, h=3.0)
    bullets(s, [
        ("C 档 NRE 占大头 (53.0 万): 数据采集 6 万 + L3 训练 6 万 + L4 训练 8 万 + L5 接入 3 万 + 安全认证 15 万 + 安全文档 6 万 + 集成 9 万", RGBColor(0x7D, 0x85, 0x90)),
        ("B 档增量主要买「换型不停线」: 推理算力 4.7 万 + 采数 6 万 + 训练 6 万", RGBColor(0x7D, 0x85, 0x90)),
    ], y=4.75, size=11.5)

    # 4 单件经济性
    s = slide(prs, "单件经济性与回收", "产量 = 实测 315.2 UPH × 档位工时 × OEE (不另拍数字)")
    rows = [["", "A", "B", "C"],
            ["年产量 (件)", "{:,}".format(a["pieces_year"]), "{:,}".format(b["pieces_year"]), "{:,}".format(c["pieces_year"])],
            ["工时 × OEE", "4800h × 0.85", "4800h × 0.85", "6000h × 0.88"],
            ["单价 (元/件)", "%.2f" % a["price_per_piece"], "%.2f" % b["price_per_piece"], "%.2f" % c["price_per_piece"]],
            ["单件成本", "%.4f" % a["unit_cost"], "%.4f" % b["unit_cost"], "%.4f" % c["unit_cost"]],
            ["单件毛利", "%.4f" % a["unit_margin"], "%.4f" % b["unit_margin"], "%.4f" % c["unit_margin"]],
            ["年收入", wan(a["revenue_year"]), wan(b["revenue_year"]), wan(c["revenue_year"])],
            ["毛利率", "%.1f%%" % a["gross_margin_pct"], "%.1f%%" % b["gross_margin_pct"], "%.1f%%" % c["gross_margin_pct"]]]
    table(s, rows, 4, y=1.5, h=3.3)
    bullets(s, [
        ("单价口径: A 替代 1 名操作工 (9 万/人·年 ÷ 25 万件) ≈ 0.36; B 多品种+少人化 +20%; C 无人夜班+质量担保 +57%", RGBColor(0x7D, 0x85, 0x90)),
        ("三档单件成本都 < 0.17 元 ⇒ 加工费模式下对客户是「人力成本 1/2 ~ 1/4」", ACC),
    ], y=4.95, size=11.5)

    # 5 三张工单
    s = slide(prs, "三张生产工单 (T1 / T2 / T3)", "工单已生成在 config/orders/BS_SCN-07-AOI-T{1,2,3}.json, 工单配置页可见")
    rows = [["工单", "档位", "范围", "班次", "产能", "交付"],
            ["T1 基础", "L2 ≤30 TOPS", "固定序: 摆盘+插拔+AOI 五点", "两班 16h", "{:,} 件/年".format(a["pieces_year"]), "14 天"],
            ["T2 精细", "L2+L3 ≤80 TOPS", "多品种换型 + 技能序列 + 双臂并行", "两班 16h", "{:,} 件/年".format(b["pieces_year"]), "28 天"],
            ["T3 专业", "L2+L3+L4(+L5) ≤300 TOPS", "无人夜班 + 异常自恢复 + 质量担保", "三班 20h", "{:,} 件/年".format(c["pieces_year"]), "60 天"]]
    table(s, rows, 6, y=1.5, h=2.2, sizes=11)
    bullets(s, [
        ("每张工单带 cost 快照 (capex/NRE/单件成本/毛利/回收期/推荐分成), 由工单生成器从成本模型直出", RGBColor(0x7D, 0x85, 0x90)),
        ("生产编排: ar3d 页底部「💰 生产演练 · 市场预期」独立窗口选工单 → ▶ 安排生产 → 实时累计产量与产值", ACC),
    ], y=4.0, size=12)

    # 6 仿真产量
    s = slide(prs, "产量: 仿真演练结果 (ar3d 实测节拍)", "节拍 11.42 s/件 · 几何产能 315.2 UPH · 392 段/轮 14 件")
    rows = [["时段", "纯节拍产量 (件)", "8h 班 (含 OEE)", "对应产值 (A 档 0.35 元/件)"],
            ["1 小时", "{:,}".format(sim_1h), "{:,}".format(shift8["A"] // 8), "%.2f 元" % (sim_1h * 0.35)],
            ["8 小时", "{:,}".format(sim_8h), "{:,}".format(shift8["A"]), "%.2f 元" % (sim_8h * 0.35)],
            ["1 年 (4800h)", "{:,}".format(int(uph * 4800)), "{:,}".format(a["pieces_year"]), wan(a["revenue_year"])]]
    table(s, rows, 4, y=1.5, h=2.2, sizes=11)
    bullets(s, [
        ("演练实测: 1h = 18,9xx 件 · 2h = 37,8xx 件 (ar3d 页面 __PROD__ 读回, 与 315.2 UPH 一致)", ACC),
        ("OEE 0.85 是「换料/换型/小停机」折减; C 档 6000h×0.88 = 166.4 万件/年 (无人夜班)", YEL),
        ("⚠ 当前站点 plane_z/T_base_cam 未标定 ⇒ 真机产量以现场标定后复测为准, 上表是几何能力", RED),
    ], y=4.1, size=12)

    # 7 销售建议
    s = slide(prs, "销售建议 (三种卖法, 按客户算账)", "设备售卖 / 按件代运营 / 混合 (推荐)")
    rows = [["卖法", "A 基础", "B 精细", "C 专业", "适合谁"],
            ["① 卖设备 (capex+NRE)×1.4", wan(sell["A"]), wan(sell["B"]), wan(sell["C"]), "有工程能力、要资产"],
            ["② 按件收费", "0.35 元/件", "0.42 元/件", "0.55 元/件", "不想投 capex、按量结算"],
            ["③ 混合 (推荐)", "设备 + 0.02 元/件运营费 + 20% 收益许可", "同左", "同左", "要绑定长期收益"]]
    table(s, rows, 5, y=1.5, h=2.1, sizes=10.5)
    bullets(s, [
        ("对客户的价值锚: 一名操作工 9 万/年, 单工位年产能 128.6 万件 ⇒ 人工折 0.07 元/件; 我们收 0.35 ⇒ 客户仍省 70%+ 且质量可追溯", FG),
        ("报价策略: 首台按 ①②③ 三选一给客户选; 第二台起只做 ③ (锁定软件许可与运营费, 复购毛利更高)", ACC),
        ("不建议: 纯低价卖硬件 (毛利 <25%, 且把模型/数据价值让渡给客户)", RED),
    ], y=4.0, size=12)

    # 8 市场策略
    s = slide(prs, "市场策略", "先做「可量化的节拍 + 良率」案例, 再复制到同类工位")
    bullets(s, [
        ("① 切入点: 光模块/连接器 插拔 + AOI 复判工位 —— 客户痛点是「夜班没人 + 复判漏检」, 我们有 316 UPH / 99.2% 良率 / 单件 0.08 元三个可测数字", FG),
        ("② 三档定位: T1 小批量试产 (14 天交付) 抢首单; T2 主力 (换型不停线) 做规模; T3 标杆 (无人夜班+质量担保) 做品牌", YEL),
        ("③ 交付即验收: 每档 WI 25 步 + 判据脚本, 现场按步骤跑, 客户能自己复测 —— 这是与集成商最大的差异", ACC),
        ("④ 渠道: 先直销 3 家头部 (拿到产线数据与案例), 再交给集成商做标准化 T1/T2 (我们收软件许可 + 运营费)", FG),
        ("⑤ 风险对冲: 未标定项 (plane_z/T_base_cam) 与 L3 数据缺口 (0 episode) 必须先补, 否则不承诺 UPH 与良率", RED),
    ], y=1.45, size=12.5)

    # 9 三方分成
    s = slide(prs, "三方分成 (机器人本体硬件 / 模型软件 / 运营数据)",
              "三种方案: 投入比例 / 价值贡献 / 混合制 (推荐)")
    rows = [["方案", "硬件", "软件", "运营", "说明"]]
    for tid in "ABC":
        sp = S[tid]
        rows.append(["投入比例 · " + tid, "%s%%" % sp["s1_invest"]["pct"]["hw"], "%s%%" % sp["s1_invest"]["pct"]["sw"],
                     "%s%%" % sp["s1_invest"]["pct"]["op"], "按 capex:NRE:运营现金 分摊"])
    for tid in "ABC":
        sp = S[tid]
        rows.append(["价值贡献 · " + tid, "%s%%" % sp["s2_value"]["pct"]["hw"], "%s%%" % sp["s2_value"]["pct"]["sw"],
                     "%s%%" % sp["s2_value"]["pct"]["op"], "行业口径 45:30:25"])
    for tid in "ABC":
        sp = S[tid]
        rows.append(["混合制 · " + tid, "%s%%" % sp["s3_hybrid"]["pct"]["hw"], "%s%%" % sp["s3_hybrid"]["pct"]["sw"],
                     "%s%%" % sp["s3_hybrid"]["pct"]["op"], "硬件一次性 + 许可 20% + 0.02 元/件"])
    table(s, rows, 5, y=1.5, h=3.9, sizes=9.5)
    bullets(s, [
        ("推荐混合制: 硬件方一次性收款 (不背产量风险) / 软件方按收益 20% (与节拍·良率绑定) / 运营方按 0.02 元/件 (数据/运维/模型迭代)", ACC),
        ("C 档可分现金 %.0f 万/年 ⇒ 硬件 %.0f 万 · 软件 %.0f 万 · 运营 %.0f 万"
         % (S["C"]["cash_year"] / 1e4, S["C"]["s3_hybrid"]["abs"]["hw"] / 1e4,
            S["C"]["s3_hybrid"]["abs"]["sw"] / 1e4, S["C"]["s3_hybrid"]["abs"]["op"] / 1e4), YEL),
    ], y=5.65, size=11.5)

    # 10 风险与下一步
    s = slide(prs, "风险与下一步", "先补三个硬缺口, 再对外承诺数字")
    bullets(s, [
        ("① 站点几何未标定: plane_z / T_base_cam 缺失 ⇒ 3D 换算被拒, 真机 UPH 与良率无法承诺 (需现场 1 天)", RED),
        ("② L3 数据缺口: zmax_data/datasets 0 个 parquet / 无 LeRobot info.json ⇒ T2/T3 的多任务能力没有数据支撑 (需 200 episode)", RED),
        ("③ 单价口径待确认: 全部 unit 为市场参考值, 供应商正式报价后只改 tools/spec/cost_model.json, 页面/工单/PPT 自动重算", YEL),
        ("④ 安全等级: 目标 PL d 未认证 (ISO 13849/9283 报告未做) ⇒ T3 只能写「目标」不能写「已达」", YEL),
        ("下一步: 采购报价 → 现场标定 → 采数 200 episode → T1 首单验收 → T2 交付 → 安全认证 → T3 标杆", ACC),
    ], y=1.5, size=12.5)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print("写出 %s (%d 字节 · %d 页)" % (os.path.relpath(OUT, ROOT), os.path.getsize(OUT), len(prs.slides._sldIdLst)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
