#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出「表面 AOI 压高光前后对比图」: 同一帧原图, 三种处理并排 + 量化数字。
栏1 原始(工控机 kind=origin, 未处理) · 栏2 旧参数(knee200/top214) · 栏3 新参数(knee160/top185)
"""
import os
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
OUT = os.path.expanduser("~/zmax/data/deliver/surface_deglare_ab_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
URL = "http://192.168.23.23:10083/picture?kind=origin"


def deglare(bgr, knee, top):
    lut = np.arange(256, dtype=np.float32)
    m = lut > knee
    lut[m] = knee + (top - knee) * (lut[m] - knee) / float(255 - knee)
    return cv2.LUT(bgr, np.clip(lut, 0, 255).astype(np.uint8))


def metrics(bgr):
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return g.mean(), float(np.percentile(g, 90)), float((g >= 250).mean() * 100)


req = urllib.request.Request(URL, headers={"User-Agent": "zmax-probe"})
raw = urllib.request.urlopen(req, timeout=20).read()
src = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
if src is None:
    raise SystemExit("取图失败")
shot_at = time.strftime("%H:%M:%S")
print("源图 %dx%d %.0fKB 拍摄 %s" % (src.shape[1], src.shape[0], len(raw) / 1024, shot_at))

COL_W, PAD, HEAD, TOPM = 720, 16, 92, 34
panels = [
    ("① 原始 (工控机 kind=origin, 未处理)", src),
    ("② 旧参数 knee=200 / top=214", deglare(src, 200, 214)),
    ("③ 新参数 knee=160 / top=185 (已上线)", deglare(src, 160, 185)),
]
h, w = src.shape[:2]
sc = COL_W / float(w)
rh = int(h * sc)
canvas = Image.new("RGB", (COL_W * 3 + PAD * 4, rh + HEAD + TOPM + 16), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t = ImageFont.truetype(FONT, 26)
    f_m = ImageFont.truetype(FONT, 22)
except Exception:
    f_t = f_m = ImageFont.load_default()

dr.text((PAD, 10), "表面 AOI 压高光前后对比 · 同一帧真图 · 拍摄 %s" % shot_at,
        font=f_t, fill=(255, 255, 255))

for i, (title, img) in enumerate(panels):
    x = PAD + i * (COL_W + PAD)
    m, p90, sat = metrics(img)
    dr.text((x, TOPM + 4), title, font=f_m, fill=(120, 220, 160) if i == 2 else (210, 210, 210))
    dr.text((x, TOPM + 32), "mean=%.1f   p90=%.1f   死白(≥250)=%.2f%%" % (m, p90, sat),
            font=f_m, fill=(255, 210, 90))
    rgb = cv2.cvtColor(cv2.resize(img, (COL_W, rh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    canvas.paste(Image.fromarray(rgb), (x, HEAD + TOPM))
    dr.rectangle([x - 1, TOPM, x + COL_W, HEAD + TOPM + rh], outline=(70, 70, 70))
    print("  %s → mean=%.1f p90=%.1f 死白=%.2f%%" % (title, m, p90, sat))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
canvas.save(OUT)
print("已保存 %s (%dx%d)" % (OUT, canvas.width, canvas.height))
