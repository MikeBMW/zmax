#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_release.py — 查 GitHub Release / CI 状态 (token 只从 ~/.git-credentials 读, 不打印)。

用法: python3 tools/check_release.py [v5.50.72 ...]
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

REPO = "MikeBMW/zmax"


def _token() -> str:
    p = os.path.expanduser("~/.git-credentials")
    try:
        txt = open(p, encoding="utf-8", errors="replace").read()
        m = re.search(r"([A-Za-z0-9_]{20,})", txt)
        return m.group(1) if m else ""
    except Exception:                                                         # noqa: BLE001
        return ""


def api(path: str, tok: str):
    req = urllib.request.Request("https://api.github.com/repos/%s%s" % (REPO, path),
                                 headers={"Authorization": "token %s" % tok,
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.load(r)


def main() -> int:
    tags = sys.argv[1:] or ["v5.50.72"]
    tok = _token()
    if not tok:
        print("❌ 没找到 token (~/.git-credentials)")
        return 1
    st, runs = api("/actions/runs?per_page=6", tok)
    print("== CI runs (最近 6) ==")
    for r in (runs.get("workflow_runs") or [])[:6]:
        print("  %-32s %-11s %-10s %s" % (r["name"][:32], r.get("status"), r.get("conclusion"),
                                          (r.get("head_branch") or "")[:18]))
    for t in tags:
        print("== Release %s ==" % t)
        try:
            st, d = api("/releases/tags/%s" % t, tok)
            print("  HTTP %s · draft=%s · name=%s · created=%s · assets=%d"
                  % (st, d.get("draft"), d.get("name"), (d.get("created_at") or "")[:16],
                     len(d.get("assets") or [])))
            for a in (d.get("assets") or [])[:5]:
                print("   - %s · %s bytes · 下载 %s 次" % (a.get("name"), a.get("size"),
                                                          a.get("download_count")))
        except Exception as e:                                                # noqa: BLE001
            print("  ✗ %s" % str(e)[:100])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
