#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""几何判据: 1700×1200 真 show() 后, 任务级/功能级元任务表是否一屏装得下 (AOI 33 条 / 任务级 5 条)。"""
import os, sys
ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import veh6_config_page as V

p = V.ConfigCenterPage()
p.resize(1700, 1200)
p.show()                      # 不 show() 时 Qt 不做真正的布局计算 (量到的是上一轮陈旧值)
for _ in range(10):
    app.processEvents()
i = p._tab_index_by_title("任务配置")
p.tabs.setCurrentIndex(i)
for _ in range(10):
    app.processEvents()

tt = p.tasks_table
ok = []
for tid in ("TASK-07-AOI", "TASK-01-FW", "TASK-02-HANDLE"):
    for r in range(tt.rowCount()):
        if tt.item(r, 0).text() == tid:
            tt.selectRow(r)
    for _ in range(4):
        app.processEvents()
    tl, mt = p.tl_table, p.meta_table
    tlneed = sum(tl.rowHeight(r) for r in range(tl.rowCount())) + tl.horizontalHeader().height()
    vis = [r for r in range(mt.rowCount()) if not mt.isRowHidden(r)]
    mtneed = sum(mt.rowHeight(r) for r in vis) + mt.horizontalHeader().height()
    a = tl.height() + 2 >= tlneed
    b = mt.height() + 2 >= mtneed
    # 口径: 任务级表**必须**一屏装全; 功能级表在 ≤40 行时必须装全 (AOI 33 条),
    #       53/44 行的任务 (全 8 任务共用的长清单) 允许表内滚 —— 有 9px 可拖分隔条, 页面整体也可滚。
    ok.append(a and (b or len(vis) > 40))
    print("%-14s 任务级 %3dpx/%3dpx %-4s (%d 条) | 功能级 %3dpx/%3dpx %-6s (%d/%d 条可见)"
          % (tid, tl.height(), tlneed, "OK" if a else "滚", tl.rowCount(),
             mt.height(), mtneed, "OK" if b else "表内滚", len(vis), mt.rowCount()))
print("RESULT:", "PASS" if all(ok) else "FAIL")
sys.exit(0 if all(ok) else 1)
