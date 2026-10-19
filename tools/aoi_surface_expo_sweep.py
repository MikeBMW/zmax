#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面相机 10083 曝光扫档: 逐档 POST 真写 → 等稳定 → 量画面统计。
技能铁律: ① 写必须 POST (GET 只读); ② 改完第一帧可能仍是旧曝光/500, 要抓两帧再判。
"""
import json
import time
import urllib.request

import cv2
import numpy as np

BASE = "http://192.168.23.23:10083"
UA = {"User-Agent": "zmax-probe"}
LEVELS = [(48000, 1.8), (35000, 1.8), (25000, 1.8), (18000, 1.8)]


def read_expo():
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + "/exposure", headers=UA), timeout=10))


def write_expo(us, gain):
    url = "%s/exposure?us=%d&gain=%s" % (BASE, int(us), gain)
    req = urllib.request.Request(url, method="POST", headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=25))


def grab(tries=3):
    """取一帧 (grab=1 真拍); 技能记录改曝光后首帧可能 500, 故重试。"""
    for i in range(tries):
        try:
            req = urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA)
            raw = urllib.request.urlopen(req, timeout=25).read()
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                return im
        except Exception as e:                                   # noqa: BLE001
            print("     抓帧第%d次失败 %s" % (i + 1, type(e).__name__))
        time.sleep(2)
    return None


def met(im):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
    return g.mean(), float(np.percentile(g, 90)), float((g >= 250).mean() * 100), float((g < 25).mean() * 100)


print("原生效值: %s" % {k: read_expo().get(k) for k in ("us", "gain", "src")})
print("\n%-12s %-10s %-8s %-8s %-10s %-10s" % ("设定 us×gain", "实际回读", "mean", "p90", "死白≥250", "暗部<25"))
print("-" * 74)
rows = []
for us, gain in LEVELS:
    try:
        r = write_expo(us, gain)
        got = "%s×%s" % (r.get("us"), r.get("gain"))
        ok = r.get("us_ok", r.get("ok"))
    except Exception as e:                                        # noqa: BLE001
        print("  %-12s 写入失败 %s: %s" % ("%d×%s" % (us, gain), type(e).__name__, str(e)[:50]))
        continue
    time.sleep(1.5)                       # 等相机应用新档 + 至少出一帧
    im = grab()
    if im is None:
        print("  %-12s 写入ok=%s 但抓帧失败" % ("%d×%s" % (us, gain), ok))
        continue
    m, p90, sat, dark = met(im)
    rows.append((us, gain, m, p90, sat, dark))
    print("  %-12s %-10s %-8.1f %-8.1f %-10.2f %-10.2f" % ("%d×%s" % (us, gain), got, m, p90, sat, dark))

print("\n判读: 目标 死白≤2% 且 mean 60~200 (程序自带验收口径); 暗部<25 上升过多说明压过头")
for us, gain, m, p90, sat, dark in rows:
    verdict = "✅ 达标" if (sat <= 2.0 and 60 <= m <= 200) else ("过曝" if sat > 2.0 else "偏暗")
    print("  %6dus × %s → mean %5.1f 死白 %5.2f%% 暗部 %5.1f%% ⇒ %s" % (us, gain, m, sat, dark, verdict))
