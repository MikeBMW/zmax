#!/usr/bin/env python3
"""光模块 3D 框: 臂相机画面 → 2D 检测框 → 相机系立方体 → 基座系 8 角点 + 像素投影。

为什么不做"深度实测": D405 的 depth 话题当前 Publisher count = 0 (深度文件停更),
所以距离用**已知件尺寸反解**(画面高度 ↔ 实物长度), 自洽但带 ~5% 误差;
一旦深度恢复, 把 depth_mm 传进来即可切到实测深度, 上层接口不变。

坐标链(全部真源, 不编造):
  T_base_tool ← 珞石 TCP 真值 (/pose: xyz + abc/四元数, 两者实测一致到 1e-4)
  T_cam2tool  ← models/handeye_state.json (残差 0.06mm / 0.0046°)
  K, dist     ← models/real_cam_calib.json (D405 出厂内参, /realsense/color/camera_info)
"""
from __future__ import annotations

import json
import math
import os
import threading
import time

import numpy as np

REPO = os.path.expanduser("~/zmax")
HAND_EYE = os.path.join(REPO, "models", "handeye_state.json")
REAL_CAL = os.path.join(REPO, "models", "real_cam_calib.json")
YOLO_PT = os.path.join(REPO, "models", "yolo_peg_live.pt")

# 光模块外形 (SFP 类, 直立插在料盘里: 长轴竖直)。画面里宽高比实测 27/122 = 0.22,
# 与 13.4/56.5 = 0.24 吻合 ⇒ 长轴当 56.5mm 用。可用环境变量覆盖。
MOD_H_MM = float(os.environ.get("ZMAX_MOD_H_MM", "56.5"))     # 长轴
MOD_W_MM = float(os.environ.get("ZMAX_MOD_W_MM", "13.4"))     # 短轴(参考)
MOD_T_MM = float(os.environ.get("ZMAX_MOD_T_MM", "8.5"))      # 厚度
CONF_MIN = float(os.environ.get("ZMAX_MOD_CONF", "0.25"))

_YOLO = None
_YOLO_LOCK = threading.Lock()
_LAST = {"d_mm": None, "t": 0.0}          # 上一次"未裁切"的有效距离(框贴边时沿用)


def _yolo():
    global _YOLO
    with _YOLO_LOCK:
        if _YOLO is None:
            from ultralytics import YOLO
            _YOLO = YOLO(YOLO_PT)
        return _YOLO


def _refine_extent(img_bgr, x1, y1, x2, y2, gap_max=3, frac=0.32):
    """在检测框基础上，沿长轴把整支光模块圈全（银色壳体 + 绿色拉环/头部）。
    检测框常只盖住壳体一段（实测：框到 y=118，而模块实际到 y≈157，头部被漏掉）。
    做法：HSV 里取「低饱和高亮(金属) | 绿色(拉环)」像素，按行统计宽度剖面，
    从框内向外扩；允许 ≤gap_max 行空洞，遇连续空洞即停（避免并入下方其它工件）。
    """
    import cv2 as _cv
    H, W = img_bgr.shape[:2]
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    xa, xb = max(0, x1 - 6), min(W, x2 + 6)
    if xb - xa < 4 or y2 <= y1:
        return x1, y1, x2, y2, "跳过(框太小)"
    hsv = _cv.cvtColor(img_bgr, _cv.COLOR_BGR2HSV)
    sub = hsv[:, xa:xb]
    S = sub[:, :, 1].astype(int)
    V = sub[:, :, 2].astype(int)
    Hh = sub[:, :, 0].astype(int)
    mask = ((S < 80) & (V > 100)) | ((Hh > 33) & (Hh < 98) & (S > 50))
    prof = mask.sum(axis=1)
    thr = max(6, frac * (x2 - x1))

    def grow(start, step):
        gap = 0
        y = start
        while 0 <= y + step < H:
            y += step
            if prof[y] >= thr:
                gap = 0
            else:
                gap += 1
                if gap > gap_max:
                    return y - step * gap
        return y

    top = grow(y1, -1)
    bot = grow(y2, +1)
    if bot <= top:
        return x1, y1, x2, y2, "扩失败(剖面为空)"
    band = mask[top:bot + 1]
    colp = band.sum(axis=0)
    cols = np.where(colp > max(2, 0.25 * (bot - top)))[0]
    nx1 = xa + int(cols[0]) if len(cols) else x1
    nx2 = xa + int(cols[-1]) if len(cols) else x2
    return nx1, top, nx2, bot, "扩 %s→%s" % ((y1, y2), (top, bot))


def detect_boxes(img_bgr, conf=CONF_MIN):
    """返回 [{name, conf, xyxy}] —— 在役权重 (peg / OPT_Gold)。"""
    m = _yolo()
    r = m.predict(img_bgr, conf=conf, imgsz=960, verbose=False)[0]
    out = []
    for b in r.boxes:
        out.append({"name": m.names[int(b.cls[0])], "conf": float(b.conf[0]),
                    "xyxy": [float(v) for v in b.xyxy[0]]})
    out.sort(key=lambda d: -d["conf"])
    return out


def _R_from_abc(a, b, c):
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cc, sc = math.cos(c), math.sin(c)
    Rz = np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]])
    Ry = np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]])
    Rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
    return Rz @ Ry @ Rx


def _load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def camera_pose(tcp):
    """T_base_cam(mm)。tcp = {'xyz':[m], 'abc_rad':[...]} 或 {'ok','x','y','z','quat'}。"""
    if not tcp:
        raise ValueError("没有 TCP 位姿")
    if "abc_rad" in tcp:
        xyz = np.array(tcp["xyz"], float) * 1000.0
        R = _R_from_abc(*tcp["abc_rad"])
    else:
        xyz = np.array([tcp["x"], tcp["y"], tcp["z"]], float) * 1000.0
        qx, qy, qz, qw = [float(v) for v in tcp["quat"]]
        R = np.array([
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])
    T_bt = np.eye(4)
    T_bt[:3, :3] = R
    T_bt[:3, 3] = xyz
    he = _load_json(HAND_EYE)
    if not he.get("ok"):
        raise ValueError("手眼未标定 (handeye_state.json ok=false)")
    T_ct = np.array(he["T_cam2tool"], float).copy()
    T_ct[:3, 3] *= 1000.0                       # 手眼平移是米 ⇒ 统一毫米
    return T_bt @ T_ct, T_bt, he


def intrinsics():
    d = _load_json(REAL_CAL)
    K = np.array(d["K"], float).reshape(3, 3)
    dist = np.array(d["dist"], float).ravel()
    return K, dist


def _undistort_norm(u, v, K, dist):
    x = (u - K[0, 2]) / K[0, 0]
    y = (v - K[1, 2]) / K[1, 1]
    k1, k2, p1, p2, k3 = list(dist[:5]) + [0.0] * (5 - len(dist[:5]))
    r2 = x * x + y * y
    rad = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 ** 3
    xd = x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
    yd = y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    return xd, yd


def build(img_bgr, tcp, depth_mm=None, h_mm=MOD_H_MM, t_mm=MOD_T_MM, conf=CONF_MIN):
    """一张图 + TCP ⇒ 光模块 3D 框。

    返回 dict: ok, box2d, corners_px(8), corners_base_mm(8), dist_mm, dims_mm,
               conf, class, src, warn[]
    """
    warn = []
    K, dist = intrinsics()
    items = detect_boxes(img_bgr, conf)
    if not items:
        return {"ok": False, "err": "画面里没检出目标 (在役权重 peg/OPT_Gold)", "warn": warn}
    det = items[0]
    if det["name"] != "OPT_Gold":
        warn.append("检出的类别是 %s, 不是 OPT_Gold (光模块类) —— 按同一位置给框" % det["name"])
    x1, y1, x2, y2 = det["xyxy"]
    det_box = [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]
    # 🔎 检测框常只盖住壳体一段(实测到 y=118, 模块实际到 y≈157) ⇒ 沿长轴把整支(含头部)圈全
    rx1, ry1, rx2, ry2, rnote = _refine_extent(img_bgr, x1, y1, x2, y2)
    x1, y1, x2, y2 = rx1, ry1, rx2, ry2
    H_img, W_img = img_bgr.shape[:2]
    # 🔴 框贴边 = 目标被画幅裁掉: 此时"框高 ⇒ 距离"必然偏大(看到的只是局部), 不能当真
    clip = {"top": y1 <= 1.5, "bottom": y2 >= H_img - 1.5,
            "left": x1 <= 1.5, "right": x2 >= W_img - 1.5}
    clipped = [k for k, v in clip.items() if v]
    if clipped:
        warn.append("检测框贴到画面边缘(%s) ⇒ 目标被裁, 尺寸不完整, 距离反解会偏大" % "/".join(clipped))
    u, v = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    h_px = max(1.0, y2 - y1)
    w_px = max(1.0, x2 - x1)

    T_bc, T_bt, he = camera_pose(tcp)
    o = T_bc[:3, 3]
    Rcb = T_bc[:3, :3]
    # 视线方向 (相机系 → 基座系)
    xd, yd = _undistort_norm(u, v, K, dist)
    d_cam = np.array([xd, yd, 1.0])
    d_cam /= np.linalg.norm(d_cam)
    d_base = Rcb @ d_cam

    f = float(K[0, 0])
    D = None
    if depth_mm:
        D = float(depth_mm)
        src = "depth(实测)"
    elif clipped and _LAST["d_mm"] and (time.time() - _LAST["t"]) < 15.0:
        D = float(_LAST["d_mm"])                    # 被裁时沿用上一次未裁的距离, 避免框忽然变大
        src = "size(沿用上次未裁切距离 %.1fmm)" % D
        warn.append("目标出画被裁, 距离沿用上一次完整观测(15s 内), 不重新反解")
    else:
        D = f * float(h_mm) / h_px
        src = "size(已知件长 %.1fmm ↔ 画面 %.0fpx)" % (h_mm, h_px)
        warn.append("无深度: 距离由已知件长反解, 误差 ~5%; 换品种要把 ZMAX_MOD_H_MM 设成真实长度")
    if not clipped and depth_mm is None:
        _LAST["d_mm"] = D
        _LAST["t"] = time.time()

    W = float(w_px) * D / f                   # 画面宽 ⇒ 实物宽(不用猜)
    H = float(h_mm) if not depth_mm else float(h_px) * D / f

    c_cam = d_cam * D                          # 立方体中心(相机系)
    ex = np.array([1.0, 0, 0])                 # 相机 x = 画面横
    ey = np.array([0, 1.0, 0])                 # 相机 y = 画面竖 (长轴)
    ez = np.array([0, 0, 1.0])                 # 相机 z = 视线
    corners_cam, corners_base, corners_px = [], [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                p = c_cam + ex * (sx * W / 2) + ey * (sy * H / 2) + ez * (sz * float(t_mm) / 2)
                corners_cam.append(p)
                corners_base.append(Rcb @ p + o)
                pc = p / p[2]
                corners_px.append([K[0, 0] * pc[0] + K[0, 2], K[1, 1] * pc[1] + K[1, 2]])
    center_base = Rcb @ c_cam + o
    return {
        "ok": True,
        "class": det["name"], "conf": round(det["conf"], 3),
        "box2d": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        "box2d_det": det_box,
        "refine": rnote,
        "corners_px": [[round(p[0], 1), round(p[1], 1)] for p in corners_px],
        "corners_base_mm": [[round(p[0], 1), round(p[1], 1), round(p[2], 1)] for p in corners_base],
        "center_base_mm": [round(p, 1) for p in center_base],
        "dist_mm": round(D, 1),
        "dims_mm": [round(W, 1), round(H, 1), round(float(t_mm), 1)],
        "cam_origin_mm": [round(p, 1) for p in o],
        "tcp_mm": [round(p, 1) for p in T_bt[:3, 3]],
        "handeye_resid_mm": he.get("resid_trans_mm_rms"),
        "src": src,
        "depth_available": bool(depth_mm),
        "clipped": clipped,
        "warn": warn,
    }


# 立方体 12 条棱 (角点顺序 = sx,sy,sz 三重循环)
EDGES = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
