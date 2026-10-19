#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出「摆正后的表面判据图」: 从 kind=origin 搜矩形刚体 → 纯旋转摆正 → 按真实尺寸裁剪。
老倪: 「判据图应该让光模块水平放置」⇒ 长边水平、只留刚体、零拉伸(输出尺寸==检出尺寸)。
交付形态按技能: 摆正图与「原图+绿框」各存一张, 不拼。
"""
import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aoi_surface_rect import surface_judge                            # noqa: E402

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
UA = {"User-Agent": "zmax-probe"}
BASE = "http://192.168.23.23:10083"
STAMP = time.strftime("%Y%m%d_%H%M%S")
OUTD = os.path.expanduser("~/zmax/data/deliver")
OUT_CROP = os.path.join(OUTD, "surface_judge_rect_%s.png" % STAMP)
OUT_OV = os.path.join(OUTD, "surface_rect_box_%s.png" % STAMP)

expo = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/exposure", headers=UA), timeout=15).read())
raw = urllib.request.urlopen(urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA),
                             timeout=30).read()
src = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
shot = time.strftime("%H:%M:%S")
g0 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
print("源图 %dx%d 拍摄 %s 曝光 %sus mean=%.1f std=%.1f 暗部=%.1f%%"
      % (src.shape[1], src.shape[0], shot, expo.get("us"), g0.mean(), g0.std(),
         float((g0 < 25).mean() * 100)))

crop, overlay, meta = surface_judge(src, out_long=1400)
print("搜索/摆正 meta: %s" % json.dumps(meta, ensure_ascii=False, default=str))

if crop is None:
    print("❌ 没搜到矩形刚体 ⇒ 按技能「宁缺勿假」不出摆正图: %s" % meta.get("why"))
    raise SystemExit(1)

ch, cw = crop.shape[:2]
ar = max(cw, ch) / float(min(cw, ch))
print("摆正图 %dx%d · 长宽比 %.2f · 水平(长边在 x)=%s" % (cw, ch, ar, cw > ch))

# ── 摆正后的判据图 (放大 2x 便于目检) ──
S = max(1, int(1300 / float(max(cw, ch))))
big = cv2.resize(crop, (cw * S, ch * S), interpolation=cv2.INTER_NEAREST)
canvas = Image.new("RGB", (big.shape[1] + 32, big.shape[0] + 118), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 25), ImageFont.truetype(FONT, 19)
except Exception:
    f_t = f_m = ImageFont.load_default()
dr.text((16, 8), "表面判据图 (摆正后) · 拍摄 %s · 曝光 %sus" % (shot, expo.get("us")),
        font=f_t, fill=(255, 255, 255))
dr.text((16, 40), "检出刚体 %dx%d · 倾角 %.2f° → 已摆正(长边水平) · 矩形度 %.3f · 放大 %dx"
        % (meta.get("crop_size", [0, 0])[0], meta.get("crop_size", [0, 0])[1],
           float(meta.get("angle", 0)), float(meta.get("fill", 0)), S),
        font=f_m, fill=(255, 210, 90))
dr.text((16, 64), "输出尺寸 == 检出尺寸 (零拉伸) · 只用旋转, 无透视重映射"
        if list(meta.get("crop_size", [])) == list(meta.get("out_size", []))
        else "⚠️ 输出尺寸 != 检出尺寸: %s vs %s" % (meta.get("crop_size"), meta.get("out_size")),
        font=f_m, fill=(120, 220, 160))
gs = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
dr.text((16, 88), "同帧像素: mean %.1f · p90 %.1f · 死白 %.2f%% · 暗部 %.1f%%"
        % (gs.mean(), float(np.percentile(gs, 90)), float((gs >= 250).mean() * 100),
           float((gs < 25).mean() * 100)), font=f_m, fill=(200, 200, 200))
canvas.paste(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)), (16, 114))
os.makedirs(OUTD, exist_ok=True)
canvas.save(OUT_CROP)
print("摆正判据图 → %s (%dx%d)" % (OUT_CROP, canvas.width, canvas.height))

# ── 原图 + 绿框 (单独一张, 不与摆正图拼) ──
if overlay is not None:
    cv2.imwrite(OUT_OV, overlay)
    print("原图+搜索框 → %s (%dx%d)" % (OUT_OV, overlay.shape[1], overlay.shape[0]))

json.dump({"shot_at": shot, "expo_us": expo.get("us"), "meta": meta,
           "crop_png": OUT_CROP, "overlay_png": OUT_OV},
          open(os.path.join(OUTD, "surface_judge_rect_%s.json" % STAMP), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
