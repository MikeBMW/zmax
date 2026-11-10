#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_deck.py — 生成《Z-MAX 项目矩阵状态评估》PPT

数据在 deck_data.json (side-car)，本脚本只管版式。
重新生成: python3 make_deck.py
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
OUT = os.path.join(HERE, "Z-MAX项目矩阵状态评估_5.50.D-P1_20261110.pptx")

# ── 版式常量 ────────────────────────────────────────────────────────────
W, H = 13.333, 7.5
M = 0.78                      # 左右边距
CW = W - 2 * M                # 内容宽
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
    """多行文本框；支持行内 **粗体**；lines 可为 str 或 list。"""
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
        5 if radius else 1,      # 5 = rounded rect, 1 = rect
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
    text(s, M, 0.86, CW, 0.72, title, 25, INK, True, line_sp=1.0)
    if sub:
        text(s, M, 1.62, CW, 0.46, sub, 13, MUTED, line_sp=1.2)
    return s


def footer(s, note):
    rect(s, M, FOOT_Y - 0.10, CW, 0.008, fill=LINE)
    text(s, M, FOOT_Y, CW * 0.68, 0.26, note, 9, MUTED)
    text(s, W - M - 2.45, FOOT_Y, 2.45, 0.26,
         "5.50.D-P1 · 2026-11-10", 9, MUTED, align=PP_ALIGN.RIGHT)


def table(slide, x, y, w, rows, col_w, head_h=0.42, row_h=0.40, size=11,
          head_fill="1F2937", zebra=True, colors=None):
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
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
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
            if ri and colors and (ri, ci) in colors:
                col = colors[(ri, ci)]
            _font(r, size, ri == 0 or (colors and (ri, ci) in colors), col)
    return shp


# ══════════════════════════════════════════════════════════════════════
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(W), Inches(H)
META = DATA["meta"]

# ── P1 封面 ───────────────────────────────────────────────────────────
s = prs.slides.add_slide(prs.slide_layouts[6])
rect(s, 0, 0, W, H, fill="0F172A")
rect(s, 0, 0, 0.14, H, fill=ACCENT)
text(s, 1.15, 2.05, 9.6, 0.40, "Z-MAX · 天枢产品边界", 13, "93C5FD", True)
text(s, 1.15, 2.55, 10.6, 1.5, META["title"], 42, WHITE, True, line_sp=1.05)
text(s, 1.15, 3.95, 10.2, 0.9, META["subtitle"], 17, "CBD5E1", line_sp=1.35)
rect(s, 1.15, 5.05, 3.4, 0.03, fill=ACCENT)
text(s, 1.15, 5.28, 10.0, 0.9,
     ["版本 %s　　编制 %s" % (META["version"], META["date"]),
      "依据：%s" % META["source"]], 11, "94A3B8", line_sp=1.5)

# ── P2 一页结论 ───────────────────────────────────────────────────────
s = page(prs, "结论先行", "我们的能力是「L2 满、L3 半、L4 空」，七个项目正好分布在这条曲线上",
         "不是一个成功率衡量所有项目，而是每一层用自己的判据。先看清能力曲线，再决定每个项目怎么立项、怎么承诺。")
bx, by, bw, bh, gap = M, 2.30, (CW - 0.55 * 2) / 3, 1.62, 0.55
for i, (num, lab, note, col) in enumerate([
        ("97.1%", "L2 主干链路实测", "33 / 34 边（剩余 1 条为无相机帧不产 3D）", GOOD),
        ("100%", "流形 + 记忆闭环", "45 / 45 边（势场→动作头→前馈→调度→记忆回灌）", GOOD),
        ("75.2%", "全图 L1~L5 + 执行层", "167 / 222 边（缺口集中在 L4/L5 真值缺失）", OKC)]):
    x = bx + i * (bw + gap)
    rect(s, x, by, bw, bh, fill=SOFT, line=LINE, radius=True)
    rect(s, x, by, 0.05, bh, fill=col)
    text(s, x + 0.30, by + 0.24, bw - 0.5, 0.66, num, 34, col, True, line_sp=1.0)
    text(s, x + 0.30, by + 0.94, bw - 0.5, 0.30, lab, 13, INK, True)
    text(s, x + 0.30, by + 1.22, bw - 0.5, 0.40, note, 9.5, MUTED, line_sp=1.15)

rect(s, M, 4.30, CW, 1.05, fill="EFF6FF", radius=True)
text(s, M + 0.32, 4.48, CW - 0.64, 0.75,
     ["**结论**：能硬承诺的只有 L2 —— 有产线证据、有闭环实测；L3 有演示但缺节拍数据；L4 连供应商自己"
      "都不承诺指标。", "所以商务上必须**按层承诺**：L2 卖指标，L3 卖增值，L4 只做 PoC。"],
     12.5, INK, line_sp=1.45)
text(s, M, 5.60, CW, 0.8,
     ["支撑数据见第 4 页；逐项目判断见第 6–12 页；建议与门槛见第 15–16 页。"], 11, MUTED)
footer(s, "Z-MAX 项目矩阵状态评估 · 结论先行")

# ── P3 进化阶梯 ───────────────────────────────────────────────────────
s = page(prs, "产品进化", "五代技术，五个供应商，一次比一次少依赖「人教」",
         "每一次跃迁都在替客户省一样东西：示教时间 → 换型时间 → 人工接管。")
evo = DATA["evolution"]
nx = M
nw = (CW - 4 * 0.12) / 5
for i, e in enumerate(evo):
    x = M + i * (nw + 0.12)
    col = [GOOD, GOOD, OKC, "7C3AED", "9CA3AF"][i]
    rect(s, x, 2.32, nw, 3.05, fill=SOFT, line=LINE, radius=True)
    rect(s, x, 2.32, nw, 0.06, fill=col)
    text(s, x + 0.20, 2.52, nw - 0.4, 0.28, "L" if False else e["layer"], 10, col, True)
    text(s, x + 0.20, 2.82, nw - 0.4, 0.42, e["stage"], 17, INK, True, line_sp=1.0)
    text(s, x + 0.20, 3.30, nw - 0.4, 0.72, e["what"], 10.5, MUTED, line_sp=1.3)
    rect(s, x + 0.20, 4.10, nw - 0.4, 0.006, fill=LINE)
    text(s, x + 0.20, 4.22, nw - 0.4, 0.30, e["who"], 10, ACCENT, True)
    text(s, x + 0.20, 4.58, nw - 0.4, 0.66, e["jump"], 9.5, INK, line_sp=1.25)
text(s, M, 5.62, CW, 0.9,
     ["**读法**：左边两级已经产出（有产线证据）；中间两级有演示或承诺；最右一级在全行业都还没有成型方案。",
      "我们不缺想法，缺的是把最右一级变成可验收指标 —— 这一点决定了对外该承诺到哪一级。"],
     12, INK, line_sp=1.5)
footer(s, "Z-MAX 项目矩阵状态评估 · 产品进化")

# ── P4 成熟度实测 ─────────────────────────────────────────────────────
s = page(prs, "实测依据", "状态空间逐层实测：越往上，验证越少、不确定性越大",
         "口径：tools/verify_l2_linkage.py --engine --all，按画布拓扑逐节点真调、跑两拍，引擎真跑 357 帧。")
rows = [["层级", "实测", "样本", "结论", "说明"]]
colors = {}
for i, m in enumerate(DATA["maturity"], 1):
    rows.append([m["layer"], m["ratio"], m["detail"], m["verdict"], m["why"]])
    c = GOOD if m["verdict"] == "可交付" else OKC if m["verdict"] == "可试点" else RISK if m["verdict"] == "仅 PoC" else MUTED
    colors[(i, 3)] = c
    colors[(i, 1)] = c
table(s, M, 2.30, CW, rows, [2.92, 0.92, 2.34, 1.02, 4.58], head_h=0.40, row_h=0.56, size=10.5, colors=colors)
text(s, M, 6.20, CW, 0.6,
     ["**这张表是后面所有判断的地基**：不是我们不想承诺 L3/L4，是这两层还没有可复现的证据。"], 11.5, INK)
footer(s, "Z-MAX 项目矩阵状态评估 · 实测依据")

# ── P5 项目矩阵 ───────────────────────────────────────────────────────
s = page(prs, "项目矩阵", "七个项目，按状态空间层级排开，一眼看清各自卡在哪",
         "同一张表里既有已交付的，也有连供应商都不承诺指标的 —— 混在一起谈是最容易出事的地方。")
rows = [["#", "项目", "供应商", "技术层", "当前状态"]]
colors = {}
for i, p in enumerate(DATA["projects"], 1):
    rows.append([p["id"], p["name"], p["vendor"], p["tech"][:38] + ("…" if len(p["tech"]) > 38 else ""), p["state"]])
    colors[(i, 1)] = TONE[p["tone"]]
table(s, M, 2.28, CW, rows, [0.50, 2.38, 2.08, 4.22, 2.60], head_h=0.38, row_h=0.52, size=9.5, colors=colors)
text(s, M, 6.42, CW, 0.5,
     ["**颜色**：绿 = 有产线级证据　橙 = 有演示或承诺待验　红 = 不具备交付能力。逐项展开见第 6–12 页。"], 10, MUTED)
footer(s, "Z-MAX 项目矩阵状态评估 · 项目矩阵")


# ── 逐项目页 ──────────────────────────────────────────────────────────
def project_page(p, heading, lead, extra=None):
    s = page(prs, "%s · %s" % (p["id"], p["vendor"]), heading, lead)
    col = TONE[p["tone"]]
    rect(s, M, 2.28, CW, 0.06, fill=col)
    info = [("技术路线", p["tech"]), ("当前状态", p["state"]), ("已知证据", p["evidence"]), ("判断", p["verdict"])]
    y = 2.55
    for k, v in info:
        text(s, M, y, 1.35, 0.32, k, 11, MUTED, True)
        text(s, M + 1.45, y, CW - 1.45, 0.80 if len(str(v)) > 46 else 0.40, v, 12, INK, line_sp=1.35)
        y += 0.86 if len(str(v)) > 46 else 0.50
    if extra:
        rect(s, M, y + 0.12, CW, 1.28, fill=SOFT, radius=True)
        text(s, M + 0.30, y + 0.30, CW - 0.60, 1.0, extra, 11.5, INK, line_sp=1.45)
    footer(s, "Z-MAX 项目矩阵状态评估 · %s" % p["name"])
    return s


P = {p["id"]: p for p in DATA["projects"]}

project_page(P["P1"], "固定轨迹 + 示教点：把「人会教」变成「机器照做」",
             "这是 L2 最基础也最扎实的一段 —— 所有后续能力的对照组。",
             "**为什么它能交付**：路径固定、工件位置固定、判据单一（插到位/插坏）。"
             "AOI 静态拍照只回答「有没有、正不正」，不参与动作 —— 责任边界清楚，出错也能定位。")
project_page(P["P2"], "伺服视觉：从「按点走」到「到位置自己找」",
             "结构光相机 + 微小空间自主引导，这是本项目第一次真正的能力跃迁。",
             "**跃迁点在哪**：机器人到达指定空间区域后，伺服视觉服务给 3D 引导 —— 工件位置变了不用重示教。"
             "支撑它的是 L2 光学质量检测 + 融合定位 + 统一状态空间三件事同时到位（实测 33/34 与 45/45）。")
project_page(P["P3"], "增强感知：换料不用重示教，是性价比最高的下一步",
             "SAM3 开放词汇分割 + L2 泛化上料 —— 只依赖 L2 和视觉，不碰 L3/L4。",
             "**为什么建议立**：它不依赖任何未就绪能力。**风险在感知本身**：来料变化（脏污、反光、遮挡、"
             "料盘材质）会直接打穿分割质量。**验收要写两条**：泛化上料成功率、换型时间。")
project_page(P["P4"], "VTLA：本体已完成，但「能演示」和「能插光模块」是两件事",
             "天机 7 kg 协作臂 + VTLA + 强化学习；目前采数据、训练中，成功率不足以支撑正常插拔。",
             "**这里要说实话**：亚毫米插拔任务的样本效率极低，VTLA 需要的数据量级远高于当前采集速度。"
             "这不是执行机构的问题，是「数据—策略」闭环还没闭上。**不宜按交付承诺立项**，建议改为技术储备与数据管道。")
project_page(P["P5"], "无界智航：目前唯一给出节拍承诺 + 三档报价 + 扩展包定位的供给方",
             "吸盘 + 可翻面，1000 UPH 节拍已承诺；基础型/精细型/专家型目标报价与方案已反馈。",
             "**商业模式一致这一点比节拍更值钱**：他们提的是「具身工具箱」——机器人扩展包，"
             "不是自动化方案。这和我们「能力分级 + 按级交付」的定位同构。"
             "新需求（如带散热片光模块抓取）他们也愿意出集成方案。建议优先战略合作。")
project_page(P["P6"], "智元：有夹爪演示视频，但还缺产线数据",
             "L3 VLA 路线，夹爪抓取摆盘。",
             "**判断**：演示级。要变成可选项，需要补三样 —— 连续运行节拍、翻面/异形件成功率、"
             "以及换型时间。建议作为 L3 VLA 的**备选供给**，不排他，也不单独对外承诺。")
project_page(P["P7"], "具脑磐石：L4 是行业共同缺口，不是一家的短板",
             "H-JEPA 架构仍在发展中；可以接场景，但不承诺 99% 成功率等性能指标，希望协商。",
             "**科学解释**：L4 的核心难点不是「预测得准」，而是**不确定性怎么表达与传播**（协方差/置信度/"
             "失败可检出性），这一层全行业都还没标准化。**建议**：分单一场景做 PoC，门槛写死"
             "（样本量、场景、判据），不进主链、不做对外承诺。")
footer_note = "Z-MAX 项目矩阵状态评估"

# ── P13 二维矩阵 ──────────────────────────────────────────────────────
s = page(prs, "总览图", "把七个项目放到「技术层 × 可交付度」上，位置比形容词可靠",
         "横轴是状态空间层级，纵轴是当前可交付程度（是否有产线级证据）。")
ax_x, ax_y, ax_w, ax_h = M + 0.9, 2.40, CW - 1.5, 3.55
rect(s, ax_x, ax_y, ax_w, ax_h, fill=WHITE, line=LINE)
for gy in (0.25, 0.5, 0.75):
    rect(s, ax_x, ax_y + ax_h * gy, ax_w, 0.006, fill="F1F5F9")
cols = [("L2", 0.10), ("L3", 0.42), ("L4", 0.76)]
for name, frac in cols:
    text(s, ax_x + ax_w * frac, ax_y + ax_h + 0.10, 1.2, 0.28, name, 12, MUTED, True)
    rect(s, ax_x + ax_w * frac - 0.004, ax_y, 0.008, ax_h, fill="F1F5F9")
# 纵轴标签
for lab, frac in (("已交付", 0.88), ("有演示/承诺", 0.52), ("不具备", 0.16)):
    text(s, M - 0.05, ax_y + ax_h * (1 - frac) - 0.14, 0.85, 0.28, lab, 9.5, MUTED,
         align=PP_ALIGN.RIGHT)
POS = {"P1": (0.10, 0.90), "P2": (0.16, 0.84), "P3": (0.26, 0.60),
       "P4": (0.44, 0.34), "P5": (0.52, 0.68), "P6": (0.60, 0.48), "P7": (0.80, 0.22)}
for p in DATA["projects"]:
    fx, fy = POS[p["id"]]
    cx, cy = ax_x + ax_w * fx, ax_y + ax_h * (1 - fy)
    col = TONE[p["tone"]]
    rect(s, cx - 0.09, cy - 0.09, 0.18, 0.18, fill=col)
    text(s, cx + 0.16, cy - 0.20, 2.6, 0.40, "%s %s" % (p["id"], p["name"].split(" · ")[0]),
         9.5, INK, True, line_sp=1.1)
text(s, M, 6.24, CW, 0.7,
     ["**这张图要说明的是**：绿点在左下（L2）密集且靠上；橙点分散在中段；红点只在右上（L4）—— "
      "**越往上一级，可交付度越低，这不是执行问题，是层级本身决定的**。"], 11.5, INK, line_sp=1.4)
footer(s, "Z-MAX 项目矩阵状态评估 · 总览图")

# ── P14 分层指标 ──────────────────────────────────────────────────────
s = page(prs, "判据", "不同层要用不同指标 —— 拿一个成功率横比所有项目，结论一定错",
         "最危险的一种错误：用 Z100Fd 的成功率去否定 L2 已经交付的事实，或者用 L2 的 UPH 去要求 L4。")
rows = [["层级", "该用的指标", "为什么"]]
for m in DATA["metrics"]:
    rows.append([m["layer"], m["metric"], m["note"]])
table(s, M, 2.32, CW, rows, [1.5, 5.0, 5.63], head_h=0.42, row_h=0.66, size=11.5)
text(s, M, 4.62, CW, 1.9,
     ["**三条硬规矩**",
      "① 每条对外承诺，必须配一条可复现判据：样本量、场景、测试方法、判定阈值。",
      "② 没有产线级证据的能力，不进合同，只进 PoC 或联合开发条款。",
      "③ 供应商给的节拍/成功率，一律转成我们的验收判据写进 SOR，不接受口头承诺。"],
     12, INK, line_sp=1.55, space=9)
footer(s, "Z-MAX 项目矩阵状态评估 · 判据")

# ── P15 建议 ──────────────────────────────────────────────────────────
s = page(prs, "建议", "四件事，按「现在能不能兑现」排序，不按听起来多先进排序",
         "原则：能硬承诺的先放量，风险可控的才立项，需要长期积累的只做储备与 PoC。")
y = 2.30
for a in DATA["advice"]:
    col = [GOOD, GOOD, OKC, MUTED][int(a["p"]) - 1]
    rect(s, M, y, CW, 0.94, fill=SOFT, line=LINE, radius=True)
    rect(s, M, y, 0.055, 0.94, fill=col)
    text(s, M + 0.28, y + 0.14, 0.55, 0.32, a["p"], 17, col, True)
    text(s, M + 0.92, y + 0.13, 1.0, 0.30, a["when"], 10.5, col, True)
    text(s, M + 1.95, y + 0.12, 4.7, 0.34, a["what"], 12.5, INK, True)
    text(s, M + 6.75, y + 0.12, CW - 6.95, 0.72,
         ["%s" % a["why"], "**门槛**：%s" % a["gate"]], 10, MUTED, line_sp=1.3, space=2)
    y += 1.02
footer(s, "Z-MAX 项目矩阵状态评估 · 建议")

# ── P16 风险 ──────────────────────────────────────────────────────────
s = page(prs, "风险", "四个最容易出事的点，每个都配一条硬判据",
         "这些不是理论风险 —— 前两类在对客户讲方案时最容易发生，后两类在项目验收时最容易发生。")
rows = [["风险", "典型触发场景", "对策"]]
for r in DATA["risks"]:
    rows.append([r["r"], r["how"], r["fix"]])
table(s, M, 2.30, CW, rows, [2.75, 4.35, 5.03], head_h=0.40, row_h=0.80, size=10.5)
text(s, M, 6.10, CW, 0.7,
     ["**一句话**：把每条承诺都变成一条能当场跑的判据，我们就不会在客户现场解释「为什么没做到」。"],
     12, INK)
footer(s, "Z-MAX 项目矩阵状态评估 · 风险")

prs.save(OUT)

# ══════════════════════════════════════════════════════════════════════
# 自检: 溢出 / 残留星号
W_IN, H_IN = W, H
bad = []
for i, sl in enumerate(prs.slides, 1):
    for sh in sl.shapes:
        if None in (sh.left, sh.top, sh.width, sh.height):
            continue
        r = (sh.left + sh.width) / 914400
        b = (sh.top + sh.height) / 914400
        if r > W_IN - 0.05 or b > H_IN - 0.02:
            bad.append((i, sh.name, round(r, 2), round(b, 2)))
stars = sum(1 for sl in prs.slides for sh in sl.shapes
            if sh.has_text_frame and "**" in sh.text_frame.text)
bold_runs = 0
for sl in prs.slides:
    for sh in sl.shapes:
        if sh.has_text_frame:
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    if r.font.bold:
                        bold_runs += 1
print("幻灯片 %d 页" % len(prs.slides))
print("溢出形状: %d %s" % (len(bad), bad[:4] if bad else ""))
print("残留 ** 的形状: %d" % stars)
print("粗体 run 数: %d" % bold_runs)
print("输出: %s" % OUT)
