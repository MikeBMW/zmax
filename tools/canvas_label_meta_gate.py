#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_label_meta_gate.py — 把「元任务预测 → 动作调制器」这条线的标签写实 (老倪 2026-10-15)。

老倪: 「元任务预测的输出, 这是个具体信号, 应该也给到动作调制器, **直接约束动作调制的状态输出**」

原来标签只写「元任务预测值 → 动作调制」, 看不出"约束"是怎么落的。改成写实口径:
  元任务预测值 (top-k 得分/spread) → 动作调制器 · 状态输出约束 (只削幅不改方向; 闸门 ZMAX_META_GATE 默认关,
  开了在 sstrace.元任务门控 上看得到削幅)
只改这一条线的 label, 其余字段/连线一条不动。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
CANVAS = os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json"))
NEW = ("元任务预测值 (top-k 得分/spread) → 动作调制器 · 状态输出约束 "
       "(只削幅不改方向 · 闸门 ZMAX_META_GATE 默认关, 开了看 sstrace.元任务门控)")

d = json.load(open(CANVAS, encoding="utf-8"))
hit = [l for l in d["links"] if l.get("f") == "n_intent_direct" and l.get("t") == "sssched"]
assert hit, "没找到 n_intent_direct → sssched 这条线"
before = json.dumps(d["links"], sort_keys=True)
old = hit[0].get("label")
hit[0]["label"] = NEW
after = json.dumps(d["links"], sort_keys=True)
n_changed = sum(1 for a, b in zip(d["links"], json.loads(before)) if a != b)
assert n_changed == 1, "改动不止一条线: %d" % n_changed
print("线 %s: 旧标签「%s」" % (hit[0].get("id"), old))
print("          新标签「%s」" % NEW)
if "--apply" not in sys.argv:
    print("(干跑; 加 --apply 落盘)")
    sys.exit(0)
ts = time.strftime("%Y%m%d_%H%M%S")
bak = os.path.join(REPO, "flows", "_archive", "state_space_obs_before_meta_label_%s.json" % ts)
shutil.copy2(CANVAS, bak)
from lerobot.engineering import flows as F                    # noqa: E402
F.save_canvas(d)
d2 = json.load(open(CANVAS, encoding="utf-8"))
h2 = [l for l in d2["links"] if l.get("f") == "n_intent_direct" and l.get("t") == "sssched"][0]
print("已写盘 (备份 %s)\n回读: 节点 %d · 连线 %d · 标签匹配 %s"
      % (bak, len(d2["nodes"]), len(d2["links"]), h2.get("label") == NEW))
