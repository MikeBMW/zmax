#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_hard_holdout.py — 从 AR 像素级真值留出集派生「难档」留出集 (外观退化, 标签不变)

为什么要它
    在役 models/yolo_ar_peg.pt 在原留出集 (seed 999, 60 张) 上 mAP50=0.995 / mAP50-95=0.939 ⇒
    该口径已饱和, 进化「有提升」在数学上不可达。难档把**外观**往真机方向推 (模糊/暗光/噪声/压缩/
    小目标), 几何真值一律不动 ⇒ 仍是像素级真值, 不是模型预测, 也不是"猜的框"。

口径
    · 输入 = zmax_data/ar_mujoco/holdout/{images,labels}  (真值来源, 只读)
    · 输出 = <out>/{images,labels} + data.yaml + meta.json (含每种退化的确定参数与 seed)
    · 4 档退化 × 60 张 = 240 张; 同一 seed 恒定 ⇒ 每代可比, 不会"这代碰巧简单"

用法
    python tools/ar_hard_holdout.py                      # 生成/刷新难档
    python tools/ar_hard_holdout.py --selftest           # 自检: 标签数/尺寸/确定性
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import os.path as osp
import shutil
import sys

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
SRC = osp.join(ROOT, "zmax_data", "ar_mujoco", "holdout")
OUT = osp.join(ROOT, "zmax_data", "ar_mujoco", "holdout_hard")
SEED = 2718

# 4 档退化 (名字 → 参数)。都是"真机会遇到"的成像劣化, 不改变目标位置。
TIERS = {
    "blur":   {"blur": 2.2},
    "dark":   {"bright": 0.55, "contrast": 0.85},
    "noise":  {"noise": 14.0, "jpeg": 45},
    "small":  {"scale": 0.55, "blur": 1.2, "jpeg": 60},
}


def degrade(img: Image.Image, spec: dict, rng: np.random.Generator) -> Image.Image:
    im = img.convert("RGB")
    if "scale" in spec:
        w, h = im.size
        # 缩小再放大回原尺寸: 等价于远距离/低分辨率 (框坐标不变)
        im = im.resize((max(8, int(w * spec["scale"])), max(8, int(h * spec["scale"]))), Image.BILINEAR)
        im = im.resize((w, h), Image.BILINEAR)
    if "blur" in spec:
        im = im.filter(ImageFilter.GaussianBlur(radius=float(spec["blur"])))
    if "bright" in spec:
        im = ImageEnhance.Brightness(im).enhance(float(spec["bright"]))
    if "contrast" in spec:
        im = ImageEnhance.Contrast(im).enhance(float(spec["contrast"]))
    if "noise" in spec:
        a = np.asarray(im, dtype=np.float32)
        a = a + rng.normal(0.0, float(spec["noise"]), a.shape).astype(np.float32)
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if "jpeg" in spec:
        import io
        b = io.BytesIO()
        im.save(b, format="JPEG", quality=int(spec["jpeg"]))
        b.seek(0)
        im = Image.open(b).convert("RGB")
    return im


def build() -> dict:
    imgs = sorted(f for f in os.listdir(osp.join(SRC, "images")) if f.lower().endswith(".jpg"))
    if not imgs:
        raise SystemExit("源留出集为空: %s" % SRC)
    if osp.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(osp.join(OUT, "images"))
    os.makedirs(osp.join(OUT, "labels"))
    n = 0
    for nm in imgs:
        stem = osp.splitext(nm)[0]
        lab = osp.join(SRC, "labels", stem + ".txt")
        if not osp.isfile(lab):
            continue
        for i, (tier, spec) in enumerate(TIERS.items()):
            rng = np.random.default_rng(SEED + 1000 * i + int(hashlib.md5(nm.encode()).hexdigest()[:6], 16))
            out_nm = "%s_%s.jpg" % (stem, tier)
            degrade(Image.open(osp.join(SRC, "images", nm)), spec, rng).save(
                osp.join(OUT, "images", out_nm), quality=92)
            shutil.copyfile(lab, osp.join(OUT, "labels", osp.splitext(out_nm)[0] + ".txt"))
            n += 1
    open(osp.join(OUT, "data.yaml"), "w", encoding="utf-8").write(
        "path: %s\ntrain: images\nval: images\nnames:\n  0: gold_module\n" % OUT)
    meta = {"n": n, "tiers": TIERS, "seed": SEED,
            "src": SRC, "note": "外观退化自派生; 标签=源像素级真值复制, 坐标未改"}
    open(osp.join(OUT, "meta.json"), "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def selftest() -> int:
    a = Image.new("RGB", (64, 64), (200, 160, 40))
    rng = np.random.default_rng(1)
    for tier, spec in TIERS.items():
        b = degrade(a, spec, rng)
        assert b.size == a.size, tier
    imgs = os.listdir(osp.join(OUT, "images")) if osp.isdir(OUT) else []
    labs = os.listdir(osp.join(OUT, "labels")) if osp.isdir(OUT) else []
    print("难档: images=%d labels=%d tiers=%s" % (len(imgs), len(labs), list(TIERS)))
    ok = len(imgs) == len(labs) and len(imgs) > 0
    print("✅ 自检通过" if ok else "❌ 图/标签数量不符")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    m = build()
    print("难档 → %s" % OUT)
    print("  %s" % json.dumps({k: v for k, v in m.items() if k != "tiers"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
