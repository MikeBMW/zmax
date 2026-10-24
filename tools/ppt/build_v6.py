# -*- coding: utf-8 -*-
"""build_v6.py — 由 v5 生成器派生 v6（ReinBee 模板视觉 + 真机实拍图）"""
import os
import re

SRC = "/home/ubuntu/zmax_data/deliverables/robotics_landscape_2026-10-23/make_pptx_v5.py"
DST = "/home/ubuntu/zmax_data/deliverables/robotics_landscape_2026-10-23/make_pptx_v6.py"

s = open(SRC, encoding="utf-8").read()
checks = []


def rep(old, new, tag, count=1):
    global s
    n = s.count(old)
    checks.append((tag, n))
    if n >= 1:
        s = s.replace(old, new, count if count else -1)


# ── 1. 配色：模板深蓝 + 明黄 ──
rep("CN = RGBColor(0x2E, 0x6F, 0xD9)",
    "CN = RGBColor(0x1F, 0x4E, 0x79)      # ReinBee 模板主色 · 深蓝\n"
    "AC = RGBColor(0xFF, 0xC0, 0x00)      # ReinBee 模板辅色 · 明黄",
    "配色")

# ── 2. header：加品牌页眉条 ──
rep('''def header(s, kick, title, n, sub=None):
    text(s, 0.62, 0.38, 11.8, 0.3, kick, 10.5, True, MUT)
    text(s, 0.62, 0.64, 12.1, 0.72, title, 22.5, True, INK)
    rect(s, 0.62, 1.42, 12.09, 0.014, fill=LINE)
    if sub:
        text(s, 0.62, 1.50, 12.1, 0.28, sub, 9.2, False, MUT)
    footer(s, n)''',
    '''def brand_bar(s):
    """模板页眉：左 ReinBee 标识 + 右英文口号（原生文字，可改）"""
    rect(s, 0.62, 0.185, 0.062, 0.215, fill=AC)
    text(s, 0.745, 0.155, 2.6, 0.28, "ReinBee", 15.5, True, CN)
    text(s, 8.30, 0.205, 4.41, 0.20, "REIN INTELLIGENCE  BEE THE FUTURE",
         7.4, False, RGBColor(0xB4, 0xB9, 0xC2), align="r")


def header(s, kick, title, n, sub=None):
    brand_bar(s)
    text(s, 0.62, 0.50, 11.8, 0.24, kick, 9.2, True, RGBColor(0x8A, 0x92, 0x9E))
    text(s, 0.62, 0.74, 12.1, 0.60, title, 21.0, True, CN)
    rect(s, 0.62, 1.40, 0.58, 0.045, fill=CN)
    rect(s, 1.22, 1.40, 0.22, 0.045, fill=AC)
    if sub:
        text(s, 0.62, 1.50, 12.1, 0.26, sub, 8.9, False, MUT)
    footer(s, n)''',
    "header")

# ── 3. footer：加版权 ──
rep('''def footer(s, n):
    text(s, 0.62, 7.08, 9.0, 0.26,
         "Z-MAX · 竞品与合作分析 v5 · 2026-10-24 · 数据口径见%s" % ("本页" if n == TOTAL else "第 %d 页" % TOTAL),
         8.2, False, MUT)
    text(s, 11.6, 7.08, 1.1, 0.26, "%d/%d" % (n, TOTAL), 8.2, False, MUT, align="r")''',
    '''def footer(s, n):
    text(s, 0.62, 7.10, 7.2, 0.24,
         "Z-MAX · 竞品与合作分析 · 2026-10-24 · 数据口径见第 %d 页" % TOTAL,
         7.9, False, MUT)
    text(s, 7.95, 7.10, 3.55, 0.24, "© ReinBee All Rights Reserved.",
         7.4, False, RGBColor(0xB4, 0xB9, 0xC2), align="r")
    text(s, 11.70, 7.10, 1.01, 0.24, "%d/%d" % (n, TOTAL), 7.9, False, MUT, align="r")''',
    "footer")

# ── 4. 表格表头：深蓝底 + 白字 ──
rep("head_fill=RGBColor(0xF0, 0xF2, 0xF6), aligns=None, bold_col0=False):",
    "head_fill=None, aligns=None, bold_col0=False):", "表头默认色")
rep("    rows, cols = len(data), len(data[0])",
    "    head_fill = CN if head_fill is None else head_fill\n    rows, cols = len(data), len(data[0])",
    "表头赋值")
rep('''            set_font(r, fsize if i else fsize, i == 0 or (bold_col0 and j == 0),
                     INK if i else RGBColor(0x3A, 0x40, 0x4B))''',
    '''            set_font(r, fsize if i else fsize, i == 0 or (bold_col0 and j == 0),
                     WHITE if i == 0 else RGBColor(0x33, 0x3A, 0x44))''',
    "表头字色")

# ── 5. 型号卡：真机实拍图替换灰占位 ──
rep('''def img_slot(s, x, y, w, h, fname):
    """图片位：真 PNG 占位图（可右键「更改图片」），上叠一行提示字"""
    ph = os.path.join(FIG, "_ph.png")''',
    '''PHOTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fig6")


def img_slot(s, x, y, w, h, fname):
    """图片位：优先 fig6/<key>.jpg 真机实拍；没有才退回灰占位并注明"""
    key = (fname or "").rsplit(".", 1)[0].replace(" ", "")
    real = os.path.join(PHOTO, key + ".jpg")
    if os.path.exists(real):
        from PIL import Image as _PILImage
        iw, ih = _PILImage.open(real).size
        if iw / ih > w / h:
            _w = w
            _h = w * ih / iw
            s.shapes.add_picture(real, Inches(x), Inches(y + (h - _h) / 2),
                                 Inches(_w), Inches(_h))
        else:
            _h = h
            _w = h * iw / ih
            s.shapes.add_picture(real, Inches(x + (w - _w) / 2), Inches(y),
                                 Inches(_w), Inches(_h))
        return True
    ph = os.path.join(FIG, "_ph.png")''',
    "型号卡真图")

# ── 6. 输出文件名 / 抬头 ──
rep('OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),',
    'OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),', "占位")
s = s.replace("Z-MAX_竞品与合作分析_33页_图表可编辑_v5_2026-10-24.pptx",
              "Z-MAX_竞品与合作分析_33页_可编辑_ReinBee模板_2026-10-24.pptx", 1)

open(DST, "w", encoding="utf-8").write(s)
print("写出 %s  %d 字节" % (os.path.basename(DST), len(s)))
for t, n in checks:
    print("  %-12s 命中 %d %s" % (t, n, "" if n >= 1 else "  ⚠️ 未命中"))
