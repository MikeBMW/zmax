#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_deck_fit.py — 估算文本框是否会溢出 (CJK 全宽口径), 只报不改。

口径: 一个字宽 ≈ 1em; 行高 ≈ size * line_spacing * 1.2 / 72 英寸。
表格: 每个单元格按列宽估行数, 行高不足则报。
"""
import sys, math, unicodedata
from pptx import Presentation
from pptx.util import Emu

PT = 12700  # EMU per point


def char_w(ch, size_pt):
    """字符宽度(相对 em)。"""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    if ch in " .,:;|'!":
        return 0.32
    if ch.isdigit():
        return 0.55
    if ch.isupper():
        return 0.62
    return 0.52


def text_lines(text, size_pt, width_in):
    """按宽度折算行数。"""
    avail_pt = width_in * 72
    lines = 0
    for seg in str(text).split("\n"):
        w = sum(char_w(c, size_pt) for c in seg) * size_pt
        lines += max(1, math.ceil(w / max(avail_pt, 1)))
    return lines


def check(path):
    prs = Presentation(path)
    bad = []
    for idx, slide in enumerate(prs.slides, 1):
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                w = sh.width / 914400
                h = sh.height / 914400
                tf = sh.text_frame
                need = 0.0
                for p in tf.paragraphs:
                    txt = "".join(r.text for r in p.runs) or p.text
                    if not txt.strip():
                        continue
                    size = next((r.font.size.pt for r in p.runs if r.font.size), 14)
                    ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.25
                    n = text_lines(txt, size, w)
                    need += n * size * ls * 1.2 / 72
                if need > h + 0.06:
                    bad.append((idx, "TEXT", sh.name, round(w, 2), round(h, 2), round(need, 2),
                                tf.text.strip().replace("\n", " ")[:38]))
            if sh.has_table:
                tbl = sh.table
                for r_i, row in enumerate(tbl.rows):
                    row_h = row.height / 914400
                    need = 0.0
                    for c_i, cell in enumerate(row.cells):
                        cw = tbl.columns[c_i].width / 914400 - 0.18
                        txt = cell.text.strip()
                        if not txt:
                            continue
                        size = 12
                        for p in cell.text_frame.paragraphs:
                            for r in p.runs:
                                if r.font.size:
                                    size = r.font.size.pt
                                    break
                            break
                        need = max(need, text_lines(txt, size, cw) * size * 1.25 / 72 + 0.07)
                    if need > row_h + 0.05:
                        bad.append((idx, "TABLE r%d" % r_i, "", "", round(row_h, 2), round(need, 2),
                                    row.cells[0].text.strip()[:24]))
    print(f"slides={len(prs.slides._sldIdLst)} 溢出候选={len(bad)}")
    for b in bad:
        print("  p%-3d %-10s %-16s w=%s h=%s need=%s | %s" % b)
    return len(bad)


if __name__ == "__main__":
    sys.exit(1 if check(sys.argv[1]) else 0)
