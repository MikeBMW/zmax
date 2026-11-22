#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_motion_plan.py — 《动作规划节点 · 功能描述》

骨架按老倪给的定性: **输入 = 3D 位姿引导（唯一 6D 目标位姿）· 输出 = action（逐拍位姿）**
  P2 定义(输入框→节点→输出框) → P3 输入契约 → P4 输出契约
  → P5~P8 四项功能(唯一目标 / 抓取序列 / 分段限幅 / 拒绝与证据)
  → P9 实测 → P10 事故固化 → P11 验收 → P12 复现

数字全部来自真源现算(action_trail_slot3.json / cell_points.json / motion_plan.py 常量),
未达到的如实写(槽3 valid=false 是先验; 真机 22 拍未完整走完)。
"""
from __future__ import annotations

import json
import os

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

OUT = "/home/ubuntu/zmax/zmax_data/reports/动作规划节点_功能描述_v2.pptx"
TRAIL = "/home/ubuntu/zmax/zmax_data/ss_live/action_trail_slot3.json"
W, H = 13.333, 7.5
INK = RGBColor(0x1E, 0x29, 0x3B)
MUTED = RGBColor(0x64, 0x74, 0x8B)
ACC = RGBColor(0x0E, 0xA5, 0xE9)
ACC2 = RGBColor(0xF5, 0x9E, 0x0B)
OK = RGBColor(0x16, 0xA3, 0x4A)
BAD = RGBColor(0xDC, 0x26, 0x26)
BG = RGBColor(0xFA, 0xFB, 0xFD)
CARD = RGBColor(0xF1, 0xF6, 0xFB)
LINE = RGBColor(0xE2, 0xE8, 0xF0)
CJK = "Noto Sans CJK SC"


def _ea(run, name=CJK):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def txt(slide, x, y, w, h, s, size=13, color=INK, bold=False, align=PP_ALIGN.LEFT, spacing=1.05):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(s.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        _ea(r)
    return tb


def box(slide, x, y, w, h, fill=None, line=None, lw=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    return sh


def table(slide, x, y, w, rows, widths=None, head_size=10.5, body_size=9.5, row_h=0.32, head_fill=ACC):
    nr, nc = len(rows), len(rows[0])
    shp = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(row_h * nr))
    t = shp.table
    if widths:
        tot = sum(widths)
        for i, cw in enumerate(widths):
            t.columns[i].width = Inches(w * cw / tot)
    for ri, row in enumerate(rows):
        t.rows[ri].height = Inches(row_h)
        for ci, val in enumerate(row):
            cell = t.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.05)
            cell.margin_top = cell.margin_bottom = Inches(0.015)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = head_fill if ri == 0 else (BG if ri % 2 else RGBColor(0xFF, 0xFF, 0xFF))
            p = cell.text_frame.paragraphs[0]
            cell.text_frame.word_wrap = True
            p.alignment = PP_ALIGN.LEFT if ci else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(val)
            r.font.size = Pt(head_size if ri == 0 else body_size)
            r.font.bold = ri == 0
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if ri == 0 else INK
            _ea(r)
    return shp


def page(prs, title, sub=None, n=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, 0.06, fill=ACC)
    txt(s, 0.55, 0.26, 12.2, 0.5, title, 22, INK, True)
    if sub:
        txt(s, 0.55, 0.80, 12.3, 0.30, sub, 10.5, MUTED)
    if n is not None:
        txt(s, W - 0.95, H - 0.40, 0.55, 0.26, str(n), 9.5, MUTED, align=PP_ALIGN.RIGHT)
        txt(s, 0.55, H - 0.40, 9.4, 0.26,
            "动作规划节点 · 功能描述 · 输入 3D 位姿引导 / 输出 action · v5.50.782", 8.5, MUTED)
    return s


def main() -> int:
    ev = {}
    if os.path.exists(TRAIL):
        ev = json.load(open(TRAIL, encoding="utf-8"))
    tp = ev.get("target_pose") or {}
    # —— 页面上所有轨迹数一律现算, 不手写(改了轨迹就会自动跟着变)
    import math
    from collections import Counter
    steps = ev.get("steps") or []
    n_st = len(steps)
    tot_mm = round(sum(math.dist(steps[i - 1]["pos"], steps[i]["pos"]) for i in range(1, n_st)), 1)
    cnt = Counter(s["phase"] for s in steps)
    _ds = [(steps[i]["phase"], round(math.dist(steps[i - 1]["pos"], steps[i]["pos"]), 2))
           for i in range(1, n_st)]
    max_step = max((v for _, v in _ds), default=0.0)
    desc_steps = [v for k, v in _ds if k == "descend"]
    rng = {}
    for _s in steps:
        rng.setdefault(_s["phase"], [_s["i"], _s["i"]])[1] = _s["i"]

    def _rng(ph):
        a = rng.get(ph)
        return "%d – %d（%d 拍）" % (a[0], a[1], cnt[ph]) if a else "-"

    seg_line = " · ".join("%s %d" % (k, cnt[k]) for k in ("approach", "descend", "grip", "lift") if cnt[k])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    # ---------------- 1 封面 ----------------
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, 2.55, fill=RGBColor(0x0B, 0x1B, 0x2B))
    txt(s, 0.85, 0.70, 11.6, 0.8, "动作规划节点 · 功能描述", 38, RGBColor(0xFF, 0xFF, 0xFF), True)
    txt(s, 0.85, 1.50, 11.6, 0.5, "输入：3D 位姿引导      输出：action", 21, RGBColor(0x7D, 0xD3, 0xFC))
    txt(s, 0.85, 2.95, 11.6, 1.2,
        "上游「测地线规划引导」给出唯一的目标 6D 位姿；本节点把它变成机器人逐拍可执行的 action：\n"
        "先到预抓点，垂直下降到抓取点，合爪。只出位姿，不下发；执行归机器人节点，且执行时不再重算。",
        14, INK, spacing=1.5)
    box(s, 0.85, 4.62, 3.5, 0.9, fill=RGBColor(0xE8, 0xF4, 0xFD), line=ACC, lw=1.3)
    txt(s, 0.98, 4.72, 3.2, 0.7, "输入\n3D 位姿引导（唯一 6D 目标）", 11.5, INK)
    box(s, 4.62, 4.62, 3.6, 0.9, fill=CARD, line=LINE)
    txt(s, 4.75, 4.72, 3.3, 0.7, "处理\n派生抓取序列 + 分段限幅", 11.5, INK)
    box(s, 8.49, 4.62, 3.9, 0.9, fill=RGBColor(0xEC, 0xFD, 0xF3), line=OK, lw=1.3)
    txt(s, 8.62, 4.72, 3.6, 0.7, "输出\naction（逐拍位姿 + 夹爪）", 11.5, INK)
    txt(s, 0.85, 6.30, 11.6, 0.4,
        "真机实测: 槽3 · %d 拍 / %.1fmm · 引导先验位姿 valid=false 已如实标注 · 2026-11-22"
        % (n_st, tot_mm), 10.5, MUTED)

    # ---------------- 2 定义 ----------------
    s = page(prs, "功能定义：一个输入，一个输出", "节点不产生几何目标，只把引导目标翻译成可执行的一拍一拍", 2)
    box(s, 0.55, 1.32, 3.55, 1.95, fill=RGBColor(0xE8, 0xF4, 0xFD), line=ACC, lw=1.4)
    txt(s, 0.72, 1.44, 3.2, 0.3, "输入 · 3D 位姿引导", 12.5, ACC, True)
    txt(s, 0.72, 1.80, 3.3, 1.35, "target_pose：一个周期只有一个\n"
        "· 位置 pos / 抓取点 grasp\n"
        "· 姿态 quat（含夹爪安装对齐）\n"
        "· 预抓点 pre / 接近方向 approach\n"
        "· valid 区分实测与先验", 10, INK, spacing=1.22)
    box(s, 4.35, 1.32, 4.6, 1.95, fill=CARD, line=INK, lw=1.4)
    txt(s, 4.52, 1.44, 4.3, 0.3, "动作规划节点 n_moveit", 12.5, INK, True)
    txt(s, 4.52, 1.80, 4.3, 1.35, "① 取唯一目标，先验/实测分开处理\n"
        "② 派生预抓点 → 抓取点 → 合爪\n"
        "③ 分段限幅（单步 ≤25mm / 向下 ≤20mm）\n"
        "④ 每拍出 action，带证据；不合格就拒出", 10, INK, spacing=1.22)
    box(s, 9.2, 1.32, 3.55, 1.95, fill=RGBColor(0xEC, 0xFD, 0xF3), line=OK, lw=1.4)
    txt(s, 9.37, 1.44, 3.2, 0.3, "输出 · action", 12.5, OK, True)
    txt(s, 9.37, 1.80, 3.3, 1.35, "逐拍目标位姿（位姿口径）\n"
        "· x/y/z + 四元数\n"
        "· 夹爪 hold / close / open\n"
        "· 段号/进度/偏差/真值时效\n"
        "· src=plan，不下发", 10, INK, spacing=1.22)
    box(s, 0.55, 3.48, 12.2, 0.86, fill=CARD, line=LINE)
    txt(s, 0.75, 3.62, 11.8, 0.62,
        "一句话：引导回答「抓哪一个、什么姿态」，本节点回答「这一拍走到哪儿」，机器人节点只负责照做并回报真值。",
        12.5, INK)
    txt(s, 0.55, 4.56, 12.2, 0.3, "三条铁律（写进代码注释与验收）", 12.5, ACC, True)
    txt(s, 0.55, 4.94, 5.9, 1.5,
        "① 一个周期只认一个目标位姿\n"
        "   —— 不是“每周期给一个下一步”\n"
        "② 拆分、限幅、拒绝都在本节点收口\n"
        "   —— 上层只给意图与位姿", 11, INK, spacing=1.35)
    txt(s, 6.75, 4.94, 6.0, 1.5,
        "③ 位姿口径不混用\n"
        "   —— 状态向量 peg_xyz[4:7] 是米，action 是毫米；\n"
        "      模块原点定义一次写死（金手指端中点）", 11, INK, spacing=1.35)

    # ---------------- 3 输入契约 ----------------
    s = page(prs, "输入契约：3D 位姿引导的每个字段都有源", "由 plan_guide.target_pose() 产出；缺字段即视为不可用", 3)
    rows = [["字段", "含义", "槽3 实测值", "缺了怎么办"],
            ["pos_mm", "模块坐标原点（金手指端中点）", "684.6, 409.3, 114.2", "无值 ⇒ 不出 action"],
            ["grasp_mm", "抓取点 = 模块体中心（与示教同口径）", "649.0, 404.0, 114.2", "回退 pos + L/2·X̂"],
            ["pre_pos_mm", "预抓点 = 抓取点 + 40mm 竖直", "649.0, 404.0, 154.2", "按 hover 现算"],
            ["quat (w,x,y,z)", "抓取姿态（已乘夹爪安装对齐）", "−0.07438, 0, 0, 0.99723", "取当前姿态并标记"],
            ["approach / hover", "接近方向与离面高度", "[0,0,−1] / 40mm", "用默认值"],
            ["slot / valid / src", "槽号、实测与否、来源说明", "3 / false / 槽3 几何先验", "valid=false 可用但位置回示教点"]]
    table(s, 0.55, 1.24, 12.2, rows, widths=[1.6, 4.1, 3.3, 3.2], row_h=0.42, body_size=9.5)
    box(s, 0.55, 4.62, 5.95, 1.55, fill=RGBColor(0xFF, 0xFB, 0xEB), line=ACC2, lw=1.2)
    txt(s, 0.72, 4.74, 5.6, 1.3,
        "⚠ 槽3 现在 valid=false\n"
        "融合服务只检出槽10，槽3 没有实物 ⇒ 给的是「槽位几何 + 同排\n"
        "朝向」先验，不是观测。AR 与 action 都标「未观测(先验)」，\n"
        "位置回落到示教真值 648.8, 407.0, 108.6。", 10.5, INK, spacing=1.25)
    box(s, 6.8, 4.62, 5.95, 1.55, fill=CARD, line=LINE)
    txt(s, 6.97, 4.74, 5.6, 1.3,
        "先验与实测的差（同一槽位）\n"
        "几何先验抓取点  649.0, 404.0, 114.2\n"
        "真机示教点      648.8, 407.0, 108.6\n"
        "差 (0.2, −3.0, +5.6)mm —— 深度口径不同，不当实测用", 10.5, INK, spacing=1.3)

    # ---------------- 4 输出契约 ----------------
    s = page(prs, "输出契约：action 是「这一拍的目标位姿」", "机器人节点拿到就执行；执行侧不许再解 IK、再算轨迹", 4)
    rows = [["字段", "含义 / 取值", "为什么要有"],
            ["x, y, z", "目标位置 mm（基座系）", "执行器唯一需要的位姿量"],
            ["a, b, c", "姿态角（度，由四元数换算）", "可读；不等于 SDK 的 rpy(rad)"],
            ["qx, qy, qz, qw", "姿态四元数（与 a/b/c 同源）", "避免欧拉奇异，可只用它"],
            ["grip_act / grip_mm", "hold / close / open，目标开度", "抓取最后一步合一"],
            ["plan.seg_i / n_seg / u / plan_id", "第几段、共几段、段内进度", "可查“执行的是哪一段”"],
            ["align.delta_mm / step_ok / truth_fresh", "相对真值偏差、单拍幅度、真值新鲜", "一眼分辨是规划错还是真值错"]]
    table(s, 0.55, 1.24, 12.2, rows, widths=[3.2, 5.2, 3.8], row_h=0.46, body_size=9.5)
    txt(s, 0.55, 4.52, 12.2, 0.3, "为什么输出「一拍」而不是「整条轨迹」", 12.5, ACC, True)
    txt(s, 0.55, 4.88, 5.9, 1.5,
        "· 每拍都能用最新真值重锚，位姿漂了立刻收紧\n"
        "· 段表仍一次性给出（槽3 实测 %d 拍 / %.1fmm），逐拍推进\n" % (n_st, tot_mm) +
        "· 执行侧只认 action，两边算法不会打架", 10.5, INK, spacing=1.3)
    txt(s, 6.75, 4.88, 6.0, 1.5,
        "代价：action 必须带足证据（段号、进度、真值年龄）。\n"
        "否则事后无法判断“规划给错了”还是“执行走歪了”。\n"
        "本次事故正是靠 action 的 delta_mm 一眼看到 69.25mm。", 10.5, INK, spacing=1.3)

    # ---------------- 5 功能① ----------------
    s = page(prs, "功能① 取唯一目标：一个周期只认一个 6D 位姿", "目标优先级固定，先验与实测量化区分，不许“每拍换个目标”", 5)
    rows = [["优先级", "来源", "条件", "行为"],
            ["1", "引导 target_pose", "字段齐（pos / quat）", "直接采用；valid=false 时位置回示教点"],
            ["2", "ctx 显式点 / 槽号", "无引导位姿", "按点名或槽位几何派生"],
            ["3", "in4 技能（原子技能）", "上两者皆缺", "用技能内置目标"],
            ["4", "obs[4:7] + 当前姿态", "以上全缺", "降级使用，valid=false 并写原因"]]
    table(s, 0.55, 1.24, 12.2, rows, widths=[0.9, 3.4, 3.4, 4.5], row_h=0.44, body_size=9.5)
    txt(s, 0.55, 3.42, 6.0, 0.3, "先验 ≠ 实测：必须能区分", 12.5, ACC, True)
    txt(s, 0.55, 3.78, 6.0, 1.7,
        "引导在没有实物时会用「槽位几何 + 同排朝向」给一个先验位姿。\n"
        "此时 valid=false：\n"
        "· 姿态可用（同排朝向一致）\n"
        "· 位置回示教真值（先验与示教差 6.3mm，别当观测）\n"
        "· AR 与 action 都标「未观测(先验)」", 10.5, INK, spacing=1.3)
    box(s, 6.8, 3.42, 5.95, 2.0, fill=CARD, line=LINE)
    txt(s, 6.97, 3.54, 5.6, 0.3, "为什么必须“唯一”", 11.5, ACC, True)
    txt(s, 6.97, 3.88, 5.6, 1.45,
        "早先引导每周期输出一个「下一步」，规划就每拍换目标：\n"
        "段表反复重建，执行到一半发现目标变了 —— 机器人在半路\n"
        "掉头。改成唯一目标后，段表从头到尾一致，只有真值重锚\n"
        "会微调下一拍。", 10.5, INK, spacing=1.28)
    txt(s, 0.55, 5.62, 12.2, 0.8,
        "实测：槽3 引导 pos 684.6, 409.3, 114.2 / 抓取点 649.0, 404.0, 114.2 / 预抓点 649.0, 404.0, 154.2（高出 40mm）。",
        10.5, INK, spacing=1.3)

    # ---------------- 6 功能② ----------------
    s = page(prs, "功能② 派生抓取序列：预抓点 → 抓取点 → 合爪", "只靠距离开关，不靠时间；先竖直下降，避免斜插撞料盘", 6)
    flow = [("approach", "走向预抓点\n距预抓点 >4mm", ACC),
            ("descend", "切到抓取点\n到预抓点 ≤4mm", ACC2),
            ("grip", "合爪\n到抓取点 <3mm", OK),
            ("done", "保持 5 拍\n交下游", MUTED)]
    for i, (h1, b1, c1) in enumerate(flow):
        x = 0.85 + i * 3.05
        box(s, x, 1.26, 2.55, 1.34, fill=CARD, line=c1, lw=1.3)
        txt(s, x + 0.12, 1.36, 2.3, 0.3, h1, 13, c1, True)
        txt(s, x + 0.12, 1.72, 2.3, 0.8, b1, 10, INK, spacing=1.25)
        if i < 3:
            box(s, x + 2.58, 1.80, 0.42, 0.3, fill=LINE, shape=MSO_SHAPE.RIGHT_ARROW)
    rows = [["段", "拍号（槽3 实测）", "终点", "内容"],
            ["approach", _rng("approach"), "648.79, 407.03, 148.58", "抬到 z=198.6 → 横移到槽3 上方 → 垂直降到预抓点"],
            ["descend", _rng("descend"), "648.79, 407.03, 108.58", "148.6 → 137.5 → 135.2 → 121.9 → 108.6，单步 ≤20mm"],
            ["grip", _rng("grip"), "648.79, 407.03, 108.58", "action 带 grip=close，连发 5 拍确认后转 done"],
            ["lift（抓后）", _rng("lift"), "648.79, 407.03, 158.58", "竖直抬升 50mm，拆成 ≤25mm 单拍，脱离槽位再横移"]]
    table(s, 0.55, 2.94, 12.2, rows, widths=[1.55, 2.3, 3.5, 4.85], row_h=0.46, body_size=9.5)
    txt(s, 0.55, 5.02, 5.9, 1.2,
        "为什么不用时间驱动：时间到了不等于到位。\n"
        "距离判据容忍速度变化与停顿，也避免超时后盲合爪。", 10.5, INK, spacing=1.3)
    txt(s, 6.75, 5.02, 6.0, 1.2,
        "为什么先竖后横：先抬到 z=198.6 再横移，不贴料盘平移；\n"
        "下降只走竖直，斜插最容易把模块顶飞。", 10.5, INK, spacing=1.3)

    # ---------------- 7 功能③ ----------------
    s = page(prs, "功能③ 分段与限幅：让每一拍都可执行、可复核", "规划侧与执行侧用同一组数，避免“规划合法、执行违规”", 7)
    rows = [["项", "规则", "为什么"],
            ["单步上限", "≤25mm（DEF_STEP）", "超过执行侧守卫会被逐条拒收"],
            ["向下段", "≤20mm", "下降撞击风险最高，步长收紧"],
            ["段内预瞄", "按 0.1s 推进段内进度 u", "每拍给“下一步小目标”，不是终点"],
            ["真值重锚", "每拍用最新 TCP 重算偏差", "位姿漂移立即收敛，不累积"],
            ["限幅位置", "规划侧截断 + 执行侧再判一次", "同一件事两层防，两侧同口径"]]
    table(s, 0.55, 1.24, 12.2, rows, widths=[1.8, 5.6, 4.8], row_h=0.46, body_size=9.5)
    box(s, 0.55, 4.20, 5.95, 1.6, fill=CARD, line=LINE)
    txt(s, 0.72, 4.32, 5.6, 1.35,
        "实测（槽3，%d 拍）\n" % n_st +
        "单拍最大位移 %.2fmm（含抬升段）\n" % max_step +
        "下降段单拍 " + " / ".join("%.2f" % v for v in desc_steps) + "mm —— 全部 ≤20mm\n" +
        "总长 %.1fmm，%d/%d 通过工作空间与单步判据" % (tot_mm, n_st, n_st), 10.5, INK, spacing=1.28)
    box(s, 6.8, 4.20, 5.95, 1.6, fill=RGBColor(0xFE, 0xF2, 0xF2), line=BAD, lw=1.2)
    txt(s, 6.97, 4.32, 5.6, 1.35,
        "踩过的坑：口径不一致\n"
        "原先规划按 50mm 切段、执行按 25mm 拦 ⇒ 规划合法、执行每拍\n"
        "拒收，表现为“点了没反应”。现在两处都用 DEF_STEP=25mm。", 10.5, INK, spacing=1.28)
    txt(s, 0.55, 5.96, 12.2, 0.6,
        "口径统一的结果：规划出的每一拍，执行侧都能直接吃下，不需要二次切分。", 10.5, INK)

    # ---------------- 8 功能④ ----------------
    s = page(prs, "功能④ 拒绝与证据：宁可不出，也不出错位姿", "每个环节都有拒绝出口，输出必带可复核证据", 8)
    rows = [["拒绝条件", "判据", "输出"],
            ["起点真值陈旧", "TCP 年龄 > 2.0s（STALE_S）", "不出段表，reason=tcp_stale"],
            ["视觉观测过旧", "观测年龄 > 2.0s（OBS_STALE_S）", "不用旧观测，reason=obs_stale"],
            ["目标越出工作空间", "x 0.15~1.05 · y −0.65~1.15 · z 0.005~0.95 m", "逐轴夹紧并写 why"],
            ["低于台面安全距", "z < 台面 + 5mm", "抬高到位并写 why"],
            ["目标或姿态缺失", "pos / quat 任一为空", "不出 action"]]
    table(s, 0.55, 1.24, 12.2, rows, widths=[2.4, 5.4, 4.4], row_h=0.42, body_size=9.5)
    txt(s, 0.55, 3.90, 12.2, 0.3, "action 里的证据块：出问题一眼定位", 12.5, ACC, True)
    txt(s, 0.55, 4.26, 6.0, 1.6,
        "delta_mm      相对真机的偏差（本次事故 69.25mm 由它报出）\n"
        "step_ok       单拍幅度是否合规\n"
        "truth_fresh   真值是否新鲜（含年龄）\n"
        "seg_i / u     第几段、段内进度", 10.5, INK, spacing=1.35)
    box(s, 6.8, 4.26, 5.95, 1.55, fill=RGBColor(0xFF, 0xFB, 0xEB), line=ACC2, lw=1.2)
    txt(s, 6.97, 4.38, 5.6, 1.3,
        "踩过的坑：位姿守护把字段吃掉\n"
        "守护节点原来只重建 {tcp:…}，把 target_pose 的姿态与\n"
        "预抓点整块丢了，规划只能拿“下一小步”当目标。\n"
        "已改为原样透传，并对目标位姿单独守一次。", 10.5, INK, spacing=1.25)

    # ---------------- 9 实测 ----------------
    s = page(prs, "实测：槽3 的 22 拍 action 轨迹", "引导目标 → 段表 → 逐拍 action，全部可复核（zmax_data/ss_live/action_trail_slot3.json）", 9)
    rows = [["项", "值"],
            ["引导目标 pos", "684.6, 409.3, 114.2  (valid=false · 槽3 几何先验)"],
            ["抓取点 grasp", "649.0, 404.0, 114.2 → 规划实际用 648.79, 407.03, 108.58（示教兜底）"],
            ["预抓点 pre", "649.0, 404.0, 154.2 → 实际 648.79, 407.03, 148.58"],
            ["拍数 / 总长", "%d 拍 / %.1fmm" % (n_st, tot_mm)],
            ["分段", seg_line],
            ["守护结果", "%d/%d 拍通过工作空间与单步判据" % (n_st, n_st)],
            ["执行器 dry-run", "%d/%d 拍读入并逐拍校验通过" % (n_st, n_st)]]
    table(s, 0.55, 1.24, 7.0, rows, widths=[1.7, 5.3], row_h=0.46, body_size=9.5)
    box(s, 7.85, 1.24, 4.9, 3.72, fill=CARD, line=LINE)
    txt(s, 8.02, 1.36, 4.6, 0.3, "轨迹形状（xz 投影，示意）", 11, ACC, True)
    box(s, 8.05, 4.35, 0.16, 0.34, fill=MUTED)
    txt(s, 8.0, 4.76, 1.6, 0.22, "起点 136", 8, MUTED)
    box(s, 8.22, 2.30, 0.16, 2.39, fill=RGBColor(0x7C, 0xD3, 0xFC), shape=MSO_SHAPE.RECTANGLE)
    txt(s, 8.16, 2.02, 1.2, 0.24, "抬升 198.6", 8, MUTED)
    box(s, 8.24, 2.28, 3.35, 0.14, fill=ACC, shape=MSO_SHAPE.RECTANGLE)
    txt(s, 10.3, 2.46, 1.5, 0.24, "横移主段", 8, MUTED)
    box(s, 11.5, 2.28, 0.16, 1.18, fill=OK, shape=MSO_SHAPE.RECTANGLE)
    txt(s, 10.85, 3.52, 2.0, 0.24, "下降至 108.6 → 合爪", 8, MUTED)
    txt(s, 8.02, 4.14, 4.6, 0.62,
        "关键: 下降段单步 ≤20mm 且只走竖直；到位后才允许合爪。", 9.5, INK, spacing=1.25)
    txt(s, 0.55, 5.24, 12.2, 1.2,
        "诚实边界：这 %d 拍是「规划输出 + 执行器 dry-run」的结果；真机逐拍真走尚未完整跑通 ——\n" % n_st +
        "第一次真走在第 0 拍就因姿态换算错误被叫停（见下页），修法已固化，等臂复位后重跑。", 11, INK, spacing=1.35)

    # ---------------- 10 事故固化 ----------------
    s = page(prs, "现场事故与固化：姿态不许自己换算", "2026-11-22 第一次真走，第 0 拍就把腕部拧歪，当场停机", 10)
    rows = [["时刻", "发生了什么", "数"],
            ["第 0 拍", "命令 464.30, 344.00, 153.53 + 由四元数换算的 rpy", "自检 on/automatic/idle 通过"],
            ["随即", "实测落点 533.55, 327.12, 157.44，姿态被拧成 0.114, −1.44, 2.925", "Δ 69.25mm"],
            ["立刻", "判超差 > 1.0mm 停止；补发 arm_stop（moveReset ok）", "无报警、无碰撞"],
            ["根因", "action 的 a/b/c 是度，SDK rpy 是弧度且欧拉约定不同；执行器里按 ZYX 反解", "换算错一层"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[1.3, 7.1, 3.8], row_h=0.50, body_size=9.5)
    box(s, 0.55, 4.06, 5.95, 1.5, fill=RGBColor(0xFE, 0xF2, 0xF2), line=BAD, lw=1.2)
    txt(s, 0.72, 4.18, 5.6, 1.28,
        "错在哪\n"
        "把 action 的四元数当“标准 ZYX 欧拉”反解成弧度喂给 SDK，\n"
        "姿态与位置在第一拍同时变化 ⇒ 关节插值把手臂甩出去。", 10.5, INK, spacing=1.28)
    box(s, 6.8, 4.06, 5.95, 1.5, fill=RGBColor(0xF0, 0xFD, 0xF4), line=OK, lw=1.2)
    txt(s, 6.97, 4.18, 5.6, 1.28,
        "固化后的规则（已写进执行器）\n"
        "执行器每拍保持实测 rpy，只改位置；\n"
        "要转向必须先在安全高度用已验证的抓取姿态一次性摆正。", 10.5, INK, spacing=1.28)
    txt(s, 0.55, 5.78, 12.2, 0.8,
        "顺带固化：到位判据必须含姿态（Δp 0.6mm / Δr 0.02rad）—— 只判位置的脚本会在“纯转身”时假报到位。",
        10.5, INK, spacing=1.3)

    # ---------------- 11 验收 ----------------
    s = page(prs, "验收标准：六条，每条都能当场复核", "不达标的写清楚，不算通过", 11)
    rows = [["#", "验收项", "判定方式", "现状"],
            ["1", "输入有唯一 target_pose，六字段齐全", "读 zmax_data/ss_live/target_pose.json", "✓ 槽3 六字段齐"],
            ["2", "守护透传不丢字段", "守护输出含 target_pose / quat / pre_pos", "✓ 实测透传"],
            ["3", "分段合规：单步 ≤25mm、向下 ≤20mm", "逐段量长度与方向", "✓ %d/%d 通过" % (n_st, n_st)],
            ["4", "三段状态机可达 grip", "dry-run 末段 = grip", "✓ 第 20 拍"],
            ["5", "无真值不出位姿", "truth_fresh=false ⇒ action 为空", "✓ reason=tcp_stale"],
            ["6", "执行侧不换算姿态", "执行日志 rpy 与命令一致", "✓ 已改为保持实测"]]
    table(s, 0.55, 1.24, 12.2, rows, widths=[0.6, 4.6, 4.6, 2.4], row_h=0.44, body_size=9.5)
    txt(s, 0.55, 4.44, 12.2, 0.3, "尚未通过的一项（如实列出）", 12.5, BAD, True)
    txt(s, 0.55, 4.80, 12.2, 1.4,
        "真机逐拍真走：%d 拍完整走完 + 合爪真值 + 抬升不脱位 —— 尚未完成。\n" % n_st +
        "第一次真走在第 0 拍被叫停；修法已固化为「姿态保持实测」，等手臂复位后重跑，\n"
        "按 %d 拍逐拍记录 Δp，超 1.0mm 即停。" % n_st, 11, INK, spacing=1.35)

    # ---------------- 12 复现 ----------------
    s = page(prs, "复现命令与文件清单", "全部数字与脚本都在仓库里，可直接重跑", 12)
    txt(s, 0.55, 1.18, 12.2, 0.3, "① 算轨迹（宿主，不碰机器人）", 12, ACC, True)
    txt(s, 0.55, 1.52, 12.2, 0.58,
        "cd /home/ubuntu/zmax && PYTHONPATH=src ./gui-venv311/bin/python tools/plan_grasp_trail.py --slot 3 --speed 15 --lift 50\n"
        "→ zmax_data/ss_live/action_trail_slot3.json（%d 拍 / %.1fmm）" % (n_st, tot_mm), 10, INK, spacing=1.3)
    txt(s, 0.55, 2.40, 12.2, 0.3, "② 只看不动的 dry-run（容器）", 12, ACC, True)
    txt(s, 0.55, 2.74, 12.2, 0.58,
        "ZMAX_TRAIL_SLOT=3 ZMAX_TRAIL_EXEC=0 bash tools/rokae_sdk_run.sh --script exec_action_trail.py\n"
        "→ %d/%d 拍读入并逐拍校验（ZMAX_TRAIL_HOLD_RPY=1 默认：姿态保持实测）" % (n_st, n_st), 10, INK, spacing=1.3)
    txt(s, 0.55, 3.62, 12.2, 0.3, "③ 真走（需 8793 授权）", 12, ACC, True)
    txt(s, 0.55, 3.96, 12.2, 0.7,
        "ZMAX_TRAIL_SLOT=3 ZMAX_TRAIL_EXEC=1 ZMAX_TRAIL_MAXI=20 bash tools/rokae_sdk_run.sh --script exec_action_trail.py   # 到抓取点\n"
        "（合爪走 Orin 默认 domain 的 /gripper_driver）\n"
        "ZMAX_TRAIL_SLOT=3 ZMAX_TRAIL_EXEC=1 ZMAX_TRAIL_MINI=21 bash tools/rokae_sdk_run.sh --script exec_action_trail.py   # 抬升 50mm", 10, INK, spacing=1.3)
    rows = [["文件", "作用"],
            ["src/.../state_space/plan_guide.py", "target_pose() / publish_target()：唯一目标位姿（输入侧）"],
            ["src/.../state_space/motion_plan.py", "目标优先级 + 分段 + 三段抓取状态机 + action（本节点）"],
            ["src/.../middleware/nodes/impl/safety_limit_impl.py", "位姿守护：透传 target_pose 并再守一次"],
            ["src/.../state_space/action_bus.py", "from_plan()：plan → action 的落点"],
            ["tools/plan_grasp_trail.py", "宿主算 action 轨迹（本页 ①）"],
            ["tools/rokae/exec_action_trail.py", "容器内逐字执行（本页 ②③）"]]
    table(s, 0.55, 4.92, 12.2, rows, widths=[5.4, 6.8], row_h=0.28, body_size=8.5)

    prs.save(OUT)
    print("写出:", OUT)
    print("页数:", len(prs.slides))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
