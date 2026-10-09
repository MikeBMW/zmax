#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_bypass_drag_smoke.py — 🤲 拖动示教捕捉带 离屏冒烟 (真起窗, 打印屏上实际显示的四个数 + 截图)

只读: 读位姿真值 / 起点 / 控制器 operation/mode; **零下发, 不改任何真机状态**。
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/ss_bypass_drag_smoke.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")

from PyQt5 import QtWidgets          # noqa: E402

import ss_bypass_view as V           # noqa: E402

SCRATCH = "/home/ubuntu/.hermes/cache/scratch"
os.makedirs(SCRATCH, exist_ok=True)
shot = os.path.join(SCRATCH, "ss_bypass_drag_band_%s.png" % time.strftime("%Y%m%d_%H%M%S"))

app = QtWidgets.QApplication(sys.argv)
win = V.SSBypassView()
win.resize(1620, 1080)
win.show()
app.processEvents()

# 停在后台轮询/单次定时器, 同步拉一轮 (不依赖事件循环) → 渲染成屏上文本
win.drag_timer.stop()
win.station_timer.stop()
win.timer.stop()
win._drag_refresh_blocking()
app.processEvents()

print("=" * 64)
print("🤲 拖动示教捕捉带 离屏冒烟 — 屏上实际显示的四个数")
print("=" * 64)
for key, human in (("pos", "① 实时位姿 x/y/z + 帧龄 + 采样时刻"),
                   ("state", "② 拖动状态 operation/mode"),
                   ("base", "③ 起点 + 距起点 mm"),
                   ("cmd", "④ 录点命令 (可复制)")):
    print("%-28s : %s" % (human, win.drag_labs[key].text()))
print("%-28s : %s" % ("⑤ 错误行 (不可达/陈旧才非空)", win.drag_err.text() or "(空)"))
pl = win._drag_last or {}
print("-" * 64)
print("原始载荷:", {
    "pose.stale": (pl.get("pose") or {}).get("stale"),
    "pose.frame_age_s": (pl.get("pose") or {}).get("frame_age_s"),
    "pose.pos": (pl.get("pose") or {}).get("pos"),
    "base.name": (pl.get("base") or {}).get("name"),
    "ctl": {k: (pl.get("ctl") or {}).get(k) for k in ("operation", "mode", "power")},
    "err": pl.get("err"),
})
win.grab().save(shot)
print("-" * 64)
print("截图:", shot, "存在=", os.path.exists(shot))
print("=" * 64)

# 收尾: 停掉可能仍在跑的线程, 避免 QThread destroyed 警告
w = getattr(win, "_drag_worker", None)
if w is not None and w.isRunning():
    w.wait(3000)
sw = getattr(win, "_station_worker", None)
if sw is not None and sw.isRunning():
    sw.wait(3000)
win.close()
app.processEvents()
sys.exit(0)
