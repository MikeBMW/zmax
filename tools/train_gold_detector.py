#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金手指检测模型训练（自蒸馏微调）。

基座: models/yolo_ar_peg.pt（现役，已能检出 gold_module）
数据: data/datasets/yolo_gold（120 张自动打标，96/24）
"""
import os
import sys

sys.path.insert(0, "src")
from ultralytics import YOLO  # noqa: E402

DATA = "data/datasets/yolo_gold/data.yaml"
BASE = "models/yolo_ar_peg.pt"
NAME = os.environ.get("GOLD_RUN", "gold_v1")
EPOCHS = int(os.environ.get("GOLD_EPOCHS", "40"))
BATCH = int(os.environ.get("GOLD_BATCH", "4"))
IMGSZ = int(os.environ.get("GOLD_IMGSZ", "512"))
# GPU 7.6G 被引擎执行器(2.3G)+两个模型进程(2.3G)+渲染站占满 ⇒ 训练只能用余量,
# 保持小 batch + 小尺寸, 不与在线服务抢显存。
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

print(f"基座={BASE} 数据={DATA} epochs={EPOCHS} batch={BATCH} imgsz={IMGSZ} name={NAME}")
m = YOLO(BASE)
r = m.train(
    data=DATA,
    epochs=EPOCHS,
    imgsz=IMGSZ,
    batch=BATCH,
    device=0,
    workers=0,        # /dev/shm 被 Chrome 占满(16G/16G) ⇒ 不能起 worker 进程, 主进程加载数据
    project="outputs/yolo_gold",
    name=NAME,
    exist_ok=True,
    pretrained=True,
    optimizer="AdamW",
    lr0=0.001,
    patience=20,
    verbose=True,
    plots=False,
)
# ultralytics 的 runs 目录被 settings 指到 external/...，不能硬编码 outputs/ 路径
best = os.path.join(str(getattr(r, "save_dir", "") or ""), "weights", "best.pt")
print("\n=== 训练完成 ===")
print("best:", best, "存在:", os.path.exists(best))

# 训练后真推理验证: **必须同时测分布内和分布外**
# 只测 val 会被数据泄漏骗 (train/val 同场景微扰时 mAP 能到 0.99, 上线直接 0 检出)
if os.path.exists(best):
    import glob
    v = YOLO(best)

    def _probe(tag, pattern, n=12):
        fs = sorted(glob.glob(pattern))[:n]
        if not fs:
            print(f"  {tag}: 无图")
            return None
        hit, confs = 0, []
        for p in fs:
            rr = v.predict(p, imgsz=IMGSZ, conf=0.25, verbose=False)[0]
            if len(rr.boxes):
                hit += 1
                confs.append(float(rr.boxes.conf.max()))
        med = sorted(confs)[len(confs) // 2] if confs else 0.0
        print(f"  {tag}: {hit}/{len(fs)} 检出 · 置信中位 {med:.3f}")
        return hit / len(fs)

    print("\n=== 真推理验证 (分布内 val 高不代表可用) ===")
    _probe("分布内 val      ", "data/datasets/yolo_gold/images/val/*.png")
    _probe("分布外 aoi_v4   ", "zmax_data/aoi_v4/snapshots/*/*.png")
    _probe("分布外 judge    ", "zmax_data/gold_collect_20261020/judge/*.png")
    print("  ⚠ 分布外检出率 <50% ⇒ 视为不可上线, 不得进默认档")
