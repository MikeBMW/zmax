#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""realsense_source.py — 本机 Intel RealSense D435 取帧源 (AR 底图 + 深度)

老倪 2026-10-11: 「我现在已经给你连上了 realsense相机, 你自己装驱动…把 3D场景的力控改成 AR…
把产品大屏的所有数据(金手指 AOI 点位/空间点位/臂相机/以前记录的点位)叠加到真实场景中」

单一职责: 单例管理 pipeline(彩色 640x480 BGR + 深度 z16 1mm), 后台线程持续取帧;
对外 latest()/snap()/depth()/intrinsics()/deproject()/mjpeg()/info()。
- 只走 Python API(pyrealsense2): 深度 + **出厂内参** 都在, v4l2 那路没有。
- 取帧失败自动重启 pipeline; latest() 带 age_s, **绝不拿旧帧冒充实时**。
"""
from __future__ import annotations

import json
import threading
import time

import numpy as np

W, H, FPS = 640, 480, 30
_LK = threading.Lock()
_ST = {"color": None, "depth": None, "ts": 0.0, "n": 0, "ci": None, "scale": 0.001,
       "err": "", "started": 0.0, "restarts": 0}


class _RS:
    def __init__(self):
        self.pipe = None
        self.running = False
        self.th = None

    def start(self):
        import pyrealsense2 as rs
        if self.running:
            return True
        try:
            cfg = rs.config()
            cfg.enable_stream(rs.stream.depth, W, H, rs.format.z16, FPS)
            cfg.enable_stream(rs.stream.color, W, H, rs.format.bgr8, FPS)
            self.pipe = rs.pipeline()
            prof = self.pipe.start(cfg)
            ci = prof.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
            sc = float(prof.get_device().first_depth_sensor().get_depth_scale())
            with _LK:
                _ST["ci"] = {"fx": float(ci.fx), "fy": float(ci.fy), "ppx": float(ci.ppx),
                             "ppy": float(ci.ppy), "w": int(ci.width), "h": int(ci.height)}
                _ST["scale"] = sc
                _ST["err"] = ""
                _ST["started"] = time.time()
                _ST["restarts"] += 1
            self.running = True
            self.th = threading.Thread(target=self._loop, daemon=True)
            self.th.start()
            return True
        except Exception as e:                                                   # noqa: BLE001
            with _LK:
                _ST["err"] = "启动失败 %s: %s" % (type(e).__name__, str(e)[:140])
            self.running = False
            return False

    def _loop(self):
        while self.running:
            try:
                fs = self.pipe.wait_for_frames(timeout_ms=2000)
                c, d = fs.get_color_frame(), fs.get_depth_frame()
                if not c or not d:
                    continue
                col, dep = np.asanyarray(c.get_data()), np.asanyarray(d.get_data())
                with _LK:
                    _ST["color"] = col
                    _ST["depth"] = dep
                    _ST["ts"] = time.time()
                    _ST["n"] += 1
            except Exception as e:                                               # noqa: BLE001
                with _LK:
                    _ST["err"] = "取帧 %s: %s" % (type(e).__name__, str(e)[:120])
                time.sleep(0.4)
                try:
                    self.pipe.stop()
                except Exception:                                                # noqa: BLE001
                    pass
                self.running = False
                time.sleep(1.0)
                self.start()

    def stop(self):
        self.running = False
        try:
            if self.pipe:
                self.pipe.stop()
        except Exception:                                                        # noqa: BLE001
            pass


_RS_OBJ = None
_RS_LK = threading.Lock()


def ensure():
    """确保 pipeline 在跑(幂等)。返回 _ST。"""
    global _RS_OBJ
    with _RS_LK:
        if _RS_OBJ is None:
            _RS_OBJ = _RS()
        if not _RS_OBJ.running:
            _RS_OBJ.start()
    return _ST


def latest():
    """最新帧: {"color","depth","age_s","n","err",...}; color 为 None 表示还没拿到真帧。"""
    ensure()
    with _LK:
        out = {"color": None if _ST["color"] is None else _ST["color"].copy(),
               "depth": None if _ST["depth"] is None else _ST["depth"].copy(),
               "age_s": (round(time.time() - _ST["ts"], 3) if _ST["ts"] else None),
               "n": _ST["n"], "err": _ST["err"], "ci": _ST["ci"], "scale": _ST["scale"]}
    return out


def snap():
    return latest()["color"]


def depth():
    return latest()["depth"]


def intrinsics():
    ensure()
    with _LK:
        return dict(_ST["ci"] or {})


def info():
    L = latest()
    d = L["depth"]
    ci = L["ci"] or {}
    dep = {}
    if d is not None:
        mm = d.astype(np.float32) * float(_ST["scale"]) * 1000.0
        v = mm[mm > 0]
        dep = {"valid_ratio": round(float((mm > 0).mean()), 4),
               "min_mm": (round(float(v.min()), 1) if v.size else None),
               "median_mm": (round(float(np.median(v)), 1) if v.size else None),
               "max_mm": (round(float(v.max()), 1) if v.size else None)}
    return {"ok": L["color"] is not None, "w": ci.get("w"), "h": ci.get("h"),
            "fx": ci.get("fx"), "fy": ci.get("fy"), "ppx": ci.get("ppx"), "ppy": ci.get("ppy"),
            "depth_scale_m": _ST["scale"], "frames": L["n"], "age_s": L["age_s"],
            "depth": dep, "err": L["err"]}


def deproject(u, v, patch=2):
    """像素 → 相机系 3D(m): 取 (u,v) 邻域深度中位, 按出厂内参反投影。返回 dict 或 {"ok":False}。"""
    L = latest()
    d, ci = L["depth"], L["ci"]
    if d is None or not ci:
        return {"ok": False, "err": "无深度/内参"}
    u0, v0 = int(round(u)), int(round(v))
    if not (0 <= u0 < d.shape[1] and 0 <= v0 < d.shape[0]):
        return {"ok": False, "err": "像素越界"}
    y0, y1 = max(0, v0 - patch), min(d.shape[0], v0 + patch + 1)
    x0, x1 = max(0, u0 - patch), min(d.shape[1], u0 + patch + 1)
    win = d[y0:y1, x0:x1].astype(np.float32) * float(_ST["scale"])
    w = win[win > 0]
    if not w.size:
        return {"ok": False, "err": "该点无有效深度"}
    z = float(np.median(w))
    x = (float(u) - ci["ppx"]) / ci["fx"] * z
    y = (float(v) - ci["ppy"]) / ci["fy"] * z
    return {"ok": True, "u": float(u), "v": float(v), "xyz_m": [x, y, z], "z_m": z,
            "win_valid": int(w.size), "win_px": int(win.size), "age_s": L["age_s"]}


def mjpeg(fps=15, quality=75):
    """MJPEG multipart 生成器(给 HTTP 流用)。"""
    import cv2
    dt = 1.0 / max(1, fps)
    while True:
        t0 = time.time()
        L = latest()
        if L["color"] is not None:
            ok, buf = cv2.imencode(".jpg", L["color"], [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(buf)
                       + buf.tobytes() + b"\r\n")
        time.sleep(max(0.0, dt - (time.time() - t0)))


if __name__ == "__main__":
    ensure()
    time.sleep(2.0)
    print(json.dumps(info(), ensure_ascii=False, indent=1))
    print(json.dumps(deproject(W / 2.0, H / 2.0), ensure_ascii=False))
