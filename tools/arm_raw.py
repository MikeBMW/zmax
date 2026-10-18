#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_raw.py —— 不依赖"回执日志"的移动/夹爪执行器

为什么需要它(2026-10-18 收工现场实测):
  grasp_opt.G.send() 靠扫描 zmax_data/rokae_sdk/logs/agent_YYYYMMDD.jsonl 等回执;
  今晚那个文件**不存在**(目录里只有 sdk_ctl_stop_*.json) ⇒ 动作其实执行了(臂真的从 139.5 走到 167.4),
  但脚本等不到回执, 90s 后判 TIMEOUT 并停手, 于是一步步卡住。
  ⇒ 改成: **只写 FIFO 下发, 然后用 /pose 轮询到位**, 不依赖任何日志。

用法:
  arm_raw.py move --to 653.3,210.7,220.2 --abc 143.2,-85.58,37.74 --speed 25
  arm_raw.py grip open|close
  arm_raw.py pos
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
CTL = "http://127.0.0.1:8793"


def http(path, timeout=6):
    return json.load(urllib.request.urlopen(CTL + path, timeout=timeout))


def pos():
    d = http("/pose")
    return [v * 1000.0 for v in d["xyz"]], [v for v in d["abc_deg"]]


def status():
    s = http("/ctl/status")
    r = s.get("robot", {})
    return s.get("motion_armed"), r.get("power"), r.get("estop"), r.get("operation")


def fifo_write(obj):
    line = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
    for _ in range(40):
        try:
            fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            time.sleep(0.25)
            continue
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        return True
    return False


def wait_tcp(tgt, timeout=120.0, tol=2.5):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        p, _a = pos()
        d = math.dist(p, tgt)
        last = d
        if d < tol:
            return True, time.time() - t0, d
        time.sleep(0.35)
    return False, time.time() - t0, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=["move", "grip", "pos", "status"])
    ap.add_argument("--to", default="")
    ap.add_argument("--abc", default="")
    ap.add_argument("--speed", type=float, default=25.0)
    ap.add_argument("--timeout", type=float, default=120.0)
    a = ap.parse_args()

    if a.op == "pos":
        print(pos())
        return 0
    if a.op == "status":
        print("armed=%s power=%s estop=%s op=%s" % status())
        return 0
    if a.op == "grip":
        ok = fifo_write({"skill": "L2.grip_open" if a.to.startswith("open") else "L2.grip_close", "speed": 20.0})
        print("下发 grip 张/合:", ok)
        return 0 if ok else 2

    tgt = [float(v) for v in a.to.split(",")]
    req = {"cmd": "move-abs", "x": tgt[0] / 1000.0, "y": tgt[1] / 1000.0, "z": tgt[2] / 1000.0,
           "speed": a.speed, "motion": "J", "allow_movej_retry": True}
    if a.abc:
        rpy = [float(v) for v in a.abc.split(",")]
        req["rx"], req["ry"], req["rz"] = [math.radians(v) for v in rpy]
        print("目标含姿态(rx/ry/rz 弧度):", [round(math.radians(v), 3) for v in rpy])
    p0, _ = pos()
    print("起点", [round(v, 1) for v in p0], "→ 目标", tgt)
    if not fifo_write(req):
        print("FIFO 写不进去(守护进程没读端?)")
        return 2
    ok, dt, d = wait_tcp(tgt, a.timeout)
    p1, _ = pos()
    print("%s: 用时 %.1fs · 终点 %s · 残差 %s" % ("到位" if ok else "未到位(超时)", dt,
                                             [round(v, 1) for v in p1], round(d, 1) if d else d))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
