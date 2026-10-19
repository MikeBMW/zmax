#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""surface_expo_roi_sweep.py — 按**模块 ROI** 扫曝光, 找"不过曝的光模块"档位

老倪 2026-10-20: 「你得用摆正的, 没有曝光的光模块给YOLO」
  ⇒ 判据必须是 **摆正后模块 ROI 的死白率**, 不是整帧 (整帧被黑背景拉低, 会误判"太暗")。
  ⇒ 几何在低曝光下已定 (5000us 能搜到 1124x188 / -69.79°), 各档沿用同一角度旋转,
     这样每档取的都是**同一个物理区域**, 死白率可比。

输出: 每档 ROI 的 mean/p90/死白/暗部 + 选出的"最不过曝且仍有细节"的那一档。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from aoi_surface_rect import surface_roi                        # noqa: E402
from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality  # noqa: E402

BASE = os.environ.get("ZMAX_SURFACE_AOI_URL", "http://192.168.23.23:10083").rstrip("/")
LEVELS = [5000, 8000, 12000, 18000, 25000, 35000, 48000]
OUTD = os.path.join(ROOT, "data/deliver")


def set_expo(us, gain=1.8, settle=2.6):
    urllib.request.urlopen(urllib.request.Request(
        "%s/exposure?us=%d&gain=%s" % (BASE, int(us), gain), method="POST",
        headers={"User-Agent": "zmax-probe"}), timeout=30).read()
    time.sleep(settle)


def rect_crop(bgr, rect, out_long=None):
    """按已定几何: 纯旋转摆正 → 按检出真实尺寸裁剪 (零插值)。"""
    cx, cy = float(rect["cx"]), float(rect["cy"])
    w, h = float(rect["w"]), float(rect["h"])
    ang = float(rect["angle"])
    if w < h:
        w, h, ang = h, w, ang + 90.0
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(bgr, M, (bgr.shape[1], bgr.shape[0]), flags=cv2.INTER_CUBIC)
    W, H = int(round(w)), int(round(h))
    crop = cv2.getRectSubPix(rot, (W, H), (cx, cy))
    return crop, rot


def metrics(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    lap = cv2.Laplacian(g, cv2.CV_64F)
    return {"mean": round(float(g.mean()), 1), "p90": round(float(np.percentile(g, 90)), 1),
            "sat": round(float((g >= 250).mean() * 100), 2),
            "dark": round(float((g < 25).mean() * 100), 2),
            "sharp": round(float(lap.var()), 1), "hw": [int(g.shape[1]), int(g.shape[0])]}


def main():
    os.makedirs(OUTD, exist_ok=True)
    sq = SurfaceOpticalQuality()

    # ── ① 低曝光定几何 (只做一次, 各档沿用) ──
    print("① 5000us 定几何…")
    set_expo(5000)
    lo = sq.capture(grab=True)
    if lo is None:
        print("❌ 取帧失败"); return 1
    rect, meta = surface_roi(lo)
    if rect is None:
        print("❌ 低曝光搜不到模块: %s" % meta.get("why")); return 1
    print("   几何: cx=%.1f cy=%.1f w=%.0f h=%.0f 长宽比=%.2f angle=%.2f° fill=%.3f"
          % (rect["cx"], rect["cy"], rect["w"], rect["h"], rect.get("aspect", 0),
             rect["angle"], rect["fill"]))

    # ── ② 逐档取帧 → 同一几何旋转 → 量 ROI ──
    rows = []
    print("\n② 逐档 ROI (同一几何, 只改曝光):")
    print("   %-8s %-7s %-7s %-8s %-8s %-8s %s" % ("us", "mean", "p90", "死白%", "暗部%", "清晰度", "判定"))
    for us in LEVELS:
        set_expo(us)
        im = sq.capture(grab=True)
        if im is None:
            print("   %-8d 取帧失败" % us); continue
        crop, rot = rect_crop(im, rect)
        q = metrics(crop)
        fq = metrics(im)
        # 判据: 死白<=5% 且 mean>=60 ⇒ 不过曝且有细节
        verdict = "✅ 可用" if (q["sat"] <= 5.0 and q["mean"] >= 60) else (
            "过曝" if q["sat"] > 5.0 else "偏暗")
        rows.append({"us": us, "roi": q, "full": fq, "verdict": verdict})
        print("   %-8d %-7.1f %-7.1f %-8.2f %-8.2f %-8.1f %s"
              % (us, q["mean"], q["p90"], q["sat"], q["dark"], q["sharp"], verdict))

    if not rows:
        print("❌ 没拿到任何档"); return 1

    # ── ③ 选档: 死白达标里 mean 最高(细节最多)的那档; 都不达标就取死白最低的 ──
    ok = [r for r in rows if r["verdict"] == "✅ 可用"]
    if ok:
        best = max(ok, key=lambda r: r["roi"]["mean"])
        note = "死白达标档里 mean 最高(细节最多)"
    else:
        best = min(rows, key=lambda r: (r["roi"]["sat"], -r["roi"]["mean"]))
        note = "没有一档同时满足 死白≤5%% 且 mean≥60 ⇒ 取死白最低的 %dus(镜面反光压不下去)" % best["us"]

    print("\n③ 选定: %dus — %s" % (best["us"], note))
    print("   ROI mean=%.1f p90=%.1f 死白=%.2f%% 暗部=%.2f%% 清晰度=%.1f"
          % (best["roi"]["mean"], best["roi"]["p90"], best["roi"]["sat"],
             best["roi"]["dark"], best["roi"]["sharp"]))

    # ── ④ 用选定档出"摆正 + 不过曝"的模块图 ──
    set_expo(best["us"])
    im = sq.capture(grab=True)
    crop, rot = rect_crop(im, rect) if im is not None else (None, None)
    if crop is None:
        print("❌ 定档取帧失败"); return 1
    stamp = time.strftime("%Y%m%d_%H%M%S")
    p_crop = os.path.join(OUTD, "surface_roi_clean_%s.png" % stamp)
    p_rot = os.path.join(OUTD, "surface_rot_clean_%s.png" % stamp)
    cv2.imwrite(p_crop, crop)
    cv2.imwrite(p_rot, rot)
    print("④ 产出: ROI %s (%dx%d) · 摆正整幅 %s"
          % (os.path.relpath(p_crop, ROOT), crop.shape[1], crop.shape[0], os.path.relpath(p_rot, ROOT)))

    rec = {"ts": stamp, "rect": {k: rect.get(k) for k in ("cx", "cy", "w", "h", "angle", "fill", "aspect")},
           "sweep": rows, "chosen_us": best["us"], "chosen_note": note,
           "roi_png": p_crop, "rot_png": p_rot}
    with open(os.path.join(ROOT, "data/memory/surface_expo_roi_sweep.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("⑤ 已记入 data/memory/surface_expo_roi_sweep.jsonl")
    print("\n选定档 %dus 现在生效 (落盘, 重启保持)" % best["us"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
