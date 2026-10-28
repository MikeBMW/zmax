#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_ss_stage.py — 订阅 zmax/ss_stage, 证明「八阶段状态机」真的在 DDS 话题上跑

老倪 2026-10-15: 「八个状态, 是哪个 topic 发出来的? 你要放到信号分析的窗口里显示」
用法: <dds-venv>/bin/python /home/ubuntu/zmax/tools/probe_ss_stage.py [秒数]
"""
from __future__ import annotations

import os
import sys
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "dds"))

from zmax_node import Node                                                      # noqa: E402

TOPIC = "ss_stage"
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0

n = Node("probe_ss_stage", domain=0)
n.sub(TOPIC)
print("订阅 %s (%.0fs) …" % (TOPIC, secs), flush=True)
got = []
t0 = time.time()
while time.time() - t0 < secs:
    s = n.take(TOPIC, 0.2)
    if s:
        got.extend(s)
if not got:
    print("❌ 0 条 — 话题没有数据 (守护没发? 源不新鲜?)")
    raise SystemExit(1)
last = got[-1]
print("✅ 收到 %d 条; 最后一条:" % len(got))
print("    阶段名 name   = %s" % last.name)
print("    十三段 idx    = %s" % last.idx)
print("    八阶段 idx8   = %s   ← 这就是「八个状态」的序号" % last.idx8)
print("    阶段限速 v_cap= %s m/s" % last.v_cap)
print("    完成 done     = %s" % last.done)
print("    源帧龄 age_s  = %.2fs" % last.age_s)
print("    唯一依据 source   = %s" % last.source)
print("    note          = %s" % last.note)
seq = [g.idx8 for g in got]
print("    idx8 序列(前 30) = %s" % seq[:30])
raise SystemExit(0)
