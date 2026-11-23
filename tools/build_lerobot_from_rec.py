#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_lerobot_from_rec.py —— 把 record_manual 的「状态+同步图像」转成 LeRobot v3 数据集

输入: zmax_data/rokae_sdk/rec/rec_manual_<ts>.jsonl  +  frames_<ts>/{arm,local}_*.jpg
输出: zmax_data/datasets/lerobot/<name>/   (data/*.parquet + images/ + meta/*)

字段口径 (与仓里既有真机集 zmax_live_215ep1 对齐):
  observation.state  float32[13] = j1..j6(rad) + x,y,z(mm) + qx,qy,qz,qw(由 rpy 转)
  action             float32[4]  = 下一状态 x,y,z(mm) + grip
  observation.images.arm / observation.images.local   image
  ⚠️ grip 未在录制里采 ⇒ 恒 0, 在 info.json 的 notes 与日志里写明, 不当真值用
  ⚠️ 图像按 t_state 之前最近一帧绑定; 滞后超过 --max-age-ms 的行丢弃(默认 120ms), 并记账

用法:
  /home/ubuntu/zmax/venvs/lerobot-venv/bin/python tools/build_lerobot_from_rec.py \
      --jsonl zmax_data/rokae_sdk/rec/rec_manual_20261122_233509.jsonl \
      --name live_sync_15s --task "插入光模块"
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"


def rpy_to_quat(r: float, p: float, y: float):
    """URDF/RPY (ZYX 顺序, 与 xCoreSDK cartPosture 一致) → 四元数 (x,y,z,w)。"""
    cr, sr = math.cos(r / 2), math.sin(r / 2)
    cp, sp = math.cos(p / 2), math.sin(p / 2)
    cy, sy = math.cos(y / 2), math.sin(y / 2)
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y_ = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return np.array([x, y_, z, w], dtype=np.float32)


def load_rows(jsonl: str):
    rows = []
    for line in open(jsonl, encoding="utf-8"):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def mm(p):
    p = list(p or [0, 0, 0])
    if max(abs(v) for v in p) <= 20.0:      # cartPosture 给 m
        p = [v * 1000.0 for v in p]
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--frames-dir", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--root", default=os.path.join(ROOT, "zmax_data/datasets/lerobot"))
    ap.add_argument("--task", default="插入光模块")
    ap.add_argument("--max-age-ms", type=float, default=120.0)
    ap.add_argument("--min-rows", type=int, default=10)
    ap.add_argument("--fps", type=int, default=0, help="0=按时间戳现算")
    ap.add_argument("--single-image", default="", help="把某一路写成 observation.image (SmolVLA 口径), 如 arm")
    ap.add_argument("--image-size", type=int, default=480, help="--single-image 时的方形边长")
    a = ap.parse_args()

    from lerobot.datasets.lerobot_dataset import LeRobotDataset  # 必须在 lerobot venv 里跑

    jsonl = os.path.abspath(a.jsonl)
    if not os.path.isfile(jsonl):
        print("❌ 没有 jsonl:", jsonl)
        return 2
    rows = load_rows(jsonl)
    if len(rows) < a.min_rows:
        print("❌ 行数太少 %d < %d" % (len(rows), a.min_rows))
        return 2

    ts_tag = os.path.basename(jsonl).replace("rec_manual_", "").replace(".jsonl", "")
    fdir = a.frames_dir or os.path.join(os.path.dirname(jsonl), "frames_%s" % ts_tag)
    has_img = any(r.get("img") for r in rows)
    cams = sorted({c for r in rows for c in (r.get("img") or {})})
    if has_img and not cams:
        has_img = False
    print("录制 %s · 行 %d · 帧目录 %s · 相机 %s" % (os.path.basename(jsonl), len(rows), fdir, cams or "无"))

    # fps: 用实际时间戳算
    ts = [float(r["t"]) for r in rows]
    dt = np.diff(ts)
    fps = a.fps or max(1, int(round(1.0 / float(np.median(dt)))))
    print("fps 现算 %d (dt 中位 %.4fs)" % (fps, float(np.median(dt))))

    # 每路相机各自量分辨率 (实测 arm 与 local 不同: 848×480 vs 640×480)
    shapes = {}
    if has_img:
        from PIL import Image
        for c in cams:
            for r in rows:
                f = (r.get("img") or {}).get(c)
                if f and os.path.isfile(os.path.join(fdir, f)):
                    with Image.open(os.path.join(fdir, f)) as im:
                        shapes[c] = (im.size[1], im.size[0], 3)   # H,W,C
                    break
        print("分辨率:", {k: v for k, v in shapes.items()})
    if not shapes:
        print("⚠️ 无图像 ⇒ 只建状态/动作数据集 (SmolVLA 需要图像, 这个集只能给 L4/位姿头用)")

    features = {
        "observation.state": {"dtype": "float32", "shape": (13,),
                              "names": ["j1", "j2", "j3", "j4", "j5", "j6",
                                        "x", "y", "z", "qx", "qy", "qz", "qw"]},
        "action": {"dtype": "float32", "shape": (4,), "names": ["x", "y", "z", "grip"]},
    }
    single = a.single_image if a.single_image in cams else ""
    if single:
        # SmolVLA 老数据集用的是 observation.image (单路、方形) ⇒ 直接按这个口径写, 免得训练时再改名
        features["observation.image"] = {"dtype": "image",
                                         "shape": (a.image_size, a.image_size, 3),
                                         "names": ["height", "width", "channels"]}
    for c in ([] if single else cams):
        if c not in shapes:
            continue
        features["observation.images.%s" % c] = {"dtype": "image", "shape": shapes[c],
                                                "names": ["height", "width", "channels"]}

    out_root = os.path.join(a.root, a.name or ("rec_" + ts_tag))
    if os.path.isdir(out_root) and os.listdir(out_root):
        print("❌ 目标已存在且非空:", out_root)
        return 2
    ds = LeRobotDataset.create(repo_id=os.path.basename(out_root), fps=fps, features=features,
                              root=out_root, robot_type="zmax_rokae_xmate",
                              use_videos=False, image_writer_threads=4)

    from PIL import Image
    kept = dropped_age = dropped_noimg = 0
    ages = []
    n = len(rows)
    for i, r in enumerate(rows):
        if not r.get("p"):
            continue
        p = mm(r["p"])
        rpy = r.get("rpy") or [0, 0, 0]
        st = np.array(list(r["j"])[:6] + list(p) + list(rpy_to_quat(*rpy)), dtype=np.float32)
        # action = 下一状态位姿(裁剪到最后一行自指) + grip(未采, 恒 0)
        nxt = rows[min(i + 1, n - 1)]
        np_ = mm(nxt.get("p") or p)
        act = np.array([np_[0], np_[1], np_[2], 0.0], dtype=np.float32)

        frame = {"observation.state": st, "action": act, "task": a.task}
        ok_img = True
        if single:
            f0 = (r.get("img") or {}).get(single)
            age0 = (r.get("img_age_ms") or {}).get(single)
            if not f0 or not os.path.isfile(os.path.join(fdir, f0)) or \
                    (age0 is not None and age0 > a.max_age_ms):
                dropped_noimg += 1
                continue
            with Image.open(os.path.join(fdir, f0)) as im:
                frame["observation.image"] = np.asarray(
                    im.convert("RGB").resize((a.image_size, a.image_size), Image.BILINEAR))
            if age0 is not None:
                ages.append(age0)
            ds.add_frame(frame)
            kept += 1
            continue
        for c in cams:
            f = (r.get("img") or {}).get(c)
            age = (r.get("img_age_ms") or {}).get(c)
            if not f or not os.path.isfile(os.path.join(fdir, f)):
                ok_img = False
                dropped_noimg += 1
                break
            if age is not None and age > a.max_age_ms:
                ok_img = False
                dropped_age += 1
                break
            with Image.open(os.path.join(fdir, f)) as im:
                frame["observation.images.%s" % c] = np.asarray(im.convert("RGB"))
            if age is not None:
                ages.append(age)
        if cams and not ok_img:
            continue
        ds.add_frame(frame)
        kept += 1
    if kept == 0:
        print("❌ 没有可用帧")
        return 2
    ds.save_episode()
    ds.finalize()
    ages_s = sorted(ages)
    print(json.dumps({
        "ok": True, "dataset": out_root, "episode": 1, "frames": kept,
        "dropped_noimg": dropped_noimg, "dropped_age": dropped_age,
        "fps": fps, "cams": cams, "task": a.task,
        "img_age_ms": {"median": int(ages_s[len(ages_s) // 2]) if ages_s else None,
                       "p95": int(ages_s[int(0.95 * (len(ages_s) - 1))]) if ages_s else None,
                       "max": int(ages_s[-1]) if ages_s else None},
        "note": "grip 未采恒 0, 不作为夹爪真值",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
