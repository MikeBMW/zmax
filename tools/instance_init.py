#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""instance_init.py — 平台 / 实例 数据包的装配与切换

平台仓库 (本目录) 只放: 代码 + 平台文档 + 出厂骨架 defaults/
你的实例数据包: data/database/<产品>/  —— 真源 + 工程库 + 总工程 + 归档, 一个目录搬走即换一套数据

实例包结构
  data/database/zmax/
  ├── zmax_engineering.db     工程库 (由真源 build 出来)
  ├── zmax_space.proj         总工程 (GUI「打开总工程」)
  ├── README.md               产品/数据手册
  ├── archive/                历史工程快照
  └── sources/                ★ 真源 (可编辑/可标定 — 你自己的)
      ├── config/             标定·平台定义·任务·订单·机器人·状态机·MCD
      ├── feature.dbc         能力库
      └── canvas/             状态空间画布真源

用法
  python3 tools/instance_init.py --check                      # 体检: 平台/实例 边界是否干净
  python3 tools/instance_init.py --new /path/to/inst          # 用出厂骨架新建一个实例包
  python3 tools/instance_init.py --link /path/to/inst         # 让平台指向该实例包 (仓库内建相对符号链接)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULTS = os.path.join(ROOT, "defaults")
DEFAULT_INST = os.path.join(ROOT, "data", "database", "zmax")

# 仓库内路径 → 实例包内相对路径
LINKS = [
    ("config", "sources/config"),
    ("feature.dbc", "sources/feature.dbc"),
    ("src/lerobot/engineering/flows/state_space_obs.json", "sources/canvas/state_space_obs.json"),
]


def instance_root():
    return os.environ.get("ZMAX_INSTANCE") or DEFAULT_INST


def link_target(rel_repo_path):
    """当前仓库路径实际指向哪里 (无链接时返回自身)"""
    p = os.path.join(ROOT, rel_repo_path)
    return os.path.realpath(p)


def cmd_check():
    inst = instance_root()
    ok = True
    print("实例数据包: %s" % inst)
    print("\n① 真源指向 (仓库内应是符号链接 → 实例包)")
    for rel, sub in LINKS:
        p = os.path.join(ROOT, rel)
        is_link = os.path.islink(p)
        tgt = os.path.realpath(p) if os.path.exists(p) else ""
        inside = tgt.startswith(os.path.realpath(inst) + os.sep)
        good = (is_link and inside) or (not os.path.exists(p) and not is_link)
        ok &= good
        print("   %s %-46s → %s" % ("✅" if good else "❌", rel,
                                    os.path.relpath(tgt, ROOT) if tgt else "(无)"))
    print("\n② 实例包完整性")
    for sub in ("zmax_engineering.db", "zmax_space.proj", "README.md", "sources/config",
                "sources/feature.dbc", "sources/canvas"):
        p = os.path.join(inst, sub)
        e = os.path.exists(p)
        ok &= e
        print("   %s %s" % ("✅" if e else "❌", sub))
    print("\n③ 公开仓库不含你的数据 (git 跟踪面)")
    dirty = subprocess.run(["git", "ls-files"] + [r for r, _ in LINKS], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    if dirty:
        ok = False
        print("   ❌ 仍被跟踪 %d 项: %s" % (len(dirty), dirty[:3]))
    else:
        print("   ✅ config/ · feature.dbc · 画布真源 均未跟踪 (只随实例包走)")
    print("\n④ 出厂骨架 (供全新实例用)")
    n = sum(len(f) for _, _, f in os.walk(DEFAULTS)) if os.path.isdir(DEFAULTS) else 0
    ok &= n > 0
    print("   %s defaults/ %d 个骨架文件 (无你的真值)" % ("✅" if n else "❌", n))
    print("\n%s" % ("🎉 平台/实例 边界干净" if ok else "⚠️ 有 ❌ 项, 见上"))
    return 0 if ok else 1


def cmd_new(dst, force=False):
    if os.path.exists(dst) and os.listdir(dst) and not force:
        print("❌ 目标非空: %s (加 --force 覆盖)" % dst); return 1
    for sub in ("sources/config", "sources/canvas", "archive"):
        os.makedirs(os.path.join(dst, sub), exist_ok=True)
    # 出厂骨架 → 实例 (结构在, 数值空; 你在实例包内改成自己的)
    n = 0
    for r, _, fs in os.walk(os.path.join(DEFAULTS, "config")):
        for f in fs:
            src = os.path.join(r, f)
            rel = os.path.relpath(src, DEFAULTS)
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out); n += 1
    for rel, sub in (("feature.dbc", "sources/feature.dbc"), ("canvas/state_space_obs.json", "sources/canvas/state_space_obs.json")):
        src = os.path.join(DEFAULTS, rel)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, sub)); n += 1
    print("✅ 新建实例包: %s (%d 个骨架文件, 待标定/待配置)" % (dst, n))
    print("   下一步: python3 tools/instance_init.py --link %s" % dst)
    return 0


def cmd_link(dst, force=False):
    dst = os.path.realpath(dst)
    bad = False
    print("平台 → 实例包: %s" % dst)
    for rel, sub in LINKS:
        src = os.path.join(dst, sub)
        if not os.path.exists(src):
            print("   ❌ 实例包里没有 %s" % sub); bad = True; continue
        p = os.path.join(ROOT, rel)
        if os.path.lexists(p) and not os.path.islink(p):
            print("   ❌ %s 是真实文件 (未解耦), 先跑 tools/ 解耦脚本" % rel); bad = True; continue
        if os.path.islink(p):
            os.unlink(p)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(os.path.relpath(src, os.path.dirname(p)), p)
        print("   ✅ %s → %s" % (rel, os.path.relpath(src, ROOT)))
    if bad:
        return 1
    print("   完成; 跑 --check 复验, 再 build 工程库: python3 tools/engineering_db.py build")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 平台/实例 数据包装配")
    ap.add_argument("--check", action="store_true", help="体检 平台/实例 边界")
    ap.add_argument("--new", metavar="DIR", help="用出厂骨架新建实例包")
    ap.add_argument("--link", metavar="DIR", help="平台指向该实例包")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.new:
        return cmd_new(os.path.abspath(a.new), a.force)
    if a.link:
        return cmd_link(os.path.abspath(a.link), a.force)
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
