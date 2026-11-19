#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_ply2splat.py — 把 3DGS 的 gs.ply 转成网页查看器用的 .splat (32 字节/高斯)。

为什么要这个:
  `8793/station` 的 3D 地图层读的是本地资产 `~/zmax/zmax_data/gs_assets/<名>/gs.splat`,
  而 550C 训练只产出 `gs.ply` ⇒ 新模型不进 splat 就永远看不到 (页面还显示旧资产 rt_live)。

格式 (antimatter15 splat, 32B/点):
  f32 x, y, z           位置
  f32 sx, sy, sz        尺度 = exp(ply 里的 log-scale)
  u8  r, g, b, a        颜色 = clamp(0.2820948*f_dc+0.5), alpha = sigmoid(opacity)
  u8  qx, qy, qz, qw    旋转 = 归一化四元数 * 128 + 128

用法:
  python3 tools/gs_ply2splat.py --ply <in.ply> --out <out.splat> [--kmax 60000]
"""
import argparse
import os
import struct
import sys

import numpy as np

_TYPES = {
    "float": ("f", 4), "float32": ("f", 4), "double": ("d", 8),
    "uchar": ("B", 1), "uint8": ("B", 1),
    "int": ("i", 4), "int32": ("i", 4), "uint": ("I", 4), "uint32": ("I", 4),
    "short": ("h", 2), "int16": ("h", 2), "ushort": ("H", 2),
}


def read_ply(path):
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise SystemExit("不是 ply: %s" % path)
        fmt, n, props, elem = None, 0, [], None
        while True:
            ln = f.readline().decode("ascii", "ignore").strip()
            if ln.startswith("format"):
                fmt = ln.split()[1]
            elif ln.startswith("element vertex"):
                n = int(ln.split()[2])
                elem = "vertex"
            elif ln.startswith("element"):
                elem = ln.split()[1]
            elif ln.startswith("property") and elem == "vertex":
                t, name = ln.split()[1], ln.split()[2]
                props.append((name, t))
            elif ln == "end_header":
                break
        if fmt != "binary_little_endian":
            raise SystemExit("只支持 binary_little_endian, 实际 %s" % fmt)
        dtypes = [(_TYPES[t][0], np.dtype("<" + _TYPES[t][0])) for _, t in props]
        dt = np.dtype([(name, d) for (name, _), (_, d) in zip(props, dtypes)])
        a = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
    return a, [p for p, _ in props]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ply", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--kmax", type=int, default=0, help="0 = 全量; >0 只留最不透明的 kmax 个")
    a = ap.parse_args()

    v, props = read_ply(a.ply)
    need = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "opacity", "rot_0", "rot_1", "rot_2", "rot_3"]
    miss = [k for k in need if k not in props]
    if miss:
        raise SystemExit("ply 缺字段: %s (有: %s)" % (miss, props[:20]))
    dc = [k for k in ("f_dc_0", "f_dc_1", "f_dc_2") if k in props]
    if len(dc) != 3:
        raise SystemExit("ply 缺 f_dc_0..2")

    pos = np.stack([v["x"], v["y"], v["z"]], 1).astype(np.float32)
    scl = np.stack([np.exp(v["scale_0"].astype(np.float32)),
                    np.exp(v["scale_1"].astype(np.float32)),
                    np.exp(v["scale_2"].astype(np.float32))], 1).astype(np.float32)
    op = 1.0 / (1.0 + np.exp(-v["opacity"].astype(np.float32)))
    col = np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], 1).astype(np.float32)
    col = np.clip(0.28209479177387814 * col + 0.5, 0.0, 1.0)
    col = (col * 255.0).round().astype(np.uint8)
    alp = (np.clip(op, 0.0, 1.0) * 255.0).round().astype(np.uint8)

    q = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], 1).astype(np.float32)
    q /= np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-9)
    qu = np.clip(q * 128.0 + 128.0, 0, 255).astype(np.uint8)

    if a.kmax and len(pos) > a.kmax:
        idx = np.argpartition(alp.astype(np.int16), -a.kmax)[-a.kmax:]
        pos, scl, col, alp, qu = pos[idx], scl[idx], col[idx], alp[idx], qu[idx]

    n = len(pos)
    rec = np.zeros((n, 32), dtype=np.uint8)
    rec[:, 0:12] = pos.view(np.uint8).reshape(n, 12)
    rec[:, 12:24] = scl.view(np.uint8).reshape(n, 12)
    rec[:, 24] = col[:, 0]
    rec[:, 25] = col[:, 1]
    rec[:, 26] = col[:, 2]
    rec[:, 27] = alp
    rec[:, 28:32] = qu
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    rec.tofile(a.out)
    print("splat: %d 点 · %.2f MB → %s" % (n, n * 32 / 1e6, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
