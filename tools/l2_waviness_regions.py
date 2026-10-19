#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_waviness_regions.py — 测"一大片"缺陷 (区域级), 而不是小斑块

老倪 2026-10-20: 「左下角还有右侧 一大片缺陷, 你没检测出来」
  复盘: 我的网格诊断第一轮就打印出 右侧列10-11 std 30~40 / 左下 y141-188 列2-4 std 32~36,
        **数据早就在眼前, 是判据把它们筛掉了** —— 判据要求 z峰值>=6 且 圆度>=0.20 且 面积>=300,
        而"一大片"的特征恰好相反: 峰值不一定极端, 但**面积大、平均强度持续偏高、片状(圆度低)**。

新判据 (区域级, 三条都与"片"对应):
  ① 片内 局部std 的均值显著高于全图基线 (持续性, 不看单点峰值)
  ② 面积够大 (>= 模块面积的 2%)
  ③ 不看圆度, 允许细长/不规则大块 (大片缺陷本来就是不规则的)
另外必须先确认 wire_mask 有没有把这两片误遮 —— 它遮了 44%, 太可疑。
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

from l2_surface_waviness import build_wire_mask, get_crop   # noqa: E402

OUTD = os.path.join(ROOT, "data/deliver")


def std_map(g, win=21):
    gf = g.astype(np.float32)
    mu = cv2.blur(gf, (win, win))
    mu2 = cv2.blur(gf * gf, (win, win))
    return np.sqrt(np.maximum(mu2 - mu * mu, 0))


def main():
    crop, expo, info = get_crop()
    if crop is None:
        print("❌ 取不到模块 ROI: %s" % info); return 1
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    H, W = g.shape[:2]
    print("曝光 %s | 模块 ROI %dx%d mean=%.1f 死白=%.2f%%"
          % (expo, W, H, g.mean(), float((g >= 250).mean() * 100)))

    wm = build_wire_mask(g)
    std = std_map(g)

    # ── ① 遮罩诊断: 网格打印 std 与"被遮掉的比例", 看左下/右侧是不是被误遮 ──
    nb, ns = 4, 12
    print("\n① 网格诊断 (每格: std均值 / 被遮罩%)   ★=std≥18 的候选大片")
    print("       " + " ".join("%12s" % ("c%d" % (i + 1)) for i in range(ns)))
    for bi in range(nb):
        y_a, y_b = bi * H // nb, (bi + 1) * H // nb
        cells = []
        for si in range(ns):
            x_a, x_b = si * W // ns, (si + 1) * W // ns
            blk = std[y_a:y_b, x_a:x_b]
            msk = wm[y_a:y_b, x_a:x_b]
            v = float(blk.mean())
            cov = 100.0 * float((msk > 0).mean())
            mark = "★" if v >= 18 else " "
            cells.append("%s%5.1f/%2.0f%%" % (mark, v, cov))
        print("   y%3d-%3d " % (y_a, y_b) + " ".join("%12s" % c for c in cells))
    print("   全程被遮 %.1f%%" % (100.0 * (wm > 0).mean()))

    # ── ② 区域级检测: 平滑 std → 阈值 → 只按面积筛(不看圆度) ──
    base = float(np.median(std))
    mad = float(np.median(np.abs(std - base))) or 1.0
    zn = (std - base) / (1.4826 * mad)
    sm = cv2.GaussianBlur(zn, (31, 31), 0)      # 大核平滑: "一大片"才响应, 单点亮斑被摊平
    print("\n② 区域级: std 基线 %.1f, 平滑后 z 分布 p50=%.2f p90=%.2f p99=%.2f"
          % (base, float(np.percentile(sm, 50)), float(np.percentile(sm, 90)),
             float(np.percentile(sm, 99))))

    results = {}
    for name, use_wm in (("不排除任何区域", False), ("排除识别到的接线", True)):
        zz = sm.copy()
        if use_wm:
            zz[wm > 0] = -99
        thr = float(np.percentile(zz, 80))      # 取最高的 20% 作种子(大片会被大核平滑, 阈值太严会漏)
        mask = (zz >= max(thr, 1.0)).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 15)))
        n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        regs = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            frac = 100.0 * area / (W * H)
            if frac < 1.5:                     # 只报占地 >=1.5% 的"一大片"
                continue
            sub = sm[y:y + h, x:x + w]
            m = (lab[y:y + h, x:x + w] == i)
            regs.append({"xywh": [int(x), int(y), int(w), int(h)], "area_pct": round(frac, 1),
                         "z_mean": round(float(sub[m].mean()), 2),
                         "z_max": round(float(sub[m].max()), 2),
                         "pos": ("左" if x + w / 2 < W / 3 else "右" if x + w / 2 > 2 * W / 3 else "中")
                                + ("上" if y + h / 2 < H / 3 else "下" if y + h / 2 > 2 * H / 3 else "中")})
        regs.sort(key=lambda d: -d["area_pct"])
        results[name] = regs
        print("\n   [%s] 占地≥2%% 的大片 %d 个:" % (name, len(regs)))
        for r in regs[:8]:
            print("      %-6s xywh=%-22s 占地%5.1f%%  z均值%5.2f  z峰%5.2f"
                  % (r["pos"], str(r["xywh"]), r["area_pct"], r["z_mean"], r["z_max"]))

    use = results["不排除任何区域"] or results["排除识别到的接线"]
    if not use:
        print("\n⚠️ 两种都没检出 >=2% 的大片")

    # ── ③ 出图: 原图 + 大片框 + 热图 ──
    S = 2
    big = cv2.resize(crop, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    for i, r in enumerate(use[:6], 1):
        x, y, w, h = r["xywh"]
        cv2.rectangle(big, (x * S, y * S), ((x + w) * S, (y + h) * S), (0, 0, 255), 4)
        cv2.putText(big, "#%d %s %.1f%% z%.1f" % (i, r["pos"], r["area_pct"], r["z_mean"]),
                    (x * S + 4, max(30, y * S + 32)), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2)
    hm = cv2.applyColorMap(cv2.normalize(sm, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
                           cv2.COLORMAP_JET)
    hm = cv2.resize(hm, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    for i, r in enumerate(use[:6], 1):
        x, y, w, h = r["xywh"]
        cv2.rectangle(hm, (x * S, y * S), ((x + w) * S, (y + h) * S), (255, 255, 255), 3)
        cv2.putText(hm, "#%d" % i, (x * S + 4, max(30, y * S + 32)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    p1 = os.path.join(OUTD, "surface_regions_%s.jpg" % stamp)
    p2 = os.path.join(OUTD, "surface_regions_heat_%s.jpg" % stamp)
    cv2.imwrite(p1, big, [cv2.IMWRITE_JPEG_QUALITY, 93])
    cv2.imwrite(p2, hm, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("\n③ 出图 → %s ; 热图 → %s" % (os.path.relpath(p1, ROOT), os.path.relpath(p2, ROOT)))

    rec = {"ts": stamp, "expo": expo, "roi_hw": [W, H],
           "wire_masked_pct": round(100.0 * (wm > 0).mean(), 2),
           "regions_with_wire_filter": results["排除识别到的接线"],
           "regions_no_filter": results["不排除任何区域"], "jpg": p1, "heat_jpg": p2}
    with open(os.path.join(ROOT, "data/memory/l2_regions_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("④ 已记入 data/memory/l2_regions_log.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
