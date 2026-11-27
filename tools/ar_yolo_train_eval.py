#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_yolo_train_eval.py — AR 检测器「训练 + 同源评测」单进程worker (一行 JSON 出证据)

为什么单独一个 worker
    训练与评测必须在**同一个权重、同一份权重文件**上完成, 且不能与常驻回路的显存打架;
    独立进程跑完即退出 ⇒ 显存干净还给引擎, 编排器只读 JSON。

口径 (不许含糊)
    · train 用本代自造数据 (ar_mujoco_clutter 渲染, 标签=金色像素主连通域)
    · eval 只在**固定留出集**上算, 每代同一份 ⇒ 代际可比
    · 同时报两个口径: hc=带干扰件留出集 (有真实提升空间) / legacy=原干净留出集 (不许回退)

用法
    python tools/ar_yolo_train_eval.py --base models/yolo_ar_peg.pt \
        --data <gen>/train.yaml --epochs 15 --project <gen> --out <gen>/train_eval.json \
        --eval hc=zmax_data/ar_evolve/holdout_clutter/data.yaml \
        --eval legacy=zmax_data/ar_mujoco/holdout/data.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

DEVICE = os.environ.get("ZMAX_TRAIN_DEVICE", "0")   # 0=cuda:0(默认) / cpu / xpu:0(Intel Arc)

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--project", required=True)
    ap.add_argument("--name", default="train")
    ap.add_argument("--out", required=True)
    ap.add_argument("--eval", action="append", default=[], help="name=yaml (可多次)")
    # 🔴 2026-11-20 老倪: 机器反应慢 → DataLoader workers 8(ultralytics 默认再乘) 各吃 1.35G,
    #   训练链合计 18.8G/15 进程把 30G 机器压进 swap。默认降到 2 (内存约 -8G, 训练慢一些)。
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    root = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
    sys.path.insert(0, os.path.join(root, "src"))
    from ultralytics import YOLO  # noqa: E402

    t0 = time.time()
    rep = {"base": a.base, "data": a.data, "epochs": a.epochs, "ok": False}
    try:
        m = YOLO(a.base)
        # 🔴 2026-11-24: 978 代零晋级, 每次都 hard50-95 0.9478 → 0.75~0.78 (mAP50 仍 0.99)。
        # 根因不是尺子(现任 best.pt 今日复测 hard 0.9478 / hc 0.9498 / legacy 0.9469, 逐位可复现),
        # 是**微调配方在毁定位**: 从收敛权重出发 lr0=0.01 + mosaic0.6/scale0.5/degrees6, 每代仅 ~140 张有标图,
        # 30 epoch 足以把框回归带偏 ⇒ 分类(mAP50)不动、IoU0.5→0.95 全崩。
        # 微调档: 小 lr + 轻几何增强; 想复现旧行为把环境变量改回去即可。
        import os as _os
        _lr0 = float(_os.environ.get("ZMAX_FT_LR0", "0.002"))
        _mosaic = float(_os.environ.get("ZMAX_FT_MOSAIC", "0.2"))
        _scale = float(_os.environ.get("ZMAX_FT_SCALE", "0.25"))
        _deg = float(_os.environ.get("ZMAX_FT_DEGREES", "2.0"))
        r = m.train(data=a.data, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=DEVICE,
                    workers=a.workers, project=a.project, name=a.name, exist_ok=True,
                    seed=a.seed, deterministic=True, verbose=False, plots=False,
                    cache=False, val=False,   # val 统一由下面的固定留出集给, 不用训练内 val
                    lr0=_lr0,
                    hsv_h=0.015, hsv_s=0.6, hsv_v=0.45, degrees=_deg, translate=0.10,
                    scale=_scale, mosaic=_mosaic, mixup=0.0, fliplr=0.5)
        rep["finetune"] = {"lr0": _lr0, "mosaic": _mosaic, "scale": _scale, "degrees": _deg}
        best = os.path.join(a.project, a.name, "weights", "best.pt")
        last = os.path.join(a.project, a.name, "weights", "last.pt")
        rep["weights"] = best if os.path.exists(best) else last
        rep["train_sec"] = round(time.time() - t0, 1)
        # 训练末轮损失 (如实记录, 不看 loss 只看 val)
        try:
            import csv
            rows = list(csv.DictReader(open(os.path.join(a.project, a.name, "results.csv"))))
            if rows:
                rep["train_last_row"] = {k.strip(): v for k, v in rows[-1].items()}
        except Exception:                                                   # noqa: BLE001
            pass
        rep["eval"] = {}
        y = YOLO(rep["weights"])
        for spec in a.eval:
            nm, yaml = spec.split("=", 1)
            e = y.val(data=yaml, imgsz=a.imgsz, batch=a.batch, device=DEVICE, verbose=False,
                      plots=False, project=a.project, name="val_" + nm, exist_ok=True)
            rep["eval"][nm] = {"yaml": yaml, "map50": round(float(e.box.map50), 4),
                               "map50_95": round(float(e.box.map), 4),
                               "precision": round(float(e.box.mp), 4),
                               "recall": round(float(e.box.mr), 4)}
        rep["ok"] = bool(rep.get("weights")) and all("map50" in v for v in rep["eval"].values())
        rep["sec_total"] = round(time.time() - t0, 1)
    except Exception as exc:                                                # noqa: BLE001
        rep["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:400])
    json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: rep.get(k) for k in ("ok", "weights", "eval", "error")},
                     ensure_ascii=False)[:800])
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
