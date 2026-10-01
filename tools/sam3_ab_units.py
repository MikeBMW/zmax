#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAM3 基座 vs 适配器 **逐单位**(帧, GT 框) IoU 明细 + 配对 95%CI —— 小样本行的功效取证

用途: `sam3_ab_multiseed.py` 里的 `shipped` 行只有 5 个 GT 框 (annot_v1 自己的留出 val),
     光看均值 Δ 会误判。本工具把**逐单位**数值与配对统计打出来, 让"样本够不够"一眼可见。

口径与 sam3_ab_multiseed.eval_perquery 完全一致 (同一预处理/同分辨率/同教师伪标签缓存/
同一批提示框抖动 seed), 配对单位 = (帧, GT 框)。

用法:
  ./gui-venv311/bin/python tools/sam3_ab_units.py --adapter outputs/sam3_finetune/annot_v1/lora_adapter \
      --split val --jitter 0.08 --eval-seeds 11,12,13 --out reports/sam3_ab_20261001/shipped_units.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))

from lerobot.policies.sam3_seg import finetune as FT                       # noqa: E402
from lerobot.policies.sam3_seg.lora_inject import load_lora_adapter        # noqa: E402
import sam3_ab_multiseed as AB                                             # noqa: E402


def ci95(vals):
    a = np.asarray(vals, float)
    if a.size < 2:
        return (0.0, 0.0, 0.0, 0.0)
    m, sd = float(a.mean()), float(a.std(ddof=1))
    se = sd / np.sqrt(a.size)
    return (m, sd, m - 1.96 * se, m + 1.96 * se)


def main() -> int:
    ap = argparse.ArgumentParser(description="适配器逐单位 IoU 明细 + 配对 CI")
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--dataset", default=FT.DATASET_DIR)
    ap.add_argument("--cache-dir", default=str(REPO / "data" / "sam3_finetune_cache"))
    ap.add_argument("--split", default="val", help="留出集 (val=该适配器训练时未见的帧)")
    ap.add_argument("--jitter", type=float, default=0.08)
    ap.add_argument("--eval-seeds", default="11,12,13")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    import torch
    names = FT.read_class_names(a.dataset)
    va = FT.scan_split(a.dataset, a.split)
    evs = [int(x) for x in a.eval_seeds.split(",") if x.strip()]
    print("[data] %s 集 %d 帧 / %d 框 · 类 %s" % (a.split, len(va), sum(len(s.boxes_xyxy) for s in va), names))

    from transformers import Sam3Model, Sam3Processor
    proc = Sam3Processor.from_pretrained(FT.SAM3_DIR, local_files_only=True)
    try:
        proc.image_processor.size = {"height": FT.SIZE, "width": FT.SIZE}
    except Exception:                                                      # noqa: BLE001
        pass
    cache = FT.preencode(proc, va, FT.SIZE, names, log=print)
    args = AB._run_args(cache_dir=a.cache_dir)

    units, rows = [], []
    m = Sam3Model.from_pretrained(FT.SAM3_DIR, local_files_only=True, dtype=torch.bfloat16).to("cuda").eval()
    for es in evs:
        r = AB.eval_perquery(m, va, cache, args, a.jitter, es)
        rows.append(("base", es, r))
    del m
    torch.cuda.empty_cache()
    mad, _, _ = FT.build_trainable_model(FT.SAM3_DIR, size=FT.SIZE, log=print)
    info = load_lora_adapter(mad, a.adapter, targets=dict(FT.LORA_TARGETS), r=FT.R, alpha=FT.ALPHA,
                             prefix_filter=AB._adapter_prefix_filter(), log=print)
    for es in evs:
        r = AB.eval_perquery(mad, va, cache, args, a.jitter, es)
        rows.append(("adapter", es, r))
    del mad
    torch.cuda.empty_cache()

    base = {es: r for tag, es, r in rows if tag == "base"}
    adap = {es: r for tag, es, r in rows if tag == "adapter"}
    for es in evs:
        for k in sorted(set(base[es]) & set(adap[es])):
            units.append({"eval_seed": es, "stem": k[0], "gt_idx": k[1],
                          "base_mask": base[es][k]["mask"], "ad_mask": adap[es][k]["mask"],
                          "base_box": base[es][k]["box"], "ad_box": adap[es][k]["box"],
                          "d_mask": adap[es][k]["mask"] - base[es][k]["mask"],
                          "d_box": adap[es][k]["box"] - base[es][k]["box"]})
    db = [u["d_box"] for u in units]
    dm = [u["d_mask"] for u in units]
    bb, sb, lo_b, hi_b = ci95(db)
    bm, sm, lo_m, hi_m = ci95(dm)
    n_frames = len({u["stem"] for u in units})
    res = {"adapter": a.adapter, "adapter_info": info, "split": a.split, "jitter": a.jitter,
           "eval_seeds": evs, "n_units": len(units), "n_distinct_frames": n_frames,
           "d_box": {"mean": bb, "sd": sb, "ci95": [lo_b, hi_b], "win_rate": float(np.mean([x > 0 for x in db]))},
           "d_mask": {"mean": bm, "sd": sm, "ci95": [lo_m, hi_m], "win_rate": float(np.mean([x > 0 for x in dm]))},
           "base_box_mean": float(np.mean([u["base_box"] for u in units])),
           "ad_box_mean": float(np.mean([u["ad_box"] for u in units])),
           "base_mask_mean": float(np.mean([u["base_mask"] for u in units])),
           "ad_mask_mean": float(np.mean([u["ad_mask"] for u in units])),
           "units": units}
    print("\n逐单位 (帧, GT框) · 抖动 %.2f · %d 个单位 / %d 帧" % (a.jitter, len(units), n_frames))
    print("  框IoU   Δ 均值 %+.4f (逐单位 sd %.4f) · 95%%CI [%+.4f, %+.4f] · 胜率 %.0f%%"
          % (bb, sb, lo_b, hi_b, 100 * res["d_box"]["win_rate"]))
    print("  掩膜IoU Δ 均值 %+.4f (逐单位 sd %.4f) · 95%%CI [%+.4f, %+.4f] · 胜率 %.0f%%"
          % (bm, sm, lo_m, hi_m, 100 * res["d_mask"]["win_rate"]))
    print("  ⇒ 逐单位 sd≈%.3f ⇒ 均值标准误 ≈ %.3f ⇒ %s"
          % (max(sb, sm), max(sb, sm) / max(np.sqrt(len(units)), 1),
             "Δ 远小于 1 个标准误 ⇒ **无功效, 不能单独定论**"
             if abs(bb) < max(sb, sm) / max(np.sqrt(len(units)), 1) else "Δ 大于 1 个标准误"))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        print("报告: %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
