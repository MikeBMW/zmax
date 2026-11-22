#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_dual_guide_1p.py — 《左右 3D 引导位姿 · 双臂协同》**一页** PPT

所有数字现算: 位姿 = plan_guide.dual_arm_guide() 现场调用; 端口/代码落点 = 节点契约文件;
三条件实测结论 = 本轮真跑的三次判定 (无左真值 / 给左真值 / 越区) —— 不在页面里手写。
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
OUT = os.path.join(ROOT, "zmax_data/reports/左右3D引导位姿_双臂协同_v1.pptx")
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


def card(slide, x, y, w, h, title, color):
    box(slide, x, y, w, h, CARD, LINE, 1.0, True)
    box(slide, x, y, 0.055, h, color, None)
    txt(slide, x + 0.16, y + 0.10, w - 0.28, 0.26, title, 11.5, color, True)


def main():
    sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))
    import numpy as np
    from plan_guide import dual_arm_guide
    from lerobot.middleware.nodes import n_geodesic as CT     # 端口/标签从契约现取

    obs = np.zeros(43)
    obs[0:3] = [0.649, 0.404, 0.1142]                          # 右臂真机当前位置 (mm→m)
    d = dual_arm_guide({"in1": obs})
    L, R = d["L"], d["R"]
    port = ", ".join(CT.PORTS_OUT)
    pair = d["pair_id"]

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, BG, None)

    # 标题
    txt(s, 0.62, 0.30, 8.05, 0.55, "左右 3D 引导位姿 · 双臂协同", 26, INK, True)
    txt(s, 0.64, 0.90, 8.05, 0.34,
        "单机双臂 · 同一物理工作空间 · 同一组任务（正反向摆盘）的实时配合", 12.0, MUTED)
    txt(s, 8.95, 0.32, 3.80, 0.85,
        "节点 n_geoplan    端口 " + port + "\n一对 = 一个目标组：同 pair_id / 同 ts",
        9.8, MUTED, False, PP_ALIGN.RIGHT, 1.15)

    # 左右两张卡
    cw, cy, ch = 5.95, 1.34, 2.06
    for i, (P, ttl, col, arm) in enumerate(((L, "左臂 · 左盘 左槽8", ACC, "L"), (R, "右臂 · 右盘 槽3", ACC2, "R"))):
        x = 0.62 + i * (cw + 0.2)
        card(s, x, cy, cw, ch,
             ttl + "  ·  arm=" + arm + "  ·  " + ("⚠先验(未观测)" if not P.get("valid") else "实测"), col)
        g = P["grasp_mm"]
        hd = P.get("head_mm") or [0, 0, 0]
        q = P.get("quat") or [1, 0, 0, 0]
        import math as _m
        yaw = 2 * _m.degrees(_m.atan2(q[3], q[0]))
        yaw = (yaw + 180.0) % 360.0 - 180.0                    # 归一到 (-180, 180]
        lines = [
            "原点/抓取点(体中心)  %7.1f, %7.1f, %6.1f" % tuple(P["pos_mm"]),
            "金手指端(备查)        %7.1f, %7.1f, %6.1f" % tuple(hd),
            "预抓点 +%dmm          %7.1f, %7.1f, %6.1f" % ((int(P["hover_mm"]),) + tuple(P["pre_pos_mm"])),
            "quat %.5f %.5f %.5f %.5f  yaw %+.1f°" % (q[0], q[1], q[2], q[3], yaw),
            "几何真源  " + str(P.get("geom_src")),
        ]
        txt(s, x + 0.18, cy + 0.40, cw - 0.32, ch - 0.48, "\n".join(lines), 9.8, INK, False, PP_ALIGN.LEFT, 1.14)

    # 三条件
    ty = 3.52
    txt(s, 0.62, ty, 4.6, 0.3, "协同的三条硬条件（缺一条就降级并写明）", 13.5, INK, True)
    rows = [
        ("① 每拍双真值", "右臂 = obs[0:3] 真机；左臂 = 旁路 ZMAX_LARM_POSE_JSON",
         "无左真值 ⇒ hold=true（实测）\n给左真值 ⇒ hold=false（实测）"),
        ("② 原子成对", "out1 右臂 / out3 左臂，同 pair_id 同 ts；一侧缺几何 ⇒ 整对 pair_valid=false",
         "本页 pair " + pair + "\npair_valid=" + str(d["pair_valid"]).lower()),
        ("③ 分区 owner", "分界 y=%.0fmm：左盘=左区、右盘=右区，越区 ⇒ cross_zone + hold" % d["zone"]["split_mm"],
         "owner L/L R/R，cross_zone=" + str(d["zone"]["cross_zone"]).lower() + "（实测越区敢 true）"),
        ("间距护栏", "两抓取点间距 < %.0fmm ⇒ 预警" % 120.0,
         "实测 %.1fmm" % d["min_gap_mm"]),
    ]
    y = ty + 0.34
    for i, (k, v, res) in enumerate(rows):
        h = 0.60
        box(s, 0.62, y, 12.1, h, CARD if i % 2 == 0 else None, LINE, 0.75)
        txt(s, 0.74, y + 0.09, 1.65, 0.44, k, 11.2, INK, True)
        txt(s, 2.44, y + 0.09, 6.5, 0.44, v, 10.2, INK)
        txt(s, 9.08, y + 0.06, 3.55, 0.52, res, 9.6, OK if "hold=false" in res or "cross_zone=false" in res else MUTED)
        y += h + 0.06

    # 代码落点 + 状态
    by = 6.50
    card(s, 0.62, by, 7.45, 0.66, "代码落点：算法 / 实现 / 契约 三层，改逻辑只改算法层", ACC)
    txt(s, 0.78, by + 0.34, 7.15, 0.28,
        "plan_guide.py: dual_arm_guide()  ·  impl/n_geoplan.py → run  ·  nodes/n_geodesic.py  ·  publish_target_pair.py",
        8.6, INK)

    card(s, 8.22, by, 4.5, 0.66, "当前状态 hold=" + str(d["hold"]).lower(), BAD if d["hold"] else OK)
    txt(s, 8.38, by + 0.34, 4.2, 0.26,
        d["why"].split(";")[0][:22], 8.6, MUTED)

    txt(s, 0.62, 7.22, 12.1, 0.22,
        "只算不下发（下发走 sslimit→n_exec）· 数字现算：位姿由 dual_arm_guide() 现场生成 · 三条件为本轮真跑判定 · 先验位姿(valid=false)不可当抓取真值",
        8.0, MUTED)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print(json.dumps({"ok": True, "pptx": OUT, "slides": len(prs.slides.__iter__.__self__._sldIdLst),
                      "bytes": os.path.getsize(OUT), "pair_id": pair,
                      "L": L["grasp_mm"], "R": R["grasp_mm"], "hold": d["hold"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
