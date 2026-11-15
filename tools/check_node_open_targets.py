#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔎 画布节点「右键打开源代码」全量体检 (老倪 2026-11-15: 保证每个节点都定位到正确源码)

判据 (与 GUI 同一套解析, 不另造口径):
  1) 用 lerobot.middleware.resolve_open_target(node) 拿落点 —— GUI 右键就走它
  2) impl_path 必须存在, 且是**真代码**不是转发壳/软链坏链
  3) 行号必须落在函数体内 (def 头或 def 之后), 不能停在文件顶/import 行 (断点永远不中)
  4) 符号 (source_symbol / _EXTERNAL_LOC[2]) 必须真出现在文件里
  5) 文件行数 ≥ 20 (少于 20 行多半是壳, 标 warning 不算 fail)

用法:
  python3 tools/check_node_open_targets.py            # 只报
  python3 tools/check_node_open_targets.py --json out.json
  python3 tools/check_node_open_targets.py --fix       # 行号漂移的自动重算回写画布
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

CANVAS_DB = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")


def gui_canvas_path():
    """🔴 2026-11-15 老倪「右键打开源代码还是 node」根因: 控制台**并不读** data/database 这份,
    而是走 simulink_module._flows_path() —— 环境变量 > 仓库根 flows/ > DB 副本。
    flows/ 里那份是 2026-11-13 的陈旧拷贝(source 还指 engineering/nodes/geo_plan_impl.py),
    所以改了 DB 副本等于没改。这里按 GUI 同一顺序取路径, 并显式检查两份是否分叉。"""
    env = os.environ.get("ZMAX_FLOWS_DIR")
    if env:
        p = os.path.join(env, "state_space_obs.json")
        if os.path.isfile(p):
            return p
    p = os.path.join(ROOT, "flows", "state_space_obs.json")
    return p if os.path.isfile(p) else CANVAS_DB


CANVAS = gui_canvas_path()


def load_canvas():
    d = json.load(open(CANVAS, encoding="utf-8"))
    return d, d.get("nodes") or []


def line_in_func(path, line):
    """行号是否落在某个 def/class 体内 (GUI 的 _line_in_func 同义)。"""
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except Exception:                                                     # noqa: BLE001
        return False
    if not (1 <= line <= len(lines)):
        return False
    for i in range(line - 1, -1, -1):
        s = lines[i].lstrip()
        if s.startswith("def ") or s.startswith("class ") or s.startswith("async def "):
            return True
        if s and not s.startswith(("#", '"', "'", "@")) and i < line - 1 and not lines[i].startswith((" ", "\t")):
            return False
    return False


def first_return_after(path, lineno):
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except Exception:                                                     # noqa: BLE001
        return None
    for i in range(max(0, lineno - 1), len(lines)):
        if lines[i].lstrip().startswith("return"):
            return i + 1
    return lineno


def find_symbol_line(path, sym):
    if not sym:
        return None
    try:
        for i, ln in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
            if ln.lstrip().startswith(sym):
                return i
    except Exception:                                                     # noqa: BLE001
        return None
    return None


def real_path(p):
    """软链解开 (相对软链按文件所在目录解析)。"""
    return os.path.realpath(p)


def audit():
    from lerobot.middleware.open_target import resolve_open_target
    d, nodes = load_canvas()
    rows = []
    for n in nodes:
        nid = n.get("id") or ""
        nm = n.get("name") or ""
        if not nid and not nm:
            continue
        pr = n.get("params") or {}
        try:
            r = resolve_open_target(n, root=ROOT)
        except Exception as e:                                             # noqa: BLE001
            r = {"error": "%s: %s" % (type(e).__name__, e)}
        p = r.get("impl_path") or r.get("path")
        line = r.get("impl_line") or r.get("line")
        row = {"id": nid, "name": nm, "kind": r.get("kind"),
               "src": pr.get("source"), "sym": pr.get("source_symbol"),
               "path": p, "line": line, "problems": []}
        if r.get("error"):
            row["problems"].append("解析异常 " + str(r["error"])[:60])
        if not p:
            row["problems"].append("无源码映射")
        else:
            rp = real_path(p)
            row["real"] = rp
            if not os.path.isfile(rp):
                row["problems"].append("文件不存在/软链坏")
            else:
                n_line = sum(1 for _ in open(rp, encoding="utf-8", errors="ignore"))
                row["file_lines"] = n_line
                if n_line < 20:
                    row["problems"].append("疑似转发壳(仅%d行)" % n_line)
                # 行号
                if not line:
                    row["problems"].append("无行号")
                elif not line_in_func(rp, int(line)):
                    fix = None
                    if row["sym"]:
                        sl = find_symbol_line(rp, row["sym"])
                        if sl:
                            fix = first_return_after(rp, sl)
                    row["problems"].append("行号不在函数体内(line=%s%s)"
                                           % (line, ", 可修正→%s" % fix if fix else ""))
                    row["suggest_line"] = fix
                # 符号
                if row["sym"]:
                    if find_symbol_line(rp, row["sym"]) is None:
                        row["problems"].append("符号不存在(%s)" % row["sym"])
        rows.append(row)
    return d, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--fix", action="store_true", help="行号漂移的按符号+首个 return 重算回写画布")
    a = ap.parse_args()

    d, rows = audit()
    total = len(rows)
    mapped = [r for r in rows if r.get("path")]
    bad = [r for r in rows if r["problems"] and "疑似转发壳" not in " ".join(r["problems"])]
    warn = [r for r in rows if r["problems"] and r not in bad]
    print("画布节点 %d 个 · 有源码映射 %d · 有硬问题 %d · 只 warning %d"
          % (total, len(mapped), len(bad), len(warn)))
    for r in sorted(bad, key=lambda x: x["id"]):
        print("  ✗ %-10s %-22s %s" % (r["id"], r["name"][:20], " / ".join(r["problems"])))
    for r in sorted(warn, key=lambda x: x["id"])[:6]:
        print("  ⚠ %-10s %-22s %s" % (r["id"], r["name"][:20], " / ".join(r["problems"])))
    nomap = [r for r in rows if not r.get("path")]
    if nomap:
        print("  · 无映射 %d 个: %s" % (len(nomap), ", ".join(x["id"] for x in nomap[:12])))

    if a.json:
        json.dump({"total": total, "bad": bad, "warn": warn, "nomap": nomap},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("  报告:", a.json)

    if a.fix:
        n_fix = 0
        by_id = {r["id"]: r for r in rows}
        for n in d.get("nodes") or []:
            r = by_id.get(n.get("id") or "")
            if not r or not r.get("suggest_line"):
                continue
            pr = n.setdefault("params", {})
            pr["source"] = os.path.relpath(r["real"], ROOT)
            pr["source_symbol"] = pr.get("source_symbol") or "def run"
            pr["source_line"] = r["suggest_line"]
            n_fix += 1
        if n_fix:
            bak = CANVAS + ".bak_openfix"
            open(bak, "w", encoding="utf-8").write(open(CANVAS, encoding="utf-8").read())
            json.dump(d, open(CANVAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("  已修正 %d 个节点的 source/行号 (备份 %s)" % (n_fix, os.path.basename(bak)))
        else:
            print("  无需修正")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
