#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""10083 表面相机降曝光 + 判据有效性验证 (降完必须验: 表面判据靠"找过曝亮条→取上边缘"量厚度)

用法: python3 tools/aoi_surface_set_expo.py <us> [gain]
"""
import json
import sys
import time
import urllib.request

import cv2
import numpy as np

BASE = "http://192.168.23.23:10083"
UA = {"User-Agent": "zmax-probe"}
us = int(sys.argv[1]) if len(sys.argv) > 1 else 25000
gain = float(sys.argv[2]) if len(sys.argv) > 2 else 1.8


def jget(path, timeout=25):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=timeout))


def post(path, timeout=40):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + path, method="POST", headers=UA),
                                            timeout=timeout))


print("改前: %s" % {k: jget("/exposure").get(k) for k in ("us", "gain", "src")})
r = post("/exposure?us=%d&gain=%s" % (us, gain))
print("写入: ok=%s us=%s gain=%s saved=%s" % (r.get("ok"), r.get("us"), r.get("gain"), bool(r.get("saved"))))
time.sleep(2)
back = jget("/exposure")
print("回读: us=%s gain=%s src=%s" % (back.get("us"), back.get("gain"), back.get("src")))

# ── 画面统计 (抓两帧, 技能: 改曝光后首帧可能仍是旧档) ──
for attempt in (1, 2):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA),
                                     timeout=25).read()
        im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        m, p90 = g.mean(), float(np.percentile(g, 90))
        sat, dark = float((g >= 250).mean() * 100), float((g < 25).mean() * 100)
        print("  画面(第%d帧): mean=%.1f p90=%.1f 死白=%.2f%% 暗部=%.1f%%"
              % (attempt, m, p90, sat, dark))
        if attempt == 2:
            break
    except Exception as e:                                        # noqa: BLE001
        print("  抓帧失败 %s" % type(e).__name__)
    time.sleep(2)

# ── 判据验证: 真拍一次, 轮询 /last_result 拿 judge_ok ──
print("\n判据验证 (POST /capture_detect → 轮询 /last_result ≤45s):")
try:
    acc = post("/capture_detect")
    print("  受理: %s" % json.dumps(acc, ensure_ascii=False)[:120])
except Exception as e:                                            # noqa: BLE001
    print("  ❌ 受理失败: %s: %s" % (type(e).__name__, str(e)[:80]))

res = None
t0 = time.time()
while time.time() - t0 < 45:
    try:
        d = jget("/last_result", timeout=12)
        if d.get("code") == 200 and (d.get("count") is not None or d.get("verdict") is not None):
            res = d
            break
    except Exception:                                             # noqa: BLE001
        pass
    time.sleep(3)

if res is None:
    print("  ⚠️ 45s 内没拿到判决 (可能仍在推理或本轮没拍成)")
else:
    print("  判决: verdict=%s count=%s ms=%s" % (res.get("verdict"), res.get("count"), res.get("ms")))
    j = res.get("judge") or {}
    if not isinstance(j, dict):          # 某些版本 judge 是字符串摘要
        print("    judge = %s" % str(j)[:160])
        j = {}
    for k in ("state", "ver", "judge_ok", "judge_why", "th_mode", "th_bar", "thick", "right_edge_x", "cover"):
        if k in j:
            print("    judge.%s = %s" % (k, j[k]))
    top = {k: res.get(k) for k in ("judge_ok", "judge_why") if k in res}
    if top:
        print("    %s" % top)
    print("\n  ⇒ %s" % ("✅ 判据仍工作" if (j.get("judge_ok") is True or j.get("state") == "ok")
                        else "❌ 判据失效/未达标 —— 降曝光废掉了表面几何判据"))
