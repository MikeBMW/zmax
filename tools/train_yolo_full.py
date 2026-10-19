#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_yolo_full.py — 插拔场景 hand/peg/hole 三类全量训练 (18,900 train / 2,100 val)

磁盘纪律 (老倪: 不过红线):
  · save_period=-1  → 不存中间轮 (只留 best.pt + last.pt)
  · 整个 run 目录预计 <310MB
  · 不写 cache (cache=False), 不落大图

基座选择: 现役 models/yolo_peg_live.pt 只有 2 类 {peg, OPT_Gold}, 与本数据集 3 类
  {hand, peg, hole} 类别**不匹配**, 不能当基座续训 ⇒ 用 COCO 的 yolov8n 重训。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = "/home/ubuntu/zmax"
DATA = os.path.join(ROOT, "zmax_data/full_train/peg_insert/data.yaml")
OUTP = os.path.join(ROOT, "runs/peg_full")
BASE = os.path.join(ROOT, "models/yolov8n.pt")


def main():
    from ultralytics import YOLO
    epochs = int(os.environ.get("ZMAX_YOLO_EPOCHS", "30"))
    imgsz = int(os.environ.get("ZMAX_YOLO_IMGSZ", "640"))
    batch = int(os.environ.get("ZMAX_YOLO_BATCH", "16"))
    name = os.environ.get("ZMAX_YOLO_NAME", "r1")

    print("=" * 66)
    print("插拔场景 YOLO 全量训练 — hand / peg / hole (3 类)")
    print("=" * 66)
    print("数据   : %s" % DATA)
    print("基座   : %s (COCO, 类别不匹配需重训)" % BASE)
    print("参数   : epochs=%d imgsz=%d batch=%d" % (epochs, imgsz, batch))
    print("产物   : %s/%s (save_period=-1 不存中间轮)" % (OUTP, name))
    t0 = time.time()

    model = YOLO(BASE)
    res = model.train(
        data=DATA, epochs=epochs, imgsz=imgsz, batch=batch, device=0,
        project=OUTP, name=name, exist_ok=True,
        save_period=-1,                 # 不存中间轮
        plots=True, verbose=True,
        workers=8, cache=False,
        pretrained=True, optimizer="auto",
        seed=0, deterministic=True,
    )

    # 训练完在验证集上评一次
    print("\n" + "=" * 66)
    print("验证集评估 (2,100 张 holdout + drmix-val)")
    print("=" * 66)
    m = model.val(data=DATA, split="val", imgsz=imgsz, batch=batch, device=0, verbose=True)
    box = getattr(m, "box", None)
    per_class = {}
    names = model.names
    try:
        for i, n in names.items():
            per_class[n] = {
                "mAP50": round(float(box.ap50[i]), 4),
                "mAP50-95": round(float(box.ap[i]), 4),
                "precision": round(float(box.p[i]), 4),
                "recall": round(float(box.r[i]), 4),
            }
    except Exception as e:                                        # noqa: BLE001
        per_class = {"err": str(e)}

    summary = {
        "ts": time.strftime("%Y%m%d_%H%M%S"), "scenario": "peg_insert (hand/peg/hole)",
        "epochs": epochs, "imgsz": imgsz, "batch": batch,
        "base": BASE, "data": DATA,
        "elapsed_s": round(time.time() - t0, 1),
        "overall": {
            "mAP50": round(float(box.map50), 4) if box is not None else None,
            "mAP50-95": round(float(box.map), 4) if box is not None else None,
            "precision": round(float(box.mp), 4) if box is not None else None,
            "recall": round(float(box.mr), 4) if box is not None else None,
        },
        "per_class": per_class,
        "weights_best": os.path.join(OUTP, name, "weights/best.pt"),
    }
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    p = os.path.join(ROOT, "reports", "yolo_full_%s.json" % summary["ts"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\n整体: mAP50=%.4f mAP50-95=%.4f P=%.4f R=%.4f"
          % (summary["overall"]["mAP50"] or 0, summary["overall"]["mAP50-95"] or 0,
             summary["overall"]["precision"] or 0, summary["overall"]["recall"] or 0))
    for n, v in per_class.items():
        if isinstance(v, dict) and "mAP50" in v:
            print("  %-8s mAP50=%.4f mAP50-95=%.4f P=%.4f R=%.4f"
                  % (n, v["mAP50"], v["mAP50-95"], v["precision"], v["recall"]))
    print("\n报告 → %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
