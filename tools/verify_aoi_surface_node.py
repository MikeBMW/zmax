#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_aoi_surface_node.py — 「L2 光学质量检测节点 = 10083 表面旁路」交付自检

老倪 2026-10-19: 「将这个功能做到状态空间工程的L2光学质量检测节点, 10083服务, 可以在4060上旁路运行」
判据 (缺一条不算做到):
 ① 模块真源 LAYER='L2'  ② DB mw_node.layer='L2'  ③ 画布 JSON 写明 surface_bypass_10083
 ④ SurfaceOpticalQuality 可跑, 返回 dict 且 ok=True
 ⑤ 摆正后长边水平 (光模块水平放置)
 ⑥ no_stretch=True (零插值; 只有 resize 才算拉伸)
 ⑦ expand_px 有记录 (保留整块模块)
 ⑧ 信号字典含 必需键, 且值都是数字 (可发总线)
 ⑨ 节点 library._surface_bypass 可调用
 ⑩ 10083 不可达时优雅降级 (不抛异常)
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
PASS = FAIL = 0


def ck(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ %s%s" % (name, ("  — %s" % detail) if detail else ""))
    else:
        FAIL += 1
        print("  ❌ %s%s" % (name, ("  — %s" % detail) if detail else ""))


print("=" * 78)
print("L2 光学质量检测节点 · 10083 表面旁路 交付自检")
print("=" * 78)

# ① 模块真源
mod_path = os.path.join(ROOT, "src/lerobot/middleware/nodes/n_inspection.py")
src = open(mod_path, encoding="utf-8").read()
ck("① 模块真源 LAYER='L2'", bool(re.search(r"^LAYER = 'L2'", src, re.M)),
   "n_inspection.py")

# ② DB
db = os.path.join(ROOT, "data/database/zmax/zmax_engineering.db")
c = sqlite3.connect(db)
row = c.execute("select layer, name from mw_node where node_id='ssaoi'").fetchone()
ck("② DB mw_node.layer='L2'", row and row[0] == "L2", "实际=%r name=%r" % (row[0] if row else None, row[1] if row else None))

# ③ 画布 JSON
cj = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
d = json.load(open(cj, encoding="utf-8"))
node = next((n for n in d.get("nodes") or [] if n.get("id") == "ssaoi"), None)
sb = ((node or {}).get("params") or {}).get("surface_bypass_10083") or {}
ck("③ 画布 JSON 写明 surface_bypass_10083", bool(sb.get("enabled")), "url=%s" % sb.get("url"))

# ④~⑧ 真跑一次
from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality    # noqa: E402

sq = SurfaceOpticalQuality()
r = sq.run()
ck("④ SurfaceOpticalQuality.run() 返回 dict 且 ok", isinstance(r, dict) and bool(r.get("ok")),
   "verdict=%s ms=%s" % (r.get("verdict"), r.get("ms")))

mod = r.get("module") or {}
rect = r.get("rect") or {}
ck("⑤ 摆正后长边水平", bool(mod.get("long_edge_horizontal")),
   "shape=%s aspect=%s" % (r.get("judge_shape"), mod.get("aspect")))
ck("⑥ no_stretch=True (零插值)", rect.get("no_stretch") is True,
   "crop=%s out=%s" % (rect.get("crop_size"), rect.get("out_size")))
ck("⑦ expand_px 有记录 (保留整块)", isinstance(rect.get("expand_px"), list),
   "expand_px=%s" % (rect.get("expand_px"),))

sig = sq.signals(r)
need = ["表面光学.可用", "表面光学.取像体检", "表面光学.模块均值", "表面光学.水平", "表面光学.曝光us"]
missing = [k for k in need if k not in sig]
ck("⑧ 信号字典含必需键且全为数字", not missing and all(isinstance(v, (int, float)) for v in sig.values()),
   "缺=%s 共%d键" % (missing, len(sig)))

# ⑨ 节点 library._surface_bypass
try:
    from lerobot.engineering.nodes import library as L
    r2 = L._surface_bypass(log=None)
    ck("⑨ library._surface_bypass 可调用", isinstance(r2, dict) and bool(r2.get("ok")),
       "ok=%s" % (r2 or {}).get("ok"))
except Exception as e:                                               # noqa: BLE001
    ck("⑨ library._surface_bypass 可调用", False, "%s: %s" % (type(e).__name__, e))

# ⑩ 不可达优雅降级
try:
    bad = SurfaceOpticalQuality(url="http://127.0.0.1:59999", timeout=1.5)
    rb = bad.run(grab=False)
    ck("⑩ 10083 不可达时优雅降级", isinstance(rb, dict) and rb.get("ok") is False,
       "why=%s" % str(rb.get("why"))[:44])
except Exception as e:                                               # noqa: BLE001
    ck("⑩ 10083 不可达时优雅降级", False, "抛了 %s: %s" % (type(e).__name__, e))

print("-" * 78)
print("结果: %d/%d PASS" % (PASS, PASS + FAIL))
sys.exit(0 if FAIL == 0 else 1)
