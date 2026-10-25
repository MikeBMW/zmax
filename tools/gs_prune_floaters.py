#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3DGS 飞点(floater)剪枝 + 覆盖范围体检 —— 提升「真实感」的第一道硬活。

为什么需要(2026-10-25 实测): 202 帧数据集训出的 gs.ply 包围盒 x[-1219,2215] y[-3236,316]
z[-3368,1148] mm —— 一只腕部相机在台面上扫了 0.2m 范围, 模型却铺到了 3~4 米外。
这些远点就是渲染时糊成一片雾/拉丝的来源, 也让「按当前相机位姿渲一帧」经常黑屏(射线打在空处)。

判据(可复核, 不靠眼睛):
  · 不透明度 sigmoid(opac) < --min-opa 的丢掉
  · 尺度 exp(scale) > --max-scale (米) 的丢掉(过大高斯 = 雾)
  · 到**稳健质心**的距离 > --max-radius (米) 的丢掉(飞点)
  · 稳健质心 = 按不透明度加权的坐标中位数(不被飞点拉偏)

用法:
  python gs_prune_floaters.py --ply in.ply [--out out.ply] [--max-radius 1.2] [--min-opa 0.02] [--max-scale 0.3]
  不带 --out 只体检(打印统计与建议), 不改文件。
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

sys.path.insert(0, "/home/intel/zmax_map/tools")
sys.path.insert(0, "/home/ubuntu/zmax/tools")
from gs_render_stream_intel import read_gs_ply  # noqa: E402


def stats(name, v, unit=1.0, q=(5, 50, 95)):
    qs = np.percentile(v, q) * unit
    print("  %-16s p5=%.3f p50=%.3f p95=%.3f %s" % (name, qs[0], qs[1], qs[2], ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ply", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--min-opa", type=float, default=0.02)
    ap.add_argument("--max-scale", type=float, default=0.30, help="米; exp(scale) 超过即视为雾")
    ap.add_argument("--max-radius", type=float, default=1.20, help="米; 离稳健质心超过即视为飞点")
    a = ap.parse_args()

    P = read_gs_ply(a.ply)
    n = len(P["means"])
    opa = 1.0 / (1.0 + np.exp(-P["opac"]))
    sc = np.exp(P["scales_log"])
    m = P["means"]

    # 稳健质心: 按不透明度加权的中位数
    w = opa / opa.sum()
    order = np.argsort(m, axis=0)
    c = np.array([m[order[:, k], k][np.searchsorted(np.cumsum(w[order[:, k]]), 0.5)] for k in range(3)])
    r = np.linalg.norm(m - c, axis=1)

    print("高斯 %d 个 · 文件 %.1f MB" % (n, 0))
    print("稳健质心 (mm) = %s" % np.round(c * 1000, 0).tolist())
    stats("不透明度", opa)
    stats("高斯尺度 (m)", sc.max(1))
    stats("到质心距离 (m)", r)
    print("包围盒 mm: min %s  max %s" % (np.round(m.min(0)*1000, 0).tolist(), np.round(m.max(0)*1000, 0).tolist()))
    for t in (0.5, 1.0, 1.5, 2.0):
        print("  质心 %.1fm 内: %6.1f%%" % (t, 100.0 * (r < t).mean()))

    keep = (opa >= a.min_opa) & (sc.max(1) <= a.max_scale) & (r <= a.max_radius)
    print("\n判据: opa>=%.3f · scale<=%.2fm · r<=%.2fm" % (a.min_opa, a.max_scale, a.max_radius))
    print("保留 %d / %d = %.1f%%  (剪掉 %.1f%%)" % (keep.sum(), n, 100.0*keep.mean(), 100.0*(1-keep.mean())))
    if keep.sum():
        k = m[keep]
        print("剪后包围盒 mm: min %s max %s" % (np.round(k.min(0)*1000, 0).tolist(), np.round(k.max(0)*1000, 0).tolist()))
        print("剪后 p95 半径 %.2f m" % np.percentile(r[keep], 95))

    if a.out:
        # 逐属性过滤后按原格式写回(只改 vertex 段, header 里 element vertex 数量替换)
        import struct
        with open(a.ply, "rb") as f:
            raw_header = b""
            while True:
                ln = f.readline()
                raw_header += ln
                if ln.strip() == b"end_header":
                    break
        props, forms = [], []
        for ln in raw_header.decode("ascii", "replace").splitlines():
            if ln.startswith("property"):
                _, typ, nm = ln.split()[:3]
                props.append((nm, {"float": "f4", "float32": "f4", "double": "f8", "uchar": "u1",
                                   "uint8": "u1", "int": "i4"}.get(typ, "f4")))
        dt = np.dtype([(nm, t) for nm, t in props])
        with open(a.ply, "rb") as f:
            f.read(len(raw_header))
            body = np.frombuffer(f.read(dt.itemsize * n), dtype=dt).copy()
        body = body[keep]
        hdr = raw_header.decode("ascii").replace("element vertex %d" % n, "element vertex %d" % int(keep.sum()))
        with open(a.out, "wb") as f:
            f.write(hdr.encode("ascii"))
            f.write(body.tobytes())
        print("已写出 %s (%d 个高斯)" % (a.out, int(keep.sum())))


if __name__ == "__main__":
    main()
