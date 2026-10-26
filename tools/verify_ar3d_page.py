#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 判据: /ar3d 独立三维页 —— 一屏只有三维视图, 没有一个按钮

老倪 2026-10-26: 「三维视图要单独打开一个页面…完全独立的一个页面, 只有三维视图, 没有其它的按钮」

判据(全部真跑, offscreen 真起 QWebEngineView 加载 8797/ar3d):
  ① 可见按钮数 == 0(offsetParent 非空的 button 一个都没有)
  ② 画布 = 整屏: canvas CSS 宽高 == 视口, 且高度 ≥ 视口 - 2px
  ③ 页面不可滚动(scrollHeight ≤ 视口 + 2)—— 不用滚轮拖
  ④ 画布真有绘制(非背景像素 > 0.5%), 且绿色(URDF)/琥珀(光模块)至少出现一种
  ⑤ 对照: /ar 整页在同样条件下**有**可见按钮(证明判据不是恒真)
截图: /tmp/ar3d_verify.png · 用量: gui-venv311/bin/python tools/verify_ar3d_page.py
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt5.QtWebEngineWidgets import QWebEngineView          # noqa: E402,F401
from PyQt5.QtWidgets import QApplication                     # noqa: E402
from PyQt5.QtCore import QTimer, QUrl                        # noqa: E402

BASE = os.environ.get("ZMAX_AR3D_BASE") or "http://127.0.0.1:8797"
SHOT = "/tmp/ar3d_verify.png"

PROBE = r"""
(() => {
  const disp = el => el ? getComputedStyle(el).display : 'missing';
  const cv = document.getElementById('vr');
  const r = cv ? cv.getBoundingClientRect() : null;
  const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
  const out = {
    url: location.pathname + location.search,
    title: document.title,
    bodyClass: document.body.className,
    vw: innerWidth, vh: innerHeight,
    header: disp(document.querySelector('header')),
    rows: disp(document.querySelector('#vrcard .row')),
    h2: disp(document.querySelector('#vrcard h2')),
    canvas: r ? [Math.round(r.width), Math.round(r.height)] : null,
    canvasTop: r ? Math.round(r.top) : null,
    visibleButtons: btns.length,
    buttonTexts: btns.slice(0, 8).map(b => b.textContent.trim().slice(0, 10)),
    scrollH: document.documentElement.scrollHeight,
    scrollable: document.documentElement.scrollHeight > innerHeight + 2
  };
  if (cv) {
    const c = cv.getContext('2d');
    if (c) {
      const d = c.getImageData(0, 0, cv.width, cv.height).data;
      let nonbg = 0, green = 0, amber = 0, mag = 0;
      for (let i = 0; i < d.length; i += 4) {
        const R = d[i], G = d[i+1], B = d[i+2];
        if (R > 12 || G > 16 || B > 22) nonbg++;
        if (G > 140 && R < 130 && B < 130) green++;
        if (R > 190 && G > 140 && G < 225 && B < 130) amber++;
        if (R > 200 && G < 120 && B > 170) mag++;
      }
      const tot = cv.width * cv.height;
      out.pixels = {pct: +(100 * nonbg / tot).toFixed(2), green: green, amber: amber, magenta: mag};
    }
  }
  return out;
})()
"""


def run(url, app, size=(1600, 1000), wait_ms=9000, shot=None):
    v = QWebEngineView()
    v.resize(*size)
    v.show()
    state = {"done": False, "res": None}

    def got(r):
        state["res"] = r
        state["done"] = True

    def after_load(ok):
        sys.stdout.write("  · loadFinished(%s) %s\n" % (ok, url)); sys.stdout.flush()
        def probe():
            v.page().runJavaScript(PROBE, got)
        QTimer.singleShot(3500, probe)

    v.loadFinished.connect(after_load)
    v.load(QUrl(url))
    t0 = time.time()
    while not state["done"] and time.time() - t0 < wait_ms / 1000.0 + 12:
        app.processEvents()
        time.sleep(0.02)
    if shot:
        v.grab().save(shot)
    v.deleteLater()
    app.processEvents()
    return state["res"]


def main():
    print("═══ /ar3d 独立三维页 判据 ═══", flush=True)
    app = QApplication.instance() or QApplication(sys.argv)
    a = run(BASE + "/ar3d", app, shot=SHOT)
    print("ar3d:", json.dumps(a, ensure_ascii=False) if a else None, flush=True)
    b = run(BASE + "/ar", app, wait_ms=20000)
    if not a:
        print("FAIL 没取到 /ar3d 的页面状态(加载超时)")
        return 1
    if not b:
        print("⚠️ 没取到 /ar 对照状态(不影响 ar3d 判定)", flush=True)
        b = {}
    else:
        print("ar  :", json.dumps({k: b.get(k) for k in ("visibleButtons", "canvas", "scrollH", "vh")},
                                  ensure_ascii=False), flush=True)
    ck = []

    def chk(name, ok, detail):
        ck.append((name, bool(ok), detail))
        print("%s %s · %s" % ("✅" if ok else "❌", name, detail))

    chk("① 可见按钮数 = 0", a.get("visibleButtons") == 0,
        "visibleButtons=%s %s" % (a.get("visibleButtons"), a.get("buttonTexts")))
    chk("② 画布铺满整屏", bool(a.get("canvas")) and a["canvas"][0] >= a["vw"] - 2
        and a["canvas"][1] >= a.get("vh", 0) - 2,
        "canvas=%s vw=%s vh=%s top=%s" % (a.get("canvas"), a.get("vw"), a.get("vh"), a.get("canvasTop")))
    chk("③ 不用滚轮(页面不可滚)", not a.get("scrollable"),
        "scrollH=%s vh=%s" % (a.get("scrollH"), a.get("vh")))
    px = a.get("pixels") or {}
    chk("④ 三维真画出来了", (px.get("pct") or 0) > 0.5 and ((px.get("green") or 0) > 200 or (px.get("amber") or 0) > 200),
        "非背景 %s%% · 绿 %s · 琥珀 %s" % (px.get("pct"), px.get("green"), px.get("amber")))
    if b:
        chk("⑤ 对照 /ar 整页仍有按钮(判据非恒真)", (b.get("visibleButtons") or 0) > 0,
            "/ar visibleButtons=%s" % b.get("visibleButtons"))
    chk("⑥ ar3d 隐藏页头/按钮行", a.get("header") == "none" and a.get("rows") == "none",
        "header=%s rows=%s h2=%s" % (a.get("header"), a.get("rows"), a.get("h2")))
    print("截图:", SHOT, os.path.getsize(SHOT) if os.path.exists(SHOT) else "-")
    bad = [n for n, ok, _ in ck if not ok]
    print("═══ %s (%d/%d) ═══" % ("全绿" if not bad else "不过: " + ", ".join(bad), len(ck) - len(bad), len(ck)))
    return 0 if not bad else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
