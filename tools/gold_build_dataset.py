#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 gold_collect 自动标注结果转成 YOLO 数据集（80/20 分层）。

输入: zmax_data/aoi_v4/gold_auto/detections.json  (由 gold_dataset_audit.py 产出)
输出: data/datasets/yolo_gold/{images,labels}/{train,val} + data.yaml

注意: 标注来自现役模型自动打标 (检出 120/120), 属"自蒸馏"——
      模型只会学它自己已经会的东西, 泛化提升有限。这一点写进 data.yaml 的注释里。
"""
import glob
import json
import os
import random
import shutil

SRC = "zmax_data/gold_collect_20261020/origin"
DST = "data/datasets/yolo_gold"
DET = "zmax_data/aoi_v4/gold_auto/detections.json"

det = {d["file"]: d for d in json.load(open(DET, encoding="utf-8"))}
imgs = sorted(glob.glob(os.path.join(SRC, "*.png")))
random.seed(0)
random.shuffle(imgs)
cut = int(len(imgs) * 0.8)

for sub in ("images/train", "images/val", "labels/train", "labels/val"):
    os.makedirs(os.path.join(DST, sub), exist_ok=True)

n_t, n_v, n_lbl = 0, 0, 0
for i, p in enumerate(imgs):
    split = "train" if i < cut else "val"
    name = os.path.basename(p)
    shutil.copy2(p, os.path.join(DST, "images", split, name))
    d = det.get(name)
    lab = os.path.join(DST, "labels", split, name.rsplit(".", 1)[0] + ".txt")
    if not d:
        open(lab, "w").close()
        continue
    # 需要图片尺寸做归一化
    from PIL import Image
    W, H = Image.open(p).size
    x1, y1, x2, y2 = d["xyxy"]
    cx, cy = (x1 + x2) / 2 / W, (y1 + y2) / 2 / H
    bw, bh = (x2 - x1) / W, (y2 - y1) / H
    with open(lab, "w") as f:
        f.write(f"{d['cls']} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
    n_lbl += 1
    if split == "train":
        n_t += 1
    else:
        n_v += 1

yaml = f"""# 金手指(gold_module) 自蒸馏数据集
# 来源: zmax_data/gold_collect_20261020 · 标注=现役 yolo_ar_peg.pt 自动打标 (检出 120/120)
# 局限: 120 张同一场景微扰 (置信度 0.882~0.891 极窄), 泛化能力未验证
path: {os.path.abspath(DST)}
train: images/train
val: images/val
names:
  0: gold_module
"""
open(os.path.join(DST, "data.yaml"), "w").write(yaml)

print(f"train {n_t} · val {n_v} · 有标注 {n_lbl}/{len(imgs)}")
print(f"→ {os.path.abspath(DST)}/data.yaml")
