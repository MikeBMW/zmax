#!/usr/bin/env python3
"""SAM3 在 Intel(550C) 上真跑一次: 文本提示 → 实例分割 → 出图 + JSON 判据。

老倪的要求是「SAM3 要完整运行, 看清楚光模块」。这个脚本只做一件事:
把 550C 本地的 SAM3 权重真实前向一遍, 给出每个提示词到底看见几个实例、
分数多少、框在哪、掩膜多大, 并把掩膜画回图上 —— 有图有数, 不靠嘴说。

用法:
  python tools/sam3_probe_intel.py --img /tmp/arm.jpg --out /tmp/sam3_out
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import torch
from PIL import Image, ImageDraw

DEFAULT_MODEL = "/home/intel/zmax_550c/models/sam3_hf"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="/tmp/sam3_out")
    ap.add_argument("--prompts", default="optical module|green connector|slot|metal pin|connector|metal")
    ap.add_argument("--threshold", type=float, default=0.30)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()

    torch.set_num_threads(a.threads)
    os.makedirs(a.out, exist_ok=True)

    from transformers import Sam3Model, Sam3Processor

    t0 = time.time()
    proc = Sam3Processor.from_pretrained(a.model, local_files_only=True)
    model = Sam3Model.from_pretrained(a.model, local_files_only=True).eval()
    t_load = time.time() - t0
    n_par = sum(p.numel() for p in model.parameters())
    print(f"[加载] {a.model}")
    print(f"[加载] {t_load:.1f}s · 参数 {n_par/1e6:.1f}M · threads={torch.get_num_threads()}")

    img = Image.open(a.img).convert("RGB")
    W, H = img.size
    print(f"[输入] {a.img} {W}x{H}")

    rows = []
    for prompt in [p.strip() for p in a.prompts.split("|") if p.strip()]:
        t1 = time.time()
        inputs = proc(images=img, text=prompt, return_tensors="pt")
        with torch.inference_mode():
            out = model(**inputs)
        res = proc.post_process_instance_segmentation(
            out, threshold=a.threshold, mask_threshold=0.5, target_sizes=[(H, W)]
        )
        dt = time.time() - t1
        r = res[0] if isinstance(res, (list, tuple)) else res
        keys = list(r.keys()) if hasattr(r, "keys") else type(r).__name__
        masks = r.get("masks") if hasattr(r, "get") else None
        scores = r.get("scores") if hasattr(r, "get") else None
        boxes = r.get("boxes") if hasattr(r, "get") else None

        n = 0 if masks is None else (len(masks) if hasattr(masks, "__len__") else int(masks.shape[0]))
        item = {"prompt": prompt, "n": int(n), "ms": round(dt * 1000, 1), "keys": keys if isinstance(keys, list) else str(keys)}

        if n:
            m = masks
            if torch.is_tensor(m):
                m_np = m.detach().cpu().numpy()
            else:
                m_np = np.asarray(m)
            if m_np.ndim == 4:
                m_np = m_np[0]
            if m_np.dtype != bool:
                m_np = m_np > 0.5
            sc = None
            if scores is not None:
                sc = scores.detach().cpu().numpy().reshape(-1)[:n]
            bx = None
            if boxes is not None:
                bx = boxes.detach().cpu().numpy()
                if bx.ndim == 3:
                    bx = bx[0]
            item["scores"] = [round(float(v), 3) for v in (sc if sc is not None else [])]
            item["areas_px"] = [int(v.sum()) for v in m_np]
            item["boxes_xyxy"] = [[round(float(v), 1) for v in b] for b in (bx if bx is not None else [])]
            item["best_area_frac"] = round(float(max(v.sum() for v in m_np)) / (W * H), 4)

            # 画图: 每个实例一种颜色, 半透明叠加 + 框 + 标签
            pal = [(255, 60, 60), (60, 220, 120), (80, 160, 255), (255, 200, 40), (200, 90, 255), (40, 230, 230)]
            ov = img.copy()
            arr = np.array(ov).astype(np.float32)
            for i, mk in enumerate(m_np):
                c = np.array(pal[i % len(pal)], dtype=np.float32)
                arr[mk] = arr[mk] * 0.45 + c * 0.55
            ov = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
            dr = ImageDraw.Draw(ov)
            for i, mk in enumerate(m_np):
                ys, xs = np.where(mk)
                if len(xs) == 0:
                    continue
                dr.rectangle([xs.min(), ys.min(), xs.max(), ys.max()], outline=pal[i % len(pal)], width=2)
                dr.text((int(xs.min()) + 3, int(ys.min()) + 2), f"{prompt}#{i}", fill=(255, 255, 255))
            safe = prompt.replace(" ", "_")
            ov.save(os.path.join(a.out, f"sam3_{safe}.png"))
            item["png"] = os.path.join(a.out, f"sam3_{safe}.png")

        rows.append(item)
        print(f"[{prompt:16s}] 实例 {item['n']:2d} · {item['ms']:7.1f}ms · 分数 {item.get('scores', [])[:5]} · 面积占比 {item.get('best_area_frac', 0)}")

    summary = {
        "img": a.img, "wh": [W, H], "model": a.model, "params_m": round(n_par / 1e6, 1),
        "load_s": round(t_load, 2), "threshold": a.threshold,
        "torch": torch.__version__, "out_dir": a.out, "rows": rows,
    }
    with open(os.path.join(a.out, "sam3_probe.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    hit = [r for r in rows if r["n"] > 0]
    print(f"[汇总] 命中提示 {len(hit)}/{len(rows)} · 结果 {a.out}/sam3_probe.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
