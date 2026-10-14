#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_media_index.py — 盘点 docs/data_snapshots 里的大文件, 生成/刷新 MEDIA-INDEX.md。

口径 (老倪 Git 精简): 图/大二进制**不进代码库** (.gitignore 挡入库), 库里只留可复核清单。
所以这份清单是从**工作区**扫出来的 (不是 `git ls-files` —— 那些文件已不入库), 每行给
名字 + 字节 + sha256(前16), 让人能核"这张图还是当时那张吗"。

用法: ./gui-venv311/bin/python tools/snapshot_media_index.py [--min-kb 200] [--write]
不带 --write 只打印 (dry)。
"""
from __future__ import annotations

import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "docs", "data_snapshots")
OUT = os.path.join(SNAP, "MEDIA-INDEX.md")
SKIP_EXT = {".md", ".json", ".py", ".sh", ".txt", ".csv", ".html", ".js", ".css", ".patch", ".diff"}


def sha16(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def main() -> int:
    min_kb = 200
    if "--min-kb" in sys.argv:
        try:
            min_kb = int(sys.argv[sys.argv.index("--min-kb") + 1])
        except (IndexError, ValueError):
            pass
    write = "--write" in sys.argv
    rows = []
    for dp, _dn, fns in os.walk(SNAP):
        for fn in fns:
            p = os.path.join(dp, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT or fn == "MEDIA-INDEX.md":
                continue
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz < min_kb * 1024:
                continue
            rows.append((os.path.relpath(p, ROOT), sz, sha16(p)))
    rows.sort()
    lines = ["# 现场快照 · 大文件清单 (不入库, 本机原路径可直接看)", "",
             "口径: **图/大二进制不进代码库** (`.gitignore` 挡入库), 库里只留这份可复核清单。",
             "本清单从**工作区**扫出 (`tools/snapshot_media_index.py`), 阈值 %dKB; 文件本身仍在原路径。" % min_kb, "",
             "| 文件 (相对仓库根) | 字节 | sha256(前16) |", "|---|---|---|"]
    for f, sz, h in rows:
        lines.append("| `%s` | %d | `%s` |" % (f, sz, h))
    lines += ["", "刷新: `./gui-venv311/bin/python tools/snapshot_media_index.py --write`", ""]
    txt = "\n".join(lines)
    print(txt[:1200])
    print("... 共 %d 个文件 (>= %dKB)" % (len(rows), min_kb))
    if write:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(txt)
        print("已写 %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
