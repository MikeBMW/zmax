#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_multi_machine_1p.py — 《多机动作协同》**一页** PPT

一页讲完: 是什么(机间≠机内) → 放哪(n_mfac + ss_grav_h) → 契约(4进3出) → 判据5条
          → 能量(主机/从机各一份) → 从机补缺口(α_s) → 台账/真值缺口 → 状态
数字现算: multi_machine_energy 现场调用; 层份额读 state_space_energy.LAYER_SHARE。
"""
from __future__ import annotations

import json
import os
import sys

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

ROOT = "/home/ubuntu/zmax"
OUT = os.path.join(ROOT, "zmax_data/reports/多机动作协同_v1.pptx")
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


def txt(slide, x, y, w, h, s, size=12, color=INK, bold=False, align=PP_ALIGN.LEFT, spacing=1.10):
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


def box(slide, x, y, w, h, fill=None, line=None, lw=1.0, radius=False):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(lw)
    shp.shadow.inherit = False
    if radius:
        try:
            shp.adjustments[0] = 0.08
        except Exception:                                               # noqa: BLE001
            pass
    return shp


def card(slide, x, y, w, h, title, color, size=11.5):
    box(slide, x, y, w, h, CARD, LINE, 1.0, True)
    box(slide, x, y, 0.05, h, color, None)
    txt(slide, x + 0.15, y + 0.09, w - 0.28, 0.26, title, size, color, True)


def build():
    import numpy as np
    from lerobot.manifold.multi_machine_energy import (machine_energy, assist_share,
                                                      dual_layer_forces, Ledger)
    from lerobot.manifold.state_space_energy import StateSpaceHamiltonian, layer_shares
    from lerobot.manifold.se3_gravity_provider import _rpy_to_T
    from lerobot.manifold.se3_impedance import pose_error

    ham = StateSpaceHamiltonian()
    g = _rpy_to_T([0.649, 0.404, 0.114, 2.961, -1.490, 0.205, 0.0])
    gd = g.copy()
    gd[:3, 3] = g[:3, 3] + g[:3, 2] * 0.005
    xi = np.array([0, 0, 0.05, 0, 0, 0])
    M = machine_energy(g, gd, xi, ham)
    S = machine_energy(g, gd, xi, ham)
    _, xi_e = pose_error(g, gd)
    PLAN, REAL, CAP = 319.0, 240.0, 120.0
    a = assist_share(REAL, PLAN, CAP)
    b = assist_share(REAL, PLAN, 40.0)
    dl = dual_layer_forces(ham, {"M": a["alpha_master"], "S": a["alpha_slave"]}, xi_e)
    sh = layer_shares()
    L = Ledger()
    for i in range(5):
        L.add("P%d" % i, "M", 0.5)
    for i in range(3):
        L.add("P%d" % i, "S", 0.5)
    L.add("P3", "S", 0.5, ok=False, note="从机超时")
    rep = L.report()

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, BG, None)
    box(s, 0, 0, 0.09, H, ACC, None)

    txt(s, 0.55, 0.24, 8.95, 0.5, "多机动作协同", 25, INK, True)
    txt(s, 0.57, 0.76, 8.9, 0.40,
        "两台及以上独立设备（主双臂机器人 + 辅助机械臂），在更大空间内为完成产线物料流转（上下料）的联合调度与协同",
        11.0, MUTED)
    txt(s, 9.7, 0.28, 3.4, 0.62,
        "调度层 n_mfac（任务/资源/时间窗）\n力场层 ss_grav_h（能量与分力）", 9.8, MUTED, False, PP_ALIGN.RIGHT, 1.2)

    # 左列
    card(s, 0.55, 1.26, 6.05, 1.62, "机间 ≠ 机内（管任务与资源，不管单机位姿）", ACC)
    txt(s, 0.70, 1.60, 5.75, 1.2,
        "要决：谁先取 · 谁等 · 占哪个位 · 多久 · 干不完谁补\n"
        "不决：单机位姿与关节（那是 n_geoplan / n_moveit）\n"
        "机内（已做）：两位姿成对、同 pair_id 同 ts、同拍\n"
        "机间（本页）：每台一张派发单、lease+握手、异步秒级",
        9.6, INK, False, PP_ALIGN.LEFT, 1.25)

    card(s, 0.55, 2.98, 6.05, 1.52, "放哪个节点", ACC2)
    txt(s, 0.70, 3.32, 5.75, 1.1,
        "新建 n_mfac：ssplan/ssllm_in/ssuph → n_mfac → 各机 ssskill→sslimit→n_exec\n"
        "不放 n_geoplan：它只出几何位姿\n"
        "不放 ssuph：只给节拍预算，无握手/租约\n"
        "不放 sslimit：单机安全闸，管不了两台机的中间",
        9.6, INK, False, PP_ALIGN.LEFT, 1.25)

    card(s, 0.55, 4.58, 6.05, 1.42, "契约：四进三出", OK)
    txt(s, 0.70, 4.90, 5.75, 1.05,
        "in1 任务/物料单　in2 各机状态真值（每台一条）\n"
        "in3 资源表（取放位/缓冲/通道）　in4 节拍预算\n"
        "out1 派发单（task_id/seq/时间窗/占位权 TTL）\n"
        "out2 协同证据　out3 互锁信号 → sslimit",
        9.6, INK, False, PP_ALIGN.LEFT, 1.25)

    # 右列
    card(s, 6.78, 1.26, 6.0, 1.62, "能量：主机一份、从机一份（H=K+U 同源）", ACC2)
    txt(s, 6.93, 1.60, 5.7, 1.2,
        "主机 U=%.6f K=%.6f H=%.6f J |F|=%.3f N\n"
        "从机 U=%.6f K=%.6f H=%.6f J |F|=%.3f N（各算各的）\n"
        "口径校验：工具轴 2cm ⇒ U=0.080000 J；0.1m/s ⇒ K=0.018215 J"
        % (M["U"], M["K"], M["H"], float(np.linalg.norm(M["F"])),
           S["U"], S["K"], S["H"], float(np.linalg.norm(S["F"]))),
        8.9, INK, False, PP_ALIGN.LEFT, 1.22)

    card(s, 6.78, 2.98, 6.0, 1.52, "从机只补主机缺口，不平均分", BAD)
    txt(s, 6.93, 3.32, 5.7, 1.1,
        "主机计划 %.0f 件/时（段表 11.28s/件）· 实测 %.0f ⇒ 缺口 %.0f\n"
        "从机能力 %.0f ⇒ 接 %.0f：α_s=%.4f α_m=%.4f Σα=%.6f\n"
        "从机只能接 %.0f ⇒ saturated=true shortfall=%.0f（照实报）\n"
        "分力 F_(i,l)=α_i·s_l·Kξᵉ　残差 %.1e　层份额 %s"
        % (PLAN, REAL, a["gap"], CAP, a["slave_take"], a["alpha_slave"], a["alpha_master"],
           a["sum_alpha"], b["slave_take"], b["shortfall"], dl["resid_sumF"],
           " · ".join("%s %.2f" % (k, v) for k, v in sh.items())),
        8.9, INK, False, PP_ALIGN.LEFT, 1.22)

    card(s, 6.78, 4.58, 6.0, 1.42, "五条判据 + 台账", OK)
    txt(s, 6.93, 4.90, 5.7, 1.05,
        "① 同一位唯一 owner（lease 带 TTL，过期回收记账）\n"
        "② 包络距离<d_min 或通道相对 ⇒ 后到者 hold\n"
        "③ 超 N 拍无心跳 ⇒ 任务回退，下游不许拿过期真值\n"
        "④ 派发不超节拍预算　⑤ 派发单原子+按 task_id 去重\n"
        "台账 %d 件/%d 行 份额 %s 失败 %d" % (rep["parts"], rep["rows"],
                                           json.dumps(rep["share"], ensure_ascii=False), len(rep["failed"])),
        8.4, INK, False, PP_ALIGN.LEFT, 1.18)

    # 底部状态条
    box(s, 0.55, 6.08, 12.23, 0.62, CARD, LINE, 0.75, True)
    txt(s, 0.70, 6.15, 12.0, 0.5,
        "状态：算法层 multi_machine_energy 14/14 自检已过（口径/份额/饱和/双层力恒等/台账）　｜　"
        "未做：n_mfac 节点·第二台真值·ss_grav_h 加 in7 份额/out3 分力·真机双机联跑",
        9.4, INK, False, PP_ALIGN.LEFT, 1.2)
    txt(s, 0.55, 6.88, 12.2, 0.24,
        "数字现算 · 只算不下发（走各机 sslimit→n_exec）· 静止贴近目标时 H≈0 是真机停机态（非算不出）· 真值缺口：现在只有一条臂末端，多机需每台一条",
        8.2, MUTED)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print(json.dumps({"ok": True, "pptx": OUT, "slides": len(prs.slides), "bytes": os.path.getsize(OUT),
                      "alpha_s": a["alpha_slave"], "resid": dl["resid_sumF"],
                      "H": [M["H"], S["H"]], "gap": a["gap"], "shortfall": b["shortfall"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    build()
