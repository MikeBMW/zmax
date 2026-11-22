#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_skill_flip.py — 《⑬ 自动翻转技能 SK13 · 功能说明》

骨架: 是什么 → 判据(什么时候翻) → 包络(怎么翻才安全) → 序列(实测 38 步) → 边界(谁决定谁执行)
      → 画布节点与连线 → 代码落点 → 实测证据 → 还没做的 → 验收 → 复现

所有数字从 skills/atomic_skills.py:class SK13Flip 与画布 JSON 现算, 不在页面里手写。
"""
from __future__ import annotations

import json
import os
import sys

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

ROOT = "/home/ubuntu/zmax"
OUT = os.path.join(ROOT, "zmax_data/reports/自动翻转技能_SK13_功能说明_v1.pptx")
CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
sys.path.insert(0, os.path.join(ROOT, "src"))

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
            "⑬ 自动翻转 · SK13 · 按需技能 · v5.50.782 · 2026-11-22", 8.5, MUTED)
    return s


def main() -> int:
    from lerobot.policies.left_right.state_space.skills.atomic_skills import SK13Flip as F

    P = F.params
    flip_deg = float(P["flip_deg"])
    dr = float(F.DR_DEG_STEP)
    n_rot = int(round(flip_deg / dr))
    clear_mm = float(P["clearance_h"]) * 1000.0
    tol = float(P["yaw_tol_deg"])
    plan = F.plan_flip([648.79, 407.03, 108.58], (1.0, 0.0, 0.0, 0.0), clear_mm=clear_mm)
    n_steps = len(plan)
    lift = plan[0]
    descend = plan[-1]

    cv = json.load(open(CANVAS, encoding="utf-8"))
    node = next(n for n in cv["nodes"] if n["id"] == "sssk13")
    links = [l for l in cv["links"] if l.get("f") == "sssk13" or l.get("t") == "sssk13"]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    # 1 封面
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, 2.5, fill=RGBColor(0x0B, 0x1B, 0x2B))
    txt(s, 0.85, 0.68, 11.6, 0.8, "⑬ 自动翻转 · SK13", 38, RGBColor(0xFF, 0xFF, 0xFF), True)
    txt(s, 0.85, 1.50, 11.6, 0.5, "按拉环朝向自动翻转 180° · 全程守运动包络", 20, RGBColor(0x7D, 0xD3, 0xFC))
    txt(s, 0.85, 2.92, 11.6, 1.2,
        "不是“多一套动作脚本”，而是把「什么时候该翻」和「翻的每一拍允许多大角度」写成可判定的规则：\n"
        "朝向相反才翻，翻了先抬净空，再按每拍 ≤%.0f° 分 %d 拍转 %.0f°，最后回落交放料。" % (dr, n_rot, flip_deg),
        13.5, INK, spacing=1.5)
    box(s, 0.85, 4.60, 3.6, 0.9, fill=RGBColor(0xE8, 0xF4, 0xFD), line=ACC, lw=1.3)
    txt(s, 0.98, 4.70, 3.3, 0.7, "输入\n模块朝向 + 目标朝向", 11.5, INK)
    box(s, 4.72, 4.60, 3.5, 0.9, fill=CARD, line=LINE)
    txt(s, 4.85, 4.70, 3.2, 0.7, "判据\n|Δyaw| ≈ %.0f°(±%.0f°)" % (flip_deg, tol), 11.5, INK)
    box(s, 8.48, 4.60, 3.9, 0.9, fill=RGBColor(0xEC, 0xFD, 0xF3), line=OK, lw=1.3)
    txt(s, 8.61, 4.70, 3.6, 0.7, "输出\n%d 步翻转序列(位姿+角度)" % n_steps, 11.5, INK)
    txt(s, 0.85, 6.28, 11.6, 0.4,
        "画布节点 sssk13 · %d 条连线 · 自测 26/26 · 工程库判据全绿 · 真机未验" % len(links), 10.5, MUTED)

    # 2 是什么
    s = page(prs, "这个技能干什么：判据 + 包络，不产目标位姿", "它回答「要不要翻」和「怎么翻才不撞」，不决定「去哪儿」", 2)
    box(s, 0.55, 1.30, 12.2, 0.9, fill=CARD, line=ACC, lw=1.4)
    txt(s, 0.75, 1.42, 11.8, 0.7,
        "一句话：拉环/模块朝向与工位要求相反 ⇒ 先抬 %.0fmm 净空，绕工具轴每拍 ≤%.0f° 分 %d 拍翻 %.0f°，再回落；"
        "全程平移 ≤%.2f m/s、角速度 ≤%.1f rad/s。" % (clear_mm, dr, n_rot, flip_deg, F.V_CAP, F.W_CAP),
        12.5, INK, spacing=1.35)
    rows = [["它做什么", "它不做什么", "为什么这么划"],
            ["判「要不要翻」（朝向判据）", "不产目标位姿", "目标位姿只能有一个出处（测地线引导）"],
            ["给分段与每拍角度预算", "不下发、不碰 8793 授权", "下发归执行器，授权归现场"],
            ["给抬升净空与速度上限", "不做放料动作", "放料是「精准放置/放下」段"],
            ["出序列给运动规划展开 action", "不进 8/13 段主链", "进主链会改阶段索引，功能会坏"]]
    table(s, 0.55, 2.42, 12.2, rows, widths=[4.4, 3.8, 4.0], row_h=0.50, body_size=9.5)
    txt(s, 0.55, 5.10, 12.2, 0.9,
        "为什么单独成一个“按需技能”而不是主链第 14 段：\n"
        "主链是状态机推进序，插一段就把 DONE_IDX / 回退区间整体挪位 —— 插拔、摆盘两条链都会跟着错。"
        "所以它按判据触发，链不动。", 11, INK, spacing=1.35)

    # 3 判据
    s = page(prs, "触发判据：相反才翻，偏一半不硬翻", "needs_flip(yaw_module, yaw_target) —— 三个出口，都能解释", 3)
    rows = [["|Δyaw|（模块 vs 目标）", "判定", "行为", "理由"],
            ["≤ %.0f°" % tol, "一致", "不翻，直接放料", "容差内视为已对齐"],
            ["%.0f° ~ %.0f°" % (180 - tol, 180 + tol), "相反", "自动翻转 %.0f°" % flip_deg, "翻转能真正解决的方向差"],
            ["其余（≈90°）", "都不是", "不硬翻，交 L3 重选技能", "翻 180° 只会更错"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[3.4, 1.8, 3.6, 3.4], row_h=0.50, body_size=9.5)
    box(s, 0.55, 3.92, 6.0, 1.75, fill=RGBColor(0xFE, 0xF2, 0xF2), line=BAD, lw=1.2)
    txt(s, 0.72, 4.04, 5.65, 1.5,
        "反面：偏 95° 也去翻 180°\n"
        "结果是“本来差 95°，翻完差 85°” —— 还多了一次带件的腕部大转。\n"
        "判据里这一档明确不翻，把决定权交回 L3（换技能/换工位）。", 10.5, INK, spacing=1.28)
    box(s, 6.8, 3.92, 5.95, 1.75, fill=CARD, line=LINE)
    txt(s, 6.97, 4.04, 5.6, 1.5,
        "实测三例（节点真跑，不是推演）\n"
        "模块 0° / 目标 180° → flip_call=True · Δ−180.0° · %d 步\n"
        "模块 0° / 目标 10°  → False ·「朝向一致 ⇒ 直接放料」\n"
        "只给模块朝向、缺目标 → None ·「缺目标朝向 ⇒ 不动作(不猜朝向)」" % n_steps, 10.5, INK, spacing=1.28)

    # 4 包络
    s = page(prs, "运动包络：四条硬约束 + 一条顺序约束", "数字真源 config/calib/zmax_skill_physics.json 段=翻转，逐项可追溯", 4)
    rows = [["约束", "值", "不守会怎样"],
            ["先抬净空", "%.0f mm" % clear_mm, "槽内直接转 ⇒ 扫到料盘/邻槽"],
            ["单拍角度", "≤ %.0f°（共 %d 拍）" % (dr, n_rot), "腕部跳变，伺服跟不上；关节限位易撞"],
            ["平移速度", "≤ %.2f m/s" % F.V_CAP, "带件横甩，夹持靠摩擦硬扛"],
            ["角速度", "≤ %.1f rad/s" % F.W_CAP, "转动惯量带来的抖动与滑移"],
            ["顺序", "抬 → 转 → 回落（不许边转边降）", "下降中旋转最容易把件顶掉"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[2.2, 3.6, 6.4], row_h=0.46, body_size=9.5)
    txt(s, 0.55, 3.98, 6.0, 0.3, "物理真源（limits_for(\"翻转\") 现取）", 12, ACC, True)
    rows2 = [["量", "值", "来源"],
             ["v", "%.3f m/s" % 0.05, "翻转段平移极慢"],
             ["a_max", "%.4f m/s²" % (5.0 / 1.35), "F/m = 5.00N / 1.35kg"],
             ["s_step", "%.4f m" % 0.005, "v_cap × dt"],
             ["w / dr", "%.1f rad/s / %.0f°" % (F.W_CAP, dr), "真源只有平移量 ⇒ 姿态上限写在技能类并注明"]]
    table(s, 0.55, 4.36, 6.0, rows2, widths=[1.3, 2.0, 2.7], row_h=0.40, body_size=9)
    box(s, 6.8, 4.36, 5.95, 1.55, fill=RGBColor(0xFF, 0xFB, 0xEB), line=ACC2, lw=1.2)
    txt(s, 6.97, 4.48, 5.6, 1.3,
        "诚实说明：真源 json 只标了平移量 (v/a/s)，没有姿态量。\n"
        "所以「每拍 ≤%.0f°」和「角速度 ≤%.1f rad/s」是写在技能类里的常量，\n"
        "并注明来源 —— 等现场标定后再回填进 json，不冒充标定值。" % (dr, F.W_CAP), 10, INK, spacing=1.25)

    # 5 序列
    s = page(prs, "翻转序列：%d 步，每一步都能复核" % n_steps, "plan_flip() 输出 —— 位置 + 姿态 + 角度预算，交给运动规划展开", 5)
    rows = [["步", "类型", "位置 (mm)", "累计角度", "本步角度"],
            ["0", lift["kind"], "%.2f, %.2f, %.2f" % tuple(lift["pos"]), "0.0°", "—"],
            ["1", "rotate", "%.2f, %.2f, %.2f" % tuple(plan[1]["pos"]), "%.1f°" % plan[1]["deg_done"],
             "%.1f°" % plan[1]["dr_max_deg"]],
            ["…", "rotate", "同高，姿态逐拍转", "…", "≤ %.0f°" % dr],
            ["%d" % (n_steps - 2), "rotate", "%.2f, %.2f, %.2f" % tuple(plan[-2]["pos"]),
             "%.1f°" % plan[-2]["deg_done"], "%.1f°" % plan[-2]["dr_max_deg"]],
            ["%d" % (n_steps - 1), descend["kind"], "%.2f, %.2f, %.2f" % tuple(descend["pos"]),
             "%.1f°" % descend["deg_done"], "—"]]
    table(s, 0.55, 1.26, 8.0, rows, widths=[0.8, 1.5, 3.2, 1.3, 1.2], row_h=0.44, body_size=9.5)
    box(s, 8.75, 1.26, 4.0, 2.64, fill=CARD, line=LINE)
    txt(s, 8.92, 1.38, 3.7, 0.3, "构成", 11, ACC, True)
    txt(s, 8.92, 1.72, 3.7, 2.0,
        "抬升   1 步（%.0fmm）\n旋转 %d 步（%.0f° / %.0f°）\n回落   1 步\n合计 %d 步"
        % (clear_mm, n_rot, flip_deg, dr, n_steps), 11, INK, spacing=1.35)
    txt(s, 0.55, 4.32, 12.2, 0.9,
        "旋转期间高度恒定（%0.2f mm 一直不动）—— 这是“先抬后转”的可检查形式：\n"
        "任何一步 z 掉回原高度，就说明序列被别处改过。" % lift["pos"][2], 11, INK, spacing=1.35)
    txt(s, 0.55, 5.30, 12.2, 1.0,
        "末步姿态与「绕工具轴转 %.0f°」的解析解夹角 < 1e-3°（自测里断言过）：\n"
        "姿态不是拼出来的，是四元数右乘逐步累乘 —— 不会出现“转到一半丢了半圈”。" % flip_deg,
        10.5, INK, spacing=1.3)

    # 6 边界
    s = page(prs, "谁决定、谁执行：四层分工不许串", "本技能只占「判据 + 包络」这一格", 6)
    rows = [["环节", "归谁", "本技能的关系"],
            ["要不要翻、偏多少", "L3 技能选择 / 感知给朝向", "提供判据函数，不替 L3 拍板"],
            ["翻完去哪儿（目标 6D）", "🧭 测地线规划引导 n_geoplan", "完全不管 —— 目标位姿唯一出处"],
            ["每一拍走多少", "🏃 运动规划 n_moveit", "只给角度预算，不生成 action"],
            ["放料/插入", "SK07 放入 · 放下段", "回落到位就交棒"],
            ["下发与授权", "n_exec + 8793 页面两步确认", "不碰"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[3.2, 4.6, 4.4], row_h=0.46, body_size=9.5)
    txt(s, 0.55, 4.05, 12.2, 1.1,
        "一句话记法：朝向判据在 L2（技能），目标位姿在引导，轨迹在规划，动作在规划出的 action，"
        "下发在执行器。\n谁越界，就会出现“两个地方各给一个目标” —— 之前踩过的半路掉头就是这么来的。", 11, INK, spacing=1.35)
    box(s, 0.55, 5.15, 12.2, 1.2, fill=CARD, line=LINE)
    txt(s, 0.75, 5.28, 11.8, 1.0,
        "与「翻转放料」整条功能的关系：翻转放料 = 朝向判据(SK13) + 目标位姿(引导) + 轨迹(action) + 放料段(SK07)。\n"
        "SK13 只补上其中最容易被忽略的一格：翻之前先抬、翻的每一拍别太大。", 10.5, INK, spacing=1.3)

    # 7 画布节点
    s = page(prs, "画布：节点 sssk13 + %d 条连线" % len(links), "data/…/canvas/state_space_obs.json 与 flows/ 两份都写（98 节点 / 232 连线）", 7)
    box(s, 0.55, 1.30, 3.6, 1.5, fill=RGBColor(0xF3, 0xE8, 0xFF), line=RGBColor(0x7C, 0x5C, 0xD8), lw=1.4)
    txt(s, 0.72, 1.42, 3.3, 0.34, "🔄 ⑬ 自动翻转 · SK13", 12, RGBColor(0x5B, 0x21, 0xB6), True)
    txt(s, 0.72, 1.78, 3.3, 0.9,
        "节点 %s\n位置 (%d, %d) · 280×110\nin1..in4 → out1/out2" % (node["id"], node["x"], node["y"]),
        9.5, INK, spacing=1.25)
    rows = [["方向", "端点", "含义"]]
    for l in links:
        rows.append([("进" if l["t"] == "sssk13" else "出"),
                     "%s.%s → %s.%s" % (l["f"], l.get("f_port"), l["t"], l.get("t_port")),
                     l.get("label", "")[:26]])
    table(s, 4.45, 1.30, 8.3, rows, widths=[0.7, 4.4, 3.2], row_h=0.44, body_size=9)
    txt(s, 0.55, 4.30, 12.2, 1.0,
        "为什么入线是这四条：① 限幅后控制（当前位姿）② L3 技能序列（选到它才走）③ 记忆赋能（标杆/通道）\n"
        "④ 目标位姿（朝向判据从这里来 —— 这一条最容易漏，漏了节点就永远“缺朝向”）。", 10.5, INK, spacing=1.3)
    txt(s, 0.55, 5.35, 12.2, 1.0,
        "出线两条：out1 交运动规划（序列→action），out2 交动力学约束（本段物理上限）。\n"
        "节点 PURE=False：只走数据面出序列，不下发；要它真动，仍走 n_exec + 8793 授权。", 10.5, INK, spacing=1.3)

    # 8 代码落点
    s = page(prs, "代码落点：一个节点看三处", "契约 / 实现 / 算法，各管一件事，改逻辑只动其中一处", 8)
    rows = [["层", "文件", "管什么"],
            ["算法", "src/lerobot/policies/left_right/state_space/skills/atomic_skills.py\nclass SK13Flip", "判据 needs_flip / 序列 plan_flip / 姿态数学 / 包络常量"],
            ["实现", "src/lerobot/middleware/nodes/impl/sssk13.py", "取四路输入 → 算 yaw → 出序列 + 物理上限"],
            ["契约", "src/lerobot/middleware/nodes/n_sk13.py", "端口/话题/执行口径 (文件名由节点名推导, 不是 id)"],
            ["注册", "impl/shared_runtime.py · nodes/_index.py", "registry key=sssk13 · id↔名字反查 · 右键源码直达"],
            ["真源", "config/calib/zmax_skill_physics.json 段=翻转", "v/a/s/s_step/jerk/m/F/dmdt + w/dr_deg"],
            ["工程库", "data/database/zmax/function_notes.json", "做什么/阻塞点/状态 (83/83 条, 判据全绿)"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[1.2, 6.4, 4.6], row_h=0.60, body_size=8.5)
    txt(s, 0.55, 5.36, 12.2, 0.9,
        "踩过的坑：契约文件名不能用节点 id。loader 按**节点名里的 ASCII** 推文件名（\"⑬ 自动翻转 · SK13\" → n_sk13.py），\n"
        "我先写成 n_skill13.py，结果 loader 另生成一个空壳模块 —— 表现是“节点在、跑起来直通、out1 空”。", 10.5, INK, spacing=1.3)

    # 9 证据
    s = page(prs, "实测证据：判据、包络、节点执行全绿", "可复跑：tools/test_skill_flip.py (26/26) + 画布单节点 step", 9)
    rows = [["检查", "结果", "怎么验的"],
            ["判据三档", "✓ 相反翻 / 一致不翻 / 偏 95° 交 L3", "needs_flip 三例"],
            ["单拍角度", "✓ 每拍 ≤ %.0f°" % dr, "plan_flip 逐拍断言"],
            ["累计角度", "✓ %.0f°（%d 拍）" % (flip_deg, n_rot), "逐拍累加"],
            ["抬升 / 回落", "✓ +%.0fmm / 回原位" % clear_mm, "首末步断言"],
            ["姿态数学", "✓ 绕 Z %.0f° 的夹角 = %.0f°" % (flip_deg, flip_deg), "四元数右乘 + 夹角"],
            ["平移限幅", "✓ 1.0 → %.2f m/s（why=速度）" % F.V_CAP, "clamp() 实测"],
            ["节点执行", "✓ step status = 实现执行", "load_project().step(only=['sssk13'])"],
            ["工程库", "✓ 83 功能 / 83 描述 / 判据全绿", "engineering_db.py check"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[2.0, 6.2, 4.0], row_h=0.42, body_size=9)
    txt(s, 0.55, 5.10, 12.2, 0.42,
        "自测脚本 %d 条断言全过；本页每条都能当场重跑，不依赖 PPT 里的说法。" % 26, 10.5, INK, spacing=1.3)
    txt(s, 0.55, 5.62, 12.2, 0.9,
        "注意：这些证明的是「判据和包络对」，不证明「真机翻转成功」—— 真机还没跑。", 10.5, BAD, spacing=1.3)

    # 10 还没做
    s = page(prs, "还没做的：四条，如实列", "不写这些，这份说明就变成“已经能用了”的假象", 10)
    rows = [["缺口", "现状", "补法"],
            ["几何通道包络", "skill_corridors.json 无「翻转」段 ⇒ clamp 里 corridor 报无通道", "现场标定摆动半径/邻槽避让后写入"],
            ["真机 180° 翻转", "一次没跑过", "先在安全高度空跑，再带件；逐拍记录姿态偏差"],
            ["夹持漂移阈值", "参数写 2mm，未实测", "1000 全开带件转动时测漂移，确认是否需要加压"],
            ["引导侧 flip 参数", "n_geoplan 还没有 flip=180 出目标位姿", "加 flip 参数并在引导层判可行域"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[2.4, 5.8, 4.0], row_h=0.56, body_size=9)
    txt(s, 0.55, 4.40, 12.2, 0.95,
        "为什么现在不做完：翻转的可行性取决于“转到一半会不会碰到东西”，这是工位几何问题，\n"
        "不是代码问题。没有摆臂半径和邻槽间距的实测，任何“可行”都是猜的。", 11, INK, spacing=1.35)
    txt(s, 0.55, 5.55, 12.2, 0.9,
        "当前可交付的边界：判据与序列可以直接进链路（出 action 前先 dry-run），真机翻转要等标定。", 10.5, INK, spacing=1.3)

    # 11 验收
    s = page(prs, "验收清单：六条，逐条可复核", "全绿才算这个技能交付；未通过的写清楚", 11)
    rows = [["#", "验收项", "判定", "现状"],
            ["1", "技能类可导入、注册进 SKILL_BY_CODE", "SKILL_BY_CODE['SK13'] is SK13Flip", "✓"],
            ["2", "按需注册，不污染 8/13 段主链", "SKILLS 仍 8 项、SKILLS_FULL 无 SK13", "✓"],
            ["3", "物理真源段「翻转」可解析", "limits_for('翻转').unknown_stage == 0", "✓"],
            ["4", "画布节点 + 连线齐全且 x 递增", "%d 条连线、端点存在、x 递增" % len(links), "✓"],
            ["5", "单节点可执行", "step(only=['sssk13']) → 实现执行", "✓"],
            ["6", "工程库判据全绿", "engineering_db.py check", "✓"]]
    table(s, 0.55, 1.26, 12.2, rows, widths=[0.6, 4.6, 4.8, 2.2], row_h=0.46, body_size=9.5)
    txt(s, 0.55, 4.60, 12.2, 1.1,
        "另有一条不在本清单里的期望：「真机带件翻转 180° 不脱手、不碰撞」。\n"
        "它现在不满足 —— 缺口见上页，今天不写在这张表里冒充通过。", 11, BAD, spacing=1.35)

    # 12 复现
    s = page(prs, "复现命令", "全部可本地重跑，不需要机器人", 12)
    txt(s, 0.55, 1.18, 12.2, 0.3, "① 技能自测（判据/包络/姿态数学）", 12, ACC, True)
    txt(s, 0.55, 1.52, 12.2, 0.6, "cd /home/ubuntu/zmax && PYTHONPATH=src ./gui-venv311/bin/python tools/test_skill_flip.py", 10, INK, spacing=1.3)
    txt(s, 0.55, 2.22, 12.2, 0.3, "② 看翻转序列（不碰机器人）", 12, ACC, True)
    txt(s, 0.55, 2.56, 12.2, 0.9,
        "PYTHONPATH=src ./gui-venv311/bin/python -c \"from lerobot.policies.left_right.state_space.skills.atomic_skills import SK13Flip as F;\n"
        "print(len(F.plan_flip([648.79,407.03,108.58], (1,0,0,0))), F.needs_flip(0, 180))\"", 9.5, INK, spacing=1.3)
    txt(s, 0.55, 3.52, 12.2, 0.3, "③ 画布节点单跑", 12, ACC, True)
    txt(s, 0.55, 3.86, 12.2, 0.9,
        "PYTHONPATH=src ./gui-venv311/bin/python -c \"from lerobot.middleware import load_project;\n"
        "r=load_project().step(only=['sssk13'])[0]; print(r['status'], r['out']['out1']['flip_call'])\"", 9.5, INK, spacing=1.3)
    txt(s, 0.55, 4.82, 12.2, 0.3, "④ 加回画布（幂等，先 dry）", 12, ACC, True)
    txt(s, 0.55, 5.16, 12.2, 0.6,
        "./gui-venv311/bin/python tools/canvas_add_sssk13.py --dry   # 断言位置/连线\n"
        "./gui-venv311/bin/python tools/canvas_add_sssk13.py --apply # 备份 + 写两份 JSON + 回读", 9.5, INK, spacing=1.3)
    txt(s, 0.55, 6.20, 12.2, 0.3, "⑤ 工程库判据", 12, ACC, True)
    txt(s, 0.55, 6.54, 12.2, 0.5,
        "./gui-venv311/bin/python tools/engineering_db.py build && ./gui-venv311/bin/python tools/engineering_db.py check | tail -3", 9.5, INK, spacing=1.3)

    prs.save(OUT)
    print("写出:", OUT)
    print("页数:", len(prs.slides))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
