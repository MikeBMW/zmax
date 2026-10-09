#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表面检测 (10083) 实测: 真拍一帧 → 取判据图/整板原图 → 量化 + 存证"""
import json
import os
import time
import urllib.error
import urllib.request

HOST = "http://192.168.23.23:10083"
UA = {"User-Agent": "zmax-probe"}
OUT = "/home/ubuntu/zmax/reports/aoi_surface_probe_" + time.strftime("%Y%m%d_%H%M%S")
os.makedirs(OUT, exist_ok=True)


def req(url, method="GET", timeout=25):
    r = urllib.request.Request(url, method=method, headers=UA)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


print("=== ① 真拍一帧 (POST /capture_detect) ===")
t0 = time.time()
st, body, _ = req(HOST + "/capture_detect", "POST")
print("  HTTP %s  %.2fs  %s" % (st, time.time() - t0, body[:120].decode("utf-8", "replace")))

print("\n=== ② 等判决 (/last_result, 轮询 ≤45s) ===")
last = None
for i in range(15):
    time.sleep(3)
    st, body, _ = req(HOST + "/last_result")
    if st == 200:
        try:
            last = json.loads(body)
        except Exception:
            continue
        if last.get("detect_type") or last.get("count") is not None:
            print("  第 %ds 拿到: %s" % ((i + 1) * 3, {k: last[k] for k in list(last)[:10] if k != "defects"}))
            break
if last:
    open(os.path.join(OUT, "last_result.json"), "w").write(json.dumps(last, ensure_ascii=False, indent=1))

print("\n=== ③ 取图 ===")
for kind, fn in (("judge", "judge.png"), ("origin", "origin.png")):
    st, body, hdr = req(HOST + "/picture?kind=" + kind, timeout=40)
    ok = st == 200 and body[:2] == b"\xff\xd8" or body[:8] == b"\x89PNG\r\n\x1a\n"
    print("  kind=%-7s HTTP %s  %8d B  %s" % (kind, st, len(body), "图 ✅" if ok else body[:80].decode("utf-8", "replace")))
    if ok:
        open(os.path.join(OUT, fn), "wb").write(body)

print("\n=== ④ 量化 (判据图/原图) ===")
try:
    import numpy as np
    import cv2
    for fn in ("judge.png", "origin.png"):
        p = os.path.join(OUT, fn)
        if not os.path.exists(p):
            continue
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        sat = float((img >= 250).mean())
        dark = float((img < 10).mean())
        print("  %-10s %sx%s  mean=%.1f p50=%.0f p90=%.0f std=%.1f sat=%.3f black=%.3f"
              % (fn, img.shape[1], img.shape[0], img.mean(), np.percentile(img, 50),
                 np.percentile(img, 90), img.std(), sat, dark))
except Exception as e:
    print("  量化失败: %s" % e)
print("\n存证目录: %s" % OUT)
print("\n=== ⑤ 8793 侧表面格状态 ===")
st, body, _ = req("http://127.0.0.1:8793/station/status")
try:
    d = json.loads(body)
    s = d["stats"].get("aoi_surface") or d["stats"].get("surface")
    print("  %s" % (json.dumps(s, ensure_ascii=False)[:300] if s else list(d["stats"].keys())))
except Exception as e:
    print("  %s (%s)" % (e, body[:100]))
