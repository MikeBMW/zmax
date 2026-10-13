#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_aoi_surface_rect.py — 侧面本机判据图口径判据 (几何证明 + 宁缺勿假)

判据:
  A) 合成帧(斜置 800x220 亮矩形, 倾角 −12°, 背景暗): 必须检出; 检出尺寸≈真值(±3px);
     摆正后裁剪图内亮区 minAreaRect 倾角 ≈ 0 (旋转生效); 输出尺寸==检出尺寸(未拉伸);
     裁剪像素 == 原帧同区域像素(同帧同像素, |均值差| < 2)。
  B) 真实帧(侧面全暗/无工件): 必须 ok=False 且给出 why; 不得伪造矩形(overlay 只写 NO RECT)。
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/ubuntu/zmax/tools")
from aoi_surface_rect import surface_judge, surface_roi                             # noqa: E402

OUT = "/home/ubuntu/zmax/reports/judge_img"
os.makedirs(OUT, exist_ok=True)
res = []


def chk(name, cond, detail=""):
    res.append((name, bool(cond), detail))
    print("  %-46s %s %s" % (name, "✅" if cond else "❌", detail))


# ── A) 合成帧: 斜置亮矩形 ────────────────────────────────────────────────
W, H, TW, TH, TILT = 1600, 1200, 800, 220, -12.0
canvas = np.full((H, W, 3), 18, np.uint8)
rect = ((W / 2, H / 2), (TW, TH), TILT)
cv2.fillPoly(canvas, [np.int32(cv2.boxPoints(rect))], (235, 235, 235))
crop, ov, meta = surface_judge(canvas, out_long=None)
chk("A1 检出斜置矩形", meta.get("ok") is True, "why=%s" % meta.get("why"))
chk("A2 矩形度 ≥0.9", (meta.get("fill") or 0) >= 0.9, "fill=%.3f" % (meta.get("fill") or 0))
d_w = abs((meta.get("crop_size") or [0, 0])[0] - TW) <= 6 or abs((meta.get("crop_size") or [0, 0])[0] - TH) <= 6
d_h = abs((meta.get("crop_size") or [0, 0])[1] - TW) <= 6 or abs((meta.get("crop_size") or [0, 0])[1] - TH) <= 6
chk("A3 检出尺寸≈真值 800x220", d_w and d_h, "crop=%s" % (meta.get("crop_size"),))
chk("A4 输出尺寸==检出尺寸(未拉伸)", meta.get("no_stretch") is True, "out=%s crop=%s" % (meta.get("out_size"), meta.get("crop_size")))
if crop is not None:
    cg = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    m = (cg > 120).astype(np.uint8) * 255
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cs:
        (_bxy, _bwh, ang2) = cv2.minAreaRect(max(cs, key=cv2.contourArea))
        _x, _y = _bxy
        _w, _h = _bwh
        a2 = abs(ang2 if abs(ang2) <= 45 else 90 - abs(ang2))
        chk("A5 摆正后残余倾角 ≈0 (|<2°|)", a2 < 2.0, "残余 %.2f° (原 %.0f°)" % (a2, TILT))
        chk("A6 摆正后亮区占满裁剪图", (cv2.contourArea(max(cs, key=cv2.contourArea)) / (cg.size)) > 0.85,
            "占比 %.2f" % (cv2.contourArea(max(cs, key=cv2.contourArea)) / cg.size))
    chk("A7 同帧同像素 |均值差|<2", abs(meta.get("same_pixel_mean_diff") or 99) < 2.0,
        "差 %.3f" % (meta.get("same_pixel_mean_diff") or -1))
    cv2.imwrite(os.path.join(OUT, "selftest_synth_overlay.png"), ov)
    cv2.imwrite(os.path.join(OUT, "selftest_synth_deskew.png"), crop)

# ── B) 真实帧: 无工件 ⇒ 宁缺勿假 ─────────────────────────────────────────
REAL = ["/home/ubuntu/zmax/reports/judge_img/surface_origin.png",
        "/home/ubuntu/zmax/zmax_data/aoi_v4/_v12_1test_surface/Surface_Image_W2448_H2048_No_1.png"]
for i, f in enumerate(REAL, 1):
    im = cv2.imread(f)
    if im is None:
        chk("B%d 读不到 %s" % (i, os.path.basename(f)), False, f)
        continue
    r, m = surface_roi(im)
    chk("B%d 真实暗帧不伪造矩形 (%s)" % (i, os.path.basename(f)[:26]), r is None,
        "why=%s" % str(m.get("why"))[:58])
    _c, _o, _m = surface_judge(im, out_long=None)
    cv2.imwrite(os.path.join(OUT, "real_NORECT_%d.png" % i), _o)

print()
bad = [n for n, ok, _ in res if not ok]
print("判定: %d/%d 过%s" % (len(res) - len(bad), len(res), "" if not bad else " · 未过: " + ", ".join(bad)))
print("出图: %s/selftest_synth_overlay.png · selftest_synth_deskew.png · real_NORECT_[12].png" % OUT)
sys.exit(1 if bad else 0)
