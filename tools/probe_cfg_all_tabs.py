#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_cfg_all_tabs.py — 把「配置中心」7 个页逐个摊开量: 每页有哪些表/显示区、多高、装得下多少行。

为什么 (老倪 2026-10-15): 「产品配置的元任务窗口, 也是太矮了, 调高适配, 优化UI」
—— 先要知道**他说的那个"元任务窗口"到底在哪一页、现在多高**, 再动手; 不靠猜。

打印口径 (全部取自真实控件, 离屏跑同一条构造路径):
  每页: 页高 / 页最小高 / 滚动条 max ; 逐个 QTableWidget: 表头首列 + 行数 + 高 + 表内滚动 max + 可见行数
  以及任何 label/textedit 里带「元任务」的控件

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_cfg_all_tabs.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (QApplication, QLabel, QScrollArea, QTableWidget,   # noqa: E402
                             QTextEdit, QTreeWidget, QWidget)

import veh6_config_page as V                                                   # noqa: E402

W, H = 1700, 1700          # 独立窗口上限档 (本机默认窗口量出的最大工作区)


def walk(w):
    yield w
    for c in w.findChildren(QWidget):
        yield c


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = V.ConfigCenterPage(model_page=None)
    page.resize(W, H)
    page.show()
    for _ in range(20):
        app.processEvents()

    print("容器 %dx%d · 页签数 %d" % (W, H, page.tabs.count()))
    for i in range(page.tabs.count()):
        title = page.tabs.tabText(i)
        sa = page.tabs.widget(i)
        if not isinstance(sa, QScrollArea):
            print("\n══ [%d] %s —— 不是 QScrollArea (%s)" % (i, title, type(sa).__name__))
            continue
        inner = sa.widget()
        page.tabs.setCurrentIndex(i)
        for _ in range(10):
            app.processEvents()
        print("\n══ [%d] %s" % (i, title))
        print("   页内容高 %d · 页最小高 %d · 视口 %d · 页滚动 max=%d"
              % (inner.height(), inner.minimumSizeHint().height(),
                 sa.viewport().height(), sa.verticalScrollBar().maximum()))
        if inner is None:
            continue
        seen = set()
        for c in inner.findChildren(QTableWidget):
            if id(c) in seen:
                continue
            seen.add(id(c))
            hh = c.horizontalHeader()
            col0 = (c.horizontalHeaderItem(0).text() if c.horizontalHeaderItem(0) else "?")
            ncol = c.columnCount()
            rh = c.rowHeight(0) if c.rowCount() else 0
            vp = c.viewport().height()
            nm = c.objectName() or type(c).__name__
            attr = [k for k in ("tasks_table", "meta_table", "table", "routes_table")
                    if getattr(page, k, None) is c]
            print("   ▦ 表 %-16s 列%d 行%d 高%d 视口%d 行高%d ⇒ 可见%d行 · 表内滚动 max=%d · 首列=「%s」%s"
                  % (nm, ncol, c.rowCount(), c.height(), vp, rh,
                     vp // max(1, rh), c.verticalScrollBar().maximum(), col0,
                     ("  ← page." + attr[0]) if attr else ""))
        for c in inner.findChildren((QLabel, QTextEdit)):
            txt = c.text() if isinstance(c, QLabel) else c.toPlainText()
            if "元任务" in (txt or ""):
                print("   ✎ %s 高%d 文本前40: %s" % (type(c).__name__, c.height(), (txt or "").replace("\n", " ")[:40]))
    print("\n═══ 页签顺序 ═══")
    for i in range(page.tabs.count()):
        print("   %d. %s" % (i, page.tabs.tabText(i)))
    if "--shot" in sys.argv:                       # 真机目检用出图 (老倪会把画面当结果)
        d = os.path.join(ROOT, "reports", "ui_shots")
        os.makedirs(d, exist_ok=True)
        for i in range(page.tabs.count()):
            t = page.tabs.tabText(i).replace(" ", "")
            page.tabs.setCurrentIndex(i)
            for _ in range(10):
                app.processEvents()
            w = page.tabs.widget(i)
            p = os.path.join(d, "cfg_%d_%s.png" % (i, t))
            w.grab().save(p)
            print("   📄 出图 %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
