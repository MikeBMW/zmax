#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_ar_work.py — 按 AR 场景的真实几何 + 真机 URDF 渲一帧作业姿态。

老倪口径（2026-11-01）：「尺寸和外形，在 AR 场景里已经画好了，你要渲染成一模一样的。
你看看 web 里的实际数据」

所以这里**不造任何几何**：
  · 台面 / 料盘 / 槽位 / 插孔口  ← 全部从 zmax_data/ar_mujoco/ar_station.xml 读（实测坐标）
  · 机器人外形               ← 真机 URDF 的厂家 STL
  · 作业点位                 ← 8797 /api/points 的示教点位（基座系）
  · 相机                     ← tcp-ar.html:573 的默认机位 yaw/pitch/dist/tgt

用法: ./gui-venv311/bin/python tools/render_ar_work.py --outdir DIR
"""
from __future__ import annotations
import os, sys, json, math
import xml.etree.ElementTree as ET
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import SPEC, LINK_ORDER, fk, load_meshes, world_tris, render, save

XML = "/home/ubuntu/zmax/zmax_data/ar_mujoco/ar_station.xml"

# tcp-ar.html:573  VR={yaw:-0.9, pitch:0.55, dist:1.6, tgt:[0.70,0.22,0.14]}
WEB_CAM = dict(yaw=-0.9, pitch=0.55, dist=1.6, tgt=[0.70, 0.22, 0.14])


# ── 1. 把 AR 场景 XML 的 geom 转成三角形 ──────────────────────────────
def _rgba(el, default=(0.5, 0.5, 0.5, 1.0)):
    s = el.get("rgba")
    if not s:
        return default
    v = [float(x) for x in s.split()]
    return tuple(v) if len(v) == 4 else default


def _box_tris(pos, half):
    cx, cy, cz = pos
    sx, sy, sz = half
    v = np.array([
        [cx - sx, cy - sy, cz - sz], [cx + sx, cy - sy, cz - sz],
        [cx + sx, cy + sy, cz - sz], [cx - sx, cy + sy, cz - sz],
        [cx - sx, cy - sy, cz + sz], [cx + sx, cy - sy, cz + sz],
        [cx + sx, cy + sy, cz + sz], [cx - sx, cy + sy, cz + sz],
    ])
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return np.array([[v[a], v[b], v[c]] for a, b, c in f])


def _prism_tris(p0, p1, r, n=16):
    """圆柱/胶囊近似：两点之间画 n 棱柱。"""
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    ax = p1 - p0
    L = np.linalg.norm(ax)
    if L < 1e-9:
        return np.zeros((0, 3, 3))
    z = ax / L
    tmp = np.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    x = np.cross(tmp, z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.cos(ang)[:, None] * x + np.sin(ang)[:, None] * y
    A = p0 + r * ring
    B = p1 + r * ring
    tris = []
    for i in range(n):
        j = (i + 1) % n
        tris.append([A[i], B[i], B[j]])
        tris.append([A[i], B[j], A[j]])
    # 端面
    ca = p0.mean() if False else p0
    cb = p1
    for i in range(n):
        j = (i + 1) % n
        tris.append([ca, A[j], A[i]])
        tris.append([cb, B[i], B[j]])
    return np.array(tris)


def load_station(xml_path=XML, skip_arms=True, skip_floor=True, skip_table=False):
    """读 AR 场景 XML → (tris, colors)。skip_arms: 真机外形用 URDF 渲，这里跳过胶囊臂。"""
    root = ET.parse(xml_path).getroot()
    body = root.find("worldbody")
    tris, cols = [], []
    stats = {}
    for el in body.iter("geom"):
        name = el.get("name", "")
        typ = el.get("type", "box")
        if skip_arms and name.startswith(("armL_", "armR_")):
            continue
        if skip_table and name == "table":
            continue
        pos = el.get("pos")
        size = el.get("size")
        rgba = _rgba(el)
        rgb = np.array(rgba[:3], float)
        t = None
        if typ == "box" and pos and size:
            t = _box_tris([float(v) for v in pos.split()], [float(v) for v in size.split()])
        elif typ == "cylinder" and pos and size:
            r, h = [float(v) for v in size.split()[:2]]
            px, py, pz = [float(v) for v in pos.split()]
            t = _prism_tris([px, py, pz - h], [px, py, pz + h], r)
        elif typ == "capsule" and el.get("fromto"):
            f6 = [float(v) for v in el.get("fromto").split()]
            r = float(size.split()[0])
            t = _prism_tris(f6[:3], f6[3:], r)
        elif typ == "plane" and pos and size:
            if skip_floor:
                continue
            sx, sy = [float(v) for v in size.split()[:2]]
            px, py, pz = [float(v) for v in pos.split()]
            t = _box_tris([px, py, pz - 0.002], [sx, sy, 0.002])
            # 地面压暗，别抢主体
            rgb = np.array([0.22, 0.23, 0.25])
        if t is None or len(t) == 0:
            continue
        tris.append(t)
        cols.append(np.tile(rgb, (len(t), 1)))
        stats[typ] = stats.get(typ, 0) + 1
    print("场景 geom: %s" % stats)
    return np.concatenate(tris, axis=0), np.concatenate(cols, axis=0)


# ── 2. 按示教点位反解作业姿态 ────────────────────────────────────────
def solve_to_point(spec, target, q0=None):
    """解一组关节角：TCP 到 target，工具轴朝下。least_squares，快且稳。"""
    from scipy.optimize import least_squares
    tgt = np.asarray(target, float)
    Down = np.array([0.0, 0.0, -1.0])

    def resid(q):
        T = fk(spec, q)
        M = T[LINK_ORDER[-1]]
        r = list((M[:3, 3] - tgt) * 8.0)          # 位置，放大权重
        r += list((M[:3, 2] - Down) * 0.25)       # 工具轴朝下
        return np.array(r)

    best = None
    seeds = [q0] if q0 is not None else []
    seeds += [np.array([0.65, 1.0, -1.2, 0.0, -0.4, 0.0]),
              np.array([0.65, 1.5, -0.6, 0.0, -0.1, 0.0]),
              np.array([0.0, 1.2, -1.5, 0.0, -0.4, 0.0]),
              np.array([0.65, 0.8, -1.8, 0.0, -0.5, 0.0])]
    lo = np.array([-3.1, -2.0, -3.1, -3.1, -2.5, -3.1])
    hi = np.array([3.1, 2.0, 3.1, 3.1, 2.5, 3.1])
    for s in seeds:
        r = least_squares(resid, np.clip(s, lo, hi), bounds=(lo, hi),
                          xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=4000)
        err = np.linalg.norm(fk(spec, r.x)[LINK_ORDER[-1]][:3, 3] - tgt)
        if best is None or err < best[0]:
            best = (err, r.x)
    return best[1], best[0]


# ── 3. 相机：按 web 的 yaw/pitch/dist/tgt 算 look-at ─────────────────
def web_view_rot(cam=WEB_CAM):
    yaw, pitch, dist = cam["yaw"], cam["pitch"], cam["dist"]
    tgt = np.array(cam["tgt"], float)
    eye = tgt + dist * np.array([math.cos(pitch) * math.sin(yaw),
                                 math.cos(pitch) * math.cos(yaw),
                                 math.sin(pitch)])
    d = tgt - eye
    z = d / np.linalg.norm(d)                       # 相机看 +Z
    up = np.array([0.0, 0.0, 1.0])
    x = np.cross(up, z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    print("相机 eye = (%.2f, %.2f, %.2f)  tgt = %s" % (*eye, list(np.round(tgt, 2))))
    return np.vstack([x, y, z]), eye


def main():
    outdir = "/tmp/ar_work"
    for i, a in enumerate(sys.argv):
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    W = int(os.environ.get("ARW_W", "1920"))
    H = int(os.environ.get("ARW_H", "1440"))
    os.makedirs(outdir, exist_ok=True)

    # 作业点：用 8797 /api/points 的 1 号位（真示教点）
    target = json.load(open("/tmp/ar_target.json"))["xyz"] if os.path.exists("/tmp/ar_target.json") \
        else [0.6488, 0.4983, 0.1104]
    print("作业点位 TCP 目标 =", target)

    spec = json.load(open(SPEC))
    meshes = load_meshes()

    q, err = solve_to_point(spec, target)
    T = fk(spec, q)
    M = T[LINK_ORDER[-1]]
    print("姿态 q =", [round(float(v), 3) for v in q])
    print("TCP 误差 %.1f mm   工具轴 (%.2f, %.2f, %.2f)" %
          (err * 1000, *M[:3, 2]))
    for k in LINK_ORDER:
        p = T[k][:3, 3] * 1000
        print("   %-10s x=%7.0f y=%7.0f z=%7.0f" % (k[-8:], p[0], p[1], p[2]))

    robot = world_tris(T, meshes)
    rcols = np.tile(np.array([0.74, 0.76, 0.80]), (len(robot), 1))
    st_tris, st_cols = load_station()

    tris = np.concatenate([st_tris, robot], axis=0)
    cols = np.concatenate([st_cols, rcols], axis=0)

    from render_robot_views import rot_cam
    R, eye = web_view_rot()
    views = {"ar_work": R,                                   # 与 web AR 页同机位
             "ar_side": rot_cam(28, 16),                      # 侧前方看机械臂
             "ar_high": rot_cam(58, 34)}                      # 偏高俯视看料盘
    for nm, RR in views.items():
        img, meta = render(tris, RR, size=(W, H), ss=2, bg=1.0, colors=cols)
        p = os.path.join(outdir, nm + ".png")
        save(img, p, dpi=150)
        a = img if isinstance(img, np.ndarray) else np.asarray(img)
        nz = float((a.min(axis=2) < 245).mean()) * 100
        print("saved %-24s %s  主体 %.1f%%" % (p, img.shape, nz))

    json.dump(dict(q=[round(float(v), 4) for v in q], tcp=[round(float(v), 4) for v in M[:3, 3]],
                   target=target, err_mm=round(float(err) * 1000, 2),
                   tool_axis=[round(float(v), 3) for v in M[:3, 2]],
                   camera=WEB_CAM, eye=[round(float(v), 3) for v in eye], xml=XML),
              open(os.path.join(outdir, "meta.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
