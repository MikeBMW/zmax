#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_manifold_deck.py — 生成《流形引擎方案》PPT (v5.50.779)

数据全部取自本机实测 (2026-11-20):
  · 引擎自检       python -m lerobot.manifold.manifold_engine --selftest  (7 流形 + 内稳态 4 项)
  · 通道自检       python src/lerobot/manifold/phase_corridor.py            (6 用例 + 24 点横扫)
  · 真机真值       zmax_data/se3/se3_state_live.json (zmax-se3-geom, rokae SDK 直采)
  · 画布           data/database/zmax/sources/canvas/state_space_obs.json  (96 节点 / 225 连线)
  · 分层验收       reports/layer_e2e_20261120_072522.json                  (L1–L5)
重生成: ./gui-venv311/bin/python tools/make_manifold_deck.py
"""
from __future__ import annotations

import os
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

W, H = Inches(13.333), Inches(7.5)
INK = RGBColor(0x14, 0x18, 0x1C)
MUT = RGBColor(0x6B, 0x72, 0x80)
ACC = RGBColor(0x0F, 0x76, 0x6E)
BAND = RGBColor(0xF2, 0xF5, 0xF7)
LINE = RGBColor(0xD8, 0xDE, 0xE4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Noto Sans CJK SC"
MONO = "Noto Sans Mono CJK SC"
VER = "v5.50.779"
DATE = "2026-11-20"

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]


def _ea(run):
    """CJK 字形必须单独写 a:ea, 否则回落到主题字体。"""
    from pptx.oxml.ns import qn
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", FONT)


def text(slide, x, y, w, h, s, size=14, color=INK, bold=False, font=FONT,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.35, wrap=True):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    lines = s.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = font
        _ea(r)
    return tb


def bullets(slide, x, y, w, h, items, size=14, color=INK, gap=8):
    """items: [(level, text)] 或 str"""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, it in enumerate(items):
        lvl, s = it if isinstance(it, tuple) else (0, it)
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = 1.3
        p.space_after = Pt(gap)
        r = p.add_run()
        r.text = ("·  " if lvl == 0 else "–  ") + s
        r.font.size = Pt(size if lvl == 0 else size - 2)
        r.font.color.rgb = color if lvl == 0 else MUT
        r.font.name = FONT
        _ea(r)
    return tb


def rect(slide, x, y, w, h, fill=BAND, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06):
    sp = slide.shapes.add_shape(shape, x, y, w, h)
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(0.9)
    sp.shadow.inherit = False
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sp.adjustments[0] = radius
        except Exception:
            pass
    sp.text_frame.word_wrap = True
    return sp


def page(title, kicker="", num=0):
    s = prs.slides.add_slide(BLANK)
    if kicker:
        text(s, Inches(0.9), Inches(0.62), Inches(6), Inches(0.3), kicker, 11, ACC, True)
    text(s, Inches(0.9), Inches(0.95), Inches(11.4), Inches(0.7), title, 27, INK, True)
    rect(s, Inches(0.9), Inches(1.72), Inches(0.62), Inches(0.05), ACC, shape=MSO_SHAPE.RECTANGLE)
    # 页脚
    rect(s, Inches(0.9), Inches(6.82), Inches(11.53), Inches(0.012), LINE, shape=MSO_SHAPE.RECTANGLE)
    text(s, Inches(0.9), Inches(6.95), Inches(8.6), Inches(0.3),
         "流形引擎方案 · %s · %s · 数字均为本机实测" % (VER, DATE), 9, MUT)
    if num:
        text(s, Inches(11.4), Inches(6.95), Inches(1.0), Inches(0.3), "%02d" % num, 9, MUT,
             align=PP_ALIGN.RIGHT)
    return s


def table(s, x, y, w, col_w, rows, head_size=11, body_size=10.5, row_h=0.34):
    n, m = len(rows), len(rows[0])
    tb = s.shapes.add_table(n, m, x, y, w, Inches(row_h * n)).table
    for j, cw in enumerate(col_w):
        tb.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        tb.rows[i].height = Inches(row_h)
        for j, val in enumerate(row):
            c = tb.cell(i, j)
            c.margin_left = c.margin_right = Inches(0.08)
            c.margin_top = c.margin_bottom = Inches(0.02)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid()
            c.fill.fore_color.rgb = ACC if i == 0 else (WHITE if i % 2 else BAND)
            tf = c.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            r = p.add_run()
            r.text = str(val)
            r.font.size = Pt(head_size if i == 0 else body_size)
            r.font.bold = (i == 0)
            r.font.color.rgb = WHITE if i == 0 else INK
            r.font.name = FONT if i == 0 else (MONO if j == 0 and len(str(val)) < 22 and any(
                ch in str(val) for ch in "=≈−_/[]√") else FONT)
            _ea(r)
    return tb


def notes(s, t):
    s.notes_slide.notes_text_frame.text = t


# ── 01 封面 ────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
rect(s, Inches(0), Inches(0), Inches(0.28), H, ACC, shape=MSO_SHAPE.RECTANGLE)
text(s, Inches(1.1), Inches(1.55), Inches(9), Inches(0.35), "Z-MAX · L4 流形引擎", 12, ACC, True)
text(s, Inches(1.1), Inches(2.0), Inches(10.5), Inches(1.1), "流形引擎方案", 46, INK, True)
text(s, Inches(1.1), Inches(3.15), Inches(10.6), Inches(0.9),
     "从「空间轨迹复现」到「相空间安全通道」\n"
     "—— 把“走哪”写成几何，把“走多快”写成物理", 17, MUT, spacing=1.5)
rect(s, Inches(1.1), Inches(4.75), Inches(1.1), Inches(0.05), ACC, shape=MSO_SHAPE.RECTANGLE)
text(s, Inches(1.1), Inches(5.0), Inches(10), Inches(0.9),
     "%s    %s\n工控机 + Orin 真机链路 · 珞石 xCore SDK 直采真值" % (VER, DATE), 12, MUT, spacing=1.5)
notes(s, "本册所有数字都来自本机实测,不是估算:引擎自检、通道自检、真机 se3 真值、"
         "画布 JSON、分层 e2e 报告。页码 08/09/11 标注了各自的真源文件。")

# ── 02 一页总览 ────────────────────────────────────────────────────────────
s = page("一页看懂：三层约束，一条链", "总览", 2)
text(s, Inches(0.9), Inches(1.95), Inches(11.4), Inches(0.85),
     "上层只给意图与条件，执行由 L2 收口；记忆给出可行域，度规给出方向，物理给出边界。", 16, INK)
cards = [
    ("① 记忆流形", "SE(3) × S¹", "记住了“走过哪”\n位置 · 姿态 · 工序相位", "空间层"),
    ("② 黎曼度规", "G = diag(1/tol²)", "决定“往哪偏”\n径向敏感 / 轴向宽容", "几何层"),
    ("③ 相空间通道", "(q, q̇) 切丛", "决定“走多快、能量多高”\n速度纤维 + 门控", "物理层"),
]
x0 = Inches(0.9)
for i, (t1, t2, t3, tag) in enumerate(cards):
    x = x0 + Inches(3.98) * i
    c = rect(s, x, Inches(3.05), Inches(3.7), Inches(2.55), BAND, LINE)
    text(s, x + Inches(0.32), Inches(3.32), Inches(3.1), Inches(0.3), tag, 10, ACC, True)
    text(s, x + Inches(0.32), Inches(3.62), Inches(3.1), Inches(0.4), t1, 17, INK, True)
    text(s, x + Inches(0.32), Inches(4.05), Inches(3.1), Inches(0.35), t2, 11.5, ACC, font=MONO)
    text(s, x + Inches(0.32), Inches(4.5), Inches(3.1), Inches(0.9), t3, 11.5, MUT, spacing=1.4)
text(s, Inches(0.9), Inches(5.9), Inches(11.4), Inches(0.6),
     "三层叠加后：偏离会被“拉回”，跨越会被“限速”，错相位会被“冻结”。", 13, MUT)
notes(s, "三层的分工是这套方案的核心:记忆解决“像不像”,度规解决“刮不刮”,相空间解决“飞不飞”。"
         "只做前两层会过冲,只做前一层会刮擦。")

# ── 03 记忆流形 ────────────────────────────────────────────────────────────
s = page("记忆流形：R³ × S³ × S¹", "底空间", 3)
text(s, Inches(0.9), Inches(1.95), Inches(6.3), Inches(0.8),
     "末端状态不是一个 7 维向量，而是三个流形的乘积：平移在平面，姿态在单位球面，\n工序进度在单位圆。", 13.5, MUT)
table(s, Inches(0.9), Inches(2.95), Inches(7.1), [1.7, 2.0, 0.9, 2.5], [
    ["分量", "空间", "维", "物理含义"],
    ["R³ 平移", "欧氏", "3", "末端位置 / mm"],
    ["S³ 四元数", "单位球面", "4", "姿态，无欧拉奇异"],
    ["S¹ 相位", "单位圆", "1", "工序弧长相位 s"],
    ["16 维状态", "A–E 五段", "16", "5 Hz 真值，只读"],
], row_h=0.4)
c = rect(s, Inches(8.35), Inches(2.95), Inches(4.08), Inches(3.1), BAND, LINE)
text(s, Inches(8.62), Inches(3.2), Inches(3.5), Inches(0.3), "真源", 10, ACC, True)
text(s, Inches(8.62), Inches(3.45), Inches(3.55), Inches(2.4),
     "zmax_data/se3/se3_state_live.json\n"
     "服务：zmax-se3-geom  5 Hz\n"
     "truth_src：rokae_xcoresdk/endInRef\n"
     "（SDK 直采，不过 DDS）", 10.5, MUT, font=MONO, spacing=1.5)
text(s, Inches(0.9), Inches(4.95), Inches(7.1), Inches(1.2),
     "关键取舍：不把姿态塞进欧拉角，也不把相位当普通标量——\n"
     "S³ 用李代数算误差，S¹ 用圆上距离做门控，两者都避开“跨 ±180° 断崖”。", 12.5, MUT, spacing=1.5)
notes(s, "16 维里 A=位置(3)、B=轴 S²(3+偏差角)、C=四元数(4)、D=滚转(1)、E=相位(s/arc/nearest_i/age)。"
         "实测:s=0.517263, arc=4068.65mm, 近点 #120, 帧龄 0.047s。")

# ── 04 引擎五段 ────────────────────────────────────────────────────────────
s = page("引擎：编码 → 投影 → 度量 → 导航 → 反馈", "流水线", 4)
stages = ["编码", "投影", "度量", "导航", "反馈"]
for i, st in enumerate(stages):
    x = Inches(0.9) + Inches(2.42) * i
    sp = rect(s, x, Inches(2.1), Inches(2.15), Inches(0.95), ACC if i == 2 else BAND,
              shape=MSO_SHAPE.CHEVRON)
    tf = sp.text_frame
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = st
    r.font.size = Pt(15)
    r.font.bold = True
    r.font.color.rgb = WHITE if i == 2 else INK
    r.font.name = FONT
    _ea(r)
text(s, Inches(0.95), Inches(3.3), Inches(11.3), Inches(0.4),
     "状态 → 流形坐标 → 度量张量 → 势场梯度 → 一步演化（默认过阻尼 = 旧行为，零回归）", 11.5, MUT)
table(s, Inches(0.9), Inches(3.95), Inches(11.5), [2.0, 9.5], [
    ["可用流形", "euclidean · sphere · torus · so3 · se3 · su2 · se3_layers · latent_flat"],
    ["引擎自检", "7 个流形 + 内稳态 4 项，全通过"],
    ["惯性项", "默认关（过阻尼一阶）；开 M=3.643 时 Δx 由 2.98e-3 → 8.17e-6"],
    ["接入现实", "标定层 n_calib_mani 每次执行回读 M / dt / 限值 / 档位"],
], row_h=0.52)
notes(s, "自检命令: PYTHONPATH=src ./gui-venv311/bin/python -m lerobot.manifold.manifold_engine --selftest。"
         "日志里可见『可用流形 8/10: euclidean · sphere · torus · so3 · se3 · su2 · se3_layers · latent_flat』。"
         "Δx 对比取自 n_calib_mani 节点 2026-11-20 07:2x 的真实一行输出。")

# ── 05 黎曼度规 ────────────────────────────────────────────────────────────
s = page("黎曼度规：方向由几何定，幅度由限值定", "几何层", 5)
text(s, Inches(0.9), Inches(1.95), Inches(5.6), Inches(2.2),
     "同一个“偏 3mm”，在径向是事故，在轴向只是没插到底。\n"
     "所以度规不是单位矩阵，而是按公差各向异性的：", 13.5, MUT, spacing=1.5)
table(s, Inches(0.9), Inches(3.15), Inches(5.6), [2.4, 1.6, 1.6], [
    ["方向", "公差", "含义"],
    ["径向", "0.3 mm", "不刮金手指"],
    ["轴向", "6.0 mm", "允许推进余量"],
], row_h=0.42)
c = rect(s, Inches(6.95), Inches(1.95), Inches(5.48), Inches(4.35), BAND, LINE)
text(s, Inches(7.25), Inches(2.2), Inches(4.9), Inches(0.3), "两条式子", 10, ACC, True)
text(s, Inches(7.25), Inches(2.55), Inches(4.95), Inches(1.2),
     "V  =  ½ · eᵀ G e\nτ  =  −α · M⁻¹ ∇V", 17, INK, font=MONO, spacing=1.7)
text(s, Inches(7.25), Inches(4.0), Inches(4.9), Inches(2.1),
     "G 正定 ⇒ 势能单调下降；\n"
     "M⁻¹ 把修正力放大在“敏感轴”，压小在“宽容轴”；\n"
     "Δ 与限值取交集 ⇒ 输出永远在物理可达范围内。", 12, MUT, spacing=1.55)
notes(s, "公差真源: config/calib/zmax_manifold.json + 专利文本里的径向/轴向分割。"
         "实测对照:4mm 轴向偏离(公差 6mm)仍判通道内;同量径向立刻越界要求修正。")

# ── 06 相空间安全通道 ──────────────────────────────────────────────────────
s = page("相空间安全通道：位置管形 + 速度管厚", "物理层 · 本次新增", 6)
text(s, Inches(0.9), Inches(1.95), Inches(11.4), Inches(0.6),
     "相空间 = 切丛 (q, q̇)。记忆轨迹是其中一条中心线；通道是围绕它的一条椭圆管道。", 13.5, MUT)
rect(s, Inches(0.9), Inches(2.62), Inches(5.55), Inches(3.55), BAND, LINE)
text(s, Inches(1.2), Inches(2.86), Inches(4.9), Inches(0.3), "无量纲偏离", 10, ACC, True)
text(s, Inches(1.2), Inches(3.18), Inches(5.0), Inches(0.5), "z = [ e_pose/tol ; e_vel/vlim ]", 13, INK, font=MONO)
text(s, Inches(1.2), Inches(3.75), Inches(5.0), Inches(2.2),
     "V = ½‖z‖²      V=1 正好压在公差上\n"
     "τ = −α · τ_lim ⊙ (z_pos + z_vel)\n"
     "α_eff = min(α, λ/2) ⇒ V̇ ≤ −λV", 12.5, INK, font=MONO, spacing=1.8)
rect(s, Inches(6.85), Inches(2.62), Inches(5.58), Inches(3.55), BAND, LINE)
text(s, Inches(7.15), Inches(2.86), Inches(4.9), Inches(0.3), "四条工程口径", 10, ACC, True)
bullets(s, Inches(7.15), Inches(3.2), Inches(5.0), Inches(2.8), [
    "度规定方向，τ_lim 定幅度 —— 输出恒在限值内",
    "S³ 误差走李代数 log，避开欧拉角奇异",
    "S¹ 相位差 > 15° ⇒ 判定记忆断裂，注入置 0",
    "α_eff 由李雅普诺夫反解，保证能量单调下降",
], size=11.5, gap=7)
text(s, Inches(0.9), Inches(6.32), Inches(11.4), Inches(0.4),
     "ε = 0.30 · α = 1.5 · λ = 2.0 · 载荷自适应 √(m/m_ref)（0.1kg ↔ 1.6T 级）", 10.5, MUT, font=MONO)
notes(s, "半宽就是公差:径向 0.3mm、轴向 6mm;速度纤维横向 50mm/s、轴向 300mm/s。"
         "载荷变化只动速度度规:重料加大阻尼,轻料减小。")

# ── 07 为什么必须 ──────────────────────────────────────────────────────────
s = page("为什么必须：人为轨迹在强跨相位线", "动机", 7)
left = [
    ("启动", "电机猛烈注入动能，克服惯性"),
    ("减速", "电机刹车，把动能抽走"),
    ("上升 / 下降", "重力势能一进一出"),
]
for i, (k, v) in enumerate(left):
    y = Inches(2.0) + Inches(0.95) * i
    rect(s, Inches(0.9), y, Inches(0.06), Inches(0.7), ACC, shape=MSO_SHAPE.RECTANGLE)
    text(s, Inches(1.15), y + Inches(0.02), Inches(2.0), Inches(0.35), k, 13.5, INK, True)
    text(s, Inches(1.15), y + Inches(0.36), Inches(5.3), Inches(0.35), v, 11.5, MUT)
text(s, Inches(0.9), Inches(5.0), Inches(6.3), Inches(1.4),
     "自然系统待在等能面上；受控轨迹横穿无数等能面。\n"
     "代价是两种：撞墙（奇异/限位）与溢出（高动量遇碰撞）。", 12.5, MUT, spacing=1.5)
rect(s, Inches(7.35), Inches(1.95), Inches(5.08), Inches(4.5), BAND, LINE)
text(s, Inches(7.65), Inches(2.2), Inches(4.4), Inches(0.3), "所以通道要管两件事", 10, ACC, True)
text(s, Inches(7.65), Inches(2.55), Inches(4.5), Inches(3.6),
     "① 位置\n   偏离就被自然梯度拉回\n\n"
     "② 能量\n   偏离速率被 λ 限住，\n   不允许“越拉越快”\n\n"
     "一句话：允许跨，但只允许\n在最省力、最安全的曲率上跨。", 12.5, INK, spacing=1.6)
notes(s, "这页是给评审的物理解释:电机做功是既有事实,问题不是要不要跨,而是跨的时候有没有边界。")

# ── 08 通道自检 ────────────────────────────────────────────────────────────
s = page("实测一：通道自检 6 例 + 24 点横扫", "证据", 8)
table(s, Inches(0.9), Inches(1.98), Inches(11.5), [4.2, 7.3], [
    ["用例", "结果（实跑输出）"],
    ["通道内偏差", "V < ε ⇒ τ = 0，零注入"],
    ["4 mm 轴向偏离", "仍判通道内（轴向公差 6 mm）"],
    ["同量径向偏离", "越界 ⇒ 触发饱和修正"],
    ["S¹ 相位不符", "门控关断，τ = 0（不乱扯）"],
    ["仅单轴旋转误差", "李代数误差只落在该轴"],
    ["24 点正弦横扫", "V̇ ≤ 0 全程成立（单调，无过冲）"],
], row_h=0.5)
text(s, Inches(0.9), Inches(5.5), Inches(11.4), Inches(1.1),
     "复现命令：./gui-venv311/bin/python src/lerobot/manifold/phase_corridor.py\n"
     "自检同时打印各用例的 V / τ / gate / clipped，数值可直接截图取证。", 11, MUT, font=MONO, spacing=1.5)
notes(s, "6 个用例 + 24 点横扫都在同一个 __main__ 里,跑一次全出。"
         "注意“4mm 轴向仍判通道内、同量径向立刻越界”这一对,就是各向异性生效的直接证据。")

# ── 09 真机接入 ────────────────────────────────────────────────────────────
s = page("实测二：真机状态进通道，节点真跑", "证据", 9)
table(s, Inches(0.9), Inches(1.98), Inches(7.3), [2.3, 2.1, 1.6], [
    ["真值字段", "实测值", "帧龄"],
    ["位置 / mm", "344.9 · 315.4 · 254.4", "0.047 s"],
    ["轴 S²", "0.9744 · 0.1592 · −0.1585", "偏差 40.45°"],
    ["四元数 S³", "0.106 · −0.9235 · −0.014 · −0.368", "—"],
    ["相位 s", "0.517263（arc 4068.65）", "近点 #120"],
], row_h=0.55)
rect(s, Inches(8.45), Inches(1.98), Inches(3.98), Inches(2.9), BAND, LINE)
text(s, Inches(8.72), Inches(2.2), Inches(3.4), Inches(0.3), "画布节点耗时", 10, ACC, True)
text(s, Inches(8.72), Inches(2.5), Inches(3.5), Inches(1.4),
     "SE(3) 记忆   56.9 ms\n相空间通道   8.8 ms", 13, INK, font=MONO, spacing=1.8)
text(s, Inches(8.72), Inches(3.9), Inches(3.4), Inches(0.8),
     "均为完整工程 step 的实测 ms\n（含真值读取与 JSONL 尾读）", 10, MUT)
text(s, Inches(8.45), Inches(5.05), Inches(4.0), Inches(1.5),
     "通道判定：gate=True · inside=True\nV_phase=0.000 · τ=[0,0,0,0,0,0]\n"
     "（臂静止 ⇒ 偏离为零，符合预期）", 10.5, INK, font=MONO, spacing=1.6)
notes(s, "真值来自 zmax-se3-geom(5Hz, rokae SDK endInRef 直采)。"
         "节点耗时是在真实 Project.step 路径里测的,不是单元测试桩。")

# ── 10 画布接线 ────────────────────────────────────────────────────────────
s = page("落地：画布上看得见、点得开", "工程", 10)
table(s, Inches(0.9), Inches(1.98), Inches(11.5), [2.6, 3.5, 3.3, 2.1], [
    ["节点", "输入", "输出", "口径"],
    ["🔷 SE(3)×S1 记忆流形", "—", "A–E 16 维", "5 Hz 只读"],
    ["🌀 相空间安全通道", "流形引擎 · SE(3)", "V / τ / 门控", "只出判据"],
    ["连线 3 条", "引擎 → 通道 · 记忆 → 通道 · 通道 → 工作安全", "—", "L4 层内"],
], row_h=0.58)
text(s, Inches(0.9), Inches(4.3), Inches(11.4), Inches(1.6),
     "规模：节点 94 → 96 · 连线 222 → 225 · 全量执行 81 个可执行节点\n"
     "契约：每个节点一份 n_<slug>.py（端口 / IMPL_KEY / compute），缺了就会“直通不执行”", 12, MUT, spacing=1.6)
text(s, Inches(0.9), Inches(5.55), Inches(11.4), Inches(0.9),
     "打开方式：控制台载入「状态空间」工程 → L4 行带最右侧两颗节点 → 双击看日志与端口值。", 12.5, INK)
notes(s, "节点 id: ss_se3_state / ss_phase_corr;契约文件 n_8815.py / n_phase.py(slug 由节点名推导)。"
         "踩过的坑:常驻循环进程未 import library 时恒报“实现未注册”,所以 compute() 里做了自注册。")

# ── 11 分层验收 ────────────────────────────────────────────────────────────
s = page("实测三：L1–L5 分层全通", "验收", 11)
table(s, Inches(0.9), Inches(2.0), Inches(11.5), [1.2, 4.4, 1.4, 4.5], [
    ["层", "验什么", "结果", "口径"],
    ["L1", "机器人接口（位姿真值）", "OK", "只读，零下行"],
    ["L2", "AR 渲染帧 → YOLO → 2D/3D", "6/6 帧", "conf 0.3 · imgsz 640"],
    ["L3", "场景理解（VLM 结构化）", "OK", "返回结构化 JSON"],
    ["L4", "意图 → 动作序列", "OK", "2 个技能 token"],
    ["L5", "人机同步 / 元任务", "OK", "元任务表 8 项"],
], row_h=0.5)
text(s, Inches(0.9), Inches(5.45), Inches(11.4), Inches(1.0),
     "报告：reports/layer_e2e_20261120_072522.{json,md}\n"
     "首轮 3 帧曾报 0/3（目标不在视野的那几帧），加到 6 帧即 6/6 —— 是取样时机，不是链路断。", 11, MUT, spacing=1.55)
notes(s, "分层脚本会真的调 YOLO 与 VLM,不是 mock。L2 首轮 0/3 的记录我保留在会话里,没有抹掉。")

# ── 12 边界与下一步 ────────────────────────────────────────────────────────
s = page("边界与下一步", "收口", 12)
bullets(s, Inches(0.9), Inches(2.0), Inches(5.5), Inches(4.2), [
    "只读：通道只产判据与 τ_safe，真动仍须 8793 授权",
    "不外推：速度取自 5 Hz 记忆流差，静止即零",
    "不夸大：对成功率是否有提升，尚无同口径对照 ⇒ 不进默认档",
], size=12.5, gap=10)
rect(s, Inches(6.85), Inches(1.95), Inches(5.58), Inches(4.35), BAND, LINE)
text(s, Inches(7.15), Inches(2.2), Inches(4.9), Inches(0.3), "下一步（按证据推进）", 10, ACC, True)
text(s, Inches(7.15), Inches(2.55), Inches(4.95), Inches(3.5),
     "① 同口径 A/B：带 / 不带通道各 30 次插拔，\n"
     "   比成功率、残差、峰值速度\n\n"
     "② 速度纤维换真源：从关节速度直取，\n"
     "   替掉差分\n\n"
     "③ 重料标定：0.1kg 与 0.2kg 两档各测一次\n"
     "   M_vel 自适应系数", 12, INK, spacing=1.6)
notes(s, "第三步做完才谈“进默认档”。在没有 A/B 之前,这层只作为 L4 判据存在。")

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "reports", "流形引擎方案_%s.pptx" % VER)
os.makedirs(os.path.dirname(out), exist_ok=True)
prs.save(out)
print("saved:", out, "slides:", len(prs.slides.__iter__.__self__._sldIdLst))
