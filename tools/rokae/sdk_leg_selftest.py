#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检: SDK 腿(不动机器人) —— 解析/守卫/开关/包络/真值, 全部只读。"""
import json
import os
import sys
import math

sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T                                                        # noqa: E402

print("=" * 78)
print("① 开关优先级 (env > 文件 > 默认 ros)")
print("  transport() =", T.transport(), "| 文件存在:", os.path.exists(T.SWITCH))
print("=" * 78)
print("② 解析 L2 真实下发的 ros2 调用 (4 种)")
calls = {
    "line_abs(空间点)": 'timeout 90 ros2 service call /move_line interfaces/srv/TargetPose "{speed: 120, '
                        'joint_state: {name: [], position: []}, pose: {position: {x: 0.6473608, y: 0.205931, '
                        'z: 0.1076848}, orientation: {x: 0.7382623, y: 0.0195962, z: 0.6742226, w: 0.0029264}}}"',
    "line_rel(抬升50)": 'timeout 90 ros2 service call /move_line interfaces/srv/TargetPose "{speed: 60, '
                        'joint_state: {name: [], position: []}, pose: {position: {x: 0.612982, y: -0.017175, '
                        'z: 0.250678}, orientation: {x: 0.720737, y: -0.015667, z: 0.691381, w: 0.047804}}}"',
    "move_pose(旋转)": 'timeout 150 ros2 service call /move_pose interfaces/srv/TargetPose "{speed: 40, '
                       'joint_state: {name: [], position: []}, pose: {position: {x: 0.612982, y: -0.017175, '
                       'z: 0.200678}, orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}}}"',
    "非运动(停机)": 'ros2 service call /stop_robot std_srvs/srv/Trigger "{}"',
}
for nm, c in calls.items():
    mv = T.parse_call(c)
    if mv is None:
        print("  %-16s → 认不出/非运动(会走 ROS 原路) ✔" % nm)
    else:
        print("  %-16s → %s pos=%s quat=%s speed=%s %s" % (
            nm, mv["srv"], [round(v, 4) for v in mv["pos"]],
            [round(v, 3) for v in mv["quat"]], mv["speed_units"], mv.get("bad") or "✔"))
print("=" * 78)
print("③ 姿态换算口径复核 (quat→rpy(ZYX) 是否回到控制器 rpy)")
p = T.read_pose()
q = p["quat"]
rpy = T.quat2rpy(*q)
print("  真值文件 rpy(deg) =", [round(math.degrees(v), 4) for v in p["rpy"]])
print("  quat→rpy(deg)     =", [round(math.degrees(v), 4) for v in rpy])
print("  最大差(deg) = %.6f  ⇒ %s" % (
    max(abs(a - b) for a, b in zip(p["rpy"], rpy)),
    "✔ 口径一致(float 噪声内)" if max(abs(a - b) for a, b in zip(p["rpy"], rpy)) < 1e-3 else "❌ 口径不一致"))
print("=" * 78)
print("④ 守卫: speed 换算 / 位移上限 / 陈旧真值")
for u in (8, 60, 120, 200, 1000):
    print("  L2 speed=%-5s ⇒ %.2f mm/s" % (u, max(1.0, min(T.MAX_SPEED_MM_S, 0.0935 * u))))
print("  MAX_ABS_MM=%s  REL_STEP_MM=%s  MAX_SPEED_MM_S=%s  POSE_FRESH_S=%s"
      % (T.MAX_ABS_MM, T.REL_STEP_MM, T.MAX_SPEED_MM_S, T.POSE_FRESH_S))
print("  TCP 真值: pos=%s · 龄 %.2fs" % ([round(v, 4) for v in p["pos"]], p["age"]))
print("=" * 78)
print("⑤ 各空间点: 包络 + 相对现位姿的位移/姿态差 (只算, 不动)")
sp = json.load(open("/home/ubuntu/zmax/data/skills/l2_atomic/space_points.json"))["points"]
for nm in ["space1", "space2", "space3", "space4", "space5", "space6"]:
    d = sp.get(nm)
    if not d:
        continue
    ok, msg = T.env_check(d["pos"])
    dist = math.sqrt(sum((d["pos"][i] - p["pos"][i]) ** 2 for i in range(3))) * 1000.0
    ang = T.quat_angle_deg(d["quat"], q)
    print("  %-7s 距离 %6.1fmm %s · 姿态差 %5.1f° · 包络 %s %s" % (
        nm, dist, "✔≤800" if dist <= T.MAX_ABS_MM else "❌超上限", ang,
        "OK" if ok else "❗出包络", msg[:60]))
print("=" * 78)
print("⑥ 关掉开关时链路必须完全不动 (transport=ros ⇒ 调用方仍走产线 ROS 原路)")
print("  当前 transport =", T.transport(), "(只有 'sdk' 才会接管 /move_line|/move_pose)")
