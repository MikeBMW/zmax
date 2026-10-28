#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《双臂协作工位 · 成本结构与市场分成预期》—— 愿景 + 全图表版 (v3)。

三轮要求叠在一起:
  ① 图表化: 饼图/方框图/比例图/趋势图/柱状图, 不要只列数字表格; 不出现"任务7"式编号文字, 用完整句子。
  ② 不再定死售价: 三档目标成本 (15+5 / 20+10 / 22+15 万) + 建议毛利空间; 客户红线 30/40/55 万只作上界。
  ③ 产品愿景统一: 先用「让工业机器人干精密活 · 最后一厘米」开场, 再给八步链路 (产品定义→任务→功能→
     模型→性能→工程→成本组成→市场分成), 让成本与分成落在愿景里, 而不是孤立的账。
  ④ 版面复核意见已修: 封面标题与副标题拉开、折线基础型改虚线且只给专业型打标签、环形图关掉扇区内百分比
     改成环下写确切比例、卡片文案缩短避免孤字、脚注加深、标题"三个"与四张卡不一致已改。

数字真源: tools/cost_model.build_tiers() · 愿景真源: tools/spec/vision.json (与配置中心愿景带、ar3d 愿景条同源)。
产出: /home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx
跑法: gui-venv311/bin/python tools/build_market_deck.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from cost_model import build_tiers                                             # noqa: E402

from pptx import Presentation                                                  # noqa: E402
from pptx.chart.data import CategoryChartData                                   # noqa: E402
from pptx.dml.color import RGBColor                                            # noqa: E402
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_LABEL_POSITION  # noqa: E402
from pptx.enum.dml import MSO_LINE_DASH_STYLE                                   # noqa: E402
from pptx.enum.shapes import MSO_SHAPE                                         # noqa: E402
from pptx.enum.text import PP_ALIGN                                            # noqa: E402
from pptx.util import Inches, Pt                                               # noqa: E402

TMPL = "/home/ubuntu/zmax_data/deliverables/模板.pptx"
LOGO = "/home/ubuntu/zmax_data/deliverables/_tmpl_media/Picture_2_image.png"
OUT = "/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx"
VISION = os.path.join(ROOT, "tools", "spec", "vision.json")

C_BLUE = RGBColor(0x44, 0x72, 0xC4)
C_ORANGE = RGBColor(0xED, 0x7D, 0x31)
C_GRAY = RGBColor(0xA5, 0xA5, 0xA5)
C_LBLUE = RGBColor(0x5B, 0x9B, 0xD5)
C_GREEN = RGBColor(0x70, 0xAD, 0x47)
C_RED = RGBColor(0xC0, 0x50, 0x4D)
C_DARK = RGBColor(0x2B, 0x31, 0x37)
C_MUTE = RGBColor(0x6B, 0x72, 0x80)
C_BG = RGBColor(0xF7, 0xF8, 0xFA)
COL3 = [C_BLUE, C_ORANGE, C_GREEN]
NAMES = ["基础型", "精细型", "专业型"]
X0, GAPC, WC = 0.95, 0.16, 3.70


def wan(x):
    return float(x or 0) / 1e4


def vision_spec():
    try:
        return json.load(open(VISION, encoding="utf-8"))
    except Exception:                                                           # noqa: BLE001
        return {}


def new_slide(prs, title, kicker=""):
    s = prs.slides.add_slide(prs.slide_layouts[0])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(0.30), Inches(0.26), width=Inches(0.40))
    tb = s.shapes.add_textbox(Inches(0.85), Inches(0.20), Inches(11.9), Inches(0.66))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.size = Pt(23)
    r.font.bold = True
    r.font.color.rgb = C_DARK
    r.font.name = "Microsoft YaHei"
    ln = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.88), Inches(0.90), Inches(1.15), Inches(0.05))
    ln.fill.solid()
    ln.fill.fore_color.rgb = C_BLUE
    ln.line.fill.background()
    if kicker:
        kb = s.shapes.add_textbox(Inches(2.15), Inches(0.84), Inches(10.6), Inches(0.34))
        kp = kb.text_frame.paragraphs[0]
        kr = kp.add_run()
        kr.text = kicker
        kr.font.size = Pt(11)
        kr.font.color.rgb = C_MUTE
        kr.font.name = "Microsoft YaHei"
    fb = s.shapes.add_textbox(Inches(11.05), Inches(7.02), Inches(2.0), Inches(0.3))
    fp = fb.text_frame.paragraphs[0]
    fp.alignment = PP_ALIGN.RIGHT
    fr = fp.add_run()
    fr.text = "© ReinBee All Rights Reserved."
    fr.font.size = Pt(8)
    fr.font.color.rgb = C_MUTE
    fr.font.name = "Arial"
    return s


def note(s, text, x=0.96, y=6.86, w=11.72, h=0.36):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.size = Pt(9.5)
    r.font.color.rgb = C_MUTE
    r.font.name = "Microsoft YaHei"


def para_block(s, x, y, w, h, lines):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (txt, col, size, bold) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(size)
        r.font.color.rgb = col
        r.font.bold = bold
        r.font.name = "Microsoft YaHei"
        p.space_after = Pt(8)
    return tb


def style_chart(ch, size=10.5, legend=True, left=True):
    ch.font.size = Pt(size)
    ch.font.name = "Microsoft YaHei"
    ch.has_legend = legend
    if legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
    ch.category_axis.tick_labels.font.size = Pt(size)
    ch.category_axis.format.line.color.rgb = RGBColor(0xD0, 0xD4, 0xD9)
    if left:
        ch.value_axis.tick_labels.font.size = Pt(size)
        ch.value_axis.has_major_gridlines = True
        ch.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE6, 0xE9, 0xED)


def color_series(plot, colors):
    for i, ser in enumerate(plot.series):
        if i < len(colors):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = colors[i]
            if ser.format.line is not None:
                ser.format.line.color.rgb = colors[i]


def card(s, x, y, w, h, big, label, ctext, color=C_BLUE, bigsize=26, csize=9.5):
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    box.fill.solid()
    box.fill.fore_color.rgb = C_BG
    box.line.color.rgb = RGBColor(0xE1, 0xE5, 0xEA)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_top = Inches(0.08)
    tf.margin_bottom = Inches(0.06)
    for i, (txt, size, bold, col) in enumerate([(big, bigsize, True, color), (label, 11, False, C_DARK),
                                                (ctext, csize, False, C_MUTE)]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = col
        r.font.name = "Microsoft YaHei"
    return box


def box_flow(s, items, y=2.0, h=1.05, gap=0.28, x0=0.85, total_w=11.9, hsize=12, bsize=9.5):
    n = len(items)
    w = (total_w - gap * (n - 1)) / n
    x = x0
    for i, (head, body, col) in enumerate(items):
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        b.fill.solid()
        b.fill.fore_color.rgb = C_BG
        b.line.color.rgb = col
        b.line.width = Pt(1.5)
        b.shadow.inherit = False
        tf = b.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.04)
        tf.margin_right = Inches(0.04)
        for j, (txt, size, bold, c2) in enumerate([(head, hsize, True, col), (body, bsize, False, C_DARK)]):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = txt
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = c2
            r.font.name = "Microsoft YaHei"
        if i < n - 1:
            ar = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + w + 0.01),
                                    Inches(y + h / 2 - 0.09), Inches(gap - 0.04), Inches(0.18))
            ar.fill.solid()
            ar.fill.fore_color.rgb = RGBColor(0xC9, 0xCE, 0xD4)
            ar.line.fill.background()
        x += w + gap



def kpi_strip(s, x, y, w, rows, accent=C_BLUE):
    """右栏底部的小数字条: 填掉文字栏下半截空白, 让左右两栏视觉等高 (复核意见)。"""
    h = 0.30 + 0.34 * len(rows)
    b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    b.fill.solid()
    b.fill.fore_color.rgb = C_BG
    b.line.color.rgb = RGBColor(0xE1, 0xE5, 0xEA)
    b.shadow.inherit = False
    tf = b.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.14)
    tf.margin_right = Inches(0.10)
    tf.margin_top = Inches(0.06)
    tf.margin_bottom = Inches(0.04)
    for i, (k, v) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r1 = p.add_run()
        r1.text = k + "　"
        r1.font.size = Pt(9.5)
        r1.font.color.rgb = C_MUTE
        r1.font.name = "Microsoft YaHei"
        r2 = p.add_run()
        r2.text = v
        r2.font.size = Pt(10)
        r2.font.bold = True
        r2.font.color.rgb = accent
        r2.font.name = "Microsoft YaHei"
        p.space_after = Pt(3)
    return b

def targets():
    """三档目标成本 + 建议利润空间 (唯一算法 tools/targets_model.py)。"""
    import sys as _sys
    _tp = os.path.dirname(os.path.abspath(__file__))
    if _tp not in _sys.path:
        _sys.path.insert(0, _tp)
    from targets_model import build_targets
    return build_targets()["tiers"]


def rollout():
    """市场策略三阶段 (唯一算法 tools/rollout_model.py)。"""
    import sys as _sys
    _tp = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    if _tp not in _sys.path:
        _sys.path.insert(0, _tp)
    from rollout_model import build_rollout
    return build_rollout()["phases"]


def main():
    d = build_tiers()
    T = d["tiers"]
    S = d["split"]
    TG = targets()
    v = vision_spec()
    vs = v.get("vision") or {}
    pillars = v.get("pillars") or []
    spine = v.get("spine") or []
    labor = T[0]["labor_per_piece"]

    prs = Presentation(TMPL)
    sldIdLst = prs.slides._sldIdLst
    for sldId in list(sldIdLst):
        rId = sldId.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        prs.part.drop_rel(rId)
        sldIdLst.remove(sldId)
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ── 1 封面
    s = prs.slides.add_slide(prs.slide_layouts[0])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    if os.path.exists(LOGO):
        s.shapes.add_picture(LOGO, Inches(0.55), Inches(0.45), width=Inches(0.52))
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(2.10), Inches(13.333), Inches(0.09))
    band.fill.solid()
    band.fill.fore_color.rgb = C_BLUE
    band.line.fill.background()
    t1 = s.shapes.add_textbox(Inches(0.95), Inches(2.40), Inches(11.6), Inches(0.95))
    tf1 = t1.text_frame
    tf1.word_wrap = True
    r = tf1.paragraphs[0].add_run()
    r.text = vs.get("headline") or "让工业机器人干精密活"
    r.font.size = Pt(40)
    r.font.bold = True
    r.font.color.rgb = C_DARK
    r.font.name = "Microsoft YaHei"
    t2 = s.shapes.add_textbox(Inches(0.98), Inches(3.60), Inches(11.6), Inches(0.66))
    tf2 = t2.text_frame
    tf2.word_wrap = True
    r2 = tf2.paragraphs[0].add_run()
    r2.text = (vs.get("subline") or "把工厂里最难的那一厘米，交给设备自己完成") + "　——　成本结构与市场分成预期"
    r2.font.size = Pt(17)
    r2.font.color.rgb = C_BLUE
    r2.font.name = "Microsoft YaHei"
    para_block(s, 0.98, 4.55, 11.4, 1.8, [
        ("测算基线：单件节拍 11.4 秒，稳定产能每小时 315 件，每轮 14 件、392 段动作，插入行程 47 毫米", C_MUTE, 11.5, False),
        ("定价前提：基础型整套不超过三十万元，精细型不超过四十万元，专业型不超过五十五万元", C_MUTE, 11.5, False),
        ("单价与人工成本按 2026 年市场口径估算，供应商正式报价到位后模型随之更新", C_MUTE, 11.5, False),
    ])
    ft = s.shapes.add_textbox(Inches(11.05), Inches(7.02), Inches(2.0), Inches(0.3))
    fp = ft.text_frame.paragraphs[0]
    fp.alignment = PP_ALIGN.RIGHT
    fr = fp.add_run()
    fr.text = "© ReinBee All Rights Reserved."
    fr.font.size = Pt(8)
    fr.font.color.rgb = C_MUTE
    fr.font.name = "Arial"

    # ── 2 愿景与三条护城河
    s = new_slide(prs, "要解决的不是「能不能动」，而是「每一次都得一样」",
                  "产品愿景与三条护城河 —— 后面八页的成本与分成，都是为这件事算账")
    tb = s.shapes.add_textbox(Inches(0.96), Inches(1.45), Inches(7.2), Inches(2.6))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (txt, col, size, bold) in enumerate([
        (vs.get("problem") or "工人一个班重复上千次同样的动作，难的不是动作本身，是每一次都得一样。", C_DARK, 12.5, False),
        (vs.get("answer") or "机械臂擅长重复，遇到来料偏三毫米、姿态歪两度就停下来等人；我们让它把这最后一厘米自己处理掉。",
         C_BLUE, 12.5, True),
    ]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(size)
        r.font.color.rgb = col
        r.font.bold = bold
        r.font.name = "Microsoft YaHei"
        p.space_after = Pt(12)
    for k, pl in enumerate(pillars[:3]):
        y = 1.45 + k * 1.62
        b = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.30), Inches(y), Inches(4.20), Inches(1.42))
        b.fill.solid()
        b.fill.fore_color.rgb = C_BG
        b.line.color.rgb = COL3[k]
        b.line.width = Pt(1.6)
        b.shadow.inherit = False
        tf = b.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0.14)
        tf.margin_right = Inches(0.12)
        for j, (txt, size, bold, c2) in enumerate([(pl.get("name", ""), 12, True, COL3[k]),
                                                  (pl.get("one_line", ""), 9.5, False, C_DARK),
                                                  (pl.get("evidence", ""), 8.5, False, C_MUTE)]):
            p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
            r = p.add_run()
            r.text = ("0%d　" % (k + 1) if j == 0 else "") + txt
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = c2
            r.font.name = "Microsoft YaHei"
    kpi_strip(s, 0.96, 4.62, 7.01, [
        ("节拍 / 产能", "11.39 s/件 · 315.2 件/h"),
        ("插入行程 / 速度", "47 mm @ 156.7 mm/s"),
        ("力上限 / 像素当量", "40 N · 0.76 mm/px @300mm"),
    ], C_BLUE)
    note(s, "愿景真源 tools/spec/vision.json：配置中心每页顶部的愿景带、ar3d 屏幕下方的愿景条、这份材料，读的是同一个文件。")

    # ── 3 八步链路
    s = new_slide(prs, "从一个动作单元到一份报价，中间有八步，每一步都能被数出来",
                  "上排八步与配置中心的八个环节一一对应；每步下面挂一个可核对的数字")
    sw_min = min(TG[k]["pct_capped"]["sw"] for k in range(3))
    sw_max = max(TG[k]["pct_capped"]["sw"] for k in range(3))
    nums = ["550A / B / C", "7 个动作单元", "33 个功能", "L2 ~ L5",
            "%.0f 件/h" % d["uph_geo"], "25 步 WI",
            "%.1f ~ %.1f 万" % (wan(TG[0]["cost_total"]), wan(TG[2]["cost_total"])),
            "%.0f%% ~ %.0f%%" % (sw_min, sw_max)]
    steps = []
    for i, st in enumerate(spine[:8]):
        steps.append(("%d %s" % (st.get("step", i + 1), st.get("title", "")), nums[i], COL3[i % 3]))
    box_flow(s, steps, y=1.55, h=1.15, gap=0.18, x0=0.96, total_w=11.40, hsize=9.5, bsize=8.5)
    para_block(s, 0.96, 3.05, 11.40, 3.4, [
        ("这条链路为什么重要", C_DARK, 14, True),
        ("左边四步决定「能不能干」：产品定义划出精度边界，任务配置把工序拆成七个可复用动作单元，"
         "功能配置给每个单元配上输入输出与实现，模型配置把能力分到 L2 到 L5 四层。", C_DARK, 10.5, False),
        ("右边四步决定「值多少钱」：性能配置把节拍、行程、力量、像素当量写成可测量，"
         "工程配置把它变成客户现场二十五步能复测的手册，成本组成与市场分成才是这笔账的落点。", C_DARK, 10.5, False),
        ("八步里任何一步空着，后面报出来的数就是空的 —— 这也是我们不给客户只报一个总价的原因。", C_ORANGE, 11, True),
    ])
    for k, (big, lab, sub) in enumerate([
        ("8 个环节", "从产品定义到市场分成", "每一环都有真源与判据，缺一环后面就空"),
        ("33 个功能 · 107 行", "功能 × 模型对应", "每个功能有输入输出与可定位实现"),
        ("25 步操作手册", "三档工程配置", "客户能按手册自己复测节拍与良率"),
    ]):
        card(s, X0 + k * (WC + GAPC), 5.02, WC, 1.30, big, lab, sub, COL3[k], 20, 9)
    note(s, "八个环节与配置中心八个页签同一套命名；ar3d 的愿景条把这条链路压成四个闭环环节（看、判、动、验）实时演示。")

    # ── 4 一页结论
    s = new_slide(prs, "成本目标定死之后，三档的差别不在毛利厚度，而在能力边界",
                  "只给建议利润空间，不写死售价：报价由销售在区间内与客户谈")
    for k, t in enumerate(TG):
        x = X0 + k * (WC + GAPC)
        card(s, x, 1.42, WC, 1.66, "%.1f ~ %.1f 万" % (t["price_lo"] / 1e4, t["price_hi"] / 1e4),
             "%s建议报价区间" % NAMES[k],
             "%s · 单套成本 %.1f 万" % (t["arms"], t["cost_total"] / 1e4), COL3[k], 21, 9.5)
        card(s, x, 3.20, WC, 1.66, "%.1f%% ~ %.1f%%" % (t["gross_pct_lo"], t["gross_pct_hi"]),
             "%s建议利润空间" % NAMES[k],
             "硬件 25~30%% · 软件 45~55%% · 红线 %.0f 万" % (t["cap_ref"] / 1e4), COL3[k], 21, 9.5)
        card(s, x, 4.98, WC, 1.10, "%.1f 万" % (t["cost_total"] / 1e4),
             "%s单套目标成本" % NAMES[k],
             "硬件 %.1f + 软件 %.1f" % (t["hw_cost"] / 1e4, t["sw_cost"] / 1e4), COL3[k], 22, 9)
    note(s, "三档成本目标：基础型硬件十五万加软件五万，精细型二十万加十万，专业型二十二万加十五万；"
            "按此目标，红线内的实际毛利是 %.1f%% / %.1f%% / %.1f%%。"
            % tuple(TG[k]["pct_at_cap"] for k in range(3)))

    # ── 5 建议利润空间
    s = new_slide(prs, "利润空间不是拍出来的，是由目标成本与客户红线夹出来的",
                  "单位：万元；柱为单套目标成本、建议报价下限与上限，红线是客户可接受的上界")
    cd = CategoryChartData()
    cd.categories = NAMES
    cd.add_series("单套目标成本", [round(t["cost_total"] / 1e4, 1) for t in TG])
    cd.add_series("建议报价下限", [round(t["price_lo"] / 1e4, 1) for t in TG])
    cd.add_series("建议报价上限", [round(t["price_hi"] / 1e4, 1) for t in TG])
    cd.add_series("客户红线", [round(t["cap_ref"] / 1e4, 1) for t in TG])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.96), Inches(1.32),
                            Inches(7.22), Inches(5.0), cd)
    ch = gf.chart
    style_chart(ch, 10)
    color_series(ch.plots[0], [C_GRAY, C_LBLUE, C_BLUE, C_RED])
    ch.plots[0].has_data_labels = True
    ch.plots[0].data_labels.number_format = '0.0'
    ch.plots[0].data_labels.number_format_is_linked = False
    ch.plots[0].data_labels.font.size = Pt(8.5)
    ch.plots[0].gap_width = 60
    para_block(s, 8.25, 1.42, 4.45, 3.6, [
        ("为什么不定售价", C_DARK, 14, True),
        ("基础型成本二十万，按三成左右毛利应报二十九到三十二万，但客户红线是三十万，所以只能在三十万顶格，"
         "实际毛利三成三。", C_DARK, 10, False),
        ("精细型是最紧的一档：成本三十万、红线四十万，顶格卖也只有两成半毛利。要拿到三成，"
         "单套成本必须压到二十八万以内。", C_ORANGE, 10, False),
        ("专业型成本三十七万、红线五十五万，顶格毛利三成三，是三档里空间最舒服的。", C_DARK, 10, False),
        ("对销售的建议：先守住红线内毛利，再谈装机数量换价格。", C_ORANGE, 10.5, True),
    ])
    kpi_strip(s, 8.25, 5.12, 4.45, [
        ("红线内实际毛利", "%.1f%% / %.1f%% / %.1f%%" % tuple(t["pct_at_cap"] for t in TG)),
        ("要降的目标成本差", "%.1f / %.1f / %.1f 万" % tuple(t["gap_to_bom"] / 1e4 for t in TG)),
        ("软件占单套成本", "%.0f%% / %.0f%% / %.0f%%" % tuple(t["sw_share_of_cost"] for t in TG)),
    ], C_BLUE)
    note(s, "四根柱依次是：单套目标成本、建议报价下限、建议报价上限、客户红线。上限高于红线时按红线报，毛利空间自动被压薄。")

    # ── 6 投入结构
    s = new_slide(prs, "一套工位的钱主要花在设备上，实施投入随智能化程度快速上升",
                  "单位：万元；同一坐标系下对比三档配置")
    cd = CategoryChartData()
    cd.categories = NAMES
    cd.add_series("设备与硬件", [round(wan(t["capex"]), 1) for t in T])
    cd.add_series("实施与训练", [round(wan(t["nre_sum"]), 1) for t in T])
    cd.add_series("年度运营支出", [round(wan(t["opex_year"]), 1) for t in T])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_STACKED, Inches(0.96), Inches(1.32),
                            Inches(7.22), Inches(5.0), cd)
    ch = gf.chart
    style_chart(ch, 10.5)
    color_series(ch.plots[0], [C_BLUE, C_ORANGE, C_GRAY])
    ch.plots[0].has_data_labels = True
    ch.plots[0].data_labels.number_format = '0.0'
    ch.plots[0].data_labels.number_format_is_linked = False
    ch.plots[0].data_labels.font.size = Pt(9)
    ch.plots[0].gap_width = 90
    para_block(s, 8.25, 1.42, 4.45, 5.3, [
        ("投入结构的三句话", C_DARK, 14, True),
        ("硬件是共同底座，三档差别主要落在算力：三十万亿次以内、八十万亿次级、三百万亿次以内。",
         C_DARK, 10.5, False),
        ("实施投入从九万跃到五十三万：数据采集十二万、模型训练与权重合并二十二万、安全验证与认证二十一万。",
         C_DARK, 10.5, False),
        ("年度运营支出基本持平，说明这套方案的钱是一次性投入，不是靠后期慢慢消耗。", C_ORANGE, 11.5, True),
    ])
    kpi_strip(s, 8.25, 5.28, 4.45, [
        ("硬件投入", "%.1f / %.1f / %.1f 万" % tuple(wan(T[i]["capex"]) for i in range(3))),
        ("实施投入", "%.1f / %.1f / %.1f 万" % tuple(wan(T[i]["nre_sum"]) for i in range(3))),
        ("年度运营", "%.1f / %.1f / %.1f 万" % tuple(wan(T[i]["opex_year"]) for i in range(3))),
    ], C_ORANGE)
    note(s, "硬件按市场参考价估算，实施按人天计价，运营支出含电费、维保、耗材与少量值守人工。")

    # ── 7 客户视角
    s = new_slide(prs, "客户真正比较的是每件产品的总持有成本，而不是设备标价",
                  "单位：元/件；灰柱是客户今天付给人工的成本，彩柱是采用方案后的总持有成本")
    cd = CategoryChartData()
    cd.categories = NAMES
    cd.add_series("人工折算成本", [round(labor, 3) for _ in T])
    cd.add_series("方案单件总成本", [round(t["client_unit_cost"], 3) for t in T])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.96), Inches(1.32),
                            Inches(7.22), Inches(5.0), cd)
    ch = gf.chart
    style_chart(ch, 10.5)
    color_series(ch.plots[0], [C_GRAY, C_GREEN])
    ch.plots[0].has_data_labels = True
    ch.plots[0].data_labels.number_format = '0.000'
    ch.plots[0].data_labels.number_format_is_linked = False
    ch.plots[0].data_labels.font.size = Pt(10)
    ch.plots[0].gap_width = 80
    para_block(s, 8.25, 1.42, 4.45, 5.3, [
        ("三档分别替客户省下多少", C_DARK, 14, True),
        ("基础型把每件成本从三角六分压到一角零二，省七成二；精细型压到一角六分三，省五成五；专业型一角九分三，省四成七。",
         C_DARK, 10.5, False),
        ("专业型省得少，是因为卖的不是便宜，而是夜班无人、异常自恢复与质量担保；停机一次的损失远大于每件几分钱。",
         C_DARK, 10.5, False),
        ("谈判时先算这笔账，再谈设备价。", C_ORANGE, 11.5, True),
    ])
    kpi_strip(s, 8.25, 5.28, 4.45, [
        ("客户单件", "%.3f / %.3f / %.3f 元" % tuple(T[i]["client_unit_cost"] for i in range(3))),
        ("比人工省", "%.0f%% / %.0f%% / %.0f%%" % tuple(T[i]["client_save_pct"] for i in range(3))),
        ("人工基准", "%.2f 元/件" % labor),
    ], C_GREEN)
    note(s, "方案单件总成本含设备折旧、软件许可与运营服务费；若客户不买设备而选按件代运营，则按每件三角五至五角五计价。")

    # ── 8 产能爬坡
    s = new_slide(prs, "产能爬坡决定回本速度，前三个月是现金流最紧的窗口",
                  "累计产量按达产节拍推算，单位：万件；基础型与精细型节拍相同、两线重合，故基础型画虚线")
    cd = CategoryChartData()
    cd.categories = ["第一个月", "第三个月", "第六个月", "第九个月", "第十二个月"]
    for k, t in enumerate(T[:2]):                # 基础型与精细型节拍相同, 只画一条, 避免两条重合
        monthly = t["pieces_year"] / 12.0 / 1e4
        if k == 0:
            cd.add_series("基础型 / 精细型（节拍相同）", [round(monthly * m, 1) for m in (1, 3, 6, 9, 12)])
    monthly_c = T[2]["pieces_year"] / 12.0 / 1e4
    cd.add_series("专业型", [round(monthly_c * m, 1) for m in (1, 3, 6, 9, 12)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.96), Inches(1.45),
                            Inches(8.02), Inches(4.8), cd)
    ch = gf.chart
    style_chart(ch, 10.5)
    for i, ser in enumerate(ch.plots[0].series):
        ser.format.line.color.rgb = [C_BLUE, C_GREEN][i]
        ser.smooth = False
        ser.format.line.width = Pt(3.2) if i else Pt(2.6)
        if i == 1:
            ser.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    ch.plots[0].has_data_labels = False
    ser2 = ch.plots[0].series[1]
    ser2.data_labels.show_value = True
    ser2.data_labels.number_format = '0.0'
    ser2.data_labels.number_format_is_linked = False
    ser2.data_labels.font.size = Pt(9)
    ser2.data_labels.position = XL_LABEL_POSITION.ABOVE
    para_block(s, 9.05, 1.55, 3.7, 4.7, [
        ("为什么要看这条线", C_DARK, 14, True),
        ("设备买回来不等于马上满产：第一周标定试跑，第一个月跑通节拍与良率，第三个月才敢开夜班。",
         C_DARK, 10.5, False),
        ("年产量分别是一百二十九万件、一百二十九万件与一百六十六万件，专业型多出的部分来自夜班与更高效率。",
         C_DARK, 10.5, False),
        ("商务上要让客户接受爬坡期约定，而不是签约即承诺满产。", C_MUTE, 10.5, False),
    ])
    note(s, "累计产量 = 达产月产量 × 月份数，未扣爬坡损失；真实首月通常只有五到七成，因此这一页是上限视角。")

    # ── 9 收入构成
    s = new_slide(prs, "同样的工位，收钱的方式决定了三年后的收入曲线",
                  "以精细型首年为例：设备款、软件许可、运营服务三段收入")
    t1 = T[1]
    p1 = TG[1]
    lic_year = t1["license_upfront"] + t1["pieces_year"] * t1["license_per_piece"]
    ops_year = t1["pieces_year"] * t1["ops_fee_per_piece"]
    cd = CategoryChartData()
    cd.categories = ["设备与实施款", "软件许可", "运营服务"]
    cd.add_series("首年收入", [round(wan(p1["price_rec"]), 1), round(wan(lic_year), 1), round(wan(ops_year), 1)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.PIE, Inches(0.96), Inches(1.42), Inches(5.55), Inches(4.85), cd)
    ch = gf.chart
    ch.font.size = Pt(11)
    ch.font.name = "Microsoft YaHei"
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    pl = ch.plots[0]
    pl.has_data_labels = True
    pl.data_labels.show_percentage = True
    pl.data_labels.number_format = '0.0%'
    pl.data_labels.number_format_is_linked = False
    pl.data_labels.font.size = Pt(11)
    pl.data_labels.font.bold = True
    for i, pt in enumerate(pl.series[0].points):
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = COL3[i]
    para_block(s, 6.8, 1.42, 5.9, 5.2, [
        ("一次性收入与持续收入怎么配", C_DARK, 14, True),
        ("只卖设备，收入在交付那年就到顶；改成设备加许可加运营，同一个客户每年都会再产生一笔与产量挂钩的收入。",
         C_DARK, 10.5, False),
        ("精细型首年结构是设备款 %.1f 万、许可 %.1f 万、运营 %.1f 万，许可与运营合计已占两成以上。"
         % (wan(p1["price_rec"]), wan(lic_year), wan(ops_year)), C_DARK, 10.5, False),
        ("许可在两年半左右就把实施投入收回来，这是这套商业模式能成立的前提。", C_DARK, 10.5, False),
        ("把许可与运营写进合同，一次性生意就变成随客户产能成长的长期生意。", C_ORANGE, 11.5, True),
    ])
    note(s, "许可费 = 建议报价的六个点一次性 + 软件成本按五年摊销另加四成毛利；运营费 = 年度运营支出另加两成半毛利。")

    # ── 10 三方分成
    s = new_slide(prs, "收益按毛利贡献在三方之间分配，档位越高软件的分量越重",
                  "从左到右依次为基础型、精细型、专业型；环下写出确切比例，避免小扇区标签压线")
    for k, (tid, title) in enumerate(zip("ABC", NAMES)):
        pct = TG[k]["pct_capped"]
        cd = CategoryChartData()
        cd.categories = ["机器人本体硬件", "模型与软件", "运营与数据"]
        cd.add_series("分成", [pct["hw"], pct["sw"], pct["op"]])
        x = 0.96 + k * 3.925
        gf = s.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Inches(x), Inches(1.42),
                                Inches(3.55), Inches(3.35), cd)
        ch = gf.chart
        ch.font.size = Pt(9.5)
        ch.font.name = "Microsoft YaHei"
        ch.has_legend = True
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(9)
        pl = ch.plots[0]
        pl.has_data_labels = False
        for i, pt in enumerate(pl.series[0].points):
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = COL3[i]
        g = T[k]["gross_year_hw"] + T[k]["gross_year_sw"] + T[k]["gross_year_op"]
        lab = s.shapes.add_textbox(Inches(x), Inches(4.84), Inches(3.55), Inches(1.02))
        tf = lab.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = "%s：硬件 %.1f%%　软件 %.1f%%　运营 %.1f%%" % (title, pct["hw"], pct["sw"], pct["op"])
        r.font.size = Pt(10.5)
        r.font.bold = True
        r.font.color.rgb = C_DARK
        r.font.name = "Microsoft YaHei"
        p2 = tf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = "三方合计年毛利 %.1f 万元" % wan(g)
        p2.space_before = Pt(5)
        r2.font.size = Pt(9.5)
        r2.font.color.rgb = C_MUTE
        r2.font.name = "Microsoft YaHei"
    note(s, "规则：硬件拿「建议报价 − 目标硬件成本」，软件拿「许可 − 目标软件成本」，运营拿「按件费 − 运营支出」；三方均为正。")

    # ── 11 落地路径
    s = new_slide(prs, "从进场标定到无人夜班，落地可以拆成四个可验收的阶段",
                  "每一阶段都有交付物与判据，任何一步不达标就停下来修")
    box_flow(s, [
        ("第一阶段　现场标定", "定几何基准", C_BLUE),
        ("第二阶段　节拍达标", "每小时三百件", C_LBLUE),
        ("第三阶段　双臂协同", "换型不停线", C_GREEN),
        ("第四阶段　自主运行", "具备夜班条件", C_ORANGE),
    ], y=1.62, h=1.25, hsize=11.5, bsize=9.5, x0=0.96, total_w=11.40)
    para_block(s, 0.96, 3.25, 11.40, 2.25, [
        ("每个阶段的时间与验收", C_DARK, 14, True),
        ("基础型从进场到验收约两周；精细型约四周，其中采集真实数据与训练策略占一半；专业型约八周，安全验证与第三方认证是长周期项。",
         C_DARK, 10.5, False),
        ("验收不看演示，看数据：单件节拍、连续运行小时数、良率、异常恢复次数，四项都要有记录。", C_ORANGE, 11, True),
        ("客户可以按我们提供的操作手册自行复测，这也是与集成商最大的区别。", C_MUTE, 10.5, False),
    ])
    kpi_strip(s, 0.96, 5.62, 11.40, [
        ("交付周期（标定→验收）", "基础型约 2 周 · 精细型约 4 周 · 专业型约 8 周"),
        ("验收四项硬指标", "单件节拍 / 连续运行小时数 / 良率 / 异常恢复次数，逐项留记录"),
    ], C_BLUE)
    note(s, "阶段划分与三档配置的交付周期一致，也与工程操作手册中的验收步骤一一对应。")

    # ── 12 四条策略 (老倪 2026-10-28: 「成本分析和市场分成，是什么策略」)
    s = new_slide(prs, "四条策略：成本定死、报价给区间、分成看成本、落地分三步",
                  "一句话概括：先按目标成本把钱算清，再按毛利空间报价，最后按毛利贡献分钱")
    R0 = rollout()
    box_flow(s, [
        ("成本策略", "目标成本定死", C_BLUE),
        ("定价策略", "不定售价给区间", C_ORANGE),
        ("分成策略", "按毛利贡献", C_GREEN),
        ("市场策略", "三阶段接续", C_LBLUE),
    ], y=1.55, h=1.05, hsize=11.5, bsize=9.5, x0=0.96, total_w=11.40)
    para_block(s, 0.96, 2.95, 11.40, 2.10, [
        ("成本：目标成本由产品定，不由采购定", C_BLUE, 12, True),
        ("基础 15+5、精细 20+10、专业 22+15 万，单套成本 20/30/37 万；现估硬件成本分别高出 %.1f / %.1f / %.1f 万，"
         "这部分要靠采购与结构设计挤掉，否则直接吃掉毛利。" % tuple(t["gap_to_bom"] / 1e4 for t in TG),
         C_DARK, 10, False),
        ("定价：老板给红线，销售给区间", C_ORANGE, 12, True),
        ("对外不定售价。建议毛利空间 %.1f~%.1f%% / %.1f~%.1f%% / %.1f~%.1f%%，折算报价区间 %.1f~%.1f / %.1f~%.1f / %.1f~%.1f 万；"
         "碰上红线 %.0f/%.0f/%.0f 万就顶格报，红线内实际毛利 %.1f%% / %.1f%% / %.1f%%。" % (
             TG[0]["gross_pct_lo"], TG[0]["gross_pct_hi"], TG[1]["gross_pct_lo"], TG[1]["gross_pct_hi"],
             TG[2]["gross_pct_lo"], TG[2]["gross_pct_hi"],
             TG[0]["price_lo"] / 1e4, TG[0]["price_hi"] / 1e4, TG[1]["price_lo"] / 1e4, TG[1]["price_hi"] / 1e4,
             TG[2]["price_lo"] / 1e4, TG[2]["price_hi"] / 1e4,
             TG[0]["cap_ref"] / 1e4, TG[1]["cap_ref"] / 1e4, TG[2]["cap_ref"] / 1e4,
             TG[0]["pct_at_cap"], TG[1]["pct_at_cap"], TG[2]["pct_at_cap"]), C_DARK, 10, False),
        ("分成与市场：钱按成本结构分，单子按信任度接", C_GREEN, 12, True),
        ("分成以目标成本为分母：硬件 %.1f/%.1f/%.1f%%，软件 %.1f/%.1f/%.1f%%，运营 %.1f/%.1f/%.1f%%；"
         "落地按精细首发、基础铺量、专业跨场景三步，客户回本 %.2f / %.2f / %.2f 年。" % (
             TG[0]["pct_capped"]["hw"], TG[1]["pct_capped"]["hw"], TG[2]["pct_capped"]["hw"],
             TG[0]["pct_capped"]["sw"], TG[1]["pct_capped"]["sw"], TG[2]["pct_capped"]["sw"],
             TG[0]["pct_capped"]["op"], TG[1]["pct_capped"]["op"], TG[2]["pct_capped"]["op"],
             R0[0]["payback_years"], R0[1]["payback_years"], R0[2]["payback_years"]), C_DARK, 10, False),
    ])
    kpi_strip(s, 0.96, 5.12, 11.40, [
        ("三条不做的事", "不定售价 · 不按投入比例分成 · 不在场景数据不足十个时降配铺量"),
        ("一句话", "成本是算出来的，利润是谈出来的，份额是结构决定的"),
    ], C_ORANGE)
    note(s, "四条策略共用一套模型：tools/spec/cost_targets.json（目标成本与毛利区间）+ tools/spec/rollout.json（阶段与分成偏好）。")

    # ── 13 市场策略三阶段接续落地 (老倪 2026-10-28: 精细版先上, 一年后且场景>10 降配基础版, 最后跨场景专业版)
    R = rollout()
    s = new_slide(prs, "三个版本不是同时卖，而是按信任度接续落地",
                  "设备价内含免费运营期，是让客户三年内回本的让利；让利成本由该阶段毛利承担")
    cd = CategoryChartData()
    cd.categories = ["精细版首发", "基础版铺量", "专业版跨场景"]
    cd.add_series("不让利时的回本（年）", [round((R[0]["payback_months_nofree"] or 999) / 12.0, 2),
                                          round((R[1]["payback_months_nofree"] or 999) / 12.0, 2),
                                          round((R[2]["payback_months_nofree"] or 999) / 12.0, 2)])
    cd.add_series("设备价内免费期后的回本（年）", [round(R[0]["payback_years"], 2), round(R[1]["payback_years"], 2),
                                                  round(R[2]["payback_years"], 2)])
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.96), Inches(1.42), Inches(5.75), Inches(4.55), cd)
    ch = gf.chart
    color_series(ch.plots[0], [C_MUTE, C_ORANGE])
    style_chart(ch, size=10, legend=True)
    ch.plots[0].has_data_labels = True
    ch.plots[0].data_labels.font.size = Pt(9)
    ch.plots[0].data_labels.font.bold = True
    ch.plots[0].gap_width = 70
    ch.has_title = True
    ch.chart_title.text_frame.text = "客户回本年限（三年是工业品采购的硬门槛）"
    ch.chart_title.text_frame.paragraphs[0].font.size = Pt(11)
    para_block(s, 7.05, 1.55, 5.55, 3.7, [
        ("第一阶段 · 精细版首发", C_ORANGE, 12, True),
        ("一个工位替白班晚班两人，设备价 %s 内含 %d 个月运营与许可，客户 %.2f 年回本。"
         % (wan(R[0]["price"]), R[0]["free_months"], R[0]["payback_years"]), C_DARK, 10, False),
        ("第二阶段 · 基础版铺量", C_BLUE, 12, True),
        ("满一年且场景超过十个后降配，用简单操作铺量，%d 个月免费，%.2f 年回本。"
         % (R[1]["free_months"], R[1]["payback_years"]), C_DARK, 10, False),
        ("第三阶段 · 专业版跨场景", C_GREEN, 12, True),
        ("真价值是新场景不再从零集成，按每年多一个场景、实施费省六成计，每年多 %s，%.2f 年回本。"
         % (wan(R[2]["reuse_year"]), R[2]["payback_years"]), C_DARK, 10, False),
    ])
    kpi_strip(s, 7.05, 5.28, 5.55, [
        ("人工基准（替代对象）", "每人每年 %.0f 万 · 两班共 %.0f 万" % (
            R[0]["labor_year"] / R[0]["persons"] / 1e4, R[0]["labor_year"] / 1e4)),
        ("三方分成随阶段移动", " %.1f→%.1f→%.1f%%（软件）" % (R[0]["pct"]["sw"], R[1]["pct"]["sw"], R[2]["pct"]["sw"])),
    ], C_ORANGE)
    note(s, "分成比例与回本年限由同一个模型算出：设备价受上限约束后，钱从硬件转到许可与按件运营，"
            "阶段越往后，软件与运营的份额越高。")

    # ── 14 风险边界
    s = new_slide(prs, "对客户承诺之前，先把四个缺口补上",
                  "这些问题不解决，任何节拍与良率的数字都只是实验室数据")
    box_flow(s, [
        ("几何标定缺口", "外参未标定", C_RED),
        ("训练数据缺口", "数据未成结构", C_RED),
        ("安全认证缺口", "未做第三方验证", C_RED),
        ("价格口径缺口", "待供应商报价", C_RED),
    ], y=1.6, h=1.25, hsize=11.5, bsize=9.5, x0=0.96, total_w=11.40)
    para_block(s, 0.96, 3.2, 11.40, 2.25, [
        ("补齐的顺序与代价", C_DARK, 14, True),
        ("几何标定需要现场一天；训练数据需要两百条左右真实示教，按每条三百元计约六万元；安全认证周期八到十二周，费用约十五万元。",
         C_DARK, 10.5, False),
        ("在这三件事完成之前，对外只承诺能力边界，不承诺具体产量与良率。", C_ORANGE, 11, True),
        ("这也是这套方案与买一台机器人的本质区别：卖的是可验证的产能，不是设备清单。", C_MUTE, 10.5, False),
    ])
    kpi_strip(s, 0.96, 5.62, 11.40, [
        ("补齐代价", "标定 1 天 · 真实示教约 6 万元 · 安全认证 8~12 周约 15 万元"),
        ("补齐之前对外只承诺", "能力边界（算力/层数/功能），不承诺具体产量与良率"),
    ], C_RED)
    note(s, "以上缺口已在工程操作手册中列为必做项，与配置中心的判据脚本同步跟踪。")

    prs.save(OUT)
    print("写出 %s (%d 字节 · %d 页)" % (OUT, os.path.getsize(OUT), len(prs.slides._sldIdLst)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
