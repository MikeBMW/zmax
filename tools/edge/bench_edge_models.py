#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intel 侧逐模型算力占用实测: 每份 IR 在各设备上独占跑, 报 单帧 ms / 独占 fps / 30fps 节拍占空 / 进程内存。

口径说明:
  · 单帧 ms  = 该模型独占设备时一次 infer 的墙钟均值 (warmup 3 + iters 20, 取 p50/p95)
  · 节拍占空 = ms × 30 / 1000 —— 若产线按 30fps 喂帧, 这台设备被该模型吃掉的时间比例
  · 内存     = 编译+跑完后的进程 RSS 增量 (权重+运行时 buffer), 真实"显存"是核显共享 RAM
用法: python bench_models.py --device NPU --iters 20 [--xml ir/xxx.xml]
"""
import argparse
import json
import os
import statistics
import time

import numpy as np
import openvino as ov

D = "/home/intel/edge_models/ir"


def rss_mb():
    with open("/proc/self/status") as f:
        for ln in f:
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) / 1024.0
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="NPU")
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--xml", default="")
    a = ap.parse_args()

    core = ov.Core()
    names = ([os.path.basename(a.xml)] if a.xml else
             [f for f in sorted(os.listdir(D)) if f.endswith(".xml")])
    r0 = rss_mb()
    rows = []
    for fn in names:
        fp = os.path.join(D, fn)
        t0 = time.time()
        try:
            m = core.compile_model(fp, a.device, {"PERFORMANCE_HINT": "LATENCY"})
        except Exception as e:                                              # noqa: BLE001
            rows.append({"model": fn[:-4], "err": "%s: %s" % (type(e).__name__, str(e)[:120])})
            continue
        cm = time.time() - t0
        req = m.create_infer_request()
        ins = {}
        for i in m.inputs:
            p = i.get_partial_shape()
            shp = [int(d.get_length()) if d.is_static else 1 for d in p]
            ins[i] = np.zeros(shp, dtype=np.float32)
        for _ in range(3):
            req.infer(ins)
        ts = []
        for _ in range(a.iters):
            t = time.perf_counter()
            req.infer(ins)
            ts.append((time.perf_counter() - t) * 1000.0)
        p50 = statistics.median(ts)
        rows.append({"model": fn[:-4], "compile_s": round(cm, 1), "p50_ms": round(p50, 2),
                     "p95_ms": round(sorted(ts)[int(len(ts) * 0.95) - 1], 2),
                     "solo_fps": round(1000.0 / p50, 1), "duty_30fps_pct": round(p50 * 30 / 10, 1),
                     "rss_delta_mb": round(rss_mb() - r0, 1)})
        del m, req
    out = {"device": a.device, "iters": a.iters, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "rows": rows}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
