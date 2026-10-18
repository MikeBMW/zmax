#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断: auto_annotate 的 VLM 标注为什么对大图返回空 content。
只调一次 call_vlm, 打印 finish_reason / usage / content 长度 / 耗时。
"""
import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import gen_overlay_from_vlm as G

cam = sys.argv[1] if len(sys.argv) > 1 else "local"
raw = urllib.request.urlopen(
    "http://127.0.0.1:8791/snapshot/%s.jpg?_=%d" % (cam, int(time.time())), timeout=15
).read()
img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
H, W = img.shape[:2]
print("源图 %dx%d %.1fKB" % (W, H, len(raw) / 1024.0))

send_w = int(os.environ.get("ZMAX_ANNOT_SEND_W", "1024"))
k = min(1.0, float(send_w) / max(W, H))
sm = cv2.resize(img, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA) if k < 1.0 else img
h2, w2 = sm.shape[:2]
ok, enc = cv2.imencode(".jpg", sm, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
print("送模型 %dx%d %.1fKB  MAXTOK=%d  MODEL=%s" % (w2, h2, len(enc) / 1024.0, G.MAXTOK, G.MODEL))

t0 = time.time()
try:
    r = G.call_vlm(enc.tobytes(), w2, h2, timeout=300)
    dt = time.time() - t0
    content = (r or {}).get("content") or ""
    print("耗时 %.1fs · content 长度 %d" % (dt, len(content)))
    for key in ("finish_reason", "usage", "model", "attempts", "err"):
        if isinstance(r, dict) and key in r:
            print("  %s: %s" % (key, json.dumps(r[key], ensure_ascii=False)[:300]))
    rea = (r or {}).get("reasoning") or ""
    print("  reasoning 长度 %d" % len(rea))
    if rea:
        print("  reasoning 前 700 字: %s" % rea[:700].replace("\n", " "))
    if content:
        print("  内容前 300 字: %s" % content[:300].replace("\n", " "))
    else:
        print("  ⚠️ content 为空")
        print("  原始返回键: %s" % list((r or {}).keys()))
except Exception as e:
    print("调用异常 %.1fs: %s: %s" % (time.time() - t0, type(e).__name__, str(e)[:300]))
