#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🦾 D405 直连相机 → HTTP JPEG（不经 ROS / DDS）

为什么改 (2026-10-26 老倪: 「视觉延迟太大了」):
  旧链路 = d405_color_pub(ROS bgr8 921KB/帧 @30fps ≈ 27MB/s) → DDS 组播 → rs_fast_node 订阅再编码
  实测后果:
    · 图像流把 WiFi 打满, DDS 报 "sequence size exceeds remaining buffer"
    · rs_fast_node 只收到 25 帧后彻底停 ⇒ 页面上臂相机是一张**冻结的旧图**
    · 单独用 cv2 测同一台相机 = 29.5fps(640x480) —— 证明相机与 USB2 带宽都没问题, 堵在 ROS/DDS 中转
  现在: 进程内 cv2 直读相机 → JPEG → HTTP。少一次跨进程 27MB/s 放大, 少一次 DDS 序列化,
        Orin CPU / WiFi 带宽一起省下来, 位姿与指令的延迟跟着降。

端点 (与旧版完全一致, 上层不用改):
  /frame.jpg  最新一帧 JPEG
  /            {"n":累计帧, "age_s":最后一帧龄, "fps":实测帧率, "enc":"direct", "err":...}
"""
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

W, H = 640, 480
GAIN = int(os.environ.get("D405_GAIN", "240"))
IDX = int(os.environ.get("D405_IDX", "-1"))      # -1 = 自动探测彩色节点 (重启后 /dev/videoN 编号会变)
FPS_REQ = int(os.environ.get("D405_FPS", "30"))
QUALITY = int(os.environ.get("D405_QUALITY", "80"))

S = {"jpg": None, "ts": 0.0, "n": 0, "err": "", "enc": "direct", "fps": 0.0}
_ROS_STARTED = {"v": False}          # ROS 回退线程是否已起 (起了就不再抢设备节点)


def _open_ok(i):
    """试开一个 /dev/videoN: 必须能按 YUYV 640x480 真读到一帧才算可用 (深度/红外/metadata 节点读不出)。"""
    c = cv2.VideoCapture(i, cv2.CAP_V4L2)
    if not c.isOpened():
        c.release()
        return None
    c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
    c.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    c.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    c.set(cv2.CAP_PROP_FPS, FPS_REQ)
    try:
        c.set(cv2.CAP_PROP_GAIN, GAIN)
    except Exception:                                            # noqa: BLE001
        pass
    c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(5):
        ok, fr = c.read()
        if ok and fr is not None and fr.size:
            return c
        time.sleep(0.15)
    c.release()
    return None


def _open_color():
    """D405 一台给 6 个 /dev/videoN, 只有彩色那个能读 YUYV ⇒ 逐个试, 谁真出帧用谁。"""
    order = ([IDX] if IDX >= 0 else []) + [i for i in range(8) if i != IDX]
    for i in order:
        c = _open_ok(i)
        if c is not None:
            S["err"] = ""
            print("[rs_fast_node] 相机 /dev/video%d 已开 %dx%d gain=%d" % (i, W, H, GAIN), flush=True)
            return c
    S["err"] = "没有可用的彩色节点 (/dev/video0-7 都读不出 YUYV)"
    return None


def _ros_fallback():
    """设备节点全被别的进程占着(librealsense / 彩色发布器) 时退到 ROS 彩色话题。

    为什么必须有: D405 一台相机只允许**一个**进程占 UVC 彩色节点; Orin 上
    d405_color_pub.py 先起来会把 /dev/videoN 占住 ⇒ 直读必 EBUSY(实测 errno 16)。
    AR 底图不能因为这个就全黑 ⇒ 再退一步订阅它已经发好的 /realsense/color/image_raw。
    """
    if _ROS_STARTED["v"]:
        return
    _ROS_STARTED["v"] = True
    print("[rs_fast_node] 设备节点被占用, 退到 ROS 彩色话题", flush=True)

    def _run():
        import sys as _s
        for _p in ("/opt/ros/humble/local/lib/python3.10/dist-packages",
                   "/opt/ros/humble/lib/python3.10/site-packages"):
            if os.path.isdir(_p) and _p not in _s.path:
                _s.path.append(_p)
        os.environ.setdefault("ROS_DOMAIN_ID", "0")
        try:
            import rclpy
            from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
            from sensor_msgs.msg import Image as _Img
        except Exception as _e:                                       # noqa: BLE001
            S["err"] = "ROS 回退不可用: %s" % _e
            _ROS_STARTED["v"] = False
            return
        try:
            rclpy.init(args=None)
            n = rclpy.create_node("rs_fast_node_jpeg_fb")
            q = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                           history=HistoryPolicy.KEEP_LAST)

            def cb(msg):
                try:
                    fr = np.frombuffer(bytes(msg.data), dtype=np.uint8).reshape(
                        msg.height, msg.width, -1)
                    if fr.shape[2] == 4:
                        fr = fr[:, :, :3]
                    if str(msg.encoding).lower().startswith("rgb"):
                        fr = fr[:, :, ::-1]
                    fr = np.ascontiguousarray(fr)
                    ok, b = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
                    if not ok:
                        return
                    now = time.time()
                    if S["ts"]:
                        inst = 1.0 / max(1e-3, now - S["ts"])
                        S["fps"] = inst if S["fps"] == 0 else S["fps"] * 0.9 + inst * 0.1
                    S["jpg"] = b.tobytes()
                    S["ts"] = now
                    S["n"] += 1
                    S["err"] = ""
                    S["enc"] = "ros"
                except Exception as _e:                              # noqa: BLE001
                    S["err"] = "ros cb: %s" % _e

            n.create_subscription(_Img, "/realsense/color/image_raw", cb, q)
            rclpy.spin(n)
        except Exception as _e:                                       # noqa: BLE001
            S["err"] = "ROS 回退失败: %s" % _e
            _ROS_STARTED["v"] = False

    threading.Thread(target=_run, name="rosfb", daemon=True).start()


def worker():
    cap = None
    while True:
        if cap is None:
            if _ROS_STARTED["v"]:            # 走 ROS 回退时别再去抢设备 (每轮 8 次探测会卡住循环)
                time.sleep(0.5)
                continue
            cap = _open_color()
            if cap is None:
                _ros_fallback()
                time.sleep(1.0)
                continue

        ok, fr = cap.read()
        if not ok or fr is None or not fr.size:
            S["err"] = "取帧失败, 重开"
            cap.release()
            cap = None
            time.sleep(0.3)
            continue

        ok, b = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
        if not ok:
            S["err"] = "imencode 失败"
            continue
        now = time.time()
        if S["ts"]:
            inst = 1.0 / max(1e-3, now - S["ts"])
            S["fps"] = inst if S["fps"] == 0 else S["fps"] * 0.9 + inst * 0.1
        S["jpg"] = b.tobytes()
        S["ts"] = now
        S["n"] += 1
        S["err"] = ""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/frame"):
            j = S["jpg"]
            if j is None:
                body = ("no frame yet n=%d err=%s" % (S["n"], S["err"])).encode()
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(j)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(j)
        else:
            s = '{"n":%d,"age_s":%.2f,"fps":%.1f,"enc":"direct","err":"%s"}\n' % (
                S["n"], (time.time() - S["ts"]) if S["ts"] else -1.0, S["fps"], S["err"])
            b = s.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    def log_message(self, *a):
        pass


def main():
    threading.Thread(target=worker, name="cam", daemon=True).start()
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", 8792), H).serve_forever(),
                     name="http", daemon=True).start()
    print("[rs_fast_node] :8792 ready (直连相机, 不经 ROS)", flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
