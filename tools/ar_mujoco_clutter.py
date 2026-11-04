#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_mujoco_clutter.py — AR 工位「带干扰件」自动造数据 (像素级真值, 有真实提升空间)

为什么要有它 (老倪 2026-11-04「结合 AR 场景, 自动生成数据, 自己进化」)
    干净场景已饱和: 在役 models/yolo_ar_peg.pt 在原始留出集 mAP50=0.995 / 难档(模糊暗光噪声) 0.995,
    「有提升」在该口径上数学上不可达 ⇒ 进化没有搜索空间。
    真机现场是**一盘子同色系模块挨在一起**: 误检(fp)才是主要失败模式。这里在料盘里随机撒
    K 个**非金色**干扰模块 (白银/蓝/红/绿/近灰), 只有 `gold_module` 有标签:
      · 几何真值来源 = 渲染图里金色像素的连通域 (与 ar_mujoco_dataset 同一把尺)
      · 干扰件颜色**故意选成过不了金色判据**的色 (银/白/蓝/红/绿), 所以标签不会被干扰件污染;
      · 每张图再做自检: 金色像素必须以**单一连通域**为主, 否则该图判「歧义」直接丢弃并计数 ⇒ 不编标签。

用法
    python tools/ar_mujoco_clutter.py --gen --n 240 --clutter 4 --seed 9001 --out <dir>
    python tools/ar_mujoco_clutter.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import os.path as osp
import random
import sys

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, osp.join(ROOT, "tools"))

W, H = 960, 720
GOLD_RGBA = "0.94 0.76 0.22 1"
# 全部**过不了**金色判据 (R>120 & G>85 & R-B>40 & G-B>20) 的颜色
DISTRACTOR_RGBA = [
    (0.78, 0.78, 0.80, 1),   # 银白模块
    (0.86, 0.88, 0.92, 1),   # 白壳
    (0.16, 0.34, 0.70, 1),   # 蓝色拉环
    (0.72, 0.18, 0.16, 1),   # 红色防尘帽
    (0.20, 0.55, 0.30, 1),   # 绿色标签
    (0.45, 0.45, 0.42, 1),   # 金属灰
]


def _gold_mask(img):
    a = img.astype(int)
    return ((a[:, :, 0] > 120) & (a[:, :, 1] > 85) &
            (a[:, :, 0] - a[:, :, 2] > 40) & (a[:, :, 1] - a[:, :, 2] > 20))


def _components(mask):
    """4-邻域连通域 → [(area, x1,y1,x2,y2)] (纯 numpy/栈, 不引 scipy)。"""
    m = mask.copy()
    hh, ww = m.shape
    out = []
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys, xs):
        if not m[y0, x0]:
            continue
        stack = [(y0, x0)]
        m[y0, x0] = False
        x1 = x2 = x0
        y1 = y2 = y0
        area = 0
        while stack:
            y, x = stack.pop()
            area += 1
            x1, x2 = min(x1, x), max(x2, x)
            y1, y2 = min(y1, y), max(y2, y)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < hh and 0 <= nx < ww and m[ny, nx]:
                    m[ny, nx] = False
                    stack.append((ny, nx))
        out.append((area, x1, y1, x2, y2))
    return out


def _add_distractors(xml: str, k: int) -> str:
    """在 <worldbody> 末尾插入 k 个干扰模块 geom (位置/尺寸/颜色运行时随机)。"""
    if k <= 0:
        return xml
    geos = "".join(
        '<geom name="distract_%d" type="box" size="0.010 0.008 0.004" pos="0.55 0.30 0.14" '
        'rgba="0.78 0.78 0.80 1" contype="0" conaffinity="0"/>\n' % i for i in range(k))
    if "</worldbody>" not in xml:
        raise SystemExit("场景 XML 没有 worldbody, 不能加干扰件")
    return xml.replace("</worldbody>", geos + "</worldbody>", 1)


def gen(n=240, seed=9001, clutter=4, out=None):
    import mujoco
    from PIL import Image

    DS = os.path.abspath(out or osp.join(ROOT, "zmax_data", "ar_mujoco", "ds_clutter"))
    random.seed(seed)
    np.random.seed(seed)
    for sub in ("images", "labels"):
        os.makedirs(osp.join(DS, sub), exist_ok=True)

    import ar_mujoco_scene as A
    xml = _add_distractors(A.build_xml(), clutter)
    xmlp = osp.join(DS, "scene_clutter.xml")
    open(xmlp, "w", encoding="utf-8").write(xml)
    model = mujoco.MjModel.from_xml_path(xmlp)
    data = mujoco.MjData(model)
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "gold_module")
    if gid < 0:
        raise SystemExit("场景里没有 gold_module")
    did = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "distract_%d" % i) for i in range(clutter)]
    did = [d for d in did if d >= 0]

    model.vis.global_.offwidth = W
    model.vis.global_.offheight = H
    ren = mujoco.Renderer(model, height=H, width=W)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)

    ctr = None
    for f in A.read_fences():
        if f.get("type") == "box" and "料盘" in str(f.get("name")) and f.get("p1"):
            ctr = np.array([(f["p1"][0] + f["p2"][0]) / 2, (f["p1"][1] + f["p2"][1]) / 2,
                            max(f["p1"][2], f["p2"][2])])
            break
    if ctr is None:
        ctr = np.array([0.52, 0.30, 0.14])

    g0 = model.geom_pos[gid].copy()
    stats = {"gen": 0, "kept": 0, "empty": 0, "ambiguous": 0, "clutter": int(clutter)}
    widths = []
    for i in range(n):
        # 目标模块: 料盘内 ±30mm (比干净集略收, 给干扰件留位置)
        gp = [g0[0] + random.uniform(-0.030, 0.030), g0[1] + random.uniform(-0.030, 0.030),
              g0[2] + random.uniform(-0.004, 0.008)]
        model.geom_pos[gid] = gp
        # 干扰件: 围绕料盘心的环带里 (半径 6~14cm), 不与目标重合
        for j, d in enumerate(did):
            ang = random.uniform(0, 2 * np.pi)
            r = random.uniform(0.06, 0.14)
            model.geom_pos[d] = [ctr[0] + r * np.cos(ang), ctr[1] + r * np.sin(ang),
                                 g0[2] + random.uniform(0.000, 0.010)]
            model.geom_size[d] = [random.uniform(0.006, 0.016), random.uniform(0.005, 0.011),
                                  random.uniform(0.002, 0.006)]
            model.geom_rgba[d] = DISTRACTOR_RGBA[j % len(DISTRACTOR_RGBA)]
        # 机位随机
        cam.lookat[:] = ctr + np.array([random.uniform(-0.03, 0.03), random.uniform(-0.03, 0.03), 0.02])
        cam.distance = random.uniform(0.55, 1.15)
        cam.azimuth = random.uniform(40.0, 140.0)
        cam.elevation = random.uniform(-88.0, -55.0)
        mujoco.mj_forward(model, data)
        ren.update_scene(data, camera=cam)
        img = ren.render().copy()

        stats["gen"] += 1
        comps = [c for c in _components(_gold_mask(img)) if c[0] >= 40]
        nm = "ar_%04d" % i
        box = None
        if comps:
            comps.sort(key=lambda c: -c[0])
            big, second = comps[0], (comps[1] if len(comps) > 1 else None)
            # 歧义判据: 第二连通域面积 > 主域 25% ⇒ 金色像素不止一处, 标注不可靠 ⇒ 丢弃
            if second and second[0] > 0.25 * big[0]:
                stats["ambiguous"] += 1
                continue
            box = [big[1], big[2], big[3], big[4]]
        Image.fromarray(img).save(osp.join(DS, "images", nm + ".jpg"), quality=90)
        lp = osp.join(DS, "labels", nm + ".txt")
        if box is None:
            open(lp, "w").write("")
            stats["empty"] += 1
            continue
        x1, y1, x2, y2 = box
        open(lp, "w").write("0 %.6f %.6f %.6f %.6f\n" % (
            (x1 + x2) / 2.0 / W, (y1 + y2) / 2.0 / H, (x2 - x1) / float(W), (y2 - y1) / float(H)))
        stats["kept"] += 1
        widths.append(x2 - x1)

    open(osp.join(DS, "data.yaml"), "w", encoding="utf-8").write(
        "path: %s\ntrain: images\nval: images\nnames:\n  0: gold_module\n" % DS)
    meta = {"stats": stats, "n": n, "seed": seed, "w": W, "h": H,
            "box_w_px": {"min": int(min(widths)) if widths else 0, "max": int(max(widths)) if widths else 0,
                         "mean": round(float(np.mean(widths)), 1) if widths else 0},
            "note": "标签=金色像素主连通域外接框; 干扰件用非金色系, 歧义图已丢弃并计数"}
    open(osp.join(DS, "meta.json"), "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False, indent=1))
    return meta, DS


def selftest() -> int:
    fails = []
    # ① 颜色可分辨: 干扰色必须过不了金色判据
    for c in DISTRACTOR_RGBA:
        rgb = [int(v * 255) for v in c[:3]]
        a = np.array([[rgb]], dtype=np.uint8)
        if _gold_mask(a)[0, 0]:
            fails.append("干扰色 %s 会被当成金色" % (rgb,))
    # ② 连通域
    m = np.zeros((20, 20), bool)
    m[2:5, 2:5] = True
    m[10:14, 12:16] = True
    comps = sorted(_components(m), key=lambda x: -x[0])
    if len(comps) != 2 or comps[0][0] != 16 or comps[1][0] != 9:
        fails.append("连通域实现不对: %s" % (comps,))
    # ③ 干扰件注入
    if '<geom name="distract_0"' not in _add_distractors("<worldbody></worldbody>", 2):
        fails.append("干扰件注入失败")
    print("✅ 自检通过" if not fails else "❌ " + "; ".join(fails))
    return 0 if not fails else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--clutter", type=int, default=4)
    ap.add_argument("--seed", type=int, default=9001)
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.gen:
        m, ds = gen(n=a.n, seed=a.seed, clutter=a.clutter, out=a.out or None)
        print("生成 → %s" % ds)
        print("  %s" % json.dumps(m["stats"], ensure_ascii=False))
        print("  框宽 px: %s" % m["box_w_px"])
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
