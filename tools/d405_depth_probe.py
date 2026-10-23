#!/usr/bin/env python3
"""验证 D405 深度 + 内参是否真的可用（只读订阅，不动任何服务）。"""
import sys
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image, CameraInfo

got = {"depth": None, "info": None, "color": None}


def mk(name, key):
    def cb(msg):
        if key == "info":
            k = np.array(msg.k).reshape(3, 3)
            got[key] = {"fx": k[0][0], "fy": k[1][1], "cx": k[0][2], "cy": k[1][2],
                        "w": msg.width, "h": msg.height,
                        "frame": msg.header.frame_id}
        else:
            h, w = int(msg.height), int(msg.width)
            buf = np.frombuffer(bytes(msg.data), dtype=np.uint16 if key == "depth" else np.uint8)
            if key == "depth":
                got[key] = buf.reshape(h, w)
            else:
                got[key] = buf.reshape(h, w, 3) if buf.size == h * w * 3 else buf.reshape(h, w)
    return cb


rclpy.init()
n = Node("depth_probe")
q = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)

n.create_subscription(Image, "/realsense/depth/image_rect_raw", mk("d", "depth"), q)
n.create_subscription(Image, "/realsense/color/image_raw", mk("c", "color"), q)
n.create_subscription(CameraInfo, "/realsense/color/camera_info", mk("i", "info"), q)

t0 = time.time()
while time.time() - t0 < 12 and any(v is None for v in got.values()):
    rclpy.spin_once(n, timeout_sec=0.3)

print("=== 收到情况 ===")
for k, v in got.items():
    print("  %-6s %s" % (k, "有" if v is not None else "无"))

if got["info"]:
    i = got["info"]
    print("\n=== 内参真值 (camera_info) ===")
    print("  fx=%.4f fy=%.4f cx=%.4f cy=%.4f  %dx%d  frame=%s"
          % (i["fx"], i["fy"], i["cx"], i["cy"], i["w"], i["h"], i["frame"]))

if got["depth"] is not None:
    d = got["depth"].astype(np.float32)
    # D405 常见 unit: 0.1mm ⇒ 1 单位 = 0.0001m；也有 1mm 设备
    valid = d[d > 0]
    print("\n=== 深度图 ===")
    print("  形状: %dx%d" % (got["depth"].shape[1], got["depth"].shape[0]))
    print("  有效像素: %d / %d (%.1f%%)" % (valid.size, d.size, valid.size / d.size * 100))
    if valid.size:
        print("  原始值: min=%d p5=%.0f 中位=%.0f p95=%.0f max=%d"
              % (valid.min(), np.percentile(valid, 5), np.median(valid),
                 np.percentile(valid, 95), valid.max()))
        for unit, name in ((0.0001, "0.1mm"), (0.001, "1mm")):
            print("  若 unit=%s ⇒ 深度 %.3f ~ %.3f m (中位 %.3f m)"
                  % (name, valid.min() * unit, valid.max() * unit, np.median(valid) * unit))
else:
    print("\n深度: 没收到")

rclpy.shutdown()
