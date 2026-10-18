#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印 DeepSeek 视觉响应的**完整原始结构**, 定位 249 个 completion tokens 落在哪个字段。"""
import base64
import json
import os
import time
import urllib.request

import cv2
import numpy as np


def key():
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    for ln in open(os.path.expanduser("~/.hermes/.env"), encoding="utf-8"):
        if ln.strip().startswith("DEEPSEEK_API_KEY="):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


raw = urllib.request.urlopen(
    "http://127.0.0.1:8791/snapshot/local.jpg?_=%d" % int(time.time()), timeout=15
).read()
img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
b64 = base64.b64encode(enc.tobytes()).decode()

body = {
    "model": os.environ.get("M", "deepseek-chat"),
    "max_tokens": 1200,
    "temperature": 0.2,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "用一句话描述这张图里看到的东西。"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ],
    }],
}
req = urllib.request.Request(
    "https://api.deepseek.com/v1/chat/completions",
    data=json.dumps(body).encode(),
    headers={"Authorization": "Bearer " + key(), "Content-Type": "application/json"},
)
t0 = time.time()
with urllib.request.urlopen(req, timeout=180) as r:
    d = json.loads(r.read().decode())
print("耗时 %.1fs" % (time.time() - t0))
print("顶层键:", list(d.keys()))
ch = (d.get("choices") or [{}])[0]
print("choice 键:", list(ch.keys()))
print("finish_reason:", ch.get("finish_reason"))
msg = ch.get("message") or {}
print("message 键:", list(msg.keys()))
for k, v in msg.items():
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    print("  %-18s len=%-6d %s" % (k, len(s or ""), (s or "")[:400].replace("\n", " ")))
print("usage:", json.dumps(d.get("usage"), ensure_ascii=False))
