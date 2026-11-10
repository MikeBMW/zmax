#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_deck.py — 生成《流形引擎 · 世界模型分层框架》PPT

数据在 deck_data.json（side-car），本脚本只管版式。
重新生成: python3 make_deck.py

口径: 每个数字都要能追溯到一次真实运行 —— 数学验证来自 tools/verify_manifold_math.py，
分层行为来自 hjepa_mr_layers._selftest，节点运行来自画布冒烟。
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
DATA = json.load(open(os.path.join(HERE, "deck_data.json"), encoding="utf-8"))
OUT = os.path.join(HERE, "流形引擎与世界模型分层框架_5.50.D-P1_20261110.pptx")

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
VIOLET = "7C3AED"
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
    shape = slide.shapes.add_shape(5 if radius else 1,
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
        text(s, M + 0.18, 0.50, 6.0, 0.34, tag, 11, ACCENT, True)
    text(s, M, 0.86, CW, 0.72, title, 24, INK, True, line_sp=1.0)
    if sub:
        text(s, M, 1.60, CW, 0.46, sub, 12.5, MUTED, line_sp=1.2)
    return s


def footer(s, note):
    rect(s, M, FOOT_Y - 0.10, CW, 0.008, fill=LINE)
    text(s, M, FOOT_Y, CW * 0.68, 0.26, note, 9, MUTED)
    text(s, W - M - 2.45, FOOT_Y, 2.45, 0.26,
         "5.50.D-P1 · 2026-11-10", 9, MUTED, align=PP_ALIGN.RIGHT)


def table(slide, x, y, w, rows, col_w, head_h=0.40, row_h=0.36, size=9.5,
          head_fill="1F2937", zebra=True, colors=None, bolds=None):
    n_r, n_c = len(rows), len(rows[0])
    shp = slide.shapes.add_table(n_r, n_c, Inches(x), Inches(y), Inches(w),
                                 Inches(head_h + row_h * (n_r - 1)))
    tbl = shp.table
    tbl.first_row = True
    for i, cw in enumerate(col_w):
        tbl.columns[i].width = Inches(cw)
    tbl.rows[0].height = Inches(head_h)
    for i in range(1, n_r):
        tbl.rows[i].height = Inches(row_h)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.07)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if ri == 0:
                cell.fill.fore_color.rgb = RGBColor.from_string(head_fill)
            elif zebra and ri % 2 == 0:
                cell.fill.fore_color.rgb = RGBColor.from_string(SOFT)
            else:
                cell.fill.fore_color.rgb = RGBColor.from_string(WHITE)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.line_spacing = 1.0
            r = p.add_run()
            r.text = str(val)
            col = WHITE if ri == 0 else INK
            bold = ri == 0
            if ri and colors and (ri, ci) in colors:
                col = colors[(ri, ci)]
            if ri and bolds and (ri, ci) in bolds:
                bold = True
            _font(r, size, bold, col)
    return shp


prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
META = DATA["meta"]

# ── P1 封面 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(prs.slide_layouts[6])
rect(s, 0, 0, W, H, fill="0F172A")
rect(s, 0, 0, 0.14, H, fill=VIOLET)
text(s, 1.15, 1.62, 9.6, 0.40, "Z-MAX · 天枢产品边界 · 专利与技术验证", 12.5, "A5B4FC", True)
text(s, 1.15, 2.10, 11.0, 1.5, META["title"], 38, WHITE, True, line_sp=1.05)
text(s, 1.15, 3.42, 10.4, 0.9, META["subtitle"], 15, "CBD5E1", line_sp=1.35)

for i, (t, c) in enumerate([("专利组合 · 12 件", "A5B4FC"), ("数学原理 · 群与流形", "86EFAC"),
                            ("实测验证 · 13 项断言", "FCD34D")]):
    x = 1.15 + i * 3.15
    rect(s, x, 4.52, 2.92, 0.56, fill="1E293B", line="334155", radius=True)
    text(s, x, 4.52, 2.92, 0.56, t, 12, c, True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

rect(s, 1.15, 5.52, 3.4, 0.03, fill=VIOLET)
text(s, 1.15, 5.74, 10.4, 0.9,
     ["版本 %s　　编制 %s" % (META["version"], META["date"]),
      "依据：%s" % META["source"]], 10, "94A3B8", line_sp=1.45)

# ── P2 一页结论 ───────────────────────────────────────────────────────
s = page(prs, "结论先行", "这套框架不是设想：数学能算、代码能跑、专利能对上",
         "三份证据各自独立 —— 数学证明它自洽，代码证明它可执行，专利证明它有边界。")
bw = (CW - 0.50) / 3
for i, h in enumerate(DATA["headline"]):
    x = M + i * (bw + 0.25)
    col = TONE[h["tone"]]
    rect(s, x, 2.24, bw, 2.54, fill=SOFT, line=LINE, radius=True)
    rect(s, x, 2.24, 0.055, 2.54, fill=col)
    text(s, x + 0.32, 2.46, bw - 0.6, 0.70, h["big"], 34, col, True, line_sp=1.0)
    text(s, x + 0.32, 3.22, bw - 0.6, 0.32, h["lab"], 13, INK, True)
    text(s, x + 0.32, 3.62, bw - 0.6, 1.02, h["note"], 10.5, MUTED, line_sp=1.45)

rect(s, M, 5.02, CW, 1.10, fill="F5F3FF", radius=True)
text(s, M + 0.32, 5.20, CW - 0.64, 0.80,
     ["**一句话**：以 SU(2) 群做统一状态载体，三个流形（接触/性能/潜空间）在同一度量下比较，"
      "世界模型按「L5 出条件 → L4 调度量 → L3 判可行性 → L2 收口下发」分层，最后由底层势函数统一兜住。",
      "**每层只做一件事**，所以每层都能单独验证 —— 这是它现在能被证明、将来能被追责的原因。"],
     11.5, INK, line_sp=1.45)
footer(s, "流形引擎 · 世界模型分层框架 · 结论先行")

# ── P3 专利全景 ───────────────────────────────────────────────────────
s = page(prs, "专利组合", "12 件专利里，4 件是这套框架的内核",
         "其余 8 件不是陪衬：它们分别管入口、骨架、记忆、协同、对位、配置和证据出口。")
rows = [["编号", "代号", "层", "专利名称（简）", "在这套框架里的位置"]]
colors, bolds = {}, {}
for i, p in enumerate(DATA["patents"], 1):
    rows.append([p["id"], p["star"], p["layer"],
                 ("★ " if p["core"] else "") + p["title"][:24], p["role"]])
    if p["core"]:
        colors[(i, 0)] = VIOLET
        bolds[(i, 0)] = True
table(s, M, 2.16, CW, rows, [0.72, 0.72, 1.16, 3.90, 5.27],
      head_h=0.34, row_h=0.322, size=8.6, colors=colors, bolds=bolds)
text(s, M, 6.46, CW, 0.40,
     ["**★ = 内核四件**：003 统一表示 · 004 逐层收窄与收口 · 007 世界模型分块 · 010 多层记忆。"
      "其余为支撑件，各自负责一段。"], 9, MUTED)
footer(s, "流形引擎 · 世界模型分层框架 · 专利组合")

# ── P4 数学原理 I ─────────────────────────────────────────────────────
s = page(prs, "数学原理 I", "为什么用 SU(2) 当统一载体：因为它对任何输入都封闭",
         "这是整套框架能「不加归一化假设、不怕脏数据」的唯一原因。")
blocks = [
    ("定义", "SU(2) = { U : U*U = I, det U = 1 }",
     "二阶酉群且行列式为 1。等价写法 U = exp(-i ω·σ/2)，ω 是三维旋转向量，σ 是泡利矩阵。"),
    ("四元数化", "U = w·I - i(x σx + y σy + z σz)，(w,x,y,z) 是单位四元数",
     "所以群元素就是四维单位球面 S³ 上的一点 —— 表示、存储、插值都变成球面上的几何问题。"),
    ("封闭性", "任意实向量 f → ω → U = exp(-i ω·σ/2) 仍在群内",
     "指数映射把整个三维空间整体映进群内部：数据多大、多脏都不会溢出，也不需要先归一化。"),
]
y = 2.18
for k, formula, why in blocks:
    rect(s, M, y, CW, 1.28, fill=SOFT, line=LINE, radius=True)
    rect(s, M, y, 0.05, 1.28, fill=VIOLET)
    text(s, M + 0.28, y + 0.15, 1.30, 0.30, k, 11.5, VIOLET, True)
    text(s, M + 1.72, y + 0.13, CW - 2.0, 0.34, formula, 13, INK, True)
    text(s, M + 1.72, y + 0.56, CW - 2.0, 0.60, why, 10.5, MUTED, line_sp=1.35)
    y += 1.40

text(s, M, 6.34, CW, 0.48,
     ["**三层含义**：方向 = 状态（误差往哪儿偏）· 角度 = 幅度（偏多少）· "
      "可观测强度 = 可信度（偏了但看不清时自动降权）。"], 11, INK)
footer(s, "流形引擎 · 世界模型分层框架 · 数学原理 I")

# ── P5 数学原理 II ────────────────────────────────────────────────────
s = page(prs, "数学原理 II", "三个流形，一套度量：接触看方向、性能看代价、潜空间看远近",
         "三个流形不是三套体系，而是同一个度量在不同数据上的取值 —— 这才谈得上跨层比较。")
mans = [
    ("接触流形", "进度方向 / 偏离方向", "把误差拆成「往孔里还有多远」和「偏出轴线多少」。"
     "前者决定该不该继续推进，后者决定要不要先纠偏。", "偏离超阈 → 否决推进"),
    ("性能流形", "耦合代价 Vp / η", "同一动作在不同层的效率代价。代价突然升高说明某一段在硬扛，"
     "不是失败但已经在浪费节拍。", "代价升高 → 换动作或换档"),
    ("潜空间流形", "由世界模型潜变量投影", "把预测出的潜在状态投到流形上，看它离已知的可行区有多远。"
     "离得远就是没见过的情况。", "远离可行区 → 降权或拒绝"),
]
bw2 = (CW - 0.44) / 3
for i, (name, formula, why, act) in enumerate(mans):
    x = M + i * (bw2 + 0.22)
    rect(s, x, 2.20, bw2, 3.16, fill=SOFT, line=LINE, radius=True)
    rect(s, x, 2.20, bw2, 0.055, fill=[GOOD, OKC, VIOLET][i])
    text(s, x + 0.26, 2.40, bw2 - 0.52, 0.34, name, 15, INK, True)
    text(s, x + 0.26, 2.82, bw2 - 0.52, 0.28, formula, 10.5, [GOOD, OKC, VIOLET][i], True)
    rect(s, x + 0.26, 3.22, bw2 - 0.52, 0.006, fill=LINE)
    text(s, x + 0.26, 3.34, bw2 - 0.52, 1.20, why, 10, MUTED, line_sp=1.4)
    rect(s, x + 0.26, 4.66, bw2 - 0.52, 0.46, fill=WHITE, line=LINE, radius=True)
    text(s, x + 0.26, 4.66, bw2 - 0.52, 0.46, act, 9.5, INK, True,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, M, 5.56, CW, 1.0,
     ["**为什么三者能共用一套度量**：它们都先被映到同一个群元素上，度量在该群上是同一条式子 —— "
      "接触读其中两维、性能读代价标量、潜空间读投影距离。",
      "**换成三套各自定义**就会出现：同一件事在三个地方算出三个结论，谁对谁错说不清。"],
     11, INK, line_sp=1.5)
footer(s, "流形引擎 · 世界模型分层框架 · 数学原理 II")

# ── P6 数学验证 ───────────────────────────────────────────────────────
s = page(prs, "实测验证", "13 项断言全过，最差一项误差 1.5e-15 —— 等于机器精度",
         "全部由 tools/verify_manifold_math.py 现场跑出来，不是引用论文结论。")
rows = [["断言", "实测值", "容差", "这条为什么重要"]]
for m in DATA["math"]:
    rows.append([m["k"], m["v"], m["c"], m["why"]])
table(s, M, 2.16, CW, rows, [2.52, 1.36, 1.10, 6.79],
      head_h=0.36, row_h=0.40, size=9)
text(s, M, 6.30, CW, 0.50,
     ["**另外还跑了三项**：σ 从 0.5 到 0.01，度量由 1.167 单调升到 1.909；法线偏离 0°→6°，"
      "增益由 1.000 单调降到 0.000；同元素对易残差 3.1e-16、异轴不对易 0.4219。"], 9.5, MUTED, line_sp=1.35)
footer(s, "流形引擎 · 世界模型分层框架 · 实测验证")

# ── P7 分层框架 ───────────────────────────────────────────────────────
s = page(prs, "分层框架", "世界模型分四层干活：上面出条件，下面做决定",
         "每层只做一件事，所以每层都能被单独验证、单独追责 —— 这是分层真正的价值。")
bw3 = (CW - 0.66) / 4
for i, L in enumerate(DATA["layers"]):
    x = M + i * (bw3 + 0.22)
    col = [GOOD, ACCENT, VIOLET, OKC][i]
    rect(s, x, 2.18, bw3, 3.30, fill=SOFT, line=LINE, radius=True)
    rect(s, x, 2.18, bw3, 0.055, fill=col)
    text(s, x + 0.24, 2.36, bw3 - 0.48, 0.32, L["name"], 15, INK, True)
    text(s, x + 0.24, 2.72, bw3 - 0.48, 0.28, L["role"], 10, col, True)
    rect(s, x + 0.24, 3.08, bw3 - 0.48, 0.006, fill=LINE)
    text(s, x + 0.24, 3.18, bw3 - 0.48, 1.02, L["does"], 10, MUTED, line_sp=1.4)
    rect(s, x + 0.24, 4.24, bw3 - 0.48, 0.90, fill=WHITE, line=LINE, radius=True)
    text(s, x + 0.36, 4.32, bw3 - 0.72, 0.76, L["evidence"], 9, INK, line_sp=1.35)
    text(s, x + 0.24, 5.20, bw3 - 0.48, 0.24, L["code"], 8, ACCENT)
text(s, M, 5.62, CW, 0.9,
     ["**收口链路**：L5 给出后续几步的条件 → L4 按误差方向与把握程度调度量 → "
      "L3 判三个条件是否都满足 → L2 按几何真值限幅或否决，只有它下发执行量。",
      "**上层永远不直接出执行量** —— 这是这套框架敢让上层用大模型、上层出错也不会撞机的原因。"],
     11, INK, line_sp=1.45)
footer(s, "流形引擎 · 世界模型分层框架 · 分层框架")

# ── P8 分层实测 ───────────────────────────────────────────────────────
s = page(prs, "分层实测", "每层的判据都跑出来了，数字不是形容词",
         "口径：hjepa_mr_layers._selftest，四层共 20 项检查，全部通过。")
pairs = [
    ("L2 收口", "法线偏离 → 增益", "0°,1°,2°,3°,4°,6° → 1.000, 0.799, 0.599, 0.398, 0.198, 0.000",
     "偏离越大越刹得住，到 6° 直接否决", GOOD),
    ("L3 条件", "三个条件同时满足才放行", "位姿偏差 5mm > 2mm 拒；法线 3° > 1.5° 拒；σ 0.5 > 0.2 拒",
     "任一超阈即拒，并给出是人看得懂的原因", ACCENT),
    ("L4 调制", "把握程度 → 度量各向异性", "σ 0.5, 0.2, 0.05, 0.01 → M 1.167, 1.333, 1.667, 1.909",
     "越有把握越果断，没把握就退回各向同性", VIOLET),
    ("L5 条件", "后续步数与外推标注", "无动力学模型时出 3 步，距离 0.010 → 0.020 → 0.030 m，并标注「匀速外推非预测」",
     "该老实的地方明说，不把趋势当预测", OKC),
]
y = 2.16
for name, test, data_s, note, col in pairs:
    rect(s, M, y, CW, 1.12, fill=SOFT, line=LINE, radius=True)
    rect(s, M, y, 0.055, 1.12, fill=col)
    text(s, M + 0.26, y + 0.14, 1.34, 0.30, name, 12.5, col, True)
    text(s, M + 1.74, y + 0.12, 4.10, 0.28, test, 10.5, INK, True)
    text(s, M + 1.74, y + 0.46, CW - 2.0, 0.28, data_s, 9.5, INK)
    text(s, M + 1.74, y + 0.78, CW - 2.0, 0.26, note, 9, MUTED)
    y += 1.18
text(s, M, 6.90, CW, 0.30, "", 8, MUTED)
footer(s, "流形引擎 · 世界模型分层框架 · 分层实测")

# ── P9 工程落地 ───────────────────────────────────────────────────────
s = page(prs, "状态空间工程", "框架不是文档里的框，是画布上能点、能跑、能看的九个节点",
         "口径：逐节点起独立进程真调，记录进程级状态与耗时。")
rows = [["节点", "职责", "实测"]]
for n in DATA["nodes"]:
    rows.append([n["id"], n["what"], n["sec"]])
table(s, M, 2.16, CW * 0.62, rows, [1.95, 3.85, 1.32], head_h=0.34, row_h=0.352, size=9.5)

bx = M + CW * 0.62 + 0.26
bw4 = CW - CW * 0.62 - 0.26
stats = [("9 / 9", "流形相关节点进程级通过", GOOD),
         ("65 / 65", "整张画布全部节点可运行", GOOD),
         ("29.83 s", "全部节点串行扫一轮", OKC)]
for i, (big, lab, col) in enumerate(stats):
    yy = 2.16 + i * 1.16
    rect(s, bx, yy, bw4, 1.02, fill=SOFT, line=LINE, radius=True)
    rect(s, bx, yy, 0.05, 1.02, fill=col)
    text(s, bx + 0.26, yy + 0.12, bw4 - 0.5, 0.42, big, 23, col, True, line_sp=1.0)
    text(s, bx + 0.26, yy + 0.60, bw4 - 0.5, 0.32, lab, 9.5, MUTED)

text(s, M, 5.82, CW, 1.0,
     ["**每个节点都能打开到源码**：契约文件写明端口与执行口径，实现在 impl 目录，算法在 policies 目录，"
      "画布标注给出执行入口的绝对路径与行号。",
      "**能跑 ≠ 会干活**：上面九项是「调用不崩、能返回」，其中标定与工作记忆节点是真出了数；"
      "预测类节点缺训练权重，返回的是降级结果。"],
     10.5, INK, line_sp=1.45)
footer(s, "流形引擎 · 世界模型分层框架 · 状态空间工程")

# ── P10 可行性 ────────────────────────────────────────────────────────
s = page(prs, "技术可行性", "哪些已经能站住，哪些还站不住 —— 分开说",
         "把「已验证」和「待验证」写在同一页，是为了避免把下一步当成已完成。")
col_w = (CW - 0.30) / 2
rect(s, M, 2.18, col_w, 3.66, fill="ECFDF5", line="A7F3D0", radius=True)
text(s, M + 0.28, 2.36, col_w - 0.56, 0.32, "已经站得住的", 13, GOOD, True)
text(s, M + 0.28, 2.74, col_w - 0.56, 3.0,
     ["· " + x for x in DATA["feasible"]["have"]], 10, INK, line_sp=1.42, space=7)

rect(s, M + col_w + 0.30, 2.18, col_w, 3.66, fill="FEF2F2", line="FECACA", radius=True)
text(s, M + col_w + 0.58, 2.36, col_w - 0.56, 0.32, "还站不住的", 13, RISK, True)
text(s, M + col_w + 0.58, 2.74, col_w - 0.56, 3.0,
     ["· " + x for x in DATA["feasible"]["lack"]], 10, INK, line_sp=1.42, space=7)

rect(s, M, 6.00, CW, 0.78, fill="EFF6FF", radius=True)
text(s, M + 0.30, 6.14, CW - 0.60, 0.52,
     ["**判断**：数学与工程底座已经可以对外讲；「预测」和「成功率」两件事还不能 —— "
      "它们缺的是权重和真实数据，不是设计。"], 11, INK, line_sp=1.3)
footer(s, "流形引擎 · 世界模型分层框架 · 技术可行性")

# ── P11 三向映射 ──────────────────────────────────────────────────────
s = page(prs, "专利—技术—证据", "每一条技术主张，都能指到一条权利要求和一个实测结果",
         "这张表是给评审和客户看的：不要求相信，只要求可以逐条核对。")
rows = [["技术主张", "对应权利要求", "实测证据", "它保证了什么"]]
for r in DATA["mapping"]:
    rows.append(r)
table(s, M, 2.16, CW, rows, [2.34, 1.72, 4.32, 3.39], head_h=0.36, row_h=0.62, size=9.5)
text(s, M, 6.24, CW, 0.60,
     ["**核对的入口**：数学 → tools/verify_manifold_math.py；分层 → hjepa_mr_layers._selftest；"
      "节点 → 画布冒烟报告；权利要求 → config/patents/patent_registry.json。"], 9.5, MUTED, line_sp=1.35)
footer(s, "流形引擎 · 世界模型分层框架 · 专利—技术—证据")

# ── P12 下一步 ────────────────────────────────────────────────────────
s = page(prs, "下一步", "四件事，按「能不能立刻做」排，不按听起来多领先排",
         "已完成的三份证据接下来要变成常态闸门，而不是一次性汇报材料。")
y = 2.20
for a in DATA["next"]:
    col = [GOOD, ACCENT, VIOLET, MUTED][int(a["p"]) - 1]
    rect(s, M, y, CW, 0.98, fill=SOFT, line=LINE, radius=True)
    rect(s, M, y, 0.055, 0.98, fill=col)
    text(s, M + 0.28, y + 0.15, 0.55, 0.32, a["p"], 17, col, True)
    text(s, M + 0.92, y + 0.14, 1.10, 0.30, a["when"], 10.5, col, True)
    text(s, M + 2.10, y + 0.13, 5.10, 0.34, a["what"], 12.5, INK, True)
    text(s, M + 7.40, y + 0.14, CW - 7.60, 0.66,
         ["**闸门**：" + a["gate"]], 10, MUTED, line_sp=1.3)
    y += 1.06
text(s, M, 6.44, CW, 0.5,
     ["**一句话收尾**：这套框架今天能拿出来的是「自洽 + 可跑 + 可核对」；"
      "能不能打，要看预测器训练完和真机数据进来之后的第二次汇报。"], 10.5, INK)
footer(s, "流形引擎 · 世界模型分层框架 · 下一步")

prs.save(OUT)

# ══════════════════════════════════════════════════════════════════════
bad = []
for i, sl in enumerate(prs.slides, 1):
    for sh in sl.shapes:
        if None in (sh.left, sh.top, sh.width, sh.height):
            continue
        r = (sh.left + sh.width) / 914400
        b = (sh.top + sh.height) / 914400
        if r > W - 0.05 or b > H - 0.02:
            bad.append((i, sh.name, round(r, 2), round(b, 2)))
stars = sum(1 for sl in prs.slides for sh in sl.shapes
            if sh.has_text_frame and "**" in sh.text_frame.text)
print("幻灯片 %d 页" % len(prs.slides))
print("溢出形状: %d %s" % (len(bad), bad[:4] if bad else ""))
print("残留 ** 的形状: %d" % stars)
print("输出: %s" % OUT)
