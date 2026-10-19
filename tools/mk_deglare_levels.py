#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面 AOI 压高光: 一次出多档对比, 让老倪直接挑 (不占服务, 纯离线模拟同一帧)。
档位含义: 像素值 >knee 的部分线性压到 top, 所以 knee/top 越小画面越暗。
"""
import os
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
OUT = os.path.expanduser("~/zmax/data/deliver/surface_deglare_levels_%s.png" % time.strftime("%Y%m%d_%H%M%S"))


def deglare(bgr, knee, top):
    lut = np.arange(256, dtype=np.float32)
    m = lut > knee
    lut[m] = knee + (top - knee) * (lut[m] - knee) / float(255 - knee)
    return cv2.LUT(bgr, np.clip(lut, 0, 255).astype(np.uint8))


def met(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return g.mean(), float(np.percentile(g, 90)), float((g >= 250).mean() * 100)


req = urllib.request.Request("http://192.168.23.23:10083/picture?kind=origin",
                             headers={"User-Agent": "zmax-probe"})
src = cv2.imdecode(np.frombuffer(urllib.request.urlopen(req, timeout=20).read(), np.uint8), cv2.IMREAD_COLOR)
shot_at = time.strftime("%H:%M:%S")

LEVELS = [
    ("原始 (未压)", None),
    ("当前 knee160/185", (160, 185)),
    ("更暗 knee130/155", (130, 155)),
    ("再暗 knee110/135", (110, 135)),
    ("最暗 knee90/115", (90, 115)),
]
COL_W, PAD, HEAD, TOPM = 560, 14, 86, 30
h, w = src.shape[:2]
rh = int(h * COL_W / float(w))
W = COL_W * len(LEVELS) + PAD * (len(LEVELS) + 1)
canvas = Image.new("RGB", (W, rh + HEAD + TOPM + 14), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 25), ImageFont.truetype(FONT, 19)
except Exception:
    f_t = f_m = ImageFont.load_default()

dr.text((PAD, 9), "表面 AOI 压高光 · 同一帧真图 · 拍摄 %s · 选一个档位我直接上线" % shot_at,
        font=f_t, fill=(255, 255, 255))
for i, (title, lv) in enumerate(LEVELS):
    img = src if lv is None else deglare(src, lv[0], lv[1])
    m, p90, sat = met(img)
    x = PAD + i * (COL_W + PAD)
    col = (120, 220, 160) if lv == (160, 185) else (215, 215, 215)
    dr.text((x, TOPM + 3), title, font=f_m, fill=col)
    dr.text((x, TOPM + 27), "mean %.0f · p90 %.0f · 死白 %.1f%%" % (m, p90, sat),
            font=f_m, fill=(255, 210, 90))
    rgb = cv2.cvtColor(cv2.resize(img, (COL_W, rh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    canvas.paste(Image.fromarray(rgb), (x, HEAD + TOPM))
    dr.rectangle([x - 1, TOPM, x + COL_W, HEAD + TOPM + rh], outline=(70, 70, 70))
    print("  %-18s mean=%.1f p90=%.1f 死白=%.2f%%" % (title, m, p90, sat))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
canvas.save(OUT)
print("已保存 %s (%dx%d)" % (OUT, canvas.width, canvas.height))
