#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_deck3.py — 《Z-MAX 项目进展》精简版 (8 页)

两个项目线：插拔 Z700Fs（他山 → 康视杰）、摆盘（无界智航 / 智元）；加自研 Z100Fd。
python3 make_deck3.py
"""
from __future__ import annotations

import os
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "Z-MAX项目进展_5.50.D-P3_20261110.pptx")

W, H = 13.333, 7.5
M = 0.85
CW = W - 2 * M
FOOT_Y = 6.98

INK, MUTED, LINE, SOFT = "1F2937", "6B7280", "E5E7EB", "F8FAFC"
GOOD, OKC, RISK, ACCENT, WHITE = "059669", "D97706", "DC2626", "1D4ED8", "FFFFFF"
EA = "微软雅黑"


def _font(run, size, bold=False, color=INK):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = "Arial"
    f.color.rgb = RGBColor.from_string(color)
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", EA)


def text(s, x, y, w, h, lines, size=13, color=INK, bold=False,
         align=PP_ALIGN.LEFT, space=6, anchor=MSO_ANCHOR.TOP, line_sp=1.2):
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
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


def rect(s, x, y, w, h, fill=SOFT, line=None, radius=False):
    sh = s.shapes.add_shape(5 if radius else 1, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor.from_string(fill)
    if line:
        sh.line.color.rgb = RGBColor.from_string(line)
        sh.line.width = Pt(0.75)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    sh.text_frame.text = ""
    return sh


def page(prs, title, sub=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    text(s, M, 0.62, CW, 0.62, title, 25, INK, True, line_sp=1.05)
    if sub:
        text(s, M, 1.34, CW, 0.42, sub, 12.5, MUTED, line_sp=1.2)
    return s


def footer(s, note):
    rect(s, M, FOOT_Y - 0.10, CW, 0.008, fill=LINE)
    text(s, M, FOOT_Y, CW * 0.7, 0.26, note, 9, MUTED)
    text(s, W - M - 2.2, FOOT_Y, 2.2, 0.26, "2026-11-10", 9, MUTED, align=PP_ALIGN.RIGHT)


prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)

# ── P1 封面 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(prs.slide_layouts[6])
rect(s, 0, 0, W, H, fill="111827")
rect(s, 0, 0, 0.10, H, fill=ACCENT)
text(s, 1.05, 2.35, 10.0, 0.40, "Z-MAX  ·  项目进展", 13, "93C5FD", True)
text(s, 1.05, 2.85, 11.0, 1.6, "两个项目线，四家供应商，\n各自走到哪一步",
     32, WHITE, True, line_sp=1.3)
rect(s, 1.07, 4.72, 1.5, 0.05, fill=ACCENT)
text(s, 1.05, 5.02, 11.0, 0.9, ["插拔 Z700Fs（他山 · 康视杰）   摆盘（无界智航 · 智元）   自研 Z100Fd"],
     12.5, "9CA3AF", line_sp=1.5)
text(s, 1.05, 6.55, 6.0, 0.3, "2026-11-10", 11, "6B7280")

# ── P2 一页看懂 ───────────────────────────────────────────────────────
s = page(prs, "一页看懂", "不评价先进，只说现在在哪。")
rows = [
    ("插拔 Z700Fs", "他山", "固定轨迹 + 示教", "实验室阶段，未上产线", RISK),
    ("插拔 Z700Fs", "康视杰", "视觉伺服 + AOI", "刚部署，测试中", OKC),
    ("摆盘", "无界智航", "吸盘，可翻面", "方案与报价已给，未上机", OKC),
    ("摆盘", "智元", "夹爪", "有演示视频，无产线数据", RISK),
    ("插拔（自研）", "Z100Fd", "7 kg 协作臂", "本体完成，成功率不足", RISK),
]
y0 = 2.10
for i, (proj, vendor, how, state, col) in enumerate(rows):
    y = y0 + i * 0.90
    rect(s, M, y, CW, 0.78, fill=SOFT if i % 2 == 0 else WHITE, line=LINE, radius=True)
    rect(s, M, y, 0.045, 0.78, fill=col)
    text(s, M + 0.30, y + 0.20, 2.30, 0.38, proj, 12, MUTED, True)
    text(s, M + 2.62, y + 0.19, 1.75, 0.40, vendor, 14, INK, True)
    text(s, M + 4.50, y + 0.22, 3.15, 0.36, how, 11.5, MUTED)
    text(s, M + 7.75, y + 0.20, CW - 7.95, 0.38, state, 12, col, True)
footer(s, "一页看懂 · 五行全部为当前状态")

# ── P3 插拔 Z700Fs ────────────────────────────────────────────────────
s = page(prs, "插拔项目 Z700Fs", "两代方案：先解决「能做」，再解决「换型」")
cards = [
    ("一代", "他山", "固定轨迹 + 示教", RISK, [
        "人工示教一遍，机器照着走",
        "**还在实验室，未上产线**",
        "问题：换型就要重新示教",
        "换一次料，等于重做一遍",
    ]),
    ("二代", "康视杰", "视觉伺服 + AOI", OKC, [
        "到大致位置后自己找目标",
        "**刚部署，正在测试**",
        "换型不用重新示教",
        "AOI 同步做在线检测",
    ]),
]
bw = (CW - 0.55) / 2
for i, (gen, vendor, how, col, items) in enumerate(cards):
    x = M + i * (bw + 0.55)
    rect(s, x, 2.05, bw, 3.55, fill=WHITE, line=LINE, radius=True)
    rect(s, x, 2.05, bw, 0.06, fill=col)
    text(s, x + 0.35, 2.30, bw - 0.7, 0.28, gen, 10.5, col, True)
    text(s, x + 0.35, 2.62, bw - 0.7, 0.48, vendor, 20, INK, True)
    text(s, x + 0.35, 3.16, bw - 0.7, 0.32, how, 11.5, MUTED)
    text(s, x + 0.35, 3.66, bw - 0.72, 1.75, ["· " + it for it in items],
         11.5, INK, line_sp=1.55)
footer(s, "插拔 Z700Fs · 二代正在替代一代，一代的示教负担是换型瓶颈")

# ── P4 摆盘 ───────────────────────────────────────────────────────────
s = page(prs, "摆盘项目", "两家：一家给了数字，一家给了视频")
cards = [
    ("无界智航", "吸盘 · 可翻面", OKC, [
        "**1000 件/时**（书面承诺）",
        "基础型 / 精细型 / 专家型三档报价",
        "带散热片的件，给「扩展包」方案",
        "未上机，节拍待实测",
    ]),
    ("智元", "夹爪", RISK, [
        "有夹爪抓取演示视频",
        "末端接近人手，适合异形件",
        "**无节拍、无良率、无连续数据**",
        "暂按备选跟进",
    ]),
]
for i, (vendor, how, col, items) in enumerate(cards):
    x = M + i * (bw + 0.55)
    rect(s, x, 2.05, bw, 3.55, fill=WHITE, line=LINE, radius=True)
    rect(s, x, 2.05, bw, 0.06, fill=col)
    text(s, x + 0.35, 2.32, bw - 0.7, 0.50, vendor, 20, INK, True)
    text(s, x + 0.35, 2.90, bw - 0.7, 0.32, how, 11.5, MUTED)
    text(s, x + 0.35, 3.40, bw - 0.72, 2.00, ["· " + it for it in items],
         11.5, INK, line_sp=1.55)
footer(s, "摆盘 · 承诺写在纸上，节拍要跑出来才算")

# ── P5 自研 Z100Fd ────────────────────────────────────────────────────
s = page(prs, "自研 Z100Fd", "硬件走完了，软件还在打成功率")
rows = [
    ("本体", "已完成", "7 kg 协作臂，装好、上电、能按指令动", GOOD),
    ("数据采集", "进行中", "正在收集抓取与插拔过程数据", OKC),
    ("动作训练", "进行中", "反复迭代，指标还不稳定", OKC),
    ("可用性", "未达标", "成功率不足以支撑正常光模块插拔", RISK),
]
for i, (k, v, note, col) in enumerate(rows):
    y = 2.10 + i * 0.86
    rect(s, M, y, CW, 0.74, fill=SOFT if i % 2 == 0 else WHITE, line=LINE, radius=True)
    text(s, M + 0.32, y + 0.19, 1.60, 0.36, k, 12.5, INK, True)
    text(s, M + 2.00, y + 0.19, 1.55, 0.36, v, 12, col, True)
    text(s, M + 3.75, y + 0.21, CW - 3.95, 0.36, note, 11, MUTED)

rect(s, M, 5.72, CW, 0.92, fill="FEF2F2", radius=True)
text(s, M + 0.32, 5.90, CW - 0.65, 0.60,
     "**结论**：只做数据与动作积累，不写交付承诺、不对外报价。", 12.5, INK)
footer(s, "自研 Z100Fd · 技术储备，不进交付")

# ── P6 建议 ───────────────────────────────────────────────────────────
s = page(prs, "建议", "按「现在能不能兑现」排序，不按听起来多先进")
adv = [
    ("一", "插拔先押康视杰", "二代解决换型问题，测完就顶上一代。", GOOD),
    ("二", "摆盘先验无界智航", "一条线跑通 1000 件/时和翻面，再谈规模。", ACCENT),
    ("三", "智元保持跟进", "等连续运行数据，不预付、不排他。", OKC),
    ("四", "自研只做积累", "专心打成功率，时机成熟再进交付。", MUTED),
]
for i, (num, head, body, col) in enumerate(adv):
    y = 2.15 + i * 1.08
    text(s, M, y + 0.02, 0.55, 0.55, num, 19, col, True)
    text(s, M + 0.70, y, 4.30, 0.42, head, 14, INK, True)
    text(s, M + 5.20, y + 0.06, CW - 5.40, 0.40, body, 11.5, MUTED)
    rect(s, M, y + 0.76, CW, 0.008, fill=LINE)
footer(s, "建议 · 四条互不冲突，可同时推进")

# ── P7 风险 ───────────────────────────────────────────────────────────
s = page(prs, "风险", "每个风险配一条能查的判据")
risks = [
    ("他山换型示教", "换一次料要重做一遍，人工成本随品类线性上升", "换型时间 ≤ 目标值"),
    ("康视杰未测完", "刚部署，稳定性还没跑够", "连续 8 小时无异常"),
    ("无界智航 1000 件/时是承诺", "上机后可能达不到", "连续 8 小时实测达标"),
    ("智元只有演示", "演示 ≠ 能连续跑", "连续 8 小时无人工干预"),
]
for i, (r, sym, judge) in enumerate(risks):
    y = 2.05 + i * 1.12
    rect(s, M, y, CW, 0.96, fill=SOFT if i % 2 == 0 else WHITE, line=LINE, radius=True)
    text(s, M + 0.30, y + 0.14, 3.85, 0.36, r, 12, INK, True)
    text(s, M + 0.30, y + 0.52, 5.60, 0.34, sym, 10.5, MUTED)
    text(s, M + 6.40, y + 0.30, CW - 6.60, 0.40, "判据：" + judge, 11, ACCENT, True)
footer(s, "风险 · 判据写不出来，就说明风险还没被管住")

# ── P8 收尾 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(prs.slide_layouts[6])
rect(s, 0, 0, W, H, fill="111827")
text(s, 1.05, 2.55, 10.0, 0.40, "一句话", 12, "93C5FD", True)
text(s, 1.05, 3.05, 11.2, 1.6, "插拔看二代，摆盘看实测，\n自研先别着急对外承诺。",
     28, WHITE, True, line_sp=1.35)
rect(s, 1.07, 5.05, 1.5, 0.05, fill=ACCENT)
text(s, 1.05, 5.35, 11.0, 0.5, "他山（实验室） · 康视杰（测试中） · 无界智航（待上机） · 智元（演示） · Z100Fd（积累）",
     12, "9CA3AF", line_sp=1.4)

prs.save(OUT)
print("输出:", OUT)
print("页数:", len(prs.slides._sldIdLst))
