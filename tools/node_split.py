#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nodes/library.py → nodes/<节点名>.py 拆分器 (可干跑 / 逐个自检 / 失败即回滚)。

老倪 2026-11-10: 「全局修改, 不要用 library, 是哪个节点就用哪个节点的名称」
—— 每个节点的实现正文放进 nodes/<节点 key>.py (文件名就是画布上那个节点),
   library.py 只留**共享运行时 + 薄壳**; registry / by_level 指向真身。

不拆坏的办法:
  1) AST 精确切段, 正文一字不改;
  2) 算它引用了 library 里哪些模块级名字 → 生成显式 import (不做 globals 注入);
  3) 原位置换薄壳 (同名转调, 老 import 不断);
  4) nodes/impl_manifest.json 登记, library 收尾时用真身重注册 registry
     ⇒ GUI「打开源代码」/ by_level 落到节点自己的文件;
  5) 每拆一个立刻自检 (包导入 + 全部 key 可调用), 失败自动回滚这一个。

用法:
  python tools/node_split.py --list
  python tools/node_split.py --key ss_yolo --dry
  python tools/node_split.py --key ss_yolo
  python tools/node_split.py --all [--limit N] [--dry]
"""
from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "src/lerobot/engineering/nodes/library.py"
NODES = LIB.parent
MANIFEST = NODES / "impl_manifest.json"

HEADER = '''# -*- coding: utf-8 -*-
"""{title} — 节点实现正文 (文件名 = 画布节点: {key})。

从 nodes/library.py 迁出 ({date})。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: {func}   ·   registry key: {key}
"""
'''


def read_lib() -> str:
    return LIB.read_text(encoding="utf-8")


def find_func(src: str, name: str):
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


def free_names(fn: ast.AST) -> set[str]:
    local: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.arg):
            local.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and n is not fn:
            local.add(getattr(n, "name", "") or "")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            local.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                local.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            local.add(n.name)
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return {u for u in used if u not in local and not u.startswith("__")}


def lib_names() -> set[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from lerobot.engineering.nodes import library  # noqa: PLC0415
    return {k for k in vars(library) if not k.startswith("__")}


def build_module(key: str, func: str, fn: ast.AST, src: str, known: set[str]) -> tuple[str, int]:
    body = ast.get_source_segment(src, fn) or ""
    names = sorted(n for n in free_names(fn) if n in known)
    out = [HEADER.format(title=key, key=key, func=func, date=time.strftime("%Y-%m-%d %H:%M"))]
    if names:
        out.append("# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入")
        out.append("from .library import (  # noqa: F401")
        out.extend("    %s," % n for n in names)
        out.append(")\n")
    out.append(body.rstrip() + "\n")
    out.append("\n# 与既有 *_impl.py 同约定: 外部也可以 from ... import run\nrun = %s\n" % func)
    return "\n".join(out), len(names)


def shell(func: str, key: str) -> str:
    return (
        'def %s(ctx):\n'
        '    """→ nodes/%s.py  (实现正文已迁出; 这只转调, 兼容老 import)"""\n'
        '    from .%s import %s as _impl\n'
        '    return _impl(ctx)\n' % (func, key, key, func)
    )


def surgery(key: str, func: str, apply: bool) -> dict:
    src = read_lib()
    fn = find_func(src, func)
    if fn is None:
        return {"ok": False, "key": key, "why": "library.py 里已没有 %s (可能已迁)" % func}
    if any(isinstance(n, ast.Global) for n in ast.walk(fn)):
        return {"ok": False, "key": key, "why": "%s 用了 global, 需人工迁移" % func}
    target = NODES / ("%s.py" % key)
    if target.exists():
        return {"ok": False, "key": key, "why": "%s.py 已存在" % key}
    known = lib_names()
    mod_src, n_imp = build_module(key, func, fn, src, known)
    lines = src.splitlines(keepends=True)
    start, end = fn.lineno - 1, (fn.end_lineno or fn.lineno)
    new_lib = "".join(lines[:start] + [shell(func, key), "\n"] + lines[end:])
    res = {"ok": True, "key": key, "func": func, "file": "nodes/%s.py" % key,
           "moved_lines": end - start, "imports": n_imp, "dry": not apply}
    ast.parse(new_lib)
    ast.parse(mod_src)
    if not apply:
        return res
    bak = LIB.with_suffix(".py.bak_split_%s" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy(LIB, bak)
    target.write_text(mod_src, encoding="utf-8")
    LIB.write_text(new_lib, encoding="utf-8")
    res["backup"] = bak.name
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    man[key] = {"func": func, "module": ".%s" % key, "file": "nodes/%s.py" % key}
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return res


def rollback(key: str, backup: str) -> None:
    shutil.copy(NODES / backup, LIB)
    (NODES / ("%s.py" % key)).unlink(missing_ok=True)
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    man.pop(key, None)
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def selftest() -> tuple[bool, str]:
    code = (
        "import sys, collections; sys.path.insert(0,'%s')\n"
        "from lerobot.engineering import registry\n"
        "import lerobot.engineering.nodes as N\n"
        "bad=[k for k,v in registry.NODE_LOGIC.items() if not callable(v.get('fn'))]\n"
        "files=collections.Counter((v.get('file') or '?').split('/')[-1] for v in registry.NODE_LOGIC.values())\n"
        "print('KEYS',len(registry.NODE_LOGIC),'BAD',len(bad),bad[:3])\n"
        "print('TOP',files.most_common(4))\n"
    ) % (ROOT / "src")
    p = subprocess.run([str(ROOT / "gui-venv311/bin/python"), "-c", code],
                       capture_output=True, text=True, cwd=str(ROOT), timeout=600)
    return (p.returncode == 0 and "BAD 0" in p.stdout), (p.stdout + p.stderr)[-1200:]


def jobs_table() -> list[tuple[str, str]]:
    """[(节点 key, 函数名)] —— 还指向 library.py 的"""
    sys.path.insert(0, str(ROOT / "src"))
    from lerobot.engineering.nodes.by_level import LEVELS_INDEX  # noqa: PLC0415
    seen, out = set(), []
    for _lvl, rows in LEVELS_INDEX.items():
        for r in rows:
            if len(r) >= 5 and r[3] == "library.py" and r[2] and r[4]:
                if r[2] in seen:
                    continue
                seen.add(r[2])
                out.append((r[2], r[4]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    table = jobs_table()
    if a.list:
        for k, f in table:
            print("%-20s → %s" % (k, f))
        print("共", len(table), "个节点仍指向 library.py")
        return
    if a.key:
        table = [t for t in table if t[0] == a.key]
    elif not a.all:
        ap.error("给 --key 或 --all")
    if a.limit:
        table = table[:a.limit]
    done, failed = 0, 0
    for k, f in table:
        r = surgery(k, f, apply=not a.dry)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        if not r["ok"]:
            failed += 1
            continue
        if a.dry:
            done += 1
            continue
        ok, out = selftest()
        if ok:
            done += 1
        else:
            rollback(k, r["backup"])
            print("❌ 自检失败 → 已回滚 %s\n%s" % (k, out), flush=True)
            failed += 1
            break
    if not a.dry:
        ok, out = selftest()
        print("SELFTEST", "OK" if ok else "FAIL")
        print(out)
    print("DONE", done, "FAILED", failed)


if __name__ == "__main__":
    main()
