#!/usr/bin/env python3
"""开拍前判「这一帧值不值得建」: 用彩色+深度量化画面构成, 不靠目测。

为什么要有这个: 3DGS 的 PSNR 天花板由视角覆盖**和场景本身有没有几何线索**共同决定。
对着「一大片平面 + 大比例远景」走一圈, 转角再够也建不出东西 —— 这类场子要当场换对象/靠近,
而不是走完 90 秒再发现只有 13dB。

指标与判据(实测标定, 640x480 D405):
  · 主体占比(0.35~0.55m) 34~60%   太低=离太远/对着空处
  · 远景占比(>1.0m)      <10%     越高越是墙/窗, 对重建是负贡献
  · 画面中心深度          250~350mm  D405 精度最好区
  · 中心清晰度(拉普拉斯方差) >250    正常 350~550, <200 = 糊了/走太快/低纹理
  · 过曝像素(>250)        <2%      纯白面没有梯度, 高斯会糊成一片

用法:
  python3 scene_composition_probe.py --frame f.jpg --depth d.png \\
      --k 387.33,387.42,318.86,238.30 [--dots]
  # 图与深度从采集桥取: curl -o f.jpg <bridge>/frame.jpg; curl -o d.png <bridge>/depth.png
  # --k 用**去畸变后**的 K(见 SKILL: 采集端 remap 后 cameras.json 的 K, 不是原始标定 K)
  # --dots 额外核验画面里是不是标定板(交错圆点阵列) —— 标定板是平面, 对 3DGS 几乎不给几何线索
"""
import argparse
import sys

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", required=True)
    ap.add_argument("--depth", required=True)
    ap.add_argument("--k", default="387.33,387.42,318.86,238.30", help="fx,fy,cx,cy(去畸变后)")
    ap.add_argument("--depth-scale-m", type=float, default=0.0001, help="D405 常用 0.1mm/计数")
    ap.add_argument("--dots", action="store_true", help="核验是否标定板(圆点阵列)")
    a = ap.parse_args()

    import cv2
    import numpy as np

    fx, fy, cx, cy = [float(x) for x in a.k.split(",")]
    im = cv2.imread(a.frame, cv2.IMREAD_COLOR)
    raw = cv2.imread(a.depth, cv2.IMREAD_UNCHANGED)
    if im is None or raw is None:
        print("[ERROR] 读不到 --frame / --depth", file=sys.stderr)
        return 2
    z = raw.astype(np.float32) * a.depth_scale_m
    h, w = z.shape
    valid = z[z > 0]
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)

    print("画面 %dx%d · 亮度 %.1f · 过曝(>250) %.1f%% · 深度有效 %.0f%%"
          % (w, h, g.mean(), 100 * (g > 250).mean(), 100 * (raw > 0).mean()))
    print("深度 p5 %.0fmm · p50 %.0fmm · p95 %.0fmm"
          % (np.percentile(valid, 5) * 1000, np.percentile(valid, 50) * 1000, np.percentile(valid, 95) * 1000))

    bands = ((0.10, 0.35, "近景"), (0.35, 0.55, "主体"), (0.55, 1.00, "台面"), (1.00, 9.0, "远景"))
    share = {}
    for lo, hi, name in bands:
        share[name] = 100.0 * float(((z >= lo) & (z < hi)).mean())
        print("  %-4s %.2f~%.2fm 占画面 %5.1f%%" % (name, lo, hi, share[name]))

    m = ((z >= 0.30) & (z <= 0.55)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, 8)
    subj = None
    if n > 1:
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, bw, bh, area = stats[i]
        zz = z[lab == i]
        zm = float(np.median(zz))
        subj = dict(area_pct=100.0 * area / (h * w), depth_mm=zm * 1000,
                    w_mm=bw * zm / fx * 1000, h_mm=bh * zm / fy * 1000)
        print("主体连通域: 占画面 %.1f%% · 中位 %.0fmm · 实测尺寸 ≈ %.0f x %.0f mm · 中心 (%d,%d)"
              % (subj["area_pct"], subj["depth_mm"], subj["w_mm"], subj["h_mm"],
                 int(cent[i][0]), int(cent[i][1])))
    else:
        print("主体连通域: 0.30~0.55m 内没有成片主体(相机对着空处/太近/太远)")

    reg = {"中央": g[140:340, 220:420], "左上": g[0:160, 0:200], "右上": g[0:160, 440:640], "下部": g[320:480, 200:440]}
    sharp = {k: float(cv2.Laplacian(v, cv2.CV_64F).var()) for k, v in reg.items()}
    print("清晰度: " + " · ".join("%s %.0f" % (k, v) for k, v in sharp.items()))

    if a.dots:
        par = cv2.SimpleBlobDetector_Params()
        par.filterByColor, par.blobColor = True, 255
        par.filterByArea, par.minArea, par.maxArea = True, 8, 400
        par.filterByCircularity, par.minCircularity = True, 0.55
        par.filterByConvexity = par.filterByInertia = False
        kp = cv2.SimpleBlobDetector_create(par).detect(cv2.GaussianBlur(g, (3, 3), 0))
        pts = sorted([(round(k.pt[0]), round(k.pt[1])) for k in kp], key=lambda t: (t[1], t[0]))
        rows = []
        for p in pts:
            if rows and p[1] - rows[-1][-1][1] < 8:
                rows[-1].append(p)
            else:
                rows.append([p])
        print("圆点核验: 检出 %d 点 / %d 行" % (len(pts), len(rows)), end="")
        if len(rows) >= 2 and len(rows[0]) >= 3:
            x0 = sorted(p[0] for p in rows[0])
            dx = (x0[-1] - x0[0]) / max(1, len(x0) - 1)
            dy = abs(sum(p[1] for p in rows[1]) / len(rows[1]) - sum(p[1] for p in rows[0]) / len(rows[0]))
            print(" · 点距 ≈ %.0fpx · 行距 ≈ %.0fpx" % (dx, dy))
            print("  ⇒ 规则交错点阵 = 标定板: **平面 + 高对比纹理**, 对 3DGS 几乎不给几何线索"
                  " ⇒ 要么靠近让它占满画面并绕弧, 要么换有立体结构的工件")
        else:
            print(" (不足以判成点阵)")

    fails = []
    if not (15.0 <= share["主体"] <= 65.0):
        fails.append("主体占比 %.0f%% 不在 15~65%%" % share["主体"])
    if share["远景"] > 10.0:
        fails.append("远景占比 %.0f%% >10%% (墙/窗对重建是负贡献)" % share["远景"])
    if not (220.0 <= (subj or {}).get("depth_mm", 0) <= 400.0):
        fails.append("主体距离 %s 不在 220~400mm" % ("%.0fmm" % subj["depth_mm"] if subj else "无"))
    if sharp["中央"] < 250:
        fails.append("中央清晰度 %.0f <250 (糊/走太快/低纹理)" % sharp["中央"])
    if 100 * (g > 250).mean() > 2.0:
        fails.append("过曝 %.1f%% >2%%" % (100 * (g > 250).mean()))

    print("判定: " + ("可以开拍" if not fails else "先调整 —— " + "; ".join(fails)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
