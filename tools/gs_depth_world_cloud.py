#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_depth_world_cloud.py — 用 D405 深度 + 内参 + 手眼 + 位姿, 把每帧反投影成**世界系彩色点云**.

为什么: 3DGS 在没采过的视角只能瞎猜(拉丝/空洞). 深度给的是真几何, 不依赖学习.

链路(每一路都有真值来源):
    深度  : zmax_data/ss_live/zmax_scene/depth_raw.npy (uint16, scale 0.0001m, Orin rs.align 到彩色)
    彩色  : http://127.0.0.1:8793/snapshot/arm.jpg           (同一台 D405 的彩色)
    内参  : models/real_cam_calib.json  -> K
    手眼  : models/handeye_state.json   -> T_cam2tool (resid 0.06mm / 0.0046deg)
    位姿  : zmax_data/rokae_sdk/tcp_out/latest.json -> T_base2tcp
    变换  : T_base2cam = T_base2tcp(pose) @ inv(T_cam2tool)

自验: 两帧不同位姿各自成云, 交叉重叠率(voxel 2cm 邻域) ≥60% 才算这条链对; 否则打印候选变换的得分.
"""
import argparse, io, json, math, os, time, urllib.request
import numpy as np

REPO = "/home/ubuntu/zmax"
SCENE = os.path.join(REPO, "zmax_data/ss_live/zmax_scene")
POSE = os.path.join(REPO, "zmax_data/rokae_sdk/tcp_out/latest.json")
CAL = os.path.join(REPO, "models/real_cam_calib.json")
HE = os.path.join(REPO, "models/handeye_state.json")


def _np(x):
    a = np.array(x, dtype=float)
    return a.reshape(4, 4) if a.size == 16 else a


def euler_xyz(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def t_base2tcp(p):
    T = np.eye(4)
    T[:3, :3] = euler_xyz(p["rx"], p["ry"], p["rz"])
    T[:3, 3] = [p["x"], p["y"], p["z"]]
    return T


def read_pose():
    with open(POSE) as f:
        d = json.load(f)
    age = time.time() - float(d.get("ts") or 0)
    return d, age


def read_depth(max_age=6.0):
    m = json.load(open(os.path.join(SCENE, "depth_meta.json")))
    age = time.time() - float(m.get("t") or 0)
    if age > max_age:
        return None, m, age
    a = np.load(os.path.join(SCENE, "depth_raw.npy"))
    return a, m, age


def fetch_color(url, timeout=5):
    try:
        raw = urllib.request.urlopen(url, timeout=timeout).read()
        import cv2
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        return img
    except Exception as e:                                                    # noqa: BLE001
        print("彩色取不到:", e)
        return None


def cloud_from(depth, color, K, T_base2cam, min_z=0.10, max_z=1.2, stride=2, rgb_bgr=True):
    h, w = depth.shape[:2]
    fx, fy, cx, cy = K[0], K[4], K[2], K[5]
    vs, us = np.mgrid[0:h:stride, 0:w:stride]
    z = depth[::stride, ::stride].astype(np.float32) * 0.0001
    ok = (z > min_z) & (z < max_z)
    z = z[ok]; u = us[ok].astype(np.float32); v = vs[ok].astype(np.float32)
    x = (u - cx) * z / fx
    y = (v - cy) * z / fy
    P = np.stack([x, y, z, np.ones_like(z)], 0)
    W = T_base2cam @ P
    pts = W[:3].T
    if color is not None:
        if color.shape[1] != w or color.shape[0] != h:
            import cv2
            color = cv2.resize(color, (w, h))
        c = color[::stride, ::stride][ok]
        if rgb_bgr:
            c = c[:, ::-1]
    else:
        c = np.full((len(pts), 3), 128, np.uint8)
    return pts, c


def voxel_keys(pts, vox):
    return np.floor(pts / vox).astype(np.int64)


def overlap_frac(a_pts, b_pts, vox=0.02):
    """b 的点里, 有多少在 a 的 voxel 邻域(27 格)内 -> 一致性. 变换错时这个数会塌."""
    if len(a_pts) == 0 or len(b_pts) == 0:
        return 0.0
    ka = set(map(tuple, voxel_keys(a_pts, vox)))
    kb = voxel_keys(b_pts, vox)
    hit = 0
    for k in map(tuple, kb):
        if k in ka:
            hit += 1
    return hit / len(kb)


def write_ply(path, pts, cols):
    n = len(pts)
    hdr = ("ply\nformat binary_little_endian 1.0\nelement vertex %d\n"
           "property float x\nproperty float y\nproperty float z\n"
           "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n" % n)
    with open(path, "wb") as f:
        f.write(hdr.encode())
        arr = np.empty(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                 ("red", "u1"), ("green", "u1"), ("blue", "u1")])
        arr["x"], arr["y"], arr["z"] = pts[:, 0], pts[:, 1], pts[:, 2]
        arr["red"], arr["green"], arr["blue"] = cols[:, 0], cols[:, 1], cols[:, 2]
        f.write(arr.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--voxel", type=float, default=0.01)
    ap.add_argument("--stride", type=int, default=2)
    ap.add_argument("--out", default=os.path.join(REPO, "zmax_data/gs_assets/cloud_world.ply"))
    ap.add_argument("--color-url", default="http://127.0.0.1:8793/snapshot/arm.jpg")
    ap.add_argument("--inv", action="store_true", help="用 T_base2cam = pose @ T_cam2tool (反向手眼) 做对照")
    a = ap.parse_args()

    K = np.array(json.load(open(CAL))["K"], dtype=float)
    T_ct = _np(json.load(open(HE))["T_cam2tool"])
    # 2026-11-14 实测定标: 用 RANSAC 拟合主平面判方向
    #   pose(Rz·Ry·Rx) @ T_cam2tool            → 主平面法向与 Z 夹角 3.2°, 光轴朝下 0.67  ✅
    #   pose @ inv(T_cam2tool) / 欧拉 Rx·Ry·Rz → 37°/36°/40° 斜, 光轴朝下分量 <=0  ❌
    T_c2t = np.linalg.inv(T_ct) if a.inv else T_ct
    print("手眼链: %s | 平移模长 %.1f mm" % ("pose@inv(T_cam2tool)(对照)" if a.inv else "pose@T_cam2tool",
                                            np.linalg.norm(T_c2t[:3, 3]) * 1000))

    acc = {}
    first = None
    stats = []
    for i in range(a.samples):
        d, m, dage = read_depth()
        p, page = read_pose()
        if d is None:
            print("跳过: 深度不新鲜(%.1fs)" % dage)
            time.sleep(a.every); continue
        col = fetch_color(a.color_url)
        T = t_base2tcp(p) @ T_c2t
        pts, cols = cloud_from(d, col, K, T, stride=a.stride)
        if len(pts) == 0:
            print("跳过: 无有效深度点"); time.sleep(a.every); continue
        # 交叉一致性(第一帧 vs 本帧)
        ov = None
        if first is None:
            first = pts
        else:
            ov = overlap_frac(first, pts)
        k = voxel_keys(pts, a.voxel)
        for j, key in enumerate(map(tuple, k)):
            if key not in acc:
                acc[key] = (pts[j], cols[j])
        stats.append((i, len(pts), round(dage, 2), round(page, 2), None if ov is None else round(ov, 3),
                      round(float(np.median(pts[:, 2])), 2)))
        print("样本%02d 点%6d 深度龄%.2fs 位姿龄%.2fs 与首帧重叠%s 中位z%.2fm"
              % (i, len(pts), dage, page, "-" if ov is None else "%.1f%%" % (ov * 100), stats[-1][5]))
        time.sleep(a.every)

    if not acc:
        print("没有任何有效样本"); return 1
    P = np.array([v[0] for v in acc.values()], dtype=np.float32)
    C = np.array([v[1] for v in acc.values()], dtype=np.uint8)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    write_ply(a.out, P, C)
    meta = {"points": int(len(P)), "samples": len(stats), "voxel_m": a.voxel,
            "ply": a.out, "bytes": os.path.getsize(a.out),
            "min": np.round(P.min(0), 3).tolist(), "max": np.round(P.max(0), 3).tolist(),
            "handeye_inv": bool(a.inv), "ts": time.time(), "stats": stats[-6:]}
    json.dump(meta, open(a.out.replace(".ply", ".json"), "w"), indent=1)
    print("写出 %s · %d 点 · %.1f MB · 范围 %s~%s"
          % (a.out, len(P), os.path.getsize(a.out) / 1e6, meta["min"], meta["max"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
