#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《双臂协作工位 · 三档目标成本分析》—— 只算成本，不写销售价 (2026-10-28 老倪定稿)。

老倪 2026-10-28: 「成分分析；基础 硬件 15万，软件 7万；精细 硬件 20万，软件10万；
专家 硬件 22万 软件 15万。按照这个给出成本分析；不要写销售价。重写 PPT」

所以这一版**整本只有成本**：
  · 目标成本三分离：目标硬件成本 / 目标软件成本 / 单套目标成本
  · 现估成本 → 目标成本的降本缺口（现估 = tools/spec/cost_model.json 的 BOM 与 NRE）
  · 实施（NRE）投入与摊销、运营年成本、每件成本、产能摊薄敏感性、与人工折算的比较
  · **不出现任何售价 / 报价 / 利润空间 / 毛利 / 分成 / 回本** 字样（判据 tools/verify_cost_deck.py 硬查）

真源（改数字只改 json，本文件不写死任何结论）：
  tools/spec/cost_targets.json   ← 目标硬件/软件成本（15+7 / 20+10 / 22+15 万）
  tools/spec/cost_model.json     ← 现估 BOM 单价、NRE、运营项、折旧/摊销年限、节拍与 OEE
算法：tools/targets_model.build_targets() + tools/cost_model.build_tiers()

产出：/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本分析_三档目标成本.pptx
跑法：gui-venv311/bin/python tools/build_cost_deck.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from build_market_deck import (                                               # noqa: E402
    TMPL, LOGO, C_BLUE, C_ORANGE, C_GREEN, C_GRAY, C_LBLUE, C_RED, C_DARK, C_MUTE, C_BG,
    new_slide, note, para_block, style_chart, color_series, card, box_flow, kpi_strip, wan,
)
from cost_model import build_tiers                                            # noqa: E402
from targets_model import build_targets                                       # noqa: E402

from pptx import Presentation                                                  # noqa: E402
from pptx.chart.data import CategoryChartData                                   # noqa: E402
from pptx.dml.color import RGBColor                                            # noqa: E402
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE                                         # noqa: E402
from pptx.enum.text import PP_ALIGN                                            # noqa: E402
from pptx.util import Inches, Pt                                               # noqa: E402

OUT = "/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本分析_三档目标成本.pptx"
# 老倪 2026-10-28 口述口径，名字按他这版叫法：基础 / 精细 / 专家
CN = {"A": "基础", "B": "精细", "C": "专家"}
COL = {"A": C_BLUE, "B": C_ORANGE, "C": C_GREEN}


def _norm(s):
    """把档位名统一成老倪这一版的叫法 (基础/精细/专家)。"""
    for k, v in CN.items():
        if k in s:
            return v
    return s


def _table(s, x, y, w, rows, col_w=None, h=0.34, head_fill=C_BLUE, size=9.5):
    """统一样式的表格：表头蓝底白字，正文浅底深字。"""
    nr, nc = len(rows), len(rows[0])
    shp = s.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(h * nr))
    tb = shp.table
    if col_w:
        for i, cw in enumerate(col_w):
            tb.columns[i].width = Inches(cw)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tb.cell(r, c)
            cell.text = ""
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if (r == 0 or c > 0) else PP_ALIGN.LEFT
            run = p.add_run()
            run.text = str(val)
            run.font.size = Pt(size)
            run.font.name = "Microsoft YaHei"
            run.font.bold = (r == 0)
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if r == 0 else C_DARK
            cell.fill.solid()
            cell.fill.fore_color.rgb = head_fill if r == 0 else (C_BG if r % 2 else RGBColor(0xFF, 0xFF, 0xFF))
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
    return tb


def _clean_slides(prs):
    lst = prs.slides._sldIdLst
    for sid in list(lst):
        rId = sid.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        prs.part.drop_rel(rId)
        lst.remove(sid)


def main():
    d = build_tiers()
    T = {t["id"]: t for t in d["tiers"]}
    TG = {t["id"]: t for t in build_targets()["tiers"]}
    ids = ["A", "B", "C"]
    pa = d.get("production_assumptions") or {}

    prs = Presentation(TMPL)
    _clean_slides(prs)
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ───────────────────────── 1 封面 ─────────────────────────
    s = prs.slides.add_slide(prs.slide_layouts[0])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(0.55), Inches(0.45), width=Inches(0.52))
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(2.05), Inches(13.333), Inches(0.09))
    band.fill.solid()
    band.fill.fore_color.rgb = C_BLUE
    band.line.fill.background()
    para_block(s, 0.95, 2.32, 11.6, 1.0, [
        ("双臂协作工位 · 三档目标成本分析", C_DARK, 40, True),
    ])
    para_block(s, 0.98, 3.42, 11.6, 1.4, [
        ("基础 %.0f 万（硬件 %.0f + 软件 %.0f）　·　精细 %.0f 万（%.0f + %.0f）　·　专家 %.0f 万（%.0f + %.0f）"
         % (wan(TG["A"]["cost_total"]), wan(TG["A"]["hw_cost"]), wan(TG["A"]["sw_cost"]),
            wan(TG["B"]["cost_total"]), wan(TG["B"]["hw_cost"]), wan(TG["B"]["sw_cost"]),
            wan(TG["C"]["cost_total"]), wan(TG["C"]["hw_cost"]), wan(TG["C"]["sw_cost"])), C_BLUE, 17, True),
        ("只讲成本构成与降本口径，不涉及成交与渠道口径", C_MUTE, 14, False),
    ])
    note(s, "数字唯一依据 tools/spec/cost_targets.json（目标成本）与 tools/spec/cost_model.json（现估 BOM / NRE / 运营 / 节拍）"
            " · 逐项现算：tools/targets_model.build_targets() + tools/cost_model.build_tiers()")

    # ───────────────────────── 2 一页结论 ─────────────────────────
    s = new_slide(prs, "一页结论：三档单套目标成本", "目标成本只分两块 —— 硬件 + 软件；运营与实施另算，不摊进单套")
    for i, k in enumerate(ids):
        t = TG[k]
        card(s, 0.95 + i * 3.86, 1.35, 3.70, 2.05, "%.0f 万" % wan(t["cost_total"]),
             "%s版 · 单套目标成本" % CN[k],
             "硬件 %.0f 万 + 软件 %.0f 万" % (wan(t["hw_cost"]), wan(t["sw_cost"])), COL[k], 34)
    box_flow(s, [
        ("硬件成本", "机器人本体 + 相机 + 夹爪 + 工装 + 主机", C_BLUE),
        ("软件成本", "模型与技能库 + 编排 + 检测 + 授权实现", C_ORANGE),
        ("实施成本", "现场标定 / 集成 / 试产 (NRE)", C_GREEN),
        ("运营成本", "维护 / 备件 / 算力与数据 (年)", C_LBLUE),
    ], y=3.75, h=1.15, x0=0.95, total_w=11.6, hsize=12, bsize=9.5)
    para_block(s, 0.95, 5.10, 11.6, 1.5, [
        ("单套目标成本 = 目标硬件成本 + 目标软件成本；实施（NRE）按三年摊销、运营按年发生，二者不进单套成本，"
         "分别在第 6、7 页单列。", C_DARK, 12, False),
        ("三档的差别只在算力与自由度：基础单臂 ≤30 TOPS；精细双臂 ≤80 TOPS；专家双臂高算力高带宽 ≤300 TOPS。",
         C_MUTE, 11, False),
    ])

    # ───────────────────────── 3 三档目标成本表 ─────────────────────────
    s = new_slide(prs, "三档目标成本分解", "改数字只改 tools/spec/cost_targets.json，本页自动重算")
    rows = [["档位", "形态", "算力", "目标硬件\n(万)", "目标软件\n(万)", "单套成本\n(万)", "软件占成本"]]
    for k in ids:
        t = TG[k]
        rows.append([CN[k] + "版", t["arms"], t["compute"],
                     "%.1f" % wan(t["hw_cost"]), "%.1f" % wan(t["sw_cost"]),
                     "%.1f" % wan(t["cost_total"]), "%.1f%%" % t["sw_share_of_cost"]])
    _table(s, 0.95, 1.35, 11.6, rows, col_w=[1.35, 1.10, 3.75, 1.45, 1.45, 1.45, 1.05], h=0.52, size=11)
    para_block(s, 0.95, 3.85, 11.6, 2.6, [
        ("硬件成本口径：" + " / ".join("%s %s" % (CN[k], TG[k]["hw_desc"]) for k in ids), C_DARK, 11, False),
        ("软件成本口径：" + " / ".join("%s %s" % (CN[k], TG[k]["sw_desc"]) for k in ids), C_DARK, 11, False),
        ("软件占比随档位上升（%.1f%% → %.1f%% → %.1f%%）：能力越靠模型，软件在成本里越重。"
         % (TG["A"]["sw_share_of_cost"], TG["B"]["sw_share_of_cost"], TG["C"]["sw_share_of_cost"]), C_MUTE, 11, False),
    ])
    note(s, "目标硬件/软件成本为老倪 2026-10-28 定稿口径；现估 BOM 与目标之间的差额见第 5 页")

    # ───────────────────────── 4 硬件 vs 软件 柱状 ─────────────────────────
    s = new_slide(prs, "成本构成：每档就是两块", "硬件 = 一次投入的物；软件 = 一次投入的能力")
    cd = CategoryChartData()
    cd.categories = ["%s版" % CN[k] for k in ids]
    cd.add_series("目标硬件成本 (万)", [wan(TG[k]["hw_cost"]) for k in ids])
    cd.add_series("目标软件成本 (万)", [wan(TG[k]["sw_cost"]) for k in ids])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.95), Inches(1.30),
                            Inches(7.35), Inches(4.85), cd)
    ch = gf.chart
    style_chart(ch, 11)
    color_series(ch.plots[0], [C_BLUE, C_ORANGE])
    ch.plots[0].gap_width = 70
    ch.plots[0].overlap = -12
    for ser in ch.plots[0].series:
        ser.data_labels.show_value = True
        ser.data_labels.font.size = Pt(10.5)
        ser.data_labels.font.bold = True
        ser.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    kpi_strip(s, 8.55, 1.30, 4.0, [
        ("基础 单套", "%.0f 万" % wan(TG["A"]["cost_total"])),
        ("精细 单套", "%.0f 万" % wan(TG["B"]["cost_total"])),
        ("专家 单套", "%.0f 万" % wan(TG["C"]["cost_total"])),
        ("软件占比区间", "%.0f%% ~ %.0f%%" % (TG["A"]["sw_share_of_cost"], TG["C"]["sw_share_of_cost"])),
    ], accent=C_ORANGE)
    para_block(s, 8.55, 3.20, 4.0, 2.9, [
        ("同样的硬件平台，能力差在软件：基础到专家，软件成本从 %.0f 万涨到 %.0f 万，"
         % (wan(TG["A"]["sw_cost"]), wan(TG["C"]["sw_cost"])), C_DARK, 11, False),
        ("涨的是模型层数（L2 → L2+L3 → L2+L3+L4/L5）与随之而来的算力、带宽。", C_MUTE, 10.5, False),
    ])

    # ───────────────────────── 5 现估 → 目标：降本缺口 ─────────────────────────
    s = new_slide(prs, "现估成本 → 目标成本：硬件要降多少", "现估 = tools/spec/cost_model.json 的 BOM 单价合计")
    cd = CategoryChartData()
    cd.categories = ["%s版" % CN[k] for k in ids]
    cd.add_series("现估硬件成本 (万)", [wan(TG[k]["bom_capex"]) for k in ids])
    cd.add_series("目标硬件成本 (万)", [wan(TG[k]["hw_cost"]) for k in ids])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.95), Inches(1.30),
                            Inches(7.35), Inches(4.85), cd)
    ch = gf.chart
    style_chart(ch, 11)
    color_series(ch.plots[0], [C_GRAY, C_BLUE])
    for ser in ch.plots[0].series:
        ser.data_labels.show_value = True
        ser.data_labels.font.size = Pt(10.5)
        ser.data_labels.font.bold = True
        ser.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    _table(s, 8.55, 1.30, 4.0, [["档位", "要降(万)", "降幅"]] + [
        ["%s版" % CN[k], "%.1f" % wan(TG[k]["gap_to_bom"]),
         "%.1f%%" % (100.0 * TG[k]["gap_to_bom"] / TG[k]["bom_capex"])] for k in ids
    ], col_w=[1.3, 1.35, 1.35], h=0.42, size=11)
    para_block(s, 8.55, 3.40, 4.0, 2.7, [
        ("硬件降本缺口合计 %.1f 万。" % (sum(TG[k]["gap_to_bom"] for k in ids) / 1e4), C_DARK, 11.5, True),
        ("路径（按贡献排序）：本体与夹爪国产替代、相机从工业级降到车规级 + 自标定、"
         "工装标准化复用、主机按算力分档不做一刀切高配。", C_MUTE, 10.5, False),
    ])

    # ───────────────────────── 6 实施 (NRE) 与摊销 ─────────────────────────
    s = new_slide(prs, "实施投入（NRE）与摊销", "实施不进单套成本，按年摊销后体现在每件成本里")
    rows = [["档位", "实施投入\n(万)", "摊销年限", "年摊销\n(万)", "现估运营\n(万/年)", "每件成本\n(元)"]]
    for k in ids:
        t = T[k]
        rows.append(["%s版" % CN[k], "%.1f" % wan(t["nre_sum"]), "%.0f 年" % t["nre_years"],
                     "%.1f" % wan(t["nre_amort"]), "%.1f" % wan(t["opex_year"]),
                     "%.4f" % t["unit_cost"]])
    _table(s, 0.95, 1.35, 11.6, rows, col_w=[1.55, 1.9, 1.7, 1.9, 2.0, 2.55], h=0.52, size=11)
    para_block(s, 0.95, 3.90, 11.6, 2.5, [
        ("每件成本 = (硬件折旧 ÷ %.0f 年 + 实施摊销 ÷ 摊销年限 + 年度运营) ÷ 年产量。"
         % T["A"]["dep_years"], C_DARK, 12, False),
        ("年产量按 %.0f 小时/年 × OEE 与节拍现算：基础/精细 %s 件、专家 %s 件。"
         % (pa.get("hours_per_year") or T["A"]["hours_per_year"],
            format(T["A"]["pieces_year"], ","), format(T["C"]["pieces_year"], ",")), C_DARK, 12, False),
        ("基础档每件 %.4f 元、精细 %.4f 元、专家 %.4f 元 —— 三档都远低于人工折算 %.2f 元/件。"
         % (T["A"]["unit_cost"], T["B"]["unit_cost"], T["C"]["unit_cost"], T["A"]["labor_per_piece"]),
         C_MUTE, 12, False),
    ])
    note(s, "实施投入含现场标定、集成联调、试产与工艺固化；摊销年限取工程口径，改 json 即重算")

    # ───────────────────────── 7 产能摊薄敏感性 ─────────────────────────
    s = new_slide(prs, "产能摊薄：产量拉起来，单件成本掉下去", "固定投入（折旧 + 实施摊销）按产量均摊，运营按年发生")
    ratios = [0.5, 1.0, 1.5]
    cd = CategoryChartData()
    cd.categories = ["%.0f%% 产能" % (r * 100) for r in ratios]
    for k in ids:
        t = T[k]
        fixed = t["dep_year"] + t["nre_amort"]
        cd.add_series("%s版 (元/件)" % CN[k],
                      [round(fixed / (t["pieces_year"] * r) + t["opex_year"] / t["pieces_year"], 4) for r in ratios])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.95), Inches(1.30),
                            Inches(8.0), Inches(4.85), cd)
    ch = gf.chart
    style_chart(ch, 11)
    for ser, k in zip(ch.plots[0].series, ids):
        ser.format.line.color.rgb = COL[k]
        ser.format.line.width = Pt(2.25)
        ser.data_labels.show_value = True
        ser.data_labels.font.size = Pt(9)
        ser.data_labels.position = XL_LABEL_POSITION.ABOVE
    para_block(s, 9.15, 1.30, 3.4, 3.6, [
        ("产量是唯一的放大器", C_DARK, 13, True),
        ("固定投入不变，产量翻一倍，固定部分摊薄一半。三档在半产能时单件成本约为满产的 1.8 倍。",
         C_MUTE, 10.5, False),
        ("所以降本有两条腿：压 BOM（第 5 页）与提产量（本页），后者不需要再投研发。", C_MUTE, 10.5, False),
    ])

    # ───────────────────────── 8 每件成本 vs 人工 ─────────────────────────
    s = new_slide(prs, "每件成本与人工折算的比较", "口径：人工折算 %.2f 元/件（含社保与班次管理）" % T["A"]["labor_per_piece"])
    cd = CategoryChartData()
    cd.categories = ["人工 (现在)", "%s版" % CN["A"], "%s版" % CN["B"], "%s版" % CN["C"]]
    cd.add_series("每件成本 (元)", [T["A"]["labor_per_piece"]] + [T[k]["unit_cost"] for k in ids])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.95), Inches(1.30),
                            Inches(7.6), Inches(4.85), cd)
    ch = gf.chart
    style_chart(ch, 11, legend=False)
    color_series(ch.plots[0], [C_GRAY, C_BLUE, C_ORANGE, C_GREEN])
    ch.plots[0].gap_width = 55
    for ser in ch.plots[0].series:
        ser.data_labels.show_value = True
        ser.data_labels.font.size = Pt(11)
        ser.data_labels.font.bold = True
        ser.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
    _table(s, 8.80, 1.30, 3.75, [["口径", "每件成本", "相对人工"]] + [
        [CN[k] + "版", "%.4f 元" % T[k]["unit_cost"],
         "%.1f%%" % (100.0 * T[k]["unit_cost"] / T["A"]["labor_per_piece"])] for k in ids
    ], col_w=[1.15, 1.35, 1.25], h=0.44, size=10.5)
    para_block(s, 8.80, 3.50, 3.75, 2.5, [
        ("成本口径，不是成交口径", C_DARK, 12, True),
        ("每件成本含硬件折旧、实施摊销与运营，不含任何成交加价；与人工折算直接比即为成本代差。",
         C_MUTE, 10.5, False),
    ])

    # ───────────────────────── 9 成本控制与验收 ─────────────────────────
    s = new_slide(prs, "成本控制与验收口径", "每条都指向一个可核的数字来源")
    box_flow(s, [
        ("目标成本", "硬件 %.0f/%.0f/%.0f 万\n软件 %.0f/%.0f/%.0f 万"
         % (wan(TG["A"]["hw_cost"]), wan(TG["B"]["hw_cost"]), wan(TG["C"]["hw_cost"]),
            wan(TG["A"]["sw_cost"]), wan(TG["B"]["sw_cost"]), wan(TG["C"]["sw_cost"])), C_BLUE),
        ("现估 BOM", "硬件 %.1f/%.1f/%.1f 万"
         % (wan(TG["A"]["bom_capex"]), wan(TG["B"]["bom_capex"]), wan(TG["C"]["bom_capex"])), C_GRAY),
        ("降本缺口", "%.1f/%.1f/%.1f 万"
         % (wan(TG["A"]["gap_to_bom"]), wan(TG["B"]["gap_to_bom"]), wan(TG["C"]["gap_to_bom"])), C_RED),
        ("验收", "供应商正式核价\n逐项对 BOM 行", C_GREEN),
    ], y=1.40, h=1.35, x0=0.95, total_w=11.6, hsize=12, bsize=10)
    para_block(s, 0.95, 3.10, 11.6, 3.3, [
        ("① 目标成本：老倪定稿口径，写在 tools/spec/cost_targets.json，页面/PPT 只读不算。", C_DARK, 12, False),
        ("② 现估成本：tools/spec/cost_model.json 的 BOM 单价 + NRE 明细，全部标注为市场参考口径，供应商未正式核价。",
         C_DARK, 12, False),
        ("③ 降本缺口：现估 − 目标，按档位分别考核；核价到手后只改 json，本 PPT 与配置中心同步重算。",
         C_DARK, 12, False),
        ("④ 不含项（免得把账做漂亮）：模具与治具的二次开模、场地改造、现场停机损失、售后备件库存占用。",
         C_MUTE, 11, False),
    ])

    # ───────────────────────── 10 风险与边界 ─────────────────────────
    s = new_slide(prs, "成本的四个不确定项", "写清楚不确定，账才可信")
    box_flow(s, [
        ("BOM 单价", "供应商未正式核价\n市场参考口径", C_BLUE),
        ("算力档位", "专家档 300 TOPS\n高带宽链路溢价", C_ORANGE),
        ("实施工时", "现场标定与集成\n按项目实际", C_GREEN),
        ("产量", "半产能时\n单件成本 ×1.8", C_LBLUE),
    ], y=1.40, h=1.35, x0=0.95, total_w=11.6, hsize=12, bsize=10)
    para_block(s, 0.95, 3.10, 11.6, 3.2, [
        ("这四项都不影响三档之间的相对关系：软件占比随档位上升、单件成本随产量下降，方向不随单价浮动改变。",
         C_DARK, 12, False),
        ("任何一项发生变化，只改 tools/spec/*.json 与 tools/spec/cost_targets.json，本 PPT 重新生成即同步。",
         C_MUTE, 11, False),
    ])
    note(s, "本册只做成本分析；需要市场侧口径另出一册")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print("✅ 已生成 %s" % OUT)
    print("   页数 %d · 单套目标成本 基础 %.1f / 精细 %.1f / 专家 %.1f 万"
          % (len(prs.slides._sldIdLst), wan(TG["A"]["cost_total"]), wan(TG["B"]["cost_total"]),
             wan(TG["C"]["cost_total"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
