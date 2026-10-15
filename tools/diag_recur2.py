#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓信号分析页的递归爆栈调用栈 (v2) — 跑真事件循环 ~25s, 让真数据源/定时器都动起来"""
import os
import sys
import threading
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

_seen = {"n": 0}


def _hook(exc_type, exc, tb):
    _seen["n"] += 1
    if _seen["n"] <= 3:
        print("=== 异常 #%d: %s: %s ===" % (_seen["n"], exc_type.__name__, exc), flush=True)
        traceback.print_exception(exc_type, exc, tb, limit=20)


sys.excepthook = _hook
threading.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback)

from PyQt5 import QtCore, QtWidgets                                          # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
sys.setrecursionlimit(500)

from canoe_graphic import CanoeGraphicWidget                                  # noqa: E402

w = CanoeGraphicWidget()
w.show()

t0 = time.time()
while time.time() - t0 < 25:
    app.processEvents()
    time.sleep(0.05)
    if int(time.time() - t0) % 5 == 0:
        st = getattr(w.wave, "curves", [])
        if st and getattr(w, "_last_report", None) != len(st):
            w._last_report = len(st)
            print("曲线 %d 条 · 已勾 %d · 异常 %d" % (len(st), len(getattr(w, "selected", [])), _seen["n"]), flush=True)

print("结束 · 捕获异常数 = %d · 曲线 %d 条" % (_seen["n"], len(getattr(w.wave, "curves", []))))
