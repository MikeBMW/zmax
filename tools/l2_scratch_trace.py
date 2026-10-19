#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_scratch_trace.py — 以老倪指认的种子(12号 [520,79,78,9])为起点, 把整条划痕追出来

为什么之前只画了一小段: 连通域是按"当前对比度连续"切的, 一条长划痕只要中间有一处
  反光/亮度过渡就会断成 5~8 段, 于是把最亮那段当成了整条 (12号 78px)。
  实际情况: 划痕非常长, 横跨模块大部分宽度。

做法 (沿方向积分, 不靠单点连通):
  ① 取种子所在的行带 y±(h/2+pad)
  ② 在带内对每一列 x 求「垂直方向梯度最大值」—— 水平划痕在垂直方向必然有强边
  ③ 得到 profile[x] → 按稳健阈值切成连续段 → 段间小空隙合并
  ④ 取包含种子的那一段 = 整条划痕的起止 x, 长度 = x2-x1
  ⑤ 出图: 整条划痕框 + 起止刻度 + 长度标注; 另出纵向/斜向扫描以免漏掉别的方向
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

from aoi_surface_rect import surface_roi                        # noqa: E402
from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality  # noqa: E402

OUTD = os.path.join(ROOT, "data/deliver")
SEED = [520, 79, 78, 9]          # 老倪: 12号最严重


def get_crop():
    sq = SurfaceOpticalQuality()
    expo = sq.exposure()
    im = sq.capture(grab=True)
    if im is None:
        return None, None, None
    rect, meta = surface_roi(im)
    if rect is None:
        return None, expo, meta.get("why")
    cx, cy = float(rect["cx"]), float(rect["cy"])
    w, h, ang = float(rect["w"]), float(rect["h"]), float(rect["angle"])
    if w < h:
        w, h, ang = h, w, ang + 90.0
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(im, M, (im.shape[1], im.shape[0]), flags=cv2.INTER_CUBIC)
    return cv2.getRectSubPix(rot, (int(round(w)), int(round(h))), (cx, cy)), expo, rect


def trace_horizontal(g, seed, pad=7, gap_merge=45):
    """沿水平方向追划痕: 行带内逐列取垂直梯度峰值, 阈值分割后合并小空隙。"""
    x0, y0, sw, sh = seed
    H, W = g.shape[:2]
    y1 = max(0, y0 - pad)
    y2 = min(H, y0 + sh + pad)
    band = g[y1:y2, :].astype(np.float32)
    # 垂直梯度(Sobel y) —— 水平走向的划痕上下沿都有强边
    gy = np.abs(cv2.Sobel(band, cv2.CV_32F, 0, 1, ksize=3))
    prof = gy.max(axis=0)                      # 每列的最大垂直梯度
    med = float(np.median(prof))
    mad = float(np.median(np.abs(prof - med))) or 1.0
    z = (prof - med) / (1.4826 * mad)
    strong = z >= 2.0                          # 比 3.0 松一档, 长划痕中段对比会掉

    # 只在种子附近±(模块宽)范围找, 避免把别处的纹理连进来
    lo = max(0, x0 - int(1.2 * W))
    hi = min(W, x0 + sw + int(1.2 * W))
    seg = np.zeros(W, dtype=bool)
    seg[lo:hi] = strong[lo:hi]
    # 合并小空隙
    xs = np.where(seg)[0]
    if len(xs) == 0:
        return None
    merged = []
    s = xs[0]
    p = xs[0]
    for x in xs[1:]:
        if x - p <= gap_merge:
            p = x
        else:
            merged.append((s, p))
            s = x
            p = x
    merged.append((s, p))
    # 取覆盖种子的那一段
    pick = None
    for a, b in merged:
        if a <= x0 + sw / 2 <= b:
            pick = (a, b)
            break
    if pick is None:
        pick = max(merged, key=lambda ab: ab[1] - ab[0])
    return {"x1": int(pick[0]), "x2": int(pick[1]), "len": int(pick[1] - pick[0] + 1),
            "band_y": [int(y1), int(y2)], "n_segments": len(merged),
            "segments": [[int(a), int(b)] for a, b in merged[:8]],
            "prof_z_max": round(float(z[lo:hi].max()), 2)}


def trace_hough(g, seed=None, min_len=60, max_gap=60, edge_skip=8):
    """HoughLinesP 追整条划痕 —— 关键在 maxLineGap 足够大, 它能跨过亮度断点把线段接起来。
    划痕本身是**直线**, 连通域法会按对比度断开, Hough 按共线接续 ⇒ 这才是量长划痕的正路。"""
    x0, y0, sw, sh = seed if seed else (0, 0, 1, 1)   # seed=None 时只走全自动分支, 不用这些值
    gx = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 4)).apply(g)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    chans = {"dark": cv2.morphologyEx(gx, cv2.MORPH_BLACKHAT, ker),
             "bright": cv2.morphologyEx(gx, cv2.MORPH_TOPHAT, ker)}
    best = None
    all_lines = []
    for cname, plane in chans.items():
        for ksz in (41, 101):
            lk = cv2.getStructuringElement(cv2.MORPH_RECT, (ksz, 1))   # 水平长核: 强化水平划痕
            enh = cv2.morphologyEx(plane, cv2.MORPH_CLOSE, lk)
            e8 = cv2.normalize(enh, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            _, bw = cv2.threshold(e8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            lines = cv2.HoughLinesP(bw, 1, np.pi / 180, threshold=25,
                                    minLineLength=min_len, maxLineGap=max_gap)
            if lines is None:
                continue
            for L in lines:
                _arr = [int(v) for v in np.asarray(L).reshape(-1)[:4]]   # cv5 返回 (N,4), cv4 是 (N,1,4)
                if len(_arr) < 4:
                    continue
                x1, y1, x2, y2 = _arr
                ln = float(np.hypot(x2 - x1, y2 - y1))
                if ln < min_len:
                    continue
                ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
                # 排除贴边棱线: 模块上下沿是横贯整宽的强边, 永远比真划痕长, 不排掉必被当成划痕
                #   (实测 y=0 长985 / y=186 长1094 都排在真划痕 y=93 长830 之前)
                H_ = g.shape[0]
                seg_y_raw = (y1 + y2) / 2.0
                if seg_y_raw <= edge_skip or seg_y_raw >= H_ - edge_skip:
                    continue
                all_lines.append({"ch": cname, "k": ksz, "p": [x1, y1, x2, y2],
                                  "len": round(ln, 1), "ang": round(ang, 1)})
                # 挑覆盖种子的那条 (seed=None 时取最长, 全自动)
                seg_y = seg_y_raw
                in_band = True if seed is None else (abs(seg_y - (y0 + sh / 2.0)) <= max(12, sh))
                seg_x1, seg_x2 = min(x1, x2), max(x1, x2)
                covers = True if seed is None else (seg_x1 - max_gap <= (x0 + sw / 2.0) <= seg_x2 + max_gap)
                if in_band and covers and (best is None or ln > best["len"]):
                    best = {"ch": cname, "k": ksz, "p": [x1, y1, x2, y2], "len": round(ln, 1),
                            "ang": round(ang, 1), "x1": seg_x1, "x2": seg_x2,
                            "y_mid": round(seg_y, 1)}
    all_lines.sort(key=lambda d: -d["len"])
    return best, all_lines[:10]


def main():
    crop, expo, info = get_crop()
    if crop is None:
        print("❌ 取不到模块 ROI: %s" % info); return 1
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    H, W = g.shape[:2]
    print("曝光 %s | ROI %dx%d mean=%.1f 死白=%.2f%%"
          % (expo, W, H, g.mean(), float((g >= 250).mean() * 100)))
    if "--seed" in sys.argv:
        print("种子(老倪指认12号): xywh=%s\n" % SEED)

    use_seed = SEED if "--seed" in sys.argv else None
    print("模式: %s\n" % ("按老倪指认种子 %s 追" % SEED if use_seed else "全自动(排除棱线后取最长直线)"))
    best, top = trace_hough(g, use_seed)
    print("① Hough 共线接续(前 10 条最长直线):")
    for i, L in enumerate(top, 1):
        print("   #%-2d %-6s 核%-4d 长%-7.1f 角度%-7.1f p=%s" % (i, L["ch"], L["k"], L["len"], L["ang"], L["p"]))
    if best is None:
        print("\n❌ Hough 没找到覆盖种子的长直线"); 
        tr = trace_horizontal(g, SEED)
        if tr is None:
            return 1
        tr = dict(tr); tr["y_mid"] = (tr["band_y"][0] + tr["band_y"][1]) / 2.0
    else:
        tr = {"x1": best["x1"], "x2": best["x2"], "len": int(best["len"]),
              "y_mid": best["y_mid"], "band_y": [max(0, int(best["y_mid"]) - 9), int(best["y_mid"]) + 9],
              "ch": best["ch"], "ang": best["ang"], "p": best["p"]}
        print("\n   采用: %s 核%d 长%.0fpx 角度%.1f° 起止 x=%d→%d y≈%.0f"
              % (best["ch"], best["k"], best["len"], best["ang"], best["x1"], best["x2"], best["y_mid"]))
    print("\n② 完整长度 %d px (种子的 78px 只是其中一段, %.1fx)"
          % (tr["len"], tr["len"] / 78.0))

    # 真实尺寸: 模块长 1097px 对应光模块实际长度 ⇒ 给出 mm 换算(按模块标准长)
    for mm_total, name in ((49.0, "SFP+ 约49mm"), (56.5, "SFP28/QSFP 约56.5mm")):
        print("   若模块实际长 %.1fmm(%s) ⇒ 划痕约 %.1f mm (占模块长度 %.0f%%)"
              % (mm_total, name, mm_total * tr["len"] / W, 100.0 * tr["len"] / W))

    # 出图: 2x 放大 + 整条划痕框 + 起止虚线
    S = 2
    big = cv2.resize(crop, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    yb1, yb2 = tr["band_y"]
    cv2.rectangle(big, (tr["x1"] * S, yb1 * S), (tr["x2"] * S, yb2 * S), (0, 0, 255), 3)
    for xx in (tr["x1"], tr["x2"]):
        cv2.line(big, (xx * S, 0), (xx * S, H * S), (0, 255, 0), 2)
    cv2.arrowedLine(big, (tr["x1"] * S, (yb1 - 12) * S), (tr["x2"] * S, (yb1 - 12) * S), (0, 255, 255), 2, tipLength=0.02)
    cv2.putText(big, "scratch FULL length = %d px (%.0f%% of module)" % (tr["len"], 100.0 * tr["len"] / W),
                (max(6, tr["x1"] * S), max(30, (yb1 - 18) * S)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
    cv2.putText(big, "x1=%d" % tr["x1"], (tr["x1"] * S + 4, H * S - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(big, "x2=%d" % tr["x2"], (max(4, tr["x2"] * S - 110), H * S - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUTD, "surface_scratch_full_%s.png" % stamp)
    cv2.imwrite(p, big)
    print("\n② 出图 → %s (%dx%d)" % (os.path.relpath(p, ROOT), big.shape[1], big.shape[0]))

    # 单独出划痕条带放大图(看清纹理), 高度 3x
    band = crop[max(0, yb1 - 6):min(H, yb2 + 6), max(0, tr["x1"] - 10):min(W, tr["x2"] + 10)]
    if band.size:
        band_big = cv2.resize(band, (band.shape[1] * 3, band.shape[0] * 3), interpolation=cv2.INTER_NEAREST)
        p2 = os.path.join(OUTD, "surface_scratch_band_%s.png" % stamp)
        cv2.imwrite(p2, band_big)
        print("   划痕条带 3x → %s (%dx%d)" % (os.path.relpath(p2, ROOT), band_big.shape[1], band_big.shape[0]))

    rec = {"ts": stamp, "expo": expo, "roi_hw": [W, H], "seed": SEED, "trace": tr, "png": p,
           "len_px": tr["len"], "len_frac": round(tr["len"] / float(W), 4)}
    with open(os.path.join(ROOT, "data/memory/l2_scratch_trace.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("③ 已记入 data/memory/l2_scratch_trace.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
