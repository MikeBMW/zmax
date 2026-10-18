#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""place_back_finish.py —— 走回槽位 → 真松爪 → 原路退出

上一轮 place_back.py 已经把模块送到槽位位姿, 但松爪发的是 {"cmd":"grip"} —— 守护进程不认(未知命令),
所以模块又被带出来了。正确用法: FIFO 里的技能键是 **skill**: {"skill":"L2.grip_open"}。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G                       # noqa: E402
from place_back import GRASP_TCP, GRASP_ABC, PULL_TCP, cur, gm, step_move   # noqa: E402


def gripper_pos():
    try:
        o = subprocess.run(["ssh", "-o", "BatchMode=yes", "tashan@192.168.23.66",
                            "source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; "
                            "timeout 12 ros2 topic echo /gripper_pos std_msgs/msg/Float32 --once --no-daemon"],
                           capture_output=True, text=True, timeout=40)
        for ln in (o.stdout or "").splitlines():
            ln = ln.strip()
            if ln.startswith("data:"):
                return float(ln.split(":", 1)[1])
    except Exception as e:                                                  # noqa: BLE001
        print("  读夹爪失败:", e)
    return None


def main():
    speed = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    xyz, abc = cur()
    print("起点 TCP %s ABC %s" % (np.round(xyz, 1), np.round(abc, 1)))
    print("夹爪(合住时应 150~300): %s" % gripper_pos())

    # ① 回到槽位位姿(姿态已对, 纯平移)
    if not step_move(GRASP_TCP, GRASP_ABC, speed, 35.0, 4.0, 3.0, "回槽位"):
        print("没回到槽位 ⇒ 不松爪")
        return 2
    time.sleep(1.5)

    # ② 真松爪: FIFO 技能键是 skill
    print("松爪: {'skill':'L2.grip_open'}")
    r = G.send({"skill": "L2.grip_open", "speed": 20.0}, wait=45)
    print("  回执:", json.dumps(r, ensure_ascii=False)[:260])
    time.sleep(2.5)
    gp = gripper_pos()
    print("  夹爪真值:", gp, "(>700 才算张开; 合住时 174)")
    if gp is None or gp < 500:
        print("⚠ 没真的张开 ⇒ 就地停, 请人看")
        return 3

    # ③ 原路退出 110mm
    if not step_move(PULL_TCP, GRASP_ABC, speed, 35.0, 4.0, 3.0, "退出"):
        print("退出没到位 ⇒ 人来看")
        return 4
    time.sleep(1.0)
    print("完成: TCP %s · 夹爪 %s" % (np.round(cur()[0], 1), gripper_pos()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
