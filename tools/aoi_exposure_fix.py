#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_exposure_fix.py — 原始图过曝切除 + 自裁判据图 (2026-09-24 老倪现场发现)

老倪: 「灰度信息丢失(过曝): 图像底部亮度到上限(255 纯白), 明暗细节/纹理/衬度完全消失, 一片死白;
       渐变过渡异常: 向下过渡时亮度没有自然线性衰减, 底部出现急剧亮度抬升 (Cliff edge);
       这是拉伸后的图像; 你要将原始图像过曝光的部分, 去掉」

实测 (真拍 10082 金手指, 2026-09-24):
  · 工控机给的拉伸图 (?kind=topview 960x960): y≥255 起 mean 恒在 238.5±0.5, 饱和像素(≥250)占比 **88%**,
    过曝行 705/960 = **73%** → 一片死白, 细节为零 ⇒ **不能直接喂任务头**
  · 原始图 (?kind=origin 2448x2048): 过曝带 y 592~1184 (sat>30%, 453 行), 最陡跳变 y=589 (12.1/行)
    金手指条 (边缘密集) 实测 y 948~1147 (200 行, sat 34~38% = 金面镜反光, 可接受)
  ⇒ 处置: **不用工控机的固定窗拉伸图, 改用原始图自裁**: 先切掉过曝带, 只保留金手指条 → 判据图。
     口径 (sat≤40%, 边缘密集, 高≥20 行) 与训练数据保持一致。

用法:
  from aoi_exposure_fix import clean_judge_frame, analyze
  clean, meta = clean_judge_frame(origin_rgb, out=960)   # 判据图 (无死白)
  st = analyze(origin_rgb)                               # 只诊断不移臂/不改图
"""
from __future__ import annotations

import os

import numpy as np

SAT_LEVEL = 250          # 判"饱和像素"的灰度门限 (255 上限下的实际死白线)
K_DEFAULT = 2.0          # 🎯 拉长倍数 (老倪 2026-09-24: 先说拉长三倍, 随即改口径 → **拉长 2 倍**)
                         #    口径: **只把短边拉 k 倍, 长边保持原样** (不再拉成方图/8~13 倍)
DEF = {
    "sat_thr": 0.40,     # 保留带允许的饱和像素占比上限 (金面镜反光 ~0.35 可过, 死白带 0.6+ 必须切)
    "edge_pct": 92,      # 边缘密集判定分位 (行 |gx| 均值)
    "min_h": 20,         # 条带最小高度 (行)
    "merge_gap": 6,      # 空隙 ≤ 该行数则合并成一条
    "pad": 8,            # 条带上下各留几行余量
    "cliff_win": 15,     # 检测 cliff 的滑窗 (行)
}


def _gray(rgb):
    a = np.asarray(rgb)
    if a.ndim == 3:
        g = (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2])
    else:
        g = a.astype(np.float32)
    return g.astype(np.float32)


def row_stats(rgb) -> dict:
    """逐行: 灰度均值 / 饱和占比 / 边缘密度(|gx| 均值)。"""
    import cv2
    g = _gray(rgb)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0))
    return {"mean": g.mean(axis=1), "sat": (g >= SAT_LEVEL).mean(axis=1),
            "edge": gx.mean(axis=1), "H": g.shape[0], "W": g.shape[1],
            "sat_all": float((g >= SAT_LEVEL).mean()), "mean_all": float(g.mean())}


def col_stats(rgb) -> dict:
    """逐列: 饱和占比 / 边缘密度 — 用于把条带左右端裁到"自己的 x 范围"。

    ⚠️ 实测坑 (2026-09-24): 只做行裁切时, 原始图右侧那片亮区会被带进画面 →
    裁后图**最右 10 列饱和占比 100%** (看着还是死白)。必须同时裁 x。
    """
    import cv2
    g = _gray(rgb)
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    return {"sat": (g >= SAT_LEVEL).mean(axis=0), "edge": gy.mean(axis=0),
            "H": g.shape[0], "W": g.shape[1]}


def trim_x(rgb, sat_thr: float = 0.60, min_w_frac: float = 0.20, merge_gap: int = 24):
    """把画面按列裁到"非过曝"的 x 范围 (左右那两片死白切掉)。返回 (x0, x1, meta)。"""
    cs = col_stats(rgb)
    ok = cs["sat"] <= sat_thr
    runs = [r for r in _runs(ok, merge_gap) if (r[1] - r[0] + 1) >= int(cs["W"] * min_w_frac)]
    if not runs:
        return 0, cs["W"], {"trimmed": False, "why": "没有合格列区间 → 保持全宽 (如实记录)",
                            "col_sat_max": round(float(cs["sat"].max()), 3)}
    best = max(runs, key=lambda r: (r[1] - r[0]))
    return best[0], best[1] + 1, {"trimmed": True, "x_span": [best[0], best[1] + 1],
                                  "dropped_cols": [0, best[0]] if best[0] else [],
                                  "col_sat_before_max": round(float(cs["sat"].max()), 3)}


def find_cliff(prof: dict) -> dict:
    """找"急剧亮度抬升"(Cliff edge): 滑窗内最大正跳变。"""
    d = np.diff(prof["mean"])
    w = DEF["cliff_win"]
    if len(d) <= w:
        return {"y": -1, "jump": 0.0}
    k = int(np.argmax(np.convolve(d, np.ones(w), "valid")))
    return {"y": k, "jump": float(d[k:k + w].mean())}


def stretch_short(rgb, k: float = K_DEFAULT):
    """**只把短边拉 k 倍** (长边不动) —— 金手指条不再被拉成方图。返回 (图, meta_k)。"""
    import cv2
    a = np.asarray(rgb)
    h, w = a.shape[:2]
    if k is None or abs(float(k) - 1.0) < 1e-6:
        return a, {"k": 1.0, "axis": "none", "out_hw": [h, w], "in_hw": [h, w],
                   "stretch_desc": "无拉长 (×1.0)"}
    if h <= w:
        out = (w, max(1, int(round(h * float(k)))))
        axis = "h"
    else:
        out = (max(1, int(round(w * float(k)))), h)
        axis = "w"
    img = cv2.resize(a, out, interpolation=cv2.INTER_CUBIC)
    _short_in, _short_out = (h, out[1]) if axis == "h" else (w, out[0])
    return img, {"k": round(float(k), 2), "axis": axis, "out_hw": [out[1], out[0]],
                 "stretch_desc": (f"短边{'高' if axis == 'h' else '宽'} {_short_in}→{_short_out} "
                                  f"(×{float(k):.1f}) · 长边不动"),
                 "in_hw": [h, w]}


def _runs(mask, merge_gap):
    out, cur = [], None
    for y, m in enumerate(mask):
        if m:
            cur = [y, y] if cur is None else [cur[0], y]
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    merged = []
    for r in out:
        if merged and r[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = r[1]
        else:
            merged.append([r[0], r[1]])
    return merged


def analyze(rgb) -> dict:
    """只诊断: 过曝带 / cliff / 金手指条候选 / 打分 (不动图)。"""
    prof = row_stats(rgb)
    cliff = find_cliff(prof)
    thr = float(np.percentile(prof["edge"], DEF["edge_pct"]))
    bands = [r for r in _runs(prof["edge"] >= thr, DEF["merge_gap"]) if r[1] - r[0] + 1 >= DEF["min_h"]]
    sat_bands = [r for r in _runs(prof["sat"] > DEF["sat_thr"], DEF["merge_gap"]) if r[1] - r[0] + 1 >= 8]
    cands = []
    for a, b in bands:
        s = float(prof["sat"][a:b + 1].mean())
        e = float(prof["edge"][a:b + 1].mean())
        cands.append({"y0": a, "y1": b, "h": b - a + 1, "sat": round(s, 3), "edge": round(e, 2),
                      "ok": s <= DEF["sat_thr"]})
    return {"H": prof["H"], "W": prof["W"], "sat_all": round(prof["sat_all"], 4),
            "mean_all": round(prof["mean_all"], 1), "cliff": cliff,
            "sat_bands": sat_bands, "gold_candidates": cands,
            "verdict": ("overexposed" if prof["sat_all"] > 0.10 else "ok")}


def clean_judge_frame(rgb, out: int | None = None, sat_thr: float | None = None, pad: int | None = None,
                      return_natural: bool = False, k: float = K_DEFAULT):
    """原始图 → **无过曝判据图**: 切掉死白带, 只保留金手指条, 归一化到 out×out (可另返原比例版)。

    返回 (clean_rgb, meta)。meta 如实记录: 切掉了多少过曝行、切前/切后饱和占比、保留行区间、cliff。
    找不到合格条带时**如实返回 None** (不硬裁一张错的)。
    """
    import cv2
    sat_thr = DEF["sat_thr"] if sat_thr is None else sat_thr
    pad = DEF["pad"] if pad is None else pad
    prof = row_stats(rgb)
    a = analyze(rgb)
    ok = [c for c in a["gold_candidates"] if c["sat"] <= sat_thr]
    if not ok:
        return None, {"ok": False, "err": "没有找到未过曝的金手指条带 (全图都可能过曝)",
                      "sat_all": a["sat_all"], "analyze": a}
    # 取"边缘最密"的合格条带 (金手指焊盘行)
    best = max(ok, key=lambda c: c["edge"])
    y0 = max(0, best["y0"] - pad)
    y1 = min(prof["H"], best["y1"] + 1 + pad)
    band = np.asarray(rgb)[y0:y1]
    # ② 列方向也裁: 切掉左右死白片 (只做行裁切会留 100% 饱和的边列, 实测坑)
    x0, x1, xmeta = trim_x(band)
    band = band[:, x0:x1]
    sat_dropped = int((prof["sat"] > sat_thr).sum())
    if out:                                    # 兼容旧口径: 显式给 out 才拉成 out×out 方图
        clean = cv2.resize(band, (int(out), int(out)), interpolation=cv2.INTER_CUBIC)
        kmeta = {"k": None, "axis": "square", "out_hw": [int(out), int(out)]}
    else:                                      # 🎯 默认: 只把短边拉 k 倍 (老倪口径)
        clean, kmeta = stretch_short(band, k)
    meta = {"ok": True, "kept_rows": [y0, y1], "kept_h": y1 - y0, "src_h": prof["H"], "src_w": prof["W"],
            "dropped_sat_rows": sat_dropped, "dropped_pct": round(sat_dropped / prof["H"] * 100, 1),
            "sat_before": round(a["sat_all"], 4), "sat_after": round(float((_gray(clean) >= SAT_LEVEL).mean()), 4),
            "cliff": a["cliff"], "candidate": best, "out": list(clean.shape[:2])[::-1],
            **kmeta,
            "x_trim": xmeta,
            "col_sat_after_max": round(float((_gray(clean) >= SAT_LEVEL).mean(axis=0).max()), 3),
            "rule": f"sat≤{sat_thr} 且 边缘密集(P{DEF['edge_pct']}) 且 高≥{DEF['min_h']}行, 上下留 {pad} 行"}
    if return_natural:
        meta["natural"] = band
    return clean, meta




# ═══════════════════════════════════════════════════════════════════════════════════════════
# 🔲 2026-10-12 老倪: 「判据图还在跳变, 上边和下面少了一小部分; 为什么反而更模糊?
#    你先从整板原图上, 把矩形区域要截取的部分, 画出边界框」
#   ⇒ 旧的取景口径 = 『边缘密度 P92 的密集带 + 上下各 pad=8 行』, 实测把真实金手指切掉
#     上边 11 行 / 下边 32 行(整板 1400x1171 坐标); 而且 x 用全宽(含 37% 无金手指背景),
#      真正的金手指只占宽度 ~63% ⇒ 背景白占像素, 判据图被挤糊。
#   新口径 gold_roi(): **两道独立证据**定 ROI(不依赖亮度/边缘密度) ——
#     · 行: 逐行数『焊盘亮块』(宽 6~40px 的亮段) 个数 ≥ gold_min_cnt 的**最长连续段**;
#     · 列: 该行段内 『焊盘亮块列』 ∪ 『金色列(R>G 且 G>B 的暖色像素)』 的跨度;
#     · 四周各留 margin_frac 比例的小余量(默认 1.0%, 最少 6px)。
#   找不到就如实返回 None, 由调用方回落旧口径 —— 绝不在一张没对准的帧上硬裁。
_GOLD_DEF = {"w_min": 6, "w_max": 40, "cnt_min": 6, "margin_frac": 0.010, "margin_min": 6,
             "gold_min": 40, "min_rows": 8}


def _blob_spans(row, thr, w_min=6, w_max=40):
    """一行里宽度在 [w_min, w_max] 的亮段(焊盘量级)"""
    ok = row > thr
    out, st = [], None
    for i, v in enumerate(ok):
        if v and st is None:
            st = i
        elif not v and st is not None:
            if w_min <= i - st <= w_max:
                out.append((st, i))
            st = None
    if st is not None and w_min <= len(ok) - st <= w_max:
        out.append((st, len(ok)))
    return out


def gold_roi(rgb, margin_frac=None, cnt_min=None, gold_min=None, max_grow=2.5):
    """真实金手指 ROI = (x0, y0, x1, y1) + info。两道证据, **锚 + 扩** 两级(2026-10-12 实测):
      · 锚 = 『竖直边缘密度』最强的连续带(与判据图旧口径同源, 逐帧实测只抖 ±1px —— 它历来稳);
      · 扩 = 从锚向上下按**金色证据**(R>100 且 R-B>35 且 R>=G 且 G-B>15)向外扩, 容忍 3 行空洞,
             硬上限 max_grow×锚高 ⇒ 把被旧口径切掉的真金手指补回来, 但不会被别的亮结构带跑
             (纯 blob 口径在产线帧上实测抖 324 行, 不可用 ⇒ 只当兜底证据)。
      · 列 = 齿排行内 『金色列』 ∪ 『焊盘亮块列』, 1%/99% 分位抗噪 + 小余量;
      · 余量 = 上下 max(6, 高*4*margin_frac) px, 左右 max(6, 宽*margin_frac) px。
    检测不到返回 (None, info) —— 调用方回落旧口径, 绝不硬裁。"""
    import cv2
    a = np.asarray(rgb)
    d = dict(_GOLD_DEF)
    if margin_frac is not None:
        d["margin_frac"] = margin_frac
    if cnt_min is not None:
        d["cnt_min"] = cnt_min
    if gold_min is not None:
        d["gold_min"] = gold_min
    H, W = a.shape[:2]
    g = _gray(a).astype(np.float32)
    if a.ndim == 3:                                    # 约定: 传进来的就是 RGB(clean_judge_frame 同口径)
        R, G, B = a[:, :, 0].astype(np.int16), a[:, :, 1].astype(np.int16), a[:, :, 2].astype(np.int16)
    else:
        R = G = B = g.astype(np.int16)
    gold = (R > 100) & ((R - B) > 35) & (R >= G) & ((G - B) > 15)
    gold_row = gold.sum(axis=1)

    # ① 锚: 竖直边缘密度最强带(稳定)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
    ed = cv2.GaussianBlur(gx.mean(axis=1).reshape(-1, 1), (1, 9), 0).ravel()
    pk = int(np.argmax(ed))
    base = {"evidence": "edge-anchor ∪ gold-expand", "src_wh": [int(W), int(H)],
            "edge_pk": round(float(ed[pk]), 2), "gold_px": int(gold.sum())}
    if ed[pk] <= 4.0:
        return None, dict(base, why="画面里找不到齿排(竖直边缘能量=%.1f)" % ed[pk])
    thr = 0.45 * float(ed[pk])
    ya0 = ya1 = pk
    while ya0 > 0 and ed[ya0 - 1] > thr:
        ya0 -= 1
    while ya1 < H - 1 and ed[ya1 + 1] > thr:
        ya1 += 1
    if ya1 - ya0 < 8:
        return None, dict(base, why="锚带太薄(%d 行)" % (ya1 - ya0))

    # ② 从锚向外按金色证据扩(容忍 3 行空洞, 硬上限 max_grow×锚高)
    gmin = max(int(d["gold_min"]), int(round(0.004 * W)))
    ev = gold_row >= gmin
    if not ev[ya0:ya1 + 1].any():                      # 锚带里没有金色 ⇒ 退回锚本身 + 小 pad
        y0, y1 = ya0, ya1
        note = "锚带内无金色证据 ⇒ 只用锚带"
    else:
        lim = int(max_grow * (ya1 - ya0 + 1))
        y0, gap = ya0, 0
        while y0 > 0 and (ya1 - y0) < lim + (ya1 - ya0):
            if ev[y0 - 1]:
                y0 -= 1
                gap = 0
            else:
                gap += 1
                if gap > 3:
                    break
                y0 -= 1
        if not ev[y0]:
            y0 = ya0
        y1, gap = ya1, 0
        while y1 < H - 1 and (y1 - y0) < lim + (ya1 - ya0):
            if ev[y1 + 1]:
                y1 += 1
                gap = 0
            else:
                gap += 1
                if gap > 3:
                    break
                y1 += 1
        if not ev[y1]:
            y1 = ya1
        note = "锚带 y%d~%d + 金色扩到 y%d~%d" % (ya0, ya1, y0, y1)

    # ③ 列证据: 齿排行内 金色列 ∪ 焊盘亮块列
    cols = np.zeros(W, np.float32)
    for y in range(y0, y1 + 1):
        row = g[y]
        bg = float(np.median(row))
        hi = float(np.percentile(row, 97))
        t2 = bg + 0.45 * max(6.0, hi - bg)
        for (s0, e0) in _blob_spans(row, t2, d["w_min"], d["w_max"]):
            cols[s0:e0] += 1.0
    bcol = np.where(cols > 0)[0]
    gcol = np.where(gold[y0:y1 + 1].sum(axis=0) >= max(6, int(0.15 * (y1 - y0 + 1))))[0]
    if len(bcol) == 0 and len(gcol) == 0:
        x0, x1 = 0, W
        note += " · 无列证据 ⇒ 全宽"
    else:
        if len(bcol):
            x0, x1 = int(np.percentile(bcol, 1)), int(np.percentile(bcol, 99)) + 1
        else:
            x0, x1 = int(gcol.min()), int(gcol.max()) + 1
        if len(gcol):                                  # 金色证据并集(更保守地往外)
            x0 = min(x0, int(gcol.min()))
            x1 = max(x1, int(gcol.max()) + 1)

    my = max(int(d["margin_min"]), int(round((y1 - y0) * d["margin_frac"] * 4)))
    mx = max(int(d["margin_min"]), int(round((x1 - x0) * d["margin_frac"])))
    x0, x1 = max(0, int(x0) - mx), min(W, int(x1) + mx)
    y0, y1 = max(0, int(y0) - my), min(H, int(y1) + my)
    if x1 - x0 < 40 or y1 - y0 < 12:
        return None, dict(base, why="ROI 太小(%dx%d)" % (x1 - x0, y1 - y0))
    info = dict(base, note=note, anchor=[int(ya0), int(ya1)],
                pad_rows=[int(y0), int(y1)], pad_cols=[int(x0), int(x1)],
                pad_wh=[int(x1 - x0), int(y1 - y0)],
                gold_cols=[int(gcol.min()), int(gcol.max()) + 1] if len(gcol) else None,
                blob_cols=[int(bcol.min()), int(bcol.max()) + 1] if len(bcol) else None,
                margin_px=[int(mx), int(my)])
    return (int(x0), int(y0), int(x1), int(y1)), info





def clean_gold_frame(rgb, return_natural=True, margin_frac=None):
    """金手指判据图**新裁剪口径**: 只留真实金手指 ROI(不切上下、不缩放/不拉伸)。
    返回 (band_rgb, meta); 找不到 ROI 返回 (None, meta) 由调用方回落。"""
    roi, info = gold_roi(rgb, margin_frac=margin_frac)
    meta = {"ok": roi is not None, "roi_mode": "pads+gold", **info}
    if roi is None:
        return None, meta
    x0, y0, x1, y1 = roi
    band = np.asarray(rgb)[y0:y1, x0:x1]
    meta.update({"roi": [int(x0), int(y0), int(x1), int(y1)], "roi_wh": [int(x1 - x0), int(y1 - y0)]})
    if return_natural:
        meta["natural"] = band
    return band, meta



def stretch_rect(rgb, rect, out: int | None = None, k: float = K_DEFAULT):
    """**把用户框选的矩形拉伸成判据图** (老倪 2026-09-24: "我拖出边界框圈出矩形, 你来将圈选矩形对应拉伸")。

    rect = (x0, y0, x1, y1) —— 原始图像素坐标 (可以是画面上拖出来的框)。
    返回 (stretched_rgb, meta)。meta 如实给出**框内**的过曝/细节指标, 让"白不白"有数可依。
    """
    import cv2
    a = np.asarray(rgb)
    H, W = a.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in rect[:4]]
    x0, x1 = max(0, min(x0, x1)), min(W, max(x0, x1))
    y0, y1 = max(0, min(y0, y1)), min(H, max(y0, y1))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None, {"ok": False, "err": f"框太小 ({x1-x0}x{y1-y0}px), 至少 4x4", "rect": [x0, y0, x1, y1]}
    crop = a[y0:y1, x0:x1]
    g = _gray(crop)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0))
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    if out:
        img = cv2.resize(crop, (int(out), int(out)), interpolation=cv2.INTER_CUBIC)
        kmeta = {"k": None, "axis": "square", "out_hw": [int(out), int(out)]}
    else:
        img, kmeta = stretch_short(crop, k)
    meta = {"ok": True, "mode": "manual_rect", "rect": [x0, y0, x1, y1], "rect_wh": [x1 - x0, y1 - y0],
            "src_hw": [H, W], "out": list(img.shape[:2])[::-1], **kmeta,
            "sat_in_rect": round(float((g >= SAT_LEVEL).mean()), 4),
            "deadwhite_rows_in_rect": int((g.mean(axis=1) > 235).sum()),
            "mean_in_rect": round(float(g.mean()), 1), "std_in_rect": round(float(g.std()), 1),
            "tenengrad_in_rect": round(float((gx * gx + gy * gy).mean()), 0),
            "warning": ("框内过曝严重 (饱和>40%): 拉伸后仍会一片白, 建议缩小/上移框" 
                        if float((g >= SAT_LEVEL).mean()) > 0.40 else "")}
    return img, meta


def load_roi(path: str):
    """读回记住的框选 ROI (跨帧/跨会话复用)。"""
    try:
        import json
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        r = d.get("rect")
        return tuple(int(v) for v in r) if r and len(r) == 4 else None
    except Exception:                                                  # noqa: BLE001
        return None


def save_roi(path: str, rect, extra: dict | None = None) -> bool:
    import json
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"rect": [int(v) for v in rect], "saved_iso": __import__("time").strftime("%F %T"),
                       **(extra or {})}, f, ensure_ascii=False, indent=1)
        return True
    except Exception:                                                  # noqa: BLE001
        return False


if __name__ == "__main__":
    import sys
    import cv2
    p = sys.argv[1] if len(sys.argv) > 1 else ""
    if not p:
        print(__doc__); raise SystemExit(0)
    bgr = cv2.imread(p)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    a = analyze(rgb)
    print("诊断:", {k: v for k, v in a.items() if k != "gold_candidates"})
    for c in a["gold_candidates"]:
        print("  条带候选:", c)
    _k = float(sys.argv[2]) if len(sys.argv) > 2 else K_DEFAULT
    clean, meta = clean_judge_frame(rgb, k=_k)          # 默认只拉短边 3 倍
    print("裁切:", {k: v for k, v in meta.items() if k not in ("natural", "candidate")})
    print(f"→ 拉长口径: {meta.get('stretch_desc')}")
    if clean is not None:
        o = p.replace(".png", f"_clean_k{_k:g}.png")
        cv2.imwrite(o, cv2.cvtColor(clean, cv2.COLOR_RGB2BGR))
        print("→", o)
