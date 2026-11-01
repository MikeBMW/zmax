#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_hybrid_robot.py — AR 工位「双臂 + 底盘箱体 + 顶视相机」混合机器人外形渲染。

外形与安装几何的唯一依据 (与 8797 AR 3D 页面同源, tools/web/tcp-ar.html):
  LARM  off [0, 0.5, 0]        左臂装在 y=+500 mm, 右臂 y=0, 两臂中心距 500 mm
  CHS   L0.600 W0.800 H0.750   底盘箱体 600(前后) × 800(左右) × 750(落地总高)
        HB 0.680               箱体本体 680 mm + 轮 Ø150 露出 70 mm
        cy 0.25                箱体在 y 上以两臂原心中点(250)对称
  TCAM  y0.25 r0.070 tilt35    顶视立柱 r=70 mm, 立在两臂中线 y=250, 高 = 1 轴高 328 mm
        body [0.090,0.025,0.025] 相机机身 90×25×25 mm (RealSense 模板)
  坐标: 箱体顶板 = 两臂安装面 = z=0; 地面 z=-0.750
用量: ./gui-venv311/bin/python tools/render_hybrid_robot.py [--pose zero|live]
"""
from __future__ import annotations
import os, sys, json, math
import numpy as np
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import (fk, load_meshes, world_tris, render, rot_cam, save, draw_dims,
                                LINK_ORDER, SPEC)

REPO = "/home/ubuntu/zmax"
OUTDIR = os.path.join(REPO, "docs/6-开阳-工程落地/figs_ar_robot")

# ── 安装几何 (tcp-ar.html 同源) ──────────────────────────────────────
ARM_Y = {"R": 0.0, "L": 0.500}
CHS = dict(L=0.600, W=0.800, H=0.750, HB=0.680, cy=0.250, wr=0.075)
TCAM = dict(y=0.250, r=0.070, h=0.328, tilt=35.0, body=(0.090, 0.025, 0.025))

C_ARM_R = np.array([0.62, 0.66, 0.71])
C_ARM_L = np.array([0.52, 0.62, 0.68])
C_BOX = np.array([0.30, 0.33, 0.38])
C_BOX_TOP = np.array([0.46, 0.49, 0.54])
C_POLE = np.array([0.22, 0.25, 0.30])
C_CAM = np.array([0.14, 0.17, 0.24])
C_WHEEL = np.array([0.10, 0.10, 0.12])


def box_tris(x0, x1, y0, y1, z0, z1):
    p = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
    q = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    t = []
    for a, b, c, d in q:
        t += [[p[a], p[b], p[c]], [p[a], p[c], p[d]]]
    return np.array(t, float)


def cyl_tris(cx, cy, z0, z1, r, n=36, axis="z"):
    t = []
    for i in range(n):
        a0 = 2 * math.pi * i / n
        a1 = 2 * math.pi * (i + 1) / n
        if axis == "z":
            p0 = [cx + r * math.cos(a0), cy + r * math.sin(a0)]
            p1 = [cx + r * math.cos(a1), cy + r * math.sin(a1)]
            A0 = [p0[0], p0[1], z0]; A1 = [p1[0], p1[1], z0]
            B0 = [p0[0], p0[1], z1]; B1 = [p1[0], p1[1], z1]
        else:  # axis = y (轮子)
            p0 = [cx + r * math.cos(a0), z0 + r * math.sin(a0)]
            p1 = [cx + r * math.cos(a1), z0 + r * math.sin(a1)]
            A0 = [p0[0], cy, p0[1]]; A1 = [p1[0], cy, p1[1]]
            B0 = [p0[0], cy + 0.05, p0[1]]; B1 = [p1[0], cy + 0.05, p1[1]]
        t += [[A0, A1, B1], [A0, B1, B0]]
    return np.array(t, float)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)


def parts(spec, q):
    """返回 [(tris, color), ...]。"""
    meshes = load_meshes()
    out = []
    for side, dy in ARM_Y.items():
        T = fk(spec, q)
        tri = world_tris(T, meshes).copy()
        tri[:, :, 1] += dy
        out.append((tri, C_ARM_R if side == "R" else C_ARM_L))

    L, W, H, HB, cy, wr = CHS["L"], CHS["W"], CHS["H"], CHS["HB"], CHS["cy"], CHS["wr"]
    hl, hw = L / 2, W / 2
    # 箱体本体 (底面 -0.680 到顶板 0), 顶板略亮
    out.append((box_tris(-hl, hl, cy - hw, cy + hw, -HB, -0.012), C_BOX))
    out.append((box_tris(-hl, hl, cy - hw, cy + hw, -0.012, 0.0), C_BOX_TOP))
    # 四轮 (轴沿 Y, Ø150)
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx = sx * (hl - 0.085)
            yy = cy + sy * (hw - 0.075)
            out.append((cyl_tris(cx, yy, -0.750 + wr, -0.750 + wr, wr, 30, axis="y"), C_WHEEL))
    # 顶视立柱 + 相机
    out.append((cyl_tris(0.0, TCAM["y"], 0.0, TCAM["h"], TCAM["r"], 40), C_POLE))
    org = np.array([0.0, TCAM["y"], TCAM["h"] + 0.006])
    D, Wd, Hd = 0.025, 0.090, 0.025           # 机身 90(宽) × 25(深) × 25(高), 短边朝 +X
    cam = box_tris(-D / 2, D / 2, -Wd / 2, Wd / 2, 0.0, Hd)
    R = rot_y(math.radians(TCAM["tilt"]))
    cam = cam @ R.T + org
    out.append((cam, C_CAM))
    return out


def bbox_of(ps):
    v = np.concatenate([t.reshape(-1, 3) for t, _ in ps])
    return v.min(0), v.max(0)


def main():
    pose = sys.argv[sys.argv.index("--pose") + 1] if "--pose" in sys.argv else "zero"
    os.makedirs(OUTDIR, exist_ok=True)
    spec = json.load(open(SPEC))
    q = [0.0] * 6 if pose == "zero" else spec["live_check"]["jpos"]
    ps = parts(spec, q)
    tris = np.concatenate([t for t, _ in ps])
    cols = np.concatenate([np.tile(c, (len(t), 1)) for t, c in ps])
    lo, hi = bbox_of(ps)
    print("hybrid bbox mm  X %.1f  Y %.1f  Z %.1f  (地面 %.0f)" %
          ((hi[0] - lo[0]) * 1000, (hi[1] - lo[1]) * 1000, (hi[2] - lo[2]) * 1000, lo[2] * 1000))

    views = {"front": (0, 0), "side": (90, 0), "top": (0, 89.9), "iso": (36, 20)}
    labels = {"front": ("总宽(左右)", "总高"), "side": ("总长(前后)", "总高"),
              "top": ("总宽(左右)", "总长(前后)"), "iso": None}
    for name, (az, el) in views.items():
        img, meta = render(tris, rot_cam(az, el), size=(1500, 1350), colors=cols)
        p = os.path.join(OUTDIR, f"hybrid_{pose}_{name}.png")
        save(img, p, dpi=160)
        if labels[name]:
            h_lab, v_lab = labels[name]
            draw_dims(os.path.join(OUTDIR, f"hybrid_{pose}_{name}_dim.png"), img, meta, h_lab, v_lab,
                      "双臂 + 底盘箱体 + 顶视相机 · 顶板=两臂安装面 (z=0)")
        print("saved", p)
    json.dump(dict(pose=pose, bbox_min_mm=(lo * 1000).round(1).tolist(),
                   bbox_max_mm=(hi * 1000).round(1).tolist(),
                   arm_y_mm=[ARM_Y["R"] * 1000, ARM_Y["L"] * 1000], chassis=CHS, topcam=TCAM),
              open(os.path.join(OUTDIR, f"hybrid_{pose}_meta.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
