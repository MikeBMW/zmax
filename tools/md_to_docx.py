#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md_to_docx.py — Markdown → Word(.docx)，面向专利/交付文档

支持: # 标题 / ## 三级标题 / 表格 / 有序与无序列表 / ``` 代码块 / 正文
不追求做通用转换器，只保证专利交底书这类文档的结构与可读性。
用法: python tools/md_to_docx.py <in.md> [out.docx]
"""
from __future__ import annotations

import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

EA = "微软雅黑"
MONO = "Consolas"


def _font(run, size=None, bold=None, mono=False):
    name = MONO if mono else EA
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        rf = rPr.makeelement(qn("w:rFonts"), {})
        rPr.append(rf)
    rf.set(qn("w:eastAsia"), EA)
    rf.set(qn("w:ascii"), name)
    rf.set(qn("w:hAnsi"), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold


def add_inline(p, text, size=10.5):
    """处理 **粗体** 与 `行内代码`"""
    for seg in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not seg:
            continue
        if seg.startswith("**") and seg.endswith("**") and len(seg) > 4:
            r = p.add_run(seg[2:-2])
            _font(r, size, True)
        elif seg.startswith("`") and seg.endswith("`") and len(seg) > 2:
            r = p.add_run(seg[1:-1])
            _font(r, size - 0.5, False, mono=True)
            r.font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)
        else:
            r = p.add_run(seg)
            _font(r, size)


def convert(md_path, out_path):
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = EA
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), EA)

    lines = open(md_path, encoding="utf-8").read().splitlines()
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()

        if not s:
            i += 1
            continue

        # 图片  ![alt](path)  —— 相对 md 所在目录解析, 缺失时留一行灰字提示(不静默跳过)
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", s)
        if m_img:
            alt, src = m_img.group(1), m_img.group(2).strip()
            if src.startswith("http://") or src.startswith("https://"):
                i += 1
                continue
            fig = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(md_path)), src))
            if os.path.exists(fig):
                try:
                    doc.add_picture(fig, width=Inches(5.9))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                except Exception as e:                                  # noqa: BLE001
                    pr = doc.add_paragraph()
                    _font(pr.add_run("[图片插入失败 %s: %s]" % (os.path.basename(fig), e)), 9)
            else:
                pr = doc.add_paragraph()
                _font(pr.add_run("[缺图: %s]" % src), 9)
                pr.runs[0].font.color.rgb = RGBColor(0xB0, 0x30, 0x30)
            i += 1
            continue

        # 代码块
        if s.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(12)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(6)
            r = p.add_run("\n".join(buf))
            _font(r, 9.5, False, mono=True)
            continue

        # 表格
        if s.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = doc.add_table(rows=1 + len(rows), cols=len(header))
            t.style = "Table Grid"
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            for ci, h in enumerate(header):
                cell = t.cell(0, ci)
                cell.text = ""
                p = cell.paragraphs[0]
                add_inline(p, "**" + h.strip("*") + "**", 9.5)
            for ri, row in enumerate(rows, start=1):
                for ci in range(len(header)):
                    val = row[ci] if ci < len(row) else ""
                    cell = t.cell(ri, ci)
                    cell.text = ""
                    add_inline(cell.paragraphs[0], val, 9.5)
            doc.add_paragraph()
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl, txt = len(m.group(1)), m.group(2)
            if lvl == 1:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(txt)
                _font(r, 17, True)
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(12)
            else:
                p = doc.add_paragraph()
                r = p.add_run(txt)
                _font(r, {2: 13.5, 3: 11.5, 4: 10.5}.get(lvl, 10.5), True)
                p.paragraph_format.space_before = Pt(10 if lvl == 2 else 6)
                p.paragraph_format.space_after = Pt(4)
            i += 1
            continue

        # 列表
        m = re.match(r"^(\d+)[.、)]\s+(.*)$", s)
        if m:
            p = doc.add_paragraph(style="List Number")
            add_inline(p, m.group(2))
            i += 1
            continue
        if re.match(r"^[-*+]\s+", s):
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, re.sub(r"^[-*+]\s+", "", s))
            i += 1
            continue

        # 正文
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(5)
        p.paragraph_format.line_spacing = 1.35
        add_inline(p, s)
        i += 1

    doc.save(out_path)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".docx"
    convert(src, dst)
    print("OK", dst, os.path.getsize(dst), "bytes")
