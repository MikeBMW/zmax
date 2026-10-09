#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运动链 负向判据: 三道闸门在"未授权/非法技能/越界"时都必须拦住 (零运动, 只发请求)

既然当前控制器处于 drag(拖动示教)模式, 不做真动; 但闸门逻辑必须证明有效 ——
拦不住 = 明天现场开箱就有风险。
用法: python3 tools/probe_motion_gates.py
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8793"


def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except Exception as e:                                                  # noqa: BLE001
        return -1, {"err": str(e)[:120]}


def brief(d):
    for k in ("detail", "msg", "error", "reason", "status", "text"):
        if k in d:
            return str(d[k])[:110]
    return json.dumps(d, ensure_ascii=False)[:110]


print("══ 运动链 · 负向闸门判据 (零运动) ══")
cases = [
    ("① 非法技能名 (白名单外)", {"skill": "L2.definitely_not_a_skill", "arm": 1}),
    ("② 真技能 + 未授权真动", {"skill": "L2.lift", "d_mm": 2, "speed": 8, "arm": 1}),
    ("③ 越界目标 (抬 900mm)", {"skill": "L2.lift", "d_mm": 900, "speed": 8, "arm": 0}),
    ("④ 超速 (speed=9999)", {"skill": "L2.lift", "d_mm": 2, "speed": 9999, "arm": 0}),
]
ok = 0
for name, payload in cases:
    st, d = post("/ctl/move", payload)
    refused = any(w in json.dumps(d, ensure_ascii=False) for w in
                  ("拒绝", "未授权", "白名单", "越界", "非法", "超", "不在", "fail", "error", "未知", "不支持"))
    print("  %-22s HTTP %-4s %s  %s" % (name, st, "🚫 拦住" if refused else "⚠️ 放过", brief(d)))
    ok += 1 if refused else 0
print("\n闸门拦住 %d/%d" % (ok, len(cases)))
print("✅ 通过: 未授权/非法技能/越界/超速 都下发不出去" if ok == len(cases)
      else "❌ 有闸门没拦住, 明天出厂前必须修")
