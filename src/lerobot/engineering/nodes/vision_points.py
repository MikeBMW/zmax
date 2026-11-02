# -*- coding: utf-8 -*-
"""📍 视觉 3D 观测点 · 契约读写 (状态空间 L2 感知节点 ↔ plan 节点 的唯一交界)

老倪 2026-10-28: 「应该正式用 L2 层的感知节点」——
  所以写这份契约的**主体是画布节点** `🎯 YOLO 目标检测`(ss_yolo, 实现 node_ss_yolo),
  不是 tools 里的脚本; tools/vision_points_pub.py 只是人工/回放入口, 复用本模块同一份写盘口径。

契约 (zmax_data/ss_live/vision_points.json):
  {t, ts_str, frame, units:"mm", verified: bool,
   source:{kind, cam, note, gaps:[...]},
   points:{ "<名>": {id, pos_mm:[x,y,z], conf, err_mm, ts, cam,
                     quat:[x,y,z,w], size_mm:[L,W,H], pose_src, pose_frame } }}

姿态 (quat/size_mm) 是**可选字段**, 2026-11-03 加:
  · 只给点的话下游只知道"在哪", 不知道"朝哪、多大"; 插拔的朝向对齐必须要姿态。
  · quat = 模块框系在 pose_frame(默认 base_link) 下的四元数, 顺序 x,y,z,w;
    尺寸 size_mm 是模块框 L/W/H (毫米), 来自 2D→3D 解算的自标定结果。
  · 拿不到就**不写这两个字段**(不写 [0,0,0,1] 冒充"正着放"), pos 照常可用。
  · 生产者的两种合法来源: ①模块被夹住 → TCP 四元数 × 解算出的相对旋转;
    ②解算器已拟合 → 直接用它的 rrel/size。都不读仿真真值。

铁律:
  · **verified 只有一种情况为真**: frame == "base_link" 且 3D 换算没有任何 gap (无深度/无外参/未标定都算 gap);
  · 坐标一律 mm; det3d 给的是米 ⇒ ×1000 (本模块统一换算);
  · 检不到就不写点、不写 0 冒充 (只更新 source/notes, points 留空)。
"""
from __future__ import annotations

import json
import math
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
        rec = {"id": p.get("id") or name,
               "pos_mm": [round(float(v), 3) for v in pos[:3]],
               "conf": (round(float(p["conf"]), 3) if p.get("conf") is not None else None),
               "err_mm": (round(float(p["err_mm"]), 3) if p.get("err_mm") is not None else None),
               "ts": t, "cam": p.get("cam") or (source or {}).get("cam")}
        q = p.get("quat")                                            # 姿态: 可选, 缺就不写
        if q is not None and len(q) == 4:
            qq = [float(v) for v in q]
            nq = math.sqrt(sum(v * v for v in qq))
            if nq > 1e-9:
                rec["quat"] = [round(v / nq, 6) for v in qq]
                rec["pose_frame"] = p.get("pose_frame") or frame
        if p.get("pose_src"):                                        # 只有尺寸时也留来源
            rec["pose_src"] = str(p["pose_src"])
        sz = p.get("size_mm")                                         # 尺寸: 可选
        if sz is not None and len(sz) == 3:
            rec["size_mm"] = [round(float(v), 2) for v in sz]
        doc["points"][name] = rec
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    return OUT, verified, len(doc["points"])


def publish_from_det(det3d, det2d=None, meta=None, cam="", kind="yolo_node", note="", pose=None):
    """L2 节点的标准用法: detect_3d_meta 的 (det3d 米, meta) + 同帧 2D conf → 契约。

    det3d: {"peg": [x,y,z](米), ...}  · det2d: {"peg": {"conf":0.87,...}}
    meta : {"frame","K_src","ext_src","depth_src","gaps"[],"notes"[]}
    pose : 可选姿态 {类名: {"quat":[x,y,z,w], "size_mm":[L,W,H], "src":"...", "frame":"base_link"}}
           不给就只写点, 契约里不出现 quat/size 字段 (向后兼容)。
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
        name = ("光模块·当前" if cls in ("peg", "module", "光模块") else str(cls))
        rec = {"pos_mm": pos_mm, "conf": d2.get("conf"), "err_mm": d2.get("err_mm"), "cam": cam}
        pz = (pose or {}).get(cls) or (pose or {}).get(name)
        if pz:
            rec["quat"] = pz.get("quat")
            rec["size_mm"] = pz.get("size_mm")
            rec["pose_src"] = pz.get("src") or pz.get("pose_src")
            rec["pose_frame"] = pz.get("frame") or frame
        pts[name] = rec
    return write(pts, frame, src, notes=meta.get("notes"), det2d=det2d)


def R_to_quat(R):
    """3×3 旋转矩阵 → 四元数 [x,y,z,w] (Shepperd 法, 数值稳定)。"""
    import numpy as np                                                        # noqa: PLC0415
    M = np.asarray(R, dtype=float).reshape(3, 3)
    tr = float(M[0, 0] + M[1, 1] + M[2, 2])
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x = 0.25 * s, (M[2, 1] - M[1, 2]) / s
        y, z = (M[0, 2] - M[2, 0]) / s, (M[1, 0] - M[0, 1]) / s
    elif M[0, 0] > M[1, 1] and M[0, 0] > M[2, 2]:
        s = math.sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2
        w, x = (M[2, 1] - M[1, 2]) / s, 0.25 * s
        y, z = (M[0, 1] + M[1, 0]) / s, (M[0, 2] + M[2, 0]) / s
    elif M[1, 1] > M[2, 2]:
        s = math.sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2
        w, x = (M[0, 2] - M[2, 0]) / s, (M[0, 1] + M[1, 0]) / s
        y, z = 0.25 * s, (M[1, 2] + M[2, 1]) / s
    else:
        s = math.sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2
        w, x = (M[1, 0] - M[0, 1]) / s, (M[0, 2] + M[2, 0]) / s
        y, z = (M[1, 2] + M[2, 1]) / s, 0.25 * s
    return [float(x), float(y), float(z), float(w)]


def pose_from_gripper(tcp_quat, rrel_deg, size_mm=None, frame="base_link"):
    """模块被夹住时的姿态: R_world = R_tcp · R_rel(rrel_deg, 度, Rz·Ry·Rx)。

    与 box3d_solver 完全同一套约定 (quat_to_R 同式 / _R_euler 同序), 不另立标准。
    rrel_deg 来自 2D→3D 解算的 fit() 返回, 是模块相对工具系的小转角。
    """
    import numpy as np                                                        # noqa: PLC0415
    x, y, z, w = [float(v) for v in tcp_quat]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    Rt = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                   [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                   [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    a, b, c = [math.radians(float(v)) for v in (rrel_deg or (0.0, 0.0, 0.0))]
    Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    out = {"quat": R_to_quat(Rt @ (Rz @ Ry @ Rx)), "frame": frame,
           "src": "gripper:TCP×R_rel"}
    if size_mm:
        out["size_mm"] = [float(v) for v in size_mm]
    return out


def read_pose(name):
    """下游取姿态: 返回 {quat, size_mm, pose_src, pose_frame, pos_mm, ts} 或 None。

    None 有两种情况, 必须区分: 契约没有这个点 (name 不存在) vs 有位置但没姿态 (quat 缺)。
    调用方用 read_pose(name) is None → 没点; 返回 dict 但无 "quat" → 有点无姿态。
    """
    doc = read() or {}
    p = (doc.get("points") or {}).get(name)
    if not p:
        return None
    out = {"pos_mm": p.get("pos_mm"), "ts": p.get("ts"), "cam": p.get("cam")}
    if p.get("quat"):
        out.update({"quat": p["quat"], "size_mm": p.get("size_mm"),
                    "pose_src": p.get("pose_src"), "pose_frame": p.get("pose_frame")})
    return out


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
