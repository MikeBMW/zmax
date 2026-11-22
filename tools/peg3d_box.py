#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peg3d_box.py — YOLO 2D 框 + D405 深度 → 相机坐标系 3D 包围盒(米制), 并投影回图像自校验。

管线(每步都可核):
  ① 取色图(848x480) + 16 位深度图(毫米, 同分辨率);
  ② YOLO 出 2D 框 → 框内深度点反投影成点云 (X=(u-cx)/fx·Z, Y=(v-cy)/fy·Z, Z=d/1000);
  ③ RANSAC 拟台面平面, 只留高出平面 ≥6mm 的点(去掉料盘底面);
  ④ 最大连通块 PCA → 三个主方向 → 有向包围盒(中心 + 长宽高);
  ⑤ 8 角点投影回图像, 与 2D 框叠画 —— 若 3D 框投影落不进 2D 框, 说明标定/深度有问题。

用法:
  python tools/peg3d_box.py [--out out.jpg] [--src-http HOST:PORT]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

import cv2
import numpy as np

MODEL = "/home/ubuntu/zmax/models/yolo_peg_live.pt"
CONF = float(os.environ.get("ZMAX_YOLO_CONF", "0.35"))
STAND_H = 0.006          # 高出台面 6mm 以上才算工件
PEG_SPEC = (72.0, 18.35, 8.5)   # QSFP28 盒 长×宽×高 mm


def _http(url: str, timeout=6) -> bytes:
    return urllib.request.urlopen(url, timeout=timeout).read()


def backproject(depth_mm: np.ndarray, K: dict, mask: np.ndarray):
    vs, us = np.nonzero(mask)
    # ⚠ 单位坑: 这台 D405 深度图是 0.1mm/unit(实测 3044 ⇒ 304mm), 不是 1mm/unit
    z = depth_mm[vs, us].astype(np.float32) * 1e-4
    ok = (z > 0.05) & (z < 2.0)
    us, vs, z = us[ok], vs[ok], z[ok]
    x = (us - K["cx"]) / K["fx"] * z
    y = (vs - K["cy"]) / K["fy"] * z
    return np.stack([x, y, z], axis=1), us, vs


def plane_ransac(P: np.ndarray, thresh=0.003, iters=300) -> tuple[np.ndarray, float]:
    """返回平面法向 n、距离 d: n·X + d = 0 (取点数最多的平面)。"""
    rng = np.random.default_rng(0)
    best, best_n, best_d = -1, None, None
    for _ in range(iters):
        idx = rng.choice(len(P), 3, replace=False)
        p0, p1, p2 = P[idx]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-9:
            continue
        n = n / nn
        d = -n.dot(p0)
        cnt = int((np.abs(P @ n + d) < thresh).sum())
        if cnt > best:
            best, best_n, best_d = cnt, n, d
    return best_n, best_d


def aabb(P: np.ndarray, trim=2.0):
    """相机轴对齐包围盒: 投影回图像后与 2D 框**同向**(老倪 11-22: 「方向要与2D差不多方向」)。

    PCA 的主方向是数据决定的, 常把框拧一个角度, 看着和 2D 框对不上; 这里用相机系 X/Y/Z 三轴,
    投影出来就是矩形, 与 YOLO 的 2D 框一致。边界取 2%~98% 分位, 去掉个别飞点。
    """
    lo = np.percentile(P, trim, axis=0)
    hi = np.percentile(P, 100.0 - trim, axis=0)
    center = (lo + hi) / 2.0
    dims = hi - lo
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    return center, dims, corners, np.eye(3)


def obb(P: np.ndarray):
    c = P.mean(axis=0)
    Q = P - c
    w, V = np.linalg.eigh(Q.T @ Q)
    order = np.argsort(w)[::-1]
    V = V[:, order]
    local = Q @ V
    lo, hi = local.min(axis=0), local.max(axis=0)
    center = c + V @ ((lo + hi) / 2)
    dims = hi - lo
    corners = []
    for sx in (lo[0], hi[0]):
        for sy in (lo[1], hi[1]):
            for sz in (lo[2], hi[2]):
                corners.append(center + V @ np.array([sx - (lo[0] + hi[0]) / 2,
                                                      sy - (lo[1] + hi[1]) / 2,
                                                      sz - (lo[2] + hi[2]) / 2]))
    return center, dims, np.array(corners), V


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.environ.get("ZMAX_RS", "192.168.23.66:8794"))
    ap.add_argument("--out", default="/home/ubuntu/zmax/zmax_data/percept/peg3d_box.jpg")
    a = ap.parse_args()
    base = "http://" + a.src

    jpg = _http(base + "/frame.jpg")
    im = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    png = _http(base + "/depth.png")
    dep = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    K = json.loads(_http(base + "/intrinsics"))
    print("图 %s 深度 %s K fx=%.2f fy=%.2f cx=%.2f cy=%.2f"
          % (im.shape[1::-1], dep.shape, K["fx"], K["fy"], K["cx"], K["cy"]))
    if im.shape[:2] != dep.shape[:2]:
        dep = cv2.resize(dep, (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST)
        print("⚠ 色/深分辨率不同, 已最近邻缩放(几何精度下降)")

    from ultralytics import YOLO
    m = YOLO(MODEL)
    r = m.predict(im, conf=CONF, device="cpu", verbose=False)[0]
    if not len(r.boxes):
        print("✗ 无检出, 不出 3D 框")
        cv2.imwrite(a.out, im)
        return 2

    out = im.copy()
    for bi, b in enumerate(r.boxes):
        x1, y1, x2, y2 = [int(float(v)) for v in b.xyxy[0]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(im.shape[1] - 1, x2), min(im.shape[0] - 1, y2)
        mask = np.zeros(dep.shape, np.uint8)
        mask[y1:y2 + 1, x1:x2 + 1] = 1
        P, us, vs = backproject(dep, K, mask)
        if len(P) < 200:
            print("  ⚠ 框%d 深度点太少(%d)" % (bi, len(P)))
            continue
        n, d = plane_ransac(P)
        if n is None:
            continue
        # 平面朝相机一侧(法向与视线相反) → 高度用 |n·X+d|
        h = np.abs(P @ n + d)
        top = P[h > STAND_H]
        if len(top) < 150:
            print("  ⚠ 框%d 台面以上点太少(%d/%d)" % (bi, len(top), len(P)))
            continue
        # 📐 图像对齐 3D 框(老倪 11-22: 「方向要与 2D 差不多方向」):
        #    水平/垂直范围直接由 2D 框的像素范围 × 该处深度换算, 厚度用台面以上点的稳健深度跨度。
        #    这样投影回来与 YOLO 的 2D 框同向、同大小, 不会出现"框拧着"的观感。
        zc = float(np.median(top[:, 2]))
        X0 = (x1 - K["cx"]) / K["fx"] * zc
        X1 = (x2 - K["cx"]) / K["fx"] * zc
        Y0 = (y1 - K["cy"]) / K["fy"] * zc
        Y1 = (y2 - K["cy"]) / K["fy"] * zc
        Z0 = float(np.percentile(top[:, 2], 10))
        Z1 = float(np.percentile(top[:, 2], 90))
        center = np.array([(X0 + X1) / 2, (Y0 + Y1) / 2, (Z0 + Z1) / 2])
        dims = np.array([abs(X1 - X0), abs(Y1 - Y0), abs(Z1 - Z0)])
        corners = np.array([[x, y, z]
                            for x in (min(X0, X1), max(X0, X1))
                            for y in (min(Y0, Y1), max(Y0, Y1))
                            for z in (Z0, Z1)])
        dims_mm = np.sort(dims) * 1000.0
        print("  框%d conf=%.2f  3D 中心(mm) %.1f,%.1f,%.1f  尺寸(排序 mm) %.1f × %.1f × %.1f  点 %d"
              % (bi, float(b.conf), *(center * 1000), *dims_mm, len(top)))
        # 🔍 点云实测(不受 2D 框松紧影响): 相机轴对齐, 取 1~99 分位去飞点
        lo1 = np.percentile(top, 1, axis=0)
        hi1 = np.percentile(top, 99, axis=0)
        pc_dims = np.sort(hi1 - lo1) * 1000.0
        print("     点云实测(mm, 1~99%%): %.1f × %.1f × %.1f   最长边差 %.1fmm"
              % (*pc_dims, abs(pc_dims[2] - PEG_SPEC[0])))
        print("     理论 QSFP28: %.1f × %.1f × %.1f mm" % PEG_SPEC)
        # 8 角点投影
        uv = [(int(K["fx"] * c[0] / c[2] + K["cx"]), int(K["fy"] * c[1] / c[2] + K["cy"]))
              for c in corners if c[2] > 0.05]
        if len(uv) == 8:
            edges = [(0,1),(1,3),(3,2),(2,0),(4,5),(5,7),(7,6),(6,4),(0,4),(1,5),(2,6),(3,7)]
            for i, j in edges:
                cv2.line(out, uv[i], uv[j], (60, 220, 60), 2, cv2.LINE_AA)
            for p in uv:
                cv2.circle(out, p, 3, (60, 220, 60), -1)
        cv2.rectangle(out, (x1, y1), (x2, y2), (60, 160, 255), 2)
        txt = "%.0fx%.0fx%.0fmm  Z=%.0fmm" % (dims_mm[2], dims_mm[1], dims_mm[0], center[2] * 1000)
        cv2.putText(out, txt, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 220, 60), 2, cv2.LINE_AA)

    cv2.imwrite(a.out, out)
    print("标注 → %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
