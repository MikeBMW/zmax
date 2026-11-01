#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_zmax_workcell.py — 按 zmax 工程 web 源码里的真实规格渲染工位。

数据全部来自 tools/web/tcp-ar.html（不截图、不自己造）：

  z=0  = 两臂安装面 = 桌面顶        ← 基准平面
  z=-0.750 = 地面（轮底 / 桌腿落地）

  CHS 底盘箱体  L=0.600 W=0.800 H=0.750(本体0.680+轮0.070) cy=0.25 wr=0.075
       body #1b2732  plate #31404f  edge #7f95ad
  TAB 实验桌    x0=0.35 x1=0.95 cy=0.25 w=1.600 t=0.030 leg=0.045
       top #7a5f45  body #54402f  legc #4a4f58  edge #d8b98c  alu #a8b3bf
  FLR 地面      x[-0.50,1.25] y[-0.70,1.20] z=-0.750
  LARM 左臂偏置 [0, 0.5, 0]（右臂在 y=0）
  LINK_COL 真机外形按连杆循环取色（蓝灰梯度）

料盘/槽位/插孔口 ← zmax_data/ar_mujoco/ar_station.xml（实测坐标，槽中心 z=0.1175，
与 tcp-ar.html:4546 的 Z=0.1175 一致，说明两者同一坐标系）

用法: ./gui-venv311/bin/python tools/render_zmax_workcell.py --outdir DIR
"""
from __future__ import annotations
import os, sys, json, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import SPEC, LINK_ORDER, fk, load_meshes, render, save
from render_ar_work import load_station, solve_to_point

XML = "/home/ubuntu/zmax/zmax_data/ar_mujoco/ar_station.xml"

# ── 以下常量逐字来自 tools/web/tcp-ar.html ────────────────────────────
CHS = dict(L=0.600, W=0.800, H=0.750, HB=0.680, cy=0.25, wr=0.075,
           body="#1b2732", plate="#31404f", edge="#7f95ad")
TAB = dict(x0=0.35, x1=0.95, cy=0.25, w=1.600, t=0.030, leg=0.045, h=0.750,
           top="#7a5f45", body="#54402f", legc="#4a4f58", edge="#d8b98c",
           alu="#a8b3bf", aluEdge="#6f7c8a", aluDark="#5c666f")
FLR = dict(x=(-0.50, 1.25), y=(-0.70, 1.20), z=-0.750)
LARM_OFF = (0.0, 0.5, 0.0)
WEB_CAM = dict(yaw=-0.9, pitch=0.55, dist=1.6, tgt=[0.70, 0.22, 0.14])

LINK_COL = [("#3d4b5c", "#7f95ad"), ("#43536a", "#8ba6c4"), ("#445a6e", "#8fbfd6"),
            ("#4a5f6b", "#9ac6c9"), ("#4d5568", "#a7b8d8"), ("#5a5568", "#c3b6d8"),
            ("#6a5a4d", "#d8c0a0"), ("#7a6a3f", "#ffd166"), ("#7a7a3f", "#ffe08a"),
            ("#808080", "#d0d0d0")]


def hx(s):
    s = s.lstrip("#")
    return np.array([int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])


def box(lo, hi, col_top, col_side=None):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]])
    faces = [((0, 2, 1), (0, 3, 2), 0), ((4, 5, 6), (4, 6, 7), 1),
             ((0, 1, 5), (0, 5, 4), 0), ((1, 2, 6), (1, 6, 5), 0),
             ((2, 3, 7), (2, 7, 6), 0), ((3, 0, 4), (3, 4, 7), 0)]
    tris, cols = [], []
    for f1, f2, is_top in faces:
        for f in (f1, f2):
            tris.append([v[a] for a in f])
            cols.append(col_top if is_top else (col_side if col_side is not None else col_top))
    return np.array(tris), np.array(cols)


def wheel_y(cx, cy, cz, r, width):
    """轮子：轴沿 y 的圆柱。"""
    n = 20
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([np.cos(ang), np.zeros(n), np.sin(ang)], axis=1) * r
    A = ring + np.array([cx, cy - width / 2, cz])
    B = ring + np.array([cx, cy + width / 2, cz])
    tris = []
    for i in range(n):
        j = (i + 1) % n
        tris.append([A[i], B[i], B[j]])
        tris.append([A[i], B[j], A[j]])
    c0 = np.array([cx, cy - width / 2, cz]); c1 = np.array([cx, cy + width / 2, cz])
    for i in range(n):
        j = (i + 1) % n
        tris.append([c0, A[j], A[i]])
        tris.append([c1, B[i], B[j]])
    return np.array(tris)


def prism_z(cx, cy, z0, z1, r, n=20):
    """竖直圆柱（轴沿 z）。"""
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.stack([np.cos(ang), np.sin(ang), np.zeros(n)], axis=1) * r
    A = ring + np.array([cx, cy, z0])
    B = ring + np.array([cx, cy, z1])
    tris = []
    for i in range(n):
        j = (i + 1) % n
        tris.append([A[i], B[i], B[j]])
        tris.append([A[i], B[j], A[j]])
    ca = np.array([cx, cy, z0]); cb = np.array([cx, cy, z1])
    for i in range(n):
        j = (i + 1) % n
        tris.append([ca, A[j], A[i]])
        tris.append([cb, B[i], B[j]])
    return np.array(tris)


def box_rot(center, size, R):
    """任意朝向盒子：size=(sx,sy,sz) 局部半尺寸，R 3x3 旋转，center 平移。"""
    sx, sy, sz = size
    sgn = np.array([[i, j, k] for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)], float)
    loc = sgn * np.array([sx, sy, sz])
    w = loc @ R.T + np.asarray(center, float)
    idx = {(-1, -1, -1): 0, (-1, -1, 1): 1, (-1, 1, -1): 2, (-1, 1, 1): 3,
           (1, -1, -1): 4, (1, -1, 1): 5, (1, 1, -1): 6, (1, 1, 1): 7}
    f = [((-1,-1,-1),(-1,1,-1),(1,1,-1)),((-1,-1,-1),(1,1,-1),(1,-1,-1)),
         ((-1,-1,1),(1,1,1),(-1,1,1)),((-1,-1,1),(1,-1,1),(1,1,1)),
         ((-1,-1,-1),(1,-1,-1),(1,-1,1)),((-1,-1,-1),(1,-1,1),(-1,-1,1)),
         ((-1,1,-1),(-1,1,1),(1,1,1)),((-1,1,-1),(1,1,1),(1,1,-1)),
         ((1,-1,-1),(1,1,-1),(1,1,1)),((1,-1,-1),(1,1,1),(1,-1,1)),
         ((-1,-1,-1),(-1,-1,1),(-1,1,1)),((-1,-1,-1),(-1,1,1),(-1,1,-1))]
    return np.array([[w[idx[a]], w[idx[b]], w[idx[c]]] for a, b, c in f])


def build_workcell():
    parts = []          # (tris, colors)

    # ── 地面 ──
    t, c = box((FLR["x"][0], FLR["y"][0], FLR["z"] - 0.004),
               (FLR["x"][1], FLR["y"][1], FLR["z"]), hx("#2a2f36"))
    parts.append((t, c))

    # ── 底盘箱体 ──
    L, W, HB, cy = CHS["L"], CHS["W"], CHS["HB"], CHS["cy"]
    t, c = box((-L / 2, cy - W / 2, -HB), (L / 2, cy + W / 2, 0.0),
               hx(CHS["plate"]), hx(CHS["body"]))
    parts.append((t, c))
    # 防撞条
    bz0, bz1 = -HB * 0.62, -HB * 0.38
    t, c = box((-L / 2 - 0.004, cy - W / 2 - 0.004, bz0),
               (L / 2 + 0.004, cy + W / 2 + 0.004, bz1), hx("#0d1418"))
    parts.append((t, c))
    # 四个轮子（Ø150，轴沿 y，轮底落在 z=-0.750）
    r, th = CHS["wr"], 0.035
    fl = -CHS["H"]
    for sx in (-1, 1):
        for sy in (-1, 1):
            wt = wheel_y(sx * (L / 2 - 0.13), cy + sy * (W / 2 - 0.03), fl + r, r, th)
            parts.append((wt, np.tile(hx("#14181e"), (len(wt), 1))))

    # ── 实验桌 ──
    x0, x1, y0, y1 = TAB["x0"], TAB["x1"], TAB["cy"] - TAB["w"] / 2, TAB["cy"] + TAB["w"] / 2
    t, c = box((x0, y0, -TAB["t"]), (x1, y1, 0.0), hx(TAB["top"]), hx(TAB["body"]))
    parts.append((t, c))
    lg = TAB["leg"]
    ins = 0.012 + lg / 2
    xa, xb, ya, yb = x0 + ins, x1 - ins, y0 + ins, y1 - ins
    zTop = -TAB["t"]        # 立柱顶 = 桌面底面（原来 -0.16 会让桌面浮空 130mm）
    for cx, cyy in ((xa, ya), (xb, yb), (xa, yb), (xb, ya)):
        t, c = box((cx - lg / 2, cyy - lg / 2, fl), (cx + lg / 2, cyy + lg / 2, zTop),
                   hx(TAB["alu"]), hx(TAB["aluEdge"]))
        parts.append((t, c))
    # 下横撑（离地 120，高 60）
    cz0, cz1 = fl + 0.12, fl + 0.18
    for yy in (ya, yb):
        t, c = box((xa, yy - 0.02, cz0), (xb, yy + 0.02, cz1), hx(TAB["aluDark"]))
        parts.append((t, c))
    # 顶部框架：两根长梁沿 y + 两端横梁
    zR0, zR1 = zTop - lg, zTop
    for xx in (xa, xb):
        t, c = box((xx - lg / 2, ya - lg / 2, zR0), (xx + lg / 2, yb + lg / 2, zR1), hx(TAB["alu"]))
        parts.append((t, c))
    for yy in (ya, yb):
        t, c = box((xa - lg / 2, yy - lg / 2, zR0), (xb + lg / 2, yy + lg / 2, zR1), hx(TAB["alu"]))
        parts.append((t, c))

    # 料盘垫高台：实测料盘底在 z=0.100，桌面顶 z=0 ⇒ 补 100mm 垫块，否则料盘悬空
    trays = [(0.5188, 0.3478, 0.1329, 0.1967), (0.5188, 0.7712, 0.1329, 0.1967),
             (0.5188, -0.0756, 0.1329, 0.1967), (0.5188, -0.4023, 0.1000, 0.1000)]
    for tx, ty, hx_, hy_ in trays:
        t, c = box((tx - hx_ - 0.004, ty - hy_ - 0.004, 0.0), (tx + hx_ + 0.004, ty + hy_ + 0.004, 0.100),
                   hx(TAB["alu"]), hx(TAB["aluEdge"]))
        parts.append((t, c))
    # ── 中央顶视相机 TCAM（web: y=0.25, r=0.070, 立柱轴高=joint_1 0.328, tilt 35°）──
    CR, CY, CH, TILT = 0.070, 0.25, 0.328, math.radians(35.0)
    t = prism_z(0.0, CY, 0.0, CH, CR)            # 立柱
    parts.append((t, np.tile(hx("#2a333f"), (len(t), 1))))
    t = prism_z(0.0, CY, CH, CH + 0.008, CR)     # 顶盖(亮一点)
    parts.append((t, np.tile(hx("#3f4d5c"), (len(t), 1))))
    t = prism_z(0.0, CY, 0.0, 0.014, CR * 1.35, n=24)      # 底座法兰
    parts.append((t, np.tile(hx("#4b5a6b"), (len(t), 1))))
    # 机身 90(W y向)×25(H)×25(D x向)，绕 Y 俯 35°（朝 +X 看）
    Ry = np.array([[math.cos(TILT), 0, math.sin(TILT)],
                   [0, 1, 0],
                   [-math.sin(TILT), 0, math.cos(TILT)]])
    body_c = np.array([0.0, CY, CH + 0.006]) + Ry @ np.array([0.0, 0.0, 0.0125])
    t = box_rot(body_c, (0.0125, 0.045, 0.0125), Ry)
    parts.append((t, np.tile(hx("#1b2430"), (len(t), 1))))
    # 前面板三个镜头（左IR/蓝RGB/右IR）
    for dy, colr in ((-0.031, "#0b0f14"), (0.0, "#1d4ed8"), (0.031, "#0b0f14")):
        lp = body_c + Ry @ np.array([0.0135, dy, 0.0])
        t = box_rot(lp, (0.0015, 0.007, 0.007), Ry)
        parts.append((t, np.tile(hx(colr), (len(t), 1))))

    # 插孔口夹具底板（web drawInspHoles: cy=278mm，底板厚 10mm）
    t, c = box((0.7905 - 0.036, 0.196, 0.264), (0.7905 + 0.036, 0.262, 0.274), hx("#161d26"), hx("#3d4b5a"))
    parts.append((t, c))

    return parts


def robot_at(meshes, q, spec, y_off=0.0, color_shift=0):
    """真机 STL 按连杆取色，可整体沿 y 平移（左臂）。"""
    T = fk(spec, q)
    tris, cols = [], []
    for i, link in enumerate(LINK_ORDER):
        if link not in meshes:
            continue
        M = T[link]
        v = meshes[link].reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        v[:, 1] += y_off
        tris.append(v.reshape(-1, 3, 3))
        cols.append(np.tile(hx(LINK_COL[(i + color_shift) % len(LINK_COL)][0]), (len(v) // 3, 1)))
    return np.concatenate(tris, axis=0), np.concatenate(cols, axis=0)


def web_view_rot(cam=WEB_CAM):
    yaw, pitch, dist = cam["yaw"], cam["pitch"], cam["dist"]
    tgt = np.array(cam["tgt"], float)
    eye = tgt + dist * np.array([math.cos(pitch) * math.sin(yaw),
                                 math.cos(pitch) * math.cos(yaw),
                                 math.sin(pitch)])
    # 🔴 render() 的 z-buffer 保留 **更大** 的 camz ⇒ 相机 z 轴要指向观察者
    #    (等价"相机看向 -Z")。若让它指向场景内部，远物会盖住近物 —— 实测机械臂
    #    会被台面整片切掉，只剩基座碗口。
    z = (eye - tgt); z /= np.linalg.norm(z)
    x = np.cross(np.array([0.0, 0.0, 1.0]), z); x /= np.linalg.norm(x)
    y = np.cross(x, z)        # 🔴 必须 x×z：render() 行号向下=+camy，反过来整图会上下颠倒
    print("相机 eye=(%.2f,%.2f,%.2f) tgt=%s" % (*eye, np.round(tgt, 2).tolist()))
    return np.vstack([x, y, z])


def overlay_axes(img_u8, R, meta, axes=None):
    """把 base 世界坐标系画在图像最上层（不参与遮挡）—— 与 tcp-ar.html 的做法一致。

    投影用的是 render() 返回的元数据：px = (v_cam[:2] - lo) * scale + off
    """
    from PIL import Image, ImageDraw, ImageFont
    if axes is None:
        axes = dict(origin=(0.0, 0.0, 0.0), length=0.160,
                    cols={"x": "#ff5d5d", "y": "#5dff8f", "z": "#5db8ff"},
                    tips={"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)})
    lo = np.asarray(meta["lo"], float)
    scale = float(meta["scale"])
    off = np.asarray(meta["off"], float)

    def proj(p):
        v = np.asarray(p, float) @ R.T
        return (v[:2] - lo) * scale + off

    im = Image.fromarray(img_u8).convert("RGB")
    d = ImageDraw.Draw(im)
    try:
        f_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except Exception:
        f_big = ImageFont.load_default()

    o3 = np.asarray(axes["origin"], float)
    o2 = proj(o3)
    for k, dirv in axes["tips"].items():
        tip = o3 + np.asarray(dirv, float) * axes["length"]
        t2 = proj(tip)
        d.line([tuple(o2), tuple(t2)], fill=axes["cols"][k], width=6)
        # 轴端画个小方头 + 标签
        d.rectangle([t2[0] - 7, t2[1] - 7, t2[0] + 7, t2[1] + 7], fill=axes["cols"][k])
        d.text((t2[0] + 11, t2[1] - 11), k.upper(), font=f_big, fill=axes["cols"][k])
    d.ellipse([o2[0] - 8, o2[1] - 8, o2[0] + 8, o2[1] + 8], fill="#e6edf3",
              outline="#11161c", width=2)
    d.text((o2[0] + 12, o2[1] + 6), "base", font=f_big, fill="#e6edf3")
    return im


def main():
    outdir = "/tmp/zmax_cell"
    for i, a in enumerate(sys.argv):
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    W = int(os.environ.get("CELL_W", "1920"))
    H = int(os.environ.get("CELL_H", "1440"))
    os.makedirs(outdir, exist_ok=True)

    spec = json.load(open(SPEC))
    meshes = load_meshes()

    # 对称取件：右臂 → b38_下槽7 (0.493, -0.218)，左臂 → b20_左槽5 (0.493, +0.727)
    # 两槽关于中央相机 y=0.25 严格对称，双臂各自背离相机 ⇒ 不遮挡
    target = [0.493, -0.218, 0.1175 + 0.120]
    q, err = solve_to_point(spec, target)
    print("右臂 q =", [round(float(v), 3) for v in q], " TCP 误差 %.1f mm" % (err * 1000))
    # 左臂：目标在左料盘 1 号槽 (0.4898, 0.9221)，扣掉左臂原心偏置 y+0.5
    qL, errL = solve_to_point(spec, [0.493, 0.727 - LARM_OFF[1], 0.1175 + 0.120])
    print("左臂 q =", [round(float(v), 3) for v in qL], " TCP 误差 %.1f mm" % (errL * 1000))

    parts = build_workcell()

    # 料盘/槽位（AR 场景实测），去掉伪地面与胶囊臂
    st_t, st_c = load_station(skip_arms=True, skip_floor=True, skip_table=True)
    parts.append((st_t, st_c))

    # 右臂（y=0）+ 左臂（y=+0.5，同一套关节角 —— 与 web 默认一致）
    parts.append(robot_at(meshes, q, spec, 0.0))
    parts.append(robot_at(meshes, qL, spec, LARM_OFF[1], color_shift=3))

    # 夹爪（URDF 只到 link6 法兰，厂家没给爪）—— 两指平行爪，指尖落进槽里
    for qq, off in ((q, 0.0), (qL, LARM_OFF[1])):
        fl = fk(spec, qq)[LINK_ORDER[-1]][:3, 3]
        gx, gy, gz = fl[0], fl[1] + off, fl[2]
        parts.append(box((gx - 0.045, gy - 0.030, gz - 0.052), (gx + 0.045, gy + 0.030, gz), hx("#2b3442")))
        for dx in (-0.026, 0.026):          # 指间距收到 ±26mm：正好夹住 ±20mm 的光模块
            parts.append(box((gx + dx - 0.007, gy - 0.024, gz - 0.112), (gx + dx + 0.007, gy + 0.024, gz - 0.050), hx("#39434f")))

    tris = np.concatenate([p[0] for p in parts], axis=0)
    cols = np.concatenate([p[1] for p in parts], axis=0)
    print("总三角形 %d，其中场景 %d、机器人 %d" %
          (len(tris), len(st_t) + sum(len(p[0]) for p in build_workcell()),
           len(tris) - len(st_t) - sum(len(p[0]) for p in build_workcell())))

    R = web_view_rot()
    from render_robot_views import rot_cam
    for nm, RR in {"cell_web": R, "cell_side": rot_cam(24, 18), "cell_high": rot_cam(52, 26)}.items():
        img, meta_r = render(tris, RR, size=(W, H), ss=2, bg=1.0, colors=cols)
        a = np.asarray(img).astype(np.float64)
        if a.max() > 1.5:
            a /= 255.0
        a = np.clip(a, 0, 1) ** 0.72          # gamma 提亮暗部（原图中位亮度仅 17/255）
        a = np.clip(a * 1.06, 0, 1)
        img = (a * 255).astype(np.uint8)
        p = os.path.join(outdir, nm + ".png")
        save(img, p, dpi=150)
        overlay_axes(img, RR, meta_r).save(p)      # 坐标系叠在最上层
        a = np.asarray(img)
        nz = float((a.min(axis=2) < 245).mean()) * 100
        print("saved %-22s %s 主体 %.1f%%" % (p, img.shape, nz))

    json.dump(dict(q=[round(float(v), 4) for v in q], target=target,
                   err_mm=round(float(err) * 1000, 2), camera=WEB_CAM,
                   src="tools/web/tcp-ar.html 常量 + ar_station.xml 料盘"),
              open(os.path.join(outdir, "meta.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
