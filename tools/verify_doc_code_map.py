#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_doc_code_map.py — 核 docs/0-总纲/CODE-MAP.md 的「文档 ↔ 代码」映射是否真成立

老倪 2026-11-11「你要保证工程文档与代码的映射」——
所以这件事不能靠人肉维护表格，必须有校验器：表里每一行都要能落到真实文件、真实符号。

判据
----
· 代码列路径不存在            → FAIL
· 符号列(--strict) 在该文件里找不到 → FAIL
· 文档列路径不存在            → WARN (文档可能已归档, 不算代码错)
· 符号是裸 `def`/`class` 占位  → WARN (说明该行还没细化到具体函数, 是待办)

用法
----
    gui-venv311/bin/python tools/verify_doc_code_map.py
    gui-venv311/bin/python tools/verify_doc_code_map.py --strict
    gui-venv311/bin/python tools/verify_doc_code_map.py --json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP = os.path.join(ROOT, "docs", "0-总纲", "CODE-MAP.md")

# 小节标题 → 概念域
SEC = re.compile(r"^##\s+([A-Z])\s+·\s+(.+)$")
ROW = re.compile(r"^\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|$")


def _clean(cell: str) -> str:
    return cell.strip().strip("`").strip()


def _doc_exists(cell: str) -> tuple[bool, str]:
    """文档列可能带 * 通配或只给目录。"""
    c = _clean(cell)
    # _clean 在「`path` §4.2」这种写法下会把尾注一起带进来: 截到空白/反引号为止
    c = c.split("`")[0].split(" ")[0].strip()
    if not c or c in ("—", "-"):
        return True, "空"
    if c.startswith("同上"):          # 表格里用「同上」继承上一行, 合法写法
        return True, "继承上一行"
    p = os.path.join(ROOT, "docs", c)
    if "*" in p:
        hits = glob.glob(p)
        return (len(hits) > 0), ("glob %d" % len(hits))
    if os.path.exists(p):
        return True, "ok"
    # 只给了目录名
    d = os.path.join(ROOT, "docs", c.split("/")[0])
    if os.path.isdir(d):
        return False, "目录在但文件缺"
    return False, "缺"


def _sym_exists(path: str, sym: str) -> tuple[bool, str]:
    """符号在文件里真存在（允许 class/def 名或裸关键字）。"""
    s = _clean(sym)
    if not s or s in ("—", "-"):
        return True, "空"
    if s in ("def", "class"):
        return False, "占位(未细化)"
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return False, "读失败: %s" % e
    name = s.replace("class ", "").replace("def ", "").strip()
    # 容忍 `_SS_STATE` 这类模块级常量：直接找字面量
    if re.search(r"(^|\s)(def|class)\s+%s\b" % re.escape(name), txt, re.M):
        return True, "ok"
    if re.search(r"^\s*%s\s*=" % re.escape(name), txt, re.M):
        return True, "ok(常量)"
    if name in txt:
        return True, "ok(串)"
    return False, "符号找不到"


def parse():
    rows = []
    sec = ("?", "未分节")
    for ln in open(MAP, encoding="utf-8"):
        m = SEC.match(ln.strip())
        if m:
            sec = (m.group(1), m.group(2).strip())
            continue
        if not ln.strip().startswith("|"):
            continue
        m = ROW.match(ln.rstrip("\n"))
        if not m:
            continue
        cells = [c for c in m.groups()]
        if _clean(cells[0]) in ("概念", "") or set(_clean(cells[0])) <= set("-: "):
            continue
        row = {"sec": sec[0], "sec_name": sec[1],
               "concept": _clean(cells[0]), "doc": _clean(cells[1]),
               "code": _clean(cells[2]), "sym": _clean(cells[3]),
               "src": _clean(cells[4])}
        # "同上" 继承上一行同列 (表格里大量缩写, 不继承会误报"文档缺")
        if rows:
            for k in ("doc", "code", "src"):
                if row[k] in ("同上", "〃", "同上。"):
                    row[k] = rows[-1][k]
        rows.append(row)
    return rows


def check(strict: bool):
    rows = parse()
    fails, warns = [], []
    for r in rows:
        cp = os.path.join(ROOT, r["code"]) if r["code"] and r["code"] not in ("—", "-") else ""
        code_ok = bool(cp) and os.path.exists(cp)
        if not code_ok:
            fails.append(dict(r, why="代码路径不存在", got=r["code"]))
            continue
        if strict:
            ok, why = _sym_exists(cp, r["sym"])
            if not ok:
                (fails if why != "占位(未细化)" else warns).append(dict(r, why="符号: " + why))
        okd, whyd = _doc_exists(r["doc"])
        if not okd:
            warns.append(dict(r, why="文档: " + whyd))
    return rows, fails, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="同时核符号")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(MAP):
        print("FAIL: 映射表不存在 %s" % MAP)
        return 2
    rows, fails, warns = check(a.strict)
    if a.json:
        print(json.dumps({"rows": len(rows), "fail": fails, "warn": warns},
                         ensure_ascii=False, indent=1, default=str))
        return 0 if not fails else 1

    by = {}
    for r in rows:
        by.setdefault(r["sec"], []).append(r)
    print("映射表: %s" % os.path.relpath(MAP, ROOT))
    print("共 %d 行，%d 个概念域: %s" % (
        len(rows), len(by), ", ".join("%s·%s(%d)" % (k, by[k][0]["sec_name"], len(by[k])) for k in sorted(by))))
    print("-" * 68)
    for k in sorted(by):
        ok = sum(1 for r in by[k] if os.path.exists(os.path.join(ROOT, r["code"])))
        print("  %s · %-14s %d/%d 代码路径存在" % (k, by[k][0]["sec_name"], ok, len(by[k])))
    print("-" * 68)
    if fails:
        print("FAIL %d 条:" % len(fails))
        for f in fails:
            print("  [%s] %s → %s  (%s)" % (f["sec"], f["concept"], f["code"], f["why"]))
    else:
        print("FAIL 0 条 ✓")
    if warns:
        print("WARN %d 条:" % len(warns))
        for w in warns[:12]:
            print("  [%s] %s  (%s)" % (w["sec"], w["concept"], w["why"]))
        if len(warns) > 12:
            print("  … 另 %d 条" % (len(warns) - 12))
    print("-" * 68)
    print("判定: %s" % ("PASS" if not fails else "FAIL"))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
