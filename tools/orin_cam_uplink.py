#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_cam_uplink.py — 把产线侧相机帧推到 ECS 中转 (远程看机器人画面的唯一通道)

背景（2026-10-25 老倪远程）: 产线相机(臂上 D405 / 中央相机)在厂内网段, 本机远程时**没有产线网卡**,
直连不到。Orin 有公网出口 (orin_uplink.py 已经在往 datadrive.world 推遥测), 所以让 **Orin 侧推帧**:
    Orin → POST /api/relay/cam/push?cam=arm      (臂上 D405)
    Orin → POST /api/relay/cam/push?cam=central  (中央/顶视相机)
本机/网页读:
    GET https://datadrive.world/api/snapshot/arm
    GET https://datadrive.world/api/snapshot/central

红线: **只读**。只 HTTP GET 取帧 + HTTP POST 上传, 不碰 ROS/不调 service/不发 topic。
用法 (在 Orin 上):
    python3 orin_cam_uplink.py --once            # 推一帧自检
    python3 orin_cam_uplink.py --watch --fps 2   # 常驻
"""
from __future__ import annotations

import argparse
import os
import time
import urllib.request

PUSH = os.environ.get("ZMAX_CAM_PUSH", "https://datadrive.world/api/relay/cam/push")
UA = {"User-Agent": "zmax-orin-cam-uplink/1.0"}


def _get(url: str, timeout: float = 3.0) -> bytes | None:
    """只读取一帧 (http 快照 / MJPEG 的单帧也算)。"""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            b = r.read()
        return b if b and len(b) > 2000 and b[:2] == b"\xff\xd8" else None
    except Exception:                                                        # noqa: BLE001
        return None


def _push(cam: str, jpg: bytes, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(f"{PUSH}?cam={cam}", data=jpg, method="POST",
                                     headers={**UA, "Content-Type": "image/jpeg"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception as e:                                                   # noqa: BLE001
        print(f"  !! push {cam} 失败: {type(e).__name__} {e}", flush=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm-url", default=os.environ.get("ZMAX_ARM_SRC", "http://127.0.0.1:8792/frame.jpg"),
                    help="臂上 D405 取帧地址 (Orin 本机 rs_fast_node)")
    ap.add_argument("--central-url", default=os.environ.get("ZMAX_CENTRAL_SRC", ""),
                    help="中央/顶视相机取帧地址 (http 快照或 MJPEG; 空=不推这路)")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    cams = [("arm", a.arm_url)] + ([("central", a.central_url)] if a.central_url else [])
    period = 1.0 / max(0.2, a.fps)
    sent = {k: 0 for k, _ in cams}
    last_log = 0.0
    while True:
        t0 = time.time()
        for cam, url in cams:
            jpg = _get(url) if url else None
            if jpg and _push(cam, jpg):
                sent[cam] += 1
        if a.once:
            print("  自检结果:", ", ".join(f"{k}={v}帧" for k, v in sent.items()), flush=True)
            return 0 if all(sent.values()) else 1
        if time.time() - last_log > 30:
            last_log = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] 已推 " +
                  ", ".join(f"{k}:{v}" for k, v in sent.items()), flush=True)
        time.sleep(max(0.0, period - (time.time() - t0)))


if __name__ == "__main__":
    raise SystemExit(main())
