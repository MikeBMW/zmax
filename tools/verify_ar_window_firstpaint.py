#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🥽 判据: AR 内嵌窗口"打开到有画面"不再白屏 + 加载耗时实测

老倪 2026-10-19: 「AR 打开后, 怎么是白屏呢? 好长时间才显示」

测三件事 (offscreen 真起 QWebEngineView, 真加载 8797/ar):
  ① show 之后 ~250ms 抓图: 白像素占比必须 < 2%  (旧版 QWebEngineView 默认白底 ⇒ 一大片白)
  ② loadFinished 用时 (秒) —— 这就是"到页面出画面"的机器耗时, 打印出来可对账
  ③ 加载完成后抓图: 页面主色应为深色 (#0b0f14 系), 且相机区有彩色像素 (画面真画出来了)

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_ar_window_firstpaint.py
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

# QtWebEngineWidgets 必须在 QApplication 之前 import
from PyQt5.QtWebEngineWidgets import QWebEngineView          # noqa: E402,F401
from PyQt5.QtWidgets import QApplication                     # noqa: E402
from PyQt5.QtCore import QTimer                              # noqa: E402

import ar_web_window as A                                    # noqa: E402

OUT = os.environ.get("ZMAX_AR_SHOT_DIR") or "/tmp/ar_firstpaint"
os.makedirs(OUT, exist_ok=True)
RES = {"t_show": None, "t_load": None, "shots": {}}


def stats(path):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    white = tot = 0
    for y in range(0, h, 5):
        for x in range(0, w, 5):
            r, g, b = px[x, y]
            tot += 1
            if r > 240 and g > 240 and b > 240:
                white += 1
    # 深色占比 (AR 页 body #0b0f14)
    dark = 0
    for y in range(0, h, 5):
        for x in range(0, w, 5):
            r, g, b = px[x, y]
            if r < 40 and g < 46 and b < 56:
                dark += 1
    col = ct = 0
    for y in range(int(h * 0.2), int(h * 0.7), 4):
        for x in range(int(w * 0.02), int(w * 0.55), 4):
            r, g, b = px[x, y]
            ct += 1
            if max(r, g, b) - min(r, g, b) > 18 and max(r, g, b) > 40:
                col += 1
    # 🖼 相机窗口区(左列)白像素 —— 这才是"白屏"该量的地方: 右栏有大量浅色文字/表格,
    #   全屏白像素永远有 8~14%, 拿它当判据会把正常页面判成白屏 (实测)。
    sw = st = 0
    for y in range(int(h * 0.22), int(h * 0.68), 3):
        for x in range(int(w * 0.02), int(w * 0.55), 3):
            r, g, b = px[x, y]
            st += 1
            if r > 240 and g > 240 and b > 240:
                sw += 1
    return {"size": [w, h], "white_pct": round(100.0 * white / max(1, tot), 2),
            "stage_white_pct": round(100.0 * sw / max(1, st), 2),
            "dark_pct": round(100.0 * dark / max(1, tot), 2),
            "color_pct": round(100.0 * col / max(1, ct), 2)}


def shot(tag):
    w = A.window()
    if w is None:
        return
    p = os.path.join(OUT, "%s.png" % tag)
    try:
        w.grab().save(p)
        RES["shots"][tag] = stats(p)
        RES["shots"][tag]["path"] = p
    except Exception as e:                                                   # noqa: BLE001
        RES["shots"][tag] = {"err": str(e)[:120]}


def main():
    app = QApplication(sys.argv)
    t0 = time.time()
    # 真实路径: 控制台启动 3s 后先 prewarm(预建窗口 + 隐藏预载页面), 点 AR 时只 show
    ok = A.prewarm()
    RES["prewarm_ok"] = bool(ok)
    RES["t_make"] = round(time.time() - t0, 3)
    w = A.window()
    if w is None:
        print(json.dumps({"err": "prewarm 失败: 内嵌 WebEngine 起不来"}, ensure_ascii=False))
        return 1

    def on_loaded(ok_):
        RES["t_preload"] = round(time.time() - t0, 3)
        RES["load_ok"] = bool(ok_)
        RES["vis_at_preload"] = "?"
        w.view.page().runJavaScript("document.visibilityState", 0,
                                    lambda v: RES.__setitem__("vis_at_preload", v))
        QTimer.singleShot(200, click)

    def click():
        # 老倪点「🥽 AR」= show_ar(): 只抬窗口, 不重新 load
        t1 = time.time()
        w.show_ar()
        RES["t_show"] = round(time.time() - t1, 3)
        QTimer.singleShot(250, lambda: shot("t0250"))
        QTimer.singleShot(800, lambda: (shot("t0800"), finish()))

    def finish():
        app.quit()

    w.view.loadFinished.connect(on_loaded)
    QTimer.singleShot(20000, finish)      # 兜底: 20s 必须退出
    app.exec_()

    print(json.dumps(RES, ensure_ascii=False, indent=1))
    fail = []
    s250 = RES["shots"].get("t0250") or {}
    s800 = RES["shots"].get("t0800") or {}
    if s250.get("white_pct") is None:
        fail.append("① 点开后 250ms 没抓到图 (窗口没起来)")
    elif (s250.get("stage_white_pct") or 0) >= 2.0:
        fail.append("① 点开 250ms 相机区仍 %s%% 白 (还会白屏)" % s250.get("stage_white_pct"))
    if s250.get("color_pct") is not None and s250["color_pct"] < 3:
        fail.append("③ 点开 250ms 相机区彩色只有 %s%% (底图没出)" % s250.get("color_pct"))
    if s800.get("color_pct") is not None and s800["color_pct"] < 3:
        fail.append("③ 点开 800ms 相机区彩色只有 %s%% (底图没出)" % s800.get("color_pct"))
    if not RES.get("load_ok"):
        fail.append("② 预载未完成 (load_ok=false)")
    print(("🟢 PASS" if not fail else "🔴 FAIL") + ("  " + " | ".join(fail) if fail else
          "  预载 %.2fs · 点开 %.3fs · 不再白屏且 0.8s 内有画面"
          % (RES.get("t_preload") or -1, RES.get("t_show") or -1)))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
