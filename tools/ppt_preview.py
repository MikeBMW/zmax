#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ppt_preview.py — 把交付目录里的 .pptx 转成幻灯片 PNG 供网页/控制台预览。

设计原则（老倪口径：点了必出结果、可导出、不虚构）：
- **只读** pptx：先 soffice 转 pdf（子进程，超时保护），再 pdftoppm 转 png；原始 pptx 一个字节都不改。
- **按 mtime 缓存**：缓存键 = 文件名 + mtime + size，pptx 改了自动重转；不重复消耗 CPU。
- **诚实失败**：soffice/pdftoppm 缺失或无输出 ⇒ 抛异常，调用方把原因原样给页面，不显示假页数。
- 文件名只取 basename + 白名单后缀，防路径穿越。

用法：
    from ppt_preview import list_decks, deck_meta, slide_path
    list_decks()                       -> [dict(name, path, size, mtime, slides(可空))]
    deck_meta(name, convert=True)      -> dict(name, slides, pages[..png], cached, err)
    slide_path(name, n)                -> png 绝对路径
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import tempfile

DATA = os.path.expanduser("~/zmax_data")
DELIV_ROOTS = [os.path.join(DATA, "deliverables"), os.path.join(DATA, "reports")]
CACHE = os.path.join(DATA, "eval", "ppt_cache")
TAIL = os.path.join(tempfile.gettempdir(), "zmax_ppt_tail")
MAX_DECKS = 40
SAFE = re.compile(r"^[^/\\.][^/\\]*\.pptx?$", re.I)


def _safe(name: str) -> bool:
    return bool(name) and bool(SAFE.match(name)) and ".." not in name


def list_decks() -> list[dict]:
    """扫描交付目录下所有 pptx（按 mtime 倒序，最多 MAX_DECKS 个）。"""
    out = []
    for root in DELIV_ROOTS:
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if not d.startswith(".") and d != "ppt_cache"]
            depth = dp[len(root):].count(os.sep)
            if depth > 3:
                dns[:] = []
                continue
            for fn in fns:
                if not fn.lower().endswith((".pptx", ".ppt")):
                    continue
                fp = os.path.join(dp, fn)
                try:
                    stt = os.stat(fp)
                except OSError:
                    continue
                out.append(dict(name=fn, path=fp, dir=dp, size=stt.st_size, mtime=stt.st_mtime))
    out.sort(key=lambda d: -d["mtime"])
    return out[:MAX_DECKS]


def _find(name: str) -> dict | None:
    for d in list_decks():
        if d["name"] == name:
            return d
    return None


def _cache_dir(d: dict) -> str:
    key = "%s_%d_%d" % (re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "_", os.path.splitext(d["name"])[0]),
                        int(d["mtime"]), d["size"])
    return os.path.join(CACHE, key[:120])


def _run(cmd, timeout=180):
    os.makedirs(TAIL, exist_ok=True)
    with open(os.path.join(TAIL, "ppt_preview.log"), "ab") as f:
        f.write(("\n$ " + " ".join(cmd) + "\n").encode())
        f.flush()
        p = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode


def deck_meta(name: str, convert: bool = True) -> dict:
    """返回该 pptx 的页信息；convert=True 时按需转换并缓存。"""
    if not _safe(name):
        return dict(name=name, ok=False, err="文件名不合法", slides=0, pages=[])
    d = _find(name)
    if not d:
        return dict(name=name, ok=False, err="交付目录里没有这个文件", slides=0, pages=[])
    cd = _cache_dir(d)
    meta_f = os.path.join(cd, "meta.json")
    if os.path.isfile(meta_f):
        try:
            m = json.load(open(meta_f, encoding="utf-8"))
            if m.get("slides") and all(os.path.isfile(os.path.join(cd, p)) for p in m["pages"]):
                m.update(cached=True, path=d["path"], size=d["size"], mtime=d["mtime"])
                return m
        except Exception:                                                       # noqa: BLE001
            pass
    if not convert:
        return dict(name=name, ok=True, cached=False, slides=0, pages=[], path=d["path"],
                    size=d["size"], mtime=d["mtime"])
    if not (shutil.which("soffice") and shutil.which("pdftoppm")):
        return dict(name=name, ok=False, err="本机缺 soffice 或 pdftoppm，无法生成预览",
                    slides=0, pages=[], path=d["path"])
    os.makedirs(cd, exist_ok=True)
    pdf = os.path.join(cd, "deck.pdf")
    try:
        rc = _run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", cd, d["path"]], timeout=300)
        made = [f for f in os.listdir(cd) if f.lower().endswith(".pdf")]
        if rc != 0 or not made:
            return dict(name=name, ok=False, err="soffice 转 PDF 失败 (rc=%s)" % rc, slides=0,
                        pages=[], path=d["path"])
        got = os.path.join(cd, made[0])
        if got != pdf and not os.path.isfile(pdf):
            os.replace(got, pdf)
        rc = _run(["pdftoppm", "-r", "110", "-png", pdf, os.path.join(cd, "s")], timeout=300)
        pages = sorted(f for f in os.listdir(cd) if re.match(r"^s-?\d+\.png$", f))
        if rc != 0 or not pages:
            return dict(name=name, ok=False, err="pdftoppm 出图失败 (rc=%s)" % rc, slides=0,
                        pages=[], path=d["path"])
        m = dict(name=name, ok=True, cached=False, slides=len(pages), pages=pages,
                 path=d["path"], size=d["size"], mtime=d["mtime"], dir=d["dir"])
        json.dump(m, open(meta_f, "w"), ensure_ascii=False)
        return m
    except subprocess.TimeoutExpired:
        return dict(name=name, ok=False, err="转换超时 (pptx 太大或 soffice 卡住)", slides=0,
                    pages=[], path=d["path"])


def slide_path(name: str, n: int) -> str | None:
    d = _find(name)
    if not d:
        return None
    m = deck_meta(name, convert=True)
    if not m.get("ok") or not m.get("pages"):
        return None
    if n < 1 or n > len(m["pages"]):
        return None
    p = os.path.join(_cache_dir(d), m["pages"][n - 1])
    return p if os.path.isfile(p) else None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        for d in list_decks():
            print("%-60s %8.1fKB  %s" % (d["name"], d["size"] / 1024, d["dir"]))
    else:
        for d in list_decks():
            m = deck_meta(d["name"])
            print(d["name"], "->", m.get("slides"), "slides", m.get("err") or "ok")
            print("   ", (m.get("pages") or [])[:3])
