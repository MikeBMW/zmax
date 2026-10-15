#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_live_window.py — 抓在役控制台窗口的真机截图 (取证用, 只读)。

用法: DISPLAY=:0 ./gui-venv311/bin/python tools/shot_live_window.py [输出png]
不传输出路径时落 reports/ui_shots/live_studio_<时间>.png。
"""
from __future__ import annotations
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication                    # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ROOT, "reports", "ui_shots", "live_studio_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(os.path.dirname(out), exist_ok=True)

# 用 xdotool 取窗口几何 (真机口径: wmctrl/xdotool 的 x,y 是**外框**, 裁图时多留边)
wid = subprocess.run(["xdotool", "search", "--name", "XSpace ZMAX"],
                     capture_output=True, text=True).stdout.split()
if not wid:
    print("⛔ 没找到 'XSpace ZMAX' 窗口 (控制台没起?)")
    sys.exit(2)
geom = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid[-1]],
                      capture_output=True, text=True).stdout
g = dict(l.split("=") for l in geom.strip().splitlines() if "=" in l)
X, Y, W, H = int(g["X"]), int(g["Y"]), int(g["WIDTH"]), int(g["HEIGHT"])

app = QApplication(sys.argv)
scr = app.primaryScreen()
shot = scr.grabWindow(0)                       # 0 = 整个根窗口
# 多留边裁 (菜单栏/外框阴影不被切)
x0, y0 = max(0, X - 20), max(0, Y - 60)
x1, y1 = min(shot.width(), X + W + 20), min(shot.height(), Y + H + 120)
shot.copy(x0, y0, x1 - x0, y1 - y0).save(out)
print("窗口 (xdotool 外框): %dx%d @ (%d,%d) · wid=%s" % (W, H, X, Y, wid[-1]))
print("📄 截图 %s (%dx%d)" % (out, x1 - x0, y1 - y0))
