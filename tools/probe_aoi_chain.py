#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_aoi_chain.py — 质量检测链路实测（打印每个环节的真值，不美化）

环节: 取帧 → AOIQualityChecker.check → 话题信号 → 三路旁路 → 业务 dict
输出: 每环节 OK/GAP + 关键数值；落盘 zmax_data/ss_live/aoi_probe.json
"""
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/src")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/zmax"

out = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": {}}


def step(k, **kw):
    out["steps"][k] = kw
    print("[%s] %s" % ("OK " if kw.get("ok") else "GAP", k), end="")
    for kk, vv in kw.items():
        if kk == "ok":
            continue
        print("  %s=%s" % (kk, vv), end="")
    print()


# ① 取帧
from lerobot.middleware.nodes.impl import shared_runtime as SR  # noqa: E402

img = SR._YOLO_CACHE.get("img")
if img is None:
    try:
        al = SR._yolo_ensure_aligner(lambda m: print("   log:", m))
        _, _, img = SR._yolo_capture(lambda m: print("   log:", m), al)
    except Exception as e:
        step("frame", ok=False, err="%s: %s" % (type(e).__name__, e))
if img is not None:
    import numpy as np
    a = np.asarray(img)
    step("frame", ok=True, shape=tuple(a.shape), dtype=str(a.dtype),
         mean=round(float(a.mean()), 2), p99=round(float(np.percentile(a, 99)), 1))

# ② 判定内核
if img is not None:
    from lerobot.policies.yolo_3d.quality_check import AOIQualityChecker

    ck = AOIQualityChecker()
    t0 = time.time()
    res = ck.check(img)
    step("check", ok=True, ms=round((time.time() - t0) * 1000, 1),
         verdict=(res.get("quality") or {}).get("verdict"),
         why=(res.get("quality") or {}).get("why"),
         passed=res.get("pass"), scratch=res.get("scratch"), blob=res.get("blob"),
         focus=(round(res["focus"], 2) if isinstance(res.get("focus"), (int, float)) else res.get("focus")),
         items=len(res.get("items") or []))

    # ③ 话题信号
    from lerobot.policies.aoi.quality import quality_signals, quality_report

    sig = quality_signals(res)
    step("signals", ok=bool(sig), n=len(sig),
         keys=", ".join(sorted(k.split(".")[-1] for k in sig)))

    # ④ 完整巡检（含三路旁路）
    from lerobot.policies.aoi.quality import inspect_aoi

    t0 = time.time()
    rep = inspect_aoi(img, log=lambda m: None, cache=dict(SR._YOLO_CACHE),
                      publish=lambda s, l: None)
    step("inspect_aoi", ok=isinstance(rep, dict) and rep.get("kind") == "aoi",
         ms=round((time.time() - t0) * 1000, 1),
         verdict=rep.get("verdict"), passed=rep.get("pass"), sig_n=rep.get("sig_n"),
         remote=rep.get("remote"),
         gold_yolo=(rep.get("gold_yolo") or {}).get("present"),
         gold_remote=rep.get("gold_remote"))

# ⑤ 节点端口（走 n_inspection.compute 的真路径）
try:
    from lerobot.middleware.nodes import n_inspection as NI

    step("contract_pure", ok=(NI.PURE is True), PURE=NI.PURE, note="PURE=False ⇒ 只直通")
    ctx = {"in1": {"value": {"kind": "yolo", "n": 1}, "age_s": 0.0, "fresh": True},
           "log": lambda m: None}
    t0 = time.time()
    r = NI.compute(ctx)
    step("node_compute", ok=bool(r and (r.get("out1") is not None)),
         ms=round((time.time() - t0) * 1000, 1),
         status=NI.LAST_STATUS, out_keys=list(r or {}),
         out1_kind=(r.get("out1") or {}).get("kind") if isinstance(r.get("out1"), dict) else type(r.get("out1")).__name__)
except Exception as e:
    step("node_compute", ok=False, err="%s: %s" % (type(e).__name__, e))

p = os.path.join(ROOT, "zmax_data", "ss_live", "aoi_probe.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\n存:", os.path.relpath(p, ROOT))
