#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 tool1 处的光模块长方体(8 角点)投到臂相机画面并叠图, 用来**核对**尺寸与朝向是否对得上实物。

口径(老倪 2026-10-25): tool1 原点 = 模块头中心; X=上表面法向(厚 T); Y=侧面法向(宽 W); Z=中轴线(长 L);
本体从模块头朝法兰方向长(sign 由 tool0−tool1 与 Z 点积定)。
输出: /home/ubuntu/mod_box_overlay.png + 控制台打印 8 角点像素与像素跨度(= 粗测尺寸)。
"""
import json, os, urllib.request
import cv2, numpy as np

REPO = os.path.expanduser("~/zmax")

def main():
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/tcp", timeout=6).read().decode())
    spec = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/module_spec", timeout=6).read().decode())
    b = urllib.request.urlopen("http://127.0.0.1:8797/snap/arm.jpg", timeout=10).read()
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    T1, T0 = d["frames"]["tool1"], d["frames"]["tool0"]
    O = np.array(T1["origin"], float) * 1000.0
    AX = [np.array(T1[k], float) for k in ("x", "y", "z")]
    O0 = np.array(T0["origin"], float) * 1000.0
    L, W, T = float(spec["L_mm"]), float(spec["W_mm"]), float(spec["T_mm"])
    sgn = 1 if float(np.dot(O0 - O, AX[2])) >= 0 else -1

    he = json.load(open(os.path.join(REPO, "models", "handeye_state.json")))
    M = np.array(he["T_cam2tool"], float)
    if np.abs(M[:3, 3]).max() < 10: M[:3, 3] *= 1000.0
    inv = np.linalg.inv(M)
    R_b2t = np.column_stack(AX)
    cam = O + R_b2t @ M[:3, 3]
    R_c2b = R_b2t @ inv[:3, :3]
    K = np.array(json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))["K"], float).reshape(3, 3)

    def proj(p):
        q = R_c2b.T @ (np.asarray(p, float) - cam)
        if q[2] <= 1: return None
        return np.array([K[0, 0]*q[0]/q[2] + K[0, 2], K[1, 1]*q[1]/q[2] + K[1, 2]])

    C = O + AX[2]*(L/2*sgn)
    half = [T/2, W/2, L/2]
    cs = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                cs.append(C + AX[0]*half[0]*sx + AX[1]*half[1]*sy + AX[2]*half[2]*sz)
    px = [proj(c) for c in cs]
    print("尺寸 L=%.1f W=%.1f T=%.1f mm · sgn=%d · 相机↔模块头 %.0fmm" %
          (L, W, T, sgn, float(np.linalg.norm(cam - O))))
    ph, pf = proj(O), proj(O + AX[2]*(L*sgn))
    print("模块头像素", None if ph is None else np.round(ph, 1),
          " 法兰侧端面中心像素", None if pf is None else np.round(pf, 1))
    if any(p is None for p in px):
        print("⚠ 有角点在相机后面(z<=0), 无法完整叠图")
    else:
        arr = np.array(px)
        print("8 角点像素跨度 x %.1f px · y %.1f px" % (float(arr[:, 0].max()-arr[:, 0].min()), float(arr[:, 1].max()-arr[:, 1].min())))
        # 12 条棱
        ix = lambda a, b_, c: ((a+1)//2)*4 + ((b_+1)//2)*2 + ((c+1)//2)
        edges = []
        for a in (-1, 1):
            for b_ in (-1, 1):
                edges += [(ix(a, b_, -1), ix(a, b_, 1))]
        for a in (-1, 1):
            for c in (-1, 1):
                edges += [(ix(a, -1, c), ix(a, 1, c))]
        for b_ in (-1, 1):
            for c in (-1, 1):
                edges += [(ix(-1, b_, c), ix(1, b_, c))]
        for i, j in edges:
            p1, p2 = tuple(np.round(px[i]).astype(int)), tuple(np.round(px[j]).astype(int))
            cv2.line(img, p1, p2, (255, 196, 87), 1, cv2.LINE_AA)
        for k, p in enumerate(px):
            cv2.circle(img, tuple(np.round(p).astype(int)), 2, (0, 0, 255) if k == 0 else (60, 220, 255), -1)
        cv2.putText(img, "L%.1f W%.1f T%.1f" % (L, W, T), (6, 470),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 196, 87), 1, cv2.LINE_AA)
    cv2.imwrite("/home/ubuntu/mod_box_overlay.png", img)
    print("叠图 → /home/ubuntu/mod_box_overlay.png")

if __name__ == "__main__":
    main()
