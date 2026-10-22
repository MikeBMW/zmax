#!/usr/bin/env python3
"""给 3DGS 数据集做图像去重 —— 同一张图配多个位姿会喂出矛盾监督。

为什么要这一步:
  实测 338 帧里有 248 帧图像完全相同(90 组), 但位姿 337/338 都不同。
  Orin 的 /frame.jpg 在机械臂微动时返回缓存帧, 位姿却在小幅真变动 ⇒
  "图没变、位姿变了" ⇒ 3DGS 看到同图不同位姿, 只能把高斯糊成一团平均掉,
  PSNR 卡在 15dB 上不去。

判据: 降采样到 64x48 灰度后平均像素差 < --thr 视为重复, 保留第一帧。

用法:
  python3 tools/gs_dedup.py --src <数据集> --out <输出> [--thr 1.0]
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np
from PIL import Image


def sig(path, size=(64, 48)):
    return np.asarray(Image.open(path).convert("L").resize(size), dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--thr", type=float, default=1.0, help="平均像素差阈值, 小于视为重复")
    a = ap.parse_args()

    with open(os.path.join(a.src, "cameras.json")) as f:
        ds = json.load(f)
    frames = ds["frames"]
    print(f"输入: {len(frames)} 帧, thr={a.thr}")

    os.makedirs(os.path.join(a.out, "images"), exist_ok=True)

    kept = []
    kept_sigs = []
    dropped = 0
    for fr in frames:
        p = os.path.join(a.src, "images", fr["file"])
        if not os.path.exists(p):
            continue
        s = sig(p)
        # 和已保留的所有帧比 —— 338 帧规模下全比也不慢
        dup = False
        for ks in kept_sigs:
            if np.abs(s - ks).mean() < a.thr:
                dup = True
                break
        if dup:
            dropped += 1
            continue
        kept.append(fr)
        kept_sigs.append(s)
        shutil.copy2(p, os.path.join(a.out, "images", fr["file"]))

    out = dict(ds)
    out["frames"] = kept
    out["_dedup"] = {
        "src": a.src,
        "n_in": len(frames),
        "n_out": len(kept),
        "n_dropped": dropped,
        "thr": a.thr,
    }
    with open(os.path.join(a.out, "cameras.json"), "w") as f:
        json.dump(out, f, indent=1)

    print(f"输出: {len(kept)} 帧 (丢弃重复 {dropped} 帧, {dropped/max(len(frames),1)*100:.1f}%)")
    # 位姿跨度（去重后才是真实有效覆盖）
    P = np.array([f["pose"] for f in kept])
    span = np.linalg.norm(P[:, :3].max(axis=0) - P[:, :3].min(axis=0))
    print(f"去重后位姿跨度: {span:.3f} m (X {np.ptp(P[:,0]):.3f} Y {np.ptp(P[:,1]):.3f} Z {np.ptp(P[:,2]):.3f})")
    if len(kept) < 40:
        print(f"⚠️ 只剩 {len(kept)} 帧, 可能太少, 考虑放宽 --thr")


if __name__ == "__main__":
    sys.exit(main())
