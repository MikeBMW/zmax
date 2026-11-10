#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_aoi_async.py — 验证 AOI 节点改成异步后: 10Hz 零阻塞 + 真结果照出

判据 (全部实测打印):
  1) 首次调用耗时应 ~0ms (worker 在后台跑), 返回 warming 而非造数
  2) 模拟 10Hz 连打 100 拍, 总耗时应 << 10s (同步实现会是 250s+)
  3) 等 worker 出结果后, 快照应带真 verdict / 8 个话题信号 / age_s
  4) 端口 out1/out2 必须有值且同源
"""
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/src")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ZMAX_AOI_MIN_INTERVAL_S", "2.0")
ROOT = "/home/ubuntu/zmax"

from lerobot.middleware.nodes.impl import ss_aoi as A  # noqa: E402

res = {}

# ① 首次调用 (非阻塞)
t0 = time.time()
o1 = A.node_ss_aoi({"log": lambda m: None})
ms1 = (time.time() - t0) * 1000
res["first_call_ms"] = round(ms1, 2)
res["first_verdict"] = o1["out1"].get("verdict")
res["first_pass"] = o1["out1"].get("pass")
print("[1] 首次调用 %.2fms  verdict=%s pass=%s (期望 warming/None, 且 <100ms)"
      % (ms1, o1["out1"].get("verdict"), o1["out1"].get("pass")))

# ② 10Hz 连打 100 拍
t0 = time.time()
for i in range(100):
    A.node_ss_aoi({"log": lambda m: None})
    time.sleep(0.1)
ms100 = (time.time() - t0) * 1000
res["burst_100_ms"] = round(ms100, 1)
print("[2] 10Hz 连打 100 拍 (含睡 10s): 墙钟 %.0fms  ⇒ 节点自身开销 %.1fms/拍"
      % (ms100, (ms100 - 10000) / 100))

# ③ 等 worker 出结果
t0 = time.time()
snap = None
while time.time() - t0 < 30:
    o = A.node_ss_aoi({"log": lambda m: None})
    if o["out1"].get("pass") is not None or o["out1"].get("verdict") not in ("warming",):
        snap = o
        break
    time.sleep(0.5)
if snap is None:
    snap = A.node_ss_aoi({"log": lambda m: None})
res["snapshot"] = {k: snap["out1"].get(k) for k in
                   ("kind", "verdict", "pass", "sig_n", "seq", "age_s", "stale", "scratch", "blob", "focus")}
print("[3] 快照: verdict=%s pass=%s sig_n=%s seq=%s age_s=%s stale=%s"
      % (res["snapshot"]["verdict"], res["snapshot"]["pass"], res["snapshot"]["sig_n"],
         res["snapshot"]["seq"], res["snapshot"]["age_s"], res["snapshot"]["stale"]))
print("    量化: scratch=%s blob=%s focus=%s"
      % (res["snapshot"]["scratch"], res["snapshot"]["blob"], res["snapshot"]["focus"]))

# ④ 端口同源
res["port_same"] = (snap["out1"] == snap["out2"])
res["port_keys"] = sorted(snap.keys())
print("[4] out1==out2: %s  顶层键: %s" % (res["port_same"], res["port_keys"]))

res["worker"] = A.aoi_worker_stats()
print("[5] worker: %s" % res["worker"])

p = os.path.join(ROOT, "zmax_data", "ss_live", "aoi_async_probe.json")
json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\n存:", os.path.relpath(p, ROOT))
