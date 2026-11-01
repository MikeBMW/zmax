#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_robot_views.py — 真机外形四视图渲染 (正面/侧面/顶视/透视) + 尺寸标注。

真源: config/robot/zmax_robot_spec.json (URDF 导出, sha256_16 4e0288ac88042652)
      + 厂家 STL 网格 data/database/zmax/sources/config/moveit_xms5/urdf/meshes/
做法: URDF 正运动学 → 三角形顶点变换 → numpy 自带 z-buffer 光栅化 (2x 超采样)
      + 扁平光照, 不依赖 OpenGL (本机 headless GL 不可用)。

用法: ./gui-venv311/bin/python tools/render_robot_views.py [--pose zero|live] [--outdir DIR]
"""
from __future__ import annotations
import os, sys, json, math, struct
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

# 中文字体 (否则标注全是方框)
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "Noto Sans CJK JP", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

REPO = "/home/ubuntu/zmax"
SPEC = os.path.join(REPO, "config/robot/zmax_robot_spec.json")
MESH_DIR = os.path.join(REPO, "data/database/zmax/sources/config/moveit_xms5/urdf/meshes/xms5_r800_w4g3b4c_meshes")
OUTDIR = os.path.join(REPO, "docs/6-开阳-工程落地/figs_ar_robot")

LINK_ORDER = ["XMS5-R800-W4G3B4C_base", "XMS5-R800-W4G3B4C_link1", "XMS5-R800-W4G3B4C_link2",
              "XMS5-R800-W4G3B4C_link3", "XMS5-R800-W4G3B4C_link4", "XMS5-R800-W4G3B4C_link5",
              "XMS5-R800-W4G3B4C_link6"]


# ── 基础几何 ────────────────────────────────────────────────────────────
def rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], float)


def ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], float)


def rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)


def rpy(r, p, y):
    return rz(y) @ ry(p) @ rx(r)


def axis_rot(axis, ang):
    ax = np.array(axis, float)
    n = np.linalg.norm(ax)
    if n < 1e-9 or abs(ang) < 1e-12:
        return np.eye(3)
    ax /= n
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)


SCALE_STL = 0.001   # 厂家 STL 单位 = mm


def read_stl(path):
    with open(path, "rb") as f:
        head = f.read(84)
        n = struct.unpack("<I", head[80:84])[0]
        data = np.frombuffer(f.read(n * 50), dtype=np.uint8).reshape(n, 50)
        tri = data[:, 12:48].copy().view("<f4").reshape(n, 3, 3).astype(np.float64)
    return tri * SCALE_STL


def fk(spec, q):
    """返回 {link: 4x4 变换}。"""
    T = {}
    cur = np.eye(4)
    T["XMS5-R800-W4G3B4C_base"] = cur.copy()
    jmap = {j["child"]: j for j in spec["joints"]}
    for i, link in enumerate(LINK_ORDER[1:], start=0):
        j = jmap[link]
        o = np.eye(4)
        o[:3, :3] = rpy(*j["origin_rpy"])
        o[:3, 3] = j["origin_xyz"]
        m = np.eye(4)
        ang = q[i] if j["type"] == "revolute" else 0.0
        m[:3, :3] = axis_rot(j["axis"], ang)
        cur = cur @ o @ m
        T[link] = cur.copy()
    return T


def load_meshes():
    out = {}
    for link in LINK_ORDER:
        p = os.path.join(MESH_DIR, link + ".stl")
        if os.path.exists(p):
            out[link] = read_stl(p)
    return out


def world_tris(T, meshes):
    tris = []
    for link, tri in meshes.items():
        M = T[link]
        v = tri.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        tris.append(v.reshape(-1, 3, 3))
    return np.concatenate(tris, axis=0)


# ── 光栅化 ──────────────────────────────────────────────────────────────
def render(tris, view_rot, size=(1400, 1700), ss=2, bg=1.0, elevate=0.0):
    """正交投影 + z-buffer。view_rot: 3x3, 把世界坐标转到相机坐标 (相机看 +Z 往里)。"""
    W, H = size[0] * ss, size[1] * ss
    R = view_rot
    v = tris.reshape(-1, 3) @ R.T
    tri = v.reshape(-1, 3, 3)
    xy = tri[:, :, :2]
    z = tri[:, :, 2]
    lo = xy.reshape(-1, 2).min(0)
    hi = xy.reshape(-1, 2).max(0)
    pad = 0.06 * max(hi - lo)
    lo, hi = lo - pad, hi + pad
    span = hi - lo
    scale = min(W / span[0], H / span[1])
    off = np.array([(W - span[0] * scale) / 2, (H - span[1] * scale) / 2])

    def to_px(p):
        return (p - lo) * scale + off

    img = np.full((H, W, 3), bg, np.float32)
    zbuf = np.full((H, W), -1e9, np.float32)

    # 光照方向 (相机空间)
    L = np.array([-0.35, 0.45, 0.82], float)
    L /= np.linalg.norm(L)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nl = np.linalg.norm(n, axis=1)
    nl[nl == 0] = 1
    n = n / nl[:, None]
    shade = 0.30 + 0.70 * np.abs(n @ L)
    base = np.array([0.72, 0.74, 0.78])          # 工业浅灰
    accent = np.array([0.16, 0.18, 0.22])        # 深色关节
    cols = (base[None, :] * shade[:, None])
    # 前三个 link 用深色, 关节感
    dark = np.zeros(len(tri), bool)
    n_base = len(tri)
    dark[:] = False
    cols[dark] = cols[dark] * 0.55 + accent * 0.45

    px = to_px(xy.reshape(-1, 2)).reshape(-1, 3, 2)
    for i in range(len(tri)):
        p = px[i]
        x0 = int(max(0, np.floor(p[:, 0].min())))
        x1 = int(min(W - 1, np.ceil(p[:, 0].max())))
        y0 = int(max(0, np.floor(p[:, 1].min())))
        y1 = int(min(H - 1, np.ceil(p[:, 1].max())))
        if x1 <= x0 or y1 <= y0:
            continue
        xs = np.arange(x0, x1 + 1) + 0.5
        ys = np.arange(y0, y1 + 1) + 0.5
        X, Y = np.meshgrid(xs, ys)
        d = ((p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1]))
        if abs(d) < 1e-12:
            continue
        w0 = ((p[1, 1] - p[2, 1]) * (X - p[2, 0]) + (p[2, 0] - p[1, 0]) * (Y - p[2, 1])) / d
        w1 = ((p[2, 1] - p[0, 1]) * (X - p[2, 0]) + (p[0, 0] - p[2, 0]) * (Y - p[2, 1])) / d
        w2 = 1 - w0 - w1
        m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not m.any():
            continue
        zz = w0 * z[i, 0] + w1 * z[i, 1] + w2 * z[i, 2]
        sub = img[y0:y1 + 1, x0:x1 + 1]
        zsub = zbuf[y0:y1 + 1, x0:x1 + 1]
        upd = m & (zz > zsub)
        if not upd.any():
            continue
        zsub[upd] = zz[upd]
        sub[upd] = cols[i]
        img[y0:y1 + 1, x0:x1 + 1] = sub
        zbuf[y0:y1 + 1, x0:x1 + 1] = zsub

    # 超采样降采样
    img = img.reshape(size[1], ss, size[0], ss, 3).mean(axis=(1, 3))
    return img, dict(lo=lo, hi=hi, scale=scale / ss, off=off / ss, size=size)


def rot_cam(azimuth_deg, elev_deg):
    """世界 → 相机。相机看向 -Z; 先绕 Z 转方位, 再抬仰角。"""
    a = math.radians(azimuth_deg)
    e = math.radians(elev_deg)
    Rz = np.array([[math.cos(a), math.sin(a), 0], [-math.sin(a), math.cos(a), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(e), math.sin(e)], [0, -math.sin(e), math.cos(e)]])
    # 交换: 让相机 z 对应世界水平方向, 用于 z-buffer 深度
    S = np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float)
    return Rx @ S @ Rz


def save(img, path, dpi=170):
    h, w = img.shape[:2]
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img)
    ax.axis("off")
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


def annotate(path_out, img, tris, rot, labels, dpi=170, unit="mm"):
    """在已渲染图旁加整体尺寸线 (总长/总宽/总高)。"""
    h, w = img.shape[:2]
    fig = plt.figure(figsize=(w / dpi + 1.5, h / dpi + 0.7), dpi=dpi)
    ax = fig.add_axes([0.02, 0.06, w / dpi / (w / dpi + 1.5), h / dpi / (h / dpi + 0.7)])
    ax.imshow(img)
    ax.axis("off")
    fig.savefig(path_out, dpi=dpi, facecolor="white")
    plt.close(fig)



def draw_dims(path, img, meta, h_label, v_label, note=""):
    """在渲染图上画总尺寸线 (h/v 分别为该视图的水平/垂直方向真实长度, 单位 mm)。"""
    lo, hi, sc, off = meta["lo"], meta["hi"], meta["scale"], meta["off"]
    w_mm = (hi[0] - lo[0]) * 1000.0
    h_mm = (hi[1] - lo[1]) * 1000.0
    # 右侧与底部留白给尺寸线 (否则标注被画布裁掉)
    pad_r, pad_b = 230, 130
    img = np.pad(img, ((0, pad_b), (0, pad_r), (0, 0)), mode="constant", constant_values=1.0)
    H, W = img.shape[:2]
    fig = plt.figure(figsize=(W / 150, H / 150), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(img)
    ax.set_xlim(0, W); ax.set_ylim(H, 0)
    ax.axis("off")

    x0 = (lo[0] - lo[0]) * sc + off[0]
    x1 = (hi[0] - lo[0]) * sc + off[0]
    y0 = (lo[1] - lo[1]) * sc + off[1]
    y1 = (hi[1] - lo[1]) * sc + off[1]
    ink = "#14181F"; gold = "#B8912A"

    # 水平尺寸线 (下方)
    yb = y1 + max(28, 0.03 * H)
    ax.annotate("", xy=(x0, yb), xytext=(x1, yb),
                arrowprops=dict(arrowstyle="<->", color=ink, lw=1.6))
    for xx in (x0, x1):
        ax.plot([xx, xx], [y1 + 6, yb], color=ink, lw=1.0)
    ax.text((x0 + x1) / 2, yb + 8, "%s %.0f mm" % (h_label, w_mm),
            ha="center", va="top", fontsize=15, color=ink, weight="bold")

    # 垂直尺寸线 (右侧)
    xr = x1 + max(28, 0.03 * W)
    ax.annotate("", xy=(xr, y0), xytext=(xr, y1),
                arrowprops=dict(arrowstyle="<->", color=ink, lw=1.6))
    for yy in (y0, y1):
        ax.plot([x1 + 6, xr], [yy, yy], color=ink, lw=1.0)
    ax.text(xr + 8, (y0 + y1) / 2, "%s %.0f mm" % (v_label, h_mm),
            ha="left", va="center", fontsize=15, color=ink, weight="bold", rotation=90)

    # 100 mm 比例尺 (左下)
    bar = 100.0 * 0.001 * sc
    bx, by = 24, H - 30
    ax.plot([bx, bx + bar], [by, by], color=gold, lw=4, solid_capstyle="butt")
    ax.text(bx + bar / 2, by - 10, "100 mm", ha="center", va="bottom", fontsize=12, color=gold)
    if note:
        ax.text(24, 18, note, ha="left", va="top", fontsize=13, color="#5B6472")
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def main():
    pose = "zero"
    outdir = OUTDIR
    for i, a in enumerate(sys.argv):
        if a == "--pose" and i + 1 < len(sys.argv):
            pose = sys.argv[i + 1]
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    os.makedirs(outdir, exist_ok=True)

    spec = json.load(open(SPEC))
    meshes = load_meshes()
    q_zero = [0.0] * 6
    q_live = spec["live_check"]["jpos"]
    q = q_zero if pose == "zero" else q_live

    T = fk(spec, q)
    tris = world_tris(T, meshes)
    v = tris.reshape(-1, 3)
    lo, hi = v.min(0), v.max(0)
    dims = (hi - lo) * 1000.0
    print("bbox mm  X %.1f  Y %.1f  Z %.1f" % tuple(dims))

    views = {
        "front": (0, 0),        # 从 +X 看: 正面 (前后/上下)
        "side": (90, 0),        # 从 +Y 看: 侧面 (左右方向变深度)
        "top": (0, 89.9),       # 俯视
        "iso": (38, 22),        # 透视视角
    }
    names = {"front": ("总宽(左右)", "总高"), "side": ("总长(前后)", "总高"),
             "top": ("总宽(左右)", "总长(前后)"), "iso": None}
    for name, (az, el) in views.items():
        img, meta = render(tris, rot_cam(az, el))
        p = os.path.join(outdir, f"robot_{pose}_{name}.png")
        save(img, p)
        if names[name]:
            h_lab, v_lab = names[name]
            note = "真机 XMS5-R800-W4G3B4C · %s 姿态 · 厂家 STL" % ("直立(全零)" if pose == "zero" else "作业")
            draw_dims(os.path.join(outdir, f"robot_{pose}_{name}_dim.png"), img, meta, h_lab, v_lab, note)
        print("saved", p, img.shape)

    # TCP 与关键尺寸
    info = dict(pose=pose, q=q, bbox_min_mm=(lo * 1000).round(1).tolist(),
                bbox_max_mm=(hi * 1000).round(1).tolist(), dims_mm=dims.round(1).tolist(),
                link_origin_mm={k: (T[k][:3, 3] * 1000).round(1).tolist() for k in LINK_ORDER})
    json.dump(info, open(os.path.join(outdir, f"robot_{pose}_meta.json"), "w"), ensure_ascii=False, indent=1)
    print("meta ->", os.path.join(outdir, f"robot_{pose}_meta.json"))


if __name__ == "__main__":
    main()
