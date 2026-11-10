#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_deck2.py — 生成《Z-MAX 项目进展横向对比》

只讲项目进展与对比，不出现分层架构与技术缩写。
重新生成: python3 make_deck2.py
"""
from __future__ import annotations

import json
import os
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Z-MAX项目进展横向对比_5.50.D-P2_20261110.pptx")

W, H = 13.333, 7.5
M = 0.78
CW = W - 2 * M
FOOT_Y = 6.98

INK = "1F2937"
MUTED = "6B7280"
LINE = "E5E7EB"
SOFT = "F8FAFC"
GOOD = "059669"
OKC = "D97706"
RISK = "DC2626"
ACCENT = "1D4ED8"
WHITE = "FFFFFF"
EA = "微软雅黑"

TONE = {"good": GOOD, "ok": OKC, "risk": RISK}


def _font(run, size, bold=False, color=INK, latin="Arial"):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = latin
    f.color.rgb = RGBColor.from_string(color)
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", EA)


def text(slide, x, y, w, h, lines, size=13, color=INK, bold=False,
         align=PP_ALIGN.LEFT, space=6, anchor=MSO_ANCHOR.TOP, line_sp=1.15):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    if isinstance(lines, str):
        lines = [lines]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space)
        p.line_spacing = line_sp
        for seg in re.split(r"(\*\*[^*]+\*\*)", str(ln)):
            if not seg:
                continue
            r = p.add_run()
            if seg.startswith("**") and seg.endswith("**") and len(seg) > 4:
                r.text, b = seg[2:-2], True
            else:
                r.text, b = seg, bold
            _font(r, size, b, color)
    return box


def rect(slide, x, y, w, h, fill=SOFT, line=None, radius=False):
    shape = slide.shapes.add_shape(
        5 if radius else 1,
        Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    if line:
        shape.line.color.rgb = RGBColor.from_string(line)
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def page(prs, tag, title, sub=None, bg=WHITE):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    if bg != WHITE:
        rect(s, 0, 0, W, H, fill=bg)
    if tag:
        rect(s, M, 0.52, 0.055, 0.30, fill=ACCENT)
        text(s, M + 0.18, 0.50, 7.0, 0.34, tag, 11, ACCENT, True)
    text(s, M, 0.86, CW, 0.80, title, 24, INK, True, line_sp=1.05)
    if sub:
        text(s, M, 1.66, CW, 0.50, sub, 12.5, MUTED, line_sp=1.25)
    return s


def footer(s, note):
    rect(s, M, FOOT_Y - 0.10, CW, 0.008, fill=LINE)
    text(s, M, FOOT_Y, CW * 0.66, 0.26, note, 9, MUTED)
    text(s, W - M - 2.45, FOOT_Y, 2.45, 0.26,
         "项目进展版 · 2026-11-10", 9, MUTED, align=PP_ALIGN.RIGHT)


def table(s, x, y, w, rows, cols, head_h=0.38, row_h=0.5, size=10,
          colors=None, first_bold=True):
    n = len(rows)
    tb = s.shapes.add_table(n, len(cols), Inches(x), Inches(y),
                            Inches(w), Inches(head_h + row_h * (n - 1))).table
    for i, cw in enumerate(cols):
        tb.columns[i].width = Inches(cw)
    tb.rows[0].height = Inches(head_h)
    for i in range(1, n):
        tb.rows[i].height = Inches(row_h)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = tb.cell(ri, ci)
            cell.margin_left = Inches(0.10)
            cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.03)
            cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if ri == 0:
                cell.fill.fore_color.rgb = RGBColor.from_string(INK)
            else:
                cell.fill.fore_color.rgb = RGBColor.from_string(
                    WHITE if ri % 2 else SOFT)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            r = p.add_run()
            r.text = str(val)
            if ri == 0:
                _font(r, size, True, WHITE)
            else:
                col = INK
                if colors and ri - 1 < len(colors) and colors[ri - 1] and ci > 0:
                    col = colors[ri - 1]
                _font(r, size, first_bold and ci == 0, col)
    return tb


# ══════════════════════════════════════════════════════════════════════
prs = Presentation()
prs.slide_width = Inches(W)
prs.slide_height = Inches(H)

# ── P1 封面 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(prs.slide_layouts[6])
rect(s, 0, 0, W, H, fill="111827")
rect(s, 0, 0, 0.10, H, fill=ACCENT)
text(s, 1.0, 2.05, 11.0, 0.42, "Z-MAX  ·  项目进展", 13, "93C5FD", True)
text(s, 1.0, 2.55, 11.2, 1.5,
     "五个方案，同一件事：\n把光模块稳定地拿起来、放进去、摆整齐",
     30, WHITE, True, line_sp=1.28)
rect(s, 1.02, 4.42, 1.5, 0.05, fill=ACCENT)
text(s, 1.0, 4.72, 11.0, 1.1, [
    "他山  ·  无界智航  ·  智元机器人  ·  自研 Z100Fd  ·  已在产线跑的两代插拔工位",
    "写到 2026-11-10 为止，各自到哪一步、给了什么承诺、还缺什么",
], 12.5, "9CA3AF", line_sp=1.5)
text(s, 1.0, 6.55, 6.0, 0.3, "2026-11-10", 11, "6B7280")
text(s, W - 3.0, 6.55, 2.2, 0.3, "项目进展版", 11, "6B7280", align=PP_ALIGN.RIGHT)

# ── P2 一页结论 ───────────────────────────────────────────────────────
s = page(prs, "结论先行",
         "两条线能交货，两家给了方案和报价，一条自研线还在打成功率",
         "不评价先进与否，只看现在能不能兑现。")
cards = [
    ("已交货", "插拔工位", "两代（固定式 / 自主找位），产线在跑，是唯一有出货证据的", GOOD),
    ("有方案有报价", "无界智航 · 摆盘", "1000 件/时、可翻面、三档配置报价都已给出", ACCENT),
    ("还在打成功率", "自研 Z100Fd", "本体已装好，正在采数据训练，暂不具备正常插拔能力", RISK),
]
bw = (CW - 0.5 * 2) / 3
for i, (tag, name, note, col) in enumerate(cards):
    x = M + i * (bw + 0.5)
    rect(s, x, 2.45, bw, 2.05, fill=SOFT, line=LINE, radius=True)
    rect(s, x, 2.45, 0.05, 2.05, fill=col)
    text(s, x + 0.32, 2.68, bw - 0.6, 0.28, tag, 10.5, col, True)
    text(s, x + 0.32, 3.02, bw - 0.6, 0.42, name, 17, INK, True)
    text(s, x + 0.32, 3.56, bw - 0.62, 0.80, note, 10.5, MUTED, line_sp=1.35)

rect(s, M, 4.85, CW, 1.15, fill="EFF6FF", radius=True)
text(s, M + 0.35, 5.05, CW - 0.7, 0.80,
     "**一句话**：能交货的只有插拔这一条线；摆盘方向两家外部供应商都还停在"
     "「方案 / 演示」，没有上机数据；自研那条线短期内不能进交付承诺。",
     13, INK, line_sp=1.4)
footer(s, "结论先行 · 全部为现状描述，不含预测")

# ── P3 发展脉络 ───────────────────────────────────────────────────────
s = page(prs, "路径",
         "这条路上有五个台阶，我们走到第三级，供应商分别站在不同位置",
         "每一级解决的问题不同，不是替代关系，是叠加关系。")
steps = [
    ("一", "固定轨迹", "人教一遍，机器照着走。换一种料，要重新教。", "已在产线", GOOD),
    ("二", "伺服视觉", "到了大致位置，自己找对目标再动手。", "已落地", GOOD),
    ("三", "增强感知", "来料变了、位置歪了，不用重新教也能认。", "准备立项", OKC),
    ("四", "视触觉动作", "最后那一点靠手感完成，不靠眼睛看。", "在研", MUTED),
    ("五", "桌面式约束工具箱", "不写程序，装上就能用，谁来都能操作。", "方向", MUTED),
]
y0 = 2.35
for i, (num, name, desc, state, col) in enumerate(steps):
    y = y0 + i * 0.83
    rect(s, M, y, CW, 0.72, fill=SOFT if i % 2 == 0 else WHITE, line=LINE, radius=True)
    text(s, M + 0.28, y + 0.16, 0.4, 0.40, num, 15, col, True)
    text(s, M + 0.75, y + 0.16, 2.75, 0.40, name, 14, INK, True)
    text(s, M + 3.62, y + 0.20, 6.65, 0.36, desc, 11.5, MUTED)
    text(s, W - M - 1.55, y + 0.20, 1.35, 0.32, state, 10.5, col, True,
         align=PP_ALIGN.RIGHT)
footer(s, "五个台阶回答的是同一个问题：换一次料，要花多少人和时间")

# ── P4 横向对比总表 ───────────────────────────────────────────────────
s = page(prs, "横向对比",
         "四个对象，摆在一张表里看，差别不在能力描述，在「有没有兑现」",
         "同一列里，越往下越接近可交付。")
rows = [
    ["项目", "供应方", "做什么", "现在到哪一步", "给了什么承诺"],
    ["插拔工位 · 第一代", "他山", "光模块插拔", "已上车、产线在跑", "节拍与良率"],
    ["插拔工位 · 第二代", "康视", "微小空间自主找位", "已落地、可复现", "到位置自己找，不用重新教"],
    ["摆盘", "无界智航", "吸盘取放、可翻面", "方案 + 三档报价已给", "1000 件/时"],
    ["摆盘", "智元机器人", "夹爪取放", "演示视频", "待补产线数据"],
    ["插拔（自研）", "我们自己", "7 kg 协作臂 + 抓取动作", "本体装完，采集训练中", "成功率尚未达标"],
]
colors = [GOOD, GOOD, ACCENT, OKC, RISK]
table(s, M, 2.42, CW, rows, [2.30, 1.45, 2.35, 2.40, 3.28],
 head_h=0.42, row_h=0.62, size=10.5, colors=colors)
text(s, M, 6.42, CW, 0.40,
     "注：插拔与摆盘是两道不同工序，节拍数字不能直接横比。", 10, MUTED)
footer(s, "横向对比 · 承诺栏只写对方书面给出或明确答应的内容")

# ── P5 他山 ───────────────────────────────────────────────────────────
s = page(prs, "对象一 · 他山",
         "他山：把「人会教」变成「机器照做」，这条路已经跑通",
         "固定点位 + 示教轨迹，是四个对象里唯一有出货记录的一条。")
blocks = [
    ("做了什么", ["固定点位、人工示教一遍轨迹", "机器按同一套动作重复执行"], GOOD),
    ("现在到哪", ["已上产线，持续运行", "是唯一能拿出出货证据的方案"], GOOD),
    ("强在哪", ["稳定、可复制、验收口径简单", "换工位只要重新示教，不用改程序"], GOOD),
    ("边界在哪", ["换一种来料，整套动作要重新教", "来料位置偏移要靠人工摆正"], OKC),
]
bw2 = (CW - 0.36) / 2
for i, (h, items, col) in enumerate(blocks):
    x = M + (i % 2) * (bw2 + 0.36)
    y = 2.40 + (i // 2) * 2.05
    rect(s, x, y, bw2, 1.85, fill=WHITE, line=LINE, radius=True)
    rect(s, x, y, 0.045, 1.85, fill=col)
    text(s, x + 0.30, y + 0.22, bw2 - 0.55, 0.32, h, 12.5, col, True)
    text(s, x + 0.30, y + 0.66, bw2 - 0.58, 1.00,
         ["· " + it for it in items], 11, INK, line_sp=1.45)
footer(s, "他山 · 结论：可以继续放量，边界清楚")

# ── P6 无界智航 ───────────────────────────────────────────────────────
s = page(prs, "对象二 · 无界智航",
         "无界智航：目前唯一给出书面节拍承诺 + 三档报价 + 扩展包定位的供应方",
         "吸盘方案，可翻面。比节拍更值钱的是它对自己的定位。")
left = [
    ("给了什么承诺", "1000 件/时", "套盘翻面一次到位"),
    ("给了什么配置", "三档", "基础型 / 精细型 / 专家型，各带目标报价"),
]
for i, (h, big, note) in enumerate(left):
    y = 2.45 + i * 1.55
    rect(s, M, y, 6.20, 1.35, fill=SOFT, line=LINE, radius=True)
    text(s, M + 0.30, y + 0.18, 2.6, 0.30, h, 10.5, MUTED, True)
    text(s, M + 0.30, y + 0.52, 2.2, 0.55, big, 21, ACCENT, True)
    text(s, M + 2.65, y + 0.60, 3.35, 0.60, note, 10.5, INK, line_sp=1.3)

rect(s, M, 5.62, CW, 1.02, fill="ECFDF5", radius=True)
text(s, M + 0.32, 5.78, CW - 0.65, 0.72,
     "**最值钱的一条**：带散热片的光模块怎么抓，他们给的是「扩展包」——机器人加装即可，"
     "不是另做一套自动化。我们卖能力、他们供硬件，位置不冲突。",
     12, INK, line_sp=1.35)
footer(s, "无界智航 · 结论：优先合作，先上一条线验节拍")

# ── P7 智元 ───────────────────────────────────────────────────────────
s = page(prs, "对象三 · 智元机器人",
         "智元：有夹爪抓取演示，但演示和「产线上连着跑」是两件事",
         "夹爪形态接近人手，适合异形件，这是它的长处。")
blocks = [
    ("给了什么", ["夹爪抓取的演示视频", "能看到完整取放动作"], ACCENT),
    ("缺什么", ["没有连续运行数据", "没有节拍、没有良率、没有换型时间"], OKC),
    ("怎么用", ["保持跟进，作为备选", "不排他、不预付，等有数据再谈"], MUTED),
]
bw3 = (CW - 0.72) / 3
for i, (h, items, col) in enumerate(blocks):
    x = M + i * (bw3 + 0.36)
    rect(s, x, 2.50, bw3, 2.30, fill=WHITE, line=LINE, radius=True)
    rect(s, x, 2.50, bw3, 0.055, fill=col)
    text(s, x + 0.28, 2.75, bw3 - 0.52, 0.34, h, 12.5, col, True)
    text(s, x + 0.28, 3.22, bw3 - 0.55, 1.35, ["· " + it for it in items],
         11, INK, line_sp=1.5)

rect(s, M, 5.12, CW, 1.32, fill="FFFBEB", radius=True)
text(s, M + 0.32, 5.30, CW - 0.65, 1.00,
     "**判断**：演示视频证明「能抓」，不证明「能一直抓对」。\n"
     "没有连续运行数据的方案，不能用来做产能承诺。", 12.5, INK, line_sp=1.45)
footer(s, "智元机器人 · 结论：备选，不排他")

# ── P8 自研 Z100Fd ────────────────────────────────────────────────────
s = page(prs, "对象四 · 自研 Z100Fd",
         "自研 Z100Fd：硬件走完了，软件还在打成功率",
         "7 kg 协作臂，本体已组装完成。这条路不靠供应商，慢，但东西在自己手里。")
rows = [
    ["阶段", "状态", "说明"],
    ["本体", "已完成", "协作臂组装、上电、能按指令动"],
    ["数据采集", "进行中", "已在收集抓取与插拔过程的数据"],
    ["动作训练", "进行中", "反复迭代，指标还不稳定"],
    ["可用性", "未达标", "成功率不足以支撑正常的光模块插拔"],
]
table(s, M, 2.45, 8.20, rows, [1.55, 1.55, 5.10],
      head_h=0.40, row_h=0.66, size=11,
      colors=[GOOD, OKC, OKC, RISK])

rect(s, M + 8.55, 2.45, CW - 8.55, 3.30, fill="FEF2F2", radius=True)
text(s, M + 8.80, 2.68, CW - 9.05, 0.45, "为什么慢", 12.5, RISK, True)
text(s, M + 8.80, 3.18, CW - 9.05, 2.35,
     ["不是硬件不行，", "是「教它做对」这件事本身要样本。",
      "光模块插拔的容差很小，", "样本不够就学不会。"],
     11, INK, line_sp=1.5)
text(s, M, 6.35, CW, 0.42,
     "结论：立项目标写成「数据与动作积累」，不写成交付承诺；对外不宣传、不报价。",
     11.5, RISK, True)
footer(s, "自研 Z100Fd · 结论：技术储备，不进交付")

# ── P9 五维对比 ───────────────────────────────────────────────────────
s = page(prs, "放在一起看",
         "同样的五个问题问四家，答案的差别一目了然",
         "评分只反映「现在能不能兑现」，不代表技术高低。")
rows = [
    ["对象", "现在能否交货", "节拍是否书面", "换型要多久", "报价是否清晰", "风险"],
    ["他山", "能（产线在跑）", "有", "要重新示教", "已结算", "低"],
    ["康视", "能（已落地）", "有", "不用重教", "已结算", "低"],
    ["无界智航", "还不能（未上机）", "1000 件/时", "换吸盘即可", "三档已给", "中"],
    ["智元机器人", "还不能（只有演示）", "无", "未知", "无", "高"],
    ["自研 Z100Fd", "还不能（未达标）", "无", "需重训", "无", "高"],
]
colors = [GOOD, GOOD, OKC, RISK, RISK]
table(s, M, 2.42, CW, rows, [1.85, 2.50, 1.80, 2.05, 1.75, 1.83],
      head_h=0.44, row_h=0.66, size=10.5, colors=colors)
text(s, M, 6.30, CW, 0.42,
     "同一列里，绿色是「已经兑现」，黄色是「承诺待验证」，红色是「还没有」。",
     10.5, MUTED)
footer(s, "五维对比 · 全部按「当下可验证的事实」打分")

# ── P10 差距 ──────────────────────────────────────────────────────────
s = page(prs, "差距",
         "三句话说完我们现在的位置",
         None)
gaps = [
    ("一", "能交货的只有一条线", "插拔工位两代都在产线跑；摆盘方向两家都还没上机，"
     "一个只有方案，一个只有演示。"),
    ("二", "千件级节拍只有一家给了书面承诺", "无界智航的 1000 件/时是目前唯一写下来的数字，"
     "但它是承诺，不是实测，要上机跑过才算。"),
    ("三", "自研线的成功率还没到「能插光模块」", "本体装好只是起点。这条线短期内不能对外承诺，"
     "否则就是把风险提前卖出去。"),
]
for i, (num, head, body) in enumerate(gaps):
    y = 2.30 + i * 1.42
    rect(s, M, y, CW, 1.24, fill=SOFT if i % 2 == 0 else WHITE, line=LINE, radius=True)
    text(s, M + 0.32, y + 0.20, 0.5, 0.55, num, 20, ACCENT, True)
    text(s, M + 0.92, y + 0.20, 4.65, 0.42, head, 14, INK, True)
    text(s, M + 0.92, y + 0.68, CW - 1.30, 0.46, body, 11, MUTED, line_sp=1.3)
footer(s, "差距 · 只列事实，不列原因分析")

# ── P11 建议 ──────────────────────────────────────────────────────────
s = page(prs, "建议",
         "四件事，按「现在能不能兑现」排序，不按听起来多先进",
         "顺序错了，钱会花在等不到结果的地方。")
adv = [
    ("立即", "插拔线继续放量", "唯一有产线证据的一条，先把产能和订单吃下来。", GOOD),
    ("试点", "无界智航先上一条线", "用一条线验 1000 件/时和翻面良率，验过再谈规模。", ACCENT),
    ("备选", "智元保持跟进，不排他", "等它给出连续运行数据再谈条件，现在不预付。", OKC),
    ("储备", "自研 Z100Fd 只做积累", "专心采数据、打成功率，不进对外报价和交付承诺。", MUTED),
]
for i, (tag, head, body, col) in enumerate(adv):
    y = 2.32 + i * 1.10
    rect(s, M, y, 1.05, 0.86, fill=col, radius=True)
    text(s, M, y + 0.02, 1.05, 0.82, tag, 11, WHITE, True,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, M + 1.28, y + 0.06, 4.30, 0.42, head, 13.5, INK, True)
    text(s, M + 5.75, y + 0.10, CW - 5.95, 0.70, body, 11, MUTED, line_sp=1.32)
footer(s, "建议 · 每条都配了「做到什么才算数」")

# ── P12 风险 ──────────────────────────────────────────────────────────
s = page(prs, "风险",
         "四个最容易出事的点，每个配一条能查的判据",
         "判据写不出来，就说明这个风险还没被真正管住。")
rows = [
    ["风险", "具体表现", "判据（做到才算过关）"],
    ["1000 件/时是承诺不是实测", "上机后节拍掉到目标以下", "连续 8 小时实测节拍达标"],
    ["翻面只在方案里", "翻面后抓空、翻面良率低", "翻面良率 ≥ 目标值"],
    ["演示 ≠ 能连续跑", "抓着抓着就漏、要人工干预", "连续 8 小时无人工干预"],
    ["自研成功率不足", "插到一半卡住、压不进", "连续 500 次插拔成功率达标"],
]
table(s, M, 2.45, CW, rows, [3.55, 4.20, 4.60],
      head_h=0.42, row_h=0.72, size=10.5,
      colors=[OKC, OKC, OKC, RISK])
text(s, M, 6.35, CW, 0.42,
     "四条判据都写在验收里，任何一条没过，就不进入下一阶段。", 11, MUTED)
footer(s, "风险 · 每条风险都有对应的验收动作")

# ── P13 收尾 ──────────────────────────────────────────────────────────
s = prs.slides.add_slide(prs.slide_layouts[6])
rect(s, 0, 0, W, H, fill="111827")
text(s, 1.0, 2.20, 11.0, 0.40, "收尾", 12, "93C5FD", True)
text(s, 1.0, 2.70, 11.2, 2.0,
     "先用能交货的赚钱，\n再用要验证的换空间，\n最后给还没成熟的留位置。",
     28, WHITE, True, line_sp=1.35)
rect(s, 1.02, 5.30, 1.5, 0.05, fill=ACCENT)
text(s, 1.0, 5.60, 11.2, 0.9,
     "他山、康视 在交货  ·  无界智航 在验证  ·  智元 在看  ·  自研 在积累",
     13, "9CA3AF", line_sp=1.5)

prs.save(OUT)
print("输出:", OUT)
print("页数:", len(prs.slides.__iter__.__self__._sldIdLst))
