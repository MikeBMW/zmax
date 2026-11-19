#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_pose_relay_intel.py — 在 550C 上把本机(工控机)的 TCP 真值转成渲染器要的位姿文件。

为什么要在 550C 上跑:
  `gs_render_stream_intel.py` 的 --sync 只读**本地文件** `/tmp/arm_tcp_pose.json`;
  那个文件不存在 ⇒ 它就退回 `tour`(环绕路径) ⇒ 手臂没动、画面自己在转
  —— 老倪 2026-11-19: 「我的手臂机器人没有移动，怎么回事？」

链路: 1750C → http://192.168.23.50:8797/api/tcp (SDK endInRef 真值) → /tmp/arm_tcp_pose.json
格式: {"ts": epoch秒, "t": [x,y,z] 米, "q": [x,y,z,w]}
只读, 不下发任何指令。
"""
import json
import os
import time
import urllib.request

SRC = os.environ.get("ZMAX_TCP_URL", "http://192.168.23.50:8797/api/tcp")
OUT = os.environ.get("ZMAX_POSE_JSON", "/tmp/arm_tcp_pose.json")
HZ = float(os.environ.get("ZMAX_RELAY_HZ", "5"))
MAX_AGE = 2.0


def main():
    period = 1.0 / max(HZ, 0.2)
    ok = err = 0
    last_log = 0.0
    while True:
        t0 = time.time()
        try:
            with urllib.request.urlopen(SRC, timeout=2.0) as r:
                d = json.loads(r.read().decode("utf-8"))
            if not d.get("ok") or d.get("stale"):
                raise ValueError("tcp 端点说 stale/not ok: %r" % (d.get("stale"),))
            if float(d.get("age_s") or 9e9) > MAX_AGE:
                raise ValueError("真值龄 %.2fs 过旧" % float(d.get("age_s") or 9e9))
            q = d.get("quat") or []
            if len(q) != 4:
                raise ValueError("quat 不完整")
            rec = {"ts": time.time(), "t": [float(d["x"]), float(d["y"]), float(d["z"])],
                   "q": [float(v) for v in q], "src": SRC, "age_s": d.get("age_s")}
            tmp = OUT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            os.replace(tmp, OUT)
            ok += 1
        except Exception as e:                                          # noqa: BLE001
            err += 1
            if time.time() - last_log > 10:
                print("relay 失败: %r (ok=%d err=%d)" % (e, ok, err), flush=True)
                last_log = time.time()
        if time.time() - last_log > 30:
            print("relay ok=%d err=%d → %s" % (ok, err, OUT), flush=True)
            last_log = time.time()
        dt = period - (time.time() - t0)
        if dt > 0:
            time.sleep(dt)


if __name__ == "__main__":
    main()
