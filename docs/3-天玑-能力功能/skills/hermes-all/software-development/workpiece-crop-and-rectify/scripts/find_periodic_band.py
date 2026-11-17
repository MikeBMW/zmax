#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""find_periodic_band.py — 判据图行带取证工具（无视觉工具时也能“看”到图）

用途：用户说「看不到目标结构 / 裁错了 / 太小太窄」时，先用这个工具在一帧原图上做三件事：
  1) 用**列自相关周期 × 对比度**找候选行带（不依赖模板框 / ROI）
  2) 打印整帧与候选带的 ASCII 缩略图（几秒看出“这条带里到底有没有目标”）
  3) 给出带内亮度/对比/节距，供判断“是裁错位置”还是“是太暗”

用法:
  python find_periodic_band.py --image frame.png
  python find_periodic_band.py --url 'http://HOST:PORT/picture?kind=origin&grab=1'
  python find_periodic_band.py --image frame.png --top 3      # 列前 3 个候选带
  python find_periodic_band.py --image frame.png --crop band.png   # 把最优带存盘

注：同节距的周期带可能不止一条（焊盘排/键排/纹理），**统计量只能证明“有周期”**；
    是不是用户点名的那个结构，要用 ASCII 缩略图或让用户指认。
"""
import argparse
import sys

import cv2
import numpy as np

CHARS = " .:-=+*#%@"


def load(src_image=None, url=None):
    if url:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "zmax-probe"})
        buf = np.frombuffer(urllib.request.urlopen(req, timeout=20).read(), np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(src_image, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit("读图失败: %s" % (url or src_image))
    return img


def gray_of(img):
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return img.astype(np.float32)


def ascii_art(g, cols=110, rows=18):
    s = cv2.resize(g, (cols, rows), interpolation=cv2.INTER_AREA)
    lo, hi = np.percentile(s, 3), np.percentile(s, 97)
    n = np.clip((s - lo) / max(1e-6, hi - lo), 0, 1)
    return "\n".join("".join(CHARS[int(v * (len(CHARS) - 1))] for v in r) for r in n)


def score_band(pr, lo, hi):
    """列剖面的周期性打分: 自相关峰 × 对比度置信。"""
    pr = pr - float(pr.mean())
    sd = float(pr.std())
    if sd < 6.0 or hi <= lo:
        return 0.0, 0.0, 0, sd
    ac = np.correlate(pr, pr, "full")[len(pr) - 1:]
    ac = ac / (float(ac[0]) + 1e-9)
    seg = ac[lo:hi]
    lag = lo + int(np.argmax(seg))
    r = float(ac[lag])
    return r * min(1.0, sd / 45.0), r, lag, sd


def find_bands(g, want=3, min_r=0.55, min_contrast=15.0):
    H, W = g.shape
    sc = min(1.0, 1200.0 / float(max(1, W)))
    small = cv2.resize(g, (int(W * sc), int(H * sc)), interpolation=cv2.INTER_AREA) if sc < 1.0 else g
    h, w = small.shape
    lo, hi = max(20, int(40 * sc)), min(w - 1, int(100 * sc))
    cands = []
    for hh in (40, 50, 60, 70, 80, 90, 110, 130):
        if hh >= h:
            continue
        for y in range(int(h * 0.10), h - hh, max(6, hh // 8)):
            score, r, lag, sd = score_band(small[y:y + hh].mean(axis=0), lo, hi)
            if r < min_r or sd < min_contrast:
                continue
            cands.append({
                "score": score, "r": r, "contrast": sd,
                "pitch": lag / sc, "y0": int(y / sc), "y1": int((y + hh) / sc),
            })
    # 去重: 同一带被多个步长命中 ⇒ 保留分高的
    out = []
    for c in sorted(cands, key=lambda d: -d["score"]):
        if all(abs(c["y0"] - o["y0"]) > 0.4 * (o["y1"] - o["y0"]) for o in out):
            out.append(c)
        if len(out) >= want:
            break
    for c in out:
        band = g[c["y0"]:c["y1"]]
        c["mean"] = float(band.mean())
        c["h"] = c["y1"] - c["y0"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--url")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--crop")
    a = ap.parse_args()
    img = load(a.image, a.url)
    g = gray_of(img)
    print("帧尺寸: %dx%d  整帧 mean=%.1f" % (g.shape[1], g.shape[0], g.mean()))
    print("\n=== 整帧缩略图 ===")
    print(ascii_art(g))

    bands = find_bands(g, want=a.top)
    if not bands:
        print("\n无合格行带(r>=0.55 且 对比>=15) ⇒ 可能太暗 / 目标不在位 / 节距不在 40~100px")
        return 1
    print("\n=== 候选行带 (按分数) ===")
    for i, c in enumerate(bands, 1):
        print("#%d y=%d..%d (高 %d) 节距 %.1fpx  r=%.2f  对比=%.0f  带内 mean=%.0f  score=%.2f"
              % (i, c["y0"], c["y1"], c["h"], c["pitch"], c["r"], c["contrast"], c["mean"], c["score"]))
    best = bands[0]
    print("\n=== 最优带缩略图 (y=%d..%d) ===" % (best["y0"], best["y1"]))
    print(ascii_art(g[best["y0"]:best["y1"]], cols=110, rows=12))
    if a.crop:
        cv2.imwrite(a.crop, img[best["y0"]:best["y1"]])
        print("\n已存: %s (%dx%d)" % (a.crop, img.shape[1], best["h"]))
    print("\n提醒: 统计量只证明“有周期”; 是不是用户点名的那个结构，看缩略图或请他指认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
