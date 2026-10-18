# -*- coding: utf-8 -*-
"""bridge_path_recorder.py — 把**真机实际走过的 TCP 轨迹**录下来, 给 AR 三维视图画

老倪 2026-10-18: 「http://127.0.0.1:8797/ar 三维视图里, 把你的移动轨迹画出来」

真值来源: 8793 /pose (SDK endInRef 5Hz 采样) —— 不是什么规划轨迹, 是手臂**实际**到过的点。
只录"动了"的点 (<0.3mm 的抖动丢掉), 常驻 4000 点环形, 停 1.0s 落盘一次(原子替换)。

输出: zmax_data/ss_live/bridge_real_path.json
  {"ok":1, "src":"真机跟随(桥接) · SDK endInRef", "n":N, "pts":[[x,y,z]..],
   "t0":.., "t1":.., "len_mm":.., "stage":"转移", "at":"HH:MM:SS"}
"""
import json
import math
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "zmax_data", "ss_live", "bridge_real_path.json")
TRACE = os.path.join(REPO, "zmax_data", "ss_live", "trace_live.json")
POSE = "http://127.0.0.1:8793/pose"
MAXN = 4000
MOVE_MM = 0.3


def _pose():
    with urllib.request.urlopen(POSE, timeout=2.0) as r:
        d = json.loads(r.read().decode())
    return [float(x) for x in d["xyz"]]


def _stage():
    try:
        return str(json.load(open(TRACE, encoding="utf-8")).get("阶段") or "")
    except Exception:                                                             # noqa: BLE001
        return ""


def main():
    hz = 10.0
    if "--hz" in sys.argv:
        hz = float(sys.argv[sys.argv.index("--hz") + 1])
    pts, ts = [], []
    t_last_write = 0.0
    last = None
    print("🎯 录真机 TCP 轨迹 → %s (%.0fHz, 移动阈值 %.1fmm)" % (OUT, hz, MOVE_MM), flush=True)
    while True:
        try:
            p = _pose()
        except Exception as e:                                                    # noqa: BLE001
            time.sleep(1.0 / hz)
            if int(time.time()) % 10 == 0:
                print("… 读位姿失败: %s: %s" % (type(e).__name__, e), flush=True)
            continue
        if last is None or math.dist(p, last) * 1000.0 >= MOVE_MM:
            pts.append([round(v, 5) for v in p])
            ts.append(round(time.time(), 2))
            last = p
            if len(pts) > MAXN:
                pts = pts[-MAXN:]
                ts = ts[-MAXN:]
        now = time.time()
        if now - t_last_write >= 1.0:
            t_last_write = now
            length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * 1000.0
            obj = {"ok": 1, "src": "真机跟随(桥接) · SDK endInRef 实测", "n": len(pts),
                   "pts": pts, "t0": (ts[0] if ts else None), "t1": (ts[-1] if ts else None),
                   "len_mm": round(length, 1), "stage": _stage(),
                   "at": time.strftime("%H:%M:%S")}
            tmp = OUT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
            os.replace(tmp, OUT)
        time.sleep(1.0 / hz)


if __name__ == "__main__":
    main()
