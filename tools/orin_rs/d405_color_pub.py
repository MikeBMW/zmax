#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""d405_color_pub.py — D405 彩色 → ROS2 /realsense/color/image_raw

2026-10-24 修: 彩色流取不到帧 (librealsense "Frame didn't arrive within 1000"),
  根因是 D405 的 UVC 彩色接口被内核 uvcvideo 占着, libusb 侧拿不到 color 帧
  (depth 走 vendor 接口不受影响, 实测 depth 14fps 正常)。
  卸载 uvcvideo 会让整个 USB 设备掉线 (实测 "No device connected"), 所以不能那么修。
  改成: 彩色走 UVC (/dev/videoN + OpenCV), 深度仍归 librealsense, 两条路互不抢。
  节点号自动探测, 换机器/换口也自己找。

用法(Orin): source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=0 && python3 d405_color_pub.py
"""
import os
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image

W, H, FPS = 640, 480, 30
GAIN = int(os.environ.get("D405_GAIN", "240"))
VIDEO_NODE = int(os.environ.get("D405_VIDEO_NODE", "-1"))   # -1 = 自动探测


def _try_open(idx):
    cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    # 不设 CAP_PROP_FPS: D405 的 UVC 在显式请求 15fps 时实测只出 4.7fps, 不设则 30fps
    cap.set(cv2.CAP_PROP_GAIN, GAIN)        # 现场是暗场, 默认 gain16 → 画面 mean 29
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(5):                       # 冷启头几帧常为空
        ok, fr = cap.read()
        if ok and fr is not None and fr.size:
            return cap
        time.sleep(0.15)
    cap.release()
    return None


def detect_node():
    if VIDEO_NODE >= 0:
        return VIDEO_NODE, _try_open(VIDEO_NODE)
    for i in range(6):
        cap = _try_open(i)
        if cap is not None:
            return i, cap
    return -1, None


class D405Color(Node):
    def __init__(self):
        super().__init__("d405_color_pub")
        q = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST)
        self.pub = self.create_publisher(Image, "/realsense/color/image_raw", q)
        self.idx = -1
        self.cap = None
        self.n = 0
        self.fail = 0
        self._open()
        self.create_timer(1.0 / FPS, self.tick)

    def _open(self):
        idx, cap = detect_node()
        self.idx, self.cap = idx, cap
        if cap is None:
            self.get_logger().error("没有可用的 UVC 彩色节点 (/dev/video0-5)")
        else:
            self.get_logger().info("D405 彩色 ← /dev/video%d (UVC %dx%d, gain=%d)" % (idx, W, H, GAIN))

    def tick(self):
        if self.cap is None:
            self.fail += 1
            if self.fail % (FPS * 3) == 0:            # 每 3s 重试一次, 不刷屏
                self._open()
            return
        ok, fr = self.cap.read()
        if not ok or fr is None or not fr.size:
            self.fail += 1
            if self.fail % (FPS * 3) == 0:
                self.get_logger().warn("连续取帧失败 %d 次, 重开 /dev/video%d" % (self.fail, self.idx))
                self.cap.release()
                self._open()
                self.fail = 0
            return
        self.fail = 0
        if fr.shape[0] != H or fr.shape[1] != W:
            fr = cv2.resize(fr, (W, H), interpolation=cv2.INTER_AREA)
        if fr.ndim == 2:
            fr = cv2.cvtColor(fr, cv2.COLOR_GRAY2BGR)
        a = np.ascontiguousarray(fr[:, :, :3])
        m = Image()
        m.height, m.width = int(a.shape[0]), int(a.shape[1])
        m.encoding = "bgr8"
        m.is_bigendian = 0
        m.step = int(a.strides[0])
        m.data = a.tobytes()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = "d405_color"
        self.pub.publish(m)
        self.n += 1
        if self.n % 150 == 0:
            self.get_logger().info("已发 %d 帧 (/dev/video%d)" % (self.n, self.idx))


def main():
    rclpy.init()
    n = D405Color()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if n.cap is not None:
                n.cap.release()
        except Exception:                            # noqa: BLE001
            pass
        n.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
