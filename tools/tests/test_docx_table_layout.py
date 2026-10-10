#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表格版式判据 (防回退) —— 老倪 2026-10-10: 「表格显示的非常不友好，用眼睛看非常费劲」

踩过的坑: **只设置 cell.width(tcW) 不写 tblLayout=fixed + tblGrid, Word/LibreOffice 会按等分排**
⇒ "五列表一律 20%"、"两列表 50:50"、逐行末字孤行。本测试把列宽真生效这件事做成硬判据。

判据:
  1. 每张表都有 w:tblLayout=fixed (否则列宽配置等于没写)
  2. 两列表左右比例 ≥ 2:1 (左标签窄、右长文本宽), 不是 50:50
  3. 没有内容完全重复的列 (4.2 表曾出现"名称"与"引擎模块"两列一模一样)
  4. 每行有 w:cantSplit (行内不许跨页断, 否则出现孤儿碎片)
  5. 每张表表头都有深色底 (可读性底座)
用法: gui-venv311/bin/python tools/tests/test_docx_table_layout.py
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

HEAD_FILLS = ("1F3864",)
FAIL = []


def _has(x):
    return subprocess.run(["bash", "-lc", "command -v %s" % x], capture_output=True).returncode == 0


def _to_pdf(docx):
    out = os.path.dirname(docx)
    subprocess.run(["bash", "-lc",
                    "rm -f '%s'/*.pdf; timeout 240 soffice --headless -env:UserInstallation=file:///tmp/lo_profile "
                    "--convert-to pdf --outdir '%s' '%s' >/dev/null 2>&1" % (out, out, docx)])
    p = glob.glob(os.path.join(out, "*.pdf"))
    return p[0] if p else ""


def _pdf_pages(pdf):
    if not pdf:
        return []
    txt = subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout
    pages = txt.split("\f")
    return [re.sub(r"\s+", "", p) for p in pages if p.strip()]


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ⛔ ") + name + ("   " + str(detail) if detail else ""))
    if not ok:
        FAIL.append(name)


def tbl_layout(t):
    e = t._tbl.tblPr.find(qn("w:tblLayout"))
    return e.get(qn("w:type")) if e is not None else None


def grid_cm(t):
    g = t._tbl.find(qn("w:tblGrid"))
    if g is None:
        return []
    return [round(int(c.get(qn("w:w"))) / 567.0, 2) for c in g.findall(qn("w:gridCol"))]


def col_texts(t, i):
    return [r.cells[i].text.strip() for r in t.rows[1:]]


def main():
    print("▶ 先重新生成 SOR (真跑导出器, 不用旧产物)")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sor_export.py")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
        return 1
    d = max(glob.glob(os.path.join(ROOT, "outputs", "sor", "*")), key=os.path.getmtime)
    f = [x for x in glob.glob(os.path.join(d, "*.docx"))][0]
    doc = Document(f)
    print("  文档: %s · 表格 %d 张\n" % (os.path.basename(f), len(doc.tables)))

    print("═══ 1) 列宽真生效 (tblLayout=fixed, 且不是等分) ═══")
    bad = [i + 1 for i, t in enumerate(doc.tables) if tbl_layout(t) != "fixed"]
    check("每张表 tblLayout=fixed", not bad, ("缺: 表%s" % bad) if bad else "%d 张全有" % len(doc.tables))

    print("\n═══ 2) 两列表比例 (左窄右宽) ═══")
    twos = [(i + 1, t, grid_cm(t)) for i, t in enumerate(doc.tables) if len(t.columns) == 2]
    for i, t, g in twos:
        if len(g) == 2 and g[0] > 0:
            ratio = g[1] / g[0]
            print(f"      表{i}: 列宽 {g} cm · 右/左 = {ratio:.2f}")
            check(f"表{i} 两列非 50:50", ratio >= 1.9, f"{ratio:.2f}")
    check("存在两列表(判据没空跑)", bool(twos))

    print("\n═══ 3) 无内容完全重复的列 ═══")
    dup_found = []
    for i, t in enumerate(doc.tables):
        n = len(t.columns)
        if n < 2 or len(t.rows) < 3:
            continue
        for a in range(n):
            for b in range(a + 1, n):
                ca, cb = col_texts(t, a), col_texts(t, b)
                if ca and ca == cb:
                    dup_found.append((i + 1, t.rows[0].cells[a].text, t.rows[0].cells[b].text))
    check("没有两列内容完全相同", not dup_found, dup_found[:3])

    print("\n═══ 4) 行内不跨页 (cantSplit) ═══")
    nosplit_missing = []
    for i, t in enumerate(doc.tables):
        for r in t.rows:
            if "w:cantSplit" not in r._tr.xml:
                nosplit_missing.append(i + 1)
                break
    check("每张表每行都有 cantSplit", not nosplit_missing,
          ("缺: 表%s" % sorted(set(nosplit_missing))) if nosplit_missing else "全有")

    print("\n═══ 5) 表头深色底 ═══")
    nofill = []
    for i, t in enumerate(doc.tables):
        tcPr = t.rows[0].cells[0]._tc.find(qn("w:tcPr"))
        shd = tcPr.find(qn("w:shd")) if tcPr is not None else None
        fill = (shd.get(qn("w:fill")) or "").upper() if shd is not None else ""
        if fill not in HEAD_FILLS:
            nofill.append((i + 1, fill))
    check("每张表表头深色底", not nofill, nofill[:3])

    print("\n═══ 6) 出图核验: 整行没被页切开 (真转 PDF 逐页找) ═══")
    if not _has("soffice") or not _has("pdftotext"):
        print("      (跳过: 本机没 soffice/pdftotext)")
    else:
        pdf = _to_pdf(f)
        pages = _pdf_pages(pdf)
        print(f"      PDF {len(pages)} 页 · 逐行检查 首格文本 与 末格文本 是否同页")
        split = []
        checked = 0
        for ti, t in enumerate(doc.tables):
            for ri, row in enumerate(t.rows[1:], start=2):
                a = re.sub(r"\s+", "", row.cells[0].text)
                b = re.sub(r"\s+", "", row.cells[-1].text)
                if len(a) < 4 or len(b) < 4:
                    continue
                pa = [i for i, pg in enumerate(pages) if a in pg]
                pb = [i for i, pg in enumerate(pages) if b in pg]
                if not pa or not pb:
                    continue
                checked += 1
                if not (set(pa) & set(pb)):
                    split.append((ti + 1, ri, a[:18], "p%s" % [x + 1 for x in pa], "p%s" % [x + 1 for x in pb]))
        print(f"      抽检 {checked} 行")
        check("没有整行被页劈开", not split, split[:3])
        # 反向: 判据不能空跑
        check("抽检行数够多(判据没空跑)", checked >= 40, checked)

    print("\n═══ 7) 「指标」列不折行 (第 5.2 指标体系的孤字行根因) ═══")
    # 复核实测: 指标列 4.4cm 时 "插深终到误差 (现有指标 F-A02)" 被折成 "...F-" + "A02)" 孤字行。
    # 判据: 估计单行宽度 ≤ 列宽-边距 (CJK 9.5pt≈3.35mm/字, ASCII≈1.7mm/字, 单元格边距 0.15cm×2)。
    def _est(txt):
        w = 0.0
        for ch in str(txt):
            w += 3.35 if ord(ch) > 0x2000 else 1.7
        return w / 10.0    # mm → cm

    t52 = [t for t in doc.tables if [c.text.strip() for c in t.rows[0].cells][:1] == ["指标"]]
    checked = 0
    worst = ("", 0.0, 0.0)
    for t in t52:
        gw = [int(g.get(qn("w:w")) or 0) / 567.0 for g in t._tbl.find(qn("w:tblGrid"))]  # dxa → cm
        col0 = gw[0] if gw else 0.0
        for r in t.rows[1:]:
            txt = r.cells[0].text.strip()
            if not txt:
                continue
            checked += 1
            if _est(txt) > worst[1]:
                worst = (txt, _est(txt), col0)
            if _est(txt) > col0 - 0.30:
                check("指标列放得下: %r" % txt[:24], False, "估 %.2fcm > 列 %.2fcm-0.30" % (_est(txt), col0))
    check("第 5.2 指标体系表全部检查", len(t52) >= 6, "%d 张" % len(t52))
    check("抽检指标名够多 (判据没空跑)", checked >= 50, checked)
    if checked:
        print("      最宽一条: %r = 估 %.2fcm (列宽 %.2fcm)" % (worst[0][:30], worst[1], worst[2]))

    print("\n" + ("✅ 全部通过" if not FAIL else "⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
