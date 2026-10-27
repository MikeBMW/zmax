#!/usr/bin/env python3
"""Markdown → PDF（A4 中文文档版式）

链路：md → HTML(自带 style) → odt → pdf（LibreOffice）
- 中文字体交给系统字体族（WenQuanYi Zen Hei / Noto Sans CJK SC），不写死 ttf 路径
- 每次转换用独立临时 profile，避免并发 soffice 抢同一个 profile 静默失败
- 出稿自检：pdftotext 抠回文字，断言中文成串 + 无 markdown 标记残留

用法:
    md2pdf.py --in a.md --out b.pdf [--title "文档标题"] [--subtitle "副标题"]
"""
import argparse
import html
import os
import re
import subprocess
import sys
import tempfile

CSS = """
@page { size: A4; margin: 18mm 15mm 16mm 15mm; }
body { font-family: "WenQuanYi Zen Hei","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",sans-serif;
       font-size: 10.5pt; line-height: 1.58; color: #1c1c1c; }
h1 { font-size: 20pt; color: #1F4E79; margin: 0 0 4pt; line-height: 1.3;
     border-bottom: 2.4pt solid #FFC000; padding-bottom: 5pt; }
h2 { font-size: 14pt; color: #1F4E79; margin: 15pt 0 6pt; line-height: 1.35;
     border-left: 3.5pt solid #FFC000; padding-left: 7pt; }
h3 { font-size: 11.5pt; color: #2E5F8A; margin: 11pt 0 4pt; }
h4 { font-size: 10.5pt; color: #33475b; margin: 8pt 0 3pt; }
p  { margin: 0 0 6pt; text-align: justify; }
.subtitle { font-size: 10.5pt; color: #5a6b7c; margin: 2pt 0 12pt; }
blockquote { margin: 7pt 0; padding: 6pt 9pt; background: #F5F7FA;
             border-left: 2.2pt solid #B9C4D0; color: #44515f; font-size: 9.5pt; }
blockquote p { margin: 0 0 3pt; }
code { font-family: "DejaVu Sans Mono",monospace; background: #F2F4F6; padding: 0 2pt; font-size: 9pt; }
pre  { background: #F7F9FB; border: 0.5pt solid #DDE3EA; padding: 6pt 8pt;
       font-family: "DejaVu Sans Mono",monospace; font-size: 8.6pt; line-height: 1.4; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.3pt; }
th { background: #1F4E79; color: #ffffff; padding: 4.5pt 6pt; text-align: left; font-weight: bold; }
td { border-bottom: 0.5pt solid #D5DBE3; padding: 4pt 6pt; vertical-align: top; }
hr { border: none; border-top: 0.6pt solid #C9D1DA; margin: 12pt 0; }
ul, ol { margin: 0 0 7pt; padding-left: 17pt; }
li { margin: 0 0 2.5pt; }
b, strong { color: #14283c; }
"""


def inline(s: str) -> str:
    """行内标记：先 escape 再替换（顺序反了标记会被转义掉）"""
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", s)
    return s


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out = []
    i = 0
    in_code = False
    in_table = False
    list_open = None

    def close_list():
        nonlocal list_open
        if list_open:
            out.append("</%s>" % list_open)
            list_open = None

    def close_table():
        nonlocal in_table
        if in_table:
            out.append("</table>")
            in_table = False

    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()

        if stripped.startswith("```"):
            close_list(); close_table()
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(html.escape(ln))
            i += 1
            continue

        if stripped.startswith("|"):
            close_list()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join("<th>%s</th>" % inline(c) for c in cells) + "</tr>")
            elif all(set(c) <= set("-: ") and c for c in cells):
                pass                                  # 分隔行丢弃
            else:
                out.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in cells) + "</tr>")
            i += 1
            continue
        close_table()

        if stripped == "":
            close_list()
            i += 1
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            close_list()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            i += 1
            continue

        if re.match(r"^\s*(---|\*\*\*|___)\s*$", ln):
            close_list()
            out.append("<hr/>")
            i += 1
            continue

        if stripped.startswith(">"):
            close_list()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote>" + "".join("<p>%s</p>" % inline(b) for b in buf if b) + "</blockquote>")
            continue

        mu = re.match(r"^\s*[-*+]\s+(.*)$", ln)
        mo = re.match(r"^\s*\d+[.)]\s+(.*)$", ln)
        if mu or mo:
            want = "ul" if mu else "ol"
            if list_open != want:
                close_list()
                out.append("<%s>" % want)
                list_open = want
            out.append("<li>%s</li>" % inline((mu or mo).group(1)))
            i += 1
            continue

        close_list()
        out.append("<p>%s</p>" % inline(ln))
        i += 1

    close_list()
    close_table()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("%s\n%s\n%s" % (" ".join(cmd), r.stdout[-800:], r.stderr[-800:]))
    return r


def convert(md_path, pdf_path, title=None, subtitle=None):
    md = open(md_path, encoding="utf-8").read()
    body = md_to_html(md)
    doc_title = title or ""
    if subtitle:
        sub = '<div class="subtitle">%s</div>' % inline(subtitle)
        pos = body.find("</h1>")
        body = (body[:pos + 5] + "\n" + sub + body[pos + 5:]) if pos >= 0 else (sub + "\n" + body)
    page = ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>%s</title>"
            "<style>%s</style></head><body>%s</body></html>"
            % (html.escape(doc_title), CSS, body))

    work = tempfile.mkdtemp(prefix="md2pdf_")
    profile = "file://" + os.path.join(work, "lo_profile")
    html_path = os.path.join(work, "doc.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)

    base = ["soffice", "--headless", "--norestore",
            "-env:UserInstallation=" + profile]
    run(base + ["--convert-to", "odt", "--outdir", work, html_path])
    odt = os.path.join(work, "doc.odt")
    if not os.path.exists(odt):
        raise RuntimeError("odt 没生成：%s" % work)
    run(base + ["--convert-to", "pdf", "--outdir", work, odt])

    out_pdf = os.path.join(work, "doc.pdf")
    if not os.path.exists(out_pdf):
        raise RuntimeError("pdf 没生成：%s" % work)
    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)), exist_ok=True)
    with open(out_pdf, "rb") as src, open(pdf_path, "wb") as dst:
        dst.write(src.read())
    return pdf_path


def selfcheck(pdf_path):
    """抠字自检：中文成串 + 无 markdown 标记残留 + 页数"""
    info = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True).stdout
    pages = re.search(r"Pages:\s+(\d+)", info)
    txt = subprocess.run(["pdftotext", pdf_path, "-"], capture_output=True, text=True).stdout
    cjk = len(re.findall(r"[\u4e00-\u9fff]", txt))
    stray = {m: txt.count(m) for m in ("**", "```", "##", "| ---")}
    stray = {k: v for k, v in stray.items() if v}
    return {
        "pages": int(pages.group(1)) if pages else None,
        "chars": len(txt),
        "cjk": cjk,
        "stray_markup": stray,
        "bytes": os.path.getsize(pdf_path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        sys.exit("找不到源文件: %s" % a.src)

    out = convert(a.src, a.dst, a.title, a.subtitle)
    chk = selfcheck(out)
    print("PDF:", out)
    print("  页数 %s · 提取字符 %d · 中文字 %d · 大小 %.1f KB"
          % (chk["pages"], chk["chars"], chk["cjk"], chk["bytes"] / 1024))
    if chk["stray_markup"]:
        print("  ⚠️ markdown 标记残留:", chk["stray_markup"])
    if chk["cjk"] < 200:
        print("  ⚠️ 中文字太少，可能字体/编码有问题")
    return 0 if chk["cjk"] >= 200 and not chk["stray_markup"] else 1


if __name__ == "__main__":
    sys.exit(main())
