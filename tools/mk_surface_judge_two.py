#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面判据图两版对照: A 纯刚体(minAreaRect 原尺寸, 零扩展) vs B 扩暗头(把暗的一端纳入)。
两版都只做**纯旋转**、输出尺寸==取出尺寸, 谁也不做 resize 拉伸。
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
from aoi_surface_rect import surface_judge                             # noqa: E402

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
UA = {"User-Agent": "zmax-probe"}
BASE = "http://192.168.23.23:10083"
STAMP = time.strftime("%Y%m%d_%H%M%S")
OUT = os.path.expanduser("~/zmax/data/deliver/surface_judge_two_%s.png" % STAMP)

expo = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/exposure", headers=UA), timeout=15).read())
raw = urllib.request.urlopen(urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA),
                             timeout=30).read()
src = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
shot = time.strftime("%H:%M:%S")

variants = []
for tag, kw in (("A 纯刚体 (不扩, 零变形)", dict(expand=False)), ("B 扩暗头 (整块模块)", dict(expand=True))):
    crop, ov, meta = surface_judge(src, out_long=1400, **kw)
    if crop is None:
        print("%s ⇒ 搜不到: %s" % (tag, meta.get("why")))
        continue
    ch, cw = crop.shape[:2]
    cs, os_ = list(meta.get("crop_size", [])), list(meta.get("out_size", []))
    variants.append({"tag": tag, "crop": crop, "meta": meta, "cw": cw, "ch": ch})
    print("%s ⇒ %dx%d 长宽比 %.2f 水平=%s crop_size=%s out_size=%s no_stretch=%s angle=%.2f md=%.2f"
          % (tag, cw, ch, max(cw, ch) / float(min(cw, ch)), cw > ch, cs, os_,
             meta.get("no_stretch"), float(meta.get("angle", 0)), float(meta.get("same_pixel_mean_diff", 0))))

if not variants:
    raise SystemExit("两版都搜不到")

W, PAD, TOP, HEAD = 1340, 14, 40, 118
rows = []
for v in variants:
    s = max(1, int(W / float(max(v["cw"], v["ch"]))))
    big = cv2.resize(v["crop"], (v["cw"] * s, v["ch"] * s), interpolation=cv2.INTER_NEAREST)
    rows.append((v, big, s))
H = HEAD + sum(r[1].shape[0] + TOP + 8 for r in rows) + PAD
canvas = Image.new("RGB", (W + PAD * 2, H), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 25), ImageFont.truetype(FONT, 19)
except Exception:
    f_t = f_m = ImageFont.load_default()
dr.text((PAD, 8), "表面判据图 · 光模块摆正 (长边水平) · 拍摄 %s · 曝光 %sus" % (shot, expo.get("us")),
        font=f_t, fill=(255, 255, 255))
dr.text((PAD, 40), "两版都只做纯旋转(scale=1.0), 没有 resize 拉伸; 差别只在裁剪范围", font=f_m, fill=(200, 200, 200))

y = HEAD
for v, big, s in rows:
    m = v["meta"]
    gs = cv2.cvtColor(v["crop"], cv2.COLOR_BGR2GRAY)
    dr.text((PAD, y), v["tag"], font=f_m, fill=(120, 220, 160))
    dr.text((PAD + 300, y),
            "%dx%d · 长宽比 %.2f · 倾角 %.2f° · 矩形度 %.3f · 放大%dx · mean %.1f p90 %.0f"
            % (v["cw"], v["ch"], max(v["cw"], v["ch"]) / float(min(v["cw"], v["ch"])),
               float(m.get("angle", 0)), float(m.get("fill", 0)), s, gs.mean(),
               float(np.percentile(gs, 90))), font=f_m, fill=(255, 210, 90))
    dr.text((PAD + 900, y), "crop==out: %s" % (list(m.get("crop_size", [])) == list(m.get("out_size", []))),
            font=f_m, fill=(120, 220, 160))
    y += TOP
    canvas.paste(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)), (PAD, y))
    dr.rectangle([PAD - 1, y - 1, PAD + big.shape[1], y + big.shape[0]], outline=(70, 70, 70))
    y += big.shape[0] + 8

os.makedirs(os.path.dirname(OUT), exist_ok=True)
canvas.save(OUT)
print("已保存 %s (%dx%d)" % (OUT, canvas.width, canvas.height))
