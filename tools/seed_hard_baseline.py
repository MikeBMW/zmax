#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seed_hard_baseline.py — 给 ledger["best"] 补上 hard(难留出集) 基线分数

为什么: 晋级主判据从 hc.map50(已在 0.995 封顶) 换成 hard.map50_95。
换了尺子就得先量出「现任冠军 best.pt 在这把新尺子上多少分」, 否则第一次晋级是无条件晋级。
CPU 评测: 现在常驻服务已占 7.5G 显存, 不许再抢显存 (同刻仅一模型进程)。
"""
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
AR = os.path.join(ROOT, "zmax_data/ar_evolve")
LEDGER = os.path.join(AR, "ledger.json")
CUR = os.path.join(AR, "best.pt")
HARD = os.path.join(AR, "holdout_hard/data.yaml")

sys.path.insert(0, os.path.join(ROOT, "src"))
from ultralytics import YOLO  # noqa: E402

led = json.load(open(LEDGER, encoding="utf-8"))
best = led.get("best") or {}
print("现任 best:", best.get("gen"), best.get("ts"), "weights_path=", best.get("weights"))

# 1) 从历史台账把 gen_127 那代的 hc/legacy 50-95 捞出来 (当时就有记录)
gen_rec = next((r for r in led["generations"] if r.get("gen") == best.get("gen")), None)
if gen_rec:
    ev = (gen_rec.get("train_eval") or {}).get("eval") or {}
    hc, lg = ev.get("hc") or {}, ev.get("legacy") or {}
    print("gen_%s 历史: hc50-95=%s legacy50-95=%s" % (best.get("gen"), hc.get("map50_95"), lg.get("map50_95")))
    best["hc_map50_95"] = hc.get("map50_95")
    best["legacy_map50_95"] = lg.get("map50_95")

# 2) 量现任权重在 hard 尺子上的分 (CPU, 不抢显存)
m = YOLO(CUR)
r = m.val(data=HARD, imgsz=640, batch=8, device="cpu", verbose=False, plots=False,
          project=os.path.join(AR, "baseline_hard"), name="gen_%s" % best.get("gen"), exist_ok=True)
best["hard_map50"] = round(float(r.box.map50), 4)
best["hard_map50_95"] = round(float(r.box.map), 4)
best["hard_precision"] = round(float(r.box.mp), 4)
best["hard_recall"] = round(float(r.box.mr), 4)
best["hard_baseline_ts"] = "2026-11-12"
led["best"] = best
json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写入 ledger.best:", json.dumps({k: best[k] for k in
      ("gen", "hard_map50", "hard_map50_95", "hard_precision", "hard_recall",
       "hc_map50", "hc_map50_95", "legacy_map50", "legacy_map50_95") if k in best},
      ensure_ascii=False))
