#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""红色目标闭环跟随 (视觉伺服) —— 机械臂末端相机盯住红色螺丝刀, 按画面偏移小步跟随。

设计口径(现场踩过):
  · 位姿真值只信 /robot/tcp_pose(SDK 直出), 不信"发出去了就当到了" —— 每步走完回读。
  · 目标只在**画面像素 + 深度**上闭环: 偏左→往左、偏右→往右、太远→前进; 不用猜相机朝向。
  · 每步 ≤40mm、默认 8mm/s; 深度算出的 base 坐标只用于**前进/后退**判距, 横向一律按像素误差走。
  · 丢目标连续 3 帧 / 步数用完 / 真值报警 ⇒ 立刻停, 不在"看不见"的情况下继续动。

用法:
  red_follow_servo.py --lock          # 只锁定并报告目标(不动臂)
  red_follow_servo.py --run           # 闭环跟随, 最多 --steps 步
  red_follow_servo.py --run --axis y  # 只做横向(左右), 不做前后

输出: 每步一行 JSON (step, px_err, depth, action, tcp_after)
"""
import argparse
import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image

BE = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                history=HistoryPolicy.KEEP_LAST)
STATION = os.environ.get("ZMAX_STATION", "http://127.0.0.1:8793")   # 在 intel 上跑时指到工位机
S = {}

# 像素误差 → 方向 (画面左右与 base Y 的对应关系现场标定过: 画面偏右 = 需要 -Y)
PX_TOL = 55.0          # 死区(px): 目标在中心 ±55px 内算"已居中"
DEPTH_OK_MM = 520.0    # 距离阈值: 近于它就认为"到位", 不再前进
STEP_MM = 30.0
SPEED = 8.0


class Cam(Node):
    def __init__(self):
        super().__init__('red_follow')
        self.create_subscription(Image, "/realsense/color/image_raw", lambda m: S.update(c=m), BE)
        self.create_subscription(Image, "/realsense/depth/image_rect_raw", lambda m: S.update(d=m), BE)
        self.create_subscription(CameraInfo, "/realsense/depth/camera_info", lambda m: S.update(i=m), 10)
        self.create_subscription(PoseStamped, "/robot/tcp_pose", lambda m: S.update(t=m), BE)


def grab(timeout=15.0):
    """取一帧 (col, dep)，超时返回 None。"""
    for k in ("c", "d"):
        S.pop(k, None)
    t0 = time.time()
    while time.time() - t0 < timeout:
        rclpy.spin_once(NODE, timeout_sec=0.2)
        if S.get("c") and S.get("d"):
            break
    if not (S.get("c") and S.get("d")):
        return None
    c, d = S["c"], S["d"]
    col = np.frombuffer(bytes(c.data), np.uint8).reshape(c.height, c.width, 3).copy()
    dep = np.frombuffer(bytes(d.data), np.uint16).reshape(d.height, d.width).copy()
    return col, dep


def find_red(col, dep):
    hsv = cv2.cvtColor(col, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 110, 70), (12, 255, 255)) | \
        cv2.inRange(hsv, (168, 110, 70), (180, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cs = [c for c in cs if cv2.contourArea(c) > 400]
    if not cs:
        return None
    ct = max(cs, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(ct)
    mm = np.zeros_like(m)
    cv2.drawContours(mm, [ct], -1, 255, -1)
    zs = dep[(mm > 0) & (dep > 0)]
    if not zs.size:
        return None
    return {"cx": x + w / 2.0, "cy": y + h / 2.0, "bbox": [x, y, w, h],
            "area": float(cv2.contourArea(ct)),
            "depth_mm": float(np.median(zs)) * 0.1}


def post(path, body, timeout=25):
    req = urllib.request.Request(STATION + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def tcp_now():
    with urllib.request.urlopen(STATION + "/ctl/status", timeout=8) as r:
        d = json.loads(r.read().decode() or "{}")
    return d.get("tcp", {}).get("xyz"), d.get("robot", {})


def move(axis, sign, mm):
    skill = {"x": ("L2.forward", "L2.backward"),
             "y": ("L2.left", "L2.right"),
             "z": ("L2.lift", "L2.lower")}[axis][0 if sign > 0 else 1]
    return post("/ctl/move", {"skill": skill, "d_mm": abs(mm),
                              "speed_mm_s": SPEED, "arm": 1})


def decide(blob, w, steps_left):
    """像素误差 → (axis, sign, mm)；None = 已居中, 不用动。"""
    ex = blob["cx"] - w / 2.0            # >0 = 目标偏右
    ey = blob["cy"] - 0
    if abs(ex) > PX_TOL:
        return ("y", -1 if ex > 0 else 1, STEP_MM)      # 偏右→往右(-Y); 偏左→往左(+Y)
    if blob["depth_mm"] > DEPTH_OK_MM:
        return ("x", 1, STEP_MM)                        # 居中但太远 → 前进
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--axis", default="all", choices=["all", "x", "y"])
    a = ap.parse_args()

    g = grab()
    if not g:
        print(json.dumps({"ok": False, "err": "没取到彩色/深度帧"}, ensure_ascii=False))
        return 2
    col, dep = g
    blob = find_red(col, dep)
    if not blob:
        print(json.dumps({"ok": False, "err": "画面里没有红色目标(面积>400px)"}, ensure_ascii=False))
        return 0
    tcp, robot = tcp_now()
    print(json.dumps({"ok": True, "lock": blob, "tcp": tcp,
                      "robot": {"op": robot.get("operation"), "estop": robot.get("estop")}},
                     ensure_ascii=False))
    if a.lock or not a.run:
        return 0

    for k in range(a.steps):
        g = grab()
        if not g:
            print(json.dumps({"ok": False, "step": k, "err": "取帧失败, 停"}, ensure_ascii=False))
            return 0
        col, dep = g
        blob = find_red(col, dep)
        if not blob:
            print(json.dumps({"ok": False, "step": k, "err": "目标丢失, 停"}, ensure_ascii=False))
            return 0
        act = decide(blob, col.shape[1], a.steps - k)
        if act is None:
            print(json.dumps({"ok": True, "step": k, "done": True,
                              "blob": {kk: round(v, 1) for kk, v in blob.items() if kk != "bbox"}},
                             ensure_ascii=False))
            return 0
        axis, sign, mm = act
        if a.axis != "all" and axis != a.axis:
            print(json.dumps({"ok": True, "step": k, "skip": "该轴不参与(%s)" % axis,
                              "blob": blob}, ensure_ascii=False))
            return 0
        r = move(axis, sign, mm)
        time.sleep(max(3.0, mm / SPEED + 2.0))
        tcp, robot = tcp_now()
        print(json.dumps({"ok": bool(r.get("ok")), "step": k, "axis": axis,
                          "sign": "+" if sign > 0 else "-", "mm": mm,
                          "dry": r.get("dry"), "px_err": round(blob["cx"] - col.shape[1] / 2.0, 1),
                          "depth_mm": round(blob["depth_mm"]), "tcp": tcp,
                          "estop": robot.get("estop")}, ensure_ascii=False))
        if robot.get("estop") or robot.get("has_error"):
            print(json.dumps({"ok": False, "err": "机器人报警/急停, 立即停"}, ensure_ascii=False))
            return 1
    return 0


if __name__ == "__main__":
    rclpy.init()
    NODE = Cam()
    try:
        sys.exit(main())
    finally:
        rclpy.shutdown()
