#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_waviness_seed2.py — 老倪指认的 2 号 [447,138,32,29] 定性+定量, 并验证判据只命中它

为什么 2 号特殊 (这是能把它和别的斑块分开的物理依据):
  · 明暗跨度 153 —— 同一小区域里既有强高光又有深阴影, 说明曲率变化剧烈(真凹凸);
    1号 跨度20 / 4号 28 / 5号 27 都只是亮度均匀的小起伏.
  · 峰值 z 6.60 —— 起伏强度最高的两个之一.
  · 圆度 0.20 ⇒ 形态是**带/片状**而非点状, 不是单个坑.

判据草案: z_max>=6.0 且 明暗跨度>=100 且 面积>=300
  2号(6.60/153/391) 命中; 1号(6.73/20/290) 跨度不足; 3号(4.34/127/969) z不足;
  4/5号 z<3.8 不足 ⇒ 唯一命中.
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

from l2_surface_waviness import build_wire_mask, get_crop, waviness   # noqa: E402

OUTD = os.path.join(ROOT, "data/deliver")
SEED2 = [447, 138, 32, 29]


def grow_region(g, seed, wire_mask, pad=45, z_gate=1.2):
    """以种子为中心向外长, 把属于同一片的凹凸都纳进来(z 局部仍偏高的连续区)。"""
    x, y, w, h = seed
    H, W = g.shape[:2]
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    sub = g[y0:y1, x0:x1]
    Hh, Ww = sub.shape[:2]
    # 用最大最小值滤波求局部起伏幅度: 凹凸处 max-min 大
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    mx = cv2.dilate(sub, k)
    mn = cv2.erode(sub, k)
    amp = (mx.astype(np.int16) - mn.astype(np.int16)).astype(np.float32)
    med = float(np.median(amp))
    mad = float(np.median(np.abs(amp - med))) or 1.0
    zz = (amp - med) / (1.4826 * mad)
    m = (zz >= z_gate).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    m[wire_mask[y0:y1, x0:x1] > 0] = 0
    n, lab, stats, cents = cv2.connectedComponentsWithStats(m, 8)
    # 取包含种子中心的连通域
    scx, scy = x + w // 2 - x0, y + h // 2 - y0
    lid = lab[min(Hh - 1, max(0, scy)), min(Ww - 1, max(0, scx))]
    if lid == 0:
        out = [x, y, w, h]
    else:
        sx, sy, sw, sh, sa = stats[lid]
        out = [int(x0 + sx), int(y0 + sy), int(sw), int(sh)]
    return out, (x0, y0, x1, y1)


def main():
    crop, expo, info = get_crop()
    if crop is None:
        print("❌ 取不到模块 ROI: %s" % info); return 1
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    H, W = g.shape[:2]
    print("曝光 %s | 模块 ROI %dx%d mean=%.1f 死白=%.2f%%"
          % (expo, W, H, g.mean(), float((g >= 250).mean() * 100)))

    wm = build_wire_mask(g)
    hits, std, z, mask = waviness(g, wm)

    # ① 判据唯一性验证
    print("\n① 判据草案 z_max>=6.0 且 跨度>=100 且 面积>=300 在全图命中情况:")
    picked = []
    for hh in hits:
        ok = hh["z_max"] >= 6.0 and hh["range"] >= 100 and hh["area"] >= 300
        print("   %-22s z=%-6.2f 跨度=%-5d 面积=%-5d → %s"
              % (str(hh["xywh"]), hh["z_max"], hh["range"], hh["area"], "✅命中" if ok else "排除"))
        if ok:
            picked.append(hh)
    print("   ⇒ 命中 %d 个" % len(picked))

    # ② 2 号精确刻画
    region, box = grow_region(g, SEED2, wm)
    rx, ry, rw, rh = region
    sub = g[ry:ry + rh, rx:rx + rw]
    print("\n② 2 号精确范围: 种子 [%s] → 生长后 xywh=%s (%dx%d)"
          % (",".join(map(str, SEED2)), region, rw, rh))
    print("   ROI 内占比: 宽 %.0f%% 高 %.0f%%; 面积 %d px (模块 %.2f%%)"
          % (100.0 * rw / W, 100.0 * rh / H, rw * rh, 100.0 * rw * rh / (W * H)))

    k11 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    amp = (cv2.dilate(sub, k11).astype(np.int16) - cv2.erode(sub, k11).astype(np.int16))
    print("   起伏: 幅度 max=%d mean=%.1f | 灰度 min=%d max=%d 跨度=%d mean=%.1f std=%.1f"
          % (int(amp.max()), float(amp.mean()), int(sub.min()), int(sub.max()),
             int(sub.max()) - int(sub.min()), float(sub.mean()), float(sub.std())))

    # ③ 出图: 局部 8x 放大 + 剖面曲线
    cx0, cy0, cx1, cy1 = box
    view = crop[cy0:cy1, cx0:cx1]
    S = max(3, min(9, int(1100 / max(1, view.shape[1]))))
    big = cv2.resize(view, (view.shape[1] * S, view.shape[0] * S), interpolation=cv2.INTER_NEAREST)
    bx, by = (rx - cx0) * S, (ry - cy0) * S
    cv2.rectangle(big, (bx, by), (bx + rw * S, by + rh * S), (0, 0, 255), 3)
    cv2.putText(big, "#2 defect %dx%d px  span=%d" % (rw, rh, int(sub.max()) - int(sub.min())),
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 255, 255), 2)

    # 剖面: 穿过缺陷中心的水平/垂直灰度曲线
    prof_h = g[ry + rh // 2, cx0:cx1].astype(int)
    prof_v = g[cy0:cy1, rx + rw // 2].astype(int)
    ph, pw = 220, big.shape[1]
    prof = np.full((ph, pw, 3), 24, np.uint8)
    for name, arr, color in (("H", prof_h, (0, 255, 255)), ("V", prof_v, (255, 160, 0))):
        a = cv2.resize(arr.astype(np.float32).reshape(1, -1), (pw, 1),
                       interpolation=cv2.INTER_LINEAR).reshape(-1)
        a = np.clip((a - a.min()) / max(1e-6, a.max() - a.min()) * (ph - 40) + 20, 0, ph - 1)
        for xi in range(1, pw):
            cv2.line(prof, (xi - 1, int(ph - a[xi - 1])), (xi, int(ph - a[xi])), color, 1)
        cv2.putText(prof, "profile %s" % name, (10, 20 if name == "H" else 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
    canvas = np.vstack([big, prof])
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUTD, "surface_defect2_%s.jpg" % stamp)
    cv2.imwrite(p, canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print("\n③ 出图 → %s (%dx%d, %d KB)  [放大 %dx, 下带灰度剖面]"
          % (os.path.relpath(p, ROOT), canvas.shape[1], canvas.shape[0],
             os.path.getsize(p) // 1024, S))

    rec = {"ts": stamp, "expo": expo, "roi_hw": [W, H], "seed": SEED2,
           "grown_xywh": region, "span": int(sub.max()) - int(sub.min()),
           "amp_max": int(amp.max()), "std": round(float(sub.std()), 1),
           "criteria": "z_max>=6.0 & span>=100 & area>=300", "n_picked": len(picked),
           "jpg": p}
    with open(os.path.join(ROOT, "data/memory/l2_defect2_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("④ 已记入 data/memory/l2_defect2_log.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
