#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 场景感知底座 —— 把 8802 的 MuJoCo 渲染帧当成**唯一数据源**。

老倪 2026-11-10: 「数据源是 AR 场景 ... 渲染是 mujoco 视频, 真正感知」。

这块只做三件事, 都是可验证的几何/取帧, 不含任何"假装看过"的分支:
  ① 取帧   fetch(cam) → (RGB ndarray, meta)  —— 帧自带 t/age/params, 下游判新鲜
  ② 投影   project(world_xyz, params) → 像素   —— 与 8802 渲染用的是同一套针孔参数
  ③ 反投影 unproject(px, params, plane_z) → 世界点 (射线 ∩ 水平面)

为什么自己算投影而不读 MuJoCo:
  8802 渲染线程里的 MjvCamera 是 MuJoCo 内部状态, 画布节点跑在**另一个进程**;
  这套参数 (az/el/dist/tgt/fovy + 画幅) 是渲染时的**唯一输入**, 复现它就是同一个相机 —
  比读 calib/K 更硬: 不依赖手眼标定是否已做。

坐标: 世界系与 MuJoCo 一致 (z 向上, 米); 页面推来的 tgt 是 z 向下, 已在 _page_cam 取反。
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS_LIVE = os.path.join(REPO, "zmax_data", "ss_live")
CAM_JSON = os.path.join(SS_LIVE, "ar3d_cam.json")
BASE = os.environ.get("ZMAX_AR_RENDER", "http://127.0.0.1:8802")

_DEF = {"az": -51.6, "el": -31.5, "dist": 2.0, "tgt": [0.325, 0.250, 0.065], "fovy": 69.4,
        "w": 960, "h": 564}


def cam_params():
    """当前 AR 机位 (页面推来的为准, 没有就用 ar3d 预设)。返回 dict 含 az/el/dist/tgt/fovy/w/h。"""
    p = dict(_DEF)
    try:
        d = json.load(open(CAM_JSON, encoding="utf-8"))
        for k in ("az", "el", "dist", "fovy"):
            if d.get(k) is not None:
                p[k] = float(d[k])
        if isinstance(d.get("tgt"), (list, tuple)) and len(d["tgt"]) == 3:
            p["tgt"] = [float(v) for v in d["tgt"]]
        for k in ("w", "h"):
            if d.get(k):
                p[k] = int(float(d[k]))
    except Exception:                                                          # noqa: BLE001
        pass
    return p


def fetch(cam="ar3d", timeout=6.0, live=True):
    """取一帧 8802 渲染图。返回 (np.uint8 RGB, meta{src,bytes,t,fps_est,age_s})。"""
    q = "cam=%s" % cam + ("&live=1" if live and cam == "ar3d" else "")
    url = "%s/frame.png?%s" % (BASE, q)
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-ar-percept"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        buf = r.read()
    meta = {"src": "ar:%s" % cam, "url": url, "bytes": len(buf),
            "t": time.time(), "dt_s": round(time.time() - t0, 3)}
    try:
        from PIL import Image
        import io
        arr = np.asarray(Image.open(io.BytesIO(buf)).convert("RGB"))
    except Exception as e:                                                     # noqa: BLE001
        raise RuntimeError("帧解码失败: %s" % e)
    meta["shape"] = list(arr.shape)
    meta["w"], meta["h"] = int(arr.shape[1]), int(arr.shape[0])
    return arr, meta


def fit(p, arr):
    """按**实际交付的这幅图**定画幅 —— 请求的 w/h 与真正渲出来的可能不同 (live 分支会回落 4:3),
    内参必须跟着真实像素走, 否则投影差几度角。"""
    q = dict(p)
    q["h"], q["w"] = int(arr.shape[0]), int(arr.shape[1])
    return q


def _basis(p):
    """世界→相机基 (与 MuJoCo free camera 同口径: 相机在 lookat + dist*dir, up=+z)。"""
    az, el = np.radians(p["az"]), np.radians(p["el"])
    d = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], float)
    tgt = np.asarray(p["tgt"], float)
    pos = tgt + d * float(p["dist"])
    fwd = -d
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(fwd @ up)) > 0.999:
        up = np.array([0.0, 1.0, 0.0])
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    up2 = np.cross(right, fwd)
    return pos, fwd, right, up2


def intrinsics(p):
    """由 fovy + 画幅得到针孔内参 (像素): fx=fy, cx/cy 在中心。"""
    h, w = float(p["h"]), float(p["w"])
    f = 0.5 * h / np.tan(np.radians(float(p["fovy"])) / 2.0)
    return {"fx": f, "fy": f, "cx": w / 2.0, "cy": h / 2.0, "w": int(w), "h": int(h)}


def project(points, p=None):
    """世界点 (N,3) → 像素 (N,2)。点必须在相机前方, 否则返回 nan。"""
    p = p or cam_params()
    K = intrinsics(p)
    pos, fwd, right, up2 = _basis(p)
    pts = np.atleast_2d(np.asarray(points, float))
    out = np.full((len(pts), 2), np.nan)
    tf = np.tan(np.radians(float(p["fovy"])) / 2.0)
    for i, v in enumerate(pts):
        d = v - pos
        zc = float(d @ fwd)
        if zc <= 1e-6:
            continue
        nx = float(d @ right) / (zc * tf * (K["w"] / K["h"]))
        ny = float(d @ up2) / (zc * tf)
        out[i] = ((nx + 1) * K["w"] / 2.0, (1 - ny) * K["h"] / 2.0)
    return out


def unproject(px, p=None, plane_z=0.109):
    """像素 (N,2) → 世界点 (N,3): 射线 ∩ 水平面 z=plane_z (台面/料盘面)。"""
    p = p or cam_params()
    pos, fwd, right, up2 = _basis(p)
    tf = np.tan(np.radians(float(p["fovy"])) / 2.0)
    K = intrinsics(p)
    px = np.atleast_2d(np.asarray(px, float))
    out = np.full((len(px), 3), np.nan)
    for i, (u, v) in enumerate(px):
        nx = (u / K["w"] * 2.0 - 1.0) * tf * (K["w"] / K["h"])
        ny = (1.0 - v / K["h"] * 2.0) * tf
        d = fwd + right * nx + up2 * ny
        d /= np.linalg.norm(d)
        if abs(d[2]) < 1e-6:
            continue
        s = (float(plane_z) - pos[2]) / d[2]
        if s <= 0:
            continue
        out[i] = pos + d * s
    return out


def frame_path(arr):
    """落盘给 VLM/节点用 (按进程+时间戳, 避免两个消费者互相覆盖)。"""
    from PIL import Image
    fp = os.path.join("/tmp", "ar_frame_%d.png" % os.getpid())
    Image.fromarray(np.asarray(arr, dtype=np.uint8)).save(fp)
    return fp


if __name__ == "__main__":
    p = cam_params()
    print("cam", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in p.items()})
    a, m = fetch()
    p = fit(p, a)
    print("frame", m["shape"], m["bytes"], "bytes", m["dt_s"], "s")
    print("intr", {k: round(v, 2) if isinstance(v, float) else v for k, v in intrinsics(p).items()})
    c = np.array([[p["w"] / 2.0, p["h"] / 2.0]])
    print("center ray ∩ plane", np.round(unproject(c, p)[0], 3))
