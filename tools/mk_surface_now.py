#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出表面相机当前曝光下的实拍图 (带统计标注), 供目检。"""
import os
import sys
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
UA = {"User-Agent": "zmax-probe"}
OUT = os.path.expanduser("~/zmax/data/deliver/surface_now_%s.png" % time.strftime("%Y%m%d_%H%M%S"))

expo = urllib.request.urlopen(urllib.request.Request("http://192.168.23.23:10083/exposure", headers=UA), timeout=15)
info = __import__("json").loads(expo.read())
shot = time.strftime("%H:%M:%S")
raw = urllib.request.urlopen(urllib.request.Request(
    "http://192.168.23.23:10083/picture?kind=origin&grab=1", headers=UA), timeout=25).read()
im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
m, p90 = g.mean(), float(np.percentile(g, 90))
sat, dark = float((g >= 250).mean() * 100), float((g < 25).mean() * 100)
print("拍摄 %s · 曝光 %sus/%sdB · mean=%.1f p90=%.1f 死白=%.2f%% 暗部=%.1f%%"
      % (shot, info.get("us"), info.get("gain"), m, p90, sat, dark))

W, PAD, HEAD = 1100, 16, 76
h, w = im.shape[:2]
rh = int(h * W / float(w))
canvas = Image.new("RGB", (W + PAD * 2, rh + HEAD + PAD), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 25), ImageFont.truetype(FONT, 20)
except Exception:
    f_t = f_m = ImageFont.load_default()
dr.text((PAD, 8), "表面相机 10083 · 拍摄 %s · 曝光 %sus / %sdB" % (shot, info.get("us"), info.get("gain")),
        font=f_t, fill=(255, 255, 255))
dr.text((PAD, 40), "mean %.1f · p90 %.1f · 死白(≥250) %.2f%% · 暗部(<25) %.1f%%"
        % (m, p90, sat, dark), font=f_m, fill=(255, 210, 90))
rgb = cv2.cvtColor(cv2.resize(im, (W, rh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
canvas.paste(Image.fromarray(rgb), (PAD, HEAD))
canvas.save(OUT)
print("已保存 %s (%dx%d)" % (OUT, canvas.width, canvas.height))
