#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""d405_color_pub.py — D405 彩色 → ROS2 /realsense/color/image_raw (2026-10-18)

为什么有它: Orin 2026-10-18 08:47 重启后机器人 ROS 栈没自启, /realsense/color/image_raw 没有发布者
  ⇒ rs_fast_node(:8792) 无源可订阅 ⇒ 控制台臂相机 503。
本脚本只用 pyrealsense2 + rclpy (Orin 上都有), 不装机、不改任何既有服务; 进程级可停 (kill 即恢复原状)。
用法(Orin): source /opt/ros/humble/setup.bash && export ROS_DOMAIN_ID=0 && python3 d405_color_pub.py
"""
import numpy as np
import pyrealsense2 as rs
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image


class D405Color(Node):
    def __init__(self):
        super().__init__("d405_color_pub")
        q = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                       history=HistoryPolicy.KEEP_LAST)
        self.pub = self.create_publisher(Image, "/realsense/color/image_raw", q)
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
        self.pipe.start(cfg)
        self.n = 0
        self.create_timer(1.0 / 15.0, self.tick)
        self.get_logger().info("D405 彩色 → /realsense/color/image_raw (640x480 bgr8 @15Hz)")

    def tick(self):
        try:
            f = self.pipe.wait_for_frames(1000)
            c = f.get_color_frame()
            if not c:
                return
            a = np.asanyarray(c.get_data())
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
                self.get_logger().info("已发 %d 帧" % self.n)
        except Exception as e:                      # noqa: BLE001
            self.get_logger().warn("取帧失败: %s" % str(e)[:100])


def main():
    rclpy.init()
    n = D405Color()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            n.pipe.stop()
        except Exception:                            # noqa: BLE001
            pass
        n.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
