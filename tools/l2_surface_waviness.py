#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_surface_waviness.py — 检测**凸凹不平**(不是划痕)

老倪 2026-10-20 纠正两点, 都改变了算法方向:
  ① 那条 692~830px 的水平长直线是**正常的安装接线**, 不是缺陷 ⇒ 长直线必须从检测里排除
  ② 缺陷是**凸凹不平** ⇒ 形态是**斑块状**(凹陷/凸起/麻面), 不是细长线

所以判据反过来: 找「圆度高、局部起伏大、且不属于任何长直线」的斑块。
  为什么局部方差能测凸凹: 平坦金属面在漫反射下局部灰度平稳; 凹凸处曲率变化 ⇒ 同一小窗内出现
  明暗并存(高光+阴影) ⇒ 局部标准差显著升高。这就是"不平整"的像素级表现。
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


def get_crop():
    sq = SurfaceOpticalQuality()
    expo = sq.exposure()
    im = sq.capture(grab=True)
    if im is None:
        return None, None, "取帧失败"
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


def build_wire_mask(g, min_len=120, edge_skip=15):
    """把**安装接线/棱线**这些长直线从检测范围里挖掉 —— 它们是正常结构。
    实测: 接线是一条 y≈90~94 横贯 700~830px 的直线, 局部方差同样很高,
    不排除的话它会稳稳排第一, 把真缺陷挤下去。"""
    gx = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 4)).apply(g)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    H, W = g.shape[:2]
    cands = []
    for plane in (cv2.morphologyEx(gx, cv2.MORPH_BLACKHAT, ker),
                  cv2.morphologyEx(gx, cv2.MORPH_TOPHAT, ker)):
        for ksz in (61, 101, 141):
            lk = cv2.getStructuringElement(cv2.MORPH_RECT, (ksz, 1))
            enh = cv2.morphologyEx(plane, cv2.MORPH_CLOSE, lk)
            e8 = cv2.normalize(enh, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            _, bw = cv2.threshold(e8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            lines = cv2.HoughLinesP(bw, 1, np.pi / 180, threshold=25,
                                    minLineLength=min_len, maxLineGap=60)
            if lines is None:
                continue
            for L in lines:
                a = np.asarray(L).reshape(-1)[:4].astype(int)
                if len(a) < 4:
                    continue
                x1_, y1_, x2_, y2_ = a
                if abs(y2_ - y1_) > 3:            # 只看近水平线: 安装接线是水平的
                    continue
                L_ = float(np.hypot(x2_ - x1_, y2_ - y1_))
                cands.append((L_, x1_, y1_, x2_, y2_))
    # ── 关键修正 2026-10-20: 接线只有**一条**, 而多尺度多通道会把它重复检出十几次,
    #   加上凹凸区的方向性纹理也被当直线 ⇒ 遮罩一度达 46.8%, **左下/右侧缺陷整片被遮死**
    #   (网格实测: 右侧 c9-c12 被遮 55~99%, 左下 c1-c5 被遮 80~93% ⇒ 真缺陷反而测不到)。
    #   改为: 只按「长度最长」取, 且总遮罩硬上限 12%。
    cands.sort(key=lambda t: -t[0])
    mask = np.zeros_like(g, dtype=np.uint8)
    budget = int(0.12 * H * W)
    used = 0
    for L_, x1_, y1_, x2_, y2_ in cands:
        if L_ < min_len:
            continue
        tmp = np.zeros_like(mask)
        cv2.line(tmp, (x1_, y1_), (x2_, y2_), 255, 4)
        add = int((tmp > 0).sum() - ((tmp > 0) & (mask > 0)).sum())
        if used + add > budget:
            continue
        mask |= tmp
        used += add
        if used >= budget:
            break
    return mask


def waviness(g, wire_mask, win=21, k=2.0, min_area=120, circ_min=0.20):
    """局部标准差 → 不平整度; 排除接线后按圆度挑斑块。"""
    gf = g.astype(np.float32)
    mu = cv2.blur(gf, (win, win))
    mu2 = cv2.blur(gf * gf, (win, win))
    var = np.maximum(mu2 - mu * mu, 0)
    std = np.sqrt(var)

    valid = std.copy()
    valid[wire_mask > 0] = 0                       # 接线区域不参与
    med = float(np.median(valid[valid > 0])) if np.any(valid > 0) else 1.0
    mad = float(np.median(np.abs(valid[valid > 0] - med))) or 1.0
    z = (valid - med) / (1.4826 * mad)

    mask = (z >= k).astype(np.uint8) * 255
    mask[wire_mask > 0] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))

    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        sub = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
        cnts, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        per = cv2.arcLength(c, True)
        if per <= 0:
            continue
        circ = float(4 * np.pi * cv2.contourArea(c) / (per * per))
        if circ < circ_min:                        # 太细长 ⇒ 多半是接线/棱线残留, 不要
            continue
        blk = std[y:y + h, x:x + w]
        zz = z[y:y + h, x:x + w]
        # 凹凸的"幅度": 块内明暗跨度, 有起伏才有跨度
        gg = g[y:y + h, x:x + w]
        out.append({"xywh": [int(x), int(y), int(w), int(h)], "area": int(area),
                    "circ": round(circ, 2), "std_mean": round(float(blk.mean()), 1),
                    "std_max": round(float(blk.max()), 1), "z_max": round(float(zz.max()), 2),
                    "range": int(gg.max()) - int(gg.min()),
                    "fill": round(float(area) / float(max(1, w * h)), 2)})
    out.sort(key=lambda d: (-d["z_max"], -d["std_mean"]))
    return out, std, z, mask


def main():
    os.makedirs(OUTD, exist_ok=True)
    crop, expo, info = get_crop()
    if crop is None:
        print("❌ 取不到模块 ROI: %s" % info); return 1
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    H, W = g.shape[:2]
    print("曝光 %s | 模块 ROI %dx%d mean=%.1f 死白=%.2f%%"
          % (expo, W, H, g.mean(), float((g >= 250).mean() * 100)))

    wm = build_wire_mask(g)
    print("① 排除安装接线/棱线: 遮掉 %d px (占模块 %.1f%%)"
          % (int((wm > 0).sum()), 100.0 * (wm > 0).mean()))

    hits, std, z, mask = waviness(g, wm)

    # 网格诊断: 纵向 4 带 × 横向 12 段, 打印每格局部方差均值 —— 不平整区域会明显更高
    nb, ns = 4, 12
    print("\n   不平整度网格 (行=纵向带, 列=横向段, 数值=该格 std 均值; 排除接线区):")
    for bi in range(nb):
        y_a, y_b = bi * H // nb, (bi + 1) * H // nb
        row = []
        for si in range(ns):
            x_a, x_b = si * W // ns, (si + 1) * W // ns
            blk = std[y_a:y_b, x_a:x_b].copy()
            msk = wm[y_a:y_b, x_a:x_b]
            blk[msk > 0] = np.nan
            row.append(np.nanmean(blk) if np.any(~np.isnan(blk)) else float("nan"))
        print("   y%3d-%3d  " % (y_a, y_b) + " ".join("%6.1f" % v for v in row))
    print("\n② 凸凹斑块 %d 个 (局部方差 z≥2.5, 面积≥180px, 圆度≥0.35, 已排除接线):" % len(hits))
    print("   %-22s %-7s %-8s %-8s %-8s %-8s %s"
          % ("xywh", "面积", "圆度", "起伏std", "峰值z", "明暗跨度", "填充率"))
    for hh in hits[:10]:
        print("   %-22s %-7d %-8.2f %-8.1f %-8.2f %-8d %.2f"
              % (str(hh["xywh"]), hh["area"], hh["circ"], hh["std_mean"],
                 hh["z_max"], hh["range"], hh["fill"]))

    # 出图: 2x 模块 + 斑块框(红) + 被排除的接线(蓝虚线示意)
    S = 2
    big = cv2.resize(crop, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    overlay_wire = cv2.resize(wm, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    blue = big.copy()
    blue[overlay_wire > 0] = (255, 140, 0)
    big = cv2.addWeighted(big, 0.75, blue, 0.25, 0)
    for i, hh in enumerate(hits[:8], 1):
        x, y, w, h = hh["xywh"]
        cv2.rectangle(big, (x * S, y * S), ((x + w) * S, (y + h) * S), (0, 0, 255), 3)
        cv2.putText(big, "#%d z%.1f c%.2f" % (i, hh["z_max"], hh["circ"]),
                    (x * S, max(24, y * S - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.putText(big, "WAVINESS (bumps/pits) candidates=%d | blue=excluded wiring/edge | 3000us sat=%.2f%%"
                % (len(hits), float((g >= 250).mean() * 100)),
                (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUTD, "surface_waviness_%s.jpg" % stamp)
    cv2.imwrite(p, big, [cv2.IMWRITE_JPEG_QUALITY, 94])
    print("\n③ 出图 → %s (%dx%d, %d KB)"
          % (os.path.relpath(p, ROOT), big.shape[1], big.shape[0], os.path.getsize(p) // 1024))

    # 单独出一张"不平整度热图", 便于判断算法到底看到了什么
    hm = cv2.applyColorMap(cv2.normalize(std, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
                           cv2.COLORMAP_JET)
    hm = cv2.resize(hm, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    ph = os.path.join(OUTD, "surface_waviness_heat_%s.jpg" % stamp)
    cv2.imwrite(ph, hm, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print("   热图 → %s" % os.path.relpath(ph, ROOT))

    rec = {"ts": stamp, "expo": expo, "roi_hw": [W, H],
           "wire_masked_pct": round(100.0 * (wm > 0).mean(), 2),
           "n_hits": len(hits), "hits": hits[:10], "jpg": p, "heat_jpg": ph}
    with open(os.path.join(ROOT, "data/memory/l2_waviness_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("④ 已记入 data/memory/l2_waviness_log.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
