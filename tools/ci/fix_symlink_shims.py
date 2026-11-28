#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_symlink_shims.py — 把被同步/git add 写坏的软链 shim 还原成真软链。

场景
----
从 Linux 中枢同步代码时，zip/tar/rsync 会**解引用软链**：550C 上
`src/lerobot/perception/yolo.py` 是软链（指向 policies/left_right/state_space/perception_yolo.py），
到了 Windows 工作区变成整份源码。本地 index 里这条仍是 mode 120000，于是
`git add -u` 把它记成「软链，目标串 = 21KB 源码」——打包机 checkout 建软链时报
`Filename too long`，Windows/macOS 所有 job 全挂（2026-11-27 实测）。

用法
----
    python tools/ci/fix_symlink_shims.py                 # 只看
    python tools/ci/fix_symlink_shims.py --fix           # 还原索引(+skip-worktree 防复发)
    python tools/ci/fix_symlink_shims.py --fix --ref v5.50.785

判据（打包前必须过）：
    git ls-tree -r -l HEAD | awk '$1=="120000" && $4>200'   # 输出必须为空
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

MAX_SANE_TARGET = 200      # 软链目标串正常几十字节；>200 基本就是整份文件内容


def git(*args: str) -> str:
    r = subprocess.run(("git",) + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("git %s 失败: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def bad_entries(ref: str = "HEAD") -> list[tuple[str, int]]:
    out = []
    for line in git("ls-tree", "-r", "-l", ref).split("\n"):
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        p = meta.split()
        if len(p) >= 4 and p[0] == "120000" and int(p[3]) > MAX_SANE_TARGET:
            out.append((path, int(p[3])))
    return out


def good_blob(path: str, ref: str) -> str | None:
    try:
        line = git("ls-tree", ref, "--", path).strip()
    except RuntimeError:
        return None
    if not line:
        return None
    meta = line.split("\t")[0].split()
    if meta[0] != "120000":
        return None
    if int(meta[3]) > MAX_SANE_TARGET:
        return None
    return meta[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--ref", default="v5.50.785", help="到哪个 ref 取回真软链 blob")
    ap.add_argument("--skip-worktree", action="store_true", default=True)
    args = ap.parse_args()

    if os.path.isdir(".git") is False and not os.path.exists(".git"):
        print("不在仓库根目录", file=sys.stderr)
        return 2

    bad = bad_entries("HEAD")
    if not bad:
        print("[shim] ✓ 干净：HEAD 里没有「软链目标串被写成整份文件」的条目")
        return 0

    print("[shim] ✗ %d 个软链 shim 被写坏了（打包机会报 Filename too long）：" % len(bad))
    for path, size in bad:
        print("   %-58s %6dB" % (path, size))

    if not args.fix:
        print("\n加 --fix 还原（不动工作区，只改索引）")
        return 1

    fixed = 0
    for path, _size in bad:
        blob = good_blob(path, args.ref)
        if not blob:
            print("   !! %s 在 %s 里找不到正常软链版本，需人工判断" % (path, args.ref))
            continue
        git("update-index", "--cacheinfo", "120000,%s,%s" % (blob, path))
        if args.skip_worktree:
            git("update-index", "--skip-worktree", path)
        fixed += 1
    print("[shim] 已还原 %d/%d（工作区文件未动，仍是实体内容，能正常 import）" % (fixed, len(bad)))
    print("[shim] 记得提交并复查：git ls-tree -r -l HEAD | awk '$1==\"120000\" && $4>200'")
    return 0 if fixed == len(bad) else 1


if __name__ == "__main__":
    sys.exit(main())
