#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch_drag_point.py —— 老倪手拖换口时"我只看不动"。

现场 2026-10-20 18:5x: 「我换个口子，拖拽，你看着」。
只读两个采样文件(rokae_tcp_sampler 落的 latest.json / state.json), **不开 SDK 会话、不发任何指令**,
好处是不跟手拖抢控制器会话。判据:
  · 拖拽段   = operationState 含 drag (或 pose 在动而 op 不是 idle)
  · 拖拽结束 = op 回 idle 且连续 1.2s 位置极差 <0.05mm
结束时把终点位姿写成候选示教点, 并给出路径统计(行程/极值/耗时), 是否入库由老倪点头。

用法:
  ./gui-venv311/bin/python tools/rokae/watch_drag_point.py --max-s 600 --out-name 插入口_拖拽
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time

POSE = "/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json"
STATE = "/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/state.json"
OUT_DIR = "/home/ubuntu/zmax/zmax_data/ar_state"


def read():
    try:
        p = json.load(open(POSE, encoding="utf-8"))
        pose = [float(p["x"]), float(p["y"]), float(p["z"])]
        quat = [float(p.get(k, 0.0)) for k in ("qx", "qy", "qz", "qw")]
        age = time.time() - os.path.getmtime(POSE)
    except Exception:                                                    # noqa: BLE001
        return None
    op = ""
    try:
        s = json.load(open(STATE, encoding="utf-8"))
        op = str(s.get("op") or s.get("operation_state") or "")
    except Exception:                                                    # noqa: BLE001
        pass
    return {"pose": pose, "quat": quat, "op": op, "age": age}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-s", type=float, default=600)
    ap.add_argument("--out-name", default="插入口_拖拽")
    ap.add_argument("--rate", type=float, default=20)
    a = ap.parse_args()

    print("[watch] 只读盯位姿(不开 SDK、不发指令) · 最长 %.0fs · 拖完自动收尾" % a.max_s, flush=True)
    t0 = time.time()
    path, dragging, still_n = [], False, 0
    last = None
    while time.time() - t0 < a.max_s:
        d = read()
        if d is None:
            time.sleep(1.0 / a.rate)
            continue
        if d["age"] > 1.5:
            print("[watch] ⚠️ 位姿真值断流 %.1fs (采样器没在跑?)" % d["age"], flush=True)
            time.sleep(0.5)
            continue
        moving = last is not None and max(abs(d["pose"][i] - last["pose"][i]) for i in range(3)) > 2e-5
        is_drag = "drag" in d["op"].lower() or (moving and "idle" not in d["op"].lower())
        if is_drag and not dragging:
            dragging = True
            path = []
            print("[watch] ▶ 拖拽开始 · TCP=[%.5f, %.5f, %.5f] op=%s"
                  % (d["pose"][0], d["pose"][1], d["pose"][2], d["op"] or "-"), flush=True)
        if dragging:
            path.append(d["pose"])
            if moving:
                still_n = 0
            else:
                still_n += 1
            # 结束判据: **op 不再是 drag** 且 1.2s 没动 (只"停住"不算 —— 手拖中途换手/停顿很常见)
            if still_n >= int(1.2 * a.rate) and "drag" not in str(d.get("op") or "").lower():
                break
        last = d
        time.sleep(1.0 / a.rate)

    d = read() or {}
    pose, quat = d.get("pose") or [0, 0, 0], d.get("quat") or [0, 0, 0, 1]
    if not path:
        print("[watch] 没看到拖拽(可能太短或 op 一直 idle)。当前 TCP=[%.5f, %.5f, %.5f]"
              % (pose[0], pose[1], pose[2]), flush=True)
        return 1
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    zs = [p[2] for p in path]
    trav = sum(math.dist(path[i], path[i - 1]) for i in range(1, len(path)))
    out = {"name": a.out_name, "recorded_at": time.strftime("%F %T"),
           "source": "rokae_tcp_sampler(latest.json) 手拖期间只读",
           "pos": [round(v, 6) for v in pose], "quat": [round(v, 6) for v in quat],
           "path": {"n": len(path), "seconds": round(len(path) / a.rate, 1),
                    "travel_mm": round(trav * 1000, 1),
                    "x_mm": [round(min(xs) * 1000, 1), round(max(xs) * 1000, 1)],
                    "y_mm": [round(min(ys) * 1000, 1), round(max(ys) * 1000, 1)],
                    "z_mm": [round(min(zs) * 1000, 1), round(max(zs) * 1000, 1)]}}
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "drag_point_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[watch] ■ 拖拽结束 · 终点 TCP=[%.5f, %.5f, %.5f]" % (pose[0], pose[1], pose[2]), flush=True)
    print("[watch]   姿态 quat=[%.4f, %.4f, %.4f, %.4f]" % tuple(quat), flush=True)
    print("[watch]   行程 %.1fmm / %.1fs · x %s y %s z %s (mm)"
          % (out["path"]["travel_mm"], out["path"]["seconds"],
             out["path"]["x_mm"], out["path"]["y_mm"], out["path"]["z_mm"]), flush=True)
    print("[watch]   候选点已存: %s (未入点库, 待老倪点头)" % p, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
