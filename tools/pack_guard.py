#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pack_guard.py — 打包前的软链闸 (给静静: 别把 Linux 软链打进 Windows 包)

为什么: 仓库里 `flows/state_space_obs.json`、`config`、`data`、`zmax_data` 都是软链;
原样打进 Windows 包后，那边解析不了（断链或自指），GUI「打开总工程」直接加载失败
（2026-11-10 本机 app9 事故）。

用法:
  python3 tools/pack_guard.py <包目录>          # 只检查, 有软链 exit 1
  python3 tools/pack_guard.py <包目录> --fix     # 就地实体化 (cp -L 语义)
打包脚本里放在 tar/copy 之后、出包之前当闸门用。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys


def _looks_like_placeholder(p: str) -> str | None:
    """git 在 Windows (core.symlinks=false) 会把软链检出成**内容就是路径的小文本文件**。
    返回它指向的真实文件(存在则返回), 否则 None。"""
    try:
        if os.path.getsize(p) > 512:
            return None
        txt = open(p, "r", encoding="utf-8", errors="ignore").read().strip()
    except OSError:
        return None
    if not txt or "\n" in txt or len(txt) > 400:
        return None
    cand = txt if os.path.isabs(txt) else os.path.join(os.path.dirname(p), txt)
    cand = os.path.normpath(cand)
    return cand if os.path.isfile(cand) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()

    links, ph = [], []
    for dirpath, dirs, files in os.walk(a.root):
        for name in list(dirs) + files:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                links.append((p, os.readlink(p), os.path.exists(p)))
        for name in files:
            p = os.path.join(dirpath, name)
            if os.path.islink(p):
                continue
            tgt = _looks_like_placeholder(p)
            if tgt:
                ph.append((p, tgt))
    if not links and not ph:
        print("✅ 没有软链/占位: %s" % a.root)
        return 0
    if ph:
        print("⚠️ 发现 %d 个「软链占位文本文件」(git core.symlinks=false 检出):" % len(ph))
        for p, t in ph[:20]:
            print("   %-60s -> %s" % (p, t))
        if a.fix:
            for p, t in ph:
                try:
                    shutil.copy2(t, p)
                except Exception as e:                                      # noqa: BLE001
                    print("   ✗ 占位实体化失败 %s: %s" % (p, e))
            print("   → 已按目标内容覆盖占位文件")
    if not links:
        return 0 if not a.fix else 0

    print("⚠️ 发现 %d 个软链 (Windows 上会断/自指):" % len(links))
    for p, tgt, ok in links:
        print("   %-60s -> %s%s" % (p, tgt, "" if ok else "   [断]"))
    if not a.fix:
        print("\n用 --fix 就地实体化, 或在打包命令里加 `cp -rL` / `tar --dereference`。")
        return 1

    fixed = bad = 0
    for p, tgt, ok in links:
        real = os.path.realpath(p)
        if not os.path.exists(real):
            print("   ✗ 断链无法实体化: %s" % p)
            bad += 1
            continue
        tmp = p + ".pack_tmp"
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                raise RuntimeError("unexpected")
            if os.path.isdir(real):
                shutil.copytree(real, tmp, symlinks=False)
            else:
                shutil.copy2(real, tmp)
            os.remove(p)
            os.replace(tmp, p)
            fixed += 1
        except Exception as e:                                              # noqa: BLE001
            print("   ✗ %s: %s" % (p, e))
            bad += 1
    print("实体化 %d 个, 失败 %d 个" % (fixed, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
