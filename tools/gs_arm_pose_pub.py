#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intel 侧: 订阅 /robot/tcp_pose (geometry_msgs/PoseStamped, 50Hz) → 写 /tmp/arm_tcp_pose.json

为什么要单独一个进程:
  rclpy 只在 /opt/ros/jazzy 的 PYTHONPATH 里, 而 3DGS 渲染跑在 gsxpu-venv(装了 torch/gsplat);
  两个解释器不能混装 ⇒ ROS 侧只做「读位姿落一个小 JSON」, 渲染侧每帧读文件。零拷贝、零依赖冲突。

用法(必须 source ROS):
  bash -c 'source /opt/ros/jazzy/setup.bash && exec /usr/bin/python3 gs_arm_pose_pub.py'
产出: /tmp/arm_tcp_pose.json  {"t":[x,y,z](m), "q":[x,y,z,w], "ts":<epoch>, "n":<count>}
"""
import json
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import PoseStamped

OUT = os.environ.get("ARM_POSE_JSON", "/tmp/arm_tcp_pose.json")
FPS_WRITE = float(os.environ.get("ARM_POSE_HZ", "50"))


class PoseTap(Node):
    def __init__(self):
        super().__init__("zmax_arm_pose_tap")
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST)
        self.n = 0
        self.last_write = 0.0
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.cb, qos)
        self.get_logger().info("订阅 /robot/tcp_pose → %s" % OUT)

    def cb(self, msg):
        now = time.time()
        if now - self.last_write < 1.0 / max(1.0, FPS_WRITE):
            return
        self.last_write = now
        p = msg.pose.position
        q = msg.pose.orientation
        self.n += 1
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"t": [p.x, p.y, p.z], "q": [q.x, q.y, q.z, q.w],
                       "ts": now, "n": self.n, "frame": msg.header.frame_id}, f)
        os.replace(tmp, OUT)          # 原子替换, 渲染侧永远读到完整 JSON


def main():
    rclpy.init()
    node = PoseTap()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
