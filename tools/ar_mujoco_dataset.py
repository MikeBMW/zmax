#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📦 ar_mujoco_dataset.py — 用 MuJoCo 渲染自动生成 YOLO 训练集（免人工标注）

老倪 2026-10-28: 「要用AR场景建模, 用mujoco仿真引擎渲染, yolo感知」

## 为什么这么做
在役 models/yolo_peg_live.pt 是**腕相机 D405 视角**训的, 换到 AR 工位的俯视机位
一个框都出不来(实测 0 框)。而仿真渲染天生带真值: 光模块的颜色/位置都是我们设的
⇒ 用**颜色分割**从渲染图里直接抠出精确标注, 不需要人标。

## 真值从哪来(不许自己编)
  · 场景几何 ← fence_store 的箱体(料盘/槽位) + ar_aoi_live 点位
  · 光模块 3D 位姿 ← 我们写进 XML 的 geom_pos(基地系, 米), 有绝对真值
  · 2D 标注 ← 渲染图里模块的本色像素做连通域 → 外接框
    ⚠️ 颜色分割出来的框就是**像素级真值**, 不是"猜的框"; 空图(没有模块像素)直接丢弃,
       绝不给"0 框"图配"有目标"的标签

## 随机化(让模型别只记住一个机位)
  机位 azimuth / elevation / distance · 模块在料盘内的位置 · 环境光强度

用法:
    python tools/ar_mujoco_dataset.py --gen --n 240        # 生成训练集
    python tools/ar_mujoco_dataset.py --selftest
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
DS = osp.join(ROOT, "zmax_data", "ar_mujoco", "ds")
sys.path.insert(0, osp.join(ROOT, "tools"))

W, H = 960, 720
GOLD_RGBA = "0.94 0.76 0.22 1"


def _gold_mask(img):
    """从渲染图里抠出金色模块像素 (sRGB 下 R 高、B 低)。"""
    a = img.astype(int)
    return ((a[:, :, 0] > 120) & (a[:, :, 1] > 85) &
            (a[:, :, 0] - a[:, :, 2] > 40) & (a[:, :, 1] - a[:, :, 2] > 20))


def _largest_box(mask, min_px=40):
    """取最大连通域的外接框。返回 [x1,y1,x2,y2] 或 None。"""
    ys, xs = np.where(mask)
    if len(ys) < min_px:
        return None
    # 简易: 用中位数±3σ 剔飞点 (金色只该出现在一个位置)
    mx, my = np.median(xs), np.median(ys)
    keep = (np.abs(xs - mx) < 90) & (np.abs(ys - my) < 90)
    if keep.sum() < min_px:
        return None
    xs, ys = xs[keep], ys[keep]
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def gen(n=240, seed=7):
    """生成 n 张渲染图 + YOLO 标签。"""
    import mujoco
    from PIL import Image

    random.seed(seed)
    np.random.seed(seed)
    for sub in ("images", "labels"):
        os.makedirs(osp.join(DS, sub), exist_ok=True)

    # 场景基座: 先建一次拿到几何, 之后每张只改机位/模块位姿/光照
    import ar_mujoco_scene as A
    xml = A.build_xml()
    xmlp = osp.join(DS, "scene_base.xml")
    open(xmlp, "w", encoding="utf-8").write(xml)
    model = mujoco.MjModel.from_xml_path(xmlp)
    data = mujoco.MjData(model)
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "gold_module")
    if gid < 0:
        raise SystemExit("场景里没有 gold_module")

    model.vis.global_.offwidth = W
    model.vis.global_.offheight = H
    ren = mujoco.Renderer(model, height=H, width=W)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)

    # 料盘中心 (机位围绕它)
    ctr = None
    for f in A.read_fences():
        if f.get("type") == "box" and "料盘" in str(f.get("name")) and f.get("p1"):
            ctr = np.array([(f["p1"][0] + f["p2"][0]) / 2, (f["p1"][1] + f["p2"][1]) / 2,
                            max(f["p1"][2], f["p2"][2])])
            break
    if ctr is None:
        ctr = np.array([0.52, 0.30, 0.14])

    g0 = model.geom_pos[gid].copy()
    stats = {"gen": 0, "kept": 0, "empty": 0}
    recs = []
    for i in range(n):
        # ① 模块在料盘内随机偏 ±35mm (跟着料盘平面走)
        model.geom_pos[gid] = [g0[0] + random.uniform(-0.035, 0.035),
                               g0[1] + random.uniform(-0.035, 0.035),
                               g0[2] + random.uniform(-0.004, 0.010)]
        # ② 机位随机 (围绕料盘)
        cam.lookat[:] = ctr + np.array([random.uniform(-0.05, 0.05),
                                        random.uniform(-0.05, 0.05), 0.02])
        cam.distance = random.uniform(0.55, 1.15)
        cam.azimuth = random.uniform(40.0, 140.0)
        cam.elevation = random.uniform(-88.0, -55.0)
        mujoco.mj_forward(model, data)
        ren.update_scene(data, camera=cam)
        img = ren.render().copy()

        stats["gen"] += 1
        box = _largest_box(_gold_mask(img))
        nm = "ar_%04d" % i
        Image.fromarray(img).save(osp.join(DS, "images", nm + ".jpg"), quality=90)
        lp = osp.join(DS, "labels", nm + ".txt")
        if box is None:
            # 空图: 标签文件留空(合法的"无目标"样本), 但**记数**, 不假装成功
            open(lp, "w").write("")
            stats["empty"] += 1
            recs.append({"name": nm, "box": None})
            continue
        x1, y1, x2, y2 = box
        # YOLO 归一化: cx cy w h
        cx = (x1 + x2) / 2.0 / W
        cy = (y1 + y2) / 2.0 / H
        bw = (x2 - x1) / float(W)
        bh = (y2 - y1) / float(H)
        open(lp, "w").write("0 %.6f %.6f %.6f %.6f\n" % (cx, cy, bw, bh))
        stats["kept"] += 1
        recs.append({"name": nm, "box": [x1, y1, x2, y2],
                     "wh": [x2 - x1, y2 - y1],
                     "cam": [round(cam.azimuth, 1), round(cam.elevation, 1),
                             round(cam.distance, 3)]})

    # 数据集描述
    open(osp.join(DS, "data.yaml"), "w", encoding="utf-8").write(
        "path: %s\ntrain: images\nval: images\nnames:\n  0: gold_module\n" % DS)
    sizes = [r["wh"][0] for r in recs if r.get("wh")]
    meta = {"stats": stats, "n": n, "seed": seed, "w": W, "h": H,
            "box_w_px": {"min": (min(sizes) if sizes else 0),
                         "max": (max(sizes) if sizes else 0),
                         "mean": (round(float(np.mean(sizes)), 1) if sizes else 0)},
            "note": "标签=渲染图里模块本色像素的连通域外接框, 像素级真值, 非人工/非模型预测"}
    open(osp.join(DS, "meta.json"), "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    m = gen(n=24, seed=11)
    st = m["stats"]
    chk("生成张数", st["gen"] == 24, "%d" % st["gen"])
    chk("有标注的图 > 60%", st["kept"] > 24 * 0.6,
        "kept=%d empty=%d" % (st["kept"], st["empty"]))
    chk("标签文件数 == 图数",
        len(os.listdir(osp.join(DS, "labels"))) == len(os.listdir(osp.join(DS, "images"))))
    chk("框宽合理 (>8px)", m["box_w_px"]["min"] > 8, "min=%s mean=%s" % (m["box_w_px"]["min"], m["box_w_px"]["mean"]))
    # 抽一个标签反算, 必须落在图内且尺寸>0
    lp = osp.join(DS, "labels", sorted(os.listdir(osp.join(DS, "labels")))[0])
    txt = open(lp).read().strip()
    if txt:
        _, cx, cy, bw, bh = txt.split()
        chk("YOLO 标签合法", 0 < float(bw) <= 1 and 0 < float(bh) <= 1,
            "cx=%s cy=%s w=%s h=%s" % (cx, cy, bw, bh))
    print()
    if fails:
        print("❌ %d 项失败" % len(fails))
        return 1
    print("✅ 数据集自检通过")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.gen:
        m = gen(n=a.n, seed=a.seed)
        print("生成 → %s" % DS)
        print("  %s" % m["stats"])
        print("  框宽 px: %s" % m["box_w_px"])
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
