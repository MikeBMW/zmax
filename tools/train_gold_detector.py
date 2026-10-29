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
best = os.path.join("outputs/yolo_gold", NAME, "weights", "best.pt")
print("\n=== 训练完成 ===")
print("best:", os.path.abspath(best), "存在:", os.path.exists(best))

# 训练后真推理验证（不是只看 mAP，要看真图检出）
if os.path.exists(best):
    v = YOLO(best)
    import glob
    vals = sorted(glob.glob("data/datasets/yolo_gold/images/val/*.png"))[:10]
    n_hit, confs = 0, []
    for p in vals:
        rr = v.predict(p, imgsz=640, conf=0.25, verbose=False)[0]
        if len(rr.boxes):
            n_hit += 1
            confs.append(float(rr.boxes.conf.max()))
    print(f"\n真推理验证: {n_hit}/{len(vals)} 张有检出")
    if confs:
        print(f"  置信度 中位 {sorted(confs)[len(confs)//2]:.3f} "
              f"范围 {min(confs):.3f}~{max(confs):.3f}")
