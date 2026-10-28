#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Release 正文里的「本版 (...)：…」块换成 VERSION.md 里当前版本的摘要。

为什么需要它: `svenstaro/upload-release-action@v2` 只吃静态 `body:` 文本，
  旧 workflow 把摘要预先固定成 v5.50.737 的一段 —— 之后每个 Release 的正文都挂 737 的内容
  (标题是新的、内容是旧的)。这里改成发布后回填: 摘要唯一依据 = VERSION.md 表首行。

用法:
  release_notes.py --tag v5.50.758                 # 读 GITHUB_TOKEN / GH_TOKEN, 直接 PATCH
  release_notes.py --tag v5.50.758 --print-only    # 只打印要写进去的正文
"""
import argparse, json, os, re, sys, urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
OWNER, REPO = "MikeBMW", "zmax"


def summary_for(tag: str):
    """VERSION.md 表首行: | **v5.50.758** | 10-27 | 摘要 |"""
    ver = tag.lstrip("v")
    for ln in (REPO_DIR / "VERSION.md").read_text(encoding="utf-8").splitlines():
        if ln.startswith(f"| **v{ver}**"):
            parts = [p.strip() for p in ln.strip().strip("|").split("|")]
            if len(parts) >= 3:
                date, txt = parts[1], parts[2]
                txt = re.sub(r"^v[\d.]+\s*[:：]\s*", "", txt)   # 去掉摘要里重复的版本号前缀
                return date, txt
    return "", ""


def api(path, method="GET", payload=None, tok=""):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"https://api.github.com{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--print-only", action="store_true")
    a = ap.parse_args()

    date, summary = summary_for(a.tag)
    if not summary:
        print(f"[release-notes] VERSION.md 里没有 {a.tag} 的行, 放弃改写", file=sys.stderr)
        return 1

    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not tok and not a.print_only:
        print("[release-notes] 没有 GITHUB_TOKEN", file=sys.stderr)
        return 2

    try:
        rel = api(f"/repos/{OWNER}/{REPO}/releases/tags/{a.tag}", tok=tok) if tok else {"body": "", "id": 0}
    except Exception as e:
        # 两个平台都没上传成功时 Release 还不存在 —— 不当成失败, 只提示
        print(f"[release-notes] {a.tag} 还没有 Release ({e}); 跳过回填", file=sys.stderr)
        return 0
    body = rel.get("body") or ""
    rid = rel.get("id")
    block = f"> 本版 ({date}): {summary}"
    # 把「本版 (...)：」及其后连续 '> ' 行整体替换成一行真实摘要
    pat = re.compile(r"^> 本版 \([^)]*\):[^\n]*(?:\n>[^\n]*)*", re.M)
    new = pat.sub(block.replace("\\", "\\\\"), body, count=1) if pat.search(body) else body + "\n\n" + block

    if a.print_only:
        print(new)
        return 0
    # PATCH 只认 release id（/releases/tags/{tag} 仅支持 GET —— 用 tag 路径会 404）
    api(f"/repos/{OWNER}/{REPO}/releases/{rid}", "PATCH", {"body": new}, tok=tok)
    # 回读校验
    chk = api(f"/repos/{OWNER}/{REPO}/releases/tags/{a.tag}", tok=tok)
    ok = block in (chk.get("body") or "")
    print(f"[release-notes] {a.tag} 回填{'成功' if ok else '失败'}: {block[:80]}…")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
