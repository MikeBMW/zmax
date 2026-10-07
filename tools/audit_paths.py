#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_paths.py — 家目录整合/改路径后的「死角」静态审计 (2026-10-08)

为什么要有它
  2026-10-08 实测教训: 按 绝对路径 / `~/x` / `$HOME/x` 三种写法改引用**是不够的**。
  还有两种写法会漏(并且真的让 SDK 执行腿整体失效、页面报「已下发(真动)」但机器人不动):
    第4种  os.path.join(os.path.expanduser("~"), "zmax_data", ...)   # `~` 与目录名分开拼
    第5种  Path.home() / "zmax_data" / ...   /   os.path.join(os.environ["HOME"], "zmax_data")
  本脚本把这两类 + 老顶层名(zmax_rel / lerobot-smolvla-lew / ...)一起扫出来, 并给出可执行判据。

用法
  python3 tools/audit_paths.py            # 扫仓库, 只读, 不修改
  python3 tools/audit_paths.py --json     # 机器可读
退出码: 0=干净, 1=有命中(需人工确认)
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "zmax_data", "external", "venvs", "toolchains", "node_modules",
             "__pycache__", ".mypy_cache", ".pytest_cache", "venv", ".venv"}

# 命中即"必然错"的模式(老工程根/老顶层名/第4·5种写法)
HARD = [
    # 第4种: expanduser("~") 与 zmax_data 分开拼(同一文件里出现)
    (re.compile(r'expanduser\(\s*[\'"]~[\'"]\s*\)'), "expanduser-4th", "第4种写法(expanduser('~') 分开拼)"),
    # 第5种: Path.home() / "zmax_data"
    (re.compile(r'Path\.home\(\)\s*/\s*[\'"]zmax_data[\'"]'), "pathhome-5th", "第5种写法(Path.home()/zmax_data)"),
    (re.compile(r'environ(?:\.get)?\(\s*[\'"]HOME[\'"]'), "envhome-5th", "第5种写法(os.environ['HOME'] 分开拼)"),
    # 老顶层名(工程根已并入 zmax/)
    (re.compile(r'/home/ubuntu/zmax_rel\b'), "old-root", "老工程根 zmax_rel"),
    (re.compile(r'(?<!zmax/external/)/home/ubuntu/lerobot-smolvla-lew\b'), "old-fork", "老 fork 路径(应为 zmax/external/)"),
    (re.compile(r'[\'"]~/lerobot-smolvla-lew'), "old-fork-tilde", "老 fork 路径(~/)"),
    (re.compile(r'/home/ubuntu/zmax_train\b'), "old-train", "老 zmax_train"),
    (re.compile(r'/home/tashan/(?!\.zmax)'), "orin-old", "Orin 上非 .zmax 路径"),
]
# 老数据目录(需人工判断: 有些是刻意保留的历史快照)
SOFT = [
    (re.compile(r'(?<!/zmax)/home/ubuntu/zmax_data\b'), "flat-data", "扁平老数据目录 /home/ubuntu/zmax_data"),
    (re.compile(r'[\'"]~/zmax_data'), "tilde-data", "扁平老数据目录 ~/zmax_data"),
    (re.compile(r'[\'"]\$HOME/zmax_data'), "envhome-data", "$HOME/zmax_data"),
]
EXT = (".py", ".sh", ".bash", ".json", ".yaml", ".yml", ".html", ".js", ".php", ".toml", ".cfg", ".ini", ".service", ".desktop", ".md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    hard, soft, scanned = [], [], 0
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith(EXT):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, REPO)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                txt = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            scanned += 1
            lines = txt.split("\n")
            # 第4种要"同一文件出现 expanduser('~') 且出现 zmax_data"才算硬命中
            has_expand_home = any(HARD[0][0].search(l) for l in lines)
            for i, l in enumerate(lines, 1):
                for rx, tag, why in HARD:
                    if tag == "expanduser-4th":
                        if rx.search(l) and "zmax_data" in txt.replace("zmax_data", "zmax_data"):
                            hard.append({"f": rel, "n": i, "tag": tag, "why": why, "l": l.strip()[:150]})
                    elif rx.search(l):
                        hard.append({"f": rel, "n": i, "tag": tag, "why": why, "l": l.strip()[:150]})
                for rx, tag, why in SOFT:
                    if rx.search(l):
                        soft.append({"f": rel, "n": i, "tag": tag, "why": why, "l": l.strip()[:150]})

    # 老数据目录是否还在磁盘上
    flat = os.path.isdir("/home/ubuntu/zmax_data")
    out = {"repo": REPO, "scanned_files": scanned, "hard": hard, "soft": soft,
           "flat_data_dir_exists": flat, "home_top": sorted(os.listdir("/home/ubuntu"))[:40]}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print("扫了 %d 个代码/配置文件" % scanned)
        print("\n【硬命中 = 必然错, 必须改】%d" % len(hard))
        for h in hard:
            print("  %s:%s  [%s] %s" % (h["f"], h["n"], h["tag"], h["l"][:110]))
        print("\n【软命中 = 老数据目录写法, 需人工判断是否刻意保留】%d" % len(soft))
        seen = {}
        for s in soft:
            seen.setdefault(s["f"], 0)
            seen[s["f"]] += 1
        for f, c in sorted(seen.items(), key=lambda kv: -kv[1])[:20]:
            print("  %-58s ×%d" % (f, c))
        print("\n/home/ubuntu/zmax_data 还在磁盘上: %s" % flat)
        print("~ 顶层: %s" % ", ".join(out["home_top"]))
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
