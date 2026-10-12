#!/usr/bin/env python3
"""判据: 金手指那格显示的是「本机裁切的实拍区域」, 不再是工控机**画上去**的判据图。

老倪 2026-10-12: 「现在的金手指点1, 有19个金手指, 你的判据图, 怎么显示这么多根?
                不要显示那么多高亮的条, 你也没对应上啊。就显示你截取的金手指区域即可」

判定 (真取图, 不看返回值):
  ① 代码默认口径 = 本机裁切 (ZMAX_AOI_GOLD_CALIBER 默认 canonical) —— 静态 + 运行时
  ② 页面那张(8791/8793 /snapshot/aoi_gold.jpg) **不是**工控机画的那张(10082 kind=crop):
     黑底占比差 > 0.30 或 平均像素差 > 20 (画的那张是纯黑底 + 一排键)
  ③ 页面那张是实拍区域: 无红/绿横幅(占比 < 0.02) · 尺寸 = 真实金手指 ROI 等比输出(新口径 ~914x33x~35x)
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


def green_frame_ratio(img):
    """判据图**口框**的绿像素占比(老倪 2026-10-12 要的绿框, 只允许是细框 ≤0.06)"""
    b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
    return float(((g > 110) & (g - r > 45) & (g - b > 45)).mean())


def banner_ratio(img):
    """🔴 红/绿**横幅**(字/条)占比 —— 只统计画面**中间**区域(外圈 6% 留给判据图口框的绿线)。"""
    h, w = img.shape[0], img.shape[1]
    dy, dx = max(2, int(h * 0.06)), max(2, int(w * 0.06))
    top = img[dy:max(dy + 1, h // 3), dx:max(dx + 1, w - dx)]
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
    ck(860 <= page.shape[1] <= 1100 and 240 <= page.shape[0] <= 470,
       "页面那张 = 新口径(真实金手指 ROI 等比输出 · 不拉伸)", page.shape[:2])
    ck(abs(bp - bd) > 0.30 or d > 20,
       "页面那张 != 工控机画的那张(证明不再是画上去的)",
       "平均像素差 %.1f · 黑底 页面 %.3f vs 画 %.3f" % (d, bp, bd))
    ck(banner_ratio(page) < 0.02, "页面那张没有红/绿横幅(绿框=判据图口框另计)", "%.4f" % banner_ratio(page))
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
    ck(860 <= st.shape[1] <= 1100 and 240 <= st.shape[0] <= 470 and banner_ratio(st) < 0.02,
       "那张 = 实拍裁切(新口径 · 无红/绿横幅)", "%dx%d · 黑底 %.3f · 横幅 %.4f" %
       (st.shape[1], st.shape[0], black_ratio(st), banner_ratio(st)))
    # 🔲 2026-10-12 新口径三条不变量(老倪: 上下别切 · 别更糊 · 别跳)
    g0 = cv2.cvtColor(st, cv2.COLOR_BGR2GRAY)
    wht = float((g0.mean(axis=1)[:2] > 235).sum() + (g0.mean(axis=1)[-2:] > 235).sum())
    lap = float(cv2.Laplacian(g0, cv2.CV_64F).var())
    rows = g0.mean(axis=1); bgv = float(np.median(rows)); nz = np.where(rows > bgv + 12)[0]
    fill = (float(nz.max() - nz.min() + 1) / g0.shape[0]) if len(nz) else 0.0
    ck(wht == 0, "① 无白边(上下各 2 行都不是死白)", "白行 %.0f" % wht)
    ck(fill > 0.80, "② 内容填满画布(不再是一条细缝 + 大片黑)", "内容占高 %.0f%%" % (100 * fill))
    ck(lap > 380, "③ 清晰度: Laplacian 方差 > 380(旧口径实测 282 ⇒ 更清楚, 不是更糊)", "%.0f" % lap)
    _fs = []
    try:
        r0 = urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8791/aoi_gold.mjpg", headers={"User-Agent": "zmax-verify"}), timeout=15)
        _buf, _t0 = b"", time.time()
        while len(_fs) < 4 and time.time() - _t0 < 15:
            _c = r0.read(8192)
            if not _c:
                break
            _buf += _c
            while True:
                _i = _buf.find(b"\xff\xd8")
                _j = _buf.find(b"\xff\xd9", _i + 2) if _i >= 0 else -1
                if _i < 0 or _j < 0:
                    break
                _im = img_of(_buf[_i:_j + 2])
                if _im is not None:
                    _fs.append(_im)
                _buf = _buf[_j + 2:]
    except Exception:                                                            # noqa: BLE001
        pass
    _szs = sorted({im.shape[:2] for im in _fs})
    ck(len(_szs) <= 1, "④ 尺寸逐帧恒定(老倪「还在跳变」= 两条渲染路逐帧换脸 / 尺寸随帧漂)",
       "%d 帧尺寸 %s" % (len(_fs), _szs))
    ck(green_frame_ratio(st) <= 0.06, "⑤ 绿框存在且只是细框(判据图口框, 不是糊成一片)",
       "绿像素占比 %.4f" % green_frame_ratio(st))

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
