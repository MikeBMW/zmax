#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs_index.py — 以专利为核心、状态空间工程为落地的文档索引生成器

口径（信息要有联系，且联系必须现算、不许手写）:
  专利 ZMP-xxxx  ──fn_ids──▶  功能 FN-xxxx (config_meta.json)
                 ──code_file──▶  画布节点 (mw_node 表)
                 ──impl_key/module──▶  源码 (source:symbol)
                 ──关键词──▶  文档 (docs/**/*.md)

产出 docs/0-索引/:
  README.md      总入口（专利为核心 · 七星为落地 · 怎么查）
  专利地图.md     各件专利 → 挂载功能/节点/代码/实测证据/相关文档
  节点索引.md     79 个画布节点 → 属于哪件专利/实现模块/源码位置
  文档对照.md     本体文档 → 关联专利（按标题与关键词打分）
  index.json     机器可读（给工具和画布用）

用法: python3 tools/docs_index.py [--dry]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
OUTDIR = os.path.join(DOCS, "0-索引")
REG = os.path.join(ROOT, "config", "patents", "patent_registry.json")
META = os.path.join(ROOT, "data", "database", "zmax", "config_meta.json")
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")

SKIP_DIRS = ("3-天玑-能力功能/skills", "7-瑶光-记录追溯/memory", "0-索引", "render", "_archive")


def load():
    reg = json.load(open(REG, encoding="utf-8"))
    cm = json.load(open(META, encoding="utf-8"))
    fns = cm["functions"]
    if isinstance(fns, list):
        fns = {f["fn_id"]: f for f in fns}
    nodes = []
    if os.path.exists(DB):
        c = sqlite3.connect(DB)
        c.row_factory = sqlite3.Row
        nodes = [dict(r) for r in c.execute("select * from mw_node")]
    return reg["patents"], fns, nodes


def link(patents, fns, nodes):
    """专利 → 功能 → 节点：用 code_file 与节点 source 对齐。"""
    by_src = {}
    for n in nodes:
        s = (n.get("source") or "").replace("\\", "/").strip()
        if s:
            by_src.setdefault(s, []).append(n["node_id"])
    node_by_id = {n["node_id"]: n for n in nodes}
    out = []
    for p in patents:
        fids = p.get("fn_ids") or []
        rel = p.get("fn_ids_related") or []
        pnodes, pfunc = [], []
        for fid in fids + rel:
            f = fns.get(fid)
            if not f:
                pfunc.append(dict(fn_id=fid, name="（唯一依据未登记）", code="", role="主挂" if fid in fids else "关联"))
                continue
            cf = (f.get("code_file") or "").replace("\\", "/").strip()
            pfunc.append(dict(fn_id=fid, name=f.get("name", ""), code=cf,
                              role="主挂" if fid in fids else "关联", layer=f.get("layer", "")))
            for nid in by_src.get(cf, []):
                if nid not in pnodes:
                    pnodes.append(nid)
        out.append(dict(pat=p, funcs=pfunc, nodes=pnodes))
    return out, node_by_id


def scan_docs():
    """扫本体文档（排除镜像目录），返回 [{path, title, head}]"""
    out = []
    for root, dirs, files in os.walk(DOCS):
        rel_root = os.path.relpath(root, DOCS).replace("\\", "/")
        if any(rel_root == s or rel_root.startswith(s + "/") for s in SKIP_DIRS):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for f in files:
            if not f.lower().endswith((".md", ".docx", ".pptx")):
                continue
            p = os.path.join(root, f)
            title, head = os.path.splitext(f)[0], ""
            if f.lower().endswith(".md"):
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read(3000)
                    m = re.search(r"^#\s+(.+)$", txt, re.M)
                    if m:
                        title = m.group(1).strip()
                    head = txt[:1200]
                except Exception:
                    pass
            out.append(dict(path=os.path.relpath(p, ROOT).replace("\\", "/"),
                            title=title, head=head))
    return out


def score(doc, linked, node_by_id):
    """文档与专利的关联分：专利关键词 + 挂载节点名 在文档里命中的次数。"""
    hay = (doc["title"] + " " + doc["head"])
    best = (0, None)
    for L in linked:
        p = L["pat"]
        kws = set()
        for seg in re.split(r"[·、，,与及的]", p["title"]):
            seg = seg.strip()
            if len(seg) >= 4:
                kws.add(seg)
        kws.add(p.get("layer", ""))
        for nid in L["nodes"]:
            nm = node_by_id.get(nid, {}).get("name", "")
            nm = re.sub(r"^[^\w\u4e00-\u9fa5]+", "", nm)
            if len(nm) >= 3:
                kws.add(nm)
        s = sum(2 if k in doc["title"] else 1 for k in kws if k and k in hay)
        if s > best[0]:
            best = (s, p["pat_id"])
    return best


def build(dry=False):
    patents, fns, nodes = load()
    linked, node_by_id = link(patents, fns, nodes)
    docs = scan_docs()
    ts = time.strftime("%Y-%m-%d %H:%M")

    # 反向：节点 → 专利
    node_pats = {}
    for L in linked:
        for nid in L["nodes"]:
            node_pats.setdefault(nid, []).append(L["pat"]["pat_id"])
    uncovered = [n for n in nodes if n["node_id"] not in node_pats]

    # 文档对照
    for d in docs:
        s, pid = score(d, linked, node_by_id)
        d["pat"] = pid if s >= 2 else ""
        d["score"] = s

    os.makedirs(OUTDIR, exist_ok=True)

    # ── index.json ──
    data = dict(generated_at=ts, patents=[], nodes=[], docs=[])
    for L in linked:
        p = L["pat"]
        data["patents"].append(dict(
            pat_id=p["pat_id"], star=p.get("star", ""), layer=p.get("layer", ""),
            title=p["title"], status=p.get("status", ""),
            funcs=L["funcs"], nodes=L["nodes"],
            impl_refs=p.get("impl_refs") or [], data_refs=p.get("data_refs") or [],
            docs=[d["path"] for d in docs if d["pat"] == p["pat_id"]][:40]))
    for n in nodes:
        data["nodes"].append(dict(node_id=n["node_id"], name=n["name"], type=n.get("type"),
                                  module=n.get("module"), impl_key=n.get("impl_key"),
                                  source=n.get("source"), symbol=n.get("symbol"),
                                  patents=node_pats.get(n["node_id"], [])))
    data["docs"] = [dict(path=d["path"], title=d["title"], patent=d["pat"]) for d in docs]
    data["summary"] = dict(patents=len(patents), nodes=len(nodes),
                           nodes_covered=len(nodes) - len(uncovered),
                           docs=len(docs),
                           docs_linked=sum(1 for d in docs if d["pat"]))
    if dry:
        print(json.dumps(data["summary"], ensure_ascii=False, indent=1))
        return data
    json.dump(data, open(os.path.join(OUTDIR, "index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ── 专利地图.md ──
    L = ["# 专利地图 · %d 件专利 → 功能 → 节点 → 代码" % len(linked), "",
         "> 由 `tools/docs_index.py` 从 `patent_registry.json` + `config_meta.json` + 画布工程库现算。",
         "> 本文件是「以专利为核心」的总览：每件专利在工程里落到哪些节点、哪份源码、哪些文档。", "",
         "| 编号 | 星位 | 层 | 发明名称 | 挂载节点 | 相关文档 |", "|---|---|---|---|---|---|"]
    for Lp in linked:
        p = Lp["pat"]
        nd = len(Lp["nodes"])
        dc = sum(1 for d in docs if d["pat"] == p["pat_id"])
        L.append("| %s | %s | %s | %s | %d | %d |" % (
            p["pat_id"], p.get("star", ""), p.get("layer", ""), p["title"], nd, dc))
    L.append("")
    for Lp in linked:
        p = Lp["pat"]
        L += ["## %s · %s" % (p["pat_id"], p["title"]), ""]
        L += ["- 星位：%s　层：%s　状态：%s" % (p.get("star", ""), p.get("layer", ""), p.get("status", "")), ""]
        L += ["**挂载功能（%d 条）**" % len(Lp["funcs"]), ""]
        L += ["| 功能编号 | 名称 | 关系 | 代码文件 |", "|---|---|---|---|"]
        for f in Lp["funcs"]:
            L.append("| %s | %s | %s | `%s` |" % (f["fn_id"], f["name"][:34], f["role"], f["code"] or "—"))
        L += ["", "**落地节点（%d 个）**" % len(Lp["nodes"]), ""]
        if Lp["nodes"]:
            L += ["| 节点 | 名称 | 实现模块 | 源码 |", "|---|---|---|---|"]
            for nid in Lp["nodes"]:
                n = node_by_id.get(nid, {})
                L.append("| `%s` | %s | `%s` | `%s` |" % (
                    nid, (n.get("name") or "")[:26], n.get("module") or "—",
                    (n.get("source") or "—")))
        else:
            L.append("_（本专利在画布上暂无对应节点）_")
        dl = [d for d in docs if d["pat"] == p["pat_id"]]
        L += ["", "**相关文档（%d 份）**" % len(dl), ""]
        for d in dl[:12]:
            L.append("- `%s` — %s" % (d["path"], d["title"][:40]))
        if len(dl) > 12:
            L.append("- …共 %d 份，见 `index.json`" % len(dl))
        L += ["", "**代码证据**", ""]
        for r in (p.get("impl_refs") or []):
            L.append("- `%s`" % r)
        L.append("")
    open(os.path.join(OUTDIR, "专利地图.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    # ── 节点索引.md ──
    L = ["# 节点索引 · 状态空间工程 79 个节点", "",
         "> 由 `tools/docs_index.py` 从画布工程库 `mw_node` 表现算。",
         "> 看一个节点归哪件专利、源码在哪、属于哪一层。", "",
         "| 节点 | 名称 | 类型 | 专利 | 实现模块 | 源码 |", "|---|---|---|---|---|---|"]
    for n in nodes:
        ps = ",".join(node_pats.get(n["node_id"], [])) or "— **无专利覆盖**"
        L.append("| `%s` | %s | %s | %s | `%s` | `%s` |" % (
            n["node_id"], (n.get("name") or "")[:22], n.get("type") or "",
            ps, n.get("module") or "—", (n.get("source") or "—")[:52]))
    L += ["", "## 没有专利覆盖的节点（%d 个）" % len(uncovered), "",
          "这些节点在工程里真实存在、能跑，但没有对应到任何一件专利 —— 要么补专利，要么说明它是支撑件。", ""]
    for n in uncovered:
        L.append("- `%s` %s（%s）" % (n["node_id"], (n.get("name") or "")[:24], n.get("module") or "—"))
    open(os.path.join(OUTDIR, "节点索引.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    # ── 文档对照.md ──
    L = ["# 文档对照 · 本体文档 → 关联专利", "",
         "> 由 `tools/docs_index.py` 按标题与关键词打分（≥2 分才挂），供检索与归档参考。",
         "> 镜像目录（`3-天玑/skills`、`7-瑶光/memory`）不参与对照。", "",
         "| 文档 | 标题 | 关联专利 |", "|---|---|---|"]
    linked_docs = sorted([d for d in docs if d["pat"]], key=lambda x: (x["pat"], x["path"]))
    for d in linked_docs:
        L.append("| `%s` | %s | %s |" % (d["path"], d["title"][:38], d["pat"]))
    L += ["", "## 未关联到专利的文档（%d 份）" % sum(1 for d in docs if not d["pat"]), "",
          "这些多是交付件、会议记录、事故台账等，本身不挂专利属正常；若其中有技术方案，应考虑补挂。", ""]
    for d in docs:
        if not d["pat"]:
            L.append("- `%s` — %s" % (d["path"], d["title"][:44]))
    open(os.path.join(OUTDIR, "文档对照.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    # ── README.md ──
    s = data["summary"]
    L = ["# 0 · 索引（文档系统的入口）", "",
         "这套文档系统只有两个轴：**专利是核心思想**（我们主张什么），**状态空间工程是落地手段**（在哪个节点、哪份代码实现）。",
         "七颗星只是归档位置，回答「这份文档放哪」；索引回答「它和什么有关系」。", "",
         "## 四个入口", "",
         "| 文件 | 回答什么问题 |", "|---|---|",
         "| `专利地图.md` | 这件专利落到哪些功能、哪些节点、哪份代码、哪些文档 |",
         "| `节点索引.md` | 这个节点归哪件专利、源码在哪；哪些节点还没有专利覆盖 |",
         "| `文档对照.md` | 这份文档和哪件专利有关 |",
         "| `index.json` | 给工具/画布用的机器可读版 |", "",
         "## 现状数字（生成时现算）", "",
         "| 口径 | 值 |", "|---|---|",
         "| 专利 | %d 件 |" % s["patents"],
         "| 画布节点 | %d 个 |" % s["nodes"],
         "| 已被专利覆盖的节点 | %d 个（%.0f%%） |" % (s["nodes_covered"], 100.0 * s["nodes_covered"] / max(s["nodes"], 1)),
         "| 无专利覆盖的节点 | %d 个 |" % (s["nodes"] - s["nodes_covered"]),
         "| 本体文档 | %d 份 |" % s["docs"],
         "| 已关联到专利的文档 | %d 份 |" % s["docs_linked"], "",
         "## 怎么加一份新文档", "",
         "1. 先问：它支撑哪件专利？找不到就说明它还没想清楚 —— 要么补进某件专利的功能条目，要么放到 `7-瑶光` 当记录。",
         "2. 按主司放进七颗星之一（判定规则见 `docs/README.md`）。",
         "3. 跑一次 `python3 tools/docs_index.py`，三个索引自动更新，文档会出现在 `文档对照.md`。", "",
         "## 只读规矩（与 docs/README.md 一致）", "",
         "`3-天玑-能力功能/skills/`、`7-瑶光-记录追溯/memory/` 是 `~/.hermes` 镜像，要改改源；",
         "`6-开阳/data_snapshots/` 按日期冻结；`5-玉衡/test-reports/` 被校验脚本按路径断言。", "",
         "---", "",
         "*生成：`tools/docs_index.py`（%s）。所有数字现算，不手写。*" % ts]
    open(os.path.join(OUTDIR, "README.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")

    print("生成完成 →", OUTDIR)
    print(json.dumps(s, ensure_ascii=False))
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    build(a.dry)
