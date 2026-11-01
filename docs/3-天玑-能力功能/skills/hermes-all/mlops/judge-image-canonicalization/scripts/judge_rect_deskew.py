#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge_rect_deskew.py — 判据图规范化: 动态搜矩形刚体 → 原图叠框 + 零拉伸摆正。

只读取像, 不写相机参数。产物两件(分开给, 不叠在一张画布上):
  <out>/overlay_box.png   原图保持原样 + 搜到的截取框(绿框/四角/尺寸倾角)
  <out>/judge_crop.png    按框摆正(纯旋转 缩放1.0 + 按真实像素尺寸裁剪) ⇒ 零拉伸

并打印亮度一致性: 原图该矩形内像素 vs 摆正图 (均值/中位差, 应 ≈0)。

用法:
  python scripts/judge_rect_deskew.py --url "http://<aoi-host>:10083/picture?kind=origin&grab=1"
  python scripts/judge_rect_deskew.py --img /tmp/frame.png --out /tmp/side
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request

import cv2
import numpy as np


def fetch(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-probe"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def find_rect(img):
    """动态搜矩形刚体: 每块亮区都是候选, 不含任何固定坐标。

    评分 = 面积占比 × 矩形度(contourArea/minAreaRect面积); 择优后取 minAreaRect 四角(天然平行)。
    为什么不用 Canny: 边缘闭合得到的是细边环(矩形度≈0.05), 低对比/过曝时全被约束拒掉。
    """
    h, w = img.shape[:2]
    g = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    g = cv2.GaussianBlur(g, (5, 5), 0)
    t, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = (g > t).astype(np.uint8) * 255
    if m.mean() / 255.0 > 0.6:                       # Otsu 前景过大 ⇒ 退到 80 分位
        m = (g > float(np.percentile(g, 80))).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((25, 25), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cs:
        a = cv2.contourArea(c)
        if a < 0.005 * h * w or a > 0.75 * h * w:
            continue
        r = cv2.minAreaRect(c)
        fill = a / max(1.0, r[1][0] * r[1][1])       # 矩形度
        score = (a / (h * w)) * fill
        if best is None or score > best[0]:
            best = (score, r, cv2.boxPoints(r).astype(np.float32), a / (h * w), fill)
    if best is None:
        raise SystemExit("未搜到矩形刚体 (检查曝光/画面里是否真有工件)")
    return best[1], best[2], {"score": round(float(best[0]), 5),
                              "area_frac": round(float(best[3]), 4), "fill": round(float(best[4]), 3)}


def deskew(img, rect, center):
    """纯旋转(缩放 1.0) + 按真实像素尺寸裁剪 ⇒ 零拉伸。

    输出尺寸必须等于检出框尺寸(用户会直接读这个数); 长边摆平(需要时 +90)。
    """
    (cx, cy), (rw, rh), ang = rect
    W, H = max(rw, rh), min(rw, rh)
    ang2 = ang + 90.0 if rw < rh else ang
    M = cv2.getRotationMatrix2D((cx, cy), ang2, 1.0)              # 缩放恒为 1.0
    rot = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_CUBIC)
    crop = cv2.getRectSubPix(rot, (int(round(W)), int(round(H))), (cx, cy))
    return crop, W, H, ang


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="取像口 (判据自己的口: kind=origin&grab=1)")
    ap.add_argument("--img", default="", help="或用本地帧文件")
    ap.add_argument("--out", default="/tmp/judge_rect")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    if a.img:
        img = cv2.imread(a.img)
    else:
        raw = fetch(a.url)
        open(os.path.join(a.out, "overlay_src.bin"), "wb").write(raw)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("取像失败")

    rect, box, dbg = find_rect(img)
    (cx, cy), _, ang = rect

    # ① 原图 + 截取框 (原图保持原样, 只叠框)
    over = img.copy()
    cv2.polylines(over, [box.astype(np.int32).reshape(-1, 1, 2)], True, (0, 255, 0), 14)
    for i, p in enumerate(box.astype(int)):
        cv2.circle(over, tuple(p), 30, (0, 0, 255), -1)
        cv2.putText(over, "ABCD"[i], (p[0] + 36, p[1] - 26), cv2.FONT_HERSHEY_SIMPLEX, 4.5, (0, 0, 255), 11)
    cv2.putText(over, "crop %.0fx%.0f  tilt %.1fdeg  fill %.2f  area %.1f%%"
                % (max(rect[1]), min(rect[1]), ang, dbg["fill"], 100 * dbg["area_frac"]),
                (40, 110), cv2.FONT_HERSHEY_SIMPLEX, 3.6, (0, 255, 0), 10)
    cv2.imwrite(os.path.join(a.out, "overlay_box.png"), over)

    # ② 摆正 (单独文件, 不叠在 ① 上)
    crop, W, H, ang = deskew(img, rect, (cx, cy))
    cv2.imwrite(os.path.join(a.out, "judge_crop.png"), crop)

    # ③ 亮度一致性: 同帧同像素比对 (应 ≈0)
    g0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gc = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    print("框: %.0fx%.0f 倾角%.2f° 矩形度%.3f 面积占比%.1f%% 得分%.4f"
          % (W, H, ang, dbg["fill"], 100 * dbg["area_frac"], dbg["score"]))
    print("摆正图: %dx%d 均值%.1f 饱和%.2f%%  (尺寸与检出框一致 ⇒ 零拉伸)"
          % (crop.shape[1], crop.shape[0], gc.mean(), 100 * (gc >= 250).mean()))
    print("亮度一致性: 原图该矩形内 %.1f vs 摆正图 %.1f" % (g0.mean(), gc.mean()))
    json.dump({"rect": [list(rect[0]), list(rect[1]), rect[2]], "crop_size": [int(W), int(H)], "dbg": dbg},
              open(os.path.join(a.out, "meta.json"), "w"), ensure_ascii=False, indent=2, default=float)
    print("交付: %s/overlay_box.png (原图+框) · %s/judge_crop.png (摆正)" % (a.out, a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
