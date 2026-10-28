#!/usr/bin/env python3
"""恒定 z / 恒定姿态的弧线路点执行器骨架 (rclpy 直发 /move_line)

用法: python3 orbit_arc_exec.py traj.json [speed_units]

traj.json: {"quat": [x,y,z,w], "z": 0.4303,
            "waypoints": [{"tcp": [x,y,z], "tag": "+8°"}, ...]}

纪律:
  · 三查不过不下发: power=on · operation=idle · has_error 假
  · 每路点核 z 与 traj.z 一致、姿态预先固定不变 ⇒ 纯平移
  · 一路点一条 /move_line, 到位判据 = 位置偏差 <2mm 连续 1.5s
  · 超时 / 偏差超限 / 状态异常 ⇒ 中止剩余路点, 绝不重发(重发=两个动作叠加)
  · 订阅一律 BEST_EFFORT —— 该发布者是 BEST_EFFORT, RELIABLE 收不到任何消息
"""
import json
import math
import sys
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

TRAJ = sys.argv[1] if len(sys.argv) > 1 else "/tmp/traj_orbit.json"
SPEED = float(sys.argv[2]) if len(sys.argv) > 2 else 200.0
TOL_MM, SETTLE_S, STEP_TIMEOUT_S = 2.0, 1.5, 45.0

d = json.load(open(TRAJ))
QUAT = d["quat"]
WPS = [(float(w["tcp"][0]), float(w["tcp"][1]), float(w["tcp"][2])) for w in d["waypoints"]]
Z0 = float(d["z"])

rclpy.init()
node = Node("orbit_exec")
QBE = QoSProfile(depth=10, history=HistoryPolicy.KEEP_LAST,
                 reliability=ReliabilityPolicy.BEST_EFFORT)
pose, stat = {"p": None}, {"raw": ""}
node.create_subscription(
    PoseStamped, "/robot/tcp_pose",
    lambda m: pose.update(p=(m.pose.position.x, m.pose.position.y, m.pose.position.z)), QBE)
node.create_subscription(String, "/robot_status", lambda m: stat.update(raw=m.data), QBE)

from interfaces.srv import TargetPose  # noqa: E402  (先 source ROS + 工作空间)
cli = node.create_client(TargetPose, "/move_line")
if not cli.wait_for_service(timeout_sec=10.0):
    print("⛔ /move_line 服务不可用")
    sys.exit(3)


def spin(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        rclpy.spin_once(node, timeout_sec=0.05)


def field(k):
    try:
        return json.loads(stat["raw"]).get(k)
    except Exception:
        return None


spin(1.0)
p, o, e = field("power_state"), field("operation_state"), field("has_error")
print("三查: power=%s · operation=%s · has_error=%s" % (p, o, e))
if p != "on" or o != "idle" or e not in (False, None):
    print("⛔ 前置不满足, 不下发 (drag/manual 需现场示教器切 idle+automatic)")
    sys.exit(3)
if pose["p"] is None:
    print("⛔ 拿不到位姿真值 (先查 QoS 是否 BEST_EFFORT)")
    sys.exit(3)

for i, wp in enumerate(WPS, 1):
    if abs(wp[2] - Z0) > 1e-6:
        print("⛔ 路点 %d 的 z 与恒定平面不符, 中止" % i)
        sys.exit(4)
    req = TargetPose.Request()
    req.speed = SPEED
    req.pose.position.x, req.pose.position.y, req.pose.position.z = wp
    req.pose.orientation.x, req.pose.orientation.y = QUAT[0], QUAT[1]
    req.pose.orientation.z, req.pose.orientation.w = QUAT[2], QUAT[3]
    fut = cli.call_async(req)
    rclpy.spin_until_future_complete(node, fut, timeout_sec=STEP_TIMEOUT_S)
    print("--- 路点 %2d/%d → (%.4f, %.4f, %.4f) 回执 %s"
          % (i, len(WPS), wp[0], wp[1], wp[2], getattr(fut.result(), "success", "None")))

    t0, okcnt, last = time.time(), 0, None
    while time.time() - t0 < STEP_TIMEOUT_S:
        spin(0.1)
        if pose["p"] is None:
            continue
        last = math.dist(pose["p"], wp) * 1000.0
        okcnt = okcnt + 1 if last < TOL_MM else 0
        if okcnt >= int(SETTLE_S / 0.1):
            break
        if field("has_error") or field("estop_detected") or field("collision_detected"):
            print("⛔ 状态异常 ⇒ 立即中止")
            sys.exit(5)
    if okcnt < int(SETTLE_S / 0.1):
        print("⛔ 路点 %d 未到位(偏差 %s mm) ⇒ 中止剩余, 不重发" % (i, last))
        sys.exit(6)
    print("    ✅ 到位 偏差 %.2fmm" % last)

print("== %d 个路点完成 · 终点 (%.6f, %.6f, %.6f) ==" % ((len(WPS),) + tuple(pose["p"])))
