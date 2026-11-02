#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vision_pose_pub.py — 给视觉契约补姿态 (quat/size_mm), 不碰位置、不编数。

背景 (2026-11-03 老倪): 「YOLO 感知输出只是一个点」——对, 点说不了"朝哪、多大",
插拔的朝向对齐拿不到姿态。Box3DSolver 早就能解出 rrel_deg/size_mm, 但没进契约。

本工具只做一件事: 读现有 zmax_data/ss_live/vision_points.json, 把解算器已拟合的
相对旋转/尺寸, 用当拍 TCP 四元数合成模块在世界系的姿态, 写回同一点。

三种情况都如实处理, 绝不补零冒充:
  · 没有解算结果            → exit 2, 契约不动
  · 有解算但没有 TCP 姿态    → 只写 size_mm, 不写 quat (点位照旧)
  · 有解算 + 有 TCP 姿态     → 写 quat + size_mm + pose_src

用法:
  python tools/vision_pose_pub.py --state zmax_data/box3d_fit.json
  python tools/vision_pose_pub.py --state models/box3d_state.json --tcp-quat 0,0,0,1 --dry
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO = os.path.expanduser("~/zmax")
sys.path.insert(0, os.path.join(_REPO, "src"))

from lerobot.engineering.nodes import vision_points as VP          # noqa: E402


def _load_fit(path):
    """从解算结果里取 rrel_deg / size_mm; 兼容 fit() 原始返回与外层包了一层 checks 的存盘。"""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    if isinstance(d.get("checks"), dict):        # 自检存盘把各方案装在 checks 下
        d = d["checks"]
    for key in ("fit_joint", "fit", "solution"):
        if isinstance(d.get(key), dict) and d[key].get("ok", True):
            d = d[key]
            break
    rrel = d.get("rrel_deg")
    size = d.get("size_mm")
    return {"rrel_deg": rrel, "size_mm": size,
            "rms_px": d.get("rms_px"), "holdout_rms_px": d.get("holdout_rms_px"),
            "degenerate": d.get("degenerate")}


def _tcp_quat(arg):
    """--tcp-quat 优先; 否则读 tcp_out/latest.json 的 quat/rotation; 都没有就 None。"""
    if arg:
        v = [float(x) for x in arg.replace(";", ",").split(",")]
        return v if len(v) == 4 else None
    for p in (os.path.join(_REPO, "zmax_data", "tcp_out", "latest.json"),
              os.environ.get("ZMAX_TCP_LATEST") or ""):
        if not p or not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:                                              # noqa: BLE001
            continue
        for k in ("quat", "quaternion", "rot_quat"):
            if isinstance(d.get(k), (list, tuple)) and len(d[k]) == 4:
                return [float(x) for x in d[k]]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=os.path.join(_REPO, "models", "box3d_state.json"))
    ap.add_argument("--class", dest="cls", default="光模块·当前")
    ap.add_argument("--tcp-quat", default=None, help="TCP 四元数 x,y,z,w")
    ap.add_argument("--frame", default="base_link")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    doc = VP.read()
    if not doc or not (doc.get("points") or {}).get(a.cls):
        print("✗ 契约里没有这个点: %s (先让 YOLO 节点写一帧)" % a.cls)
        return 2
    if not os.path.exists(a.state):
        print("✗ 没有解算结果: %s → 不写姿态 (不能拿默认值冒充朝向)" % a.state)
        return 2

    fit = _load_fit(a.state)
    if not fit["rrel_deg"] or not fit["size_mm"]:
        print("✗ 解算结果缺 rrel_deg/size_mm → 不写")
        return 2
    if fit.get("degenerate"):
        print("✗ 解算被判退化 (rms %.2f px) → 不写姿态" % float(fit.get("rms_px") or 0))
        return 2

    q = _tcp_quat(a.tcp_quat)
    pt = doc["points"][a.cls]
    if q:
        pose = VP.pose_from_gripper(q, fit["rrel_deg"], size_mm=fit["size_mm"], frame=a.frame)
        pt.update({"quat": pose["quat"], "size_mm": pose["size_mm"],
                   "pose_src": pose["src"], "pose_frame": a.frame})
        print("✓ 姿态: quat=%s size_mm=%s (TCP %s × R_rel %s)"
              % ([round(v, 4) for v in pose["quat"]], pose["size_mm"], q, fit["rrel_deg"]))
    else:
        pt.update({"size_mm": [float(v) for v in fit["size_mm"]],
                   "pose_src": "size_only:解算自标定", "pose_frame": a.frame})
        print("⚠ 没有 TCP 姿态 → 只写尺寸 %s, 不写 quat" % ([round(float(v), 2) for v in fit["size_mm"]]))

    if a.dry:
        print("[dry] 不落盘; 会写成: %s" % json.dumps(
            {k: pt.get(k) for k in ("pos_mm", "quat", "size_mm", "pose_src", "pose_frame")},
            ensure_ascii=False))
        return 0

    pts = {a.cls: pt}
    src = dict(doc.get("source") or {})
    src["pose_added_by"] = os.path.basename(__file__)
    path, verified, n = VP.write(pts, doc.get("frame"), src,
                                 notes=(src.get("notes") or []) + ["姿态由 %s 补写" % os.path.basename(__file__)],
                                 det2d=doc.get("det2d"))
    print("✓ 已写 %s · 点 %d · verified=%s" % (path, n, verified))
    return 0


if __name__ == "__main__":
    sys.exit(main())
