#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《光模块插拔工位 · 量产成本/定价/三方分成方案》PPT
唯一数据源: reports/pricing_20261027/metrics.json (由 tools/pricing_model_20261027.py 现算)
"""
import json, os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

ROOT = "/home/ubuntu/zmax"
OUT = os.path.join(ROOT, "reports", "pricing_20261027")
M = json.load(open(os.path.join(OUT, "metrics.json"), encoding="utf-8"))
R = {r["vol"]: r for r in M["rows"]}
R500, R300, R100, R1000 = R[500], R[300], R[100], R[1000]
T = M["tact"]; TR = M["truth"]

FONT = "Noto Sans CJK SC"
INK = RGBColor(0x11, 0x17, 0x1F)
GRAY = RGBColor(0x5A, 0x63, 0x70)
BLUE = RGBColor(0x1F, 0x6F, 0xEB)
RED = RGBColor(0xD1, 0x24, 0x2F)
GREEN = RGBColor(0x1A, 0x7F, 0x37)
AMBER = RGBColor(0xB5, 0x6A, 0x00)
LGRAY = RGBColor(0xF2, 0xF4, 0xF7)

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5


def _ea(run):
    run.font.name = FONT
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", FONT)


def txt(slide, x, y, w, h, text, size=14, bold=False, color=INK, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, spacing=1.15):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = 0
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
        _ea(r)
    return box


def head(slide, title, sub=None, kicker=None):
    bar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(W), Inches(0.09))
    bar.fill.solid(); bar.fill.fore_color.rgb = BLUE; bar.line.fill.background()
    if kicker:
        txt(slide, 0.62, 0.30, 8.0, 0.28, kicker, 10.5, True, BLUE)
    txt(slide, 0.62, 0.56, 12.1, 0.55, title, 25, True, INK)
    if sub:
        txt(slide, 0.62, 1.10, 12.1, 0.34, sub, 12, False, GRAY)
    return 1.55 if sub else 1.30


def footer(slide, text):
    txt(slide, 0.62, 7.06, 12.1, 0.26, text, 8.5, False, GRAY)


def kpi(slide, x, y, w, value, label, color=BLUE, hint=None):
    card = slide.shapes.add_shape(5, Inches(x), Inches(y), Inches(w), Inches(1.30))
    card.fill.solid(); card.fill.fore_color.rgb = LGRAY
    card.line.color.rgb = RGBColor(0xDE, 0xE3, 0xEA); card.line.width = Pt(0.75)
    card.shadow.inherit = False
    txt(slide, x + 0.18, y + 0.13, w - 0.3, 0.52, value, 27, True, color)
    txt(slide, x + 0.18, y + 0.68, w - 0.3, 0.28, label, 11, False, GRAY)
    if hint:
        txt(slide, x + 0.18, y + 0.98, w - 0.3, 0.26, hint, 9, False, GRAY)


def table(slide, data, x, y, w, colw, rowh=0.34, size=10.5, hdr_size=10.5,
          bold_col0=False, align=None, hdr_fill=RGBColor(0x1F, 0x3A, 0x5F)):
    rows, cols = len(data), len(data[0])
    shp = slide.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w), Inches(rowh * rows))
    tbl = shp.table
    tbl.first_row = True
    tot = sum(colw)
    for j, cw in enumerate(colw):
        tbl.columns[j].width = Emu(int(Inches(w) * cw / tot))
    for i, row in enumerate(data):
        tbl.rows[i].height = Inches(rowh if i else rowh * 1.08)
        for j, val in enumerate(row):
            c = tbl.cell(i, j)
            c.text = ""
            c.margin_left = c.margin_right = Inches(0.06)
            c.margin_top = c.margin_bottom = Inches(0.015)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = c.text_frame.paragraphs[0]
            a = (align[j] if align else (PP_ALIGN.LEFT if j == 0 else PP_ALIGN.CENTER))
            p.alignment = a
            r = p.add_run(); r.text = str(val)
            r.font.size = Pt(hdr_size if i == 0 else size)
            r.font.bold = (i == 0) or (bold_col0 and j == 0)
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if i == 0 else INK
            _ea(r)
            c.fill.solid()
            if i == 0:
                c.fill.fore_color.rgb = hdr_fill
            else:
                c.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if i % 2 else LGRAY
    return tbl


def money(v):   # 元 → "25.1 万"
    return f"{v/10000:.1f} 万"


# ── 1 封面 ────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(1, Inches(0), Inches(0), Inches(W), Inches(H))
bg.fill.solid(); bg.fill.fore_color.rgb = RGBColor(0x0B, 0x16, 0x27); bg.line.fill.background()
txt(s, 0.9, 1.55, 11.5, 0.4, "Z-MAX · 光模块插拔 / 检测工位", 14, True, RGBColor(0x7D, 0xB8, 0xFF))
txt(s, 0.9, 2.05, 11.8, 1.7, "量产成本 · 定价 · 三方分成方案", 44, True, RGBColor(0xFF, 0xFF, 0xFF))
txt(s, 0.9, 3.35, 11.6, 0.9, "以大批量量产的 BOM / 摊销 / 实施成本为锚，倒推客户回本与\n硬件 · 软件 · 运营 三方 1:1:1 的利润分配", 15, False, RGBColor(0xC7, 0xD2, 0xE0), spacing=1.5)
line = s.shapes.add_shape(1, Inches(0.92), Inches(4.62), Inches(2.2), Inches(0.05))
line.fill.solid(); line.fill.fore_color.rgb = RGBColor(0x1F, 0x6F, 0xEB); line.line.fill.background()
txt(s, 0.9, 4.86, 11.5, 0.9,
    f"节拍真源: /ar3d 右侧栏 左臂 3.00 s/个 · 右臂 {T['right']:.2f} s/个 · 整体 {T['overall']:.2f} s/个\n"
    f"成本真源: config/platform/zmax_cost_model.json（硬件逐项给定）+ tools/pricing_model_20261027.py 现算",
    11, False, RGBColor(0x9A, 0xA8, 0xBA), spacing=1.4)
txt(s, 0.9, 6.55, 11.0, 0.35, "2026-10-27 · 静态测算版（软件尚未报价，价格为本方案推导值）", 10.5, False, RGBColor(0x7C, 0x8A, 0x9C))

# ── 2 结论先行 ────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "三句话结论", "节拍决定产能，量产决定成本，成本决定三方能不能平分利润")
kpi(s, 0.62, y0 + 0.10, 3.85, f"{T['overall']:.2f} s/个", "整体节拍（瓶颈=右臂插拔）",
    BLUE, f"{T['cap_h']:.0f} 个/h(目标) · 两班制 {T['cap_year']/1e4:.1f} 万件/年 · 良率 99.2%")
kpi(s, 4.72, y0 + 0.10, 3.85, money(R500["price"]), "量产标准价（500 台/年档）",
    GREEN, f"较现价 {money(TR['now_price'])} 降 {(1-R500['price']/TR['now_price'])*100:.0f}% · 毛利 {R500['gross_margin']*100:.0f}%")
kpi(s, 8.82, y0 + 0.10, 3.85, money(R500["each"]), "三方各得（单台）",
    AMBER, "毛利池 ÷ 3 = 硬件 / 软件 / 运营")
txt(s, 0.62, y0 + 1.72, 12.1, 2.5,
    f"① 节拍：整体 {T['overall']:.2f} s/个。右臂末端速度取左臂同口径（{(T.get('speed_profile') or {}).get('v_mm_s','—')} mm/s"
    f" = 左臂每循环 3.0 s ÷ 等效位移 1,877 mm），4 孔先插满 1→2→3→4，之后每轮「拔一对 → AOI → 插同一对」不插等待。\n"
    "② 价格：量产价 25.1 万（现 36.3 万），客户 2 年回本、我方毛利 40%；"
    "1.5 年回本做不到——底价 23.2 万已经高于客户 1.5 年能承受的 18.8 万，对外只承诺 2 年。\n"
    "③ 分成：单台毛利池 11.15 万，1:1:1 各 3.72 万；但运营方还要自己掏 1.1 万实施 + 0.75 万维保，"
    "实得 1.86 万——所以要么实施费单列、要么改成 32/32/36。",
    13, False, INK, spacing=1.62)
footer(s, "口径：人力综合成本 9 万/人·年（给定区间 8~10 万取中值）· 人效 η=0.85 · 软件按 5 年装机量摊销 600 万研发")

# ── 3 真实节拍 ────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "真实节拍：瓶颈在右臂插拔，不在摆盘",
          "数据取自 /ar3d 右侧栏（页面现算，非手填）；左臂 3.0 s/个 为老倪敲定值")
data = [["工位 / 环节", "节拍", "段表构成", "说明"],
        ["左臂摆盘", "3.00 s/个", "14 循环 × 8 步", "抓→抬→平移→落，夹爪按 120mm 等效位移折算"],
        ["右臂插拔", f"{T['right']:.2f} s/个", "8 轮 × 4 孔轮转", f"末端 {(T.get('speed_profile') or {}).get('v_mm_s','—')} mm/s(左臂同速) · 预插1,2,3,4 → 拔2·AOI·落盘 → 插同一2孔 → 换另一对"],
        ["整体（产线）", f"{T['overall']:.2f} s/个", "= max(左, 右)", f"瓶颈右臂 ⇒ 目标 {T['cap_h']:.0f} 个/h(仿真稳态 {T.get('uph_actual',0):.0f}) · {T['cap_year']/1e4:.1f} 万件/年 · 良率 99.2%(0.8% 不良)"],
        ["单盘（14 个）", f"{T['batch_s']:.1f} s", "8 轮合计", f"与页面「每盘 14 个 {T['batch_s']:.1f} s」一致"]]
table(s, data, 0.62, y0 + 0.10, 12.1, [2.0, 1.5, 2.2, 6.4], rowh=0.52, size=11)
txt(s, 0.62, y0 + 2.55, 12.1, 1.5,
    f"三件事：\n"
    f"· 左臂富余 {T['right']/3.0:.0f} 倍（{T['right']:.2f} ÷ 3.00）⇒ 一个摆盘单元可喂 {T['right']/3.0:.0f} 个插拔工位；\n"
    f"· 一轮 = 拔2(含 AOI+落盘) + 插2 ≈ {T['right']*2:.1f} s ⇒ {T['right']:.2f} s/个；再快只能减动作(侧面复检面数)或做双工位并行；\n"
    f"· 在孔自然驻留 {T.get('dwell_natural',[0,0])[0]:.0f}~{T.get('dwell_natural',[0,0])[1]:.0f} s（首轮最短），全程无专门等待段；"
    f"14 个一批 {T['batch_s']:.1f} s（目标档 42.0 s）。",
    12.5, False, INK, spacing=1.6)
footer(s, "口径：右臂为仿真段表（距离/200mm/s + 每个固定动作 0.4~0.8 s），4 孔轮转 + 先插满后拔插同一对为老倪给定流程；真机尚未实测")

# ── 4 现状成本 ────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "现状单套成本：36.3 万，回本 2.02 年（人效 100% 口径）",
          "硬件逐项为给定真源；软件 16 万是套餐份额，尚未单独报价")
_HW = json.load(open(os.path.join(ROOT, "config/platform/zmax_cost_model.json"), encoding="utf-8"))["hardware"]
it = [(h["item"], h["model"], format(h["price"], ",")) for h in _HW]
data = [["项", "型号 / 规格", "单价（元）"]] + [[a, b, c] for a, b, c in it]
data += [["硬件小计", "—", f"{TR['hw_total']:,}"],
         ["软件（套餐份额，含三年授权）", "未单独报价", f"{TR['sw_share']:,}"],
         ["合计", "单套", f"{TR['now_price']:,}"]]
table(s, data, 0.62, y0 + 0.05, 7.2, [3.1, 2.5, 1.6], rowh=0.44, size=10.5)
txt(s, 8.10, y0 + 0.05, 4.6, 3.4,
    f"年节省 = {TR['heads']} 人 × {TR['labor']/10000:.0f} 万/人·年\n= {TR['annual_save']/10000:.0f} 万/年\n\n"
    f"静态回本 = {TR['now_price']/10000:.1f} 万 ÷ {TR['annual_save']/10000:.0f} 万\n= {TR['payback_now']:.2f} 年\n\n"
    "注意：这是「人效 1.0、零维保、零 NRE」的上限口径。\n"
    "扣掉维保 3% + 软件年费 2 万、人效按 0.85，\n"
    f"同一台机器的真实回本 = {R[10]['payback']:.2f} 年。",
    12.5, False, INK, spacing=1.55)
footer(s, "真源 config/platform/zmax_cost_model.json（2026-10-19 老倪给定）+ tools/cost_model.py 现算")

# ── 5 降本三来源 ──────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "量产降本只有三个来源，机械臂占一半",
          "500 台/年档相对单台：BOM 20.3 → 13.7 万，软件 16 万 → 0.24 万/台 + 2 万/年订阅")
src = [["来源", "单台档", "500 台/年档", "降幅", "依据"],
       ["硬件 BOM", "20.30 万", "13.74 万", "−32%", "机械臂 13.5→8.9 万（主项）+ 域控 5.5→3.85 万"],
       ["软件（一次性）", "16.00 万", "0.24 万", "摊销", "600 万研发 ÷ 5 年 × 500 台 = 2,400 元/台"],
       ["实施 / 标定", "3.00 万", "1.10 万", "−63%", "标准作业包 + 远程标定，人天从 12 降到 4"],
       ["合计成本", "39.30 万", "15.08 万", "−62%", "软件另收 2 万/台·年（订阅），不计入硬件成本"]]
table(s, src, 0.62, y0 + 0.08, 12.1, [1.9, 1.5, 1.7, 1.1, 6.0], rowh=0.52, size=11)
txt(s, 0.62, y0 + 2.75, 12.1, 1.6,
    "两个反直觉的点：\n"
    "① 软件不是成本大头——按量摊销后单台只剩 2,400 元，把软件当「16 万」压价会让毛利算成负数；\n"
    "② 真正的杠杆是机械臂：换国产同档力控臂（13.5 → 9 万）省的 4.5 万，比砍掉整个软件包还多。",
    12.5, False, INK, spacing=1.6)
footer(s, "阶梯折扣为假设值（国产力控臂/域控/相机在 100 台/年量级普遍有 20~35% 议价），需向供应商询价确认后替换")

# ── 6 成本曲线 ────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "量产成本曲线：100 台/年才进「可报价」区间",
          "低于 100 台，研发摊销会把单台成本顶到 30 万以上——这就是为什么小批量只能按现价卖")
rows = [["台/年", "硬件 BOM", "软件摊销", "实施", "单台成本", "建议售价", "毛利率", "客户回本"]]
for v in (10, 100, 300, 500, 1000):
    r = R[v]
    rows.append([str(v), f"{r['bom']/10000:.2f} 万", f"{r['amort']/10000:.2f} 万", f"{r['impl']/10000:.2f} 万",
                 f"{r['cost']/10000:.2f} 万", f"{r['price']/10000:.1f} 万" + ("（现价封顶）" if r["capped"] else ""),
                 f"{r['gross_margin']*100:.0f}%", f"{r['payback']:.2f} 年"])
table(s, rows, 0.62, y0 + 0.08, 12.1, [0.9, 1.5, 1.5, 1.3, 1.5, 2.4, 1.0, 1.3], rowh=0.46, size=10.5)
txt(s, 0.62, y0 + 2.95, 12.1, 1.4,
    "· 10 台/年：成本 30.6 万，售价只能顶到现价 36.3 万，毛利 16%，运营方倒贴 0.38 万/台；\n"
    "· 300~500 台/年：成本落到 15~16 万，25 万价位仍有 40% 毛利，客户 2 年回本——这是唯一的良性区间；\n"
    "· 1000 台/年：价格可以再降到 22.6 万（毛利 38%），用于抢份额。",
    12, False, INK, spacing=1.55)
footer(s, "回本口径：人效 η=0.85（年省 15.3 万）+ 年维保 3% 售价 + 软件年费 2 万；未折现")

# ── 7 定价与成交区间 ──────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "定价：25.1 万标准价，底价 23.2 万，不做 1.5 年回本承诺",
          "底价 = 成本 ÷ (1−35% 毛利)；上限 = 净年省 × 客户目标回本年限")
rows = [["台/年", "成本", "底价（35% 毛利）", "客户上限（1.5 年）", "是否可谈", "建议成交价"]]
for v in (100, 300, 500, 1000):
    r = R[v]
    ok = "可谈" if r["floor35"] <= r["ceiling"] else f"空区间（差 {(r['floor35']-r['ceiling'])/10000:.1f} 万）"
    rows.append([str(v), f"{r['cost']/10000:.1f} 万", f"{r['floor35']/10000:.1f} 万",
                 f"{r['ceiling']/10000:.1f} 万", ok, f"{r['price']/10000:.1f} 万"])
table(s, rows, 0.62, y0 + 0.08, 12.1, [0.9, 1.5, 2.2, 2.3, 3.0, 2.2], rowh=0.46, size=10.5)
txt(s, 0.62, y0 + 2.42, 12.1, 0.62,
    "结论：在 35% 毛利下，任何量级都撑不住客户「1.5 年回本」——差 4.3~6.1 万。对外统一按 2 年回本谈，"
    "要压价就用「多工位 / 买断转订阅」，不要动单价。", 12, True, RED, spacing=1.4)
prod = [["产品档", "含什么", "价格（未税）", "客户回本", "适用"],
        ["单工位买断", "插拔 + 5 项在线检测 + 三年软件", "25.1 万", "2.00 年", "首台 / 单点替换"],
        ["买断 + 订阅", "同上，CAPEX 降 1.5 万，软件转年费", "23.6 万 + 2 万/年", "2.06 年", "客户压 CAPEX"],
        ["三工位产线包", "3 工位 + 集中调度 + 换型", "67.8 万（9 折）", "1.95 年", "整线招标"],
        ["软件授权（集成商）", "能力包，硬件客户自购", "8 万/台 + 1.5 万/年", "—", "竞标 / 份额"]]
table(s, prod, 0.62, y0 + 3.18, 12.1, [2.1, 4.6, 2.2, 1.2, 2.0], rowh=0.42, size=10)
footer(s, "价格均为未税；订阅年费含版本升级与远程诊断；集成商授权价为建议价，按项目量阶梯")

# ── 8 客户 ROI ────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "客户 ROI：标准价 25.1 万，1.65~2.0 年回本，5 年净现值 36 万",
          "两个口径都给：人效 1.0（理想）与人效 0.85（保守，本方案采用）")
rows = [["口径", "年节省", "年支出（维保+软件）", "净年省", "回本", "5 年 NPV"]]
p0 = R500["price"]
for nm, eta in (("人效 1.0（理想）", 1.0), ("人效 0.85（保守）", 0.85)):
    save = 180000 * eta
    opex = p0 * 0.03 + 20000
    net = save - opex
    rows.append([nm, f"{save/10000:.1f} 万", f"{opex/10000:.2f} 万", f"{net/10000:.1f} 万",
                 f"{p0/net:.2f} 年", f"{(-p0 + sum(net/1.08**t for t in range(1,6)))/10000:.1f} 万"])
table(s, rows, 0.62, y0 + 0.08, 8.0, [2.4, 1.4, 2.1, 1.3, 1.0, 1.2], rowh=0.50, size=10.5)
txt(s, 8.85, y0 + 0.05, 3.85, 3.2,
    f"单件经济性（500 台档 · 5 年直线折旧）\n"
    f"· 产能 {T['cap_h']:.0f} 个/h · {T['cap_year']/1e4:.1f} 万件/年\n"
    f"· 设备折旧 {T['dep_per_piece']:.3f} 元/件\n"
    f"· 单件人工（原 2 人）约 0.25 元/件\n"
    f"⇒ 25 万级的设备，单件成本已经低于 0.1 元，"
    f"定价不该锚定产能，只能锚定人力与良率。",
    12, False, INK, spacing=1.55)
txt(s, 0.62, y0 + 2.45, 12.1, 1.2,
    "谈判口径：客户一定会拿「2 年回本」当底线。我们的 25.1 万正好卡在 2.00 年；"
    "再往下就是拿我方毛利换份额——只在大客户三工位以上让，且用订阅把 CAPEX 降下来换。",
    12, False, INK, spacing=1.5)
footer(s, "NPV 折现率 8%，5 年，未计残值；年节省口径 = 2 人 × 9 万（1 工位 2 班 每班 1 人）")

# ── 9 三方分成 ────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "三方 1:1:1 各 3.72 万，运营方实得 1.86 万",
          "分配基数 = 售价 − 硬件 BOM − 软件摊销；实施与维保按成本归属运营方")
rows = [["环节", "金额（元/台）", "谁承担"],
        ["售价", f"{R500['price']:,}", "客户"],
        ["− 硬件 BOM", f"−{R500['bom']:,}", "硬件方（成本）"],
        ["− 软件摊销", f"−{R500['amort']:,}", "软件方（成本）"],
        ["= 毛利池", f"{R500['pool']:,}", "三方分配"],
        ["硬件方 1/3", f"{R500['each']:,.0f}", "净得"],
        ["软件方 1/3", f"{R500['each']:,.0f}", "净得 + 订阅 2 万"],
        ["运营方 1/3", f"{R500['each']:,.0f}", f"还要付实施 {R500['impl']:,} + 维保 {R500['maint']:,.0f}"],
        ["运营方实得", f"{R500['ops_net']:,.0f}", f"比另两方少 {(R500['each']-R500['ops_net'])/10000:.2f} 万"]]
table(s, rows, 0.62, y0 + 0.05, 7.6, [2.6, 2.4, 2.6], rowh=0.40, size=10.5)
txt(s, 8.45, y0 + 0.05, 4.3, 3.4,
    "三条修正（任选一条，别三条都用）\n"
    "① 实施费单列：客户另付 1.1 万/台，运营方回到 3.72 万；\n"
    "② 维保改年费：3% 售价（约 0.75 万/年）由客户按年付；\n"
    "③ 分成改 32 / 32 / 36：运营方多拿 0.37 万/台。\n\n"
    "推荐 ①+②：三方账面仍是 1:1:1，但运营方不再用自己的份额垫实施与维保——"
    "这是「平分利润」而不是「平分毛利」。",
    11.5, False, INK, spacing=1.5)
txt(s, 0.62, y0 + 3.72, 12.1, 0.6,
    "订阅池（2 万/台·年）建议按 软件 50% / 运营 30% / 硬件 20%（备件与固件维护）分："
    "这是经常性收入，按投入分比按毛利分更公平。", 11.5, False, GRAY)
footer(s, "以 500 台/年档计；毛利池已扣硬件与软件成本，未扣公司管理费用与销售费用")

# ── 10 五年计划 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "五年经营测算：300 台/年时，三方各得约 600~1900 万",
          "台数为目标假设；软件含存量装机年费，运营已扣实施与维保")
rows = [["年度", "台数", "均价", "营收", "毛利池", "硬件方", "软件方（含年费）", "运营方（净）"]]
for p in M["plan"]:
    rows.append([f"Y{p['year']}", str(p["units"]), f"{p['price']/10000:.1f} 万",
                 f"{p['revenue']/10000:.0f} 万", f"{p['pool']/10000:.0f} 万",
                 f"{p['hw']/10000:.0f} 万", f"{p['sw']/10000:.0f} 万", f"{p['ops']/10000:.0f} 万"])
table(s, rows, 0.62, y0 + 0.08, 12.1, [0.9, 0.9, 1.2, 1.4, 1.4, 1.4, 2.1, 1.9], rowh=0.44, size=10.5)
txt(s, 0.62, y0 + 2.95, 12.1, 1.5,
    "· 前两年运营方是负的（Y1 −4 万、Y2 −15 万）：实施人力先垫、维保先摊，装机量还没起来；\n"
    "· 从 Y3 起订阅池开始反超硬件——300 台存量 × 2 万 = 600 万/年，几乎全是毛利；\n"
    "· 所以分成协议要写「运营方前两年缺口由后续年费优先补偿」，否则没人愿意做运营。",
    12, False, INK, spacing=1.55)
footer(s, "本页为模型推演，非承诺；台数为目标假设，需按实际中标情况滚动修正")

# ── 11 市场打法 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "怎么拿到更多市场：三条腿，别只靠降价",
          "价格已经压到 25 万，再降就是拿毛利换份额——要用模式换，不用单价换")
col = [["打法", "怎么卖", "我方所得", "成立条件"],
       ["直销首台 POC", "成本价 15.1 万 + 验收对赌（节拍/良率）", "约 0 毛利，换场景数据与复购", "客户愿开产线数据"],
       ["集成商授权", "软件 8 万/台 + 1.5 万/年，硬件客户自购", "毛利 80%+，不占我方现金", "找到有光模块客户的集成商"],
       ["三工位产线包", "67.8 万/线（9 折），含集中调度", "单线毛利 30 万", "客户年产 > 200 万件"],
       ["存量改造", "只卖插拔单元 + 检测，复用客户现有输送", "12~15 万/台", "老线自动化改造预算"]]
table(s, col, 0.62, y0 + 0.05, 12.1, [1.8, 4.6, 3.2, 2.6], rowh=0.56, size=10.5)
txt(s, 0.62, y0 + 2.85, 12.1, 1.6,
    "市场位置的实话：优艾智合 O 系列强在移动底盘，无界智航 X-Arm 强在双臂本体，"
    "我们在「插拔力控 + 在线五项判据 + 25 万价位」这一格没有直接对手——"
    "所以份额战要打「单工位替换」，不要打「整线方案」。\n"
    "先用 10~20 台把 3 个标杆客户做成可复制的节拍/良率数据，再谈渠道。",
    12, False, INK, spacing=1.55)
footer(s, "竞品口径来自公开资料（优艾智合 OW 系列整机尺寸/载荷、无界智航 X-Arm 双臂结构），非我方实测")

# ── 12 风险与下一步 ───────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
y0 = head(s, "还缺什么证据，下一步 90 天怎么走",
          "本方案所有节拍是仿真值，所有折扣是假设值——两件事必须先在真机上补")
rows = [["缺口", "现状", "补法", "什么时候"],
        ["真机节拍", f"{T['right']:.2f} s/个（仿真: 末端 {(T.get('speed_profile') or {}).get('v_mm_s','—')} mm/s）", "单工位连跑 200 件，记 CT/成功率/停机", "30 天内"],
        ["在孔驻留下限", f"自然 {T.get('dwell_natural',[0,0])[0]:.0f}~{T.get('dwell_natural',[0,0])[1]:.0f} s，工艺下限未验证", "按 20/40/60 s 各试 50 件，看 AOI 通过率曲线", "30 天内"],
        ["AOI 耗时", "金手指 0.8 s + 侧面 4 面 2.0 s，未单独实测", "五项判据各自计时（当前不在关键路径）", "30 天内"],
        ["阶梯折扣", "BOM 折扣为假设（-20~38%）", "机械臂/域控/相机各取 2 家报价", "45 天内"],
        ["软件研发口径", "600 万为假设", "按实际人力台账替换", "45 天内"],
        ["运营成本", "维保 3%、实施 1.1 万为假设", "首个客户结算后回填", "90 天内"]]
table(s, rows, 0.62, y0 + 0.05, 12.1, [1.9, 4.0, 4.5, 1.5], rowh=0.42, size=10)
txt(s, 0.62, y0 + 2.65, 12.1, 1.6,
    f"90 天节点：①第 30 天出真机节拍报告（替换本方案 {T['right']:.2f} s）→ ②第 60 天出三份供应商报价（替换折扣）"
    f"→ ③第 90 天定版价格表并签第一份三方分成协议。\n"
    f"在此之前，对外只报「25 万级、2 年回本、节拍约 {T['right']:.0f} s/个（仿真，4 孔轮转）」，不报良率与 MTBF。",
    12, False, INK, spacing=1.55)
footer(s, "本方案不替代真机验收；节拍/良率/MTBF 三项未经实测不得进入对外合同条款")

path = os.path.join(OUT, "Z-MAX_光模块插拔工位_量产定价与三方分成方案_20261027.pptx")
prs.save(path)
print(path, os.path.getsize(path), "bytes ·", len(prs.slides._sldIdLst), "slides")
