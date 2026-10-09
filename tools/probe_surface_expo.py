#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面检测 (10083) 曝光档位实验: 试拍 → 量化 → 找光模块 → 复原
纪律: 记下改前值; 每档真拍一帧存证; 结束复原 80000us x1.8 (程序落盘默认值)"""
import json
import os
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

HOST = "http://192.168.23.23:10083"
UA = {"User-Agent": "zmax-probe"}
OUT = "/home/ubuntu/zmax/reports/aoi_surface_expo_" + time.strftime("%Y%m%d_%H%M%S")
os.makedirs(OUT, exist_ok=True)


def req(url, method="GET", timeout=30):
    r = urllib.request.Request(url, method=method, headers=UA)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get_expo():
    st, b = req(HOST + "/exposure")
    try:
        return json.loads(b)
    except Exception:
        return {"raw": b[:120].decode("utf-8", "replace")}


def snap(tag):
    req(HOST + "/capture_detect", "POST")
    time.sleep(1.2)
    st, b = req(HOST + "/picture?kind=origin", timeout=40)
    if st != 200 or b[:2] != b"\xff\xd8" and b[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    p = os.path.join(OUT, tag + ".png")
    open(p, "wb").write(b)
    img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    return p, img


def describe(img):
    p50 = float(np.percentile(img, 50))
    p90 = float(np.percentile(img, 90))
    sat = float((img >= 250).mean())
    # 长细亮结构: 阈值分割 + 形态学, 找 长宽比 > 6 的连通域
    th = max(np.percentile(img, 97), 120)
    m = (img > th).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 25), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    items = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a > 3000 and max(w, h) / max(1, min(w, h)) > 4:
            items.append((int(x), int(y), int(w), int(h), int(a)))
    items.sort(key=lambda t: -t[4])
    return p50, p90, sat, items[:4]


print("=== 改前参数 ===")
before = get_expo()
print("  us=%.0f gain=%.2f src=%s ver=%s" % (before.get("us", -1), before.get("gain", -1),
                                             before.get("src"), before.get("version")))

for tag, us, gain in (("base_80000", None, None), ("hi_150000", 150000, 1.8), ("hi_300000", 300000, 1.8)):
    if us is not None:
        st, b = req("%s/exposure?us=%d&gain=%.1f" % (HOST, us, gain), "POST")
        print("\n=== 下发 %dus x %.1f → HTTP %s %s" % (us, gain, st, b[:110].decode("utf-8", "replace")))
        time.sleep(1.5)
    p, img = snap(tag)
    if img is None:
        print("  %s: 取图失败" % tag)
        continue
    p50, p90, sat, items = describe(img)
    print("  %-12s %dx%d mean=%.1f p50=%.0f p90=%.0f sat=%.3f" % (tag, img.shape[1], img.shape[0],
                                                                  img.mean(), p50, p90, sat))
    print("    长细亮结构(前4): %s" % (items if items else "无"))

print("\n=== 复原 %.0fus x %.2f ===" % (before.get("us", 80000), before.get("gain", 1.8)))
st, b = req("%s/exposure?us=%d&gain=%.2f" % (HOST, int(before.get("us", 80000)), float(before.get("gain", 1.8))), "POST")
print("  HTTP %s %s" % (st, b[:110].decode("utf-8", "replace")))
print("  复核: %s" % json.dumps(get_expo())[:160])
print("\n存证: %s" % OUT)
