#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""z700_docx.py —— Z700 交付文档生成器(Word)

生成三份:
  01_Z700精细操作机器人_解决方案.docx     主文档, 最详细
  02_Z700_立项报告.docx                   立项决策用
  03_Z700_竞品分析报告.docx               竞品对标

设计纪律:
  · 所有性能数字来自 outputs/z700/metrics.json(实测) 或明确标"待实测"
  · 表格用真表格, 不用缩进伪表格
  · 中文排版: 微软雅黑正文, 标题分级, 页码
"""
import datetime
import json
import os
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z700_features import ARRAYS, all_features                       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "outputs", "z700")
VERSION = "5.50.E-R1"
TODAY = datetime.date.today().isoformat()
CN = "微软雅黑"


# ═══════════════════════════════════════════════════════════════════════════
# 文档构建器
# ═══════════════════════════════════════════════════════════════════════════
class Doc:
    def __init__(self, code="", title="", subtitle="", secret="内部"):
        self.d = Document()
        self._base_style()
        self.code, self.title, self.subtitle, self.secret = code, title, subtitle, secret
        self.h1 = 0
        self.h2 = 0

    # ── 基础样式 ──
    def _base_style(self):
        st = self.d.styles["Normal"]
        st.font.name = CN
        st.font.size = Pt(10.5)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        pf = st.paragraph_format
        pf.line_spacing = 1.45
        pf.space_after = Pt(4)
        for s in self.d.sections:
            s.top_margin = Cm(2.2)
            s.bottom_margin = Cm(2.0)
            s.left_margin = Cm(2.4)
            s.right_margin = Cm(2.0)

    # ── 封面 ──
    def cover(self):
        d = self.d
        for _ in range(3):
            d.add_paragraph()
        p = d.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(self.title)
        r.font.size = Pt(26)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)

        if self.subtitle:
            p = d.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(self.subtitle)
            r.font.size = Pt(14)
            r.font.color.rgb = RGBColor(0x2E, 0x5A, 0x9A)
            r.font.name = CN
            r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)

        for _ in range(6):
            d.add_paragraph()

        rows = [
            ("文档编号", self.code),
            ("版本", VERSION),
            ("密级", self.secret),
            ("编制日期", TODAY),
            ("编制单位", "Z-MAX 产品与工程中心"),
            ("适用范围", "光模块生产工厂 · 精细操作工位"),
        ]
        t = d.add_table(rows=len(rows), cols=2)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        for i, (k, v) in enumerate(rows):
            t.rows[i].cells[0].width = Cm(4.0)
            t.rows[i].cells[1].width = Cm(9.5)
            self._cell(t, i, 0, k, bold=True, shade="EAF0F8")
            self._cell(t, i, 1, v)
        d.add_page_break()

    def _cell(self, t, i, j, text, bold=False, shade=None, size=9.5, color=None):
        c = t.rows[i].cells[j]
        c.text = ""
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.15
        r = p.add_run(str(text) if text is not None else "")
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        if color:
            r.font.color.rgb = color
        if shade:
            tcPr = c._tc.get_or_add_tcPr()
            sh = OxmlElement("w:shd")
            sh.set(qn("w:fill"), shade)
            tcPr.append(sh)

    # ── 标题 ──
    def H1(self, text):
        self.h1 += 1
        self.h2 = 0
        d = self.d
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(16)
        p.paragraph_format.space_after = Pt(8)
        r = p.add_run("%d  %s" % (self.h1, text))
        r.font.size = Pt(16)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        # 下边框
        pPr = p._p.get_or_add_pPr()
        pbdr = OxmlElement("w:pBdr")
        bot = OxmlElement("w:bottom")
        bot.set(qn("w:val"), "single")
        bot.set(qn("w:sz"), "10")
        bot.set(qn("w:color"), "2E5A9A")
        pbdr.append(bot)
        pPr.append(pbdr)
        return p

    def H2(self, text):
        self.h2 += 1
        d = self.d
        p = d.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run("%d.%d  %s" % (self.h1, self.h2, text))
        r.font.size = Pt(12.5)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x2E, 0x5A, 0x9A)
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        return p

    def H3(self, text):
        p = self.d.add_paragraph()
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(text)
        r.font.size = Pt(11)
        r.font.bold = True
        r.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        return p

    # ── 正文 ──
    def P(self, text, size=10.5, bold=False, color=None, indent=True, align=None):
        p = self.d.add_paragraph()
        if indent:
            p.paragraph_format.first_line_indent = Cm(0.74)
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        if color:
            r.font.color.rgb = color
        return p

    def BULLET(self, text, size=10.5, level=0):
        p = self.d.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.74 + 0.6 * level)
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(("· " if level == 0 else "– ") + text)
        r.font.size = Pt(size)
        r.font.name = CN
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        return p

    def NOTE(self, text):
        """提示框(浅底)。"""
        p = self.d.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        r = p.add_run(text)
        r.font.size = Pt(9.5)
        r.font.name = CN
        r.font.color.rgb = RGBColor(0x8B, 0x4A, 0x00)
        r._element.rPr.rFonts.set(qn("w:eastAsia"), CN)
        pPr = p._p.get_or_add_pPr()
        sh = OxmlElement("w:shd")
        sh.set(qn("w:fill"), "FFF6E0")
        pPr.append(sh)
        return p

    # ── 表格 ──
    def TABLE(self, headers, rows, widths=None, size=9, head_shade="2E5A9A",
              zebra=True, align_center_cols=None):
        n = len(headers)
        t = self.d.add_table(rows=1, cols=n)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        if widths:
            for j, w in enumerate(widths):
                for cell in t.columns[j].cells:
                    cell.width = Cm(w)
        for j, h in enumerate(headers):
            self._cell(t, 0, j, h, bold=True, shade=head_shade, size=size,
                       color=RGBColor(0xFF, 0xFF, 0xFF))
        for i, row in enumerate(rows, 1):
            cells = t.add_row().cells
            for j, v in enumerate(row):
                self._cell(t, i, j, v, size=size,
                           shade=("F7F9FC" if (zebra and i % 2 == 0) else None))
            if widths:
                for j, w in enumerate(widths):
                    cells[j].width = Cm(w)
            if align_center_cols:
                for j in align_center_cols:
                    for p in cells[j].paragraphs:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)
        return t

    # ── 页码 ──
    def page_numbers(self):
        for s in self.d.sections:
            footer = s.footer
            p = footer.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run()
            r.font.size = Pt(9)
            r.font.name = CN
            fld = OxmlElement("w:fldSimple")
            fld.set(qn("w:instr"), "PAGE")
            r._r.addnext(fld)
            r2 = p.add_run(" / ")
            r2.font.size = Pt(9)
            fld2 = OxmlElement("w:fldSimple")
            fld2.set(qn("w:instr"), "NUMPAGES")
            r2._r.addnext(fld2)

    def save(self, path):
        self.page_numbers()
        self.d.save(path)
        return path


# ═══════════════════════════════════════════════════════════════════════════
# 公共素材
# ═══════════════════════════════════════════════════════════════════════════
def load():
    met = json.load(open(os.path.join(OUT, "metrics.json"), encoding="utf-8"))
    feats = all_features()
    return met, feats


def gantt_rows():
    """14 段甘特(实测)。"""
    p = os.path.join(REPO, "zmax_data", "runs", "replay215_20261115_225309",
                     "derived", "seg_stats.json")
    d = json.load(open(p, encoding="utf-8"))
    total = d["total_s"]
    out = []
    for s in d["segments"]:
        out.append([s["name"], "#%d-%d" % (s["i0"], s["i1"]), str(s["n"]),
                    "%.2f" % s["dur_s"], "%.1f%%" % (100.0 * s["dur_s"] / total),
                    "%.3f" % s["per_pt_s"],
                    "%.0f" % (s.get("path_mm") or 0),
                    "%.1f" % ((s.get("path_mm") or 0) / s["dur_s"] if s["dur_s"] else 0)])
    return out, total


def std_rows():
    sp = os.path.join(OUT, "standards_rows.json")
    if os.path.exists(sp):
        try:
            return [list(x) for x in json.load(open(sp, encoding="utf-8"))]
        except Exception:                                                # noqa: BLE001
            pass
    from z700_xlsx import DEFAULT_STD                                    # noqa: PLC0415
    return [list(x) for x in DEFAULT_STD]
