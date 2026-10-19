#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_surface_defect_local.py — L2 客观局部异常检测 (不依赖 VLM 的是/否)

为什么不用 VLM 下结论: 实测 SmolVLM 有 **yea-saying bias** —— 同一张图问
"有划痕吗"和"是不是完全干净"两个相反问题**都答 yes** (tools/l5_vlm_hallucination_test.py ① ② ③)。
⇒ 缺陷结论必须由可复现的算法给; VLM 只保留"描述性线索"。

算法 (标准 AOI 局部对比度法, 参数可复现):
  ① 在**摆正后的模块 ROI**内 (不看整帧 — 老倪 2026-10-19 口径)
  ② 灰度 → CLAHE 抑制光照不均 → 大核中值滤波得到"该处本应有的亮度"背景
  ③ 残差 = |图 − 背景|; 阈值 = max(k·σ, 绝对下限) ⇒ 候选像素
  ④ 形态学开运算去噪 → 连通域 → 面积/长宽/对比度过滤 ⇒ 缺陷候选框
  ⑤ 输出: 候选数 + 每个框的位置/面积/峰值对比度 + 标注图
"""
from __future__ import annotations

import json
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from aoi_surface_rect import surface_judge                                  # noqa: E402
from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality  # noqa: E402

OUTD = os.path.join(ROOT, "data/deliver")
LOGF = os.path.join(ROOT, "data/memory/l2_defect_log.jsonl")


def detect_defects(bgr, k_sigma=4.0, min_area_frac=0.0004, clahe_clip=2.0, med_k=31,
                   edge_margin_frac=0.05):
    """局部异常检测。返回 (candidates, dbg) — 参数全部显式, 别人能重跑出同样结果。"""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
    gg = clahe.apply(g)
    bg = cv2.medianBlur(gg, med_k if med_k % 2 == 1 else med_k + 1)   # 该处"应有的"亮度
    resid = np.abs(gg.astype(np.int16) - bg.astype(np.int16)).astype(np.float32)
    sigma = float(np.std(resid))
    thr = max(k_sigma * sigma, 12.0)                                  # 绝对下限防噪声压倒
    mask = (resid >= thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    h, w = g.shape[:2]
    n, lab, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    min_area = max(12, int(min_area_frac * h * w))
    # 2026-10-19: 模块边缘/棱线本身就是高对比 ⇒ 贴边候选必误报, 按 margin 排除
    mx, my = int(w * edge_margin_frac), int(h * edge_margin_frac)
    cands, dropped_edge = [], 0
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area:
            continue
        if bw < 3 or bh < 3:
            continue
        if x <= mx or y <= my or (x + bw) >= (w - mx) or (y + bh) >= (h - my):
            dropped_edge += 1
            continue
        sub = resid[y:y + bh, x:x + bw]
        cands.append({
            "bbox": [int(x), int(y), int(bw), int(bh)],
            "area": int(area),
            "area_frac": round(float(area) / (h * w), 5),
            "peak": round(float(sub.max()), 1),
            "mean": round(float(sub.mean()), 1),
            "aspect": round(max(bw, bh) / float(max(1, min(bw, bh))), 2),
            "where": ("左" if x < w / 3 else ("中" if x < 2 * w / 3 else "右")),
        })
    cands.sort(key=lambda c: -c["peak"])
    dbg = {"sigma": round(sigma, 2), "thr": round(thr, 2), "min_area": min_area,
           "n_raw": int(n - 1), "dropped_edge": dropped_edge, "n_kept": len(cands),
           "edge_margin_frac": edge_margin_frac, "roi_hw": [int(w), int(h)]}
    return cands, dbg


def main(grab=True):
    os.makedirs(OUTD, exist_ok=True)
    os.makedirs(os.path.dirname(LOGF), exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")

    sq = SurfaceOpticalQuality()
    expo = sq.exposure()
    im = sq.capture(grab=grab)
    if im is None:
        print("❌ 取帧失败"); return 1
    crop, _, meta = surface_judge(im, out_long=1400, expand=True)
    if crop is None:
        print("❌ 没搜到刚体: %s" % meta.get("why")); return 1

    roi_q = SurfaceOpticalQuality.metrics(crop)
    l2_v, l2_why = SurfaceOpticalQuality.verdict(roi_q)
    cands, dbg = detect_defects(crop)

    print("① 摆正 ROI %dx%d 水平=%s no_stretch=%s expand_px=%s"
          % (roi_q["hw"][0], roi_q["hw"][1], roi_q["hw"][0] >= roi_q["hw"][1],
             meta.get("no_stretch"), meta.get("expand_px")))
    print("② 光学: mean=%.1f 死白=%.2f%% 暗部=%.1f%% 清晰度=%.1f ⇒ %s (%s)"
          % (roi_q["mean"], roi_q["sat_pct"], roi_q["dark_pct"], roi_q["sharpness"], l2_v, l2_why))
    print("③ 局部异常: σ=%.2f 阈值=%.2f 原始连通域=%d 贴边剔除=%d 保留候选=%d (最小面积 %d px)"
          % (dbg["sigma"], dbg["thr"], dbg["n_raw"], dbg.get("dropped_edge", 0),
             dbg["n_kept"], dbg["min_area"]))
    for i, cd in enumerate(cands[:8], 1):
        print("   候选%d %s @bbox=%s 面积=%d(%.3f%%) 峰值=%.1f 长宽比=%.2f"
              % (i, cd["where"], cd["bbox"], cd["area"], cd["area_frac"], cd["peak"], cd["aspect"]))

    # 标注图 (放大便于目检)
    vis = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    vis = cv2.cvtColor(vis, cv2.COLOR_RGB2BGR)
    for i, cd in enumerate(cands[:8], 1):
        x, y, bw, bh = cd["bbox"]
        cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
        cv2.putText(vis, str(i), (x, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    S = max(1, min(5, int(760 / float(vis.shape[0]))))   # 按高度放大: 188 高 ⇒ 4倍, 便于目检
    big = cv2.resize(vis, (vis.shape[1] * S, vis.shape[0] * S), interpolation=cv2.INTER_NEAREST)
    png = os.path.join(OUTD, "l2_defect_marked_%s.png" % stamp)
    cv2.imwrite(png, big)

    rec = {"ts": stamp, "expo": expo, "roi_png": png,
           "rect": {k: meta.get(k) for k in ("angle", "fill", "crop_size", "no_stretch", "expand_px")},
           "roi_quality": roi_q, "verdict": l2_v, "verdict_why": l2_why,
           "detect_params": {"k_sigma": 4.0, "min_area_frac": 0.0004, "clahe_clip": 2.0, "med_k": 31},
           "dbg": dbg, "candidates": cands}
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("④ 标注图 → %s (放大%dx)" % (os.path.relpath(png, ROOT), S))
    print("⑤ 已记入 %s" % os.path.relpath(LOGF, ROOT))
    print("\n口径说明: 候选=统计异常, **不等于缺陷**。判定需 ① 光学达标(当前 %s) ② 人工/标定件复核。" % l2_v)
    return 0


if __name__ == "__main__":
    sys.exit(main(grab="--nograb" not in sys.argv))
