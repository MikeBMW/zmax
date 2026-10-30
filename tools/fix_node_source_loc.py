#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「右键源码」的落点从 class/def 行改到**真正执行且带 return 的函数行**(老倪 2026-10-31)

问题（实测 78 条外部实现里有 45 条）:
    _EXTERNAL_LOC[key] = (文件, 行, "class Xxx") —— 行号落在 class/def 头上，
    而 class 行只在 import 时执行一次 ⇒ 断点永远不中，看着"代码在跑但不停"。

做法:
    以 reports/node_breakpoints.json 的**真实执行记录**(open_funcs: 该文件里真被调用的函数名)为准，
    在该文件 AST 里挑一个「真被执行过 + 函数体里有 return」的函数，把落点改成它的**第一条 return**，
    符号串同步改成 "def <函数名>"。挑不到就退回: 该行所在函数的第一条 return；再退: 不动并报告。

用法:
    ./gui-venv311/bin/python tools/fix_node_source_loc.py            # 只看会改什么 (dry)
    ./gui-venv311/bin/python tools/fix_node_source_loc.py --apply    # 真改 library.py
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
LIB = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "library.py")
REPORT = os.path.join(ROOT, "reports", "node_breakpoints.json")


def funcs_in(path: str) -> dict:
    """{函数名: (def行, end行, [return行])} —— 含类方法 (按名字扁平化)。"""
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:                                                      # noqa: BLE001
        return {}
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(n.name, (n.lineno, getattr(n, "end_lineno", n.lineno),
                                    sorted({r.lineno for r in ast.walk(n) if isinstance(r, ast.Return)})))
    return out


def line_owner(fmap: dict, line: int):
    for name, (d, e, rets) in fmap.items():
        if d <= line <= e:
            return name, rets
    return None, []


GOOD = ("forward", "run", "apply", "compute", "step", "process", "detect", "fuse", "plan",
        "execute", "predict", "encode", "score", "check", "update", "select", "decide")


def pick(fmap: dict, executed: list, owner_rets: list) -> tuple:
    """在真执行过的函数里挑一个带 return 的 (优先语义入口名; 排除私有/调试辅助)。"""
    def _ok(n):
        low = n.lower()
        return (not n.startswith("_")) and low not in ("brk", "core_idea", "state_correction") \
            and "brk" not in low and "debug" not in low

    cands = [(n, fmap[n][2]) for n in executed if n in fmap and fmap[n][2] and _ok(n)]
    if not cands:
        return None, []
    for pref in GOOD:                                    # 语义入口优先
        for n, rets in cands:
            if n == pref:
                return n, rets
    # 否则挑 return 最多的 (通常是主逻辑), 平手取行号靠后的 (更内层)
    n, rets = max(cands, key=lambda x: (len(x[1]), fmap[x[0]][0]))
    return n, rets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    from lerobot.engineering.nodes import library as L                      # noqa: PLC0415
    ext = dict(getattr(L, "_EXTERNAL_LOC", {}))
    rep = {r["key"]: r for r in json.load(open(REPORT, encoding="utf-8"))["rows"] if r.get("key")}
    src = open(LIB, encoding="utf-8").read()

    changes, skipped = [], []
    for key, v in ext.items():
        path, line, sym = (list(v) + [None, None, None])[:3]
        if not path or not os.path.isfile(path):
            skipped.append((key, "文件不存在"))
            continue
        fmap = funcs_in(path)
        owner, owner_rets = line_owner(fmap, int(line or 0))
        if owner and owner.startswith("_"):                  # 私有辅助(调试钩子)不当落点
            owner, owner_rets = None, []
        if owner and owner_rets and int(line) in owner_rets:
            continue                                        # 已经落在 return 上, 不动
        if owner and owner_rets:
            new_line, new_fn = owner_rets[0], owner          # 同函数内挪到 return
        elif (rep.get(key) or {}).get("open_lines"):
            # ③ 有真执行行记录: 直接挑一个**真被执行到的 return 行** (最硬的证据)
            row = rep[key]
            el = set(row.get("open_lines") or [])
            cands = []
            for nm, (d0, e0, rr) in fmap.items():
                if nm.startswith("_"):
                    continue
                hit_r = [x for x in rr if x in el]
                if hit_r:
                    cands.append((nm, min(hit_r)))
            if not cands:
                skipped.append((key, "该文件这一拍没有执行到任何 return"))
                continue
            for pref in GOOD:
                m0 = next((c for c in cands if c[0] == pref), None)
                if m0:
                    break
            else:
                m0 = max(cands, key=lambda c: c[1])
            new_fn, new_line = m0[0], m0[1]
        else:                                                # class/def 行 → 按真执行函数挑
            row = rep.get(key) or {}
            fn_name, rets = pick(fmap, row.get("open_funcs") or [], owner_rets)
            if not fn_name:
                skipped.append((key, "没有可用函数 (未执行过/无 return)"))
                continue
            new_line, new_fn = rets[0], fn_name
        if new_fn.startswith("_"):
            skipped.append((key, "只挑到私有辅助函数 %s, 需人工指定" % new_fn))
            continue
        if int(new_line) == int(line or 0) and str(sym) == "def %s" % new_fn:
            continue
        changes.append((key, os.path.basename(path), int(line or 0), str(sym), new_line, new_fn))

    print("要改 %d 条 · 跳过 %d 条" % (len(changes), len(skipped)))
    for c in changes:
        print("   %-14s %-28s %4s %-26s → 行 %-4s def %s"
              % (c[0], c[1], c[2], c[3][:26], c[4], c[5]))

    if not a.apply:
        print("\n(dry-run; 加 --apply 才写文件)")
        return 0

    n = 0
    for key, _f, _l, _s, new_line, new_fn in changes:
        # 定位语句起点 → 括号配对找到整条元组 (路径表达式里也有括号, 不能用正则截断)
        head_pat = re.compile(r'_EXTERNAL_LOC\["%s"\]\s*=\s*\(' % re.escape(key))
        m = head_pat.search(src)
        if not m:
            print("   ⚠️ 找不到 _EXTERNAL_LOC[%s], 跳过" % key)
            continue
        i, depth = m.end(), 1
        while i < len(src) and depth:
            c = src[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        if depth:
            print("   ⚠️ 括号没配上, 跳过:", key)
            continue
        body = src[m.end():i - 1]
        mm = re.match(r'^(.*?)\s*,\s*[0-9]+\s*,\s*(?:".*?"|\'.*?\')\s*$', body, re.S)
        if not mm:
            print("   ⚠️ 结构不符, 跳过:", key, body[:60].replace("\n", " "))
            continue
        new_stmt = '_EXTERNAL_LOC["%s"] = (%s, %d, "def %s")' % (key, mm.group(1).strip(), new_line, new_fn)
        src = src[:m.start()] + new_stmt + src[i:]
        n += 1
    open(LIB, "w", encoding="utf-8").write(src)
    print("已写入 %d 条 →" % n, os.path.relpath(LIB, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
