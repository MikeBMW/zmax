# -*- coding: utf-8 -*-
"""📍 视觉 3D 观测点 · 契约读写 (状态空间 L2 感知节点 ↔ plan 节点 的唯一交界)

老倪 2026-10-28: 「应该正式用 L2 层的感知节点」——
  所以写这份契约的**主体是画布节点** `🎯 YOLO 目标检测`(ss_yolo, 实现 node_ss_yolo),
  不是 tools 里的脚本; tools/vision_points_pub.py 只是人工/回放入口, 复用本模块同一份写盘口径。

契约 (zmax_data/ss_live/vision_points.json):
  {t, ts_str, frame, units:"mm", verified: bool,
   source:{kind, cam, note, gaps:[...]},
   points:{ "<名>": {id, pos_mm:[x,y,z], conf, err_mm, ts, cam} }}

铁律:
  · **verified 只有一种情况为真**: frame == "base_link" 且 3D 换算没有任何 gap (无深度/无外参/未标定都算 gap);
  · 坐标一律 mm; det3d 给的是米 ⇒ ×1000 (本模块统一换算);
  · 检不到就不写点、不写 0 冒充 (只更新 source/notes, points 留空)。
"""
from __future__ import annotations

import json
import os
import time

_REPO = os.path.expanduser("~/zmax")
OUT = os.environ.get("ZMAX_VISION_POINTS") or os.path.join(_REPO, "zmax_data", "ss_live", "vision_points.json")

BASE_FRAME = "base_link"


def write(points, frame, source, notes=None, det2d=None):
    """写契约文件。points: {名: {pos_mm, conf, err_mm, cam}}。返回 (path, verified, 点数)。"""
    gaps = list((source or {}).get("gaps") or [])
    verified = (frame == BASE_FRAME) and not gaps
    now = time.time()
    doc = {"t": now, "ts_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
           "frame": frame, "units": "mm", "verified": bool(verified),
           "source": dict(source or {}, gaps=gaps, notes=list(notes or [])),
           "points": {}}
    if det2d:
        # 2D 检出随契约一起留证 (3D 缺标定时也照样能看到"这一帧检到了什么/多信")
        doc["det2d"] = {k: {"box": [round(float(v), 1) for v in (d.get("box") or [])],
                            "conf": round(float(d.get("conf") or 0), 3)} for k, d in det2d.items()}
    for name, p in (points or {}).items():
        pos = p.get("pos_mm") or []
        if len(pos) < 3:
            continue
        t = float(p.get("ts") or now)
        doc["points"][name] = {"id": p.get("id") or name,
                              "pos_mm": [round(float(v), 3) for v in pos[:3]],
                              "conf": (round(float(p["conf"]), 3) if p.get("conf") is not None else None),
                              "err_mm": (round(float(p["err_mm"]), 3) if p.get("err_mm") is not None else None),
                              "ts": t, "cam": p.get("cam") or (source or {}).get("cam")}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    return OUT, verified, len(doc["points"])


def publish_from_det(det3d, det2d=None, meta=None, cam="", kind="yolo_node", note=""):
    """L2 节点的标准用法: detect_3d_meta 的 (det3d 米, meta) + 同帧 2D conf → 契约。

    det3d: {"peg": [x,y,z](米), ...}  · det2d: {"peg": {"conf":0.87,...}}
    meta : {"frame","K_src","ext_src","depth_src","gaps"[],"notes"[]}
    """
    meta = meta or {}
    det2d = det2d or {}
    frame = meta.get("frame") or "unknown"
    src = {"kind": kind, "cam": cam or meta.get("cam") or "",
           "K_src": meta.get("K_src"), "ext_src": meta.get("ext_src"),
           "depth_src": meta.get("depth_src"), "gaps": list(meta.get("gaps") or [])}
    for _k in ("video", "frame_i", "video_fps", "img", "frame_age_s", "scan_frames"):        # 取证元数据透传
        if meta.get(_k) is not None:
            src[_k] = meta[_k]
    pts = {}
    for cls, v in (det3d or {}).items():
        try:
            pos_mm = [float(v[0]) * 1000.0, float(v[1]) * 1000.0, float(v[2]) * 1000.0]
        except Exception:                                                     # noqa: BLE001
            continue
        d2 = det2d.get(cls) or {}
        pts[("光模块·当前" if cls in ("peg", "module", "光模块") else str(cls))] = {
            "pos_mm": pos_mm, "conf": d2.get("conf"), "err_mm": d2.get("err_mm"), "cam": cam}
    return write(pts, frame, src, notes=meta.get("notes"), det2d=det2d)


def read():
    try:
        with open(OUT, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                         # noqa: BLE001
        return None


def ray_plane_3d(px, py, K, T_base_cam, plane_z_mm):
    """像素射线 ∩ z=plane_z 平面 → base_link mm。T 支持 4×4 列表或 {'R':9,'t':3}(米)。"""
    import numpy as np                                                        # noqa: PLC0415
    fx, cx, fy, cy = float(K[0]), float(K[2]), float(K[4]), float(K[5])
    d_cam = np.array([(px - cx) / fx, (py - cy) / fy, 1.0], dtype=float)
    if isinstance(T_base_cam, (list, tuple)) and len(T_base_cam) == 16:
        M = np.array(T_base_cam, dtype=float).reshape(4, 4)
        R, t = M[:3, :3], M[:3, 3]
    elif isinstance(T_base_cam, dict) and "R" in T_base_cam and "t" in T_base_cam:
        R = np.array(T_base_cam["R"], dtype=float).reshape(3, 3)
        t = np.array(T_base_cam["t"], dtype=float).reshape(3) * 1000.0
    else:
        raise ValueError("T_base_cam 格式不认识: %s" % type(T_base_cam).__name__)
    d = R.dot(d_cam)
    if abs(d[2]) < 1e-9:
        raise ValueError("射线与台面平行")
    s = (float(plane_z_mm) - t[2]) / d[2]
    if s <= 0:
        raise ValueError("台面在相机背后 (s=%.3f)" % s)
    p = t + s * d
    return [float(p[0]), float(p[1]), float(plane_z_mm)]
