#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_scratch_detect.py — 本机自检划痕 (不依赖工控机 YOLO 的类别表)

背景: 工控机 housing YOLO 只报出 housing_pit (凹坑, conf 0.473), 老倪目检说**表面有划痕**
  ⇒ 那个模型的类别表里没有划痕这一类 ⇒ 划痕必须本机自己检。

划痕的形态学特征 (和凹坑/污点的区别):
  · 细长: 长宽比高 (≥4), 面积小但延展长
  · 方向一致: 某一条线上灰度突变, 而不是各向同性斑点
  · 高对比: 相对局部背景要么明显暗(划入)要么明显亮(划出反光)

做法 (每一步都可复核, 不用 VLM 猜):
  ① 灰度 + CLAHE 压光照不均
  ② 黑帽(暗细线) + 顶帽(亮细线) 两个通道 —— 划痕在金属面上两种都可能
  ③ 4 方向线形核卷积, 取最大响应 (划痕有方向, 斑点没有)
  ④ 响应阈值(按稳健 z 分数) + 连通域 → 细长筛选
  ⑤ 出图: ROI 放大 + 划痕框 + 每条的 长/宽/长宽比/对比度/方向
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


def line_kernels(length=21):
    """4 个方向的线形核 — 划痕在某个方向上响应远大于其它方向。"""
    ks = {}
    for name, ang in (("h", 0), ("v", 90), ("d45", 45), ("d135", 135)):
        k = np.zeros((length, length), np.uint8)
        c = length // 2
        if ang == 0:
            k[c, :] = 1
        elif ang == 90:
            k[:, c] = 1
        else:
            idx = np.arange(-c, c + 1)
            if ang == 45:
                k[np.clip(c - idx, 0, length - 1), np.clip(c + idx, 0, length - 1)] = 1
            else:
                k[np.clip(c + idx, 0, length - 1), np.clip(c + idx, 0, length - 1)] = 1
        ks[name] = k
    return ks


def detect_scratch(crop, k_sigma=3.0, min_len=18, aspect_min=4.0, max_width=10,
                   min_width=2.0, min_contrast=40.0, edge_margin=3, max_aspect=80.0):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 4)).apply(g)
    # 暗细线 / 亮细线
    bh = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))

    kernels = line_kernels(21)
    resp = {}
    for ch_name, plane in (("dark", bh), ("bright", th)):
        best = np.zeros_like(plane, dtype=np.float32)
        best_dir = np.full(plane.shape, -1, dtype=np.int8)
        for i, (dn, k) in enumerate(kernels.items()):
            # 方向性开运算 ≈ 只保留该方向的细线
            opened = cv2.morphologyEx(plane, cv2.MORPH_OPEN, k)
            better = opened > best
            best[better] = opened[better]
            best_dir[better] = i
        resp[ch_name] = (best, best_dir)

    hits = []
    for ch_name, (r, rdir) in resp.items():
        med = float(np.median(r))
        mad = float(np.median(np.abs(r - med))) or 1.0
        z = (r - med) / (1.4826 * mad)
        mask = (z >= k_sigma).astype(np.uint8) * 255
        if mask.sum() == 0:
            continue
        # 方向性开运算保留细长结构, 再做连通域
        n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 25:
                continue
            sub = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
            cnts, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                continue
            csel = max(cnts, key=cv2.contourArea)
            if len(csel) < 5:            # minAreaRect 需要 >=5 点才稳
                continue
            (rcx, rcy), (rw, rh), rang = cv2.minAreaRect(csel)
            L, Wd = max(rw, rh), max(1.0, min(rw, rh))
            if L < min_len or Wd > max_width or Wd < min_width:
                continue
            # 排除贴边 (模块上下沿是棱线, 必产生超长高对比"线", 实测 930x12 aspect 77 那种)
            H_, W_ = g.shape[:2]
            if x <= edge_margin or y <= edge_margin or (x + w) >= W_ - edge_margin or (y + h) >= H_ - edge_margin:
                continue
            asp = L / Wd
            if asp < aspect_min or asp > max_aspect:
                continue
            roi_vals = g[y:y + h, x:x + w]
            contrast = float(roi_vals.max() - roi_vals.min())
            if contrast < min_contrast:      # 低对比的 1~2px 细线多为压缩/纹理伪影
                continue
            hits.append({"ch": ch_name, "xywh": [int(x), int(y), int(w), int(h)],
                         "len": round(float(L), 1), "wid": round(float(Wd), 1),
                         "aspect": round(float(asp), 2), "contrast": round(contrast, 1),
                         "angle": round(float(rang), 1),
                         "mean_z": round(float(z[y:y + h, x:x + w].max()), 2)})
    hits.sort(key=lambda d: (-d["aspect"], -d["len"]))
    return hits, g


def main():
    os.makedirs(OUTD, exist_ok=True)
    sq = SurfaceOpticalQuality()
    expo = sq.exposure()
    im = sq.capture(grab=True)
    if im is None:
        print("❌ 取帧失败"); return 1
    rect, meta = surface_roi(im)
    if rect is None:
        print("❌ 搜不到模块: %s" % meta.get("why")); return 1

    cx, cy = float(rect["cx"]), float(rect["cy"])
    w, h, ang = float(rect["w"]), float(rect["h"]), float(rect["angle"])
    if w < h:
        w, h, ang = h, w, ang + 90.0
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(im, M, (im.shape[1], im.shape[0]), flags=cv2.INTER_CUBIC)
    crop = cv2.getRectSubPix(rot, (int(round(w)), int(round(h))), (cx, cy))

    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sat = float((g >= 250).mean() * 100)
    print("曝光 %s | 模块 ROI %dx%d mean=%.1f 死白=%.2f%% 清晰度=%.1f"
          % (expo, crop.shape[1], crop.shape[0], g.mean(), sat,
             float(cv2.Laplacian(g, cv2.CV_64F).var())))

    hits, genh = detect_scratch(crop)
    print("\n划痕候选 %d 条 (长≥18px 宽2~10px 长宽比4~80 对比度≥40 且不贴边):" % len(hits))
    print("   %-6s %-22s %-7s %-7s %-7s %-8s %s" % ("通道", "xywh", "长", "宽", "长宽比", "对比度", "方向"))
    for hh in hits[:12]:
        print("   %-6s %-22s %-7.1f %-7.1f %-7.2f %-8.1f %.1f°"
              % (hh["ch"], str(hh["xywh"]), hh["len"], hh["wid"], hh["aspect"], hh["contrast"], hh["angle"]))

    # 出图: ROI 大图 + 标框
    S = 2 if crop.shape[1] <= 1200 else 1
    big = cv2.resize(crop, (crop.shape[1] * S, crop.shape[0] * S), interpolation=cv2.INTER_NEAREST)
    for i, hh in enumerate(hits[:12], 1):
        x, y, ww, hh2 = hh["xywh"]
        cv2.rectangle(big, (x * S, y * S), ((x + ww) * S, (y + hh2) * S), (0, 0, 255), 3)
        cv2.putText(big, "#%d" % i, (x * S, max(26, y * S - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 3)
    cv2.putText(big, "3000us sat=%.2f%% | scratch candidates=%d | x%d" % (sat, len(hits), S),
                (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUTD, "surface_scratch_%s.png" % stamp)
    cv2.imwrite(p, big)
    print("\n出图 → %s (%dx%d)" % (os.path.relpath(p, ROOT), big.shape[1], big.shape[0]))

    rec = {"ts": stamp, "expo": expo, "roi_hw": [int(crop.shape[1]), int(crop.shape[0])],
           "sat_pct": round(sat, 2), "n_hits": len(hits), "hits": hits[:12], "png": p}
    with open(os.path.join(ROOT, "data/memory/l2_scratch_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("已记入 data/memory/l2_scratch_log.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
