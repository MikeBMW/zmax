# -*- coding: utf-8 -*-
"""从 PPT 备注导出可打印讲稿（docx）"""
import re
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from pptx import Presentation

SRC = "/home/ubuntu/zmax/zmax_data/deliverables/20261104/Z-MAX总技术手册_5.50.D-M1.pptx"
OUT = "/home/ubuntu/zmax/zmax_data/deliverables/20261104/Z-MAX总技术手册_演讲备注讲稿_288页.docx"

pr = Presentation(SRC)
doc = Document()
st = doc.styles["Normal"]
st.font.name = "宋体"
st.font.size = Pt(10.5)
st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
for s in doc.sections:
    s.top_margin = Cm(2.0); s.bottom_margin = Cm(2.0)
    s.left_margin = Cm(2.2); s.right_margin = Cm(2.2)

h = doc.add_heading("Z-MAX 精细操作机器人 · 总技术手册 5.50.D-M1", level=0)
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
p = doc.add_paragraph("演讲备注讲稿（288 页 · 可照念）")
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.runs[0].font.size = Pt(12)
p = doc.add_paragraph("用法：PPT 每页右下角“备注”已写入同一段文字。讲稿按篇分节，每页一行页码 + 一句标题 + 备注正文；"
                      "平均每页 20-30 秒，全册约 80-95 分钟。时间紧可跳过第 4 篇技术史与第 10 篇附录。")
p.runs[0].font.size = Pt(9)
p.runs[0].font.color.rgb = RGBColor(0x55, 0x55, 0x55)

PART_NAME = {}


def slide_meta(s):
    ts = [sh.text_frame.text.strip() for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
    ch, title = "", ""
    for t in ts:
        m = re.match(r"^(\d+)\.(\d\d)$", t)
        if m:
            ch = t
            break
    if ch:
        for i, t in enumerate(ts):
            if re.match(r"^(\d+)\.(\d\d)$", t) and i + 1 < len(ts):
                title = ts[i + 1]
                break
    elif len(ts) >= 2:
        title = ts[1] if ts[0].isdigit() else ts[0]
    return ch, title


cur_part = None
for i, s in enumerate(pr.slides, 1):
    note = s.notes_slide.notes_text_frame.text.strip() if s.has_notes_slide else ""
    ch, title = slide_meta(s)
    part = int(ch.split(".")[0]) if ch else None
    if part and part != cur_part:
        cur_part = part
        sec = doc.add_paragraph()
        r = sec.add_run(f"\n第 {part} 篇　{title}")
        r.bold = True
        r.font.size = Pt(13)
        r.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
    head = doc.add_paragraph()
    head.paragraph_format.space_before = Pt(7)
    r = head.add_run(f"P{i:03d}" + (f"　{ch}　{title[:34]}" if ch else ""))
    r.bold = True
    r.font.size = Pt(9.5)
    r.font.color.rgb = RGBColor(0x8A, 0x33, 0x11)
    body = doc.add_paragraph(note)
    body.paragraph_format.space_after = Pt(3)

doc.save(OUT)
print("SAVED", OUT, "pages", i)
