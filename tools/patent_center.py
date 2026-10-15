#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patent_center.py — Z-MAX 专利中心 (专利申请渠道预留 + 申请文档生成/导出/预览)。

老倪 2026-10-15:
  「注意，预留所有功能的专利申请渠道；在配置中心，文档配置 增加专利 导出和预览功能，通SOR 项目立项，等文档同级别；
   你来根据先有状态空间工程，设计专利申请的内容，要有层次，逻辑，要保证全局数据真实，可靠，能落地，形成专有知识产权」

设计要点 (为什么这样做):
  · **渠道预留**: 真源 `config/patents/patent_registry.json` 里每件专利带 `fn_ids`(主挂)/`fn_ids_related`(关联),
    与单一工程库 `functions` 表逐条比对 —— 74 项功能必须**逐条**挂到至少一件专利上 (覆盖 74/74),
    未挂上的功能不隐藏、直接列出来 (渠道未闭合要看得见)。
  · **内容分层**: 每件专利 = 层次 (体系/数学/模型/执行/标定/视觉) + 逻辑 (技术问题→技术方案→有益效果→权利要求→实施例),
    内容由编写稿 (`config/patents/drafts/*.json`) 定稿成真源 registry。
  · **数据真实**: 文档里的统计数字**全部现算** (工程库 functions / product_features / canvas_nodes + 模型矩阵),
    不写死; 每件专利再附它挂的功能条目与真源符号 (可直接点到代码), 保证"能落地"。
  · **文档同级**: 输出的 md/docx 与 SOR/项目立项/合作协议同目录 (`docs/deliverables`)、同入口 (配置中心·文档配置页)。

用法:
    ./gui-venv311/bin/python tools/patent_center.py --coverage          # 渠道覆盖核对 (74/74)
    ./gui-venv311/bin/python tools/patent_center.py --build             # 编写稿 → 真源 registry
    ./gui-venv311/bin/python tools/patent_center.py --export all        # 导出 md+docx 到 docs/patents
    ./gui-venv311/bin/python tools/patent_center.py --preview ZMP-2026-001
    ./gui-venv311/bin/python tools/patent_center.py --json              # 给 GUI 用
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_J = os.path.join(ROOT, "config", "patents", "patent_registry.json")
DRAFT_DIR = os.path.join(ROOT, "config", "patents", "drafts")
OUT_DIR = os.path.join(ROOT, "docs", "patents")
DELIV_DIR = os.path.join(ROOT, "docs", "deliverables")
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")


# ─────────────────────────────── 真源读取 ───────────────────────────────
def _j(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                           # noqa: BLE001
        return default


def _rows(sql):
    if not os.path.exists(DB):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        out = list(con.execute(sql))
        con.close()
        return out
    except Exception:                                                           # noqa: BLE001
        return []


def build_registry(write=True):
    """编写稿 (config/patents/drafts/*.json) → 真源 registry (含派生字段)。"""
    parts, pats = [], []
    if os.path.isdir(DRAFT_DIR):
        for fn in sorted(os.listdir(DRAFT_DIR)):
            if fn.endswith(".json"):
                d = _j(os.path.join(DRAFT_DIR, fn), {}) or {}
                parts.append(fn)
                pats.extend(d.get("patents") or [])
    reg = {
        "schema": "zmax-patent-registry/1",
        "updated": time.strftime("%Y-%m-%d %H:%M:%S%z"),
        "note": ("Z-MAX 专利申请渠道真源。每件专利挂 fn_ids(主)/fn_ids_related(关联); 覆盖核对见 tools/patent_center.py --coverage。"
                 "编写稿在 config/patents/drafts/, 本文件由 --build 生成。"),
        "draft_parts": parts,
        "patents": pats,
    }
    if write:
        os.makedirs(os.path.dirname(REG_J), exist_ok=True)
        with open(REG_J, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=1)
    return reg


def load_registry(auto_build=True):
    reg = _j(REG_J, None)
    if not reg and auto_build:
        reg = build_registry(write=True)
    return reg or {"patents": []}


# ─────────────────────────────── 覆盖核对 ───────────────────────────────
def fn_rows():
    """工程库功能清单 (fn_id / 名称 / 系统 / 层 / 承载模块 / 真源符号)。"""
    out = []
    for r in _rows("select fn_id, name, system_id, layer, kind, module_ref, params from functions"):
        sym = ""
        try:
            p = json.loads(r[6] or "{}")
            sym = "%s%s" % (p.get("source") or "", (":" + p.get("source_symbol")) if p.get("source_symbol") else "")
        except Exception:                                                       # noqa: BLE001
            sym = ""
        out.append({"fn_id": r[0], "name": r[1], "sys": r[2], "layer": r[3], "kind": r[4],
                    "module": r[5] or "", "symbol": sym})
    return out


def coverage():
    """渠道覆盖: 74 项功能是否**逐条**挂上专利 (主挂 + 关联)。未挂上的列出来, 不隐藏。"""
    reg = load_registry()
    fns = fn_rows()
    prim, rel = {}, {}
    for p in reg.get("patents", []):
        for fid in (p.get("fn_ids") or []):
            prim.setdefault(fid, []).append(p["pat_id"])
        for fid in (p.get("fn_ids_related") or []):
            rel.setdefault(fid, []).append(p["pat_id"])
    per_fn = []
    for f in fns:
        per_fn.append({**f, "pat_primary": prim.get(f["fn_id"], []), "pat_related": rel.get(f["fn_id"], []),
                       "channel": bool(prim.get(f["fn_id"]) or rel.get(f["fn_id"]))})
    miss = [x["fn_id"] for x in per_fn if not x["channel"]]
    per_pat = []
    for p in reg.get("patents", []):
        per_pat.append({"pat_id": p["pat_id"], "title": p["title"], "layer": p.get("layer", ""),
                        "star": p.get("star", ""), "status": p.get("status", ""),
                        "n_fn": len(p.get("fn_ids") or []), "n_rel": len(p.get("fn_ids_related") or [])})
    return {"total_fn": len(fns), "covered": len(fns) - len(miss), "uncovered": miss,
            "per_fn": per_fn, "per_patent": per_pat, "n_patent": len(reg.get("patents", [])),
            "src": os.path.relpath(REG_J, ROOT)}


# ─────────────────────────────── 真源实时数据 ───────────────────────────────
def live_facts():
    """文档里要引用的统计数字 —— 全部现算 (不许手抄, 老倪: 全局数据真实)。"""
    f = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S%z")}
    try:
        f["fn_total"] = _rows("select count(*) from functions")[0][0]
        f["fn_by_sys"] = {r[0]: r[1] for r in _rows("select system_id, count(*) from functions group by system_id")}
        f["fn_by_layer"] = {r[0]: r[1] for r in _rows("select layer, count(*) from functions group by layer")}
        f["pf_total"] = _rows("select count(*) from product_features")[0][0]
        f["pf_in_service"] = _rows("select count(*) from product_features where status='在役'")[0][0]
        f["nodes"] = _rows("select count(*) from canvas_nodes")[0][0]
    except Exception:                                                           # noqa: BLE001
        pass
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
        import zmax_platform_info as Z                                           # noqa: PLC0415
        f["matrix"] = {k: "%s (%s)" % (Z.short_model_name(v.get("name")), v.get("version") or "—")
                       for k, v in Z.matrix_columns().items()}
        f["layers"] = {r["layer"]: r["model"] for r in Z.layer_summary()["rows"]}
    except Exception:                                                           # noqa: BLE001
        f["matrix"], f["layers"] = {}, {}
    return f


# ─────────────────────────────── 文档生成 ───────────────────────────────
def draft_text(pat, cov=None, facts=None, with_facts=True):
    """一件专利的申请文件正文 (markdown): 层次清楚 + 数据真源现算 + 可落地证据。"""
    cov = cov or coverage()
    facts = facts or live_facts()
    mine = [x for x in cov["per_fn"] if pat["pat_id"] in (x["pat_primary"] + x["pat_related"])]
    L = []
    A = L.append
    A("# %s" % pat["title"])
    A("")
    A("| 项 | 内容 |")
    A("|---|---|")
    A("| 申请编号 (内部) | %s |" % pat["pat_id"])
    A("| 代号 / 阵法位置 | %s (%s) |" % (pat.get("codename", ""), pat.get("star", "")))
    A("| 层次 | %s |" % pat.get("layer", ""))
    A("| 申请类型 | %s |" % pat.get("type", "发明专利"))
    A("| 状态 | %s |" % pat.get("status", "撰写中"))
    A("| 关联功能 | 主挂 %d 条 · 关联 %d 条 |" % (len(pat.get("fn_ids") or []), len(pat.get("fn_ids_related") or [])))
    A("| 申请人 / 发明人 | 待填 (申请主体与署名按公司口径填写) |")
    A("")
    A("## 摘要")
    A("")
    A(pat.get("abstract", ""))
    A("")
    A("## 1. 技术领域")
    A("")
    A("本发明属于具身智能与工业机器人技术领域, 具体涉及%s。" % pat.get("layer", "机器人系统工程"))
    A("")
    A("## 2. 背景技术 (现有技术的问题)")
    A("")
    for i, x in enumerate(pat.get("problems") or [], 1):
        A("%d) %s" % (i, x))
    A("")
    A("## 3. 发明内容 (技术方案, 按层次展开)")
    A("")
    for i, x in enumerate(pat.get("solution") or [], 1):
        A("%d) %s" % (i, x))
    A("")
    A("### 3.1 有益效果")
    A("")
    for i, x in enumerate(pat.get("effects") or [], 1):
        A("%d) %s" % (i, x))
    A("")
    A("## 4. 权利要求书")
    A("")
    for c in (pat.get("claims") or []):
        A(c)
        A("")
    A("## 5. 具体实施方式 (实施例)")
    A("")
    for i, x in enumerate(pat.get("embodiment") or [], 1):
        A("%d) %s" % (i, x))
    A("")
    A("### 5.1 实施证据 (代码/节点/脚本 — 可直接核对)")
    A("")
    for x in (pat.get("impl_refs") or []):
        A("- `%s`" % x)
    A("")
    A("### 5.2 本专利挂载的功能条目 (专利申请渠道)")
    A("")
    A("| 功能编号 | 功能名称 | 系统 | 层 | 挂载 | 真源符号 |")
    A("|---|---|---|---|---|---|")
    for x in mine:
        role = []
        if pat["pat_id"] in x["pat_primary"]:
            role.append("主挂")
        if pat["pat_id"] in x["pat_related"]:
            role.append("关联")
        A("| %s | %s | %s | %s | %s | `%s` |" % (x["fn_id"], x["name"], x["sys"], x["layer"],
                                                 "+".join(role), x["symbol"] or x["module"]))
    A("")
    if with_facts:
        A("### 5.3 全工程真源数据 (生成时现算, 非手写)")
        A("")
        A("生成时间: %s" % facts.get("generated_at", "—"))
        A("")
        A("| 口径 | 值 |")
        A("|---|---|")
        A("| 功能条目 (工程库 functions 表) | %s 条 |" % facts.get("fn_total", "—"))
        A("| 按系统 | %s |" % " · ".join("%s %s" % (k, v) for k, v in sorted((facts.get("fn_by_sys") or {}).items())))
        A("| 按层 | %s |" % " · ".join("%s %s" % (k, v) for k, v in sorted((facts.get("fn_by_layer") or {}).items())))
        A("| 产品特征 (在役) | %s 条 (%s 在役) |" % (facts.get("pf_total", "—"), facts.get("pf_in_service", "—")))
        A("| 状态空间画布节点 | %s 个 |" % facts.get("nodes", "—"))
        A("| 各层在役模型 (与主控台模型矩阵同源) | %s |" % " · ".join(
            "%s %s" % (k, v) for k, v in sorted((facts.get("matrix") or {}).items())))
        A("")
        A("> 上述数字全部由 `tools/patent_center.py` 从单一真源现算: 工程库 `data/database/zmax/zmax_engineering.db`、"
          "`models/active_models.json`、主控台模型矩阵 `tools/model_config_matrix.py`。真源变了, 文档重生成即变 —— 不存在手写漂移。")
        A("")
    A("---")
    A("")
    A("*本文件由 `tools/patent_center.py` 生成 (真源 `%s`), 供专利申请撰写与内部评审使用; 申请号/公开号/发明人按提交后回填。*"
      % cov.get("src", "config/patents/patent_registry.json"))
    return "\n".join(L)


def export(which="all", out_dir=None, fmt=("md",)):
    """导出申请文件: 每件一个 md (可选 docx) + 一份汇总清单。返回写出的文件列表。"""
    reg = load_registry()
    cov, facts = coverage(), live_facts()
    out_dir = out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    pats = reg.get("patents", [])
    if which not in ("all", "*"):
        pats = [p for p in pats if p["pat_id"] == which]
        if not pats:
            return []
    wrote = []
    for p in pats:
        txt = draft_text(p, cov=cov, facts=facts)
        base = "%s_%s" % (p["pat_id"], _safe(p["title"])[:48])
        if "md" in fmt:
            fp = os.path.join(out_dir, base + ".md")
            with open(fp, "w", encoding="utf-8") as f:
                f.write(txt)
            wrote.append(fp)
        if "docx" in fmt:
            dp = _write_docx(p, txt, os.path.join(out_dir, base + ".docx"))
            if dp:
                wrote.append(dp)
    # 汇总清单 (层级总览 + 覆盖)
    idx = ["# Z-MAX 专利申请渠道清单 (总览)", "",
           "生成时间: %s" % facts.get("generated_at", "—"), "",
           "## 一、层级与件数", "", "| 层次 | 件数 | 专利 |", "|---|---|---|"]
    by = {}
    for p in reg.get("patents", []):
        by.setdefault(p.get("layer", "—"), []).append("%s %s" % (p["pat_id"], p.get("title", "")))
    for k in sorted(by):
        idx.append("| %s | %d | %s |" % (k, len(by[k]), " ; ".join(by[k])))
    idx += ["", "## 二、功能 → 专利渠道覆盖", "",
            "- 功能条目: **%d 条** · 已挂渠道: **%d 条** (%.1f%%) · 未挂: %s"
            % (cov["total_fn"], cov["covered"], 100.0 * cov["covered"] / max(1, cov["total_fn"]),
               ("%d 条 %s" % (len(cov["uncovered"]), ",".join(cov["uncovered"][:8]))) if cov["uncovered"] else "0 条 (渠道 100% 预留)"),
            "", "| 专利 | 层次 | 主挂功能 | 关联功能 | 状态 |", "|---|---|---|---|---|"]
    for x in cov["per_patent"]:
        idx.append("| %s %s | %s | %d | %d | %s |" % (x["pat_id"], x["title"][:34], x["layer"], x["n_fn"], x["n_rel"], x["status"]))
    idx += ["", "## 三、全工程真源数据 (现算)", "",
            "- 功能 %s 条 (按系统 %s; 按层 %s)" % (facts.get("fn_total"), facts.get("fn_by_sys"), facts.get("fn_by_layer")),
            "- 产品特征 %s 条 (%s 在役) · 画布节点 %s 个" % (facts.get("pf_total"), facts.get("pf_in_service"), facts.get("nodes")),
            "- 各层在役模型: %s" % facts.get("matrix"), "",
            "> 数据真源: 工程库 functions/product_features/canvas_nodes + models/active_models.json + 主控台模型矩阵; 现算不手写。"]
    fp = os.path.join(out_dir, "00_专利申请渠道清单.md")
    with open(fp, "w", encoding="utf-8") as f:
        f.write("\n".join(idx) + "\n")
    wrote.append(fp)
    return wrote


def _safe(s):
    import re
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(s or "")).strip("_")


def _write_docx(pat, txt, path):
    """md 正文 → docx (有 python-docx 才写; 没有就跳过, 不影响 md 导出)。"""
    try:
        from docx import Document                                              # noqa: PLC0415
    except Exception:                                                           # noqa: BLE001
        return None
    doc = Document()
    for line in txt.splitlines():
        s = line.rstrip()
        if s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("|"):
            doc.add_paragraph(s)
        elif s.startswith("> "):
            doc.add_paragraph(s[2:])
        elif s.startswith("- "):
            doc.add_paragraph(s[2:], style="List Bullet")
        else:
            doc.add_paragraph(s)
    doc.save(path)
    return path


def preview(pat_id):
    reg = load_registry()
    for p in reg.get("patents", []):
        if p["pat_id"] == pat_id:
            return draft_text(p)
    return "⛔ 未找到专利 %s (真源 %s)" % (pat_id, os.path.relpath(REG_J, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="编写稿 → 真源 registry")
    ap.add_argument("--coverage", action="store_true", help="渠道覆盖核对")
    ap.add_argument("--export", nargs="?", const="all", help="导出 all 或某件 pat_id")
    ap.add_argument("--preview", help="打印某件专利正文")
    ap.add_argument("--json", action="store_true", help="输出 JSON (给 GUI)")
    ap.add_argument("--out", default=None, help="导出目录 (默认 docs/patents)")
    a = ap.parse_args()
    if a.build:
        r = build_registry(True)
        print("✅ 真源生成: %s (%d 件)" % (os.path.relpath(REG_J, ROOT), len(r["patents"])))
    if a.coverage or a.json:
        cov = coverage()
        if a.json:
            print(json.dumps(cov, ensure_ascii=False, indent=1))
        else:
            print("渠道覆盖: %d/%d 已挂%s" % (cov["covered"], cov["total_fn"],
                                            "" if not cov["uncovered"] else " · 未挂: %s" % cov["uncovered"]))
    if a.export:
        wrote = export(a.export, a.out, fmt=("md", "docx"))
        print("导出 %d 个文件:" % len(wrote))
        for w in wrote:
            print("  " + os.path.relpath(w, ROOT))
    if a.preview:
        print(preview(a.preview))
    if not any([a.build, a.coverage, a.export, a.preview, a.json]):
        cov = coverage()
        print("专利 %d 件 · 功能渠道 %d/%d" % (cov["n_patent"], cov["covered"], cov["total_fn"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
