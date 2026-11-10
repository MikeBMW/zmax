# -*- coding: utf-8 -*-
"""servo_essence_demo — 视觉伺服"本质"的数值验证 (开环 vs 闭环, 同一标定误差)。

回答老倪 2026-11-10: 「视觉伺服本质是什么? 是我先验位置结构么?」

实验设计 (全部真源数值, 但这是**数学性质验证**, 不是现场精度):
  目标点  config/calib/zmax_calib.json → cell_geometry.points.hole = (757.5, 227.9, 190.1)mm
  内参    config/calib/zmax_calib.json → camera (fx=394.062 fy=393.472 ...)
  标定误差 3.5mm —— 取自实测: URDF FK 与 /robot/tcp_pose 真值之差 ~3.5mm
  相机位姿 示意: 距目标 250mm, 斜 35° (只为暴露几何性质, 不代表现场机位)

两个对照:
  A 开环  标定误差 100% 传给落点           → 3.5mm
  B 闭环  IBVS 归一化点特征 + 交互矩阵      → 0.21mm (8 步)

结论: 视觉伺服不消除误差源, 而是把"绝对测量 + 比较"换成"相对误差 + 收敛"。

⚠️ 这个脚本本身记录了两个真实坑 (都踩过, 都导致发散到 300mm+):
  坑1  相机系速度必须 R_bc 转回 base 才能作用于世界坐标
  坑2  在固定相机的模型里移动"点"与移动"相机"符号相反
       (相机向 +X 走 ⇒ 点相对相机向 -X ⇒ 世界系等效点位移 = -R_bc @ v_cam)

用法: gui-venv311/bin/python tools/servo_essence_demo.py
"""
from __future__ import annotations

import json
import os

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(REPO, "config", "calib", "zmax_calib.json")


def rot(rx, ry, rz):
    a, s = np.cos(rx), np.sin(rx)
    b, t = np.cos(ry), np.sin(ry)
    c, d = np.cos(rz), np.sin(rz)
    return (np.array([[c, -d, 0], [d, c, 0], [0, 0, 1]]) @
            np.array([[b, 0, t], [0, 1, 0], [-t, 0, b]]) @
            np.array([[1, 0, 0], [0, a, -s], [0, s, a]]))


def main():
    cal = json.load(open(CAL, encoding="utf-8"))
    K = cal["camera"]
    fx, fy = K["fx"], K["fy"]
    hole = cal["cell_geometry"]["points"]["points"]["hole"]
    p_star = np.array([hole["x"], hole["y"], hole["z"]], float) * 1000.0

    R_bc = rot(np.deg2rad(35), 0, np.deg2rad(-10))
    t_bc = p_star - R_bc @ np.array([0.0, 0.0, 250.0])
    delta = np.array([3.5, 0.0, 0.0])          # 标定误差 (实测量级)
    t_hat = t_bc - delta                        # 系统"以为"的相机位姿

    def norm_xy(p_w):
        pc = R_bc.T @ (p_w - t_hat)
        return np.array([pc[0] / pc[2], pc[1] / pc[2]]), pc[2]

    s_star, _ = norm_xy(p_star)
    print("目标 hole(base) = %s mm" % np.round(p_star, 1))
    print("目标特征 s* = %s (归一化)   标定误差 3.5mm" % np.round(s_star, 4))

    p = p_star + np.array([20.0, 12.0, 8.0])
    lam = 0.6
    print("\n闭环 IBVS (初始偏 %.1f mm):" % np.linalg.norm(p - p_star))
    n = 0
    for k in range(12):
        s, z = norm_xy(p)
        e = s - s_star
        L = np.array([[-1.0 / z, 0.0, s[0] / z],
                      [0.0, -1.0 / z, s[1] / z]])       # 交互矩阵 (纯平移)
        v_cam = -lam * (np.linalg.pinv(L) @ e)
        p = p - R_bc @ v_cam                            # 坑2: 符号
        n = k + 1
        print("   step %d: |e|=%9.6f → 位置误差 %8.4f mm" % (k, np.linalg.norm(e), np.linalg.norm(p - p_star)))
        if np.linalg.norm(e) < 1e-4:
            break

    open_err = np.linalg.norm(delta)
    closed_err = np.linalg.norm(p - p_star)
    print("\nA 开环 3.5mm 标定误差 → 落点误差 %.4f mm" % open_err)
    print("B 闭环 同一误差       → 位置误差 %.4f mm (%d 步)" % (closed_err, n))
    print("压低 %.0f 倍 —— 误差源没消失, 是被闭环增益吸收了。" % (open_err / max(closed_err, 1e-9)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
