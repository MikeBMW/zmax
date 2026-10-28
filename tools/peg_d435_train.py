#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peg_d435_train.py — 用 D435 视角的帧训练「光模块」检测头(1 类: peg, 只给 2D 框)。

老倪 2026-10-20 选 B: 「单独给 D435 视角训一个检测头(现权重在 D435 上 0 检出), 只能给 2D 框」。

为什么不用现役权重直接跑: `models/yolo_peg_live.pt` 是在**腕相机 D405** 的视角/尺度上训的,
在 D435 上 conf>=0.25 基本 0 检出(实测: 全帧 0 个; conf=0.15 才冒出一个 0.37 的疑似框 + 两个静止杂物误检)。

流程(每步都打印数字, 不靠形容词):
  1. 读 `zmax_data/datasets/peg_d435/meta.jsonl` + raw/*.jpg
  2. **伪标签**: 用基座模型在 D435 帧上跑, 只取 class=peg 且尺寸在 [min,max] 像素、且
     与相邻帧同位置框 IoU>=iou_keep 的(时间一致性) —— 单帧孤立的低分框一律丢
  3. 按时间切分 train/val (不用随机切: 相邻帧几乎一样, 随机切会虚高)
  4. 训练 ultralytics YOLO (基座默认 COCO yolov8n)
  5. 训练后在 val 上真推理 → 打印检出率/置信度分布 + 落 4 张标注图; 汇总 JSON 进 reports/
用法:
  gui-venv311/bin/python tools/peg_d435_train.py --epochs 80 --name d435_r1
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import shutil
import sys
import time

import cv2
import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools"))


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1) + max(0.0, bx2 - bx1) * max(0.0, by2 - by1) - inter
    return 0.0 if ua <= 0 else inter / ua


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "zmax_data/datasets/peg_d435"))
    ap.add_argument("--base-model", default=os.path.join(ROOT, "models/yolo_peg_live.pt"),
                    help="伪标签用的模型(现役腕相机权重)")
    ap.add_argument("--init", default=os.path.join(ROOT, "models/yolov8n.pt"),
                    help="训练基座(COCO, 1 类新头)")
    ap.add_argument("--conf", type=float, default=0.22)
    ap.add_argument("--min-px", type=float, default=22.0)
    ap.add_argument("--max-px", type=float, default=200.0)
    ap.add_argument("--iou-keep", type=float, default=0.30, help="与相邻帧框的最小 IoU(时间一致性)")
    ap.add_argument("--static-filter", action="store_true", default=True,
                    help="剔除跨帧位置几乎不变的簇(静止杂物误检); 默认开")
    ap.add_argument("--no-static-filter", dest="static_filter", action="store_false")
    ap.add_argument("--static-min-frac", type=float, default=0.25, help="簇出现帧数占比门槛")
    ap.add_argument("--static-px", type=float, default=12.0, help="簇位置 std 上限(px)")
    ap.add_argument("--static-rad", type=float, default=18.0, help="簇半径(px)")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--name", default="d435_r1")
    a = ap.parse_args()

    from ultralytics import YOLO

    recs = []
    for one in [x for x in a.data_dir.split(",") if x.strip()]:
        mp = os.path.join(one, "meta.jsonl")
        if not os.path.exists(mp):
            print("跳过(无 meta.jsonl): %s" % one); continue
        for ln in open(mp, encoding="utf-8"):
            if not ln.strip():
                continue
            r = json.loads(ln)
            r["_dir"] = one
            if os.path.exists(os.path.join(one, "raw", r["file"])):
                recs.append(r)
    recs.sort(key=lambda r: r["ts"])
    print("帧数: %d (%.1fs 跨度)" % (len(recs), recs[-1]["ts"] - recs[0]["ts"] if recs else 0))

    # ── 伪标签 ─────────────────────────────────────────────────────────
    base = YOLO(a.base_model)
    peg_ids = [i for i, n in base.names.items() if n == "peg"]
    print("基座类别:", base.names, "→ 取 peg =", peg_ids)
    cand = []           # 每帧: [(box, conf), ...]
    for r in recs:
        im = cv2.imread(os.path.join(r["_dir"], "raw", r["file"]))
        res = base.predict(im, conf=a.conf, verbose=False)[0]
        bx = []
        for b in res.boxes:
            if peg_ids and int(b.cls) not in peg_ids:
                continue
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            w, h = x2 - x1, y2 - y1
            if not (a.min_px <= w <= a.max_px and a.min_px <= h <= a.max_px):
                continue
            bx.append(([x1, y1, x2, y2], float(b.conf)))
        cand.append(bx)

    kept, rej_iso = 0, 0
    labels = []
    for i, bx in enumerate(cand):
        out = []
        for box, cf in bx:
            near = cand[i - 1] + cand[i + 1] if 0 < i < len(cand) - 1 else (cand[i - 1] if i else cand[i + 1] if len(cand) > 1 else [])
            ok = any(iou(box, nb) >= a.iou_keep for nb, _ in near)
            if ok:
                out.append(box)
            else:
                rej_iso += 1
        labels.append(out)
        kept += len(out)
    print("伪标签: 保留 %d 框 / 丢弃孤立 %d 框 (时间一致性 IoU>=%.2f)" % (kept, rej_iso, a.iou_keep))

    # ── 静止杂物过滤 (2026-10-20 实测: 腕相机权重在 D435 上会把台面上的静止物件误检成 peg) ──
    # 判据用**运动**: 机械臂在动时真模块的像素位置跟着动(本次采集里最高分框 x 极差 238px),
    # 而误检点在 165 帧里几乎不动(实测两个簇 (250,400)/(300,400) 出现 153~160 帧)。
    # ⇒ 跨帧聚类后, "出现帧数多 且 位置方差小" 的簇一律当静止杂物剔掉; 这不是预先固定坐标, 是拿运动判的。
    if a.static_filter:
        pts = []
        for i, bx in enumerate(labels):
            for box in bx:
                pts.append(((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0, i))
        clusters = []          # [cx, cy, n, sx, sy]
        for cx, cy, _i in pts:
            for c in clusters:
                if abs(c[0] - cx) <= a.static_rad and abs(c[1] - cy) <= a.static_rad:
                    c[2] += 1
                    c[0] += (cx - c[0]) / c[2]
                    c[1] += (cy - c[1]) / c[2]
                    c[3].append(cx)
                    c[4].append(cy)
                    break
            else:
                clusters.append([cx, cy, 1, [cx], [cy]])
        static = []
        for c in clusters:
            if c[2] >= a.static_min_frac * len(labels):
                vx = float(np.std(c[3])) if len(c[3]) > 1 else 0.0
                vy = float(np.std(c[4])) if len(c[4]) > 1 else 0.0
                if vx < a.static_px and vy < a.static_px:
                    static.append((c[0], c[1], c[2], round(vx, 1), round(vy, 1)))
        if static:
            print("静止杂物簇(出现>=%.0f%%帧 且 位置std<%.0fpx): %s"
                  % (100 * a.static_min_frac, a.static_px, static))
            dropped_static = 0
            for i, bx in enumerate(labels):
                keep = []
                for box in bx:
                    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
                    if any(abs(sx - cx) <= a.static_rad and abs(sy - cy) <= a.static_rad
                           for sx, sy, _n, _vx, _vy in static):
                        dropped_static += 1
                    else:
                        keep.append(box)
                labels[i] = keep
            print("静止杂物框剔除: %d 个 → 剩 %d 框" % (dropped_static, sum(len(x) for x in labels)))

    n_pos = sum(1 for l in labels if l)
    print("有目标的帧 %d / %d (%.0f%%)" % (n_pos, len(recs), 100.0 * n_pos / max(1, len(recs))))

    # ── 切分 + 落盘 ─────────────────────────────────────────────────────
    # ⚠ 不能按时间切尾: 有标注的帧集中在一段(实采 400 帧里只有 73 帧标得上), 尾部全是空帧 ⇒
    #   val 0 个实例、mAP 恒 0, 看着像"训崩了"。改成**按有无目标分层抽样**, 保证 val 里有正样本。
    ds = os.path.join(a.data_dir.split(",")[0], "ds_%s" % a.name)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        os.makedirs(os.path.join(ds, sub), exist_ok=True)
    pos_idx = [i for i, l in enumerate(labels) if l]
    neg_idx = [i for i, l in enumerate(labels) if not l]
    step = max(2, int(round(1.0 / max(1e-6, a.val_frac))))
    val_idx = set(pos_idx[::step]) | set(neg_idx[::step])
    split = len(recs) - len(val_idx)
    print("切分(分层): val %d 帧 (其中带目标 %d) / train %d 帧"
          % (len(val_idx), len([i for i in val_idx if labels[i]]), split))
    for i, (r, boxes) in enumerate(zip(recs, labels)):
        part = "val" if i in val_idx else "train"
        src = os.path.join(r["_dir"], "raw", r["file"])
        dst = os.path.join(ds, "images", part, r["file"])
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
        W, H = r["w"], r["h"]
        lines = []
        for x1, y1, x2, y2 in boxes:
            cx, cy = (x1 + x2) / 2.0 / W, (y1 + y2) / 2.0 / H
            bw, bh = (x2 - x1) / W, (y2 - y1) / H
            lines.append("0 %.6f %.6f %.6f %.6f" % (cx, cy, bw, bh))
        with open(os.path.join(ds, "labels", part, r["file"].replace(".jpg", ".txt")), "w") as f:
            f.write("\n".join(lines))
    yaml_p = os.path.join(ds, "data.yaml")
    with open(yaml_p, "w") as f:
        f.write("path: %s\ntrain: images/train\nval: images/val\nnc: 1\nnames: ['peg']\n" % ds)
    print("数据集: %s (train %d / val %d) · %s" % (ds, split, len(val_idx), yaml_p))

    # ── 训练 ───────────────────────────────────────────────────────────
    model = YOLO(a.init)
    t0 = time.time()
    res = model.train(data=yaml_p, epochs=a.epochs, imgsz=a.imgsz, batch=a.batch,
                      name=a.name, project=os.path.join(ROOT, "runs/peg_d435"),
                      exist_ok=True, save_period=-1, cache=False, plots=False,
                      verbose=True, device=0)
    dt = time.time() - t0
    best = os.path.join(ROOT, "runs/peg_d435", a.name, "weights/best.pt")
    print("训练结束 %.1fs · best=%s" % (dt, best))

    # ── 训练后真推理(val) ───────────────────────────────────────────────
    m = YOLO(best)
    val_files = sorted(glob.glob(os.path.join(ds, "images/val/*.jpg")))
    det_n, hit, confs = 0, 0, []
    for p in val_files:
        im = cv2.imread(p)
        r = m.predict(im, conf=0.25, verbose=False)[0]
        det_n += len(r.boxes)
        if len(r.boxes):
            hit += 1
            confs.append(max(float(b.conf) for b in r.boxes))
    print("val 推理: %d 帧 · 有检出 %d 帧 (%.0f%%) · 平均框 %.2f · conf 中位 %.2f" %
          (len(val_files), hit, 100.0 * hit / max(1, len(val_files)),
           det_n / max(1, len(val_files)), float(np.median(confs)) if confs else 0))
    for p in val_files[:4]:
        im = cv2.imread(p)
        r = m.predict(im, conf=0.25, verbose=False)[0]
        outp = os.path.join(ROOT, "zmax_data/reports", "d435_val_%s" % os.path.basename(p))
        cv2.imwrite(outp, r.plot())
    summary = {"name": a.name, "frames": len(recs), "train": split, "val": len(recs) - split,
               "pseudo_boxes": kept, "frames_with_target": n_pos,
               "conf_thr": a.conf, "iou_keep": a.iou_keep,
               "val_frames": len(val_files), "val_hit": hit, "val_boxes": det_n,
               "val_conf_median": float(np.median(confs)) if confs else None,
               "train_s": round(dt, 1), "weights": best,
               "epochs": a.epochs, "init": a.init}
    sp = os.path.join(ROOT, "zmax_data/reports", "peg_d435_train_%s.json" % a.name)
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("汇总: %s" % sp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
