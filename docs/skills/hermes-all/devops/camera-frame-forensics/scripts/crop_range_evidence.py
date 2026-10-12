#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""crop_range_evidence.py — 成品图「被切/糊/跳」取证: 把裁切范围画在原图上 + 量三项

用法(默认参数就是本环境现役链路):
  gui-venv311/bin/python scripts/crop_range_evidence.py
  BOARD_URL=... JUDGE_URL=... ./crop_range_evidence.py

输出: 左 = 原图(框外压暗; 绿框=现在截取; 青线=独立量出的真实范围; 黄框=建议范围)
      右 = 现在那张成品图(放大) + 量到的数字;  存 PNG 到 tools/web/dl/ ⇒ 浏览器直接看。
同时 stdout 打: 框坐标 / 真实范围 / 被切几行 / 输出像素当量(横纵缩放) / 建议框。

适配别的链路: 换 BOARD_URL/JUDGE_URL/REPO, 并保证 `aoi_exposure_fix.clean_judge_frame` 在 REPO/tools 下
(它就是加工链本体 —— 截取框必须从它返回的 meta 里拿, 不要目测)。
"""
import os
import sys
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = os.environ.get("REPO", "/home/ubuntu/zmax")
BOARD_URL = os.environ.get("BOARD_URL", "http://127.0.0.1:8791/snapshot/aoi_gold_raw.jpg")
JUDGE_URL = os.environ.get("JUDGE_URL", "http://127.0.0.1:8791/snapshot/aoi_gold.jpg")
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(REPO, "tools", "web", "dl"))
FONT = os.environ.get("CJK_FONT", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
MIN_BLOBS = int(os.environ.get("MIN_BLOBS", "6"))      # 该行亮块 ≥N 个 ⇒ 判为在目标上
MARGIN = int(os.environ.get("MARGIN", "8"))            # 建议框四周余量(px)

sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)
from aoi_exposure_fix import clean_judge_frame, DEF  # noqa: E402


def grab(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(
        u, headers={"User-Agent": "zmax-audit"}), timeout=t).read()


def blob_profile(bgr, band=None):
    """逐行数亮块段(宽 6~40px)个数; band 给定时只在该行区间累加列剖面。"""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    cnt = np.zeros(g.shape[0], np.int32)
    cols = np.zeros(g.shape[1], np.float32)
    lo, hi = band if band else (0, g.shape[0] - 1)
    for y in range(g.shape[0]):
        row = g[y]
        bg = np.median(row); hi_v = np.percentile(row, 97)
        thr = bg + 0.45 * max(6.0, hi_v - bg)
        ok = row > thr
        n, st = 0, None
        for i, v in enumerate(ok):
            if v and st is None:
                st = i
            elif not v and st is not None:
                if 6 <= i - st <= 40:
                    n += 1
                    if lo <= y <= hi:
                        cols[st:i] += 1.0
                st = None
        cnt[y] = n
    return cnt, cols


def longest_run(mask):
    ys = np.where(mask)[0]
    if not len(ys):
        return None
    runs, st = [], ys[0]
    for i in range(1, len(ys)):
        if ys[i] != ys[i - 1] + 1:
            runs.append((st, ys[i - 1])); st = ys[i]
    runs.append((st, ys[-1]))
    runs = [r for r in runs if r[1] - r[0] + 1 >= 4]
    return max(runs, key=lambda r: r[1] - r[0]) if runs else None


def main():
    t0 = time.strftime("%H%M%S")
    board = cv2.imdecode(np.frombuffer(grab(BOARD_URL), np.uint8), cv2.IMREAD_COLOR)
    judge = cv2.imdecode(np.frombuffer(grab(JUDGE_URL), np.uint8), cv2.IMREAD_COLOR)
    H, W = board.shape[:2]

    _clean, meta = clean_judge_frame(cv2.cvtColor(board, cv2.COLOR_BGR2RGB),
                                     out=900, return_natural=True)
    if not meta.get("ok"):
        print("⛔ 加工链在当前帧上没给出参数: %s" % str(meta)[:200])
        print("   (目标不在位/全过曝时属正常 —— 先确认工件在位再取证)")
        return 1
    y0, y1 = meta["kept_rows"]
    x0, x1 = (meta.get("x_trim") or {}).get("x_span") or (0, meta["src_w"])
    best = meta.get("candidate") or {}

    cnt, _ = blob_profile(board)
    band = longest_run(cnt >= MIN_BLOBS)
    _cnt2, cols = blob_profile(board, band) if band else (cnt, np.zeros(W, np.float32))
    xs = np.where(cols > 0)[0]
    xlo, xhi = (int(np.percentile(xs, 1)), int(np.percentile(xs, 99))) if len(xs) else (0, W - 1)
    sug = (max(0, xlo - MARGIN), max(0, (band[0] if band else y0) - MARGIN),
           min(W - 1, xhi + MARGIN), min(H - 1, (band[1] if band else y1) + MARGIN))

    up = max(0, y0 - (band[0] if band else y0))
    dn = max(0, (band[1] if band else y1) - y1)
    strip_w, strip_h = (meta.get("src_w") or W), max(1, y1 - y0)
    cw, ch = 900 * 0.96, 332 * 0.68          # 输出内容区(按定尺与留白比例; 换口径自行改)
    sx, sy = cw / float(strip_w), ch / float(strip_h)

    print("=" * 92)
    print("原图 %dx%d   (画框所用坐标系)" % (W, H))
    print("① 现在截取框 : x %d~%d (w=%d) · y %d~%d (h=%d)   [检测带 %s~%s + pad %s, 列裁 %s]" %
          (x0, x1, x1 - x0, y0, y1, y1 - y0, best.get("y0"), best.get("y1"), DEF["pad"], "全宽" if x0 == 0 and x1 >= W else "已裁"))
    if band:
        print("② 真实范围   : y %d~%d (h=%d) · x %d~%d (w=%d, 占宽 %.0f%%)  ⇒ 上少 %d 行 / 下少 %d 行" %
              (band[0], band[1], band[1] - band[0] + 1, xlo, xhi, xhi - xlo, 100.0 * (xhi - xlo) / W, up, dn))
    print("③ 输出像素当量: 源条带 %dx%d ⇒ 内容 %.0fx%.0f ⇒ 横 x%.2f (1 out px = %.2f src px) · 纵 x%.2f (1 out px = %.2f src px)" %
          (strip_w, strip_h, cw, ch, sx, 1 / sx, sy, 1 / sy))
    print("④ 建议框     : x %d~%d (w=%d) · y %d~%d (h=%d)" % (sug[0], sug[2], sug[2] - sug[0], sug[1], sug[3], sug[3] - sug[1]))

    # ── 画图 ──
    pad_r = 760
    canvas = np.zeros((H, W + pad_r + 24, 3), np.uint8); canvas[:] = (24, 26, 30)
    vis = board.copy()
    if band:
        vis[:band[0]] = (vis[:band[0]].astype(np.float32) * 0.42).astype(np.uint8)
        vis[band[1]:] = (vis[band[1]:].astype(np.float32) * 0.42).astype(np.uint8)
    cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 3)                       # 绿 = 现在
    if band:
        cv2.line(vis, (0, band[0]), (W - 1, band[0]), (255, 210, 60), 2, cv2.LINE_AA)   # 青(BGR!)
        cv2.line(vis, (0, band[1]), (W - 1, band[1]), (255, 210, 60), 2, cv2.LINE_AA)
    cv2.rectangle(vis, (sug[0], sug[1]), (sug[2], sug[3]), (0, 220, 255), 3)     # 黄 = 建议
    canvas[:H, :W] = vis
    sc = 720.0 / judge.shape[1]
    jr = cv2.resize(judge, (720, int(judge.shape[0] * sc)), interpolation=cv2.INTER_NEAREST)
    jx, jy = W + 24, 96
    canvas[jy:jy + jr.shape[0], jx:jx + jr.shape[1]] = jr[:max(0, H - jy), :pad_r]

    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    f_b = ImageFont.truetype(FONT, 34); f_m = ImageFont.truetype(FONT, 26); f_s = ImageFont.truetype(FONT, 22)
    d.text((14, 10), "① 原图(页面看到的那张) %dx%d —— 框 = 加工图实际截取的范围" % (W, H), font=f_b, fill=(255, 255, 255))
    d.text((14, 54), "绿框 = 现在截取: y %d~%d (高 %d 行, 占 %.1f%%), x %s" %
           (y0, y1, y1 - y0, 100.0 * (y1 - y0) / H, "全宽 %d" % W if x0 == 0 and x1 >= W else "%d~%d" % (x0, x1)),
           font=f_m, fill=(80, 255, 80))
    if band:
        d.text((14, 88), "青线 = 真实范围(独立口径): y %d~%d (高 %d) ⇒ 上少 %d 行 · 下少 %d 行" %
               (band[0], band[1], band[1] - band[0] + 1, up, dn), font=f_m, fill=(255, 210, 60))
    d.text((14, 122), "黄框 = 建议范围: x %d~%d (宽 %d) · y %d~%d (高 %d)" %
           (sug[0], sug[2], sug[2] - sug[0], sug[1], sug[3], sug[3] - sug[1]), font=f_m, fill=(0, 235, 255))
    d.text((jx, 14), "② 现在的加工图 %dx%d" % (judge.shape[1], judge.shape[0]), font=f_b, fill=(255, 255, 255))
    d.text((jx, 54), "糊: 横 x%.2f 压缩 · 纵 x%.2f 拉伸 (1 out px = %.2f src px)" % (sx, sy, 1 / sy), font=f_m, fill=(255, 190, 120))
    d.text((jx, jy + jr.shape[0] + 16), "跳: 源带每帧抖 ±1px × 放大 %.2f ⇒ 屏上 ±%dpx" % (sy, max(1, int(round(sy)))), font=f_s, fill=(255, 190, 120))
    d.text((jx, jy + jr.shape[0] + 46), "（逐帧跳变请用 MJPEG 流量: 快照槽没人看时是冻帧, 会误判\"不跳\"）", font=f_s, fill=(200, 210, 220))

    os.makedirs(OUT_DIR, exist_ok=True)
    fp = os.path.join(OUT_DIR, "crop_range_%s.png" % t0)
    img.save(fp)
    print("⑤ 已写: %s" % fp)
    print("   看: http://<host>:8799/dl/%s   (8799 的 CT 表没有 .jpg ⇒ 必须存 PNG 才能内嵌显示)" % os.path.basename(fp))
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
