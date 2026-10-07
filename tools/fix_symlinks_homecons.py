#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修链器: 软链的**目标字符串**里写死了家目录老路径 ⇒ 指向工程内新路径。

为什么需要 (2026-10-07 实测):
  家目录整合删掉老路径后, 一次 `find ~ -xtype l` 报出 1121 条断链 ——
  `zmax/models/*` 全是 `→ /home/ubuntu/zmax_data/...`, `gui-venv311/bin` 也是
  `→ /home/ubuntu/lerobot-venv/bin` 这种。**软链目标字符串不会被"改引用"扫到**
  (它不在任何文件内容里), 必须在搬迁后单独修一遍。

用法: python3 tools/fix_symlinks_homecons.py --dry | --apply
"""
import argparse
import os
import subprocess
import sys
import time

HOME = "/home/ubuntu"
REPO = "/home/ubuntu/zmax"
MAP = [("/home/ubuntu/zmax_data", "/home/ubuntu/zmax/zmax_data"),
       ("/home/ubuntu/lerobot-smolvla-lew", "/home/ubuntu/zmax/external/lerobot-smolvla-lew"),
       ("/home/ubuntu/INTACT-JEPA", "/home/ubuntu/zmax/external/INTACT-JEPA"),
       ("/home/ubuntu/gs-venv", "/home/ubuntu/zmax/venvs/gs-venv"),
       ("/home/ubuntu/lerobot-venv", "/home/ubuntu/zmax/venvs/lerobot-venv"),
       ("/home/ubuntu/dds-venv", "/home/ubuntu/zmax/venvs/dds-venv"),
       ("/home/ubuntu/colmap-venv", "/home/ubuntu/zmax/venvs/colmap-venv"),
       ("/home/ubuntu/cuda-nvcc-env", "/home/ubuntu/zmax/venvs/cuda-nvcc-env"),
       ("/home/ubuntu/cuda-shim", "/home/ubuntu/zmax/toolchains/cuda-shim"),
       ("/home/ubuntu/hermes-install", "/home/ubuntu/zmax/hermes/install"),
       ("/home/ubuntu/zmax_ss_remote", "/home/ubuntu/zmax/zmax_data/ss_live"),
       ("/home/ubuntu/zmax_moveit_plan", "/home/ubuntu/zmax/zmax_data/runtime/moveit_plan"),
       ("/home/ubuntu/stable-wm-cache", "/home/ubuntu/zmax/zmax_data/stable-wm-cache"),
       ("/home/ubuntu/aoi_v4", "/home/ubuntu/zmax/zmax_data/aoi_v4"),
       ("/home/ubuntu/l4_ab", "/home/ubuntu/zmax/zmax_data/l4_ab"),
       ("/home/ubuntu/android-sdk", "/home/ubuntu/zmax/zmax_data/toolchains/android-sdk"),
       ("/home/ubuntu/zmax_rel", "/home/ubuntu/zmax"),
       ("/home/ubuntu/zmax_dds", "/home/ubuntu/zmax/dds"),
       ("/home/ubuntu/zmax_aoi", "/home/ubuntu/zmax/tools/aoi")]
SKIP = ("/.git/", "/node_modules/", "/__pycache__/", "/proc/", "/sys/", "/dev/", "/run/")


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--root", action="append", default=None)
    a = ap.parse_args()
    roots = a.root or [REPO, HOME + "/.hermes", HOME]
    r = subprocess.run(["find"] + roots + ["-maxdepth", "8", "-type", "l"],
                       capture_output=True, text=True, timeout=600)
    links = [l for l in r.stdout.splitlines() if l and not any(s in l for s in SKIP)]
    log("扫到软链 %d 条 · 模式=%s" % (len(links), "APPLY" if a.apply else "DRY"))
    fixed, still_bad, seen = 0, [], set()
    for l in links:
        if l in seen:
            continue
        seen.add(l)
        try:
            t = os.readlink(l)
        except OSError:
            continue
        if not t.startswith("/"):
            continue                                    # 相对链: 搬迁后多数仍成立, 不动
        nt = t
        for o, w in MAP:
            if nt == o or nt.startswith(o + "/"):
                nt = w + nt[len(o):]
                break
        if nt == t:
            continue
        live = os.path.exists(nt)
        log("  %-64s → %s %s" % (l[:64], nt[:64], "" if live else "(目标仍不存在!)"))
        if a.apply:
            os.unlink(l)
            os.symlink(nt, l)
        fixed += 1
        if not live:
            still_bad.append((l, nt))
    log("需修 %d 条 · 修完目标仍缺 %d 条" % (fixed, len(still_bad)))
    for l, nt in still_bad[:10]:
        log("  ⚠️ %s → %s" % (l, nt))
    r = subprocess.run(["find"] + roots + ["-maxdepth", "8", "-xtype", "l"],
                       capture_output=True, text=True, timeout=600)
    log("修后仍断链: %d 条" % len([x for x in r.stdout.splitlines() if x and not any(s in x for s in SKIP)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
