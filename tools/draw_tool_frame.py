#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""draw_tool_frame.py —— 在臂相机画面上画出 tool1 坐标系 (老倪 2026-10-18 要求)

数据源(全部是已有标定, 不编造):
  · T_cam2tool : models/handeye_state.json  (P_cam = T @ P_tool, 残差 0.06mm)
  · K / dist   : models/real_cam_calib.json (臂相机内参, 来自 ROS camera_info)
  · 实时帧     : http://192.168.23.66:8792/frame.jpg  (单帧, 只读)

画法: 原点一个实心点 + 三根箭头(X红/Y绿/Z蓝), 每根 40mm, 端点标轴名和长度。
输出: zmax_data/ar_rs/tool_frame_<ts>.png (2× 放大) + 终端打印像素坐标。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "zmax_data", "ar_rs")
AXES = [((1, 0, 0), (60, 60, 235), "X"), ((0, 1, 0), (60, 210, 60), "Y"), ((0, 0, 1), (235, 140, 40), "Z")]


def grab(url="http://192.168.23.66:8792/frame.jpg", timeout=8):
    b = urllib.request.urlopen(url, timeout=timeout).read()
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)


def project(P_cam, K):
    """P_cam (N,3) mm → 像素 (N,2); 返回 None 若在相机后面。"""
    P = np.asarray(P_cam, float)
    z = P[:, 2]
    if np.any(z <= 5.0):
        return None
    uv = (K @ P.T).T
    return uv[:, :2] / uv[:, 2:3]


def main():
    L = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    img = grab()
    if img is None:
        print("取不到臂相机画面")
        return 2
    he = json.load(open(os.path.join(REPO, "models", "handeye_state.json"), encoding="utf-8"))
    T = np.array(he["T_cam2tool"], float)
    # 🔴 文件里的矩阵平移是**米**(0.2147), 而 t_mm 字段是毫米(214.73); 先统一到 mm
    if np.linalg.norm(T[:3, 3]) < 2.0:
        T[:3, 3] *= 1000.0
    cal = json.load(open(os.path.join(REPO, "models", "real_cam_calib.json"), encoding="utf-8"))
    K = np.array(cal["K"], float).reshape(3, 3)
    dist = np.array(cal.get("dist") or [0, 0, 0, 0, 0], float).ravel()

    # 🔴 实测: handeye_state.json 里 T_cam2tool 的平移 = 相机在 tool 系下的位置(t_mm 同量),
    #    ⇒ 要画 tool 点就得用它的逆 (tool→cam)。直接拿 T 当 tool→cam 用会把原点画到相机背后。
    Ti = np.linalg.inv(T)
    pts_tool = [np.zeros(3)] + [np.array(a[0], float) * L for a in AXES]
    P_cam = np.array([Ti[:3, :3] @ p + Ti[:3, 3] for p in pts_tool])
    rvec, _ = cv2.Rodrigues(np.eye(3))
    uv, _ = cv2.projectPoints(P_cam.reshape(-1, 1, 3), rvec, np.zeros(3), K, dist)
    uv = uv.reshape(-1, 2)
    o = uv[0]
    zc = P_cam[:, 2]
    if np.any(zc <= 5):
        print("⚠ tool1 原点在相机后面(z=%.1fmm) ⇒ 这帧画不出来" % zc[0])
        return 3

    S = 2
    big = cv2.resize(img, None, fx=S, fy=S, interpolation=cv2.INTER_CUBIC)
    O = tuple(np.round(o * S).astype(int))
    for k, ((_, _, lab), col) in enumerate(zip(AXES, [a[1] for a in AXES]), start=1):
        P = tuple(np.round(uv[k] * S).astype(int))
        cv2.arrowedLine(big, O, P, col, 3, cv2.LINE_AA, tipLength=0.12)
        t = np.array(P) + np.array([6, -6])
        cv2.putText(big, "%s %.0fmm" % (lab, L), tuple(t), cv2.FONT_HERSHEY_SIMPLEX, 0.75, col, 2, cv2.LINE_AA)
    cv2.circle(big, O, 7, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(big, O, 7, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(big, "tool1 origin px (%d, %d)" % (o[0], o[1]), (O[0] + 12, O[1] + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(big, "T_cam2tool (handeye 0.06mm) + K(camera_info)", (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 255, 200), 2, cv2.LINE_AA)
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, "tool_frame_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
    cv2.imwrite(f, big)
    print("tool1 原点 像素 (%.1f, %.1f) · 相机系 z=%.1fmm" % (o[0], o[1], zc[0]))
    for k, a in enumerate(AXES, start=1):
        print("  %s 轴 %.0fmm → (%.1f, %.1f)" % (a[2], L, uv[k][0], uv[k][1]))
    print("图:", f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
