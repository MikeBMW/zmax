#!/usr/bin/env python3
"""把 D405 深度图反投影成 3DGS 初始点云 (PLY)。

为什么需要: gs_train.py 在没有初始点云时, 会在"相机前 0.28m"摆一个
0.30x0.30x0.20m 的随机盒子当初始点 —— 和真实场景毫无关系, 全靠训练去纠正,
PSNR 卡在 14~15 上不去。D405 有真实深度, 反投影出来的点直接就贴在物体表面上,
初始几何对了, 后面才有收敛空间。

约定 (与 gs_train.py 的 cameras.json 一致):
  · T_cam2world: 世界←相机 (OpenCV 光学系, z 向前)
  · 深度: uint16, unit=0.1mm (D405), 0 = 无效
  · 反投影: X_cam = ((u - cx) / fx * z, (v - cy) / fy * z, z)
            X_world = T_cam2world @ [X_cam, 1]

用法:
  python3 tools/gs_depth_to_ply.py --src <数据集目录> --out init.ply
    --src 里应有 cameras.json + images/ + depth/
    --max-points 限制输出点数 (均匀下采样)
    --min-z / --max-z 米, 过滤过近过远的坏深度
"""
import argparse
import json
import os
import os.path as osp
import sys

import numpy as np


def read_ply_header_and_points(path):
    """读 3DGS 风格 PLY 的点 (只取 xyz), 用于合并已有 PLY。"""
    raise NotImplementedError


def write_ply(path, xyz, rgb=None):
    """写二进制 little-endian PLY, 3DGS 可直接读。"""
    n = len(xyz)
    xyz = np.asarray(xyz, dtype=np.float32)
    rgb = np.zeros((n, 3), dtype=np.uint8) if rgb is None else np.asarray(rgb, dtype=np.uint8)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        rec = np.empty((n, 6), dtype=np.float32)
        rec[:, :3] = xyz
        rec[:, 3:] = rgb.astype(np.float32)
        # 逐字段混合类型: 用 structured array 才对
        out = np.zeros(n, dtype=np.dtype([
            ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
            ("red", "u1"), ("green", "u1"), ("blue", "u1")]))
        out["x"], out["y"], out["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        out["red"], out["green"], out["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
        f.write(out.tobytes())
    return n


def load_depth(path, expect_w=None, expect_h=None):
    """读深度图。支持 .png (16 位) 和 .raw (uint16 LE 裸数据 + .json 元数据)。"""
    if path.endswith(".raw"):
        meta_path = path.replace(".raw", ".json")
        if not osp.exists(meta_path):
            raise RuntimeError(f"裸深度缺元数据: {meta_path}")
        with open(meta_path) as f:
            m = json.load(f)
        w, h = int(m["width"]), int(m["height"])
        arr = np.fromfile(path, dtype="<u2")
        if arr.size != w * h:
            raise RuntimeError(f"深度尺寸不符: {arr.size} != {w}x{h}")
        return arr.reshape(h, w), m.get("unit_m", 0.0001)
    # PNG
    import cv2
    d = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if d is None:
        raise RuntimeError(f"读不了深度图: {path}")
    if d.dtype != np.uint16:
        # 8 位深度精度太差, 拒绝 (避免又被当成真值)
        raise RuntimeError(f"深度不是 16 位 (dtype={d.dtype}), 精度不足: {path}")
    return d, 0.0001


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="数据集目录 (含 cameras.json)")
    ap.add_argument("--out", required=True, help="输出 PLY 路径")
    ap.add_argument("--depth-dir", default="depth", help="深度子目录名 (默认 depth)")
    ap.add_argument("--max-points", type=int, default=200000)
    ap.add_argument("--min-z", type=float, default=0.10, help="米, 小于此值丢弃")
    ap.add_argument("--max-z", type=float, default=3.00, help="米, 大于此值丢弃")
    ap.add_argument("--stride", type=int, default=1, help="像素采样步长, 越大点越少")
    ap.add_argument("--no-color", action="store_true", help="不读彩色")
    a = ap.parse_args()

    cam_path = osp.join(a.src, "cameras.json")
    if not osp.exists(cam_path):
        print(f"[ERROR] 没有 {cam_path}", file=sys.stderr)
        return 2
    with open(cam_path) as f:
        cams = json.load(f)

    K = np.array(cams["K"], dtype=np.float64)
    fx, fy = K[0][0], K[1][1]
    cx, cy = K[0][2], K[1][2]
    frames = cams.get("frames", [])
    if not frames:
        print("[ERROR] cameras.json 没有 frames", file=sys.stderr)
        return 2

    depth_dir = osp.join(a.src, a.depth_dir)
    if not osp.isdir(depth_dir):
        print(f"[ERROR] 没有深度目录 {depth_dir}", file=sys.stderr)
        print("        (采集守护需要先存深度, 见 gs_autocap_daemon.py)", file=sys.stderr)
        return 2

    all_xyz = []
    all_rgb = []
    used = 0
    skipped = 0
    total_valid = 0

    import cv2

    for fi, fr in enumerate(frames):
        name = fr["file"]
        stem = osp.splitext(name)[0]
        # 深度文件名: 优先 <stem>.png / .raw
        dpath = None
        for cand in (f"{stem}.png", f"{stem}.raw"):
            p = osp.join(depth_dir, cand)
            if osp.exists(p):
                dpath = p
                break
        if dpath is None:
            skipped += 1
            continue
        try:
            depth, unit = load_depth(dpath)
        except Exception as e:
            print(f"  [skip] {name}: {e}")
            skipped += 1
            continue

        z = depth.astype(np.float32) * unit          # 米
        # 采样
        if a.stride > 1:
            z = z[::a.stride, ::a.stride]
        h, w = z.shape
        uu, vv = np.meshgrid(np.arange(w), np.arange(h))
        if a.stride > 1:
            uu = uu * a.stride
            vv = vv * a.stride

        m = (z > a.min_z) & (z < a.max_z) & np.isfinite(z)
        n_valid = int(m.sum())
        total_valid += n_valid
        if n_valid == 0:
            skipped += 1
            continue

        zz = z[m]
        Xc = np.stack([
            (uu[m] - cx) / fx * zz,
            (vv[m] - cy) / fy * zz,
            zz,
        ], axis=1)

        T = np.array(fr["T_cam2world"], dtype=np.float64)
        R, t = T[:3, :3], T[:3, 3]
        Xw = Xc @ R.T + t

        all_xyz.append(Xw.astype(np.float32))

        if not a.no_color:
            img_p = osp.join(a.src, "images", name)
            if osp.exists(img_p):
                img = cv2.imread(img_p)
                if img is not None:
                    rgb = img[vv[m], uu[m]][:, ::-1]        # BGR → RGB
                    all_rgb.append(rgb.astype(np.uint8))
                else:
                    all_rgb.append(np.zeros((n_valid, 3), np.uint8))
            else:
                all_rgb.append(np.zeros((n_valid, 3), np.uint8))
        used += 1

    if not all_xyz:
        print("[ERROR] 一张有效深度都没有", file=sys.stderr)
        print(f"  帧数 {len(frames)}, 跳过 {skipped}", file=sys.stderr)
        return 1

    xyz = np.concatenate(all_xyz, axis=0)
    rgb = np.concatenate(all_rgb, axis=0) if all_rgb else None
    print(f"[info] {used} 帧贡献点云 | 原始点 {xyz.shape[0]:,} | 有效深度像素 {total_valid:,}")

    # 均匀下采样
    if a.max_points and xyz.shape[0] > a.max_points:
        idx = np.random.RandomState(0).choice(xyz.shape[0], a.max_points, replace=False)
        xyz = xyz[idx]
        if rgb is not None:
            rgb = rgb[idx]
        print(f"[info] 下采样到 {a.max_points:,} 点")

    os.makedirs(osp.dirname(osp.abspath(a.out)) or ".", exist_ok=True)
    n = write_ply(a.out, xyz, rgb)

    bb_min, bb_max = xyz.min(axis=0), xyz.max(axis=0)
    print(f"[done] 写入 {a.out} | {n:,} 点 | {os.path.getsize(a.out)/1048576:.2f} MB")
    print(f"       包围盒 X[{bb_min[0]:.3f},{bb_max[0]:.3f}] "
          f"Y[{bb_min[1]:.3f},{bb_max[1]:.3f}] Z[{bb_min[2]:.3f},{bb_max[2]:.3f}] m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
