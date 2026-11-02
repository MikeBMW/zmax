#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板姿态(孔轴/工具四元数)数学自检 — 不需要真机、不需要图像。

老倪 2026-11-02「只有位置, 能保证姿态么」⇒ board_frame_module 补了姿态输出。
这里用**已知的合成板姿态**验证几何不写错 (这是判据, 不是示意):

  1. 板绕 Z 转 20°、再绕 X 倾 12° ⇒ 工具 Z 必须等于 -板法向, 工具 X ⊥ 工具 Z
  2. 工具四元数 → 旋转矩阵 与构造矩阵逐元素一致 (≤1e-9)
  3. 纯 yaw 17° 的板 ⇒ 工具 X 与板行方向的夹角为 0°, 工具 Z 朝板里 (与 +n 差 180°)
  4. 四元数夹角函数: 同一姿态 0°, 差 3° 的转置姿态 3°

用法: ./gui-venv311/bin/python tools/test_board_frame_attitude.py
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import board_frame_module as B                                    # noqa: E402


def rot(axis, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def q_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def main():
    ok = []

    def chk(name, cond, detail=""):
        ok.append(bool(cond))
        print("%s %-46s %s" % ("PASS" if cond else "FAIL", name, detail))

    # 1/2 倾斜板: 先绕 Z 20°, 再绕 X 12°
    R = rot("x", 12.0) @ rot("z", 20.0)
    Rt, n, ex, tz = B.tool_frame_from_board(R)
    chk("工具 Z = -板法向", np.allclose(tz, -n, atol=1e-12),
        "tz=%s n=%s" % (np.round(tz, 4), np.round(n, 4)))
    chk("工具 X ⊥ 工具 Z", abs(float(np.dot(Rt[:, 0], Rt[:, 2]))) < 1e-12)
    chk("工具系右手正交 (det=+1)", abs(np.linalg.det(Rt) - 1.0) < 1e-12,
        "det=%.12f" % np.linalg.det(Rt))
    q = B.quat_of(Rt)
    chk("四元数 → 矩阵 与构造矩阵一致", np.allclose(q_to_R(q), Rt, atol=1e-9))
    chk("四元数单位模", abs(float(np.linalg.norm(q)) - 1.0) < 1e-9, "|q|=%.12f" % np.linalg.norm(q))

    # 3 纯 yaw 17°
    R2 = rot("z", 17.0)
    Rt2, n2, ex2, tz2 = B.tool_frame_from_board(R2)
    ang_x = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(Rt2[:, 0], ex2))))))
    ang_n = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(tz2, n2))))))
    chk("纯 yaw: 工具 X 对齐板行方向", ang_x < 1e-9, "夹角 %.6f°" % ang_x)
    chk("纯 yaw: 工具 Z 与法向差 180°", abs(ang_n - 180.0) < 1e-9, "夹角 %.4f°" % ang_n)

    # 4 四元数夹角
    from lerobot.engineering.exec import daemon as D              # noqa: E402
    a0 = [0.0, 0.0, 0.0, 1.0]
    h = math.radians(3.0) / 2.0
    a3 = [0.0, 0.0, math.sin(h), math.cos(h)]
    chk("四元数夹角: 同姿态 0°", abs(D._quat_angle_deg(a0, a0) - 0.0) < 1e-9)
    chk("四元数夹角: 差 3° 读出 3°", abs(D._quat_angle_deg(a0, a3) - 3.0) < 1e-6,
        "%.6f°" % D._quat_angle_deg(a0, a3))
    chk("四元数夹角: 非法输入给 None", D._quat_angle_deg(None, a0) is None)

    print("\n结果: %d PASS / %d FAIL" % (sum(ok), len(ok) - sum(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
