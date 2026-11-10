#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_doc_system.py — 文档系统体检（老倪 2026-11-11「再次检查文档系统」）

查四件事，缺一件就不算"一目了然"：
  ① 每一层都有 README 入口
  ② README 里 `反引号` 引用的文件/目录真实存在（防止入口本身指空）
  ③ 无断链软链
  ④ CODE-MAP 映射校验通过（调 verify_doc_code_map.py --strict）

用法
----
    gui-venv311/bin/python tools/verify_doc_system.py
    gui-venv311/bin/python tools/verify_doc_system.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
LAYERS = ["0-总纲", "1-天枢-产品边界", "2-天璇-作业任务", "3-天玑-能力功能",
          "4-天权-模型算法", "5-玉衡-指标验收", "6-开阳-工程落地", "7-瑶光-记录追溯"]

# README 里反引号里的这些不是路径，跳过
NOT_PATH = re.compile(r"^(https?:|--|ZMAX_|SS_|HF_|~|git |ls |find |grep |cd |python|conda|"
                      r"pip |bash |cat |cp |mv |rm |chmod |sudo |systemctl|docker )")
# 版本号/档位形态 (5.50.A/B/C、v1.0.4、X.Y.Z) —— 不是路径
VERLIKE = re.compile(r"^v?\d+(\.\d+)+([.-][A-Za-z0-9.]+)?(/[A-Za-z])?$|^\d+\.\d+\.")
# 纯通配 ( *.md / * ) —— 不是具体文件, 不算悬空
WILDONLY = re.compile(r"^[\w./-]*\*[\w./*-]*\.[A-Za-z0-9]+$|^\*$")
# 示例/占位文本 (含 < > 或 x.y 之类), 不是真路径
PLACEHOLDER = re.compile(r"[<>]|^v?\d+\.x\.|\bx\.y\b")
CODEISH = re.compile(r"\.(py|json|sh|yaml|yml|toml|cfg|ini|pt|onnx|npz|log|txt)$")
DOCISH = re.compile(r"\.(md|docx|pdf|pptx|xlsx|csv|png|jpg|jpeg|svg)$")


def _refs(text: str):
    """抽出 README 中像文件/目录的 `反引号` 词。"""
    out = []
    for m in re.finditer(r"`([^`\n]{2,120})`", text):
        s = m.group(1).strip()
        if not s or NOT_PATH.match(s) or " " in s:
            continue
        if s.startswith(("[", "{")):
            continue
        if PLACEHOLDER.search(s):
            continue
        if VERLIKE.match(s):
            continue
        if CODEISH.search(s) or DOCISH.search(s) or "/" in s:
            # 去掉行号后缀 `file.py:12` 与锚点 `x.json#seg`
            s = re.sub(r":\d+(-\d+)?$", "", s)
            s = s.split("#")[0]
            if not s:
                continue
            out.append(s)
    return out


def _resolve(ref: str, layer_dir: str):
    """按三种基准解析：本层目录 / docs 根 / 仓库根。"""
    if "*" in ref:
        import glob as _g
        for base in (layer_dir, DOCS, ROOT):
            if _g.glob(os.path.join(base, ref)):
                return True
            if _g.glob(os.path.join(base, "**", ref), recursive=True):
                return True
        return None
    ref = os.path.expanduser(ref)
    cands = [os.path.join(layer_dir, ref), os.path.join(DOCS, ref), os.path.join(ROOT, ref)]
    for c in cands:
        if os.path.exists(c):
            return c
    # 目录前缀引用（`ops/` 写作 `ops`）
    for c in cands:
        if os.path.isdir(c.rstrip("/")):
            return c
    # 裸文件名: 在本层递归找同名, 唯一命中即算存在 (表格里常只写文件名, 位置单列说明子目录)
    base = os.path.basename(ref.rstrip("/"))
    if base and "/" not in ref:
        hits = []
        for b, _, fs in os.walk(layer_dir):
            if base in fs or os.path.isdir(os.path.join(b, base)):
                hits.append(os.path.join(b, base))
                if len(hits) > 1:
                    return True          # 多处同名也算找到(不判悬空)
        if hits:
            return hits[0]
        # 全仓兜底 (README 里可能只写文件名, 真身在 src/ 或 tools/)
        for sub in ("src", "tools", "config"):
            for b, _, fs in os.walk(os.path.join(ROOT, sub)):
                if "__pycache__" in b:
                    continue
                if base in fs:
                    return os.path.join(b, base)
    return None


def run():
    res = {"layers": [], "missing_readme": [], "dead_refs": [], "broken_links": [],
           "code_map": {}, "ok": False}

    for L in LAYERS:
        d = os.path.join(DOCS, L)
        if not os.path.isdir(d):
            res["missing_readme"].append(L + " (目录不存在)")
            continue
        nfiles = sum(len(f) for _, _, f in os.walk(d))
        rp = os.path.join(d, "README.md")
        has = os.path.isfile(rp)
        refs = []
        if has:
            txt = open(rp, encoding="utf-8", errors="replace").read()
            for r in _refs(txt):
                if _resolve(r, d) is None:
                    refs.append(r)
        res["layers"].append({"layer": L, "files": nfiles, "readme": has,
                              "bad_refs": refs})
        if not has:
            res["missing_readme"].append(L)
        for r in refs:
            res["dead_refs"].append({"layer": L, "ref": r})

    # 断链软链
    for base, dirs, files in os.walk(DOCS):
        for n in dirs + files:
            p = os.path.join(base, n)
            if os.path.islink(p) and not os.path.exists(p):
                res["broken_links"].append(os.path.relpath(p, ROOT))

    # CODE-MAP
    try:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "verify_doc_code_map.py"),
                            "--strict", "--json"], capture_output=True, text=True, timeout=180)
        j = json.loads(r.stdout or "{}")
        res["code_map"] = {"rows": j.get("rows"), "fail": len(j.get("fail") or []),
                           "warn": len(j.get("warn") or [])}
    except Exception as e:                                          # noqa: BLE001
        res["code_map"] = {"err": "%s: %s" % (type(e).__name__, e)}

    cm = res["code_map"]
    res["ok"] = (not res["missing_readme"] and not res["dead_refs"]
                 and not res["broken_links"] and cm.get("fail") == 0)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = run()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1

    print("文档系统体检 —— docs/")
    print("=" * 70)
    print("%-22s %8s %6s %s" % ("层", "文件数", "入口", "入口里的悬空引用"))
    for L in r["layers"]:
        print("%-22s %8d %6s %s" % (L["layer"], L["files"],
                                    "有" if L["readme"] else "缺",
                                    ("%d 处" % len(L["bad_refs"])) if L["bad_refs"] else "—"))
    print("=" * 70)
    cm = r["code_map"]
    if "err" in cm:
        print("CODE-MAP  : 跑失败 — %s" % cm["err"])
    else:
        print("CODE-MAP  : %s 行, FAIL %s, WARN %s" % (cm.get("rows"), cm.get("fail"), cm.get("warn")))
    print("断链软链  : %d" % len(r["broken_links"]))
    print("缺入口    : %d %s" % (len(r["missing_readme"]), r["missing_readme"] or ""))
    if r["dead_refs"]:
        print("悬空引用  : %d" % len(r["dead_refs"]))
        for x in r["dead_refs"][:10]:
            print("   [%s] `%s`" % (x["layer"], x["ref"]))
        if len(r["dead_refs"]) > 10:
            print("   … 另 %d 处" % (len(r["dead_refs"]) - 10))
    print("=" * 70)
    print("判定: %s" % ("PASS" if r["ok"] else "FAIL"))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
