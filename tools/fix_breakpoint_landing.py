#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_breakpoint_landing.py —— 把「右键打开」的落点改到**真的会执行**的那一行

背景 (老倪 2026-10-31「所有断点都要进入; 全局改, 每个节点严格检查」):
  reports/node_breakpoints.json 里 FAIL-NORET 的节点, 落点指向的是**这条路径上根本不会调用**的函数
  (例: sssched 指向 cognition.ActionModulator.advance, 实际跑的是 library.node_ss_s3; ss_mani_eng 指向
  manifold_engine.parallel_transport, 实际跑的是 node 包装)。落在那里永远不停 —— 不是断点坏了, 是位置错。

判据 (不看文档, 只看真跑记录):
  取该节点**真跑命中**的 return 行 (real_returns_hit) 作为落点; 落点外层函数必须是 library.py 里的 node 包装,
  即"这一拍真的走过的那一行"。

用法:
  ./gui-venv311/bin/python tools/fix_breakpoint_landing.py [--apply]
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "reports", "node_breakpoints.json")
LIB = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "library.py")


def outermost_func(tree, line):
    """返回包住 line 的**最外层**函数名 (node 包装), 跳过内嵌闭包。"""
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.lineno <= line <= getattr(n, "end_lineno", n.lineno):
                if best is None or n.lineno < best[1]:
                    best = (n.name, n.lineno)
    return best[0] if best else None


def plan():
    d = json.load(open(REPORT, encoding="utf-8"))
    tree = ast.parse(open(LIB, encoding="utf-8").read())
    out = []
    for r in d["rows"]:
        if r["verdict"] != "FAIL-NORET":
            continue
        hits = r.get("real_returns_hit") or r.get("real_returns") or []
        if not hits:
            continue
        line = int(hits[0])
        fn = outermost_func(tree, line)
        if r["real_file"].endswith("library.py"):
            out.append({"id": r["id"], "key": r.get("key") or r["id"],
                        "file": "src/lerobot/engineering/nodes/library.py",
                        "line": line, "sym": ("def %s" % fn) if fn else "命中 return"})
    return out


def main() -> int:
    apply = "--apply" in sys.argv
    items = plan()
    if not items:
        print("✅ 没有 FAIL-NORET 项, 无需改落点")
        return 0
    src = open(LIB, encoding="utf-8").read()
    lines = src.splitlines(True)
    added, changed = [], 0
    for it in items:
        expr = ('_EXTERNAL_LOC["%s"] = (os.path.join(_REPO_ROOT, "%s"), %d, "%s")'
                % (it["key"], it["file"], it["line"], it["sym"]))
        pat = re.compile(r'^_EXTERNAL_LOC\["%s"\]\s*=.*$' % re.escape(it["key"]), re.M)
        if pat.search(src):
            new = pat.sub(expr + "   # 🎯 2026-10-31 落点校准: 原来指到本路径不调用的函数 ⇒ 断点永不命中", src, count=1)
            if new != src:
                changed += 1
                src = new
                lines = src.splitlines(True)
        else:
            added.append(expr + "   # 🎯 2026-10-31 新增落点 (原无映射, 断点在别处永不命中)")
        print("· %-12s → %s:%d  %s" % (it["key"], it["file"].split("/")[-1], it["line"], it["sym"]))
    if added:
        # 插到 library.py 里**最后一处** _EXTERNAL_LOC 赋值之后, 保证不被后面的定义覆盖
        idxs = [i for i, ln in enumerate(lines) if ln.startswith("_EXTERNAL_LOC[")]
        at = (max(idxs) + 1) if idxs else 0
        lines[at:at] = ["\n# 🎯 2026-10-31 老倪「所有断点都要进入」: 补齐无映射节点的落点 (真跑命中的那一行)\n"] + \
                       [a + "\n" for a in added]
        src = "".join(lines)
    if not apply:
        print("\n(dry-run; 加 --apply 才写库)  待改 %d 条 · 新增 %d 条" % (changed, len(added)))
        return 0
    open(LIB, "w", encoding="utf-8").write(src)
    import py_compile
    py_compile.compile(LIB, doraise=True)
    print("\n✅ 已写入 %s (改 %d · 增 %d) · py_compile OK" % (os.path.relpath(LIB, ROOT), changed, len(added)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
