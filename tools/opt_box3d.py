#!/usr/bin/env python3
"""光模块 3D 框: 臂相机画面 → 2D 检测框 → 相机系立方体 → 基座系 8 角点 + 像素投影。

为什么不做"深度实测": D405 的 depth 话题当前 Publisher count = 0 (深度文件停更),
所以距离用**已知件尺寸反解**(画面高度 ↔ 实物长度), 自洽但带 ~5% 误差;
一旦深度恢复, 把 depth_mm 传进来即可切到实测深度, 上层接口不变。

坐标链(全部唯一依据, 不编造):
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
MOD_D_REF_MM = float(os.environ.get("ZMAX_MOD_D_REF", "159.2"))   # 整支可见时实测的相机↔模块距离(刚性参考)
MOD_T_MM = float(os.environ.get("ZMAX_MOD_T_MM", "8.5"))      # 厚度
CONF_MIN = float(os.environ.get("ZMAX_MOD_CONF", "0.25"))

_YOLO = None
_YOLO_LOCK = threading.Lock()
_LAST = {"d_mm": None, "t": 0.0}          # 上一次"未裁切"的有效距离(框贴边时沿用)
_CONT = {"d_mm": None, "h_px": None, "w_px": None, "base_mm": None, "t": 0.0}   # 连续性闸: 上一次被接受的观测
_SMO = {"c": None, "H": None, "t": 0.0}   # 输出平滑: 上一次画出去的框(中心/H), 老倪「别突然变化」
_LASTBOX = {"box2d": None, "t": 0.0}     # 上一次检出的 2D 框: 全图检不到时在它附近局部重检(别丢模块)
_JUMP = {"box": None, "n": 0}           # 位置跳变待确认计数: 模块是连续的, 一帧跳半屏必然错检
_PATCH_F = os.environ.get("ZMAX_MOD_PATCH", "/dev/shm/mod3_patch.png")   # 上一次成功框内的灰度模板(跨 fork)
det_name_fallback = "peg"               # 模板接住时沿用的类名(与在役权重同口径)


def _yolo():
    global _YOLO
    with _YOLO_LOCK:
        if _YOLO is None:
            from ultralytics import YOLO
            _YOLO = YOLO(YOLO_PT)
        return _YOLO



def warm():
    """在**父进程**里把权重装好并跑一次空推 —— AR 服务是 fork-per-request,
    父进程预先装载后子进程按 COW 直接继承; 否则每个请求都要重装权重(实测 ~900ms, 现场感知就是"画面延迟大")。"""
    try:
        import numpy as _np
        m = _yolo()
        m.predict(_np.zeros((480, 640, 3), _np.uint8), conf=0.9, imgsz=int(os.environ.get("ZMAX_YOLO_IMGSZ", "640")),
                  device=os.environ.get("ZMAX_YOLO_DEVICE", "cpu"), verbose=False)
        return True
    except Exception:                                                       # noqa: BLE001
        return False


_STATE_F = os.environ.get("ZMAX_MOD_STATE", "/dev/shm/zmax_mod_state.json")


def _state_load():
    """AR 服务是 fork-per-request(每请求一个子进程) ⇒ 模块级变量**不跨请求**。
    连续性闸/平滑必须靠外部状态, 否则每个请求都是"第一次", 闸等于没装。
    放 /dev/shm(内存盘), 原子替换写, 读失败一律返回空(不阻断检测)。"""
    try:
        with open(_STATE_F, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                       # noqa: BLE001
        return {}


def _freeze_load():
    """读钉住的结果(/dev/shm/mod3_freeze.json); 没有就返回 None。"""
    try:
        with open("/dev/shm/mod3_freeze.json", encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("ok") else None
    except Exception:                                                       # noqa: BLE001
        return None


def _state_save(d):
    try:
        tmp = _STATE_F + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, _STATE_F)
    except Exception:                                                       # noqa: BLE001
        pass


def _refine_width(img_bgr, x1, y1, x2, y2, pad=26, min_frac=0.30):
    """横向精修: 在框的 y 行范围内逐列统计模块掩膜, 从框中心向两侧扩到"断档"为止。

    🔴 2026-10-19 老倪现场: 「你现在的绿色光模块的边界框, 向左偏了一些, 修正」
       —— _refine_extent 只沿**长轴(上下)**扩, 水平方向一直沿用 YOLO 原框(±6px)。
       实测 YOLO 框中心比模块真实中心偏 3~4px(316~350 vs 实际 312~347), 视觉上就是框没盖住模块。
       这里只改 x、绝不动 y(被画幅裁掉时 y 不可观测, 不能猜)。
    """
    import cv2 as _cv
    H, W = img_bgr.shape[:2]
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    ya, yb = max(0, y1), min(H - 1, y2)
    if yb <= ya or x2 <= x1:
        return x1, x2, "跳过(框太小)"
    hsv = _cv.cvtColor(img_bgr, _cv.COLOR_BGR2HSV)
    S = hsv[:, :, 1].astype(int)
    V = hsv[:, :, 2].astype(int)
    Hh = hsv[:, :, 0].astype(int)
    mask = ((S < 80) & (V > 100)) | ((Hh > 33) & (Hh < 98) & (S > 50))   # 银壳 + 绿拉环
    prof = mask[ya:yb + 1, :].sum(axis=0)
    thr = max(3.0, min_frac * (yb - ya + 1))
    # 🔴 2026-10-19: 起点不能用框中心 —— 框本身整体偏了, 拿它当锚会一路偏下去。
    #   老倪现场给的真值: 「光模块就在屏幕中心, 上边沿中线上」⇒ 在框左右窗口里取**掩膜覆盖最宽的列**当锚。
    _wx0, _wx1 = max(0, x1 - pad), min(W - 1, x2 + pad)
    _seg = prof[_wx0:_wx1 + 1]
    cx = int(_wx0 + int(np.argmax(_seg))) if _seg.size else int(round((x1 + x2) / 2.0))
    ok = prof >= thr
    lo, hi = max(0, x1 - pad), min(W - 1, x2 + pad)
    l = cx
    while l > lo and ok[l - 1]:
        l -= 1
    r = cx
    while r < hi and ok[r + 1]:
        r += 1
    if r - l < 4:
        return x1, x2, "跳过(掩膜太窄)"
    return l, r, "横修 %d~%d (原 %d~%d, 中心 %+.1fpx)" % (l, r, x1, x2, (l + r) / 2.0 - (x1 + x2) / 2.0)


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
    # 🔴 2026-10-18: imgsz 960→640 + 默认 CPU(实测 60ms; GPU 7ms 但 fork 后不能复用 CUDA 上下文)
    # 之前慢的真正原因不是 imgsz, 是**每个请求都在子进程里重新 YOLO(...) 装载权重(~900ms)** ⇒ 见 warm()
    r = m.predict(img_bgr, conf=conf, imgsz=int(os.environ.get("ZMAX_YOLO_IMGSZ", "640")),
                  device=os.environ.get("ZMAX_YOLO_DEVICE", "cpu"), verbose=False)[0]
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
    _st = _state_load()                     # fork-per-request ⇒ 状态必须从 /dev/shm 取回
    if _st:
        _LAST.update(_st.get("last") or {})
        _CONT.update(_st.get("cont") or {})
        _SMO.update(_st.get("smo") or {})
        _LASTBOX.update(_st.get("lastbox") or {})
        _JUMP.update(_st.get("jump") or {})
    K, dist = intrinsics()
    # 🔴 老倪 2026-10-18「绿色标注框，在画面中的位置，保持不动都可以」:
    # 相机在腕上、模块被夹住 ⇒ 刚体关系, 像素位置本该是常量。钉住后不再每帧追,
    # 画面继续刷新(帧龄是真的), 但框的位置/尺寸/角点全部原样返回。
    _fr = _freeze_load()
    if _fr is not None:
        out = dict(_fr)
        out["ts"] = time.time()
        out["frozen"] = True
        out["frame_ts"] = time.time()
        return out

    items = detect_boxes(img_bgr, conf)
    # 🆕 2026-10-20 现场: 手臂相机与臂一体 ⇒ 爪中模块**恒在画面上半部**;
    #   实测 bottom 料盘里的模块会以 conf 0.42 被检出(y 459~480), 而真模块在顶部(y 0~58, conf 0.68),
    #   两框同帧竞争时曾选错。⇒ 先丢掉画面下半部的框(料盘里的), 全空才回退。
    _H = img_bgr.shape[0]
    _up = [d for d in items if (d["xyxy"][1] + d["xyxy"][3]) / 2.0 < _H * 0.5]
    if _up:
        if len(_up) != len(items):
            warn.append("手臂相机位置先验: 丢掉画面下半部 %d 个框(料盘), 保留 %d 个上半部" % (len(items) - len(_up), len(_up)))
        items = _up
    else:
        if items:
            warn.append("⚠ 上半部无框, 回退用全画面最高 conf 框(可能在料盘)")
    det_src = "yolo" if items else None
    if not items:
        # 🔴 2026-10-19 现场: 走完围栏线后腕部姿态翻了 180°, 模块亮度/角度变了 ⇒ 模型只给 0.10 的 conf
        #   (实测原图 conf=0.101 box=[300.7,4.1,357.7,65.0]), 而默认阈值 0.25 直接把它滤掉,
        #   结果"框丢了"。这里先按低阈值重检一次, 后面的选框规则(离上次框最近/离画面中心最近)负责挡误检。
        _low = detect_boxes(img_bgr, min(conf, 0.08))
        if _low:
            items = _low
            det_src = "yolo-low"
            warn.append("默认阈值 %.2f 未检出 ⇒ 低阈值(0.08)重检命中 conf %.2f" % (conf, _low[0]["conf"]))
    if not items:
        # 🔴 老倪 2026-10-18「稳住，别丢光模块」: 只剩小头/被遮挡时全图 YOLO 会漏(实测连丢 13 帧)。
        # 模块是连续的、跑不掉 —— 就在上一次框的邻域里裁一块放大 2× 重检, 命中后映射回全图坐标。
        lb = _LASTBOX.get("box2d")
        if lb and (time.time() - float(_LASTBOX.get("t") or 0)) < 30.0:
            Hh, Ww = img_bgr.shape[:2]
            mx, my = max(24, (lb[2] - lb[0])), max(24, (lb[3] - lb[1]))
            cx1 = int(max(0, lb[0] - mx)); cx2 = int(min(Ww, lb[2] + mx))
            cy1 = int(max(0, lb[1] - my)); cy2 = int(min(Hh, lb[3] + my))
            import cv2
            # ① 模板匹配(纯 CV): 模块是刚性跟着相机走的, 图像里位置几乎不变 ⇒ 上一次的框内图像
            #    就是最好的模板。实测模型在"只剩小头/暗光"时会彻底漏检, 而模板匹配仍能跟上。
            tpl_f = _PATCH_F
            try:
                tpl = cv2.imread(tpl_f, cv2.IMREAD_GRAYSCALE)
            except Exception:                                               # noqa: BLE001
                tpl = None
            if tpl is not None and tpl.size > 64:
                sx1 = int(max(0, lb[0] - 0.6 * (lb[2] - lb[0]) - 12))
                sy1 = int(max(0, lb[1] - 0.6 * (lb[3] - lb[1]) - 12))
                sx2 = int(min(Ww, lb[2] + 0.6 * (lb[2] - lb[0]) + 12))
                sy2 = int(min(Hh, lb[3] + 0.6 * (lb[3] - lb[1]) + 12))
                win = img_bgr[sy1:sy2, sx1:sx2]
                if win.shape[0] >= tpl.shape[0] and win.shape[1] >= tpl.shape[1]:
                    res = cv2.matchTemplate(cv2.cvtColor(win, cv2.COLOR_BGR2GRAY), tpl, cv2.TM_CCOEFF_NORMED)
                    _, mxv, _, mxl = cv2.minMaxLoc(res)
                    if mxv >= 0.55:
                        bx1 = sx1 + mxl[0]; by1 = sy1 + mxl[1]
                        items = [{"name": det_name_fallback, "conf": float(mxv),
                                  "xyxy": [float(bx1), float(by1),
                                           float(bx1 + tpl.shape[1]), float(by1 + tpl.shape[0])]}]
                        det_src = "template"
                        warn.append("YOLO 漏检 ⇒ 模板匹配接住(相似度 %.2f), 模块未丢" % mxv)
            if not items and cx2 - cx1 > 16 and cy2 - cy1 > 16:
                # ② 再退一步: 邻域放大重检(对小目标有时有效; 实测本例多数无效, 所以放在模板之后)
                crop = img_bgr[cy1:cy2, cx1:cx2]
                crop2 = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                hit = detect_boxes(crop2, max(0.12, conf * 0.6))
                if hit:
                    _b = dict(hit[0])
                    _b["xyxy"] = [cx1 + v / 2.0 for v in _b["xyxy"]]
                    items = [_b]
                    det_src = "roi"
                    warn.append("全图未检出 ⇒ 邻域放大 2× 重检命中(conf %.2f), 模块未丢" % _b["conf"])
    if not items:
        return {"ok": False, "err": "画面里没检出目标 (在役权重 peg/OPT_Gold)", "warn": warn}
    # ── 选哪一个检测 ── 老倪 2026-10-18「光模块的位置标记错了」:
    # 实测低置信度时最高分那只可能是画面另一头的物体。规则:
    #   ① 有上一次框(3s 内) ⇒ 取**离它最近**、且 conf ≥ 0.15 的那只(模块是连续的, 不会跳到别处)
    #   ② 冷启动 ⇒ 取离画面中心最近的(相机装在手爪上, 爪口与模块就在光轴附近)
    #   ③ 都没有 ⇒ 退回最高分(并如实标注)
    det = items[0]
    if len(items) > 1:
        def _ctr(it):
            a = it["xyxy"]
            return ((a[0] + a[2]) / 2.0, (a[1] + a[3]) / 2.0)
        _lb = _LASTBOX.get("box2d")
        if _lb and (time.time() - float(_LASTBOX.get("t") or 0)) < 3.0:
            _ref = ((_lb[0] + _lb[2]) / 2.0, (_lb[1] + _lb[3]) / 2.0)
            _cand = [it for it in items if it["conf"] >= 0.15]
            if _cand:
                det = min(_cand, key=lambda it: math.hypot(_ctr(it)[0] - _ref[0], _ctr(it)[1] - _ref[1]))
        else:
            _hc = (img_bgr.shape[1] / 2.0, img_bgr.shape[0] / 2.0)
            det = min(items, key=lambda it: math.hypot(_ctr(it)[0] - _hc[0], _ctr(it)[1] - _hc[1]))
        if det is not items[0]:
            warn.append("多检出 %d 只: 按%s选了 conf %.2f 的那只(不是最高分)" % (
                len(items), "就近" if _lb else "离画面中心最近", det["conf"]))
    if det["name"] != "OPT_Gold":
        warn.append("检出的类别是 %s, 不是 OPT_Gold (光模块类) —— 按同一位置给框" % det["name"])
    x1, y1, x2, y2 = det["xyxy"]
    det_box = [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]
    H_img, W_img = img_bgr.shape[:2]
    # 🔎 检测框常只盖住壳体一段(实测到 y=118, 模块实际到 y≈157) ⇒ 沿长轴把整支(含头部)圈全
    # 🔴 但**已经被画幅裁掉时绝不能再外扩**(老倪 2026-10-18「又太长了」):
    # 只剩小头时, 检测框下方紧挨着的是台面/背景亮面, 外扩会跨过缝隙把背景并进来(实测 58px→92px)。
    # 被裁 = 只看得到一段, 这时"整支有多长"本来就不可观测 ⇒ 用检测框原样, 不猜。
    _clip0 = {"top": y1 <= 1.5, "bottom": y2 >= H_img - 1.5, "left": x1 <= 1.5, "right": x2 >= W_img - 1.5}
    # 🆕 2026-10-22 现场(老倪: 「手臂相机现在没有光模块, 不需要显示绿色边界框」):
    #   实测: 画面顶边那台浅灰白圆角装置被在役权重以 class=peg conf≈0.44~0.48 误检, 框贴顶边被裁
    #   (只看到一条边, 深度也不可用) ⇒ 页面却一直画一个"光模块 3D"绿框。
    #   判据: **类别不是光模块类(OPT_Gold) 且 框贴画幅边被裁** ⇒ 判误检、不给框(回 ok=False, 页面不画);
    #   框完整(未贴边)的 peg 仍走原逻辑给框(保住 2026-10-19「别丢光模块」)。
    _clipped0 = [k for k, v in _clip0.items() if v]
    # 🆕 2026-10-22 老倪: 「现在的光模块, 就一个小头, 边界框你得画出来啊」
    #   同一个"贴边 peg"既可能是误检(顶边圆角装置, conf≈0.44~0.48), 也可能是**只露小头的真模块**。
    #   单靠类别统一处理会把真模块也挡掉 ⇒ 加置信度分界: ≥0.65 当真模块, 只框可见那段并标注"被裁"。
    _peg_clip_conf = float(os.environ.get("ZMAX_PEG_CLIP_MIN", "0.65"))
    _is_real_head = (_clipped0 and det.get("name") != "OPT_Gold"
                     and float(det.get("conf") or 0) >= _peg_clip_conf)
    if _clipped0 and det.get("name") != "OPT_Gold" and not _is_real_head:
        warn.append("类别 %s 且框贴 %s 边被裁 ⇒ 判为误检, 不给光模块框"
                    % (det.get("name"), "/".join(_clipped0)))
        return {"ok": False,
                "err": "本帧未检出光模块(误检被挡: %s 类 + 贴%s边)" % (det.get("name"), "/".join(_clipped0)),
                "class": det.get("name"), "conf": round(float(det.get("conf") or 0), 3),
                "box2d": det_box, "clipped": _clipped0, "warn": warn}
    if any(_clip0.values()):
        rnote = "被裁(%s)⇒用检测框原样, 不外扩" % "/".join(k for k, v in _clip0.items() if v)
        # 被裁时 y 不可观测(不能猜), 但 **x 可以修** —— 横向偏左/偏右是纯像素事实
        if not ("left" in _clip0 or "right" in _clip0):
            _l, _r, _wn = _refine_width(img_bgr, x1, y1, x2, y2)
            if _r - _l >= 6:
                x1, x2 = _l, _r
                rnote += " · " + _wn
    else:
        rx1, ry1, rx2, ry2, rnote = _refine_extent(img_bgr, x1, y1, x2, y2)
        x1, y1, x2, y2 = rx1, ry1, rx2, ry2
        _l, _r, _wn = _refine_width(img_bgr, x1, y1, x2, y2)
        if _r - _l >= 6:
            x1, x2 = _l, _r
            rnote += " · " + _wn
    # 🔴 框贴边 = 目标被画幅裁掉: 此时"框高 ⇒ 距离"必然偏大(看到的只是局部), 不能当真
    clip = {"top": y1 <= 1.5, "bottom": y2 >= H_img - 1.5,
            "left": x1 <= 1.5, "right": x2 >= W_img - 1.5}
    clipped = [k for k, v in clip.items() if v]
    if clipped:
        warn.append("检测框贴到画面边缘(%s) ⇒ 目标被裁, 尺寸不完整, 距离反解会偏大" % "/".join(clipped))
    # 🔴 2026-10-18 老倪(只露小头时): 「有点大, 现在光模块只是露了一个小头」
    # 只剩小头时, 可见区域会把**背景的亮面/金属反光**一起圈进来(实测框宽 68px, 而真实小头只有 36px),
    # 框就被撑大。物理上能算: 模块宽 13.4mm、夹住后相机↔模块距离 159.2mm(刚性) ⇒ 画面里就该是
    # f×13.4/159.2 ≈ 32px。所以"被裁"时宽度按这个**物理宽度**收口, 不再相信可见掩膜。
    if clipped:
        _f0 = float(K[0, 0])
        w_ref_px = _f0 * float(MOD_W_MM) / float(MOD_D_REF_MM)
        _cx = (x1 + x2) / 2.0
        if (x2 - x1) > 1.25 * w_ref_px:                 # 明显比物理宽度宽 ⇒ 圈进背景了
            x1, x2 = _cx - w_ref_px / 2.0, _cx + w_ref_px / 2.0
            warn.append("被裁+框过宽(%0.0fpx > 物理 %0.0fpx) ⇒ 宽度按 13.4mm/159.2mm 收口"
                        % ((_cx + w_ref_px / 2.0) - (_cx - w_ref_px / 2.0), w_ref_px))
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
        # 被裁 = 只看得到一段 ⇒ 尺寸反解都不可靠(实测: 长轴 365mm / 宽度 77.7mm, 真值 159mm)。
        # 模块被夹爪夹住时相机↔模块是**刚性距离**, 直接用整支可见时实测的参考值。
        D = float(MOD_D_REF_MM)
        src = "刚性参考 %.1fmm(被裁, 不反解)" % D
        warn.append("目标出画被裁 ⇒ 不做尺寸反解, 距离取刚性参考 %.0fmm" % D)
    else:
        D = f * float(h_mm) / h_px
        src = "size(已知件长 %.1fmm ↔ 画面 %.0fpx)" % (h_mm, h_px)
        warn.append("无深度: 距离由已知件长反解, 误差 ~5%; 换品种要把 ZMAX_MOD_H_MM 设成真实长度")
    # ── 位置闸 ── 老倪 2026-10-18: 「光模块的位置标记错了」
    # 实测: 低置信度(0.25)时 YOLO 会跳到画面另一头的物体上(框从 [314,0,347,59] 跳到 [272,414,306,479]),
    # 尺寸闸拦不住(尺寸本身差不多)。模块是连续的 ⇒ 相邻帧中心不可能跳半屏。
    # 规则: 跳得太远 ⇒ 这一帧判失败(沿用上次框), 但**连续 5 帧都指向同一新位置**才认(允许真的重新捕获)。
    _lb = _LASTBOX.get("box2d")
    if _lb and (time.time() - float(_LASTBOX.get("t") or 0)) < 3.0:
        _c0 = ((_lb[0] + _lb[2]) / 2.0, (_lb[1] + _lb[3]) / 2.0)
        _c1 = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        _jump_px = math.hypot(_c1[0] - _c0[0], _c1[1] - _c0[1])
        _lim = max(60.0, 1.5 * math.hypot(_lb[2] - _lb[0], _lb[3] - _lb[1]))
        if _jump_px > _lim:
            _nb = _JUMP.get("box")
            if _nb and math.hypot(_c1[0] - (_nb[0] + _nb[2]) / 2.0, _c1[1] - (_nb[1] + _nb[3]) / 2.0) < 25.0:
                _JUMP["n"] = int(_JUMP.get("n") or 0) + 1
            else:
                _JUMP["box"] = [x1, y1, x2, y2]
                _JUMP["n"] = 1
            if int(_JUMP["n"]) < 5:
                _state_save({"last": _LAST, "cont": _CONT, "smo": _SMO, "lastbox": _LASTBOX, "jump": _JUMP})
                return {"ok": False,
                        "err": "位置跳变 %.0fpx > 限 %.0fpx ⇒ 判为错检, 沿用上次框(确认 %d/5)"
                               % (_jump_px, _lim, int(_JUMP["n"])), "warn": warn}
            warn.append("位置跳变 %.0fpx, 但已连续 5 帧稳定指向新位置 ⇒ 接受(重新捕获)" % _jump_px)

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
            # 🔴 2026-10-18 老倪(抬升时): 「你的光模块别扩大啊」
            # 相机装在腕上、模块被夹爪夹住 ⇒ 两者的距离是**刚性常量**, 抬臂时不该变。
            # 变化只可能来自"可见高度变多/变少"(只看到小头/整支)这种成像假象 ⇒ 限幅 3mm/s,
            # 让距离只能慢慢追随, 不会因为画面里多露一截就把框撑大。
            _dt = max(0.05, _now - _CONT["t"])
            _lim = 3.0 * _dt
            _prev = float(_CONT["d_mm"])
            D = min(max(D, _prev - _lim), _prev + _lim)
            if abs(D - _prev) >= _lim - 1e-6:
                warn.append("距离变化率被限幅(≤3mm/s): 抓着模块抬升时距离是刚性的, 不让框跟着变大/变小")
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

    _FLAT = os.environ.get("ZMAX_OBB_FLAT", "1") not in ("0", "false", "False")

    def _corners(Hv, ctr=None):
        """立方体 8 角点 (相机系 / 基座系 / 像素投影)。

        🔧 2026-10-22 老倪: 「3D 边界框方向不对, 没有与光模块的位姿保持一致」
        旧实现: 立方体建在**相机轴**上(画面横/画面竖/视线)再整体转到基座系 ⇒ 相机有俯角时,
        模块平放在台面上, 框的长轴却被抬起 (实测长轴 z 分量 0.61 ≈ 38°), 看着就是框歪了。
        新实现(_FLAT 默认开): 光模块平放 ⇒ 每个像素角点沿**自己的视线**打到同一水平面
        (z = 该框中心的 z), 上下再各加 t/2 厚度成体 ⇒ 长轴自动落在台面内, 与模块实际姿态一致。
        角点顺序保持与旧实现完全一致 (sx, sy, sz 三层嵌套), 上层绘图不用改。
        """
        c0 = c_cam if ctr is None else ctr
        cc, cb, cp = [], [], []
        if _FLAT:
            Kinv = np.linalg.inv(K)
            zb = float((Rcb @ c0 + o)[2])
            # ① 4 个像素角点沿各自视线打到**中心水平面** → 得到贴台的足印(长/短轴都落在台面内)
            foot, pix = [], []
            for sx in (-1, 1):
                for sy in (-1, 1):
                    p = c0 + ex * (sx * W / 2) + ey * (sy * Hv / 2)
                    pc = p / p[2]
                    u = K[0, 0] * pc[0] + K[0, 2]
                    v = K[1, 1] * pc[1] + K[1, 2]
                    db = Rcb @ (Kinv @ np.array([u, v, 1.0]))
                    dz = db[2] if abs(db[2]) > 1e-9 else 1e-9
                    foot.append(o + ((zb - o[2]) / dz) * db)
                    pix.append((u, v))
            # ② 斜视时"视线打到平面"会把足印拉长(实测 55mm 的模块投出 74mm) ⇒ 按**实物长轴**收口
            #    光模块长度是已知常量(MOD_H_MM), 被画幅裁切时只可能更短, 不可能更长。
            # 足印 4 点顺序 = [(-,-), (-,+), (+,-), (+,+)] ⇒ 相邻四条边里最长的那条才是**长轴**
            # (踩过: 用 (i, i+2) 配对量到的是短轴, 结果长轴 71.7mm 没被收口)
            edges = [(0, 1), (1, 3), (3, 2), (2, 0)]
            e = max(edges, key=lambda ab: np.linalg.norm(foot[ab[0]][:2] - foot[ab[1]][:2]))
            vlong = foot[e[1]] - foot[e[0]]
            Lf = float(np.linalg.norm(vlong[:2]))
            c2 = np.mean(np.array([f[:2] for f in foot]), axis=0)
            u_ax = (vlong[:2] / Lf) if Lf > 1e-6 else np.array([0.0, 1.0])
            u_perp = np.array([-u_ax[1], u_ax[0]])
            # 尺寸口径: 朝向来自视觉、尺寸来自实物(光模块是尺寸已知刚体);
            # 被画幅裁掉时"整支多长"不可观测 ⇒ 长度只取**可见那段** H, 绝不许按整支画。
            _sc = float(os.environ.get("ZMAX_OBB_SCALE", "0.94"))
            half_l = min(Lf, float(H), float(h_mm)) * _sc / 2.0
            half_w = float(MOD_W_MM) * _sc / 2.0
            foot = []
            for (sx, sy) in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                p2 = c2 + u_ax * (sy * half_l) + u_perp * (sx * half_w)
                foot.append(np.array([p2[0], p2[1], zb]))
            # ③ 竖直挤出 t/2 ⇒ 厚度边严格竖直, 长/短轴严格水平
            for i, (sx, sy) in enumerate([(-1, -1), (-1, 1), (1, -1), (1, 1)]):
                for sz in (-1, 1):
                    p_b = foot[i] + np.array([0.0, 0.0, sz * float(t_mm) / 2])
                    cb.append(p_b)
                    cc.append(Rcb.T @ (p_b - o))
                    cp.append([pix[i][0], pix[i][1]])
            # 角点顺序映射回旧嵌套 (sx, sy, sz)
            order = [0, 1, 2, 3]   # 已按 (sx,sy) 排列, 每个占两位(sz-/+)
            cb2 = [cb[0], cb[1], cb[2], cb[3], cb[4], cb[5], cb[6], cb[7]]
            return cc, cb2, cp
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    p = c0 + ex * (sx * W / 2) + ey * (sy * Hv / 2) + ez * (sz * float(t_mm) / 2)
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

    # ── 输出平滑 ── 老倪 2026-10-18: 「别突然变化，记住了」
    # 连续性闸只管"明显算错"的帧; 真实的抖动(检测框 1~2px)仍会让框小幅跳。
    # 这里对**画出去的中心和高度**做指数平滑(默认 0.55 新值), 让框看上去是连续的移动。
    # 注意: 平滑只作用于显示用的中心/尺寸, 不影响 dist_mm 与 tool1 关系的统计口径。
    smooth_applied = False
    _t2 = time.time()
    if _SMO["c"] is not None and (_t2 - _SMO["t"]) < 1.5:
        _a = float(os.environ.get("ZMAX_MOD_SMOOTH", "0.55"))
        c_s = _a * center_base + (1.0 - _a) * np.array(_SMO["c"])
        H_s = _a * H + (1.0 - _a) * float(_SMO["H"])
        c_cam_s = Rcb.T @ (c_s - o)
        corners_cam, corners_base, corners_px = _corners(H_s, c_cam_s)
        center_base, H, smooth_applied = c_s, H_s, True
    # 🔴 老倪 2026-10-18「标注框不要变长」:
    # 自洽迭代/斜视投影/平滑 都可能把框在竖向撑长(现场看到"框比物体长一截")。
    # 最后上一道**硬夹**: 画出去的竖向跨度不许超过检测框(1.02 容差), 超了按比例把 H 收回。
    try:
        _ys = [q[1] for q in corners_px]
        _span = max(_ys) - min(_ys)
        if h_px >= 3 and _span > float(h_px) * 1.02:
            H *= (float(h_px) * 1.02) / _span
            _ctr = c_cam_s if smooth_applied else None
            corners_cam, corners_base, corners_px = _corners(H, _ctr)
            center_base = Rcb @ (c_cam_s if smooth_applied else c_cam) + o
            warn.append("框竖向被夹回可见高度 %.0f→%.0fpx" % (_span, float(h_px) * 1.02))
    except Exception:                                                       # noqa: BLE001
        pass
    if det_src == "yolo":
        _LASTBOX.update(box2d=[float(x1), float(y1), float(x2), float(y2)], t=time.time())
    try:                                     # 存"上一次成功的框内图像"当模板(模板匹配的素材)
        import cv2 as _cv2
        _px1, _py1 = int(max(0, x1)), int(max(0, y1))
        _px2, _py2 = int(min(img_bgr.shape[1], x2)), int(min(img_bgr.shape[0], y2))
        if det_src == "yolo" and _px2 - _px1 >= 8 and _py2 - _py1 >= 8:
            # 🔴 只有 YOLO 检出的框才配当模板。用模板自己的结果再存模板 = 自锁(实测错框被 1.00 相似度锁死)
            _cv2.imwrite(_PATCH_F, _cv2.cvtColor(img_bgr[_py1:_py2, _px1:_px2], _cv2.COLOR_BGR2GRAY))
    except Exception:                                                       # noqa: BLE001
        pass
    _SMO.update(c=[float(v) for v in center_base], H=float(H), t=_t2)
    _state_save({"last": _LAST, "cont": _CONT, "smo": _SMO, "lastbox": _LASTBOX, "jump": _JUMP})

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
        "det_src": det_src,
        "continuity": {"jump": jump, "smoothed": bool(fresh and not jump), "display_smooth": smooth_applied},
        "warn": warn,
    }


# 立方体 12 条棱 (角点顺序 = sx,sy,sz 三重循环)
EDGES = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
