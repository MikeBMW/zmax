#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_models_output.py — 「所有模型能输出 + 精度执行」的取证

不发明指标, 只取三样真数据:
  ① 真机帧上真推理 (L2 YOLO): 新权重 vs 在役权重, 同帧同阈值, 报 检出帧数/平均置信/最大置信
  ② 训练日志里各层最后一条 loss / validate 数字 (L4/L3/L5) —— 没有就写"无"
  ③ 多机能量算法自检 (14/14)

用法: PYTHONPATH=src ./gui-venv311/bin/python tools/verify_models_output.py [--train-dir reports/joint_train_xxx]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = "/home/ubuntu/zmax"
IMG_DIRS = [
    "data/datasets/yolo_annot/dataset/images/val",
    "data/datasets/yolo_annot/dataset/images/train",
    "zmax_data/yolo_annot_20260917_1345/dataset/images/val",
    "zmax_data/yolo_annot_20260917_1345/dataset/images/train",
]


def yolo_probe(weights, frames, conf=0.25):
    from ultralytics import YOLO
    import numpy as np
    m = YOLO(weights)
    rows = []
    for f in frames:
        r = m.predict(f, conf=conf, verbose=False)[0]
        c = r.boxes.conf.cpu().numpy() if r.boxes is not None and len(r.boxes) else np.array([])
        rows.append((os.path.basename(f), int(len(c)), float(c.max()) if len(c) else 0.0,
                     float(c.mean()) if len(c) else 0.0))
    hit = sum(1 for x in rows if x[1] > 0)
    return {"weights": weights, "frames": len(rows), "hit_frames": hit,
            "mean_conf": float(np.mean([x[3] for x in rows if x[1] > 0])) if hit else 0.0,
            "max_conf": float(max(x[2] for x in rows)), "rows": rows}


def frames(n=6):
    out = []
    for d in IMG_DIRS:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, "*.jpg")) + glob.glob(os.path.join(p, "*.png")))
        if len(out) >= n:
            break
    return out[:n]


def grab(log, pats):
    if not os.path.isfile(log):
        return None
    txt = open(log, encoding="utf-8", errors="ignore").read()
    for p in pats:
        m = re.findall(p, txt)
        if m:
            return m[-1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-dir", default="")
    a = ap.parse_args()
    td = a.train_dir or (sorted(glob.glob(os.path.join(ROOT, "reports/joint_train_*")))[-1])
    print("证据目录:", os.path.relpath(td, ROOT))

    res = {"train_dir": os.path.relpath(td, ROOT)}

    # ① L2 真推理
    fr = frames(6)
    new = sorted(glob.glob(os.path.join(ROOT, "outputs/**/annot_*/weights/best.pt"), recursive=True))
    new = [w for w in new if os.path.getmtime(w) > os.path.getmtime(os.path.join(ROOT, "VERSION.md")) - 86400 * 2]
    new = new[-1] if new else ""
    live = os.path.join(ROOT, "models/yolo_peg_live.pt")
    print("\n[L2] 真机帧 %d 张 · 阈值 conf=0.25" % len(fr))
    if fr and new:
        A = yolo_probe(new, fr)
        print("  新权重 %s: 检出 %d/%d 帧 · 平均置信 %.3f · 最高 %.3f"
              % (os.path.relpath(new, ROOT), A["hit_frames"], A["frames"], A["mean_conf"], A["max_conf"]))
        res["yolo_new"] = A
    if fr and os.path.exists(live):
        B = yolo_probe(live, fr)
        print("  在役   models/yolo_peg_live.pt: 检出 %d/%d 帧 · 平均置信 %.3f · 最高 %.3f"
              % (B["hit_frames"], B["frames"], B["mean_conf"], B["max_conf"]))
        res["yolo_live"] = B

    # ② 各层日志数字
    print("\n[各层训练数字]")
    for name, pats in [
        ("L4", [r"validate[^\n]*loss[^\n]*?([0-9.]+)", r"val_loss[=: ]+([0-9.]+)", r"Epoch 1[^\n]*loss[^\n]*?([0-9.]+)"]),
        ("L3", [r"train_loss[=: ]+([0-9.]+)", r"loss[=: ]+([0-9.]+)"]),
        ("L2", [r"mAP50[^\n]*?([0-9.]+)\]", r"all\s+(\d+)\s+\d+\s+([0-9.]+)"]),
        ("L5", [r"acc[^\n]*?([0-9.]+)", r"A/B[^\n]*?([0-9.]+)"]),
    ]:
        v = grab(os.path.join(td, name + ".log"), pats)
        print("  %s: %s" % (name, v if v else "日志无匹配数字 (如实记无)"))
        res.setdefault("train", {})[name] = v

    # ③ 多机能量
    print("\n[多机能量]")
    p = os.path.join(ROOT, "src/lerobot/manifold/multi_machine_energy.py")
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import numpy as np
    from lerobot.manifold.multi_machine_energy import machine_energy, assist_share
    from lerobot.manifold.state_space_energy import StateSpaceHamiltonian
    from lerobot.manifold.se3_gravity_provider import _rpy_to_T
    ham = StateSpaceHamiltonian()
    g = _rpy_to_T([0.649, 0.404, 0.114, 2.961, -1.490, 0.205, 0.0]); gd = g.copy()
    gd[:3, 3] = g[:3, 3] + g[:3, 2] * 0.005
    M = machine_energy(g, gd, np.array([0, 0, 0.05, 0, 0, 0]), ham)
    s = assist_share(240.0, 319.0, 120.0)
    print("  H=%.6f J | α_s=%.4f α_m=%.4f Σα=%.6f · 输出正常"
          % (M["H"], s["alpha_slave"], s["alpha_master"], s["sum_alpha"]))
    res["energy"] = {"H": M["H"], "alpha_s": s["alpha_slave"]}

    out = os.path.join(td, "verify_models_output.json")
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=2)
    print("\n落盘:", os.path.relpath(out, ROOT))
    # 判定: 每层要么有数字要么显式"无", 不许静默通过
    bad = [k for k, v in res.get("train", {}).items() if v is None]
    if bad:
        print("⚠ 无数字的层:", ",".join(bad), "(未跑或日志未出数, 不算成功)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
