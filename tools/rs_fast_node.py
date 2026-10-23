#!/usr/bin/env python3
"""Z-MAX Orin D405 快速转发节点 —— 彩色 JPEG + 深度 16 位 PNG + 内参。

端点:
  GET /frame.jpg     彩色 JPEG (原逻辑, 保持不变)
  GET /depth.png     深度 16 位 PNG (无偏色, 无损; unit=0.1mm, 0=无效)
  GET /depth.raw     深度原始 uint16 小端裸数据 (307200 字节, 给训练端直读)
  GET /intrinsics    真内参 JSON (来自 camera_info, 不猜)
  GET /             状态 JSON (帧号 / 帧龄 / 编码 / 错误)

深度是 3DGS 精确初始化点云的唯一可靠来源; 早先训练只有猜出来的盒子,
PSNR 卡在 14~15 上不去。内参同样以 camera_info 为准。
"""
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CameraInfo, Image
from http.server import BaseHTTPRequestHandler, HTTPServer

S = {"jpg": None, "ts": 0.0, "n": 0, "err": "", "enc": "",
     "d_png": None, "d_raw": None, "d_ts": 0.0, "d_n": 0, "d_err": "",
     "d_shape": (0, 0), "d_valid_ratio": 0.0,
     "K": None, "K_ts": 0.0, "frame_id": ""}

_DEPTH_UNIT_M = 0.0001      # D405: 1 单位 = 0.1mm


def cb_color(msg):
    try:
        S["enc"] = getattr(msg, "encoding", "")
        h, w = int(msg.height), int(msg.width)
        buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
        e = S["enc"]
        if e in ("bgr8", "8UC3"):
            a = buf.reshape(h, w, 3)
        elif e == "rgb8":
            a = buf.reshape(h, w, 3)[:, :, ::-1]
        elif e in ("bgra8",):
            a = buf.reshape(h, w, 4)[:, :, :3]
        elif e in ("mono8", "8UC1"):
            a = cv2.cvtColor(buf.reshape(h, w), cv2.COLOR_GRAY2BGR)
        else:
            a = buf[:h * w].reshape(h, w)
            a = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
        ok, b = cv2.imencode(".jpg", np.ascontiguousarray(a), [cv2.IMWRITE_JPEG_QUALITY, 78])
        if ok:
            S["jpg"] = b.tobytes()
            S["ts"] = time.time()
            S["n"] += 1
        else:
            S["err"] = "imencode false"
    except Exception as ex:
        S["err"] = repr(ex)[:120]
        print("cb_color err", S["err"], flush=True)


def cb_depth(msg):
    try:
        h, w = int(msg.height), int(msg.width)
        buf = np.frombuffer(bytes(msg.data), dtype=np.uint16)
        if buf.size != h * w:
            S["d_err"] = "深度尺寸不符 %d != %d" % (buf.size, h * w)
            return
        d = buf.reshape(h, w)
        # PNG 16 位无损; raw 给训练端直读省一次解码
        ok, png = cv2.imencode(".png", d)
        if ok:
            S["d_png"] = png.tobytes()
            S["d_raw"] = d.tobytes()
            S["d_ts"] = time.time()
            S["d_n"] += 1
            S["d_shape"] = (w, h)
            valid = int((d > 0).sum())
            S["d_valid_ratio"] = round(valid / float(d.size), 4)
        else:
            S["d_err"] = "深度 PNG 编码失败"
    except Exception as ex:
        S["d_err"] = repr(ex)[:120]
        print("cb_depth err", S["d_err"], flush=True)


def cb_info(msg):
    try:
        k = np.array(msg.k, dtype=np.float64).reshape(3, 3)
        S["K"] = {"fx": float(k[0][0]), "fy": float(k[1][1]),
                  "cx": float(k[0][2]), "cy": float(k[1][2]),
                  "width": int(msg.width), "height": int(msg.height),
                  "depth_unit_m": _DEPTH_UNIT_M,
                  "dist": list(msg.d) if len(msg.d) else [],
                  "source": "ROS /realsense/color/camera_info"}
        S["K_ts"] = time.time()
        S["frame_id"] = msg.header.frame_id
    except Exception as ex:
        print("cb_info err", repr(ex)[:100], flush=True)


class H(BaseHTTPRequestHandler):
    def _bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        self._bytes(obj.encode(), "application/json")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/frame.jpg":
            j = S["jpg"]
            if j is None:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(("no frame yet n=%d err=%s enc=%s"
                                  % (S["n"], S["err"], S["enc"])).encode())
                return
            return self._bytes(j, "image/jpeg")

        if p == "/depth.png":
            d = S["d_png"]
            if d is None:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(("no depth yet n=%d err=%s" % (S["d_n"], S["d_err"])).encode())
                return
            return self._bytes(d, "image/png")

        if p == "/depth.raw":
            d = S["d_raw"]
            if d is None:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(("no depth yet n=%d" % S["d_n"]).encode())
                return
            w, h = S["d_shape"]
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(d)))
            self.send_header("X-Depth-Width", str(w))
            self.send_header("X-Depth-Height", str(h))
            self.send_header("X-Depth-Dtype", "uint16-le")
            self.send_header("X-Depth-Unit-M", str(_DEPTH_UNIT_M))
            self.send_header("X-Depth-Age-S", "%.3f" % (time.time() - S["d_ts"]))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(d)
            return

        if p == "/intrinsics":
            if S["K"] is None:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"no camera_info yet")
                return
            import json
            return self._json(json.dumps(S["K"], ensure_ascii=False))

        # 默认状态
        import json
        st = {"color": {"n": S["n"], "age_s": round(time.time() - S["ts"], 2) if S["ts"] else -1,
                        "enc": S["enc"], "err": S["err"]},
              "depth": {"n": S["d_n"], "age_s": round(time.time() - S["d_ts"], 2) if S["d_ts"] else -1,
                        "shape": list(S["d_shape"]), "valid_ratio": S["d_valid_ratio"],
                        "unit_m": _DEPTH_UNIT_M, "err": S["d_err"]},
              "intrinsics": S["K"], "frame_id": S["frame_id"]}
        return self._json(json.dumps(st, ensure_ascii=False) + "\n")

    def log_message(self, *a):
        pass


rclpy.init()
n = Node("rs_fast_node")
q = QoSProfile(depth=8, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
n.create_subscription(Image, "/realsense/color/image_raw", cb_color, q)
n.create_subscription(Image, "/realsense/depth/image_rect_raw", cb_depth, q)
n.create_subscription(CameraInfo, "/realsense/color/camera_info", cb_info, q)
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", 8792), H).serve_forever(), daemon=True).start()
print("[rs_fast_node] :8792 ready  /frame.jpg  /depth.png  /depth.raw  /intrinsics", flush=True)
try:
    rclpy.spin(n)
except KeyboardInterrupt:
    pass
