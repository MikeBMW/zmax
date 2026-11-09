#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 场景 → YOLO 数据集 (MuJoCo 渲染 + 几何真值标注, 零人工标注)

为什么要这个:
  在役权重 models/yolo_peg_live.pt 是**真机照片**训的, 对 MuJoCo 渲染图 0 检出 (实测:
  全景 640 输入 det=0, close 机位 det=0) —— 域差。老倪 2026-11-10 定的路子是
  550B 调代码 → 550A 微调 → 550C 部署, 本脚本产的就是 550A 要吃的训练集。

标注为什么可信:
  框不是人画的, 是从 **geom 的真值 xpos/xmat/size** 八个角投到画面得到的,
  用的相机就是当时渲染用的那个 MjvCamera (同一个 scn.camera[0]), 所以框与像素**同源**。

用法:
  MUJOCO_GL=osmesa ./gui-venv311/bin/python tools/ar_label_export.py --n 600 --out zmax_data/ar_yolo
  产物: <out>/images/*.jpg  <out>/labels/*.txt  <out>/data.yaml  <out>/stats.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

os.environ.setdefault("MUJOCO_GL", "osmesa")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import numpy as np                          # noqa: E402
import mujoco                               # noqa: E402
from PIL import Image                       # noqa: E402

import ar_mujoco_env                        # noqa: E402

CLASSES = ["OPT_Gold", "hole"]              # 光模块 / 插孔
W, H = 960, 720


def build():
    xml = ar_mujoco_env.build_mjcf()
    model = mujoco.MjModel.from_xml_string(xml)
    return model, mujoco.MjData(model)


def cam_to_px(scn, pts):
    c = scn.camera[0]
    pos = np.array(c.pos, float)
    fwd = np.array(c.forward, float)
    up = np.array(c.up, float)
    fwd /= np.linalg.norm(fwd)
    up /= np.linalg.norm(up)
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    up2 = np.cross(right, fwd)
    fovy = np.radians(float(scn.camera[0].fovy) if hasattr(scn.camera[0], "fovy") else 45.0)
    out = []
    for v in pts:
        d = np.asarray(v, float) - pos
        zc = float(d @ fwd)
        if zc <= 1e-6:
            out.append(None)
            continue
        nx = float(d @ right) / (zc * np.tan(fovy / 2) * (W / H))
        ny = float(d @ up2) / (zc * np.tan(fovy / 2))
        out.append(((nx + 1) * W / 2.0, (1 - ny) * H / 2.0))
    return out


def geom_corners(data, model, gid):
    p = data.geom_xpos[gid]
    R = data.geom_xmat[gid].reshape(3, 3)
    s = model.geom_size[gid]
    return [p + R @ (np.array([sx, sy, sz]) * s) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def yolo_line(cls_i, box):
    x1, y1, x2, y2 = box
    return "%d %.6f %.6f %.6f %.6f" % (cls_i, (x1 + x2) / 2 / W, (y1 + y2) / 2 / H,
                                       (x2 - x1) / W, (y2 - y1) / H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data", "ar_yolo"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--jitter-deg", type=float, default=18.0)
    ap.add_argument("--holdout", type=float, default=0.15)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    for sub in ("images", "images/val", "labels", "labels/val"):
        os.makedirs(os.path.join(a.out, sub), exist_ok=True)

    model, data = build()
    gid = lambda n: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, n)   # noqa: E731
    sid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "hole")
    targets = {"R_mod": 0, "L_mod": 0}
    for nm in ("gold_module",):
        g = gid(nm)
        if g >= 0:
            targets[nm] = 0
    print("model nq=%d ngeom=%d · targets=%s · hole site=%d"
          % (model.nq, model.ngeom, list(targets), sid))
    renderer = mujoco.Renderer(model, H, W)
    opt = mujoco.MjvOption()
    opt.geomgroup[3] = 1
    scn = mujoco.MjvScene(model, maxgeom=20000)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    pert = mujoco.MjvPerturb()

    jl = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "R_j%d" % i) for i in range(6)]
    jl += [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "L_j%d" % i) for i in range(6)]
    jl = [j for j in jl if j >= 0]
    stats = {"n": 0, "kept": 0, "boxes": 0, "per_class": {c: 0 for c in CLASSES}, "skipped": 0}

    # 🎯 基准位姿取**产线在跑的那一组** (ar_mj_q.json), 在它附近抖动 —— 不能从零位随机:
    #   零位(直臂)时 0.26m 特写相机落在前臂内部, 渲出来是黑的 (实测 mean 9.7), 样本直接被丢。
    _base = {}
    try:
        _q = json.load(open(os.path.join(ROOT, "zmax_data", "ss_live", "ar_mj_q.json"), encoding="utf-8"))
        for side in ("R", "L"):
            for i, v in enumerate(_q.get(side) or []):
                _base["%s_j%d" % (side, i)] = float(v)
        print("base pose from ar_mj_q.json · %d joints" % len(_base))
    except Exception as e:                                                     # noqa: BLE001
        print("⚠️ 无基准位姿 (%s) ⇒ 用零位" % e)

    for k in range(a.n):
        for j in jl:
            if rng.random() < 0.6:
                adr = model.jnt_qposadr[j]
                if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE:
                    jn = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j) or ""
                    b = _base.get(jn, 0.0)
                    data.qpos[adr] = np.radians(b + rng.uniform(-a.jitter_deg, a.jitter_deg))
        mujoco.mj_forward(model, data)
        # 🎥 两种机位各占一半, 理由 (2026-11-10 实测):
        #   2.0m 全景下模块 13mm ≈ 3px, 训练/检测都没有意义; 真实工位靠**臂上相机**近距离看件。
        #   所以 60% 用「跟物机位」(与 8802 ?cam=close 同口径: 钉在 R_tcp、正对 R_mod 侧面, 0.2~0.35m),
        #   40% 用全景 (学上下文/抗误检)。两个机位的框都由同一个 MjvCamera 真值投影得到。
        _gmod = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "R_mod")
        _gtcp = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "R_tcp")
        _attempt = 0
        _img_ok = False
        while _attempt < 4 and not _img_ok:
            _attempt += 1
            if rng.random() < 0.6 and _gmod >= 0 and _gtcp >= 0:
                _ax = -data.geom_xmat[_gmod].reshape(3, 3)[:, 0]
                _ax = _ax / (np.linalg.norm(_ax) + 1e-9)
                cam.lookat[:] = data.geom_xpos[_gtcp] + rng.normal(0, 0.004, 3)
                cam.azimuth = float(np.degrees(np.arctan2(_ax[1], _ax[0])) + rng.normal(0, 12))
                cam.elevation = float(np.degrees(np.arcsin(np.clip(_ax[2], -1, 1))) + rng.normal(0, 10))
                cam.distance = float(rng.uniform(0.20, 0.38))
                model.vis.global_.fovy = float(rng.uniform(45, 60))
                cam_kind = "close"
            else:
                cam.azimuth = float(rng.uniform(-75, 25))
                cam.elevation = float(rng.uniform(-50, -12))
                cam.distance = float(rng.uniform(1.5, 2.8))
                cam.lookat[:] = [float(rng.uniform(0.25, 0.65)), float(rng.uniform(0.15, 0.4)),
                                 float(rng.uniform(0.05, 0.3))]
                model.vis.global_.fovy = float(rng.uniform(55, 70))
                cam_kind = "wide"
            mujoco.mjv_updateScene(model, data, opt, pert, cam, mujoco.mjtCatBit.mjCAT_ALL, scn)
            renderer.update_scene(data, cam, opt)
            img = renderer.render()
            # 🚫 均值 <20 = 相机埋在臂体/箱体里 (实测直臂 pose 下 0.26m 机位会落在前臂内部, 画面全黑)
            _img_ok = float(img.mean()) >= 20.0
        if not _img_ok:
            stats["skipped"] += 1
            continue

        lines = []
        for nm, ci in targets.items():
            g = gid(nm)
            if g < 0:
                continue
            pts = cam_to_px(scn, geom_corners(data, model, g))
            pts = [p for p in pts if p]
            if len(pts) < 4:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x1, x2 = max(0, min(xs)), min(W, max(xs))
            y1, y2 = max(0, min(ys)), min(H, max(ys))
            if x2 - x1 < 6 or y2 - y1 < 6:
                continue
            # 可见性: 中心点周围不能全是背景(暗), 否则框在遮挡物后面
            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
            patch = img[max(0, cy - 3):cy + 4, max(0, cx - 3):cx + 4]
            if patch.size and float(patch.mean()) < 12:
                continue
            lines.append(yolo_line(ci, (x1, y1, x2, y2)))
            stats["per_class"][CLASSES[ci]] += 1
        if sid >= 0:
            c3 = data.site_xpos[sid]
            Rz = data.site_xmat[sid].reshape(3, 3)
            half = 0.008
            pts = cam_to_px(scn, [c3 + Rz @ np.array([sx * half, sy * half, 0])
                                  for sx in (-1, 1) for sy in (-1, 1)])
            pts = [p for p in pts if p]
            if len(pts) == 4:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                x1, x2 = max(0, min(xs)), min(W, max(xs))
                y1, y2 = max(0, min(ys)), min(H, max(ys))
                if x2 - x1 >= 4 and y2 - y1 >= 4:
                    lines.append(yolo_line(1, (x1, y1, x2, y2)))
                    stats["per_class"]["hole"] += 1
        stats["n"] += 1
        if not lines:
            stats["skipped"] += 1
            continue
        sub = "val" if rng.random() < a.holdout else ""
        jpg = os.path.join(a.out, "images", sub, "ar_%05d.jpg" % k)
        lab = os.path.join(a.out, "labels", sub, "ar_%05d.txt" % k)
        Image.fromarray(img).save(jpg, quality=92)
        with open(lab, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        stats["kept"] += 1
        stats.setdefault("cam_" + cam_kind, 0)
        stats["cam_" + cam_kind] += 1
        stats["boxes"] += len(lines)
        if (k + 1) % 100 == 0:
            print("… %d/%d kept=%d boxes=%d" % (k + 1, a.n, stats["kept"], stats["boxes"]), flush=True)

    with open(os.path.join(a.out, "data.yaml"), "w", encoding="utf-8") as f:
        f.write("path: %s\ntrain: images\nval: images/val\nnames:\n" % a.out)
        for i, c in enumerate(CLASSES):
            f.write("  %d: %s\n" % (i, c))
    with open(os.path.join(a.out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print("done", stats)


if __name__ == "__main__":
    main()
