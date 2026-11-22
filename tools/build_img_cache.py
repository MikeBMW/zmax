#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_img_cache.py — 把采集图像一次性缩成 96×96 缓存 (uint8 .npy), 之后训练秒级加载。

为什么要这个: live_train_loop 每轮都用 PIL 逐张解码 1280×720 再缩 96×96, 单进程串行,
3.6 万张要十几分钟 —— 训练时间几乎全花在解码上, 不是训练本身。

做法: 8 进程并行解码 → 每 episode 一个 <ep>_X.npy (N×96×96×3 uint8) + <ep>_idx.json
      (与 frames.jsonl 顺序一一对应的帧名), 训练侧按 idx 对齐即可。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from multiprocessing import Pool

import numpy as np
from PIL import Image

ROOT = "/home/ubuntu/zmax"
SRC = os.path.join(ROOT, "zmax_data/live_ds")          # 原图
META = os.path.join(ROOT, "zmax_data/live_ds_fix")     # 去重元数据
OUT = os.path.join(ROOT, "zmax_data/live_cache")
SZ = 96


def _one(args):
    p, = args
    try:
        return np.asarray(Image.open(p).convert("RGB").resize((SZ, SZ)), np.uint8)
    except Exception:
        return np.zeros((SZ, SZ, 3), np.uint8)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(META, "episode_*/data/frames.jsonl"))):
        ep = f.split("/")[-3]
        rows = [json.loads(l) for l in open(f)]
        paths = [os.path.join(SRC, ep, r["img"]) for r in rows]
        with Pool(8) as po:
            arrs = po.map(_one, [(p,) for p in paths], chunksize=64)
        X = np.stack(arrs) if arrs else np.zeros((0, SZ, SZ, 3), np.uint8)
        np.save(os.path.join(OUT, "%s_X.npy" % ep), X)
        json.dump([r["img"] for r in rows], open(os.path.join(OUT, "%s_idx.json" % ep), "w"))
        print("%s: %d 张 → %s_X.npy (%.0f MB)"
              % (ep, len(X), ep, X.nbytes / 1e6), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
