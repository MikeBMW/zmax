#!/usr/bin/env python3
"""pose_recorder.py — 把 /robot/tcp_pose 与图像帧计数落到 jsonl（默认 10Hz）

为什么要有它: 位姿只在内存里 50Hz 流过时, 相机一被挪动/换型/重标, 就永远没有
"那一时刻位姿是多少"的证据 —— 而本技能判"相机被挪了"之后, 下一步就是追认
"哪些采集/标定是在旧外参下做的"。必须在采集**之前**就起它, 事后补不了。

用法:
    source /opt/ros/<distro>/setup.bash
    python3 pose_recorder.py
环境变量:
    POSE_DIR(/home/intel/zmax_map/data/pose_log) POSE_HZ(10)
    POSE_TOPIC(/robot/tcp_pose) IMG_TOPIC(/realsense/color/image_raw)

两个必须记的列:
    t      墙钟 (time.time())
    stamp  ROS 时戳 (header.stamp) —— 实测两者可差 32s(NTP 回拨/时源不是同一台),
           只记一个就回放对不上图像帧。|t-stamp| 突然变大 = 时钟事件, 不是丢帧。

坑: 这两个话题的发布者都是 BEST_EFFORT, 必须 qos_profile_sensor_data,
    用默认 RELIABLE 会 "offering incompatible QoS. No messages will be received from it."
    且一行都不落（进程还活着, 最难看出来）。
"""
import json
import os
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

OUT_DIR = os.environ.get("POSE_DIR", "/home/intel/zmax_map/data/pose_log")
os.makedirs(OUT_DIR, exist_ok=True)
OUT = os.path.join(OUT_DIR, "pose_%s.jsonl" % time.strftime("%Y%m%d"))
HZ_DOWN = float(os.environ.get("POSE_HZ", "10"))


class Rec(Node):
    def __init__(self):
        super().__init__("pose_recorder")
        self.f = open(OUT, "a", buffering=1)
        self.last = 0.0
        self.img_n = 0
        self.img_ts = None
        self.pose_n = 0
        self.row_n = 0
        self.create_subscription(PoseStamped, os.environ.get("POSE_TOPIC", "/robot/tcp_pose"),
                                 self.on_pose, qos_profile_sensor_data)
        self.create_subscription(Image, os.environ.get("IMG_TOPIC", "/realsense/color/image_raw"),
                                 self.on_img, qos_profile_sensor_data)
        self.create_timer(30.0, self.beat)
        self.get_logger().info("recorder -> %s @ %.0fHz (sensor QoS)" % (OUT, HZ_DOWN))

    def beat(self):
        # 30s 一条：既证明活着, 又能在日志里看出回调到底进没进
        self.get_logger().info("pose_in=%d img_in=%d rows=%d" % (self.pose_n, self.img_n, self.row_n))

    def on_img(self, m):
        self.img_n += 1
        self.img_ts = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9

    def on_pose(self, m):
        self.pose_n += 1
        now = time.time()
        if now - self.last < 1.0 / HZ_DOWN:
            return
        self.last = now
        p, q = m.pose.position, m.pose.orientation
        self.f.write(json.dumps({
            "t": round(now, 3),
            "stamp": round(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9, 3),
            "frame": m.header.frame_id,
            "x": round(p.x, 6), "y": round(p.y, 6), "z": round(p.z, 6),
            "qx": round(q.x, 6), "qy": round(q.y, 6), "qz": round(q.z, 6), "qw": round(q.w, 6),
            "img_n": self.img_n, "img_stamp": self.img_ts,
        }, ensure_ascii=False) + "\n")
        self.row_n += 1


def main():
    rclpy.init()
    n = Rec()
    try:
        rclpy.spin(n)
    except (KeyboardInterrupt, Exception):
        pass
    finally:
        try:
            n.destroy_node()
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
