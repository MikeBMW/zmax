#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📐 从世界系点云里量「料盘 / 槽位」尺寸 —— 纯离线, 不动机器人。

真源: zmax_data/gs_assets/cloud_world_1114.ply (98,448 点, 手眼标定后世界系)
方法: RANSAC 找主平面(台面/料盘面) → 平面内 2mm 栅格 → 找"被占据包围的空洞" =
      槽口 → 用槽距 49mm 交叉校验(不靠槽距定标, 只用它认对错)

输出: zmax_data/reports/tray_measure_<ts>.json + 终端表
"""
import json
import math
import os
import time

import numpy as np

REPO = os.path.expanduser("~/zmax")
PLY = os.path.join(REPO, "zmax_data", "gs_assets", "cloud_world_1114.ply")


def load_ply(p):
    """按 header 里的 property 列表构造 dtype —— 别假设只有 xyz(本文件还带 rgb)。"""
    with open(p, "rb") as f:
        hdr = b""
        while True:
            line = f.readline()
            hdr += line
            if line.strip() == b"end_header":
                break
        lines = hdr.decode(errors="ignore").split("\n")
        n = int([x for x in lines if "element vertex" in x][0].split()[-1])
        tmap = {"float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8",
                "uchar": "u1", "uint8": "u1", "int": "<i4", "uint": "<u4"}
        fields = []
        in_vertex = False
        for ln in lines:
            t = ln.strip().split()
            if len(t) >= 2 and t[0] == "element":
                in_vertex = (t[1] == "vertex")
                continue
            if in_vertex and len(t) == 3 and t[0] == "property":
                fields.append((t[2], tmap.get(t[1], "<f4")))
        dt = np.dtype(fields)
        a = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
    return np.stack([a["x"], a["y"], a["z"]], 1).astype(np.float64)


def ransac_plane(P, iters=1500, thr=0.004, seed=0):
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(iters):
        idx = rng.choice(len(P), 3, replace=False)
        p0, p1, p2 = P[idx]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n = n / nn
        d = -n @ p0
        dist = np.abs(P @ n + d)
        inl = dist < thr
        k = int(inl.sum())
        if best is None or k > best[0]:
            best = (k, n, d, inl)
    return best


def analyze_plane(P, n, d, label, cell=0.002):
    Q = P[np.abs(P @ n + d) < 0.004]
    if len(Q) < 500:
        return None
    # 平面内基底
    tmp = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, tmp); u /= np.linalg.norm(u)
    v = np.cross(n, u)
    uv = np.stack([Q @ u, Q @ v], 1)
    mn = uv.min(0); mx = uv.max(0)
    span = mx - mn
    # 栅格占据
    gx = int(math.ceil(span[0] / cell)); gy = int(math.ceil(span[1] / cell))
    if gx * gy > 4_000_000:
        return None
    occ = np.zeros((gy, gx), np.uint8)
    ij = ((uv - mn) / cell).astype(int)
    ij[:, 0] = np.clip(ij[:, 0], 0, gx - 1)
    ij[:, 1] = np.clip(ij[:, 1], 0, gy - 1)
    occ[ij[:, 1], ij[:, 0]] = 1
    # 封闭空隙: 未占据且四邻域都(间接)被占 —— 用形态学填洞近似
    try:
        import cv2
        filled = occ.copy()
        h, w = occ.shape
        mask = np.zeros((h + 2, w + 2), np.uint8)
        inv = (1 - occ).astype(np.uint8) * 255
        cv2.floodFill(inv, mask, (0, 0), 0)
        holes = (inv > 0) & (occ == 0)
        n_lab, lab, stats, cent = cv2.connectedComponentsWithStats(holes.astype(np.uint8), 8)
    except Exception:
        return None
    out = []
    for i in range(1, n_lab):
        x, y, w, h, area = stats[i]
        aw, ah = w * cell * 1000, h * cell * 1000
        a = area * cell * cell * 1e6
        if 4 <= aw <= 120 and 4 <= ah <= 120 and a >= 40:
            out.append({"w_mm": round(aw, 1), "h_mm": round(ah, 1), "area_mm2": round(a, 0),
                        "cx": round(float(cent[i][0]) * cell * 1000, 1),
                        "cy": round(float(cent[i][1]) * cell * 1000, 1)})
    return {"label": label, "n_inliers": int(len(Q)), "span_mm": [round(s * 1000, 1) for s in span],
            "holes": out, "plane_n": [round(float(x), 3) for x in n]}


def main():
    P = load_ply(PLY)
    print("点云 %d 点 · 范围 x %.3f~%.3f y %.3f~%.3f z %.3f~%.3f"
          % (len(P), P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(),
             P[:, 2].min(), P[:, 2].max()))
    sub = P[np.random.default_rng(1).choice(len(P), min(20000, len(P)), replace=False)]
    results = []
    used = np.zeros(len(sub), bool)
    Q = sub
    for k in range(3):
        best = ransac_plane(Q, iters=1200, thr=0.004, seed=k)
        if not best or best[0] < 400:
            break
        cnt, n, d, inl = best
        r = analyze_plane(P, n, d, "平面%d" % (k + 1))
        if r:
            results.append(r)
            print("-" * 76)
            print("%s: 内点 %d · 平面内跨度 %.1f × %.1f mm · n=%s"
                  % (r["label"], r["n_inliers"], r["span_mm"][0], r["span_mm"][1], r["plane_n"]))
            if r["holes"]:
                hs = sorted(r["holes"], key=lambda h: -h["area_mm2"])[:10]
                for h in hs:
                    print("   空洞 %.1f × %.1f mm · 面积 %.0f mm² · @ (%.1f, %.1f)"
                          % (h["w_mm"], h["h_mm"], h["area_mm2"], h["cx"], h["cy"]))
            else:
                print("   无封闭空洞")
        # 去掉该平面内点继续
        dist = np.abs(Q @ n + d)
        Q = Q[dist >= 0.006]
        if len(Q) < 500:
            break

    out = os.path.join(REPO, "zmax_data", "reports", "tray_measure_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("-" * 76)
    n_holes = sum(len(r["holes"]) for r in results)
    print("合计空洞候选 %d 个 · 明细 %s" % (n_holes, out))
    print("判据: 若某平面出现 7 个 4~60mm 的矩形空洞且间距≈49mm ⇒ 就是料盘槽位")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
