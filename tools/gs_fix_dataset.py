#!/usr/bin/env python3
"""把 3DGS 数据集从「错的位姿+猜的内参」修正成「真值位姿+真值内参」。

错在哪（两个都致命）:
  1. 位姿: 采集守护直接拿 TCP 位姿当相机位姿
        T_cam2world = T_base2tcp                    ← 错
     正确: 相机在臂上, 差一个手眼外参
        T_cam2world = T_cam2tool @ inv(T_base2tcp)   ← 对
     依据: docs/notes/CALIB-20260921-handeye.md 写的是 T_cam_base = inv(G·X),
           等价于 T_cam2base = X @ inv(G), 其中 X = T_cam2tool, G = T_base2tcp

  2. 内参: 用的是焦距默认值 768
     真值: fx=394.06 fy=393.47 cx=318.44 cy=238.66 (ROS camera_info)
     焦距差近一倍 ⇒ 投影全错 ⇒ 高斯怎么训都糊

用法:
  python3 tools/gs_fix_dataset.py --src <原数据集> --out <新数据集>
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np


def load_handeye(path):
    with open(path) as f:
        d = json.load(f)
    X = np.array(d["T_cam2tool"], dtype=float)
    if X.shape != (4, 4):
        raise ValueError("T_cam2tool 不是 4x4")
    return X, d


def load_intrinsics(path):
    with open(path) as f:
        d = json.load(f)
    K = d["K"]
    if len(K) == 9:
        fx, cx = K[0], K[2]
        fy, cy = K[4], K[5]
    else:
        raise ValueError("K 长度不是 9")
    return fx, fy, cx, cy, d.get("dist")


def euler_zyx_to_R(rx, ry, rz):
    """机械臂 RPY -> 旋转矩阵, 约定 Rz@Ry@Rx (对采集数据实测误差 0.0000)。"""
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def pose_to_T(pose):
    """[x,y,z,rx,ry,rz] -> 4x4 T_base2tcp"""
    T = np.eye(4)
    T[:3, :3] = euler_zyx_to_R(pose[3], pose[4], pose[5])
    T[:3, 3] = pose[:3]
    return T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="原数据集目录 (含 cameras.json / images)")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--handeye", default="/home/ubuntu/zmax/models/handeye_state.json")
    ap.add_argument("--calib", default="/home/ubuntu/zmax/models/real_cam_calib.json")
    ap.add_argument("--no-handeye", action="store_true", help="跳过手眼变换(只修内参, 做消融用)")
    a = ap.parse_args()

    X_cam2tool, he = load_handeye(a.handeye)
    fx, fy, cx, cy, dist = load_intrinsics(a.calib)
    print(f"手眼外参 T_cam2tool: t={he['t_mm']} mm  rpy={he['rpy_deg']} deg")
    print(f"  (标定残差 平移 {he['resid_trans_mm_rms']}mm / 姿态 {he['resid_rot_deg_rms']}deg)")
    print(f"真值内参: fx={fx:.2f} fy={fy:.2f} cx={cx:.2f} cy={cy:.2f}")
    X_inv = np.linalg.inv(X_cam2tool)

    src_cam = os.path.join(a.src, "cameras.json")
    with open(src_cam) as f:
        ds = json.load(f)
    frames = ds.get("frames", [])
    print(f"\n原数据集: {len(frames)} 帧, 原 K={ds.get('K')}")
    print(f"                            原 size={ds.get('width')}x{ds.get('height')}")

    os.makedirs(a.out, exist_ok=True)
    os.makedirs(os.path.join(a.out, "images"), exist_ok=True)

    new_frames = []
    n_missing_pose = 0
    shifts = []
    for fr in frames:
        pose = fr.get("pose")
        if pose is None:
            n_missing_pose += 1
            continue
        T_base2tcp = pose_to_T(np.array(pose, dtype=float))
        if a.no_handeye:
            T_base2cam = T_base2tcp
        else:
            # T_cam2tool 的命名 = p_tool = X @ p_cam (把 cam 点变到 tool 系)
            #   p_base = G @ p_tool = G @ X @ p_cam
            #   ⇒ T_base2cam = G @ X
            T_base2cam = T_base2tcp @ X_cam2tool
        T_cam2world = np.linalg.inv(T_base2cam)
        # 验证: T_base2cam[:3,3] 才是"相机在 base 系的位置",
        # 它和 TCP 位置的差应恒等于手眼模长 |t_X| (相机固连在 TCP 上)
        shifts.append(np.linalg.norm(T_base2cam[:3, 3] - T_base2tcp[:3, 3]))
        nf = dict(fr)
        nf["T_cam2world"] = T_cam2world.tolist()
        new_frames.append(nf)
        # 复制图像
        sp = os.path.join(a.src, "images", fr["file"])
        dp = os.path.join(a.out, "images", fr["file"])
        if os.path.exists(sp) and not os.path.exists(dp):
            shutil.copy2(sp, dp)

    out_ds = {
        "width": ds.get("width"),
        "height": ds.get("height"),
        "K": [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
        "convention": "T_cam2world",
        "frames": new_frames,
        "_fix": {
            "handeye": a.handeye if not a.no_handeye else None,
            "T_cam2tool": X_cam2tool.tolist(),
            "calib": a.calib,
            "old_K": ds.get("K"),
            "new_K": [fx, fy, cx, cy],
            "dist": dist,
            "formula": "T_cam2world = T_cam2tool @ inv(T_base2tcp)" if not a.no_handeye else "T_cam2world = T_base2tcp (未修正)",
        },
    }
    with open(os.path.join(a.out, "cameras.json"), "w") as f:
        json.dump(out_ds, f, indent=1)

    print(f"\n输出: {a.out}")
    print(f"  帧数 {len(new_frames)}" + (f" (跳过 {n_missing_pose} 帧无 pose)" if n_missing_pose else ""))
    if shifts:
        s = np.array(shifts)
        print(f"  手眼修正位移量: 中位 {np.median(s)*1000:.1f} mm · 范围 [{s.min()*1000:.1f}, {s.max()*1000:.1f}] mm")
        print(f"  (应接近手眼模长 244.1mm — 偏差大说明 pose 约定不对)")
    print(f"  K: fx={fx:.2f} fy={fy:.2f} cx={cx:.2f} cy={cy:.2f}")


if __name__ == "__main__":
    sys.exit(main())
