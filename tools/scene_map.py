#!/usr/bin/env python3
"""场景建图 + 自主避障移动 (老倪 2026-10-18: 「你要避让长方体, 自主在这个场景里移动, 不要碰撞。
xoy 平面就是桌面。x 位置也不能小于 100mm。你自己移动, 我看看。你能建图么?」)

建图: 把围栏盒子重采样成 3D 占据栅格 (体素), 盒子外扩 SAFE_MM 作为安全墙;
      桌面 z=0 以下全禁; x < X_MIN 全禁; 机械臂基座圆柱半径 120mm 也禁 (臂根会撞)。
规划: 26 邻域 A*, 代价 = 路径长度, 允许原地八叉方向;
      输出逐段绝对点, 直接喂 move-abs / path (姿态保持不变, 只走直线运动)。

用法:
  python tools/scene_map.py --build                 # 只建图 + 打印统计
  python tools/scene_map.py --plan 600,0,350 550,-250,300   # 规划到若干航点
  python tools/scene_map.py --run 600,0,350 550,-250,300 --speed 60   # 规划并真机执行
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import time
import urllib.request

import numpy as np

REPO = os.path.expanduser("~/zmax")
FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
LOG = os.path.join(REPO, "zmax_data", "rokae_sdk", "logs", "agent_%s.jsonl" % time.strftime("%Y%m%d"))
OUT = os.path.join(REPO, "zmax_data", "ar_rs")
MAP_NPZ = os.path.join(OUT, "scene_map.npz")
MAP_JSON = os.path.join(OUT, "scene_map.json")

RES_MM = 25.0            # 体素边长
SAFE_MM = 80.0           # 盒子外扩 (工具长 258mm, 只按 TCP 规划 ⇒ 留足余量)
X_MIN_MM = 100.0         # 老倪: x 不能小于 100mm
Z_MIN_MM = 40.0          # 桌面以上留 40mm
BASE_R_MM = 120.0        # 基座圆柱禁入半径
REACH_MM = 800.0         # 实测可达半径 (0.81m 能到, 0.83m 控制器不动)
BOUND = {"x": (0.05, 0.90), "y": (-0.60, 0.60), "z": (0.0, 0.85)}


def get(url, timeout=6):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def build_map():
    items = get("http://127.0.0.1:8797/api/fence").get("items") or []
    nx = int(round((BOUND["x"][1] - BOUND["x"][0]) * 1000 / RES_MM))
    ny = int(round((BOUND["y"][1] - BOUND["y"][0]) * 1000 / RES_MM))
    nz = int(round((BOUND["z"][1] - BOUND["z"][0]) * 1000 / RES_MM))
    occ = np.zeros((nx, ny, nz), dtype=bool)
    xs = BOUND["x"][0] * 1000 + (np.arange(nx) + 0.5) * RES_MM
    ys = BOUND["y"][0] * 1000 + (np.arange(ny) + 0.5) * RES_MM
    zs = BOUND["z"][0] * 1000 + (np.arange(nz) + 0.5) * RES_MM
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    who = {}
    # ① 盒子 (外扩 SAFE_MM)
    for it in items:
        if it.get("type") != "box" or not it.get("enabled", True):
            continue
        p1 = np.array(it["p1"]) * 1000.0
        p2 = np.array(it["p2"]) * 1000.0
        lo = np.minimum(p1, p2) - SAFE_MM
        hi = np.maximum(p1, p2) + SAFE_MM
        m = ((X >= lo[0]) & (X <= hi[0]) & (Y >= lo[1]) & (Y <= hi[1]) & (Z >= lo[2]) & (Z <= hi[2]))
        occ |= m
        who[it["name"]] = int(m.sum())
    # ② 桌面以下 / x 太小 / 基座圆柱 / 超出可达
    hard = (Z < Z_MIN_MM) | (X < X_MIN_MM)
    r = np.sqrt(X ** 2 + Y ** 2 + Z ** 2)
    hard |= (r > REACH_MM)
    hard |= (np.sqrt(X ** 2 + Y ** 2) < BASE_R_MM) & (Z < 700)
    occ |= hard
    free = ~occ
    np.savez_compressed(MAP_NPZ, occ=occ, xs=xs, ys=ys, zs=zs, res=RES_MM)
    info = {"built": time.strftime("%F %T"), "res_mm": RES_MM, "safe_mm": SAFE_MM,
            "shape": [nx, ny, nz], "free": int(free.sum()), "occ": int(occ.sum()),
            "free_ratio": round(float(free.mean()), 4), "by_fence": who,
            "bounds_mm": {k: [v[0] * 1000, v[1] * 1000] for k, v in BOUND.items()},
            "rules": {"x_min_mm": X_MIN_MM, "z_min_mm": Z_MIN_MM, "base_r_mm": BASE_R_MM,
                      "reach_mm": REACH_MM, "fence_inflate_mm": SAFE_MM}}
    with open(MAP_JSON, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=1)
    return occ, xs, ys, zs, info


def load_map():
    if not os.path.exists(MAP_NPZ):
        return build_map()
    d = np.load(MAP_NPZ)
    info = json.load(open(MAP_JSON, encoding="utf-8"))
    return d["occ"], d["xs"], d["ys"], d["zs"], info


def w2i(xs, ys, zs, p):
    ix = int(np.clip(np.searchsorted(xs, p[0]), 0, len(xs) - 1))
    iy = int(np.clip(np.searchsorted(ys, p[1]), 0, len(ys) - 1))
    iz = int(np.clip(np.searchsorted(zs, p[2]), 0, len(zs) - 1))
    return ix, iy, iz


def nearest_free(occ, xs, ys, zs, p, rad=6):
    i, j, k = w2i(xs, ys, zs, p)
    if not occ[i, j, k]:
        return i, j, k
    best = None
    for di in range(-rad, rad + 1):
        for dj in range(-rad, rad + 1):
            for dk in range(-rad, rad + 1):
                a, b, c = i + di, j + dj, k + dk
                if 0 <= a < occ.shape[0] and 0 <= b < occ.shape[1] and 0 <= c < occ.shape[2] and not occ[a, b, c]:
                    d = di * di + dj * dj + dk * dk
                    if best is None or d < best[0]:
                        best = (d, a, b, c)
    return None if best is None else best[1:]


def astar(occ, start, goal):
    nx, ny, nz = occ.shape
    nbrs = [(di, dj, dk) for di in (-1, 0, 1) for dj in (-1, 0, 1) for dk in (-1, 0, 1)
            if not (di == dj == dk == 0)]
    def h(a, b):
        return math.dist(a, b)
    openq = [(h(start, goal), 0.0, start)]
    came = {}
    gsc = {start: 0.0}
    seen = set()
    while openq:
        _, g, cur = heapq.heappop(openq)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        if cur in seen:
            continue
        seen.add(cur)
        for d in nbrs:
            nb = (cur[0] + d[0], cur[1] + d[1], cur[2] + d[2])
            if not (0 <= nb[0] < nx and 0 <= nb[1] < ny and 0 <= nb[2] < nz):
                continue
            if occ[nb]:
                continue
            ng = g + math.dist(cur, nb)
            if ng < gsc.get(nb, 1e18):
                gsc[nb] = ng
                came[nb] = cur
                heapq.heappush(openq, (ng + h(nb, goal), ng, nb))
    return None


def simplify(pts_mm, step_mm=40.0):
    """把体素级折线压成稀疏航点 (每段 ≥step_mm, 保留拐点)."""
    if len(pts_mm) < 3:
        return pts_mm
    out = [pts_mm[0]]
    last = np.array(pts_mm[0])
    prev_dir = None
    for p in pts_mm[1:-1]:
        v = np.array(p) - last
        d = v / (np.linalg.norm(v) or 1.0)
        turn = 0.0 if prev_dir is None else math.degrees(math.acos(max(-1, min(1, float(d @ prev_dir)))))
        if turn > 12.0 or np.linalg.norm(v) >= step_mm:
            out.append(p)
            prev_dir = d
            last = np.array(p)
    out.append(pts_mm[-1])
    return out


def plan(goals_mm, verbose=True):
    occ, xs, ys, zs, info = load_map()
    cur = get("http://127.0.0.1:8793/pose")
    here = [cur["xyz"][0] * 1000, cur["xyz"][1] * 1000, cur["xyz"][2] * 1000]
    s = nearest_free(occ, xs, ys, zs, here)
    if s is None:
        raise SystemExit("当前位姿在占据格里没有空闲邻居: %s" % np.round(here, 1))
    route = [here]
    cell = s
    legs = []
    for g in goals_mm:
        gi = nearest_free(occ, xs, ys, zs, g)
        if gi is None:
            print("⚠ 目标 %s 全被占据, 跳过" % g)
            continue
        path = astar(occ, cell, gi)
        if path is None:
            print("⚠ 到 %s 无解 (被围栏封死), 跳过" % g)
            continue
        pts = [[xs[a], ys[b], zs[c]] for a, b, c in path]
        pts = simplify(pts)
        pts[0] = route[-1]
        legs.append(pts)
        route += pts[1:]
        cell = gi
        if verbose:
            print("  航点 %s ← %d 个体素 → %d 个稀疏点" % (g, len(path), len(pts)))
    return legs, route, info


def send(req, wait=180.0):
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


def run(goals_mm, speed, dry):
    occ, xs, ys, zs, info = load_map()
    legs, route, _ = plan(goals_mm)
    if not legs:
        raise SystemExit("没有可走的航段")
    total = sum(math.dist(legs[k][i], legs[k][i + 1]) for k in range(len(legs)) for i in range(len(legs[k]) - 1))
    print("规划: %d 段 / %d 个点 / 合计 %.0fmm (体素 %.0fmm, 外扩 %.0fmm)"
          % (len(legs), sum(len(l) for l in legs), total, RES_MM, SAFE_MM))
    allp = [p for l in legs for p in l]
    gb = {"x": [min(p[0] for p in allp) / 1000 - 0.03, max(p[0] for p in allp) / 1000 + 0.03],
          "y": [min(p[1] for p in allp) / 1000 - 0.03, max(p[1] for p in allp) / 1000 + 0.03],
          "z": [max(0.02, min(p[2] for p in allp) / 1000 - 0.03), max(p[2] for p in allp) / 1000 + 0.03]}
    print("guard_box = %s" % {k: [round(v, 3) for v in gb[k]] for k in gb})
    if dry:
        for k, l in enumerate(legs):
            print("  段%d: %s" % (k + 1, [[round(v) for v in p] for p in l]))
        return 0
    # 一段一个 path 命令 (端点 zone 混合 ⇒ 不停), 姿态沿用当前
    for k, l in enumerate(legs):
        base = l[0]
        deltas = [[l[i][0] - l[i - 1][0], l[i][1] - l[i - 1][1], l[i][2] - l[i - 1][2]] for i in range(1, len(l))]
        req = {"id": "tour%d_%d" % (k, int(time.time())), "cmd": "path", "points": deltas,
               "speed": speed, "zone": 8, "guard_box": gb}
        d = send(req, wait=30 + total / max(1.0, speed) * 3)
        print("段%d: rc=%s %s" % (k + 1, d.get("rc"), str(d.get("verdict"))[:110]))
        if d.get("rc") not in (0,):
            print("⛔ 停在段%d, 不再继续" % (k + 1))
            return d.get("rc")
    p = get("http://127.0.0.1:8793/pose")
    print("终点 TCP = %s mm" % [round(v * 1000, 1) for v in p["xyz"]])
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--plan", nargs="*", default=None)
    ap.add_argument("--run", nargs="*", default=None)
    ap.add_argument("--speed", type=float, default=60.0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.build or (a.plan is None and a.run is None):
        occ, xs, ys, zs, info = build_map()
        print("建图完成: 体素 %.0fmm · 形状 %s · 空闲 %.1f%% · 占据 %.1f%%"
              % (info["res_mm"], info["shape"], info["free_ratio"] * 100, (1 - info["free_ratio"]) * 100))
        for k, v in info["by_fence"].items():
            print("   %-14s 占 %6d 体素" % (k, v))
        print("调参: x≥%.0fmm · z≥%.0fmm · 基座圆柱 r%.0fmm · 可达 %.0fmm · 围栏外扩 %.0fmm"
              % (X_MIN_MM, Z_MIN_MM, BASE_R_MM, REACH_MM, SAFE_MM))
        print("地图: %s / %s" % (MAP_NPZ, MAP_JSON))
    if a.plan is not None or a.run is not None:
        goals = [[float(x) for x in s.split(",")] for s in (a.run if a.run is not None else a.plan)]
        run(goals, a.speed, dry=(a.dry or a.run is None))


if __name__ == "__main__":
    main()
