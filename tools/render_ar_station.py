#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_ar_station.py — 直接渲染 AR 场景本身（ar_station.xml），不自己造几何。

老倪口径：尺寸和外形在 AR 场景里已经画好了，要渲成一模一样的。
所以这里不新建表格/料盘，而是把 zmax_data/ar_mujoco/ar_station.xml 原样载入
MuJoCo 渲一遍 —— 台面、4 个料盘、42 个槽位、插孔口、双臂胶囊，全部是实测坐标。

注意：必须**先放大离屏缓冲**再建 Renderer（mujoco 默认 offwidth=480，否则黑帧）。

用法: ./gui-venv311/bin/python tools/render_ar_station.py --outdir DIR
"""
from __future__ import annotations
import os, sys, json

os.environ.setdefault("MUJOCO_GL", "osmesa")     # headless 必给

XML = "/home/ubuntu/zmax/zmax_data/ar_mujoco/ar_station.xml"

# 机位候选：az 绕 z 轴、el 俯角、dist 距离；lookat 对准料盘群中心
LOOKAT = [0.5188, 0.2500, 0.1500]
VIEWS = {
    "iso":   dict(azimuth=135.0, elevation=-28.0, distance=1.55),
    "iso2":  dict(azimuth=118.0, elevation=-34.0, distance=1.42),
    "front": dict(azimuth=160.0, elevation=-22.0, distance=1.60),
    "top34": dict(azimuth=128.0, elevation=-46.0, distance=1.45),
}


def arg(flag, default=None):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    import mujoco
    import numpy as np
    from PIL import Image

    outdir = arg("--outdir", "/tmp/ar_station")
    W = int(arg("--w", "1920"))
    H = int(arg("--h", "1440"))
    os.makedirs(outdir, exist_ok=True)

    # 先放大离屏缓冲，再建 Renderer（顺序不能反）
    spec = mujoco.MjSpec.from_file(XML)
    model = spec.compile()
    model.vis.global_.offwidth = max(model.vis.global_.offwidth, W)
    model.vis.global_.offheight = max(model.vis.global_.offheight, H)
    model.vis.quality.shadowsize = 8192
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)

    ren = mujoco.Renderer(model, height=H, width=W)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = LOOKAT
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE

    print("geoms=%d  nq=%d  offscreen=%dx%d" %
          (model.ngeom, model.nq, model.vis.global_.offwidth, model.vis.global_.offheight))

    out = {}
    for name, v in VIEWS.items():
        cam.azimuth = v["azimuth"]
        cam.elevation = v["elevation"]
        cam.distance = v["distance"]
        ren.update_scene(data, camera=cam)
        img = ren.render()                      # RGB (H, W, 3) uint8
        p = os.path.join(outdir, f"ar_station_{name}.png")
        Image.fromarray(img).save(p)
        nb = int((np.asarray(img)[..., :3].max(axis=2) > 12).sum())
        print("saved %-42s %dx%d  nonblack=%d  (az=%.0f el=%.0f d=%.2f)"
              % (p, img.shape[1], img.shape[0], nb, v["azimuth"], v["elevation"], v["distance"]))
        out[name] = dict(path=p, **v, nonblack=nb)

    json.dump(dict(xml=XML, lookat=LOOKAT, w=W, h=H, views=out),
              open(os.path.join(outdir, "meta.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
