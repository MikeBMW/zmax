#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""realsense_probe.py — 本机 RealSense D435 自检 (2026-10-11 老倪新接的 AR 相机)

只读自检: 设备/序列号/固件 · 彩色+深度各抓一帧落盘 · 内参/深度标尺/帧率/像素统计。
用法: gui-venv311/bin/python tools/realsense_probe.py [--out DIR] [--secs N]
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

OUT = os.path.expanduser("~/zmax/zmax_data/ar_rs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--secs", type=float, default=3.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    import pyrealsense2 as rs
    ctx = rs.context()
    devs = list(ctx.devices)
    print("设备数: %d" % len(devs))
    for d in devs:
        print("  %s sn=%s fw=%s usb=%s" % (d.get_info(rs.camera_info.name),
                                           d.get_info(rs.camera_info.serial_number),
                                           d.get_info(rs.camera_info.firmware_version),
                                           d.get_info(rs.camera_info.usb_type_descriptor)))
    if not devs:
        raise SystemExit("没有 RealSense 设备")
    pipe = rs.pipeline()
    cfg = rs.config()
    cfg.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    prof = pipe.start(cfg)
    try:
        # 让自动曝光收敛
        t0 = time.time()
        n = 0
        while time.time() - t0 < a.secs:
            pipe.wait_for_frames(timeout_ms=3000)
            n += 1
        frames = pipe.wait_for_frames(timeout_ms=5000)
        color = np.asanyarray(frames.get_color_frame().get_data())
        depth = np.asanyarray(frames.get_depth_frame().get_data())
        ci = frames.get_color_frame().get_profile().as_video_stream_profile().get_intrinsics()
        di = frames.get_depth_frame().get_profile().as_video_stream_profile().get_intrinsics()
        scale = prof.get_device().first_depth_sensor().get_depth_scale()
        dc = 0.0
        try:                                       # 深度→彩色外参 (D435 出厂标定值)
            dc = frames.get_depth_frame().get_profile().get_extrinsics_to(
                frames.get_color_frame().get_profile())
        except Exception:                                                       # noqa: BLE001
            dc = None
        import cv2
        cp = os.path.join(a.out, "color.png")
        dp = os.path.join(a.out, "depth.png")
        cv2.imwrite(cp, color)
        cv2.imwrite(dp, depth)
        dmm = depth.astype(np.float32) * scale * 1000.0
        valid = dmm[dmm > 0]
        info = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "frames_drained": n,
            "color_png": cp, "depth_png": dp,
            "color_shape": list(color.shape), "mean_bgr": [round(float(x), 1) for x in color.reshape(-1, 3).mean(0)],
            "depth_shape": list(depth.shape), "depth_scale_m": scale,
            "depth_valid_ratio": round(float((dmm > 0).mean()), 4),
            "depth_min_mm": round(float(valid.min()), 1) if valid.size else None,
            "depth_median_mm": round(float(np.median(valid)), 1) if valid.size else None,
            "depth_max_mm": round(float(valid.max()), 1) if valid.size else None,
            "color_intrinsics": {"fx": ci.fx, "fy": ci.fy, "ppx": ci.ppx, "ppy": ci.ppy,
                                 "w": ci.width, "h": ci.height, "model": str(ci.model),
                                 "coeffs": list(ci.coeffs)},
            "depth_intrinsics": {"fx": di.fx, "fy": di.fy, "ppx": di.ppx, "ppy": di.ppy,
                                 "w": di.width, "h": di.height},
            "depth_to_color_extrinsics": (None if dc is None else
                                          {"rotation": list(dc.rotation), "translation": list(dc.translation)}),
        }
        jp = os.path.join(a.out, "probe.json")
        json.dump(info, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps({k: v for k, v in info.items() if k not in ("depth_to_color_extrinsics",)}, ensure_ascii=False, indent=1))
        print("落盘: %s / %s / %s" % (cp, dp, jp))
    finally:
        pipe.stop()


if __name__ == "__main__":
    main()
