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
_CONT = {"d_mm": None, "h_px": None, "w_px": None, "base_mm": None, "t": 0.0}   # 连续性闸: 上一次被接受的观测


def _yolo():
    global _YOLO
    with _YOLO_LOCK:
        if _YOLO is None:
            from ultralytics import YOLO
            _YOLO = YOLO(YOLO_PT)
        return _YOLO


def _refine_extent(img_bgr, x1, y1, x2, y2, gap_max=3, frac=0.32, max_extend=100,
                   max_color_dist=45.0, green_extra=25):
    """在检测框基础上，沿长轴把整支光模块圈全（银色壳体 + 绿色拉环/头部）。

    检测框常只盖住壳体一段（实测：框到 y=118，而模块实际到 y≈157，头部被漏掉）。

    🔴 两次现场血案（都是"扩过头"）：
      ① 只按"行剖面 ≥ 0.32×框宽"扩 ⇒ 遇到大片同色背景一路扩到画面边缘（58px 的框被扩成 0~479）。
      ② 只加"最多 ±100px"还不够 ⇒ 仍会把相邻的别的东西吃进来。
    ⇒ 现在四条一起收口：
      ①向外最多 max_extend px ②阈值 = max(8, 0.32×框宽, 0.5×框内剖面中位数)
      ③扩出的行若明显比框宽（>1.6×）当场停 ④**颜色必须连续**：行内平均色与框内平均色差 ≤ max_color_dist；
        绿色（拉环）允许再额外 green_extra px —— 因为拉环是绿的、壳体是银的，但绿 PCB 底面在更远处，靠这条把它挡住。
    """
    import cv2 as _cv
    H, W = img_bgr.shape[:2]
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    xa, xb = max(0, x1 - 6), min(W, x2 + 6)
    if xb - xa < 4 or y2 <= y1:
        return x1, y1, x2, y2, "跳过(框太小)"
    hsv = _cv.cvtColor(img_bgr, _cv.COLOR_BGR2HSV)
    sub = img_bgr[:, xa:xb]
    sh = hsv[:, xa:xb]
    S = sh[:, :, 1].astype(int)
    V = sh[:, :, 2].astype(int)
    Hh = sh[:, :, 0].astype(int)
    mask = ((S < 80) & (V > 100)) | ((Hh > 33) & (Hh < 98) & (S > 50))
    green = (Hh > 33) & (Hh < 98) & (S > 50)
    prof = mask.sum(axis=1)

    ya, yb = max(0, y1), min(H - 1, y2)
    in_prof = prof[ya:yb + 1]
    base_med = float(np.median(in_prof)) if in_prof.size else 0.0
    thr = max(8.0, frac * (x2 - x1), 0.5 * base_med)
    wide = 1.6 * max(4, x2 - x1)

    sel = mask[ya:yb + 1]
    ref_col = sub[ya:yb + 1][sel].mean(0) if sel.any() else None

    def row_col(y):
        m = mask[y]
        return (sub[y][m].mean(0) if m.any() else None), (m & green[y]).sum() > 0.5 * max(1, m.sum())

    def ok_row(y, moved):
        if prof[y] < thr or prof[y] > wide:
            return False
        c, is_green = row_col(y)
        if ref_col is None or c is None:
            return True
        d = float(np.abs(c - ref_col).mean())
        if d <= max_color_dist:
            return True
        return bool(is_green and moved <= green_extra)          # 拉环: 颜色不同但紧邻

    def grow(start, step, limit):
        gap = 0
        y = start
        moved = 0
        while 0 <= y + step < H and moved < limit:
            y += step
            moved += 1
            if ok_row(y, moved):
                gap = 0
            else:
                gap += 1
                if gap > gap_max:
                    return y - step * gap
        return y

    top = grow(y1, -1, max_extend)
    bot = grow(y2, +1, max_extend)
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
    elif clipped:
        # 🔴 2026-10-18 现场: 只剩"一个小头"时, 可见高度 61px ≠ 整支 56.5mm,
        # 按长轴反解会给出 365mm 这种明显偏大的距离 ⇒ 框的深度/尺寸跟着错。
        # 宽度几乎不受纵向裁切影响, 被裁时改用**宽度**反解。
        D = f * float(MOD_W_MM) / w_px
        src = "size(被裁→用宽度 %.1fmm ↔ 画面 %.0fpx)" % (MOD_W_MM, w_px)
        warn.append("目标出画被裁 ⇒ 长轴不可信, 改用宽度反解距离(宽度受纵向裁切影响小)")
    else:
        D = f * float(h_mm) / h_px
        src = "size(已知件长 %.1fmm ↔ 画面 %.0fpx)" % (h_mm, h_px)
        warn.append("无深度: 距离由已知件长反解, 误差 ~5%; 换品种要把 ZMAX_MOD_H_MM 设成真实长度")
    # ── 连续性闸 ── 老倪 2026-10-18: 「光模块不可能突然变化很大的, 它是一个连续的模块」
    # 同一支模块相邻两帧的画面尺寸不会翻倍/减半, 距离也不会凭空跳。
    # 越界 ⇒ 这一帧必然是算错了(遮挡/裁切/误检), 沿用上一次可信值, 并显式标注, 不许"看起来像"就画出来。
    _now = time.time()
    jump = None
    fresh = bool(_CONT["t"]) and (_now - _CONT["t"]) < 2.5
    if fresh:
        r_h = h_px / max(1e-6, _CONT["h_px"])
        r_w = w_px / max(1e-6, _CONT["w_px"])
        if not (0.62 <= r_h <= 1.62) or not (0.55 <= r_w <= 1.80):
            jump = "画面尺寸跳变 h×%.2f w×%.2f" % (r_h, r_w)
    if jump and _CONT["d_mm"]:
        D = float(_CONT["d_mm"])
        src = "size(跳变被拒→沿用上次 %.1fmm)" % D
        warn.append("连续性闸: %s ⇒ 该帧不可信, 沿用上次距离(模块是连续物体, 不会突跳)" % jump)
    else:
        if fresh and _CONT["d_mm"]:
            D = 0.6 * D + 0.4 * float(_CONT["d_mm"])          # 轻度平滑, 压抖动
        _CONT.update(d_mm=float(D), h_px=float(h_px), w_px=float(w_px), t=_now)
    if not clipped and depth_mm is None:
        _LAST["d_mm"] = D
        _LAST["t"] = time.time()

    W = float(w_px) * D / f                   # 画面宽 ⇒ 实物宽(不用猜)
    # 🔴 2026-10-18 老倪: 「你的标注，太长了」「画面中的光模块，只有一个小头」
    # 原来无深度时 H 直接取整支 56.5mm ⇒ 只看到 61px 小头时, 画出来的框仍有 140px 高,
    # 视觉上就是"框比物体长出一大截"。框只应该盖住**看得见的那部分**:
    # 可见像素高 h_px × 距离 D ÷ 焦距 f = 可见实物高。整支都可见时自然 ≈ 56.5mm。
    H = float(h_px) * D / f

    c_cam = d_cam * D                          # 立方体中心(相机系)
    ex = np.array([1.0, 0, 0])                 # 相机 x = 画面横
    ey = np.array([0, 1.0, 0])                 # 相机 y = 画面竖 (长轴)
    ez = np.array([0, 0, 1.0])                 # 相机 z = 视线

    def _corners(Hv):
        cc, cb, cp = [], [], []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    p = c_cam + ex * (sx * W / 2) + ey * (sy * Hv / 2) + ez * (sz * float(t_mm) / 2)
                    cc.append(p)
                    cb.append(Rcb @ p + o)
                    pc = p / p[2]
                    cp.append([K[0, 0] * pc[0] + K[0, 2], K[1, 1] * pc[1] + K[1, 2]])
        return cc, cb, cp

    # 🔴 投影自洽(2026-10-18 老倪「你的标注，太长了」):
    # 立方体斜着看时, 3D 框的**投影**会比正面可见高度大一截(实测 24mm 的框投出 82px, 而可见只有 61px),
    # 现场看到的就是"框比物体长"。所以按"投影高 = 可见像素高"反解一次 H, 迭代到一致。
    corners_cam, corners_base, corners_px = _corners(H)
    for _ in range(3):
        ys = [q[1] for q in corners_px]
        proj = max(ys) - min(ys)
        if proj < 2.0 or h_px < 2.0:
            break
        H *= float(h_px) / proj
        corners_cam, corners_base, corners_px = _corners(H)
    center_base = Rcb @ c_cam + o
    _CONT["base_mm"] = [float(v) for v in center_base]
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
        "dims_mm": [round(float(W), 1), round(float(H), 1), round(float(t_mm), 1)],   # 必须转 float: np.float64 不能直接 json 序列化
        "cam_origin_mm": [round(p, 1) for p in o],
        "tcp_mm": [round(p, 1) for p in T_bt[:3, 3]],
        "handeye_resid_mm": he.get("resid_trans_mm_rms"),
        "src": src,
        "depth_available": bool(depth_mm),
        "clipped": clipped,
        "extent_note": ("只框可见部分(头部出画)" if clipped else "整支"),
        "continuity": {"jump": jump, "smoothed": bool(fresh and not jump)},
        "warn": warn,
    }


# 立方体 12 条棱 (角点顺序 = sx,sy,sz 三重循环)
EDGES = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
