#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_motion_axes.py — 奇异区姿态下逐轴放行探测 (真下发, 每步 5~10mm, 逐步核真值)

用途: 控制器报 50113/50120 奇异规避 / rc=6 疑似 50102 时, 快速判定"哪些方向还能动",
      再据结果选脱困方向。**不做任何组合动作**(每次只一条相对指令, 到位后核真值)。
"""
import json
import math
import time
import urllib.request

import numpy as np

POSE = "/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json"
API = "http://127.0.0.1:8793/ctl/move"


def pose():
    d = json.load(open(POSE, encoding="utf-8"))
    return (np.array([d["x"], d["y"], d["z"]]), np.array([d["qx"], d["qy"], d["qz"], d["qw"]]),
            float(d["ts"]))


def ang(a, b):
    return math.degrees(2 * math.acos(min(1.0, abs(float(np.dot(a, b))))))


def send(skill, key, val, speed=1000):
    body = {"skill": skill, key: float(val), "speed": float(speed), "arm": 1}
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": repr(e)[:120]}


def probe(skill, key, val, label):
    p0, q0, _ = pose()
    out = send(skill, key, val)
    time.sleep(6)
    p1, q1, ts = pose()
    dp = (p1 - p0) * 1000.0
    dq = ang(q0, q1)
    ok = float(np.linalg.norm(dp)) > 0.5 or dq > 0.5
    print("  %-18s %-16s 位移=(%+.1f,%+.1f,%+.1f)mm 姿态%+.2f°  ⇒ %s" % (
        label, "%s %.1f" % (skill, val), dp[0], dp[1], dp[2], dq, "✅动" if ok else "❌不动(控制器拒)"))
    for l in (out.get("lines") or [])[-1:]:
        print("      | %s" % l[:140])
    return ok, dp, dq


if __name__ == "__main__":
    print("── 奇异区逐轴探测 (每步真下发, 立即核真值) ──")
    for skill, key, val, lab in (
            ("L2.lift", "d_mm", 10.0, "① 上升 +10mm"),
            ("L2.backward", "d_mm", 10.0, "② 后退 -X 10mm"),
            ("L2.left", "d_mm", 10.0, "③ 向左 +Y 10mm"),
            ("L2.rot_c_neg", "deg", 5.0, "④ 绕工具Z -5°"),
            ("L2.rot_a_pos", "deg", 5.0, "⑤ 绕工具X +5°")):
        probe(skill, key, val, lab)
        time.sleep(1)
    p, q, ts = pose()
    print("── 探测后位置 [%.5f, %.5f, %.5f] ──" % (p[0], p[1], p[2]))
