#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_robot_work_ppt.py — 单页 PPT：渲染后的机器人作业姿态。

一页、白底、图大、字少（按老倪口径：首页不提技术参数）。
用法: python3 tools/make_robot_work_ppt.py --img PNG --out PPTX
"""
import os, sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

GREY_D = RGBColor(0x22, 0x26, 0x2E)
GREY_M = RGBColor(0x6B, 0x72, 0x80)
ACCENT = RGBColor(0x1E, 0x6F, 0xD9)


def arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    img = arg("--img", "/tmp/robot_work/robot_work.png")
    out = arg("--out", "/home/ubuntu/zmax/zmax_data/tmp/legacy_decks/机器人作业姿态.pptx")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])      # 空白版式

    # ── 图片：右侧大图，等比缩放，高度占满可视区 ──────────────
    from PIL import Image
    iw, ih = Image.open(img).size
    box_h = Inches(6.30)
    box_w = Emu(int(box_h * iw / ih))
    pic = s.shapes.add_picture(img, Inches(4.55), Inches(0.60), height=box_h)

    # ── 左侧标题区：一条竖色带 + 两行字，别的都不放 ───────────
    bar = s.shapes.add_shape(1, Inches(0.85), Inches(2.62), Inches(0.055), Inches(1.55))
    bar.fill.solid(); bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    bar.shadow.inherit = False

    tb = s.shapes.add_textbox(Inches(1.10), Inches(2.50), Inches(3.15), Inches(1.80))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE

    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    r = p.add_run(); r.text = "机器人作业姿态"
    r.font.size = Pt(34); r.font.bold = True
    r.font.color.rgb = GREY_D
    r.font.name = "微软雅黑"

    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.LEFT
    p2.space_before = Pt(10)
    r2 = p2.add_run(); r2.text = "光模块上下料工位"
    r2.font.size = Pt(16)
    r2.font.color.rgb = GREY_M
    r2.font.name = "微软雅黑"

    prs.save(out)
    print("saved", out, os.path.getsize(out), "bytes")
    print("img", iw, "x", ih, "-> placed height 6.30in")
    return out


if __name__ == "__main__":
    main()
