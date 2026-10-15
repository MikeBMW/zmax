#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_page_blocks.py — 把某一页的**顶层块**逐个量高, 找出"高度都花在哪了" (只读, 离屏)。

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_page_blocks.py [页名关键字]
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLabel, QScrollArea, QWidget          # noqa: E402

import veh6_config_page as V                                                   # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else "产品配置"
W, H = 1700, 1700


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = V.ConfigCenterPage(model_page=None)
    page.resize(W, H)
    page.show()
    for _ in range(20):
        app.processEvents()
    idx = None
    for i in range(page.tabs.count()):
        if KEY in page.tabs.tabText(i):
            idx = i
    page.tabs.setCurrentIndex(idx)
    for _ in range(10):
        app.processEvents()
    sa = page.tabs.widget(idx)
    inner = sa.widget()
    print("页 %s · 内容高 %d · 视口 %d · 滚动 max=%d"
          % (page.tabs.tabText(idx), inner.height(), sa.viewport().height(),
             sa.verticalScrollBar().maximum()))
    lay = inner.layout()
    print("布局项 %d 个 (顶层块 —— 高度从哪来):" % lay.count())
    tot = 0
    for i in range(lay.count()):
        it = lay.itemAt(i)
        w = it.widget()
        if w is None:
            sp = it.spacerItem()
            if sp is not None:
                print("  [%2d] ── 弹性空白 (addStretch) 高 %d" % (i, sp.sizeHint().height()))
            else:
                print("  [%2d] ── 子布局 %s" % (i, type(it.layout()).__name__))
            continue
        h = w.height()
        tot += h
        txt = ""
        if isinstance(w, QLabel):
            txt = (w.text() or "").replace("\n", " ")[:34]
        kids = w.findChildren(QWidget)
        print("  [%2d] %-16s 高%5d 最小高%5d 子控件%3d  %s"
              % (i, type(w).__name__, h, w.minimumSizeHint().height(), len(kids), txt))
    print("  顶层块合计 %d (内容 %d)" % (tot, inner.height()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
