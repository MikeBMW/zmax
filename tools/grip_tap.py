#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grip_tap.py —— 夹爪真值连续采样 (只读)

为什么要单独一条:
  /gripper_pos 上挂两个类型(Float32/Float64), 且每读一次要起 ssh ⇒ 塞进 3Hz 主循环会把节拍拖垮。
  这里用**流式** ros2 topic echo 一次订阅持续读, 本地给每行盖时间戳, 落 jsonl,
  事后与位姿/视觉样本按时间对齐 ⇒ 能精确切出"什么时候夹住、什么时候松开"。

用法: ./gui-venv311/bin/python tools/grip_tap.py --sec 600
输出: zmax_data/ar_rs/grip_<ts>.jsonl  ({"ts":..., "t":"HH:MM:SS", "pos":174.0})
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

ORIN = "tashan@192.168.23.66"
OUT_DIR = os.path.expanduser("~/zmax/zmax_data/ar_rs")
ROS = ('source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; '
       'export FASTDDS_BUILTIN_TRANSPORTS=UDPv4; export ROS_LOCALHOST_ONLY=0; '
       'exec ros2 topic echo /gripper_pos std_msgs/msg/Float32 --no-daemon')
NUM = re.compile(r"data:\s*(-?[\d.]+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=float, default=600.0)
    a = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "grip_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    f = open(path, "w", encoding="utf-8")
    print("夹爪流采样 → %s (%.0fs)" % (path, a.sec), flush=True)
    t0 = time.time()
    p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ORIN, ROS],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    n = 0
    try:
        for line in p.stdout:                                              # noqa: SIM115
            if time.time() - t0 > a.sec:
                break
            m = NUM.search(line)
            if not m:
                continue
            ts = time.time()
            f.write(json.dumps({"ts": round(ts, 3), "t": time.strftime("%H:%M:%S"), "pos": float(m.group(1))}) + "\n")
            f.flush()
            n += 1
    finally:
        p.terminate()
        f.close()
    print("采样 %d 条 → %s" % (n, path), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
