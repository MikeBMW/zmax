#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orin_tcp_pose_log.py — 在 Orin 上订阅 /robot/tcp_pose (44Hz), 落 JSONL 时间序列。

为什么放在 Orin 上跑: 44Hz 走 ssh 流式传输会被 YAML 解析+网络抖动拖慢; 直接在源头
(subscribe) 落盘, 本机再用 scp 拉, 时间戳是 ROS header stamp, 事后按时间配对即可。

只读: 只 subscribe, 不 publish, 不 moveAppend。输出 ~/.zmax/tcp_pose_log.jsonl
"""
import json
import os
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from geometry_msgs.msg import PoseStamped

OUT = os.path.expanduser("~/.zmax/tcp_pose_log.jsonl")


class Log(Node):
    def __init__(self):
        super().__init__("zmax_tcp_pose_log")
        self.f = open(OUT, "a", buffering=1)
        self.n = 0
        # 🔴 发布端是 BEST_EFFORT: 用默认 RELIABLE 订阅会报
        #    "offering incompatible QoS ... No messages will be received" 且**一条都收不到**(实测 0 行)
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST, depth=50)
        self.create_subscription(PoseStamped, "/robot/tcp_pose", self.cb, qos)

    def cb(self, m: PoseStamped):
        p, q = m.pose.position, m.pose.orientation
        # header.stamp 是控制器时钟; 同时记本机墙钟 ts, 便于跨机按墙钟对齐
        self.f.write(json.dumps({
            "ros_t": m.header.stamp.sec + m.header.stamp.nanosec * 1e-9,
            "ts": time.time(),
            "x": p.x * 1000.0, "y": p.y * 1000.0, "z": p.z * 1000.0,
            "qx": q.x, "qy": q.y, "qz": q.z, "qw": q.w,
        }) + "\n")
        self.n += 1


def main() -> int:
    rclpy.init()
    n = Log()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        print("已写 %d 条 → %s" % (n.n, OUT), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
