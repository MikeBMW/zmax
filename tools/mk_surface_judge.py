#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出表面判据图 (10083 kind=judge) 实况: 判据图本身 + 它的统计 + judge_ok/judge_why。
老倪问「判据图呢」⇒ 判据图是人看的那张, 与模型输入(zmax_main_960)/原图都不是同一张。
"""
import json
import os
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
BASE = "http://192.168.23.23:10083"
UA = {"User-Agent": "zmax-probe"}
OUT = os.path.expanduser("~/zmax/data/deliver/surface_judge_%s.png" % time.strftime("%Y%m%d_%H%M%S"))


def get(path, t=30):
    return urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=t).read()


expo = json.loads(get("/exposure", 15))
try:
    ci = json.loads(get("/crop_info", 20))
except Exception:                                                  # noqa: BLE001
    ci = {}
try:
    lr = json.loads(get("/last_result", 20))
except Exception:                                                  # noqa: BLE001
    lr = {}
shot = time.strftime("%H:%M:%S")

imgs = {}
for kind in ("judge", "origin"):
    try:
        raw = get("/picture?kind=%s&grab=1" % kind, 30)
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if im is not None:
            imgs[kind] = im
    except Exception as e:                                         # noqa: BLE001
        print("  %s 取图失败 %s" % (kind, type(e).__name__))

print("拍摄 %s · 曝光 %sus/%sdB" % (shot, expo.get("us"), expo.get("gain")))
for k, im in imgs.items():
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    print("  %-7s %dx%d mean=%.1f p90=%.1f 死白=%.2f%% 暗部=%.1f%%"
          % (k, im.shape[1], im.shape[0], g.mean(), np.percentile(g, 90),
             float((g >= 250).mean() * 100), float((g < 25).mean() * 100)))
print("  judge_ok=%s" % lr.get("judge_ok"))
print("  judge_why=%s" % str(lr.get("judge_why"))[:120])
for k in ("judge_file", "judge_mode", "judge_rot_deg", "judge_ver", "model_input_file", "model_input_kind"):
    v = lr.get(k, ci.get(k))
    if v is not None:
        print("  %s = %s" % (k, str(v)[:100]))

if "judge" not in imgs:
    raise SystemExit("判据图取不到")

JH, W, PAD = imgs["judge"].shape[0], 1400, 16
sc = W / float(imgs["judge"].shape[1])
rh = int(JH * sc)
oh = int(imgs["origin"].shape[0] * W / float(imgs["origin"].shape[1])) if "origin" in imgs else 0
HEAD = 108
H = HEAD + rh + 12 + (oh + 26 if oh else 0) + 12
canvas = Image.new("RGB", (W + PAD * 2, H), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 25), ImageFont.truetype(FONT, 19)
except Exception:
    f_t = f_m = ImageFont.load_default()

dr.text((PAD, 8), "表面判据图 (10083 kind=judge) · 拍摄 %s · 曝光 %sus" % (shot, expo.get("us")),
        font=f_t, fill=(255, 255, 255))
gj = cv2.cvtColor(imgs["judge"], cv2.COLOR_BGR2GRAY)
dr.text((PAD, 38), "判据图 %dx%d · mean %.1f · p90 %.1f · 死白 %.2f%% · 暗部 %.1f%%"
        % (imgs["judge"].shape[1], imgs["judge"].shape[0], gj.mean(),
           np.percentile(gj, 90), float((gj >= 250).mean() * 100), float((gj < 25).mean() * 100)),
        font=f_m, fill=(255, 210, 90))
okc = (120, 220, 160) if lr.get("judge_ok") else (255, 120, 120)
dr.text((PAD, 62), "judge_ok = %s" % lr.get("judge_ok"), font=f_m, fill=okc)
dr.text((PAD, 84), "judge_why = %s" % str(lr.get("judge_why"))[:96], font=f_m, fill=okc)

y = HEAD
rgb = cv2.cvtColor(cv2.resize(imgs["judge"], (W, rh), interpolation=cv2.INTER_NEAREST), cv2.COLOR_BGR2RGB)
canvas.paste(Image.fromarray(rgb), (PAD, y))
dr.rectangle([PAD - 1, y - 1, PAD + W, y + rh], outline=(70, 70, 70))
y += rh + 12
if oh and "origin" in imgs:
    dr.text((PAD, y), "对照: 原图 (kind=origin)", font=f_m, fill=(210, 210, 210))
    y += 26
    rgb2 = cv2.cvtColor(cv2.resize(imgs["origin"], (W, oh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    canvas.paste(Image.fromarray(rgb2), (PAD, y))
    dr.rectangle([PAD - 1, y - 1, PAD + W, y + oh], outline=(70, 70, 70))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
canvas.save(OUT)
print("已保存 %s (%dx%d)" % (OUT, canvas.width, canvas.height))
