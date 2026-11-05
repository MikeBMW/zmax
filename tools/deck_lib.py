#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎨 技术白皮书 PPT 渲染器 (16:9, 深色工程风) — 供 build_tech_deck.py 调用

设计目标 (老倪界面偏好): 字少不挤不截断 / 一页一个技术点 / 数字可复核 / 页脚可查出处。
"""
from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

FONT = "Microsoft YaHei"
MONO = "Consolas"

BG = RGBColor(0x0B, 0x12, 0x20)
PANEL = RGBColor(0x13, 0x1F, 0x33)
PANEL2 = RGBColor(0x18, 0x27, 0x3E)
TEXT = RGBColor(0xE8, 0xF1, 0xFF)
MUTED = RGBColor(0x93, 0xA9, 0xC9)
ACCENT = RGBColor(0x22, 0xD3, 0xEE)
ACCENT2 = RGBColor(0xF5, 0x9E, 0x0B)
GOOD = RGBColor(0x34, 0xD3, 0x99)
BAD = RGBColor(0xF8, 0x71, 0x71)
LINE = RGBColor(0x27, 0x3B, 0x59)

W, H = Inches(13.333), Inches(7.5)


def new_deck() -> Presentation:
    pr = Presentation()
    pr.slide_width = W
    pr.slide_height = H
    return pr


def _blank(pr: Presentation):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, H)
    bg.fill.solid(); bg.fill.fore_color.rgb = BG
    bg.line.fill.background()
    bg.shadow.inherit = False
    return s


def _tb(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    return tb, tf


def _p(tf, text, size=15, color=TEXT, bold=False, font=FONT, space_after=6, first=False,
       align=PP_ALIGN.LEFT, line_spacing=None):
    para = tf.paragraphs[0] if first else tf.add_paragraph()
    para.alignment = align
    para.space_after = Pt(space_after)
    if line_spacing:
        para.line_spacing = line_spacing
    run = para.add_run()
    run.text = text
    run.font.size = Pt(size); run.font.bold = bold; run.font.name = font
    run.font.color.rgb = color
    return para


def _rect(slide, x, y, w, h, fill=PANEL, line=None, radius=None):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid(); shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line; shape.line.width = Pt(1)
    shape.shadow.inherit = False
    if radius:
        try:
            shape.adjustments[0] = radius
        except Exception:                                            # noqa: BLE001
            pass
    return shape


def _header(slide, chapter: str, title: str, sub: str = ""):
    if chapter:
        _p(_tb(slide, Inches(0.75), Inches(0.42), Inches(6.0), Inches(0.3))[1],
           chapter, 11, ACCENT, True, space_after=0, first=True)
    tb, tf = _tb(slide, Inches(0.75), Inches(0.72), Inches(11.9), Inches(0.9))
    _p(tf, title, 27, TEXT, True, space_after=0, first=True)
    if sub:
        _p(_tb(slide, Inches(0.75), Inches(1.5), Inches(11.6), Inches(0.45))[1],
           sub, 13.5, MUTED, space_after=0, first=True)
    ln = slide.shapes.add_connector(1, Inches(0.75), Inches(1.95) if sub else Inches(1.62),
                                    Inches(12.58), Inches(1.95) if sub else Inches(1.62))
    ln.line.color.rgb = LINE; ln.line.width = Pt(1)


def _footer(slide, idx: int, deck: str):
    _p(_tb(slide, Inches(0.75), Inches(6.95), Inches(8.0), Inches(0.3))[1],
       deck, 9.5, MUTED, space_after=0, first=True)
    _p(_tb(slide, Inches(11.9), Inches(6.95), Inches(0.9), Inches(0.3))[1],
       f"{idx:03d}", 10, MUTED, space_after=0, first=True, align=PP_ALIGN.RIGHT)


# ────────────────────────────── slide kinds ──────────────────────────────

def cover(pr, title, sub, meta_lines):
    s = _blank(pr)
    bar = _rect(s, 0, 0, Inches(0.16), H, ACCENT)
    bar.line.fill.background()
    tb, tf = _tb(s, Inches(1.1), Inches(2.05), Inches(10.8), Inches(1.6))
    _p(tf, title, 42, TEXT, True, space_after=10, first=True)
    _p(tf, sub, 20, ACCENT, space_after=0)
    ln = s.shapes.add_connector(1, Inches(1.1), Inches(4.15), Inches(7.4), Inches(4.15))
    ln.line.color.rgb = ACCENT; ln.line.width = Pt(2)
    tb2, tf2 = _tb(s, Inches(1.1), Inches(4.5), Inches(10.4), Inches(1.8))
    for i, line in enumerate(meta_lines):
        _p(tf2, line, 13, MUTED, space_after=7, first=(i == 0))
    return s


def section(pr, num, title, desc, bullets=None):
    s = _blank(pr)
    _rect(s, 0, 0, Inches(0.16), H, ACCENT2).line.fill.background()
    _ns = f"{num:02d}" if float(num).is_integer() else f"{float(num):.2f}"
    _p(_tb(s, Inches(1.0), Inches(1.55), Inches(3.0), Inches(1.0))[1],
       _ns, 66, ACCENT2, True, space_after=0, first=True)
    _p(_tb(s, Inches(1.0), Inches(2.9), Inches(10.6), Inches(1.2))[1],
       title, 34, TEXT, True, space_after=0, first=True)
    _p(_tb(s, Inches(1.05), Inches(3.95), Inches(9.6), Inches(0.9))[1],
       desc, 14, MUTED, space_after=0, first=True)
    if bullets:
        tb, tf = _tb(s, Inches(1.05), Inches(4.72), Inches(10.6), Inches(2.0))
        for i, b in enumerate(bullets):
            _p(tf, "· " + b, 11.5, TEXT, space_after=3, first=(i == 0))
    return s


def bullets(pr, idx, deck, chapter, title, items, sub="", note="", size=15):
    s = _blank(pr)
    _header(s, chapter, title, sub)
    tb, tf = _tb(s, Inches(0.8), Inches(2.22), Inches(11.8), Inches(4.4))
    first = True
    for it in items:
        if isinstance(it, tuple):
            lead, rest = it
            para = tf.paragraphs[0] if first else tf.add_paragraph()
            para.space_after = Pt(9)
            r = para.add_run(); r.text = "▪ "
            r.font.size = Pt(size); r.font.color.rgb = ACCENT; r.font.name = FONT
            r2 = para.add_run(); r2.text = lead + "  "
            r2.font.size = Pt(size); r2.font.bold = True; r2.font.name = FONT
            r2.font.color.rgb = TEXT
            r3 = para.add_run(); r3.text = rest
            r3.font.size = Pt(size); r3.font.name = FONT; r3.font.color.rgb = TEXT
        else:
            _p(tf, "▪ " + str(it), size, TEXT, space_after=9, first=first)
        first = False
    if note:
        _rect(s, Inches(0.8), Inches(6.3), Inches(11.8), Inches(0.46), PANEL2)
        _p(_tb(s, Inches(0.98), Inches(6.4), Inches(11.4), Inches(0.3))[1],
           note, 11, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def formula(pr, idx, deck, chapter, title, lines, sub="", note=""):
    s = _blank(pr)
    _header(s, chapter, title, sub)
    _rect(s, Inches(0.8), Inches(2.2), Inches(11.8), Inches(3.85), PANEL)
    tb, tf = _tb(s, Inches(1.15), Inches(2.55), Inches(11.1), Inches(3.2))
    for i, ln in enumerate(lines):
        _p(tf, ln, 16, ACCENT if i == 0 else TEXT, i == 0, font=MONO, space_after=12, first=(i == 0))
    if note:
        _p(_tb(s, Inches(1.15), Inches(6.25), Inches(11.2), Inches(0.5))[1],
           note, 11.5, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def table(pr, idx, deck, chapter, title, headers, rows, sub="", note="", col_w=None, size=12):
    s = _blank(pr)
    _header(s, chapter, title, sub)
    n_r, n_c = len(rows) + 1, len(headers)
    top = Inches(2.22)
    if n_r > 12:                       # 行多 → 缩字号并压高度, 给页脚注留位
        size = min(size, 9.5)
    height = min(Inches(3.85), Inches(0.38) * n_r + Inches(0.1))
    shape = s.shapes.add_table(n_r, n_c, Inches(0.8), top, Inches(11.8), height)
    tbl = shape.table
    if col_w:
        total = sum(col_w)
        for i, cw in enumerate(col_w):
            tbl.columns[i].width = Emu(int(Inches(11.8) * cw / total))
    for j, h in enumerate(headers):
        cell = tbl.cell(0, j)
        cell.text = ""
        cell.fill.solid(); cell.fill.fore_color.rgb = PANEL2
        p = cell.text_frame.paragraphs[0]
        r = p.add_run(); r.text = h
        r.font.size = Pt(size + 0.5); r.font.bold = True; r.font.name = FONT
        r.font.color.rgb = ACCENT
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = PANEL if i % 2 else RGBColor(0x10, 0x1A, 0x2B)
            p = cell.text_frame.paragraphs[0]
            r = p.add_run(); r.text = str(val)
            r.font.size = Pt(size); r.font.name = FONT
            r.font.color.rgb = TEXT
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    if note:
        _p(_tb(s, Inches(0.8), Inches(6.55), Inches(11.8), Inches(0.4))[1],
           note, 10, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def timeline(pr, idx, deck, chapter, title, events, sub="", note=""):
    """events: [(year, label, desc)] 最多 6 个"""
    s = _blank(pr)
    _header(s, chapter, title, sub)
    y = Inches(3.5)
    ln = s.shapes.add_connector(1, Inches(0.95), y, Inches(12.35), y)
    ln.line.color.rgb = LINE; ln.line.width = Pt(2)
    n = len(events)
    span = Inches(11.4) / max(1, n - 1) if n > 1 else Inches(0)
    for i, (year, label, desc) in enumerate(events):
        x = Inches(0.95) + Emu(int(span * i))
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, x - Inches(0.075), y - Inches(0.075),
                                 Inches(0.15), Inches(0.15))
        dot.fill.solid(); dot.fill.fore_color.rgb = ACCENT; dot.line.fill.background()
        _p(_tb(s, x - Inches(0.55), y - Inches(0.72), Inches(1.4), Inches(0.34))[1],
           year, 14, ACCENT, True, space_after=0, first=True, align=PP_ALIGN.CENTER)
        _p(_tb(s, x - Inches(0.78), y + Inches(0.22), Inches(1.7), Inches(0.4))[1],
           label, 11.5, TEXT, True, space_after=0, first=True, align=PP_ALIGN.CENTER)
        _p(_tb(s, x - Inches(0.82), y + Inches(0.72), Inches(1.75), Inches(1.4))[1],
           desc, 10, MUTED, space_after=0, first=True, align=PP_ALIGN.CENTER)
    if note:
        _p(_tb(s, Inches(0.8), Inches(6.3), Inches(11.8), Inches(0.5))[1],
           note, 11, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def layers(pr, idx, deck, chapter, title, rows, sub="", note=""):
    """rows: [(层名, 职责, 关键实现/证据)] 从上到下"""
    s = _blank(pr)
    _header(s, chapter, title, sub)
    top = Inches(2.18)
    hh = Inches(0.78) / max(1, len(rows)) * 4.2
    for i, (name, duty, ev) in enumerate(rows):
        y = top + Emu(int(hh * i))
        fill = PANEL if i % 2 == 0 else PANEL2
        _rect(s, Inches(0.8), y, Inches(2.35), hh - Inches(0.09), PANEL2, ACCENT if i == 0 else None)
        _p(_tb(s, Inches(0.95), y + Inches(0.08), Inches(2.1), hh - Inches(0.2))[1],
           name, 13, ACCENT, True, space_after=0, first=True)
        _rect(s, Inches(3.25), y, Inches(4.6), hh - Inches(0.09), fill)
        _p(_tb(s, Inches(3.42), y + Inches(0.08), Inches(4.3), hh - Inches(0.2))[1],
           duty, 11.5, TEXT, space_after=0, first=True)
        _rect(s, Inches(7.95), y, Inches(4.6), hh - Inches(0.09), fill)
        _p(_tb(s, Inches(8.12), y + Inches(0.08), Inches(4.3), hh - Inches(0.2))[1],
           ev, 10.5, MUTED, space_after=0, first=True)
    if note:
        _p(_tb(s, Inches(0.8), Inches(6.42), Inches(11.8), Inches(0.4))[1],
           note, 11, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def cards(pr, idx, deck, chapter, title, items, sub="", note="", cols=2):
    """items: [(标题, 正文)]"""
    s = _blank(pr)
    _header(s, chapter, title, sub)
    rows = (len(items) + cols - 1) // cols
    cw = Inches(11.8) / cols
    ch = Inches(3.9) / max(1, rows)
    for i, (t, body) in enumerate(items):
        r, c = i // cols, i % cols
        x = Inches(0.8) + Emu(int(cw * c))
        y = Inches(2.2) + Emu(int(ch * r))
        _rect(s, x, y, cw - Inches(0.18), ch - Inches(0.16), PANEL)
        _p(_tb(s, x + Inches(0.22), y + Inches(0.16), cw - Inches(0.6), Inches(0.35))[1],
           t, 13.5, ACCENT, True, space_after=0, first=True)
        _p(_tb(s, x + Inches(0.22), y + Inches(0.58), cw - Inches(0.6), ch - Inches(0.8))[1],
           body, 11.5, TEXT, space_after=0, first=True)
    if note:
        _p(_tb(s, Inches(0.8), Inches(6.4), Inches(11.8), Inches(0.4))[1],
           note, 11, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def bigstat(pr, idx, deck, chapter, title, stats, sub="", note=""):
    """stats: [(数值, 说明)] 3-4 个"""
    s = _blank(pr)
    _header(s, chapter, title, sub)
    n = len(stats)
    cw = Inches(11.8) / n
    _mx = max(len(str(s[0])) for s in stats)
    _vs = 40 if _mx <= 5 else (32 if _mx <= 7 else 26)
    for i, (val, label) in enumerate(stats):
        x = Inches(0.8) + Emu(int(cw * i))
        _rect(s, x, Inches(2.5), cw - Inches(0.25), Inches(2.4), PANEL)
        _p(_tb(s, x + Inches(0.2), Inches(2.75), cw - Inches(0.65), Inches(0.9))[1],
           val, _vs, ACCENT, True, space_after=0, first=True, align=PP_ALIGN.CENTER)
        _p(_tb(s, x + Inches(0.3), Inches(3.85), cw - Inches(0.85), Inches(0.8))[1],
           label, 12, TEXT, space_after=0, first=True, align=PP_ALIGN.CENTER)
    if note:
        _p(_tb(s, Inches(0.8), Inches(5.35), Inches(11.8), Inches(1.1))[1],
           note, 12, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def quote(pr, idx, deck, chapter, text, source, title=""):
    s = _blank(pr)
    if title:
        _p(_tb(s, Inches(0.85), Inches(1.0), Inches(11.6), Inches(0.5))[1],
           title, 13, ACCENT, True, space_after=0, first=True)
    _rect(s, Inches(0.85), Inches(2.1), Inches(0.09), Inches(2.4), ACCENT)
    _p(_tb(s, Inches(1.3), Inches(2.15), Inches(10.9), Inches(2.4))[1],
       text, 22, TEXT, True, space_after=0, first=True)
    _p(_tb(s, Inches(1.32), Inches(4.85), Inches(10.8), Inches(0.6))[1],
       source, 12, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def figures(pr, idx, deck, chapter, title, items, sub="", note="", cols=2, cap_h=0.45):
    """items: [(图片路径, 图注)] — 等比缩放适配格子, 不拉伸"""
    from pptx.util import Inches as _In
    s = _blank(pr)
    _header(s, chapter, title, sub)
    n = len(items)
    cols = min(cols, n) if n else 1
    rows = (n + cols - 1) // cols
    top = _In(2.15)
    avail_h = int((_In(6.25) - top) / max(1, rows))
    cw = _In(11.8) / cols
    box_h = avail_h - int(_In(cap_h + 0.10))
    for i, (path, cap) in enumerate(items):
        r, c = i // cols, i % cols
        x = _In(0.8) + int(cw * c)
        y = top + avail_h * r
        try:
            pic = s.shapes.add_picture(str(path), int(x + _In(0.12)), int(y), width=int(cw - _In(0.4)))
        except Exception:                                                # noqa: BLE001
            _p(_tb(s, x, y, cw - _In(0.3), _In(0.4))[1], "[图缺失] " + str(path), 11, BAD, space_after=0, first=True)
            continue
        w, h = pic.width, pic.height
        if h > box_h:                       # 太高 → 按高度回缩并居中
            ratio = box_h / h
            pic.width = int(w * ratio)
            pic.height = box_h
        if pic.width > cw - _In(0.3):       # 太宽 → 按宽度回缩
            ratio = (cw - _In(0.3)) / pic.width
            pic.width = int(pic.width * ratio)
            pic.height = int(pic.height * ratio)
        pic.left = int(x + (cw - pic.width) / 2)
        pic.top = int(y)
        _p(_tb(s, x + _In(0.12), int(y + box_h) + _In(0.06), cw - _In(0.4), _In(cap_h))[1],
           cap, 10.5, MUTED, space_after=0, first=True, align=PP_ALIGN.CENTER)
    if note:
        _p(_tb(s, _In(0.8), _In(6.35), _In(11.8), _In(0.5))[1], note, 10.5, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def funcmap(pr, idx, deck, chapter, title, rows, left_title="输入", left_items=(),
            right_title="输出", right_items=(), sub="", note=""):
    """功能框图: 左输入柱 → 中分层块 → 右输出柱; rows=[(层名, 关键节点, 节点数, 入/出)]"""
    s = _blank(pr)
    _header(s, chapter, title, sub)
    lx, mx, rx = Inches(0.8), Inches(3.5), Inches(10.55)
    lw, mw, rw = Inches(2.3), Inches(6.7), Inches(2.1)
    # 左柱
    _rect(s, lx, Inches(2.2), lw, Inches(0.4), PANEL2)
    _p(_tb(s, lx + Inches(0.12), Inches(2.27), lw - Inches(0.2), Inches(0.3))[1],
       left_title, 12, ACCENT, True, space_after=0, first=True)
    # 右柱
    _rect(s, rx, Inches(2.2), rw, Inches(0.4), PANEL2)
    _p(_tb(s, rx + Inches(0.12), Inches(2.27), rw - Inches(0.2), Inches(0.3))[1],
       right_title, 12, ACCENT2, True, space_after=0, first=True)
    # 中列分层
    top = Inches(2.55)
    bh = Inches(0.60)
    gap = Inches(0.10)
    for i, (name, nodes, cnt, io) in enumerate(rows):
        y = top + int((bh + gap) * i)
        _rect(s, mx, y, mw, bh, PANEL, ACCENT if i == 0 else LINE)
        _p(_tb(s, mx + Inches(0.15), y + Inches(0.06), Inches(1.5), Inches(0.3))[1],
           name, 12.5, ACCENT, True, space_after=0, first=True)
        _p(_tb(s, mx + Inches(0.15), y + Inches(0.36), mw - Inches(0.3), Inches(0.28))[1],
           f"{nodes}　｜　{cnt} 个节点　｜　{io}", 10, MUTED, space_after=0, first=True)
        if i < len(rows) - 1:
            ar = s.shapes.add_connector(1, mx + Inches(1.0), y + bh, mx + Inches(1.0), y + bh + gap)
            ar.line.color.rgb = ACCENT; ar.line.width = Pt(1.2)
    # 左柱条目
    tb, tf = _tb(s, lx, Inches(2.75), lw - Inches(0.15), Inches(3.4))
    for i, it in enumerate(left_items):
        _p(tf, "· " + it, 10.5, TEXT, space_after=5, first=(i == 0))
    tb2, tf2 = _tb(s, rx, Inches(2.75), rw - Inches(0.15), Inches(3.4))
    for i, it in enumerate(right_items):
        _p(tf2, "· " + it, 10.5, TEXT, space_after=5, first=(i == 0))
    if note:
        _p(_tb(s, Inches(0.8), Inches(6.42), Inches(11.8), Inches(0.5))[1],
           note, 10.5, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s


def nodeblock(pr, idx, deck, chapter, title, name, ins, outs, desc="", tick="", code="", sub=""):
    """单个功能的方框图: 左输入 chips → 中间功能块 → 右输出 chips"""
    s = _blank(pr)
    _sub = (sub or desc)[:40]
    _header(s, chapter, title, _sub + ("…" if len(sub or desc) > 40 else ""))
    cx, cy, cw, chh = Inches(4.95), Inches(3.95), Inches(3.4), Inches(1.05)
    chip_h, chip_gap, maxn = Inches(0.34), Inches(0.06), 8
    # 中间功能块
    _rect(s, cx, cy, cw, chh, PANEL2, ACCENT)
    _p(_tb(s, cx + Inches(0.12), cy + Inches(0.16), cw - Inches(0.24), Inches(0.5))[1],
       name, 14, ACCENT, True, space_after=0, first=True, align=PP_ALIGN.CENTER)
    _p(_tb(s, cx + Inches(0.12), cy + Inches(0.62), cw - Inches(0.24), Inches(0.4))[1],
       f"输入 {len(ins)} 条 · 输出 {len(outs)} 条", 10, MUTED, space_after=0, first=True,
       align=PP_ALIGN.CENTER)
    # 左侧输入
    lx, lw = Inches(0.8), Inches(3.35)
    shown_in = ins[:maxn]
    for j, e in enumerate(shown_in):
        y = cy - Inches(0.35) + int((chip_h + chip_gap) * j) - int((chip_h + chip_gap) * (len(shown_in) - 1) / 2)
        _rect(s, lx, y, lw, chip_h, PANEL, LINE)
        _p(_tb(s, lx + Inches(0.1), y + Inches(0.03), lw - Inches(0.2), Inches(0.2))[1],
           (e.get("peer") or "")[:14], 8.5, TEXT, False, space_after=0, first=True)
        _p(_tb(s, lx + Inches(0.1), y + Inches(0.19), lw - Inches(0.2), Inches(0.18))[1],
           (e.get("sig") or "")[:30], 7.0, MUTED, space_after=0, first=True)
        ln = s.shapes.add_connector(1, lx + lw, y + int(chip_h / 2), cx, cy + int(chh / 2))
        ln.line.color.rgb = LINE; ln.line.width = Pt(1)
    if len(ins) > maxn:
        _p(_tb(s, lx, cy + Inches(1.6), lw, Inches(0.3))[1], f"…另有 {len(ins) - maxn} 条输入未展开", 8, MUTED, space_after=0, first=True)
    # 右侧输出
    rx, rw = Inches(9.15), Inches(3.4)
    shown_out = outs[:maxn]
    for j, e in enumerate(shown_out):
        y = cy - Inches(0.35) + int((chip_h + chip_gap) * j) - int((chip_h + chip_gap) * (len(shown_out) - 1) / 2)
        _rect(s, rx, y, rw, chip_h, PANEL, LINE)
        _p(_tb(s, rx + Inches(0.1), y + Inches(0.03), rw - Inches(0.2), Inches(0.2))[1],
           (e.get("peer") or "")[:14], 8.5, TEXT, False, space_after=0, first=True)
        _p(_tb(s, rx + Inches(0.1), y + Inches(0.19), rw - Inches(0.2), Inches(0.18))[1],
           (e.get("sig") or "")[:30], 7.0, MUTED, space_after=0, first=True)
        ln = s.shapes.add_connector(1, cx + cw, cy + int(chh / 2), rx, y + int(chip_h / 2))
        ln.line.color.rgb = LINE; ln.line.width = Pt(1)
    if len(outs) > maxn:
        _p(_tb(s, rx, cy + Inches(1.6), rw, Inches(0.3))[1], f"…另有 {len(outs) - maxn} 条输出未展开", 8, MUTED, space_after=0, first=True)
    # 图例
    _p(_tb(s, Inches(0.8), Inches(1.88), Inches(3.2), Inches(0.25))[1], "输入 · 上游给", 9, ACCENT, True, space_after=0, first=True)
    _p(_tb(s, Inches(9.15), Inches(1.90), Inches(3.2), Inches(0.25))[1], "输出 · 下游收", 9, ACCENT2, True, space_after=0, first=True)
    # 底部两行
    if tick:
        _p(_tb(s, Inches(0.8), Inches(5.62), Inches(11.9), Inches(0.55))[1], tick[:150], 9.5, MUTED, space_after=0, first=True)
    if code:
        _p(_tb(s, Inches(0.8), Inches(6.12), Inches(11.9), Inches(0.55))[1], code[:170], 9, MUTED, space_after=0, first=True)
    _footer(s, idx, deck)
    return s
