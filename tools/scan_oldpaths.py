#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_oldpaths.py — 精确列出**可执行代码区**里的老路径写法(2026-10-08)

只扫会被真跑的目录(tools/ src/ hermes/ web/ config/ configs/ .github/ + 仓库根脚本),
不扫 docs/(历史留档, 按纪律不改)。输出 file:line + 原写法 + 命中类别, 供逐条修。
用法: python3 tools/scan_oldpaths.py [--json]
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIRS = ("tools/", "src/", "hermes/", "web/", "config/", "configs/", ".github/")
EXT = (".py", ".sh", ".bash", ".json", ".yaml", ".yml", ".html", ".php", ".service", ".desktop")

# 老路径风格 -> 说明。命中即"整合后指错地方"。
PATS = [
    (re.compile(r'Path\.home\(\)\s*/\s*"zmax_data"'), "5th-zmax_data", 'Path.home()/"zmax_data" ⇒ 应指 <仓库根>/zmax_data'),
    (re.compile(r'Path\.home\(\)\s*/\s*"lerobot-smolvla-lew"'), "5th-fork", 'Path.home()/"lerobot-smolvla-lew" ⇒ 应指 <仓库根>/external/lerobot-smolvla-lew'),
    (re.compile(r'expanduser\(\s*"~"\s*\)\s*,\s*"zmax_data"'), "4th-zmax_data", 'join(expanduser("~"),"zmax_data") ⇒ 应指 <仓库根>/zmax_data'),
    (re.compile(r'expanduser\(\s*"~"\s*\)\s*,\s*"lerobot-smolvla-lew"'), "4th-fork", 'join(expanduser("~"),"lerobot-smolvla-lew") ⇒ <仓库根>/external/...'),
    (re.compile(r'os\.environ(?:\.get)?\(\s*"HOME"[^)]*\)\s*,\s*"zmax_data"'), "5th-env-zmax_data", 'join(os.environ["HOME"],"zmax_data") ⇒ <仓库根>/zmax_data'),
    (re.compile(r'"/home/ubuntu/zmax_data(?![a-z_])'), "flat-abs", '老扁平绝对路径 /home/ubuntu/zmax_data ⇒ /home/ubuntu/zmax/zmax_data'),
    (re.compile(r'"/home/ubuntu/lerobot-smolvla-lew'), "fork-abs", '老 fork 绝对路径 ⇒ /home/ubuntu/zmax/external/lerobot-smolvla-lew'),
    (re.compile(r'"~/zmax_data'), "flat-tilde", '老扁平 ~/zmax_data ⇒ ~/zmax/zmax_data'),
    (re.compile(r'"~/lerobot-smolvla-lew'), "fork-tilde", '老 fork ~/lerobot-smolvla-lew ⇒ ~/zmax/external/lerobot-smolvla-lew'),
    (re.compile(r'"/home/ubuntu/zmax_rel\b'), "old-root", '老工程根 zmax_rel ⇒ /home/ubuntu/zmax'),
]


def main():
    hits = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in {".git", "zmax_data", "external", "venvs", "toolchains", "node_modules", "__pycache__"}]
        rel_root = os.path.relpath(root, REPO) + os.sep
        if not (rel_root.startswith(CODE_DIRS) or root == REPO):
            continue
        for fn in files:
            if not fn.endswith(EXT):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, REPO)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                lines = open(p, encoding="utf-8", errors="replace").read().split("\n")
            except OSError:
                continue
            for i, l in enumerate(lines, 1):
                s = l.strip()
                if s.startswith("#") or s.startswith(">") or s.startswith("//"):
                    continue  # 注释/文档串不算(但注意: 有些文件整块是说明)
                for rx, tag, why in PATS:
                    if rx.search(l):
                        hits.append({"f": rel, "n": i, "tag": tag, "why": why, "l": s[:130]})
    if "--json" in sys.argv:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
    else:
        print("代码区老路径命中 %d 条:" % len(hits))
        cur = None
        for h in sorted(hits, key=lambda x: (x["f"], x["n"])):
            if h["f"] != cur:
                cur = h["f"]
                print("\n  %s" % cur)
            print("    %-4s [%-16s] %s" % (h["n"], h["tag"], h["l"]))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
