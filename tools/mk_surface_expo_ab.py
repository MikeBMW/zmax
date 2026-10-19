#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曝光 A/B: 同一场景两档曝光, 各抓一帧 + 各验一次判据, 出并排对比图。
目的: 把「judge_ok=False」归因到曝光 (而不是本轮工件/姿态偶然)。
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
OUT = os.path.expanduser("~/zmax/data/deliver/surface_expo_ab_%s.png" % time.strftime("%Y%m%d_%H%M%S"))


def jget(p, t=25):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + p, headers=UA), timeout=t))


def post(p, t=40):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + p, method="POST", headers=UA), timeout=t))


def grab():
    for _ in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA),
                                         timeout=25).read()
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                return im
        except Exception:                                          # noqa: BLE001
            time.sleep(2)
    return None


def verify():
    """真拍一次并轮询判决, 返回 (verdict, count, judge_ok, why)"""
    try:
        post("/capture_detect")
    except Exception as e:                                         # noqa: BLE001
        return None, None, None, "受理失败 %s" % type(e).__name__
    t0 = time.time()
    while time.time() - t0 < 50:
        try:
            d = jget("/last_result", t=12)
            if d.get("code") == 200 and d.get("verdict") is not None:
                return d.get("verdict"), d.get("count"), d.get("judge_ok"), str(d.get("judge_why") or "")[:70]
        except Exception:                                          # noqa: BLE001
            pass
        time.sleep(3)
    return None, None, None, "50s 未出判决"


def met(im):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    return g.mean(), float(np.percentile(g, 90)), float((g >= 250).mean() * 100), float((g < 25).mean() * 100)


shots = []
for us in (48000, 25000):
    post("/exposure?us=%d&gain=1.8" % us)
    time.sleep(2)
    im = grab()
    time.sleep(1)
    im = grab() if im is not None else im
    v, n, ok, why = verify()
    if im is None:
        print("  %dus 抓帧失败" % us)
        continue
    m, p90, sat, dark = met(im)
    shots.append({"us": us, "im": im, "mean": m, "p90": p90, "sat": sat, "dark": dark,
                  "verdict": v, "count": n, "judge_ok": ok, "why": why})
    print("  %6dus mean=%5.1f p90=%5.1f 死白=%4.2f%% 暗部=%4.1f%% | verdict=%s count=%s judge_ok=%s %s"
          % (us, m, p90, sat, dark, v, n, ok, why))

if len(shots) < 2:
    raise SystemExit("样本不足")

COL, PAD, HEAD, TOPM = 660, 14, 96, 34
h, w = shots[0]["im"].shape[:2]
rh = int(h * COL / float(w))
canvas = Image.new("RGB", (COL * 2 + PAD * 3, rh + HEAD + TOPM + 70), (24, 24, 24))
dr = ImageDraw.Draw(canvas)
try:
    f_t, f_m = ImageFont.truetype(FONT, 24), ImageFont.truetype(FONT, 19)
except Exception:
    f_t = f_m = ImageFont.load_default()
dr.text((PAD, 8), "表面相机 10083 曝光 A/B · 同一场景 · %s" % time.strftime("%H:%M:%S"),
        font=f_t, fill=(255, 255, 255))
for i, s in enumerate(shots):
    x = PAD + i * (COL + PAD)
    okc = (120, 220, 160) if s["judge_ok"] else (255, 120, 120)
    dr.text((x, TOPM + 2), "%dus / 1.8dB" % s["us"], font=f_m, fill=(215, 215, 215))
    dr.text((x, TOPM + 26), "mean %.1f · p90 %.1f · 死白 %.2f%% · 暗部 %.1f%%"
            % (s["mean"], s["p90"], s["sat"], s["dark"]), font=f_m, fill=(255, 210, 90))
    dr.text((x, TOPM + 50), "判据 judge_ok=%s  %s" % (s["judge_ok"], s["why"]), font=f_m, fill=okc)
    rgb = cv2.cvtColor(cv2.resize(s["im"], (COL, rh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    canvas.paste(Image.fromarray(rgb), (x, HEAD + TOPM))
    dr.rectangle([x - 1, TOPM, x + COL, HEAD + TOPM + rh], outline=(70, 70, 70))
dr.text((PAD, HEAD + TOPM + rh + 6),
        "判据靠「找过曝亮条→取上边缘/台阶」量厚度(表面 v12.1) ⇒ 曝光压低后亮条消失, 掩膜估角与直线估角对不上",
        font=f_m, fill=(255, 210, 90))
canvas.save(OUT)
print("已保存 %s" % OUT)
json.dump([{k: v for k, v in s.items() if k != "im"} for s in shots],
          open(os.path.join(os.path.dirname(OUT), "surface_expo_ab.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
