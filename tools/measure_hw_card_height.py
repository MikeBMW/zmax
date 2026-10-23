#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""measure_hw_card_height.py — 量「硬件资源」卡在真实数据下的高度 (改高度前后同一口径)

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/measure_hw_card_height.py [--shot out.png]
判据: sizeHint().height() + 子控件各自高度 + 渲染 PNG 的实际非空行数。
"""
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import studio  # noqa: E402

W = 1200
card = studio.HardwareCard()
card.resize(W, card.sizeHint().height())
card.show()
app.processEvents()
if hasattr(card, "refresh"):
    card.refresh()
app.processEvents()

sh = card.sizeHint().height()
print("卡片 sizeHint 高度: %d px (宽 %d)" % (sh, W))
print("  布局 margins=%s spacing=%s" % (card.layout().contentsMargins().top(), card.layout().spacing()))
vis = getattr(card, "_visual", None)
if vis is not None:
    print("  HwVisual sizeHint=%d 实际=%d" % (vis.sizeHint().height(), vis.height()))
    for k, rg in vis.rings.items():
        print("   ring %-4s %dx%d" % (k, rg.width(), rg.height()))
    for k, b in vis.bars.items():
        print("   bar  %-5s %dx%d" % (k, b.width(), b.height()))
    for k, l in vis._lamps.items():
        print("   lamp %-6s %dx%d" % (k, l.width(), l.height()))
for c in card.findChildren(type(card.lb_ts)):
    t = (c.text() or "")[:20]
    if c.isVisible() and t:
        print("   可见文本 %-22r %dx%d" % (t, c.width(), c.height()))

shot = None
if "--shot" in sys.argv:
    shot = sys.argv[sys.argv.index("--shot") + 1]
    card.grab().save(shot)
    print("  截图 -> %s" % shot)
print("总高 = %d px" % card.height())
