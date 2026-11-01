#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""robot_3view_deck.py — 机器人三视图 + 尺寸标注 + 坐标系 + 结构参数 PPT。

图纸口径：
  · 外形来自真机 URDF 厂家 STL（XMS5-R800-W4G3B4C）
  · 尺寸标注用 render_robot_views.draw_dims（总宽/总长/总高 + 100mm 比例尺）
  · 坐标系按 tcp-ar.html:2444 的口径：原点=右臂底座，轴长 base 160mm，红X/绿Y/蓝Z，
    叠在图像最上层（AR 页也是这么画的）
  · 结构参数直接读 URDF（关节原点/轴/限位/力矩、连杆质量），不手填

用法: ./gui-venv311/bin/python tools/robot_3view_deck.py --outdir DIR
"""
from __future__ import annotations
import os, sys, json, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import (SPEC, LINK_ORDER, fk, load_meshes, world_tris,
                                render, rot_cam, save, draw_dims)

URDF = "/home/ubuntu/zmax/zmax_data/rokae_sdk/urdf/xms5_r800_w4g3b4c.urdf"
AX_C = {"x": "#ff5d5d", "y": "#5dff8f", "z": "#5db8ff"}
AX_LEN = 0.24          # 图纸上放大到 240mm，160mm 在图里太短看不清（口径仍留在注记里）


def overlay_axes(img_u8, R, meta, origin=(0, 0, 0), length=AX_LEN):
    """世界坐标系叠加层（不参与遮挡），口径同 AR 场景。"""
    lo = np.asarray(meta["lo"], float); scale = float(meta["scale"])
    off = np.asarray(meta["off"], float)

    def proj(p):
        v = np.asarray(p, float) @ R.T
        return (v[:2] - lo) * scale + off

    im = Image.fromarray(img_u8).convert("RGB")
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except Exception:
        f = ImageFont.load_default()
    o = proj(origin)
    for k, dv in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        t = proj(np.asarray(origin, float) + np.array(dv, float) * length)
        d.line([tuple(o), tuple(t)], fill=AX_C[k], width=6)
        d.rectangle([t[0] - 7, t[1] - 7, t[0] + 7, t[1] + 7], fill=AX_C[k])
        d.text((t[0] + 12, t[1] - 12), k.upper(), font=f, fill=AX_C[k])
    d.ellipse([o[0] - 8, o[1] - 8, o[0] + 8, o[1] + 8], fill="#e6edf3", outline="#11161c", width=2)
    d.text((o[0] + 12, o[1] + 8), "base", font=f, fill="#2b3440")
    return im


def read_urdf_params(path=URDF):
    import xml.etree.ElementTree as ET
    r = ET.parse(path).getroot()
    joints, mass = [], {}
    for j in r.iter("joint"):
        nm = j.get("name", "")
        if j.get("type") != "revolute":
            continue
        o = j.find("origin"); a = j.find("axis"); l = j.find("limit")
        xyz = [float(v) for v in (o.get("xyz", "0 0 0").split() if o is not None else [0, 0, 0])]
        ax = [float(v) for v in (a.get("xyz", "0 0 1").split() if a is not None else [0, 0, 1])]
        joints.append(dict(
            name=nm.replace("XMS5-R800-W4G3B4C_", ""), xyz=xyz, axis=ax,
            lo=float(l.get("lower")), hi=float(l.get("upper")),
            vel=float(l.get("velocity")), eff=float(l.get("effort"))))
    for lk in r.iter("link"):
        i = lk.find("inertial")
        if i is not None:
            mass[lk.get("name").replace("XMS5-R800-W4G3B4C_", "")] = float(i.find("mass").get("value"))
    return joints, mass


def solve_work_pose():
    """用 8797 示教点位反解：法兰落在 1 号槽正上方（爪尖入槽）。"""
    from render_ar_work import solve_to_point
    spec = json.load(open(SPEC))
    q, err = solve_to_point(spec, [0.4898, 0.4987, 0.1175 + 0.120])
    return q, err


def main():
    outdir = "/tmp/robot3v"
    for i, a in enumerate(sys.argv):
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    os.makedirs(outdir, exist_ok=True)

    spec = json.load(open(SPEC))
    meshes = load_meshes()
    q, err = solve_work_pose()
    print("作业姿态 q =", [round(float(v), 3) for v in q], "TCP 误差 %.1f mm" % (err * 1000))

    T = fk(spec, q)
    tris = world_tris(T, meshes)
    v = tris.reshape(-1, 3)
    lo, hi = v.min(0), v.max(0)
    dims = (hi - lo) * 1000.0
    print("外形包围盒 mm  X %.0f  Y %.0f  Z %.0f" % tuple(dims))

    views = {"front": (0, 0, ("总宽(左右)", "总高")),
             "side": (90, 0, ("总长(前后)", "总高")),
             "top": (0, 89.9, ("总宽(左右)", "总长(前后)")),
             "iso": (38, 22, None)}
    outs = {}
    for name, (az, el, labs) in views.items():
        R = rot_cam(az, el)
        img, meta = render(tris, R, size=(1700, 1400), ss=2)
        raw = os.path.join(outdir, f"view_{name}.png")
        save(img, raw)
        out = raw
        if labs:
            dim = os.path.join(outdir, f"view_{name}_dim.png")
            draw_dims(dim, img, meta,
                      labs[0], labs[1],
                      "真机 XMS5-R800-W4G3B4C · 作业姿态 · 厂家 STL · 100mm 比例尺")
            out = dim
        # 叠坐标系
        a8 = np.asarray(Image.open(out).convert("RGB"))
        # draw_dims 用 matplotlib 重画过，投影已变，坐标轴改用原始 meta 叠在 raw 上不匹配，
        # 所以只在无标注图(iso)上叠轴；三视图的轴单独出一版无标注+轴
        if labs is None:
            overlay_axes(a8, R, meta).save(out)
        else:
            rax = os.path.join(outdir, f"view_{name}_axes.png")
            a8r = np.asarray(Image.open(raw).convert("RGB"))
            overlay_axes(a8r, R, meta).save(rax)
            outs[name + "_axes"] = rax
            print("saved", rax)
        outs[name] = out
        print("saved", out)

    joints, mass = read_urdf_params()
    meta_all = dict(q=[round(float(v), 3) for v in q], err_mm=round(float(err) * 1000, 2),
                    bbox_mm=dims.round(1).tolist(), dims_mm=dims.round(1).tolist(),
                    joints=joints, mass=mass, total_mass_kg=round(sum(mass.values()), 3),
                    views=outs)
    json.dump(meta_all, open(os.path.join(outdir, "meta.json"), "w"), ensure_ascii=False, indent=1)
    print("总质量 %.3f kg" % sum(mass.values()))


if __name__ == "__main__":
    main()
