#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三件套同源导出 — 项目立项文档 + 供应商 SOR + 合作协议 (2026-10-10)

要求: 三份文档必须来自**同一数据源**(单一工程库 + 平台真源), 且能自证同源。
做法: 依次调用三个导出器 → 收集各自 manifest → 断言三份文档记录的源库 sha256 完全一致 →
      写 bundle/manifest.json (含一致性断言结果)。

用法:
  python3 tools/docs_bundle.py          # 导出三件套到一个包
  python3 tools/docs_bundle.py --check  # 只校验现有最新三份是否同源
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "outputs", "docs_bundle")
PY = sys.executable
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
EXPORTERS = [
    ("项目立项文档", "tools/project_doc_export.py", "outputs/project_docs", "manifest.json", "engineering_db_sha256"),
    ("供应商 SOR", "tools/sor_export.py", "outputs/sor", "manifest.json", "source_db_sha256"),
    ("合作协议", "tools/agreement_export.py", "outputs/agreements", "manifest.json", "source_db_sha256"),
]


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def newest(pat):
    c = glob.glob(os.path.join(ROOT, pat))
    return max(c, key=os.path.getmtime) if c else None


def collect():
    rows = []
    for name, tool, outdir, man, key in EXPORTERS:
        d = newest(os.path.join(outdir, "*"))
        m = os.path.join(d, man) if d else None
        md = json.load(open(m, encoding="utf-8")) if m and os.path.isfile(m) else {}
        rows.append({"name": name, "tool": tool, "dir": os.path.relpath(d, ROOT) if d else None,
                     "manifest": m and os.path.relpath(m, ROOT), "sha_key": key,
                     "src_sha": md.get(key) or (md.get("sources") or {}).get("engineering_db_sha256"),
                     "files": md.get("files", {})})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.check:
        for name, tool, *_ in EXPORTERS:
            print("▶ 导出 %s (%s)" % (name, tool))
            r = subprocess.run([PY, tool], cwd=ROOT, capture_output=True, text=True)
            for ln in (r.stdout or "").strip().splitlines()[:1]:
                print("   " + ln)
            if r.returncode != 0:
                print("   ⛔ 失败:\n" + (r.stderr or "")[-400:])
                return 1
    rows = collect()
    db_sha = sha(DB)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT, ts)
    os.makedirs(out, exist_ok=True)
    same = [r for r in rows if r["src_sha"]]
    consistent = all(r["src_sha"] == db_sha for r in same) if same else False
    bundle = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "data_source": {"engineering_db": os.path.relpath(DB, ROOT), "engineering_db_sha256": db_sha,
                              "platform_sources": ["config/platform/zmax_platform.json",
                                                   "config/platform/zmax_project_bom.json",
                                                   "config/platform/zmax_data_governance.json",
                                                   "feature.dbc", "flows/scenes_5jobs.json"]},
              "documents": rows,
              "consistency": {"同源断言": "三份文档记录的工程库 sha256 必须一致",
                              "结果": "✅ 同源一致" if consistent else "⛔ 不一致 (见下)",
                              "doc_db_sha256": {r["name"]: (r["src_sha"] or "未记录")[:16] for r in rows},
                              "actual_db_sha256": db_sha[:16]}}
    json.dump(bundle, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # 三份文档实体一并收进包 (方便直接发放)
    for r in rows:
        if r["dir"]:
            dst = os.path.join(out, os.path.basename(r["dir"]) + "_" + r["name"])
            if not os.path.isdir(dst):
                shutil.copytree(os.path.join(ROOT, r["dir"]), dst, dirs_exist_ok=True)
    print("\n═══ 三件套同源导出 ═══")
    for r in rows:
        print("  %-8s %s" % (r["name"], r["dir"]))
        for fn, meta in (r["files"] or {}).items():
            print("     - %-34s %8s B  sha256=%s…" % (fn, meta["bytes"], meta["sha256"][:12]))
    print("  工程库 sha256 %s… (三份文档记录值: %s)"
          % (db_sha[:16], {r["name"]: (r["src_sha"] or "-")[:8] for r in rows}))
    print("  %s" % bundle["consistency"]["结果"])
    print("  包目录: %s" % os.path.relpath(out, ROOT))
    return 0 if consistent else 1


if __name__ == "__main__":
    sys.exit(main())
