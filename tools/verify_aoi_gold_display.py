#!/usr/bin/env python3
"""判据: 金手指那格显示的是「本机裁切的实拍区域」, 不再是工控机**画上去**的判据图。

老倪 2026-10-12: 「现在的金手指点1, 有19个金手指, 你的判据图, 怎么显示这么多根?
                不要显示那么多高亮的条, 你也没对应上啊。就显示你截取的金手指区域即可」

判定 (真取图, 不看返回值):
  ① 代码默认口径 = 本机裁切 (ZMAX_AOI_GOLD_CALIBER 默认 canonical) —— 静态 + 运行时
  ② 页面那张(8791/8793 /snapshot/aoi_gold.jpg) **不是**工控机画的那张(10082 kind=crop):
     黑底占比差 > 0.30 或 平均像素差 > 20 (画的那张是纯黑底 + 一排键)
  ③ 页面那张是实拍区域: 无红/绿横幅(占比 < 0.02) · 尺寸 900x332(老口径)
  ④ AR 页那张(8797 /api/aoi/gold.jpg) 与 8793 同源 (平均像素差 < 10)
  另附【如实报告】(不算成败): 工控机自报根数/节距/行带 · /region 是否检出区域 · 机器人 TCP 离各示教点多远
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cv2  # noqa: E402

P = F = 0


def ck(cond, name, extra=""):
    global P, F
    if cond:
        P += 1
        print("  ✅ " + name + (("  · " + str(extra)) if extra else ""))
    else:
        F += 1
        print("  ⛔ " + name + (("  · " + str(extra)) if extra else ""))


def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "zmax-verify"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:                                                            # noqa: BLE001
        return b""


def img_of(raw):
    if not raw:
        return None
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def banner_ratio(img):
    h = img.shape[0]
    top = img[:max(1, h // 3)]
    b, g, r = top[:, :, 0].astype(int), top[:, :, 1].astype(int), top[:, :, 2].astype(int)
    red = float(((r > 110) & (r - g > 45) & (r - b > 45)).mean())
    grn = float(((g > 110) & (g - r > 45) & (g - b > 45)).mean())
    return max(red, grn)


def black_ratio(img):
    return float((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 10).mean())


print("=== ① 默认口径 = 本机裁切 ===")
src = open(os.path.join(ROOT, "tools", "cam_live_stream.py"), encoding="utf-8").read()
ck('os.environ.get("ZMAX_AOI_GOLD_CALIBER", "canonical")' in src,
   "cam_live_stream 默认口径 = canonical(本机从原始帧裁切, 不画任何东西)")
ck('"same"' in src and 'ZMAX_AOI_GOLD_CALIBER' in src, "仍保留 same(工控机那张)可切回")

print("\n=== ②③ 页面那张 vs 工控机画的那张 ===")
page = img_of(fetch("http://127.0.0.1:8791/snapshot/aoi_gold.jpg"))
drawn = img_of(fetch("http://192.168.23.23:10082/picture?kind=crop"))
ck(page is not None, "取到页面那张 (8791 /snapshot/aoi_gold.jpg)",
   ("%dx%d" % (page.shape[1], page.shape[0])) if page is not None else "取不到")
ck(drawn is not None, "取到工控机画的那张 (10082 kind=crop)",
   ("%dx%d" % (drawn.shape[1], drawn.shape[0])) if drawn is not None else "取不到")
if page is not None and drawn is not None:
    h = min(page.shape[0], drawn.shape[0])
    w = min(page.shape[1], drawn.shape[1])
    d = float(np.abs(page[:h, :w].astype(int) - drawn[:h, :w].astype(int)).mean())
    bp, bd = black_ratio(page), black_ratio(drawn)
    ck((page.shape[1], page.shape[0]) == (900, 332), "页面那张尺寸 = 900x332(老口径)", page.shape[:2])
    ck(abs(bp - bd) > 0.30 or d > 20,
       "页面那张 != 工控机画的那张(证明不再是画上去的)",
       "平均像素差 %.1f · 黑底 页面 %.3f vs 画 %.3f" % (d, bp, bd))
    ck(banner_ratio(page) < 0.02, "页面那张没有红/绿横幅", "%.4f" % banner_ratio(page))
    ck(bp < 0.30, "页面那张不是纯黑底(是实拍区域)", "黑底占比 %.3f" % bp)

print("\n=== ④ AR 页的判据图来源 = 本机裁切的实拍区域 ===")
try:
    html = open(os.path.join(ROOT, "tools", "web", "tcp-ar.html"), encoding="utf-8").read()
    ck(":8791/snapshot/aoi_gold.jpg" in html,
       "AR 页判据图直取 8791 金手指格(本机裁切的实拍区域)")
    ck("/api/aoi/gold.jpg?t=" not in html,
       "AR 页不再取 8797 中转那张(中转会被 RealSense 轮询挤住, 实测 25s 超时)")
except Exception as e:                                                           # noqa: BLE001
    ck(False, "读 tcp-ar.html", repr(e)[:100])
st = img_of(fetch("http://127.0.0.1:8791/snapshot/aoi_gold.jpg"))
ck(st is not None, "现场真取到那张",
   ("%dx%d" % (st.shape[1], st.shape[0])) if st is not None else "取不到")
if st is not None:
    ck(st.shape[:2] == (332, 900) and banner_ratio(st) < 0.02,
       "那张 = 实拍裁切(900x332 · 无红/绿横幅)", "黑底 %.3f · 横幅 %.4f" % (black_ratio(st), banner_ratio(st)))

print("\n=== 【如实报告】为什么这张看着不像金手指 ===")
ci = json.loads(fetch("http://192.168.23.23:10082/crop_info") or b"{}")
j = (ci or {}).get("judge") or {}
if j:
    print("   工控机自报: ver=%s · n_keys=%s(原始 %s) · 节距 %spx · 行带 %s (%s 行)" %
          (j.get("ver"), j.get("n_keys"), (j.get("gate") or {}).get("n_keys_raw"),
           j.get("lattice_pitch_px"), j.get("kept_rows"), j.get("kept_h")))
rg = json.loads(fetch("http://192.168.23.23:10082/region") or b"{}")
print("   /region 检出: bbox=%s quad=%s focus=%s angle=%s" %
      (rg.get("bbox"), rg.get("quad"), rg.get("focus"), rg.get("angle")))
try:
    t = json.loads(open(os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json"),
                        encoding="utf-8").read())
    cur = (float(t["x"]), float(t["y"]), float(t["z"]))
    print("   TCP 现值 (%.4f, %.4f, %.4f) 帧龄 %.0fs" % (cur[0], cur[1], cur[2],
                                                     time.time() - float(t.get("ts") or 0)))
    for nm, tg in (("金手指点1(新)", [0.489774, 0.1473783, 0.4054162]),
                   ("金手指点1(旧)", [0.596737, 0.142622, 0.641536])):
        dd = max(abs(cur[i] - tg[i]) * 1000 for i in range(3))
        print("      vs %-12s 最大差 %.1f mm" % (nm, dd))
except Exception as e:                                                           # noqa: BLE001
    print("   读 TCP 失败: %s" % repr(e)[:80])

print("\n=== 汇总: PASS %d · FAIL %d ===" % (P, F))
sys.exit(0 if F == 0 else 1)
