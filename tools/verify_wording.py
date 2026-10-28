#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用语判据: 工程与对外文档里不得出现口语化、AI 腔的表述。

老倪 2026-10-28: 「全局搜索, 整个工程, 文档, 不要出现 重新生成 唯一依据 预先固定 这样的口语, 不要有 AI 的味道」

扫描范围: tools / docs / config / web 的源码与文档, 外加三件对外产物 (PPT / 立项报告 MD / 工程手册 MD)。
排除: 备份 (.bak)、历史快照 (docs/data_snapshots)、本脚本的规则表、数据与日志目录。

跑法: gui-venv311/bin/python tools/verify_wording.py
"""
import os
import sys

ROOT = "/home/ubuntu/zmax"
PASS, FAIL = [], []

sys.path.insert(0, os.path.join(ROOT, "tools"))
from sweep_wording import RULES  # noqa: E402

# 判定词直接取 sweep_wording 的规则表 (唯一依据), 不在此重复维护
BANNED = []
for _pat, _rep in RULES:
    if "\\" in _pat:
        continue
    if _pat not in BANNED:
        BANNED.append(_pat)

EXT = (".py", ".md", ".html", ".json", ".txt", ".sh", ".yaml", ".yml", ".csv",
       ".java", ".service", ".proj", ".xml", ".css", ".js")
SKIP_DIR = {".git", "node_modules", "__pycache__", "gui-venv311", "venv", ".venv",
            "zmax_data", "reports", "logs", "data", "_deck_png", "图片库", "data_snapshots"}
ARTIFACTS = [
    "/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx",
    os.path.join(ROOT, "docs", "deliverables", "项目立项报告_双臂协作工位.md"),
    os.path.join(ROOT, "docs", "deliverables", "工程操作手册_三档_A_B_C.md"),
]


def chk(name, ok, detail=None):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                        (" — " + str(detail)) if detail not in (None, "") else ""))


def scan_text(path):
    hits = []
    try:
        txt = open(path, encoding="utf-8", errors="ignore").read()
    except Exception:                                                       # noqa: BLE001
        return hits
    for w in BANNED:
        if w in txt:
            hits.append(w)
    return hits


def main():
    offenders = {}
    files = 0
    for top in ("tools", "docs", "config", "web", "data/database/zmax"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, top)):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
            for fn in filenames:
                if not fn.endswith(EXT) or fn.endswith(".bak"):
                    continue
                if fn in ("sweep_wording.py", "verify_wording.py"):
                    continue
                p = os.path.join(dirpath, fn)
                files += 1
                h = scan_text(p)
                if h:
                    offenders[os.path.relpath(p, ROOT)] = h
    chk("① 源码与文档 (%d 个文件) 无口语化表述" % files, not offenders,
        "%d 个文件: %s" % (len(offenders), list(offenders.items())[:3]))

    # ② 对外产物
    try:
        from pptx import Presentation
        prs = Presentation(ARTIFACTS[0])
        blob = []
        for sl in prs.slides:
            for sh in sl.shapes:
                if sh.has_text_frame:
                    blob.append(sh.text_frame.text)
        txt = " ".join(blob)
        hit = [w for w in BANNED if w in txt]
        chk("② 成本分析 PPT (14 页) 无口语化表述", not hit, hit)
    except Exception as e:                                                  # noqa: BLE001
        chk("② 成本分析 PPT 可读", False, repr(e))
    for p in ARTIFACTS[1:]:
        h = scan_text(p)
        chk("② %s 无口语化表述" % os.path.basename(p), not h, h)

    # ③ 页面文案 (配置中心 + ar3d)
    try:
        import json
        import urllib.request
        html = urllib.request.urlopen("http://127.0.0.1:8797/ar3d", timeout=10).read().decode("utf-8", "ignore")
        hit = [w for w in BANNED if w in html]
        chk("③ ar3d 页面文案无口语化表述", not hit, hit)
        raw = urllib.request.urlopen("http://127.0.0.1:8797/api/ar/vision", timeout=8).read()
        api = json.loads(raw)
        hit = [w for w in BANNED if w in json.dumps(api, ensure_ascii=False)]
        chk("③ /api/ar/vision 文案无口语化表述", not hit, hit)
    except Exception as e:                                                  # noqa: BLE001
        chk("③ ar3d 可访问", False, repr(e))

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  -", f)
        for k, v in list(offenders.items())[:12]:
            print("  ·", k, v)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
