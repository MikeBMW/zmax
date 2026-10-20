#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rs_probe.py — D435 取帧能力探针 (只读, 用于判定 -71 到底是"设备卡死"还是"带宽/端口")

用法 (必须独占设备: 先停 AR 服务, 否则 EBUSY):
  ./gui-venv311/bin/python /tmp/rs_probe.py                # 640x480@30 深度+彩色, 5s
  ./gui-venv311/bin/python /tmp/rs_probe.py --fps 15       # 降带宽再试
  ./gui-venv311/bin/python /tmp/rs_probe.py --reset        # 先 hardware_reset 再开
"""
import argparse
import time

import pyrealsense2 as rs


def try_open(w, h, fps, secs=5.0):
    ctx = rs.context()
    devs = list(ctx.query_devices())
    print("设备 %d 台: %s" % (len(devs), [d.get_info(rs.camera_info.name) for d in devs]))
    if not devs:
        return {"ok": False, "err": "没有 RealSense 设备"}
    cfg = rs.config()
    cfg.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps)
    cfg.enable_stream(rs.stream.color, w, h, rs.format.bgr8, fps)
    pipe = rs.pipeline()
    t0 = time.time()
    try:
        prof = pipe.start(cfg)
    except Exception as e:
        return {"ok": False, "err": "start 失败 %s: %s" % (type(e).__name__, str(e)[:160]),
                "ms": round((time.time() - t0) * 1000)}
    ms_start = (time.time() - t0) * 1000
    n = 0
    first = None
    t1 = time.time()
    err = None
    while time.time() - t1 < secs:
        try:
            fs = pipe.wait_for_frames(timeout_ms=2000)
            c, d = fs.get_color_frame(), fs.get_depth_frame()
            if c and d:
                n += 1
                if first is None:
                    first = round((time.time() - t1) * 1000)
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:120])
            break
    try:
        pipe.stop()
    except Exception:
        pass
    el = time.time() - t1
    return {"ok": n > 0, "fps": round(n / el, 2) if el > 0 else 0, "frames": n,
            "start_ms": round(ms_start), "first_frame_ms": first, "err": err,
            "w": w, "h": h, "fps_cfg": fps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    if a.reset:
        ctx = rs.context()
        for d in ctx.query_devices():
            try:
                d.hardware_reset()
                print("hardware_reset →", d.get_info(rs.camera_info.name))
            except Exception as e:
                print("reset 失败:", e)
        time.sleep(4.0)
    print(try_open(a.w, a.h, a.fps, a.secs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
