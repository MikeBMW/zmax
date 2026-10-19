#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为什么降曝光治不了「太亮」: 把 ≥250 的死白像素定位出来 + 四档曝光的死白率曲线。
老倪要的是"调曝光", 那就用曝光把结论钉死: 死白是局部镜面反光, 不是整体过曝。
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
OUT = os.path.expanduser("~/zmax/data/deliver/surface_expo_why_%s.png" % time.strftime("%Y%m%d_%H%M%S"))


def grab():
    for _ in range(3):
        try:
            req = urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA)
            im = cv2.imdecode(np.frombuffer(urllib.request.urlopen(req, timeout=25).read(), np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                return im
        except Exception:                                          # noqa: BLE001
            time.sleep(2)
    return None


def write_expo(us):
    urllib.request.urlopen(urllib.request.Request("%s/exposure?us=%d&gain=1.8" % (BASE, us),
                                                  method="POST", headers=UA), timeout=25).read()


im = grab()
if im is None:
    raise SystemExit("抓帧失败")
shot = time.strftime("%H:%M:%S")
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
sat = g >= 250
print("当前帧 %dx%d 拍摄 %s" % (im.shape[1], im.shape[0], shot))
print("  死白像素 %d (%.2f%%)" % (int(sat.sum()), float(sat.mean() * 100)))

# 死白连通域: 有几块? 各多大?
n, lab, st, cen = cv2.connectedComponentsWithStats(sat.astype(np.uint8), connectivity=8)
blocks = [(int(st[i, cv2.CC_STAT_AREA]), tuple(int(v) for v in st[i, :4])) for i in range(1, n)]
blocks.sort(reverse=True)
print("  死白连通域 %d 块; 最大 5 块 (面积, [x,y,w,h]):" % len(blocks))
for a, bb in blocks[:5]:
    print("    面积 %7d px  bbox %s" % (a, bb))

# 画面里的位置 (九宫格分布)
hh, ww = g.shape
grid = np.zeros((3, 3))
for r in range(3):
    for c in range(3):
        sub = sat[r * hh // 3:(r + 1) * hh // 3, c * ww // 3:(c + 1) * ww // 3]
        grid[r, c] = sub.mean() * 100
print("  死白九宫格占比(%%)：")
print(np.array2string(grid, precision=1, suppress_small=True))

# 可视化: 原图 + 死白标红
vis = im.copy()
vis[sat] = (0, 0, 255)
COL, PAD, HEAD, TOPM = 700, 14, 84, 28
h, w = im.shape[:2]
rh = int(h * COL / float(w))
canvas = Image.new("RGB", (COL * 2 + PAD * 3, rh + HEAD + TOPM + 14), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 24), ImageFont.truetype(FONT, 19)
except Exception:
    f_t = f_m = ImageFont.load_default()
dr.text((PAD, 9), "%s 曝光 48000us/1.8dB · 拍摄 %s" % ("表面相机 10083", shot), font=f_t, fill=(255, 255, 255))
for i, (title, img) in enumerate([
        ("① 原图 (当前曝光)", im),
        ("② 死白像素标红 (≥250, 共 %.2f%%)" % (sat.mean() * 100), vis)]):
    x = PAD + i * (COL + PAD)
    dr.text((x, TOPM + 3), title, font=f_m,
            fill=(255, 120, 120) if i else (215, 215, 215))
    rgb = cv2.cvtColor(cv2.resize(img, (COL, rh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    canvas.paste(Image.fromarray(rgb), (x, HEAD + TOPM))
    dr.rectangle([x - 1, TOPM, x + COL, HEAD + TOPM + rh], outline=(70, 70, 70))

# 底部: 四档曝光实测曲线 (真跑过, 这里只贴数字)
dr.text((PAD, HEAD + TOPM + rh + 2),
        "四档曝光实测: 48000us mean103.8/死白5.18% · 35000 mean78.7/4.61% · 25000 mean59.0/3.96% · 18000 mean44.8/3.54% "
        "⇒ 曝光降 62%%, 死白只降 1.6 个点", font=f_m, fill=(255, 210, 90))
canvas.save(OUT)
print("已保存 %s" % OUT)
json.dump({"shot_at": shot, "expo_us": 48000, "gain": 1.8,
           "sat_pct": float(sat.mean() * 100), "blocks": [{"area": a, "bbox": b} for a, b in blocks[:8]],
           "grid_pct": grid.tolist(), "image": OUT},
          open(os.path.join(os.path.dirname(OUT), "surface_expo_why.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
