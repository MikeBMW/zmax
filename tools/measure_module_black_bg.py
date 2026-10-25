#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""黑底板下重测光模块外形 (臂相机).

判据: 黑底板 ⇒ 模块是画面里最亮的细长连通域。取最大细长亮块 → PCA 主轴 = 长轴,
垂直方向 = 宽度; 厚度取不到(只看到顶面), 由顶面/侧壁亮度台阶或标称给出。
尺度: 模块头固定距相机 244.1mm(手眼刚性) ⇒ 0.619 mm/px @f=394.06; 沿长轴用两端各自深度校正。
"""
import json, os, urllib.request
import cv2, numpy as np

REPO = os.path.expanduser("~/zmax")

def main():
    b = urllib.request.urlopen("http://127.0.0.1:8797/snap/arm.jpg", timeout=10).read()
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    d = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/tcp", timeout=6).read().decode())
    print("帧", img.shape, "字节", len(b), "| TCP age %.2fs" % d.get("age_s"))

    he = json.load(open(os.path.join(REPO, "models", "handeye_state.json")))
    M = np.array(he["T_cam2tool"], float)
    Zc = float(np.linalg.norm(M[:3, 3])) * (1.0 if np.abs(M[:3, 3]).max() >= 10 else 1000.0)
    cal = json.load(open(os.path.join(REPO, "models", "real_cam_calib.json")))
    K = np.array(cal["K"], float).reshape(3, 3)
    f = float(K[0, 0])
    print("相机↔模块头 = %.1fmm · f=%.2f ⇒ %.3f mm/px (在该深度)" % (Zc, f, Zc / f))

    best = None
    for th in range(90, 221, 10):
        m = ((g > th).astype(np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, st, cent = cv2.connectedComponentsWithStats(m, 8)
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if a < 300: continue
            pts = np.column_stack(np.nonzero(lab == i))            # (y,x)
            if len(pts) < 50: continue
            p = pts[:, ::-1].astype(np.float32)                    # (x,y)
            mean = p.mean(0)
            u, s, vt = np.linalg.svd(p - mean, full_matrices=False)
            axis = vt[0]                                            # 长轴
            proj = (p - mean) @ axis
            L = float(proj.max() - proj.min())
            Wd = float(((p - mean) @ vt[1]).max() - ((p - mean) @ vt[1]).min())
            fill = a / max(1.0, L * max(Wd, 1e-6))
            if L < 20 or Wd < 3: continue
            aspect = L / max(Wd, 1e-6)
            # 尺寸窗口: 56.5mm@244mm/0.619 ≈ 91px 长, 13.4mm ≈ 22px 宽 ⇒ 只认像模块的尺度,
            #   否则整片亮背景以 322x140px 的"细长块"胜出 (实测踩过)
            if not (45 <= L <= 150 and 6 <= Wd <= 50): continue
            if not (2.0 <= aspect <= 6.0) or fill < 0.55: continue
            if y < 80: continue                      # 顶部多半是背景/墙
            score = a
            if best is None or score > best["area"]:
                ang = float(np.degrees(np.arctan2(axis[1], axis[0])))
                best = dict(area=int(a), bbox=[int(x), int(y), int(w), int(h)],
                            L_px=round(L, 1), W_px=round(Wd, 1), aspect=round(aspect, 2),
                            fill=round(fill, 2), th=int(th), ang=round(ang, 1),
                            center=[round(float(mean[0]), 1), round(float(mean[1]), 1)],
                            ends=[[round(float(mean[0] + axis[0] * proj.max()), 1), round(float(mean[1] + axis[1] * proj.max()), 1)],
                                  [round(float(mean[0] + axis[0] * proj.min()), 1), round(float(mean[1] + axis[1] * proj.min()), 1)]])
    if not best:
        print("⛔ 没有找到细长亮块 (可能需要调阈值/ROI)")
        return
    print("最佳亮块:", json.dumps(best, ensure_ascii=False))
    sc = Zc / f
    print("⇒ 可见长 %.1fpx = %.1fmm · 宽 %.1fpx = %.1fmm (尺度 %.3f mm/px)" %
          (best["L_px"], best["L_px"] * sc, best["W_px"], best["W_px"] * sc, sc))

    # 叠加标注图, 便于人眼复核
    vis = img.copy()
    x, y, w, h = best["bbox"]
    cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 1)
    c = best["center"]; ang = np.radians(best["ang"])
    ax = np.array([np.cos(ang), np.sin(ang)])
    p1 = (int(c[0] - ax[0] * best["L_px"] / 2), int(c[1] - ax[1] * best["L_px"] / 2))
    p2 = (int(c[0] + ax[0] * best["L_px"] / 2), int(c[1] + ax[1] * best["L_px"] / 2))
    cv2.line(vis, p1, p2, (0, 255, 255), 1)
    cv2.putText(vis, "L%.0fpx %.0fmm W%.0fpx %.0fmm" % (best["L_px"], best["L_px"] * sc, best["W_px"], best["W_px"] * sc),
                (6, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.imwrite("/home/ubuntu/mod_meas_black.png", vis)
    json.dump(best, open("/home/ubuntu/mod_meas_black.json", "w"), ensure_ascii=False, indent=1)
    print("标注图 → /home/ubuntu/mod_meas_black.png")

if __name__ == "__main__":
    main()
