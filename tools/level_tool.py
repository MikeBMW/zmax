#!/usr/bin/env python3
"""把 tool1 模块末端的轴放平 (逐步小角度转, 每步掺一点位移).

背景 (2026-10-18 实测):
  · 纯姿态 MoveL/MoveJ (位移 0) 控制器**静默忽略** —— 回 PASS/Δ=0 但姿态不动
  · 一次转 43° ⇒ 50102 奇异点/未执行; 一次转 10° + 2mm 位移 ⇒ 正常执行
  ⇒ 做法: 每步 ≤10°, 每步掺 2mm 抬升, 直到倾斜 <2°

用法: ./gui-venv311/bin/python tools/level_tool.py [--step 10] [--dz 2] [--max-steps 8] [--dry]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.request

import numpy as np

REPO = os.path.expanduser("~/zmax")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
LOG = os.path.join(REPO, "zmax_data", "rokae_sdk", "logs",
                   "agent_%s.jsonl" % time.strftime("%Y%m%d"))


def get(url):
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.loads(r.read().decode())


def rot(rpy):
    a, b, c = rpy
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def rpy_of(R):
    b = math.atan2(-R[2, 0], math.hypot(R[0, 0], R[1, 0]))
    a = math.atan2(R[2, 1], R[2, 2])
    c = math.atan2(R[1, 0], R[0, 0])
    return np.array([a, b, c])


def tool1_frame():
    """URDF 正解 → tool1 的旋转矩阵 (与 AR 页面画出来的外形同口径)."""
    u = get("http://127.0.0.1:8797/api/urdf")
    q = get("http://127.0.0.1:8797/api/tcp")["joints"]
    T = {"world": (np.eye(3), np.zeros(3))}
    ji = 0
    for j in u["joints"]:
        pR, pt = T[j["parent"]]
        R = pR @ rot(j["rpy"])
        t = pt + pR @ np.array(j["xyz"])
        if j["type"] == "revolute":
            ax = np.array(j["axis"], float)
            th = q[ji]
            ji += 1
            ax = ax / np.linalg.norm(ax)
            K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
            R = R @ (np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K))
        T[j["child"]] = (R, t)
    return T["tool1"][0]


def send(req, wait=60.0):
    rid = req["id"]
    fd = os.open(FIFO, os.O_WRONLY)
    try:
        os.write(fd, (json.dumps(req) + "\n").encode())
    finally:
        os.close(fd)
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(0.5)
        try:
            with open(LOG, encoding="utf-8") as f:
                for line in f:
                    if rid in line:
                        d = json.loads(line)
                        if d.get("id") == rid:
                            return d
        except Exception:                                               # noqa: BLE001
            pass
    return {"rc": 99, "verdict": "TIMEOUT"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=float, default=10.0, help="每步转几度 (实测 >15° 会被 50102 拒)")
    ap.add_argument("--dz", type=float, default=2.0, help="每步掺的抬升 mm (纯姿态会被静默忽略)")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    for i in range(a.max_steps):
        R1 = tool1_frame()
        z = R1[:, 2]
        tilt = math.degrees(math.asin(max(-1.0, min(1.0, z[2]))))
        print("第 %d 步前: tool1 Z=[%.3f %.3f %.3f] 倾斜 %+.1f°" % (i, z[0], z[1], z[2], tilt))
        if abs(tilt) < 2.0:
            print("✅ 已放平 (|倾斜| < 2°)")
            break
        pose = get("http://127.0.0.1:8793/pose")
        zt = z.copy()
        zt[2] = 0.0
        zt /= np.linalg.norm(zt)
        ax = np.cross(z, zt)
        if np.linalg.norm(ax) < 1e-9:
            print("轴已竖直, 无法用'放平'定义, 停")
            break
        ax /= np.linalg.norm(ax)
        ang = math.radians(min(a.step, abs(tilt)))
        if tilt < 0:
            ax = -ax
        K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
        Rd = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)
        abc = np.degrees(rpy_of(Rd @ rot(pose["abc_rad"])))
        xyz = [pose["xyz"][0], pose["xyz"][1], pose["xyz"][2] + a.dz / 1000.0]
        print("   → 转 %.1f° 到 abc=%s, 同时抬 %.1fmm" % (min(a.step, abs(tilt)), np.round(abc, 1), a.dz))
        if a.dry:
            break
        rid = "lvl_%d_%d" % (int(time.time()), i)
        d = send({"id": rid, "cmd": "move-abs", "x": xyz[0], "y": xyz[1], "z": xyz[2],
                  "rx": math.radians(abc[0]), "ry": math.radians(abc[1]), "rz": math.radians(abc[2]),
                  "speed": 8, "motion": "L", "allow_movej_retry": True,
                  "guard_box": {"x": [0.30, 0.90], "y": [-0.05, 0.50], "z": [0.20, 0.62]}})
        print("   ← rc=%s %s" % (d.get("rc"), str(d.get("verdict"))[:90]))
        if d.get("rc") not in (0,):
            print("⛔ 这一步被拒/保护停, 停下不再叠")
            break
    R1 = tool1_frame()
    z = R1[:, 2]
    print("最终 tool1 Z=[%.3f %.3f %.3f] 倾斜 %+.1f° · abc=%s"
          % (z[0], z[1], z[2], math.degrees(math.asin(max(-1.0, min(1.0, z[2])))),
             np.round(np.degrees(get("http://127.0.0.1:8793/pose")["abc_rad"]), 1)))


if __name__ == "__main__":
    main()
