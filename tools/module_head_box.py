#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在**手臂相机**里检测光模块头 → 画绿色边界框 → 把它的中心反投影成 base 系点。

老倪 2026-10-25: 「tool1 模块头的坐标系, 中心点偏了。要在光模块头上, 检测出绿色边界框,
然后把 tool1 的原点, 放在绿色边界框的中间位置」。

做法(全自动, 不需要人点):
 1. 用控制器上报的 tool1 投影当"粗 hint"(它偏, 但同侧);
 2. 在 hint 附近找**细长亮块**(模块本体), PCA 出长轴;
 3. 头部 = 长轴上**靠近 hint 的那一端**; 以该端为中心取 1/3 长 × 全宽的旋转矩形 = 绿色边界框;
 4. 框中心像素 → 反投影到 base(用 tool1 在该口径下的相机系深度当平面) ⇒ 新的模块头中心。
输出: /home/ubuntu/mod_head_box.jpg · /home/ubuntu/mod_head_box.json
"""
import json, os, urllib.request
import cv2, numpy as np

REPO = os.path.expanduser("~/zmax")

def main():
    b = urllib.request.urlopen("http://127.0.0.1:8797/snap/arm.jpg", timeout=10).read()
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/tcp", timeout=6).read().decode())
    F1 = d["frames"]["tool1"]
    O = np.array(F1["origin"], float) * 1000.0
    R = np.column_stack([np.array(F1[k], float) for k in ("x", "y", "z")])
    M = np.array(json.load(open(os.path.join(REPO, "models", "handeye_state.json")))["T_cam2tool"], float)
    if np.abs(M[:3, 3]).max() < 10: M[:3, 3] *= 1000.0
    cam = O + R @ M[:3, 3]
    R_c2b = R @ M[:3, :3]
    K = np.array(json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))["K"], float).reshape(3, 3)

    def uv_of(p):
        q = R_c2b.T @ (np.asarray(p, float) - cam)
        if q[2] <= 1: return None, None
        return (K[0, 0]*q[0]/q[2] + K[0, 2], K[1, 1]*q[1]/q[2] + K[1, 2]), q[2]
    uv0, z0 = uv_of(O)
    print("tool1(控制器上报) → 像素 (%.1f, %.1f) 相机系 z=%.0fmm" % (uv0[0], uv0[1], z0))

    # 找模块: 细长亮块, 取离 hint 最近的那个
    # 只在 hint 附近找(模块头就该在 tool1 附近, 允许因出画/贴边而变短)
    X0, X1, Y0, Y1 = 0, g.shape[1], 0, g.shape[0]
    print("搜索窗 x[%d,%d] y[%d,%d]" % (X0, X1, Y0, Y1))
    cands = []
    for th in (110, 130, 150, 170):
        m = np.zeros_like(g)
        m[Y0:Y1, X0:X1] = (g[Y0:Y1, X0:X1] > th).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if a < 220: continue
            pts = np.column_stack(np.nonzero(lab == i))[:, ::-1].astype(np.float32)
            rect = cv2.minAreaRect(pts)                       # ((cx,cy),(w,h),ang)
            (cx, cy), (rw, rh), ang = rect
            L, Wd = max(rw, rh), min(rw, rh)
            if not (35 <= L <= 190 and 6 <= Wd <= 55): continue
            if not (2.2 <= L / max(Wd, 1e-6) <= 7.0): continue
            dist = float(np.hypot(cx - uv0[0], cy - uv0[1]))
            if False: continue
            cands.append(dict(a=int(a), rect=[float(cx), float(cy), float(rw), float(rh), float(ang)],
                              L=float(L), W=float(Wd), dist=round(dist, 1), th=th, i=int(i),
                              box=[list(map(float, p)) for p in cv2.boxPoints(rect)]))
    if not cands:
        print("⛔ 没找到模块候选")
        return
    # 只按"像不像一根模块"排序: 长宽比接近 56.5/13.4=4.2 且够长; 不按离 tool1 的远近(那个基准是错的)
    cands.sort(key=lambda c: (abs(c["L"]/max(c["W"],1e-6) - 4.2), -c["L"]))
    best = cands[0]
    print("选中模块: 长%.0fpx 宽%.0fpx 中心(%.0f,%.0f) 离hint %.0fpx (th%d, 共%d候选)" %
          (best["L"], best["W"], best["rect"][0], best["rect"][1], best["dist"], best["th"], len(cands)))

    # 模块端面: 用该连通域像素沿长轴投影, 取靠近 hint 的那一端
    box = np.array(best["box"], np.float32)                 # 直接用选中候选自己的四点(别再重算连通域, 编号会变)
    cen = np.array([rect[0][0], rect[0][1]], float)
    # 长轴方向 = 最长边方向
    e = [(box[(k+1) % 4] - box[k]) for k in range(4)]
    li = int(np.argmax([np.linalg.norm(v) for v in e]))
    axis = e[li] / max(1e-6, np.linalg.norm(e[li]))
    L = float(np.linalg.norm(e[li])); Wd = float(np.linalg.norm(e[(li+1) % 4]))
    # 两端中点
    pA = (box[li] + box[(li+1) % 4]) / 2.0
    pB = (box[(li+2) % 4] + box[(li+3) % 4]) / 2.0
    dA = float(np.hypot(*(pA - uv0))); dB = float(np.hypot(*(pB - uv0)))
    head_end = pA if dA <= dB else pB
    far_end = pB if dA <= dB else pA
    u = (head_end - far_end) / max(1e-6, np.linalg.norm(head_end - far_end))
    seg = min(L / 3.0, 34.0)                                   # 头部 1/3 段(上限 34px)
    c_head = head_end - u * seg / 2.0                          # 头部框中心
    half_w = Wd / 2.0
    nrm = np.array([-u[1], u[0]])
    q = [c_head - u*seg/2 - nrm*half_w, c_head + u*seg/2 - nrm*half_w,
         c_head + u*seg/2 + nrm*half_w, c_head - u*seg/2 + nrm*half_w]
    q = np.array(q, np.int32)

    # 头部框中心 → base
    Z = z0
    p_cam = np.array([(c_head[0]-K[0, 2])/K[0, 0]*Z, (c_head[1]-K[1, 2])/K[1, 1]*Z, Z])
    p_base = cam + R_c2b @ p_cam
    off = p_base - O
    print("头部绿框中心像素 (%.1f, %.1f) → base (%.1f, %.1f, %.1f)mm" % (c_head[0], c_head[1], *p_base))
    print("与控制器 tool1 差: %.1f mm  分量 %s" % (np.linalg.norm(off), np.round(off, 1)))
    print("模块像素: 长 %.0fpx 宽 %.0fpx · 尺度 %.3f mm/px ⇒ 长 %.1fmm 宽 %.1fmm" %
          (L, Wd, Z/K[0, 0], L*Z/K[0, 0], Wd*Z/K[0, 0]))

    vis = img.copy()
    cv2.polylines(vis, [q.reshape(-1, 1, 2)], True, (0, 255, 0), 2, cv2.LINE_AA)      # 绿色边界框
    cv2.circle(vis, tuple(np.int32(c_head)), 3, (0, 0, 255), -1)                       # 框中心(红点)
    cv2.putText(vis, "tool1(controller)", (int(uv0[0])+6, int(uv0[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1, cv2.LINE_AA)
    cv2.drawMarker(vis, tuple(np.int32(uv0)), (255, 0, 255), cv2.MARKER_CROSS, 14, 1)
    Lm, Wm = L*Z/K[0, 0], Wd*Z/K[0, 0]
    cv2.putText(vis, "head box center -> base offset %.1fmm" % np.linalg.norm(off),
                (6, vis.shape[0]-8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.imwrite("/home/ubuntu/mod_head_box.jpg", vis)
    json.dump({"uv0": [round(float(uv0[0]), 1), round(float(uv0[1]), 1)], "z_cam_mm": round(float(Z), 1),
               "module_px": {"L": round(L, 1), "W": round(Wd, 1)},
               "module_mm": {"L": round(Lm, 1), "W": round(Wm, 1)},
               "head_center_uv": [round(float(c_head[0]), 1), round(float(c_head[1]), 1)],
               "head_center_base_mm": [round(float(v), 1) for v in p_base],
               "offset_vs_tool1_mm": [round(float(v), 1) for v in off],
               "offset_norm_mm": round(float(np.linalg.norm(off)), 1),
               "green_box_uv": [[int(v[0]), int(v[1])] for v in q]},
              open("/home/ubuntu/mod_head_box.json", "w"), ensure_ascii=False, indent=1)
    print("图 → /home/ubuntu/mod_head_box.jpg")

if __name__ == "__main__":
    main()
