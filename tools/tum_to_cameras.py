#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tum_to_cameras.py — 把 mono_sfm 的 trajectory.tum 转成 gs_train.py 要的 cameras.json

为什么需要这一步:
  mono_sfm.py 产出 TUM 格式 (timestamp tx ty tz qx qy qz qw),
  gs_train.py 吃 cameras.json (convention=T_cam2world, OpenCV 光学系, 含 K)。

位姿方向已核对 (tools/mapping/mono_sfm.py:236):
  X0 = poses[i][0].T @ (Xw.T - poses[i][1])   ← world→cam 的运算形式
  ⇒ poses[i] = (R_c2w, t_c2w位置), 即 t 是相机在世界系的位置, R 是 cam→world 旋转。
  ⇒ 直接能填 T_cam2world, 不需要求逆。

用法:
  python3 tum_to_cameras.py --tum <map>/trajectory.tum --images <frames_dir> \
      --out <dataset_dir> [--focal 768] [--width 640] [--height 480]
"""
from __future__ import annotations

import argparse
import json
import os
import os.path as osp

import numpy as np


def quat_to_R(qx, qy, qz, qw):
    """四元数(x,y,z,w) → 3x3 旋转矩阵"""
    n = np.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if n < 1e-12:
        return np.eye(3)
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ], dtype=np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tum", required=True)
    ap.add_argument("--images", required=True, help="抽好的帧目录 (jpg)")
    ap.add_argument("--out", required=True, help="数据集输出目录 (写 cameras.json, 软链 images)")
    ap.add_argument("--focal", type=float, default=0.0, help="像素焦距; 0=按 1.2*max(w,h) 估 (与 mono_sfm 同口径)")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    a = ap.parse_args()

    # 读 TUM: timestamp tx ty tz qx qy qz qw
    rows = []
    for ln in open(a.tum):
        v = ln.split()
        if len(v) < 8:
            continue
        try:
            rows.append([float(x) for x in v[:8]])
        except ValueError:
            continue
    if not rows:
        raise SystemExit("trajectory.tum 里没有有效行")
    rows.sort(key=lambda r: r[0])

    # 帧文件: mono_sfm 用 order 列表的索引当 timestamp, 文件名是 f_0001.jpg 顺序
    files = sorted(f for f in os.listdir(a.images) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    if not files:
        raise SystemExit("images 目录里没有帧")

    # 尺寸与焦距
    W, H = a.width, a.height
    if not W or not H:
        try:
            from PIL import Image
            with Image.open(osp.join(a.images, files[0])) as im:
                W, H = im.size
        except Exception:
            W, H = 640, 480
    fx = a.focal if a.focal > 0 else 1.2 * max(W, H)
    K = [[fx, 0.0, W / 2.0], [0.0, fx, H / 2.0], [0.0, 0.0, 1.0]]

    # 对齐: tum 行数可能少于帧文件数 (mono_sfm 会跳过未匹配帧),
    # 按 timestamp(=原始帧索引) 映射到文件名; 越界则退化为顺序对齐。
    frames = []
    ts = [int(round(r[0])) for r in rows]
    use_index = (max(ts) < len(files)) and len(set(ts)) == len(ts)
    for k, r in enumerate(rows):
        _, tx, ty, tz, qx, qy, qz, qw = r
        R = quat_to_R(qx, qy, qz, qw)
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = R
        T[:3, 3] = [tx, ty, tz]
        fn = files[ts[k]] if use_index else files[min(k, len(files) - 1)]
        frames.append({"file": fn, "T_cam2world": T.tolist()})

    os.makedirs(a.out, exist_ok=True)
    dst_img = osp.join(a.out, "images")
    if not osp.exists(dst_img):
        try:
            os.symlink(osp.abspath(a.images), dst_img)
        except OSError:
            import shutil
            shutil.copytree(a.images, dst_img)

    out = {
        "width": int(W), "height": int(H),
        "K": K,
        "convention": "T_cam2world",
        "note": "由 tools/tum_to_cameras.py 从 mono_sfm trajectory.tum 转换; 单目无绝对尺度",
        "frames": frames,
    }
    p = osp.join(a.out, "cameras.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 自检: 相机间距, 太近说明视差不足 3DGS 学不好
    centers = np.array([[f["T_cam2world"][0][3], f["T_cam2world"][1][3], f["T_cam2world"][2][3]]
                        for f in frames])
    span = centers.max(0) - centers.min(0)
    print(json.dumps({
        "cameras_json": p, "frames": len(frames), "image_files": len(files),
        "aligned_by": "timestamp_index" if use_index else "order",
        "size": [int(W), int(H)], "focal_px": round(fx, 1),
        "cam_span": [round(float(x), 4) for x in span],
        "path_len": round(float(np.sum(np.linalg.norm(np.diff(centers, axis=0), axis=1))), 4),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
