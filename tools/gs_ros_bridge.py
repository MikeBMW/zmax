#!/usr/bin/env python3
"""Intel 本地 ROS2 → HTTP 桥 (给 gs_autocap_daemon 用)

为什么需要: 采集守护原来指 http://192.168.23.66:8792/frame.jpg + http://192.168.23.50:8804/pose,
这两个端点一个绑在 Orin 的 127.0.0.1、一个在工位机(不在产线网段时整台不可达) ⇒ Intel 侧一条都拉不到。
Intel 本机 ROS2 域里其实两样都有: /realsense/color/image_raw (bgr8 640x480) + /robot/tcp_pose (base_link)。

契约与 8804 保持逐字段一致:
  GET /frame.jpg  → JPEG 字节
  GET /pose       → {ts,t,x,y,z,rx,ry,rz,qx,qy,qz,qw,frame,age_s,stale}   (rpy = ZYX 欧拉, 与 rokae endInRef 同口径)
  GET /health     → {ok,img_age_s,pose_age_s,wh,enc,brightness,fps}
"""
import io
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image

PORT = int(os.environ.get("GS_BRIDGE_PORT", "8811"))
BIND = os.environ.get("GS_BRIDGE_BIND", "127.0.0.1")
STALE_S = float(os.environ.get("GS_BRIDGE_STALE_S", "3.0"))   # 超过这么久没新帧 ⇒ stale
JPEG_Q = int(os.environ.get("GS_BRIDGE_JPEG_Q", "92"))

LOCK = threading.Lock()
IMG = {"jpg": b"", "mono": 0.0, "wh": None, "enc": None, "bright": None}
POSE = {"d": {}, "mono": 0.0}
FPS = {"n": 0, "t0": time.monotonic(), "rate": 0.0}


def quat_to_rpy_zzy(qx, qy, qz, qw):
    """四元数 → ZYX 欧拉 (roll,pitch,yaw), 与 rokae endInRef 的 rx/ry/rz 同口径"""
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    roll = math.atan2(2 * (qw * qx + qy * qz), 1 - 2 * (qx * qx + qy * qy))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (qw * qy - qz * qx))))
    yaw = math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz))
    return roll, pitch, yaw


class Bridge(Node):
    def __init__(self):
        super().__init__("gs_ros_bridge")
        q = QoSProfile(depth=2, reliability=ReliabilityPolicy.BEST_EFFORT)   # 两个话题都是 BEST_EFFORT
        self.create_subscription(Image, os.environ.get("GS_IMG_TOPIC", "/realsense/color/image_raw"), self.on_img, q)
        self.create_subscription(PoseStamped, os.environ.get("GS_POSE_TOPIC", "/robot/tcp_pose"), self.on_pose, q)

    def on_img(self, m):
        try:
            a = np.frombuffer(bytes(m.data), dtype=np.uint8)
            if m.encoding in ("bgr8", "rgb8"):
                a = a.reshape(m.height, m.width, 3)
                bgr = a if m.encoding == "bgr8" else a[..., ::-1]
            elif m.encoding in ("mono8", "8UC1"):
                bgr = np.stack([a.reshape(m.height, m.width)] * 3, -1)
            else:
                a = a.reshape(m.height, m.width, -1)[..., :3]
                bgr = a if m.encoding.startswith("bgr") else a[..., ::-1]
            import cv2
            ok, buf = cv2.imencode(".jpg", np.ascontiguousarray(bgr), [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_Q])
            if not ok:
                return
            bright = float(bgr.mean())
            with LOCK:
                IMG.update(jpg=buf.tobytes(), mono=time.monotonic(), wh=[m.width, m.height],
                           enc=m.encoding, bright=round(bright, 2))
                FPS["n"] += 1
                el = time.monotonic() - FPS["t0"]
                if el >= 5.0:
                    FPS["rate"] = round(FPS["n"] / el, 2)
                    FPS["n"], FPS["t0"] = 0, time.monotonic()
        except Exception as e:            # 单帧坏掉不许把节点带死
            self.get_logger().warn("img decode err: %r" % (e,))

    def on_pose(self, m):
        p, o = m.pose.position, m.pose.orientation
        rx, ry, rz = quat_to_rpy_zzy(o.x, o.y, o.z, o.w)
        ts = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        with LOCK:
            POSE["d"] = {"ts": ts, "t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + (".%03d" % int((ts % 1) * 1000)),
                         "x": p.x, "y": p.y, "z": p.z, "rx": rx, "ry": ry, "rz": rz,
                         "qx": o.x, "qy": o.y, "qz": o.z, "qw": o.w,
                         "frame": m.header.frame_id or "base_link"}
            POSE["mono"] = time.monotonic()


class H(BaseHTTPRequestHandler):
    # 保持 HTTP/1.0 语义(每次响应即关连接): urllib 拉图偶发 keep-alive 挂住, 采集循环不能被一条连接拖死
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/frame.jpg", "/frame"):
            with LOCK:
                jpg, mono = IMG["jpg"], IMG["mono"]
            age = time.monotonic() - mono if mono else 1e9
            if not jpg or age > STALE_S:
                return self._send(503, json.dumps({"err": "no fresh frame", "age_s": round(age, 2)}))
            return self._send(200, jpg, "image/jpeg", {"X-Frame-Age": round(age, 3)})
        if path == "/pose":
            with LOCK:
                d, mono = dict(POSE["d"]), POSE["mono"]
            age = time.monotonic() - mono if mono else 1e9
            if not d:
                return self._send(503, json.dumps({"err": "no pose yet"}))
            d["age_s"] = round(age, 3)
            d["stale"] = bool(age > STALE_S)
            d["age_src"] = "ros2:/robot/tcp_pose(mono)"
            return self._send(200, json.dumps(d))
        if path == "/health":
            now = time.monotonic()
            with LOCK:
                img_age = round(now - IMG["mono"], 2) if IMG["mono"] else None
                pose_age = round(now - POSE["mono"], 2) if POSE["mono"] else None
                out = {"ok": bool(IMG["jpg"]) and bool(POSE["d"]), "port": PORT,
                       "img_age_s": img_age, "pose_age_s": pose_age,
                       "wh": IMG["wh"], "enc": IMG["enc"], "brightness": IMG["bright"], "fps": FPS["rate"],
                       "stale_after_s": STALE_S}
            return self._send(200, json.dumps(out))
        return self._send(404, json.dumps({"err": "not found", "paths": ["/frame.jpg", "/pose", "/health"]}))


def main():
    rclpy.init()
    node = Bridge()
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    srv = ThreadingHTTPServer((BIND, PORT), H)
    print("gs_ros_bridge on %s:%d  img=%s pose=%s" % (
        BIND, PORT, os.environ.get("GS_IMG_TOPIC", "/realsense/color/image_raw"),
        os.environ.get("GS_POSE_TOPIC", "/robot/tcp_pose")), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
