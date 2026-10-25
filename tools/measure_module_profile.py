#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把臂相机画面**绕 tool1 原点旋转**, 让"模块头→法兰"方向变成竖直, 再取窗口做 ASCII 剖面。
用途: 量光模块的长/宽 —— 模块长轴在图上就是这条轴, 宽度就是垂直方向的亮暗台阶。
"""
import json, os, subprocess, sys, urllib.request
import cv2, numpy as np

REPO = os.path.expanduser("~/zmax")
HERE = os.path.dirname(os.path.abspath(__file__))

def tcp():
    with urllib.request.urlopen("http://127.0.0.1:8797/api/tcp", timeout=6) as r:
        return json.loads(r.read().decode())

def frame():
    b = urllib.request.urlopen("http://127.0.0.1:8797/snap/arm.jpg", timeout=10).read()
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR), len(b)

def main():
    d = tcp()
    fr = d["frames"]; T1 = fr["tool1"]; T0 = fr["tool0"]
    O = np.array(T1["origin"], float) * 1000.0
    Z = np.array(T1["z"], float); X = np.array(T1["x"], float); Y = np.array(T1["y"], float)
    O0 = np.array(T0["origin"], float) * 1000.0

    he = json.load(open(os.path.join(REPO, "models", "handeye_state.json")))
    M = np.array(he["T_cam2tool"], float)
    if np.abs(M[:3, 3]).max() < 10: M[:3, 3] *= 1000.0
    inv = np.linalg.inv(M)
    R_b2t = np.array([[T1["x"][0], T1["y"][0], T1["z"][0]],
                      [T1["x"][1], T1["y"][1], T1["z"][1]],
                      [T1["x"][2], T1["y"][2], T1["z"][2]]], float)      # base←tool1
    cam = O + R_b2t @ M[:3, 3]                      # 相机原点(base, mm)
    R_c2b = R_b2t @ inv[:3, :3]
    cal = json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))
    K = np.array(cal["K"], float).reshape(3, 3)

    def proj(p_mm):
        p = R_c2b.T @ (np.asarray(p_mm, float) - cam)
        if p[2] <= 1: return None
        return np.array([K[0, 0]*p[0]/p[2] + K[0, 2], K[1, 1]*p[1]/p[2] + K[1, 2]]), float(p[2])

    a, dz1 = proj(O)
    b, dz0 = proj(O0)
    img, nb = frame()
    print("TCP(mm)", np.round(O, 1), " 帧字节", nb, " 帧龄 %.1fs" % (d.get("age_s") or -1))
    print("模块头(tool1) → 像素 (%.1f, %.1f) 距相机 %.0fmm" % (a[0], a[1], dz1))
    print("法兰(tool0)   → 像素 (%.1f, %.1f) 距相机 %.0fmm" % (b[0], b[1], dz0))
    ang = np.degrees(np.arctan2(-(b[0]-a[0]), (b[1]-a[1])))     # 让 a→b 变竖直向下
    print("旋转角 %.1f° (a→b 变竖直)" % ang)

    # 绕 a 旋转整幅图, 使 a→b 朝下
    Rm = cv2.getRotationMatrix2D((float(a[0]), float(a[1])), ang, 1.0)
    rot = cv2.warpAffine(img, Rm, (img.shape[1]*3, img.shape[0]*4), flags=cv2.INTER_LINEAR,
                         borderValue=(0, 0, 0))
    g = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY)
    # a 在旋转后仍在 (a[0], a[1])
    cx, cy = int(round(a[0])), int(round(a[1]))
    win = g[max(0, cy-6):cy+150, cx-45:cx+45]                   # 60mm 长 / 30mm 宽 的窗口
    print("窗口", win.shape, " 平均 %.0f" % win.mean())
    chars = ' .:-=+*#%@'
    for y in range(0, win.shape[0], 3):
        row = ''.join(chars[min(9, int(win[y:y+3, x:x+3].mean()/25.6))] for x in range(0, win.shape[1], 2))
        print('%4d|%s|' % (y, row))
    cv2.imwrite("/home/ubuntu/mod_axis.png", rot[max(0,cy-20):cy+170, cx-60:cx+60])
    print("剖面图 → /home/ubuntu/mod_axis.png")

if __name__ == "__main__":
    main()
