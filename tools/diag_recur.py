#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓信号分析页的递归爆栈调用栈 (老倪 2026-10-15: 新窗口日志里 RecursionError 又出现)"""
import os
import sys
import threading
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

_seen = {"n": 0}


def _hook(exc_type, exc, tb):
    _seen["n"] += 1
    if _seen["n"] <= 2:
        print("=== 捕获异常 #%d: %s ===" % (_seen["n"], exc_type.__name__))
        traceback.print_exception(exc_type, exc, tb, limit=25)


sys.excepthook = _hook
threading.excepthook = lambda a: _hook(a.exc_type, a.exc_value, a.exc_traceback)

from PyQt5 import QtWidgets                                                  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
sys.setrecursionlimit(300)          # 让爆栈尽早暴露, 便于抓栈

w = None
for _ in range(3):
    try:
        w = __import__("canoe_graphic").CanoeGraphicWidget()
        break
    except RecursionError:
        print("构造期就爆栈")
if w is None:
    raise SystemExit(1)

try:
    for i in range(12):
        w._tick()
        QtWidgets.QApplication.processEvents()
except RecursionError:
    traceback.print_exc(limit=25)
print("轮次完成 · 捕获到的异常数 = %d · 曲线 %d 条" % (_seen["n"], len(getattr(w.wave, "curves", []))))
