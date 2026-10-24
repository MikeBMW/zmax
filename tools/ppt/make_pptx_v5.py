# -*- coding: utf-8 -*-
"""make_pptx_v5.py — 32 页完整版（四张表 + 分析 + 型号卡 + 可编辑）

所有数字从 data_v5.json 读；型号卡留了图片位（灰色框 + 文件名），替换即用。
"""
import json
import os
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

BASE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(BASE, "data_v5.json"), encoding="utf-8"))
FIG = os.path.join(BASE, "fig5")
DECK = "Z-MAX_竞品与合作分析_v5_四表全量_2026-10-24.pptx"

CN = RGBColor(0x2E, 0x6F, 0xD9)
OS = RGBColor(0xE8, 0x87, 0x3A)
RED = RGBColor(0xD9, 0x3A, 0x3A)
GRN = RGBColor(0x2F, 0xA3, 0x6B)
ME = RGBColor(0x7B, 0x3F, 0xF2)
INK = RGBColor(0x1A, 0x1D, 0x24)
MUT = RGBColor(0x6B, 0x72, 0x80)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xD4, 0xD9, 0xE1)
GREYBG = RGBColor(0xF4, 0xF6, 0xF8)
MEBG = RGBColor(0xF1, 0xEA, 0xFE)
REDBG = RGBColor(0xFD, 0xEE, 0xEB)
GRNBG = RGBColor(0xEE, 0xF8, 0xF2)
BLUEBG = RGBColor(0xEE, 0xF3, 0xFD)
W, H = 13.333, 7.5
TOTAL = 33
FONT = "微软雅黑"

prs = Presentation()
prs.slide_width = Inches(W)
prs.slide_height = Inches(H)
BLANK = prs.slide_layouts[6]


def set_font(run, size, bold, color, font=FONT):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}ea")
    if ea is None:
        from lxml import etree
        ea = etree.SubElement(rPr, "{http://schemas.openxmlformats.org/drawingml/2006/main}ea")
    ea.set("typeface", font)


def new(bg=None):
    s = prs.slides.add_slide(BLANK)
    if bg is not None:
        rect(s, 0, 0, W, H, fill=bg)
    return s


def rect(s, x, y, w, h, fill=None, line_c=None, lw=0.75):
    from pptx.enum.shapes import MSO_SHAPE
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line_c is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line_c; sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    from pptx.oxml.ns import qn
    st = sh._element.find(qn("p:style"))
    if st is not None:
        sh._element.remove(st)
    return sh


def text(s, x, y, w, h, txt, size=12, bold=False, color=INK, line=1.3, align="l",
         anchor="t"):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.02)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE,
                          "b": MSO_ANCHOR.BOTTOM}[anchor]
    lines = txt.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = line
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER,
                       "r": PP_ALIGN.RIGHT}[align]
        for seg in re.split(r"(\*\*[^*]+\*\*)", ln):
            if not seg:
                continue
            r = p.add_run()
            if seg.startswith("**") and seg.endswith("**"):
                r.text = seg[2:-2]; set_font(r, size, True, color)
            else:
                r.text = seg; set_font(r, size, bold, color)
    return tb


def header(s, kick, title, n, sub=None):
    text(s, 0.62, 0.38, 11.8, 0.3, kick, 10.5, True, MUT)
    text(s, 0.62, 0.64, 12.1, 0.72, title, 22.5, True, INK)
    rect(s, 0.62, 1.42, 12.09, 0.014, fill=LINE)
    if sub:
        text(s, 0.62, 1.50, 12.1, 0.28, sub, 9.2, False, MUT)
    footer(s, n)


def footer(s, n):
    text(s, 0.62, 7.08, 9.0, 0.26,
         "Z-MAX · 竞品与合作分析 v5 · 2026-10-24 · 数据口径见%s" % ("本页" if n == TOTAL else "第 %d 页" % TOTAL),
         8.2, False, MUT)
    text(s, 11.6, 7.08, 1.1, 0.26, "%d/%d" % (n, TOTAL), 8.2, False, MUT, align="r")


def conclusion(s, y, txt, color=INK, size=11.5):
    rect(s, 0.62, y, 0.055, 0.40, fill=color)
    text(s, 0.78, y + 0.02, 11.95, 0.40, txt, size, True, color, line=1.2)


def table(s, x, y, w, data, col_w, fsize=8.2, row_h=0.32, head_h=0.34,
          head_fill=RGBColor(0xF0, 0xF2, 0xF6), aligns=None, bold_col0=False):
    rows, cols = len(data), len(data[0])
    gf = s.shapes.add_table(rows, cols, Inches(x), Inches(y), Inches(w),
                            Inches(head_h + row_h * (rows - 1)))
    t = gf.table
    scale = w / sum(col_w)
    for j, cw in enumerate(col_w):
        t.columns[j].width = Inches(cw * scale)
    t.rows[0].height = Inches(head_h)
    for i in range(1, rows):
        t.rows[i].height = Inches(row_h)
    for i, row in enumerate(data):
        for j, cell in enumerate(row):
            c = t.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.085)
            c.margin_top = c.margin_bottom = Inches(0.02)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid()
            c.fill.fore_color.rgb = head_fill if i == 0 else WHITE
            tf = c.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.line_spacing = 1.06
            al = "c" if i == 0 else (aligns[j] if aligns else "l")
            p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER,
                           "r": PP_ALIGN.RIGHT}[al]
            r = p.add_run()
            r.text = str(cell)
            set_font(r, fsize if i else fsize, i == 0 or (bold_col0 and j == 0),
                     INK if i else RGBColor(0x3A, 0x40, 0x4B))
    return gf


def pic(s, name, x, y, w=None, h=None):
    p = os.path.join(FIG, name)
    if not os.path.exists(p):
        return None
    kw = {}
    if w: kw["width"] = Inches(w)
    if h: kw["height"] = Inches(h)
    return s.shapes.add_picture(p, Inches(x), Inches(y), **kw)


def img_slot(s, x, y, w, h, fname):
    """图片位：真 PNG 占位图（可右键「更改图片」），上叠一行提示字"""
    ph = os.path.join(FIG, "_ph.png")
    if os.path.exists(ph):
        s.shapes.add_picture(ph, Inches(x), Inches(y), Inches(w), Inches(h))
    else:
        rect(s, x, y, w, h, fill=RGBColor(0xF7, 0xF8, 0xFA), line_c=RGBColor(0xC9, 0xCE, 0xD6))
    text(s, x, y + h / 2 - 0.12, w, 0.24, "产品图位", 8.6, True, RGBColor(0x9A, 0xA3, 0xAF),
         align="c")


def robot_cards(s, items, y0, cols=2, note=None):
    """型号卡：左图片位 + 右四行信息（2 列 × 3 行 = 一页 6 张）"""
    gap = 0.19
    cw = (12.09 - gap * (cols - 1)) / cols
    ch = 1.56
    for k, (comp, model, form, spec, fname) in enumerate(items):
        r_, c_ = divmod(k, cols)
        x = 0.62 + c_ * (cw + gap)
        y = y0 + r_ * (ch + 0.155)
        rect(s, x, y, cw, ch, fill=WHITE, line_c=LINE)
        img_slot(s, x + 0.11, y + 0.11, 1.24, ch - 0.22, fname)
        tx = x + 1.48
        tw = cw - 1.60
        text(s, tx, y + 0.11, tw, 0.26, comp, 10.2, True, INK)
        text(s, tx, y + 0.38, tw, 0.26, model, 9.8, True, CN)
        text(s, tx, y + 0.65, tw, 0.22, form, 7.8, False, MUT)
        text(s, tx, y + 0.88, tw, 0.60, spec, 7.5, False, MUT, line=1.18)
    if note and len(items) < cols * 3:
        r_, c_ = divmod(len(items), cols)
        x = 0.62 + c_ * (cw + gap)
        y = y0 + r_ * (ch + 0.155)
        rect(s, x, y, cw, ch, fill=MEBG)
        text(s, x + 0.16, y + 0.14, cw - 0.32, 0.24, "这一页怎么读", 9.6, True, ME)
        text(s, x + 0.16, y + 0.46, cw - 0.32, ch - 0.60, note, 8.4, False,
             RGBColor(0x3A, 0x40, 0x4B), line=1.32)


def findings_page(n, kick, title, items, color, concl=None):
    s = new()
    header(s, kick, title, n)
    y = 1.62
    hh = 1.02 if concl else 1.12
    for i, (h1, h2) in enumerate(items):
        rect(s, 0.62, y, 12.09, hh - 0.12, fill=WHITE, line_c=LINE)
        rect(s, 0.62, y, 0.055, hh - 0.12, fill=color)
        text(s, 0.80, y + 0.08, 0.42, 0.3, str(i + 1), 13, True, color)
        text(s, 1.26, y + 0.06, 11.2, 0.28, h1, 11.6, True, INK)
        text(s, 1.26, y + 0.36, 11.2, hh - 0.52, h2, 9.2, False, MUT, line=1.22)
        y += hh
    if concl:
        conclusion(s, y + 0.06, concl, color, 10.6)


# ══════════════════ P1 封面 ══════════════════
s = new(RGBColor(0x14, 0x17, 0x1D))
rect(s, 0.62, 2.30, 0.06, 1.60, fill=ME)
text(s, 0.95, 2.26, 11.4, 0.34, "竞品与合作分析 · 四表全量版 · 2026-10-24", 12.5, True,
     RGBColor(0xA8, 0xB0, 0xBE))
text(s, 0.95, 2.66, 11.4, 0.90, "谁在绕过集成商，谁值得我们拉进来", 34, True, WHITE)
text(s, 0.95, 3.66, 11.4, 0.80,
     "全球前 10 · 国内前 20 · 轮式双臂 15 家 · 混合形态 15 家 · 模型/数据 20 家",
     14, False, RGBColor(0xC9, 0xD1, 0xDD), line=1.5)
text(s, 0.95, 6.40, 11.4, 0.30,
     "33 页 · 全部文字与表格为 PowerPoint 原生对象，可直接删改 · 型号卡图片位可右键替换",
     9.5, False, RGBColor(0x8B, 0x93, 0xA0))

# ══════════════════ P2 阅读指引 ══════════════════
s = new()
header(s, "阅读指引", "这份报告有什么、怎么用、哪里不能当真", 2)
CH = [("第 1 章 · 3–6 页", "核心判断：谁打谁、谁谈谁、我方站哪一格",
       "竞合 2×2、逐家判断表、四维雷达"),
      ("第 2 章 · 7–9 页", "全球前 10：优势在哪、溢价从哪来", "估值条形、单台估值、4 条结论"),
      ("第 3 章 · 10–14 页", "国内前 20：特点与估值口径陷阱", "全量表、口径分色、4 条结论"),
      ("第 4 章 · 15–20 页", "轮式双臂 15 家：具体型号 + 数据强度", "四维表、15 张型号卡（3 页）、数据矩阵"),
      ("第 5 章 · 21–25 页", "混合形态 15 家：模型普遍弱一代", "四维表、15 张型号卡（3 页）、痕迹统计"),
      ("第 6 章 · 26–30 页", "模型/数据 20 家：开源可验证性是硬筛子", "全量表、架构分布、开源阶梯"),
      ("第 7 章 · 31–32 页", "策略与行动：四条打法 + 12 个月", "策略页、优先序表、投入曲线")]
y = 1.62
for a, b, c in CH:
    rect(s, 0.62, y, 12.09, 0.52, fill=WHITE, line_c=LINE)
    rect(s, 0.62, y, 0.05, 0.52, fill=CN)
    text(s, 0.80, y + 0.13, 2.0, 0.26, a, 9.4, True, MUT)
    text(s, 2.85, y + 0.13, 5.6, 0.26, b, 10.0, True, INK)
    text(s, 8.60, y + 0.14, 4.0, 0.26, c, 8.6, False, MUT)
    y += 0.60
rect(s, 0.62, 6.28, 12.09, 0.66, fill=REDBG)
rect(s, 0.62, 6.28, 0.055, 0.66, fill=RED)
text(s, 0.80, 6.34, 11.7, 0.56,
     "**三处不能当真**：① 估值口径混排（一级投后 / 二级市值 / IPO 理论测算），同一张表内不可直接比较；"
     "② 型号卡里的产品图是**占位框**，需替换为实拍图；③ 出货量与估值的时间点不完全对齐，见第 33 页。",
     9.0, False, INK, line=1.25)

# ══════════════════ P3 核心判断 ══════════════════
s = new()
header(s, "第 1 章 · 核心判断", "三句话，决定我们怎么对待每一家", 3)
tt = D["findings"]["thesis"]
y = 1.68
for i, (h1, h2) in enumerate(tt):
    rect(s, 0.62, y, 12.09, 1.34, fill=[MEBG, BLUEBG, GRNBG][i])
    rect(s, 0.62, y, 0.06, 1.34, fill=[ME, CN, GRN][i])
    text(s, 0.92, y + 0.16, 0.5, 0.6, "0%d" % (i + 1), 24, True, [ME, CN, GRN][i])
    text(s, 1.62, y + 0.14, 10.8, 0.40, h1, 15.5, True, INK)
    text(s, 1.62, y + 0.62, 10.8, 0.64, h2, 10.2, False, RGBColor(0x3A, 0x40, 0x4B), line=1.32)
    y += 1.50
conclusion(s, 6.30,
           "所以这张报告不是「谁厉害榜」，是「谁的商业模式和我重叠、谁能被我装进平台」。", ME)

# ══════════════════ P4 竞合 2×2 ══════════════════
s = new()
header(s, "第 1 章 · 竞合地图", "四个格子，四种对待方式", 4)
pic(s, "fig_rel.png", 0.62, 1.52, w=6.12)
CARDS = [("打｜直接竞品", RED, "它石、智元。差异不在模型，在「存量产线 + 多本体」"),
         ("谈｜模型伙伴", GRN, "具脑、无界。它出脑，我出场景与判据库"),
         ("看｜能力补充", MUT, "RIMBOT 日冕。触觉与力控模块，体量小"),
         ("守｜元任务层", ME, "右下只有我方：场景 9.0、自研本体 1.0")]
y = 1.58
for t1, c, t2 in CARDS:
    rect(s, 7.95, y, 4.78, 1.16, fill=WHITE, line_c=LINE)
    rect(s, 7.95, y, 0.055, 1.16, fill=c)
    text(s, 8.14, y + 0.10, 4.4, 0.28, t1, 11.2, True, c)
    text(s, 8.14, y + 0.44, 4.4, 0.64, t2, 8.8, False, MUT, line=1.24)
    y += 1.26
conclusion(s, 6.60, "守住右下角的前提不是模型，是工厂判据库 —— 那要三年现场数据，买不到。", ME)

# ══════════════════ P5 逐家判断 ══════════════════
s = new()
header(s, "第 1 章 · 逐家判断", "五家关键公司：关系、它的位置、证据、我们怎么办", 5)
data = [["公司", "关系", "它的位置", "可查证据", "对我们的意义"]]
for c, rel, pos, ev, mean in D["rel"]:
    data.append([c, rel, pos, ev, mean])
table(s, 0.62, 1.56, 12.09, data, [1.22, 1.16, 2.62, 4.32, 3.22], fsize=7.4,
      row_h=0.92, head_h=0.30, bold_col0=True)
text(s, 0.62, 6.62, 12.1, 0.36,
     "关系口径：直接竞品 = 商业模式重叠且不可合作；竞合 = 短期可采购、长期替代；"
     "伙伴 = 能力互补且不抢交付；补充 = 单点能力可插。", 8.4, False, MUT)

# ══════════════════ P6 四维雷达 ══════════════════
s = new()
header(s, "第 1 章 · 能力对比", "六家的四维形状：我方缺的只是本体", 6)
pic(s, "fig_radar.png", 0.62, 1.50, w=8.24)
text(s, 9.45, 1.60, 3.4, 0.34, "三种形状，加一个我方", 12, True, INK)
NOTES = [("满而均衡", "智元 — 四维全高，正面打不过，只能错位", RED),
         ("两轴突出", "它石 — 场景+模型双高，但只有自家本体", RED),
         ("模型孤立", "具脑/无界 — 模型强、场景与本体弱，正好互补", GRN),
         ("我方", "场景 9.0 / 数据 8.5 高，本体 1.0 低 —— 空位即定位", ME)]
y = 2.02
for h1, h2, c in NOTES:
    rect(s, 9.45, y, 3.3, 0.98, fill=WHITE, line_c=LINE)
    rect(s, 9.45, y, 0.05, 0.98, fill=c)
    text(s, 9.62, y + 0.08, 3.0, 0.24, h1, 10.4, True, c)
    text(s, 9.62, y + 0.36, 3.0, 0.56, h2, 8.4, False, MUT, line=1.22)
    y += 1.08
conclusion(s, 6.48, "四维里我们唯一低的是本体 —— 而这恰好是「不做又一个机器人公司」的证明。", ME)

# ══════════════════ P7 国际前 10 表 ══════════════════
s = new()
header(s, "第 2 章 · 全球格局", "全球前 10：按可查估值/市值排，中国占 6 席", 7,
       "注：Optimus 无独立估值、按「上市业务线」列；智元为 2026-10 新融资估值（拟港股）；优必选为价格区间；"
       "星海图 / 千寻同为 200 亿档，因数据可查性与整机出货证据略弱未入前 10")
data = [["#", "公司", "估值 / 市值", "性质", "核心看点"]]
for r in D["global10"]:
    data.append([r[0], r[1], r[2], r[4], r[5]])
table(s, 0.62, 1.86, 12.09, data, [0.35, 1.55, 2.55, 1.05, 6.59], fsize=7.7,
      row_h=0.44, head_h=0.29, bold_col0=False)

# ══════════════════ P8 国际图 ══════════════════
s = new()
header(s, "第 2 章 · 全球格局", "估值与单台估值：溢价差 41 倍，差在叙事不在交付", 8)
pic(s, "fig_g10.png", 0.62, 1.52, w=12.09)
conclusion(s, 5.98,
           "Figure 单台 1.86 亿元、宇树 4500 万、智元 967 万 —— 同一门生意，市场给三种价。", OS)

# ══════════════════ P9 国际优势分析 ══════════════════
findings_page(9, "第 2 章 · 全球格局", "国际前 10 的四条优势，以及我们该学什么",
              D["findings"]["global_edge"], OS,
              "对我们有用的只有第二条：出货与盈利是唯一能自己造的证据，叙事会被时间打折。")

# ══════════════════ P10 / P11 国内前 20 ══════════════════
for part, (i0, i1, note) in enumerate([
        (0, 10, "前 10 名：6 家在 200 亿档，估值已收敛 —— 这一档的区分度不在估值，在出货与数据"),
        (10, 20, "11–20 名：三家的数字要特别小心（乐聚 43 亿是实际投后、优艾 26.5 亿未达百亿、云深处 139 亿是 IPO 发行估值）")]):
    s = new()
    header(s, "第 3 章 · 国内格局", "国内前 20（%d）" % (part + 1), 10 + part, note)
    data = [["#", "公司", "估值 / 市值", "性质", "关键数据"]]
    for r in D["domestic20"][i0:i1]:
        data.append([r[0], r[1], r[2], r[4], r[5]])
    table(s, 0.62, 1.82, 12.09, data, [0.35, 1.55, 2.35, 1.35, 6.49], fsize=7.6,
          row_h=0.455, head_h=0.30)

# ══════════════════ P12 国内特点 ══════════════════
findings_page(12, "第 3 章 · 国内格局", "国内前 20 的四个特点（有两个是对我们有利的）",
              D["findings"]["domestic_traits"], CN)

# ══════════════════ P13 国内图 ══════════════════
s = new()
header(s, "第 3 章 · 国内格局", "同一张榜里混了四种上市性质，颜色分开才看得懂", 13)
pic(s, "fig_d20.png", 0.62, 1.50, w=11.0)
conclusion(s, 6.34,
           "蓝=科创板/拟港股、青=港股、灰=Pre-IPO 未达百亿、浅蓝=私募 —— 只有前两类是市场定价。", CN)

# ══════════════════ P14 口径陷阱 ══════════════════
s = new()
header(s, "第 3 章 · 口径陷阱", "三个数字，谁引用谁被打回", 14)
CASES = [("乐聚机器人", "常被引用 104 亿", "实际投后 43.27 亿",
          "104 亿是 IPO 理论测算值（按募资规模反推），不是最后一轮投后估值。差 2.4 倍。", RED),
         ("优艾智合", "常被表述「百亿独角兽」", "实际 26.5 亿",
          "Pre-IPO 阶段，未达百亿门槛；三年累计亏损 8.44 亿。它是全表最像我们的公司，但体量被高估。", RED),
         ("优必选", "300 亿 / 530 亿港元两个说法", "取决于取价时点",
          "港股 2026 年波动区间造成；引用时要带日期，否则同一家公司在两份材料里差 76%。", OS)]
y = 1.62
for nm, myth, real, why, c in CASES:
    rect(s, 0.62, y, 12.09, 1.36, fill=WHITE, line_c=LINE)
    rect(s, 0.62, y, 0.055, 1.36, fill=c)
    text(s, 0.84, y + 0.12, 2.6, 0.30, nm, 13, True, INK)
    text(s, 3.55, y + 0.13, 3.0, 0.26, myth, 9.6, False, RGBColor(0x9A, 0x7B, 0x7B))
    text(s, 6.60, y + 0.13, 2.6, 0.26, real, 9.6, True, c)
    text(s, 0.84, y + 0.56, 11.6, 0.70, why, 9.0, False, MUT, line=1.24)
    y += 1.48
conclusion(s, 6.22,
           "对外材料只用三种表述：某日收盘市值、某轮投后估值、招股书披露 —— 别用「约」和「级」。", RED)

# ══════════════════ P15 轮式表 ══════════════════
s = new()
header(s, "第 4 章 · 轮式双臂", "具身形态·轮式底盘双臂 15 家（四维）", 15,
       "13/15 明确轮式底盘；云深处是轮足四足、中科慧灵轮式/双足 —— 行业共识是「不摔、能进电梯、能过门槛」")
data = [["#", "公司", "Agent 场景", "模型能力", "数据资产", "轮式本体 / 型号"]]
for r in D["wheel15"]:
    data.append([r[0], r[1], r[2], r[3], r[4], r[5]])
table(s, 0.62, 1.86, 12.09, data, [0.32, 1.28, 2.55, 2.85, 2.55, 2.54], fsize=6.7,
      row_h=0.325, head_h=0.28)

# ══════════════════ P16–P18 型号卡 ══════════════════
WNOTE = ["这 5 家都有轮式双臂整机 + 公开的数据或模型证据。除中国移动（集团自用场景）外全部对外销售，"
         "属于我们**可以直接采购或对标**的对象。",
         "云深处是轮足四足、中科慧灵轮式/双足 —— 严格说不是「轮式双臂」，列进来是因为形态相近且都在工业场景交付。",
         "优艾智合是全表最像我们的：半导体晶圆盒搬运、300+ 客户、一脑多态。它证明「一脑多形态」卖得进工厂。"]
for k, sl in enumerate([D["robots_w"][0:5], D["robots_w"][5:10], D["robots_w"][10:15]]):
    s = new()
    header(s, "第 4 章 · 具体机器人", "轮式双臂：%d 个具体型号（%d/3）" % (len(sl), k + 1), 16 + k,
           "型号与参数按公开资料填写；图位可右键「更改图片」替换，替换后删掉叠在上面的「产品图位」四字")
    robot_cards(s, sl, 1.86, note=WNOTE[k])

# ══════════════════ P19 轮式分析 ══════════════════
findings_page(19, "第 4 章 · 轮式双臂", "轮式的四个结论：数据两极分化，模型只有 4 家能说清",
              D["findings"]["wheel_edge"], CN,
              "这张表里最该警惕的不是最强的，是最像的 —— 优艾用「一脑多形态」卖进了半导体，那条路我们走得通。")

# ══════════════════ P20 轮式数据矩阵 ══════════════════
s = new()
header(s, "第 4 章 · 轮式双臂", "数据资产强弱：3 家能自证，9 家拿不出", 20)
pic(s, "fig_wheel.png", 0.62, 1.52, w=12.09)
conclusion(s, 6.30,
           "数据权重加大后，这条直接决定排序 —— 不是谁机器人好，是谁拿得出可训练的数据。", CN)

# ══════════════════ P21 混合表 ══════════════════
s = new()
header(s, "第 5 章 · 混合形态", "AMR 底盘 + 协作臂 15 家（四维）", 21,
       "这张表多数是集成商，模型与数据普遍弱于轮式一代 —— 15 家里只有 10 家拿得出数据或模型合作痕迹")
data = [["#", "公司", "Agent 场景", "模型能力", "数据资产", "本体 / 型号"]]
for r in D["hybrid15"]:
    data.append([r[0], r[1], r[2], r[3], r[4], r[5]])
table(s, 0.62, 1.86, 12.09, data, [0.32, 1.66, 2.42, 2.70, 2.42, 2.57], fsize=6.7,
      row_h=0.325, head_h=0.28)

# ══════════════════ P22–P23 混合型号卡 ══════════════════
HNOTE = ["这 5 家里只有迦智、优艾、艾利特拿得出数据痕迹；富唯、节卡的模型与数据都写「未公开」，是本表最弱的两个。",
         "海康、新松、达明、Flexiv 是「设备强、模型弱」的典型 —— 它们的数据是设备运行日志，不是带动作标签的训练集。",
         "FANUC、Productive 是成熟工业自动化往具身补；NEURA 是欧洲叙事型，交付证据最弱。"]
for k, sl in enumerate([D["robots_h"][0:5], D["robots_h"][5:10], D["robots_h"][10:15]]):
    s = new()
    header(s, "第 5 章 · 具体机器人", "混合形态：%d 个具体型号（%d/3）" % (len(sl), k + 1), 22 + k,
           "这类产品公开图较少，建议优先用现场实拍；图位可右键「更改图片」替换")
    robot_cards(s, sl, 1.86, note=HNOTE[k])

# ══════════════════ P24 混合分析 ══════════════════
s = new()
header(s, "第 5 章 · 混合形态", "混合形态：模型落后一代，但这正是入口", 25)
y = 1.58
for i, (h1, h2) in enumerate(D["findings"]["hybrid_edge"][:3]):
    rect(s, 0.62, y, 12.09, 0.86, fill=WHITE, line_c=LINE)
    rect(s, 0.62, y, 0.055, 0.86, fill=GRN)
    text(s, 0.80, y + 0.06, 0.4, 0.28, str(i + 1), 11.5, True, GRN)
    text(s, 1.22, y + 0.05, 11.2, 0.26, h1, 10.8, True, INK)
    text(s, 1.22, y + 0.32, 11.2, 0.48, h2, 8.8, False, MUT, line=1.2)
    y += 0.94
pic(s, "fig_hybrid.png", 0.62, 4.40, w=11.0)
conclusion(s, 6.62, "对这批公司，我们不是竞品，是给它们装脑子的人 —— 谈判位置比轮式那边好。", GRN)

# ══════════════════ P25 / P26 模型表 ══════════════════
for k, (i0, i1) in enumerate([(0, 10), (10, 20)]):
    s = new()
    header(s, "第 6 章 · 模型与数据", "模型/数据供应商 20 家（%d/2）" % (k + 1), 26 + k,
           "权重：开源 > JEPA/分层 > Agent 工业 > 数据 > 触觉；有本体扣分")
    data = [["#", "公司", "开源（可查证据）", "架构 / JEPA / 分层", "Agent 工业", "数据资产"]]
    for r in D["model20"][i0:i1]:
        data.append([r[0], r[1], r[2], r[9] + "｜" + r[3], r[4], r[5]])
    table(s, 0.62, 1.86, 12.09, data, [0.30, 1.12, 2.95, 2.60, 2.55, 2.57], fsize=6.4,
          row_h=0.485, head_h=0.28)

# ══════════════════ P27 架构分布 ══════════════════
s = new()
header(s, "第 6 章 · 模型与数据", "20 家的技术路线：7 家押纯世界模型，4 家是 VLA 系", 28)
pic(s, "fig_arch.png", 0.62, 1.56, w=11.6)
conclusion(s, 5.92,
           "7 家押纯世界模型、4 家走 VLA、真正 JEPA 只有 3 家 —— 谈之前先问权重能不能下载。", ME)

# ══════════════════ P28 开源阶梯 ══════════════════
s = new()
header(s, "第 6 章 · 模型与数据", "开源可验证性：只有第一层能自己跑一遍", 29)
pic(s, "fig_open.png", 0.62, 1.56, w=12.09)
conclusion(s, 6.06,
           "合作前先要三样：权重链接、License、跑通的 benchmark —— 三样给不出两家以上，就当它闭源。", GRN)

# ══════════════════ P29 模型层分析 ══════════════════
findings_page(30, "第 6 章 · 模型与数据", "模型层的四个结论：能谈的只有 11 家", D["findings"]["model_edge"], ME,
              "20 家里 11 家不造整机 —— 我们要的不是「更聪明的脑」，是「愿意在一个工位上被调三个月的脑」。")

# ══════════════════ P30 策略 ══════════════════
s = new()
header(s, "第 7 章 · 策略", "四条打法：不做机器人公司，做工艺与 AI 之间的翻译层", 31)
ST = [("01", "把「最后一公里」做成产品", "光模块插拔的 0.1N 力控、金手指零划痕、批次偏移容差 —— 这些不在别人的模型里，"
                                      "在我们的元任务配置和工厂数据里。任何大脑或本体，接上接口就能在产线上干活。", ME),
      ("02", "和无界、具脑做「模型–场景」互换", "它们要场景验证，我们要大脑能力。不签独家，让多家模型在平台上竞争，客户按效果选 —— "
                                       "我们做「模型应用商店」的运营方。", GRN),
      ("03", "对智元保持供应商姿态，警惕平台野心", "客户指定智元本体就采购 + 叠加元任务。平台必须做到模型与本体解耦："
                                         "智元本体能跑，别的本体也能跑。跨本体兼容条款要写进每一份合同。", CN),
      ("04", "对它石不做正面竞争，做利旧差异", "它石是「自研本体+自研模型+新建产线」，我们是「存量设备+多品牌混线」。"
                                     "存量市场规模远大于新建，且它石的方案进不去。", RED)]
y = 1.62
for n_, t1, t2, c in ST:
    rect(s, 0.62, y, 12.09, 1.06, fill=WHITE, line_c=LINE)
    rect(s, 0.62, y, 0.06, 1.06, fill=c)
    text(s, 0.88, y + 0.12, 0.55, 0.5, n_, 19, True, c)
    text(s, 1.55, y + 0.11, 10.95, 0.30, t1, 12.5, True, INK)
    text(s, 1.55, y + 0.47, 10.95, 0.54, t2, 9.3, False, MUT, line=1.28)
    y += 1.20
conclusion(s, 6.46,
           "四条打法的共同判断：我们不和人比模型，比的是「谁能让别人的模型在我这条产线上跑起来」。", ME)

# ══════════════════ P31 优先序 + 投入 ══════════════════
s = new()
header(s, "第 7 章 · 策略", "合作优先序：先谈谁、先买谁、先守什么", 32)
data = [["优先级", "对象", "动作", "合同要点", "时间窗"],
        ["1", "无界智航", "谈（已有 POC）", "能力按工位计价；数据脱敏双向授权；退出时权重可迁移", "0–3 个月"],
        ["2", "具脑磐石", "谈（架构顾问）", "Cog-WM 作可插拔大脑选项；小样本场景先跑 PoC", "0–6 个月"],
        ["3", "迦智 / 艾利特 / Flexiv", "买（本体+场景）", "驱动与接口开放；不绑专用夹爪；二级市场可替换", "3–9 个月"],
        ["4", "优艾智合", "竞合（最像我们）", "半导体搬运场景错开；一脑多态可参考但不同盟", "持续观察"],
        ["5", "智元", "买（本体）", "跨本体兼容条款；模型与本体解耦验证", "按客户指定"],
        ["—", "它石智航", "不打（差异化）", "存量利旧 + 多品牌混线，不进它的新建线战场", "—"]]
table(s, 0.62, 1.58, 7.35, data, [0.55, 1.45, 1.45, 3.2, 1.1], fsize=7.6,
      row_h=0.62, head_h=0.32, bold_col0=True)
pic(s, "fig_invest.png", 8.02, 1.60, w=4.74)
text(s, 8.02, 4.72, 4.74, 1.4,
     "投入产出（实测）：现状 20 条只覆盖 38%，针对性补 8 条就到了 69%，补齐 17 条到 9/9 全覆盖。"
     "问题不是条数不够，是那 20 条选错了。", 8.4, False, MUT, line=1.3)
conclusion(s, 6.42, "12 个月失败线：8 个月内跨本体换型时间仍 >2h，就退回项目制集成，别硬撑平台叙事。", RED)

# ══════════════════ P32 口径与来源 ══════════════════
s = new()
header(s, "附录", "口径、来源、以及这份报告不能证明的事", 33)
L = ["**估值口径**：一级市场投后估值（私募）、二级市场收盘市值（科创板/港股）、IPO 发行估值、"
     "IPO 理论测算值 —— 四者不可直接比较。本报告已在表内用「性质」列标注。",
     "**时间点**：估值数据截至 2026-10-24；出货量为各公司 2025 年或 2026H1 披露口径，两者不同期。",
     "**未披露 ≠ 0**：表内「未公开/未明确」原样保留；不折算、不估算、不填 0。",
     "**模型架构**：仅采信有公开论文、开源仓库或官方技术博客支撑的标注；"
     "「VLA 大模型」这类一句话描述统一归为「未给架构证据」。",
     "**开源可验证性**：以能否下载权重+代码+License 为准；只开数据集不算开源模型。",
     "**产品图**：型号卡内为占位框，需替换为实拍图；本报告不提供版权图片。",
     "**不能证明的事**：这些数字不能证明任何一家「技术更强」—— 只证明市场愿意给它多少估值。"]
y = 1.56
for i, ln in enumerate(L):
    text(s, 0.62, y, 0.30, 0.28, "%d" % (i + 1), 11, True, MUT)
    text(s, 1.00, y, 11.6, 0.62, ln, 9.4, False, INK, line=1.30)
    y += 0.68
rect(s, 0.62, 6.34, 12.09, 0.52, fill=GREYBG)
text(s, 0.80, 6.42, 11.7, 0.36,
     "数据源：老倪提供的四张表（2026-10-24）+ 公司官网/公告/招股书/公开评测榜单；"
     "逐条录入未改数字。生成脚本 data_v5.py → figs_v5.py → make_pptx_v5.py。",
     8.4, False, MUT)

prs.save(os.path.join(BASE, DECK))
print("saved:", os.path.join(BASE, DECK), os.path.getsize(os.path.join(BASE, DECK)), "bytes",
      len(prs.slides.__iter__.__self__._sldIdLst), "slides")
