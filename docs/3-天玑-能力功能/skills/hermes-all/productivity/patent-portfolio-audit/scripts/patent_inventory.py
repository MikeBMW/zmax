#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patent_inventory.py — 专利组合盘点 (全部现算, 不打字面量)

依赖: 仅 stdlib。仓库根默认 ~/zmax, 用 ZMAX_ROOT 覆盖。

用法:
  python3 scripts/patent_inventory.py                            # 逐件表 + 缺口
  python3 scripts/patent_inventory.py --dir src/lerobot/manifold  # 目录级落地引用覆盖率
  python3 scripts/patent_inventory.py --json                     # 机器可读

输出:
  1) 逐件: 编号/星/层/状态/主关功能/节点/权项/方案步/落地引用/md/pdf
  2) 缺口: 无 data_refs、无量化字样、embodiment 写死「N 个」、交底书或 PDF 缺失
  3) 覆盖率: 指定目录下每个 .py 被哪件专利 impl_refs 引用 (名义覆盖 vs 文本落点)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.environ.get("ZMAX_ROOT", os.path.expanduser("~/zmax"))
REG = os.path.join(ROOT, "config/patents/patent_registry.json")
IDX = os.path.join(ROOT, "docs/0-索引/index.json")
JD = os.path.join(ROOT, "docs/1-天枢-产品边界/patents/交底书")

QUANT = re.compile(r"实测|测得|误差|rmse|偏差|mm\\b|%")
HARD_NUM = re.compile(r"(画布节点|节点|功能)\\s*(\\d+)\\s*个")


def load():
    pats = json.load(open(REG, encoding="utf-8"))["patents"]
    nodes = {}
    if os.path.exists(IDX):
        idx = json.load(open(IDX, encoding="utf-8"))
        nodes = {p["pat_id"]: p.get("nodes") or [] for p in idx.get("patents") or []}
    return pats, nodes


def inventory(pats, nodes):
    rows, gaps = [], []
    for p in pats:
        pid = p["pat_id"]
        md = glob.glob(os.path.join(JD, pid + "_*.md"))
        dx = glob.glob(os.path.join(JD, pid + "_*.docx"))
        pdf = glob.glob(os.path.join(JD, "pdf", pid + "_*.pdf"))
        blob = " ".join(p.get("embodiment") or []) + " " + " ".join(p.get("effects") or [])
        row = dict(
            pat_id=pid, star=p.get("star"), layer=p.get("layer"), status=p.get("status"),
            title=p["title"], fn_main=len(p.get("fn_ids") or []),
            fn_rel=len(p.get("fn_ids_related") or []), nodes=len(nodes.get(pid) or []),
            claims=len(p.get("claims") or []), steps=len(p.get("solution") or []),
            refs=len(p.get("impl_refs") or []), data_refs=len(p.get("data_refs") or []),
            quant=len(QUANT.findall(blob)), md=bool(md), docx=bool(dx), pdf=bool(pdf),
        )
        rows.append(row)
        if not row["data_refs"]:
            gaps.append((pid, "data_refs 空" + (" (但有量化数字, 数字来源无登记)" if row["quant"] else "")))
        if not row["quant"]:
            gaps.append((pid, "embodiment/effects 无量化实测"))
        for i, e in enumerate(p.get("embodiment") or []):
            for m in HARD_NUM.finditer(e):
                gaps.append((pid, "embodiment[%d] 写死『%s %s 个』— 核对当前实际值" % (i, m.group(1), m.group(2))))
        if not (row["md"] and row["docx"] and row["pdf"]):
            gaps.append((pid, "交底书不全 md=%s docx=%s pdf=%s" % (row["md"], row["docx"], row["pdf"])))
    return rows, gaps


def shared_nodes(pats, nodes, top=8):
    cnt = {}
    for pid, ns in nodes.items():
        for n in ns:
            cnt.setdefault(n, set()).add(pid)
    return sorted(cnt.items(), key=lambda kv: -len(kv[1]))[:top]


def dir_coverage(pats, rel_dir):
    d = os.path.join(ROOT, rel_dir)
    if not os.path.isdir(d):
        return None
    out = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".py"):
            continue
        rel = os.path.join(rel_dir, f).replace("\\", "/")
        owners = [p["pat_id"] for p in pats
                  if any(rel in str(r).replace("\\", "/") for r in (p.get("impl_refs") or []))]
        out.append((f, owners))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None, help="按目录扫 impl_refs 覆盖率, 如 src/lerobot/manifold")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(REG):
        print("找不到 registry: %s (设 ZMAX_ROOT?)" % REG)
        return 1
    pats, nodes = load()
    rows, gaps = inventory(pats, nodes)

    if a.json:
        print(json.dumps(dict(rows=rows, gaps=gaps, total=len(rows)), ensure_ascii=False, indent=1))
        return 0

    print("%-14s %-4s %-7s %-6s %-4s %-3s %-3s %-3s %-3s %-2s %-2s %s"
          % ("编号", "星", "层", "状态", "功能", "节点", "权项", "步骤", "引用", "md", "pdf", "名称"))
    for r in rows:
        print("%-14s %-4s %-7s %-6s %-4s %-3d %-3d %-3d %-3d %-2s %-2s %s" % (
            r["pat_id"], r["star"], (r["layer"] or "")[:7], (r["status"] or "")[:6],
            "%d/%d" % (r["fn_main"], r["fn_rel"]), r["nodes"], r["claims"], r["steps"], r["refs"],
            "Y" if r["md"] else "N", "Y" if r["pdf"] else "N", r["title"][:34]))

    print("\n合计 %d 件 · 功能挂载 %d · 节点链接 %d · 定稿 %d" % (
        len(rows), sum(r["fn_main"] + r["fn_rel"] for r in rows), sum(r["nodes"] for r in rows),
        sum(1 for r in rows if (r["status"] or "") == "定稿")))

    sh = shared_nodes(pats, nodes)
    if sh:
        print("主干节点 (被最多件共享): " + ", ".join("%s(%d)" % (n, len(o)) for n, o in sh))

    print("\n== 缺口 %d 条 ==" % len(gaps))
    for pid, g in gaps:
        print("  %s  %s" % (pid, g))

    if a.dir:
        cov = dir_coverage(pats, a.dir)
        if cov is None:
            print("\n目录不存在: %s" % a.dir)
        else:
            none = [f for f, o in cov if not o]
            print("\n== %s 落地引用覆盖率: %d/%d 个 .py 被引用 ==" % (a.dir, len(cov) - len(none), len(cov)))
            for f, o in cov:
                if o:
                    print("  %-42s %s" % (f, ",".join(x[-3:] for x in o)))
            if none:
                print("  未被任何专利引用 (%d): %s" % (len(none), ", ".join(none)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
