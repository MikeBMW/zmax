#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📦 把 L2 节点算法搬进 state_space/ (老倪 2026-11-15「所有 L2 节点的算法都要迁到这个路径下」)

做法 (与 motion_plan / plan_guide 同款, 保证老 import 不断):
  ① 复制本体到 src/lerobot/policies/left_right/state_space/<新名>.py
  ② 原路径改成**相对软链**指向新文件 (打开/import/编辑都是同一份)
  ③ 逐个 import 自检: 老路径能导入、新路径能导入、关键符号在

用法: python3 tools/migrate_l2_algos.py [--apply]
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil

ROOT = "/home/ubuntu/zmax"
SS = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space")

# (原文件, state_space 新文件名, 自检符号, 节点 id 说明)
MOVES = [
    ("src/lerobot/engineering/nodes/exec_dispatch_impl.py", "exec_dispatch.py", "run", "n_exec 执行收口"),
    ("src/lerobot/perception/yolo.py", "perception_yolo.py", None, "ssbg0 分段感知"),
    ("src/lerobot/policies/yolo_3d/yolo_state_aligner.py", "perception_3d.py", "YoloStateAligner", "ssyolo/ss2d3d"),
    ("src/lerobot/policies/yolo_3d/gen_tactile.py", "perception_tactile.py", None, "sstactile 触觉"),
    ("src/lerobot/policies/aoi/quality.py", "aoi_quality.py", "quality_signals", "ssaoi 光学质量"),
    ("tools/sam3_seg.py", "perception_seg.py", None, "ss_seg 分割"),
    ("src/lerobot/skills/muscle_memory.py", "muscle_memory.py", None, "L2 肌肉记忆"),
]


def rel_link(target_abs, link_dir):
    return os.path.relpath(target_abs, link_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    plan = []
    for src, newname, sym, why in MOVES:
        sp = os.path.join(ROOT, src)
        dst = os.path.join(SS, newname)
        if os.path.islink(sp):
            plan.append((src, newname, "已是软链: -> %s" % os.readlink(sp), why, "skip"))
            continue
        if not os.path.isfile(sp):
            plan.append((src, newname, "源文件不存在", why, "skip"))
            continue
        plan.append((src, newname, "%.0fKB / %d 行" % (os.path.getsize(sp) / 1024,
                                                       sum(1 for _ in open(sp, encoding="utf-8", errors="ignore"))), why, "move"))

    print("迁移计划 %d 项:" % len(plan))
    for src, newname, info, why, act in plan:
        print("  %-6s %-56s → state_space/%-24s %-22s %s" % (act.upper(), src, newname, why, info))
    if not a.apply:
        return 0

    done = []
    for src, newname, _info, _why, act in plan:
        if act != "move":
            continue
        sp = os.path.join(ROOT, src)
        dst = os.path.join(SS, newname)
        if os.path.isfile(dst):                      # 目标已存在 ⇒ 先比对, 相同才覆盖
            same = open(sp, "rb").read() == open(dst, "rb").read()
            if not same:
                print("  ⚠ 目标已存在且内容不同, 跳过: %s" % newname)
                continue
            os.remove(sp)
        else:
            shutil.copy2(sp, dst)
            os.remove(sp)
        link = rel_link(dst, os.path.dirname(sp))
        os.symlink(link, sp)
        done.append((src, newname))
        print("  ✅ %-56s -> state_space/%s  (软链 %s)" % (src, newname, link))

    # ── 自检: 两侧都能导入 ───────────────────────────────────────────────
    import sys
    sys.path.insert(0, os.path.join(ROOT, "src"))
    print("\n导入自检:")
    for src, newname in done:
        old_mod = src.replace("src/", "").replace("/", ".").replace(".py", "")
        new_mod = "lerobot.policies.left_right.state_space." + newname[:-3]
        for m in (old_mod, new_mod):
            try:
                mod = importlib.import_module(m)
                print("  ✅ %-62s %s" % (m, "ok" if mod else "?"))
            except Exception as e:                                            # noqa: BLE001
                print("  ❌ %-62s %s: %s" % (m, type(e).__name__, str(e)[:70]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
