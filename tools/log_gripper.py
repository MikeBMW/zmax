#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""log_gripper.py — 把 Orin 的 /gripper_pos 以高频落本地 JSONL, 与图像/末端真值按墙钟对齐。

为什么要有: 之前采集只有末端位姿, 动作第 7 维 grip 恒为占位 1.0 —— 因为本地 39071/status
只有 endInRef/jointPos, **没有夹爪**。夹爪真值在 Orin: /gripper_pos (读) 与
/gripper_driver (interfaces/srv/GripperSrv, 0=夹紧 200=张开, 控制)。

实现: 起一条 ssh 跑 `ros2 topic echo /gripper_pos --field data`, 逐行读回, 盖本地时间戳。
只读(只 echo 不 call), 不碰机械臂。
"""
from __future__ import annotations

import json
import os
import subprocess
import time

ROOT = "/home/ubuntu/zmax"
OUT = os.path.join(ROOT, "zmax_data/live_gripper")
SSH = ["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", "tashan@192.168.23.66",
       "source /opt/ros/humble/setup.bash; exec ros2 topic echo /gripper_pos --field data"]
SECS = float(os.environ.get("ZMAX_GRIP_SECS", "5400"))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "grip_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    t0 = time.time()
    n = 0
    p = subprocess.Popen(SSH, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    with open(path, "w", buffering=1) as f:
        for line in p.stdout:
            s = line.strip()
            if not s or s.startswith("---"):
                continue
            try:
                v = float(s)
            except ValueError:
                continue
            f.write(json.dumps({"ts": time.time(), "pos": v}) + "\n")
            n += 1
            if time.time() - t0 > SECS:
                break
    p.terminate()
    print("gripper: %d 条 → %s" % (n, path), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
