#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📍 L2 感知 → 3D 观测点发布 (**人工/回放入口**; 正式写者是画布 L2 节点)

老倪 2026-10-28: 「应该正式用 L2 层的感知节点」⇒ 正式写者 = 画布节点
  `🎯 YOLO 目标检测` (ss_yolo → library.node_ss_yolo), 每跑一帧就在发布观测点。
本脚本只做两件事: ①别的感知节点/标定后手工给点 ②回放验证; 写盘口径与节点同一份实现
(`lerobot.engineering.nodes.vision_points`), 不另写一套。

    zmax_data/ss_live/vision_points.json
    {
      "t": <epoch>, "ts_str": "…", "frame": "base_link", "units": "mm", "verified": bool,
      "source": {"kind": "manual|depth3d", "cam": "...", "gaps": [...], "notes": [...]},
      "points": {"光模块·当前": {"id": "...", "pos_mm": [x,y,z], "conf": 0.0~1.0,
                                 "err_mm": <1σ 估计>, "ts": <epoch>, "cam": "…"}}
    }

两种写入口:
  ① `--pos X Y Z --conf C [--err E] [--name 光模块·当前]`   —— 别的感知节点/标定后直接给点
  ② `--from-det zmax_data/ss_bypass/yolo_detections.json`  —— 真检测框 → 3D
     需要: K(config/calib) + T_base_cam + plane_z。**缺任何一项就只写 gap、不写点**。

铁律: frame 必须 base_link (真机执行链的唯一基座系); 单位 mm; ts 必填 —— plan 侧按 ts 判时效。
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("ZMAX_VISION_POINTS") or os.path.join(REPO, "zmax_data", "ss_live", "vision_points.json")
sys.path.insert(0, os.path.join(REPO, "src"))
from lerobot.engineering.nodes import vision_points as VP        # noqa: E402  同一份写盘口径

CALIB = os.path.join(REPO, "config", "calib", "zmax_calib.json")
DET = os.path.join(REPO, "zmax_data", "ss_bypass", "yolo_detections.json")


def _write(doc):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    return OUT


def _doc(kind, cam, note=""):
    now = time.time()
    return {"t": now, "ts_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "frame": "base_link", "units": "mm",
            "source": {"kind": kind, "cam": cam, "note": note}, "points": {}}


def publish_point(name, pos, conf, err=None, cam="manual", kind="manual", note=""):
    out, verified, n = VP.write({name: {"pos_mm": pos, "conf": conf, "err_mm": err, "cam": cam}},
                                "base_link", {"kind": kind, "cam": cam, "gaps": [], "notes": [note]})
    return out


def from_det(path=DET, name="光模块·当前"):
    """真检测框 → 3D(base_link)。缺标定/TCP 真值就报缺退出, 不造点。"""
    if not os.path.isfile(path):
        sys.exit("❌ 检测文件不存在: %s (先让 L2 检测节点跑起来)" % path)
    d = json.load(open(path, encoding="utf-8"))
    dets = d.get("detections") or []
    peg = d.get("peg_optical_module")
    if not dets and not peg:
        sys.exit("❌ 检测文件里 0 个目标 (frame_age_s=%s) —— 相机没帧或没识别到光模块, 不写假点"
                 % d.get("frame_age_s"))
    calib = json.load(open(CALIB, encoding="utf-8")) if os.path.isfile(CALIB) else {}
    missing = []
    if not (calib.get("T_base_cam") or {}).get("value"):
        missing.append("T_base_cam(手眼)")
    if not (calib.get("plane_z") or {}).get("value"):
        missing.append("plane_z(台面高度)")
    if missing:
        sys.exit("❌ 3D 换算缺标定: %s —— 现场标定后再跑 (K 已就位: %s)"
                 % (" / ".join(missing), "有" if (calib.get("camera") or {}).get("K") else "无"))
    # 到这里说明标定齐了: 用 K + T_base_cam + plane_z 做「像素射线 ∩ 台面平面」反投影
    cam = calib.get("camera") or {}
    K = cam.get("K")
    if not K or len(K) != 9:
        sys.exit("❌ 相机内参 K 不完整 —— 不写假点")
    T = (calib.get("T_base_cam") or {}).get("value")
    pz = float((calib.get("plane_z") or {}).get("value"))
    box = (peg or (dets[0] if dets else {})).get("box") or []
    if len(box) < 4:
        sys.exit("❌ 检测框不完整 (%s) —— 不写假点" % (box,))
    px, py = (float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0
    pos = ray_plane_3d(px, py, K, T, pz)
    return publish_point(name, pos, float((peg or {}).get("conf") or d.get("conf_th") or 0.0),
                         (peg or {}).get("err_mm"), cam=d.get("source_label") or "realsense",
                         kind="depth3d",
                         note="框中心 + K/T_base_cam/plane_z 反投影 (frame_age_s=%s)" % d.get("frame_age_s"))


def _K_inv_ray(px, py, K):
    """像素 → 相机系射线方向 (未归一, z=1 平面)。K 为 3×3 行优先列表。"""
    fx, cx, fy, cy = float(K[0]), float(K[2]), float(K[4]), float(K[5])
    return [(px - cx) / fx, (py - cy) / fy, 1.0]


def ray_plane_3d(px, py, K, T_base_cam, plane_z_mm):
    """像素射线 ∩ z=plane_z 平面 → base_link mm。T_base_cam 支持 4×4 列表或 {'R':9,'t':3}。"""
    import numpy as np                                                       # noqa: PLC0415
    d_cam = np.array(_K_inv_ray(px, py, K), dtype=float)
    if isinstance(T_base_cam, (list, tuple)) and len(T_base_cam) == 16:
        M = np.array(T_base_cam, dtype=float).reshape(4, 4)
        R, t = M[:3, :3], M[:3, 3]
    elif isinstance(T_base_cam, dict) and "R" in T_base_cam and "t" in T_base_cam:
        R = np.array(T_base_cam["R"], dtype=float).reshape(3, 3)
        t = np.array(T_base_cam["t"], dtype=float).reshape(3) * 1000.0        # 米→mm
    else:
        sys.exit("❌ T_base_cam 格式不认识 (%s) —— 不写假点" % type(T_base_cam).__name__)
    o = t.copy()                                                             # 相机光心 (base, mm)
    d = R.dot(d_cam)                                                         # 方向 (base)
    if abs(d[2]) < 1e-9:
        sys.exit("❌ 射线与台面平行, 无法求交 —— 不写假点")
    s = (float(plane_z_mm) - o[2]) / d[2]
    if s <= 0:
        sys.exit("❌ 台面在相机背后 (s=%.3f) —— 标定/像素有误, 不写假点" % s)
    p = o + s * d
    return [float(p[0]), float(p[1]), float(plane_z_mm)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pos", nargs=3, type=float, metavar=("X", "Y", "Z"), help="base_link mm")
    ap.add_argument("--conf", type=float, default=1.0)
    ap.add_argument("--err", type=float, default=None, help="1σ 估计 mm")
    ap.add_argument("--name", default="光模块·当前")
    ap.add_argument("--cam", default="manual")
    ap.add_argument("--note", default="")
    ap.add_argument("--from-det", nargs="?", const=DET, default=None,
                    help="从 YOLO 检测文件换算 3D (缺标定会拒写)")
    a = ap.parse_args()
    if a.from_det:
        print("✅ 写入:", from_det(a.from_det, a.name))
        return
    if not a.pos:
        ap.error("要么给 --pos X Y Z, 要么 --from-det")
    p = publish_point(a.name, a.pos, a.conf, a.err, cam=a.cam, note=a.note)
    print("✅ 写入:", p)


if __name__ == "__main__":
    main()
