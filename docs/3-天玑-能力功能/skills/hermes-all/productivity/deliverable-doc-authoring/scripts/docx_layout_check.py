#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docx 落版体检：转 PDF，逐页查越界 / 表注孤立 / 页数 / 内嵌图数。

用法:
    python3 docx_layout_check.py 交付.docx [--expect-pages 21] [--keep-pdf]

检查项（默认容差按 A4 + 2.2cm 页边距）:
    overflow    文字框越过右/下边界的词数            判据 = 0
    cap_orphan  页首第一行就是「表 x-y / 图 x-y」表注  判据 = 0
    pages       页数；给了 --expect-pages 必须相等
    media       docx 内嵌图片数（只报数，供与图注数对账）

退出码: overflow>0 或 cap_orphan>0 或 页数不符 -> 1
依赖: soffice / pdftotext (poppler-utils)
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', re.S)
CAP_RE = re.compile(r'^(表|图)\s*[0-9A-Z]+[.\-\u2013][0-9]+')


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("命令失败: %s\n%s" % (" ".join(cmd), (r.stderr or "")[-800:]))
    return r.stdout


def to_pdf(docx, outdir):
    prof = os.path.join(outdir, "lo_profile")
    sh(["soffice", "--headless", "--norestore",
        "-env:UserInstallation=file://" + prof,
        "--convert-to", "pdf", "--outdir", outdir, os.path.abspath(docx)])
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(docx))[0] + ".pdf")
    if not os.path.exists(pdf):
        sys.exit("转换后找不到 PDF: " + pdf)
    return pdf


def pages_of(pdf):
    xml = sh(["pdftotext", "-bbox", pdf, "-"])
    pages = []
    for w, h, body in PAGE_RE.findall(xml):
        words = [(float(a), float(b), float(c), float(d), t)
                 for a, b, c, d, t in WORD_RE.findall(body)]
        pages.append((float(w), float(h), words))
    return pages


def first_line(words, tol=9.0):
    if not words:
        return ""
    y0 = min(x[1] for x in words)
    line = sorted([x for x in words if x[1] - y0 <= tol], key=lambda x: x[0])
    return "".join(x[4] for x in line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--margin-pt", type=float, default=58.0, help="右边界容差(pt)")
    ap.add_argument("--bottom-pt", type=float, default=30.0, help="下边界容差(pt)，留给页码")
    ap.add_argument("--expect-pages", type=int)
    ap.add_argument("--keep-pdf", action="store_true")
    a = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="docxchk_")
    try:
        pdf = to_pdf(a.docx, tmp)
        pages = pages_of(pdf)

        over_hits, orphans = [], []
        for i, (w, h, words) in enumerate(pages, 1):
            over = [x for x in words if x[2] > w - a.margin_pt or x[3] > h - a.bottom_pt]
            if over:
                over_hits.append((i, len(over), "".join(x[4] for x in over[:8])))
            fl = first_line(words)
            if CAP_RE.match(fl):
                orphans.append((i, fl))

        print("页数: %d" % len(pages))
        for i, (_w, _h, words) in enumerate(pages, 1):
            print("  p%02d 首行: %s" % (i, first_line(words)[:60]))

        print("越界词: %d 页受影响" % len(over_hits))
        for i, n, s in over_hits:
            print("  p%02d %d 词越界: %s" % (i, n, s))

        print("表注/图注孤立在页首: %d" % len(orphans))
        for i, s in orphans:
            print("  p%02d %s" % (i, s[:60]))

        try:
            with zipfile.ZipFile(a.docx) as z:
                media = [n for n in z.namelist() if n.startswith("word/media/")]
            print("内嵌图片: %d 个" % len(media))
        except Exception as e:  # noqa: BLE001
            print("读 docx 失败: %s" % e)

        fail = bool(over_hits or orphans)
        if a.expect_pages and len(pages) != a.expect_pages:
            print("页数不符: 期望 %d 实际 %d" % (a.expect_pages, len(pages)))
            fail = True
        if a.keep_pdf:
            print("PDF: " + pdf)
        print("结果:", "FAIL" if fail else "PASS")
        return 1 if fail else 0
    finally:
        if not a.keep_pdf:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
