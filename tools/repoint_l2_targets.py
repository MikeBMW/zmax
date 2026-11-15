#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 迁移后把「右键落点」与 _EXTERNAL_LOC 指到 state_space 新位置 (老倪 2026-11-15)

- 画布: 这批节点 params.source/source_symbol/source_line → state_space/*
- library._EXTERNAL_LOC: 仍指老路径的条目 → 新的 state_space 文件 (行号按符号重算)
用法: python3 tools/repoint_l2_targets.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil

ROOT = "/home/ubuntu/zmax"
CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
LIB = os.path.join(ROOT, "src/lerobot/engineering/nodes/library.py")

NEW = {
    "src/lerobot/engineering/nodes/exec_dispatch_impl.py": "src/lerobot/policies/left_right/state_space/exec_dispatch.py",
    "src/lerobot/perception/yolo.py": "src/lerobot/policies/left_right/state_space/perception_yolo.py",
    "src/lerobot/policies/yolo_3d/yolo_state_aligner.py": "src/lerobot/policies/left_right/state_space/perception_3d.py",
    "src/lerobot/policies/yolo_3d/gen_tactile.py": "src/lerobot/policies/left_right/state_space/perception_tactile.py",
    "src/lerobot/policies/aoi/quality.py": "src/lerobot/policies/left_right/state_space/aoi_quality.py",
    "tools/sam3_seg.py": "src/lerobot/policies/left_right/state_space/perception_seg.py",
    "src/lerobot/skills/muscle_memory.py": "src/lerobot/policies/left_right/state_space/muscle_memory.py",
    "src/lerobot/manifold/manifold_engine.py": None,   # 测地线本体已单独迁 (geodesic_nav.py)
}

NODE_TO_FILE = {
    "n_exec": "exec_dispatch.py",
    "ssyolo": "perception_3d.py",
    "ss2d3d": "perception_3d.py",
    "sstactile": "perception_tactile.py",
    "ssaoi": "aoi_quality.py",
    "ss_seg": "perception_seg.py",
    "ssbg0": "perception_yolo.py",
}
NODE_SYM = {
    "n_exec": "def run",
    "ssyolo": "class YoloStateAligner",
    "ss2d3d": "def detect_3d",
    "sstactile": "def main",
    "ssaoi": "def quality_signals",
    "ss_seg": "def main",
    "ssbg0": "class YoloPerception",
}


def find_def(path, want):
    want = re.sub(r"^(def|class|async def)\s+", "", want.split("(")[0]).strip()
    try:
        for i, ln in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
            t = ln.lstrip()
            if t.startswith(("def ", "class ", "async def ")):
                nm = re.sub(r"^(class|async def|def)\s+", "", t.split("(")[0]).strip()
                if nm == want:
                    return i
    except Exception:                                                        # noqa: BLE001
        pass
    return None


def first_def(path):
    try:
        for i, ln in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
            t = ln.lstrip()
            if t.startswith(("def ", "class ")) and not t.startswith("def _"):
                nm = t.split("(")[0].strip()
                return i, ("def " + nm[4:]) if nm.startswith("def ") else ("class " + nm[6:])
    except Exception:                                                        # noqa: BLE001
        pass
    return 1, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    SS = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space")

    d = json.load(open(CANVAS, encoding="utf-8"))
    chg = []
    for n in d.get("nodes") or []:
        nid = n.get("id") or ""
        if nid not in NODE_TO_FILE:
            continue
        pr = n.setdefault("params", {})
        p = os.path.join(SS, NODE_TO_FILE[nid])
        if not os.path.isfile(p):
            continue
        sym = NODE_SYM.get(nid)
        ln = find_def(p, sym) if sym else None
        if not ln:
            ln, sym2 = first_def(p)
            sym = sym or sym2
        new = (os.path.relpath(p, ROOT), sym, int(ln))
        old = (pr.get("source"), pr.get("source_symbol"), pr.get("source_line"))
        pr["source"], pr["source_symbol"], pr["source_line"] = new
        chg.append((nid, old, new))

    print("画布改 %d 个节点:" % len(chg))
    for nid, old, new in chg:
        print("  %-11s %s → %s:%s %s" % (nid, (old[0] or "-").split("/")[-1], new[0].split("state_space/")[-1], new[2], new[1]))

    # _EXTERNAL_LOC 里指老路径的, 改写
    txt = open(LIB, encoding="utf-8").read()
    n_rep = 0
    for old_p, new_p in NEW.items():
        if not new_p:
            continue
        for pat in (old_p, os.path.join(ROOT, old_p)):
            if pat in txt:
                txt = txt.replace(pat, new_p)
                n_rep += 1
    print("library._EXTERNAL_LOC 路径改写 %d 处" % n_rep)

    if a.apply:
        shutil.copy2(CANVAS, CANVAS + ".bak_repoint")
        json.dump(d, open(CANVAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if n_rep:
            shutil.copy2(LIB, LIB + ".bak_repoint")
            open(LIB, "w", encoding="utf-8").write(txt)
        print("已回写 (备份 .bak_repoint)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
