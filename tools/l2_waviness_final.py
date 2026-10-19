#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_waviness_final.py — 收紧版: 排除装配孔, 边界收窄到缺陷本体

老倪 2026-10-20 两处修正:
  ① 4 号 [687,56,75,97] 不是缺陷, 是**装配孔**(正常结构) ⇒ 必须能自动排除孔
  ② 其它几个**太大**, 边界要缩到缺陷本身

装配孔为什么能自动排掉 (形状学依据, 不靠位置硬编码):
  · 孔是**近圆**的 (4号 75x97 ⇒ 长短边比 1.29, 圆度接近1)
  · 孔**内部平坦** (孔底/孔内灰度均匀, 局部 std 低), 而凸凹缺陷内部 std 高
  · 孔**边缘锐利** (一圈强边), 用 HoughCircles 直接能锁到
  ⇒ 判据: 近圆 (min/max 边长 >= 0.65) 且 内部 std 中位数低于全图基线 ⇒ 判为孔, 排除

边界收窄三招 (上一版 31x31 平滑 + 25x15 闭运算把片撑肥了):
  · 平滑核 31→13
  · 闭运算 25x15 → 9x5
  · 种子阈值 p80 → p88, 只留核心; 再做 3px 腐蚀回缩
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

from l2_surface_waviness import get_crop     # noqa: E402

OUTD = os.path.join(ROOT, "data/deliver")


def std_map(g, win=21):
    gf = g.astype(np.float32)
    mu = cv2.blur(gf, (win, win))
    mu2 = cv2.blur(gf * gf, (win, win))
    return np.sqrt(np.maximum(mu2 - mu * mu, 0))


def classify_hole(g, std, x, y, w, h, base):
    """按**区域自身形状**判装配孔, 不挖图。
    4号 [687,56,75,97]: 长短边比 1.29(近圆) + 内部平坦 ⇒ 孔。
    上一版用 HoughCircles 全图找圆, 误检 16 个(孔内 std 全算出 0.0), 又把响应图整个挖掉
    ⇒ 缺陷区域 0 片。所以改成只看候选区域自己。"""
    if w <= 4 or h <= 4:
        return None
    aspect = max(w, h) / float(min(w, h))
    # 去掉外圈 30% 后看内部是否平坦
    mx, my = int(w * 0.3), int(h * 0.3)
    inner = std[y + my:y + h - my, x + mx:x + w - mx]
    if inner.size < 25:
        return None
    s_med = float(np.median(inner))
    if aspect <= 1.45 and s_med <= base * 1.15:
        return {"xywh": [int(x), int(y), int(w), int(h)], "aspect": round(aspect, 2),
                "std_in": round(s_med, 1), "base": round(base, 1)}
    return None


def find_mount_holes(g, std, smin=12, smax=140):
    """(保留但不再用于挖图)"""
    gx = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 4)).apply(g)
    gb = cv2.GaussianBlur(gx, (5, 5), 1.2)
    circles = cv2.HoughCircles(gb, cv2.HOUGH_GRADIENT, dp=1.2, minDist=40,
                               param1=110, param2=32, minRadius=smin, maxRadius=smax)
    holes = []
    base = float(np.median(std))
    if circles is not None:
        for c in np.asarray(circles).reshape(-1, 3):
            cx, cy, r = float(c[0]), float(c[1]), float(c[2])
            y0, y1 = max(0, int(cy - r)), min(g.shape[0], int(cy + r))
            x0, x1 = max(0, int(cx - r)), min(g.shape[1], int(cx + r))
            if y1 - y0 < 6 or x1 - x0 < 6:
                continue
            # 孔内(去掉外圈 25%)的 std 中位数
            yy, xx = np.ogrid[y0:y1, x0:x1]
            inner = ((yy - (cy - y0)) ** 2 + (xx - (cx - x0)) ** 2) <= (0.75 * r) ** 2
            s_in = std[y0:y1, x0:x1][inner]
            s_med = float(np.median(s_in)) if s_in.size else 0.0
            if s_med <= base * 1.15:          # 内部比基线还平 ⇒ 是孔, 不是凸凹
                holes.append({"cx": round(cx, 1), "cy": round(cy, 1), "r": round(r, 1),
                              "std_in": round(s_med, 1), "base": round(base, 1)})
    return holes


def regions(g, std, holes, thr_pct=86, min_frac=1.5):
    H, W = g.shape[:2]
    base = float(np.median(std))
    mad = float(np.median(np.abs(std - base))) or 1.0
    zn = (std - base) / (1.4826 * mad)
    sm = cv2.GaussianBlur(zn, (13, 13), 0)                     # 31→13, 边界不再被撑开
    # 注意: 这里**不再**把孔从响应图里挖掉(挖图会让整片缺陷消失), 只在下面按形状分类
    thr = float(np.percentile(sm, thr_pct))
    mask = (sm >= max(thr, 1.0)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 5)))   # 25x15→9x5
    mask = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))    # 7 太狠, 右侧整片被吃掉
    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        frac = 100.0 * area / (W * H)
        if frac < min_frac:
            continue
        m = (lab[y:y + h, x:x + w] == i)
        sub = sm[y:y + h, x:x + w]
        cx_, cy_ = x + w / 2.0, y + h / 2.0
        rec = {"xywh": [int(x), int(y), int(w), int(h)], "area_pct": round(frac, 2),
               "z_mean": round(float(sub[m].mean()), 2),
               "z_max": round(float(sub[m].max()), 2),
               "pos": ("左" if cx_ < W / 3 else "右" if cx_ > 2 * W / 3 else "中")
                      + ("上" if cy_ < H / 3 else "下" if cy_ > 2 * H / 3 else "中")}
        hole = classify_hole(g, std, x, y, w, h, base)
        if hole is not None:
            holes.append(hole)                 # 装配孔: 不算缺陷
            continue
        out.append(rec)
    out.sort(key=lambda d: -d["area_pct"])
    return out, sm


def main():
    crop, expo, info = get_crop()
    if crop is None:
        print("❌ 取不到模块 ROI: %s" % info); return 1
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    H, W = g.shape[:2]
    std = std_map(g)
    print("曝光 %s | 模块 ROI %dx%d mean=%.1f 死白=%.2f%%"
          % (expo, W, H, g.mean(), float((g >= 250).mean() * 100)))

    holes = []                      # 由 regions() 内部按区域形状分类填充
    regs, sm = regions(g, std, holes)
    if holes:
        print("\n① 判为装配孔(近圆+内部平坦)而排除 %d 个:" % len(holes))
        for hh in holes:
            print("   xywh=%-22s 长短边比=%.2f 内部std=%.1f (基线%.1f)"
                  % (str(hh["xywh"]), hh["aspect"], hh["std_in"], hh["base"]))
    else:
        print("\n① 未识别到装配孔")
    print("\n② 收紧后缺陷区域 %d 片 (阈值 p88, 平滑13, 闭9x5, 腐蚀7, 占地≥1.5%%):" % len(regs))
    print("   %-6s %-24s %-9s %-9s %s" % ("位置", "xywh", "占地%", "z均值", "z峰"))
    for r in regs[:8]:
        print("   %-6s %-24s %-9.2f %-9.2f %.2f"
              % (r["pos"], str(r["xywh"]), r["area_pct"], r["z_mean"], r["z_max"]))

    # 出图
    S = 2
    big = cv2.resize(crop, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    for hh in holes:
        cv2.circle(big, (int(hh["cx"] * S), int(hh["cy"] * S)), int(hh["r"] * S), (0, 200, 0), 3)
        cv2.putText(big, "hole", (int(hh["cx"] * S) - 22, int(hh["cy"] * S) - int(hh["r"] * S) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
    for i, r in enumerate(regs[:6], 1):
        x, y, w, h = r["xywh"]
        cv2.rectangle(big, (x * S, y * S), ((x + w) * S, (y + h) * S), (0, 0, 255), 3)
        cv2.putText(big, "#%d %s %.1f%%" % (i, r["pos"], r["area_pct"]),
                    (x * S + 3, max(26, y * S + 26)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
    cv2.putText(big, "tight regions=%d | green=assembly holes excluded | 3000us sat=%.2f%%"
                % (len(regs), float((g >= 250).mean() * 100)),
                (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUTD, "surface_final_%s.jpg" % stamp)
    cv2.imwrite(p, big, [cv2.IMWRITE_JPEG_QUALITY, 95])
    hm = cv2.applyColorMap(cv2.normalize(sm, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8),
                           cv2.COLORMAP_JET)
    hm = cv2.resize(hm, (W * S, H * S), interpolation=cv2.INTER_NEAREST)
    for i, r in enumerate(regs[:6], 1):
        x, y, w, h = r["xywh"]
        cv2.rectangle(hm, (x * S, y * S), ((x + w) * S, (y + h) * S), (255, 255, 255), 3)
    ph = os.path.join(OUTD, "surface_final_heat_%s.jpg" % stamp)
    cv2.imwrite(ph, hm, [cv2.IMWRITE_JPEG_QUALITY, 93])
    print("\n③ 出图 → %s ; 热图 → %s"
          % (os.path.relpath(p, ROOT), os.path.relpath(ph, ROOT)))

    rec = {"ts": stamp, "expo": expo, "roi_hw": [W, H], "holes": holes,
           "regions": regs, "jpg": p, "heat_jpg": ph}
    with open(os.path.join(ROOT, "data/memory/l2_waviness_final.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("④ 已记入 data/memory/l2_waviness_final.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
