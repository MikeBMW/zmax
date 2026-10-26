#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""👁 用臂相机深度图把「臂前面的东西」量成 base 坐标的盒子 (给规划避让用)

老倪 2026-10-26:「你看到你面前相机了么？你要规划一个避让这个相机的路径, 同时建立3DGS图」
  —— 光读工程配置里的围栏不够: 配置里只有 侧面检测相机 / 检测设备 / 上横梁 三个盒子,
     台面上临时出现的相机、支架、料盘都不在配置里。所以这里用**深度真值**现场量:
       D405 深度(unit 0.1mm) + K + 手眼 T_cam2tool + 当前 TCP 位姿
       → 点云投到 base 系 → 体素聚类 → 每簇给一个 AABB 盒子(毫米) + 体积 + 到当前 TCP 的距离。
     这些盒子可以直接写进 fence_store (type=box) 参与扣减, 规划自然绕开。

用法:
  python tools/scan_obstacles.py --frame /tmp/f.jpg --depth /tmp/d.png [--json out.json]
  (帧/深度从 Orin 取: http://192.168.23.66:8792/frame.jpg , /depth.png)
"""
import argparse
import json
import math
import os
import os.path as osp
import sys

import cv2
import numpy as np

MODELS = os.environ.get("ZMAX_MODELS", osp.expanduser("~/zmax/models"))
TCP_JSON = osp.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")


def rpy_to_R(rx, ry, rz):
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return np.array([[cy * cz, cz * sx * sy - cx * sz, cx * cz * sy + sx * sz],
                     [cy * sz, cx * cz + sx * sy * sz, -cz * sx + cx * sy * sz],
                     [-sy, cy * sx, cx * cy]], float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True)
    ap.add_argument("--depth", required=True)
    ap.add_argument("--json", default="")
    ap.add_argument("--voxel-mm", type=float, default=15.0)
    ap.add_argument("--min-pts", type=int, default=800)
    ap.add_argument("--above-bench-mm", type=float, default=25.0)
    a = ap.parse_args()

    hd = json.load(open(osp.join(MODELS, "handeye_state.json"), encoding="utf-8"))
    cb = json.load(open(osp.join(MODELS, "real_cam_calib.json"), encoding="utf-8"))
    X = np.array(hd["T_cam2tool"], float)
    K = np.array(cb["K"], float).reshape(3, 3)
    # 位姿真源优先 Orin 桥 /status (6 维 + 50Hz, 单位 m/rad); latest.json 只在桥不可达时兜底
    t, rpy = None, None
    try:
        import urllib.request
        st = json.loads(urllib.request.urlopen("http://192.168.23.66:39061/status",
                                               timeout=6).read())["status"]
        e = st["endInRef"]
        t = np.array([float(e[0]), float(e[1]), float(e[2])], float)
        rpy = [float(e[3]), float(e[4]), float(e[5])]
        print("[位姿] Orin 桥 endInRef (m/rad)")
    except Exception as _ex:                                                # noqa: BLE001
        tcp = json.load(open(TCP_JSON, encoding="utf-8"))
        t = np.array([float(tcp["x"]), float(tcp["y"]), float(tcp["z"])], float)
        rpy = [float(tcp.get(k) or 0.0) for k in ("rx", "ry", "rz")]
        print("[位姿] latest.json 兜底 (桥不可达: %s)" % _ex)
    T_base2tcp = np.eye(4)
    T_base2tcp[:3, :3], T_base2tcp[:3, 3] = rpy_to_R(*rpy), t
    T_base2cam = T_base2tcp @ X
    R_bc, p_bc = T_base2cam[:3, :3], T_base2cam[:3, 3]

    dep = cv2.imread(a.depth, cv2.IMREAD_UNCHANGED)
    if dep is None or dep.dtype != np.uint16:
        raise SystemExit("⛔ 深度不是 16 位 uint16: %s" % a.depth)
    h, w = dep.shape
    z = dep.astype(np.float32) * 0.0001                     # 0.1mm → m
    vv, uu = np.mgrid[0:h, 0:w]
    ok = (z > 0.06) & (z < 1.2)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    xc = (uu - cx) / fx * z
    yc = (vv - cy) / fy * z
    Pc = np.stack([xc[ok], yc[ok], z[ok]], 1)               # 相机光学系
    Pb = (R_bc @ Pc.T).T + p_bc                             # base 系 (米)
    Pb_mm = Pb * 1000.0

    # 台面高度 = 点云 z 的低分位众数(臂朝下看, 绝大多数点是台面)
    zs = Pb_mm[:, 2]
    hist, edges = np.histogram(zs, bins=100)
    top3 = np.argsort(hist)[-3:][::-1]
    print("[z 分布] 三个峰: " + " · ".join("%.0fmm(%d点)" % (
        edges[i] + (edges[1] - edges[0]) / 2, hist[i]) for i in top3))
    bench = float(edges[int(np.argmax(hist))] + (edges[1] - edges[0]) / 2)
    up = Pb_mm[zs > bench + a.above_bench_mm]
    print("[台面] z≈%.0fmm · 点云 %d 个 · 台面以上 %d 个 (>%.0fmm)"
          % (bench, len(Pb_mm), len(up), a.above_bench_mm))
    if len(up) < a.min_pts:
        print("[结果] 台面以上点太少(%.0f), 认为视野里没有立起来的物体" % len(up))
        return 0

    # 体素聚类 (26 邻域 BFS)
    vs = a.voxel_mm
    vi = np.floor(up / vs).astype(np.int64)
    keys = {}
    for i, k in enumerate(map(tuple, vi)):
        keys.setdefault(k, []).append(i)
    seen, clusters = set(), []
    for k in keys:
        if k in seen:
            continue
        stack, comp = [k], []
        seen.add(k)
        while stack:
            c = stack.pop()
            comp.append(c)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        n = (c[0] + dx, c[1] + dy, c[2] + dz)
                        if n in keys and n not in seen:
                            seen.add(n)
                            stack.append(n)
        idx = [i for c in comp for i in keys[c]]
        if len(idx) >= a.min_pts:
            clusters.append(np.array(idx))

    boxes = []
    for idx in clusters:
        P = up[idx]
        lo, hi = P.min(0), P.max(0)
        size = hi - lo
        ctr = (lo + hi) / 2
        d_tcp = float(np.linalg.norm(ctr / 1000.0 - t)) * 1000.0
        boxes.append({"p1_mm": [round(float(v), 1) for v in lo],
                      "p2_mm": [round(float(v), 1) for v in hi],
                      "size_mm": [round(float(v), 1) for v in size],
                      "center_mm": [round(float(v), 1) for v in ctr],
                      "n_pts": int(len(idx)), "dist_to_tcp_mm": round(d_tcp, 1)})
    boxes.sort(key=lambda b: -b["n_pts"])
    print("[物体] 找到 %d 个台面以上物体 (按点数):" % len(boxes))
    for b in boxes[:8]:
        print("   size %s mm · 中心 %s mm · %d 点 · 距TCP %.0fmm"
              % (b["size_mm"], b["center_mm"], b["n_pts"], b["dist_to_tcp_mm"]))
    out = {"bench_z_mm": round(bench, 1), "n_points": int(len(Pb_mm)),
           "tcp_mm": [round(v * 1000, 1) for v in t], "boxes": boxes,
           "frame": a.frame, "depth": a.depth}
    if a.json:
        json.dump(out, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("[落盘] %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
