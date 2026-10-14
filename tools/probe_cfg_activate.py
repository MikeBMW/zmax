#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏试跑「配置中心按任务ID激活」这条路 (与命令通道 cfg_task / 界面下拉完全同一执行体)。

用途: 命令通道点了没反应时, 用最小复现把真因打出来 (而不是靠看状态栏猜)。
不写盘: 只在 --do 时才真激活 (默认只做"能不能选中行 + 有没有下拉"的检查)。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
sys.path.insert(0, "/home/ubuntu/zmax/tools")

from PyQt5.QtWidgets import QApplication                                            # noqa: E402

app = QApplication.instance() or QApplication([])
import veh6_config_page as V                                                        # noqa: E402

tid = sys.argv[1] if len(sys.argv) > 1 else "TASK-01-FW"
do = "--do" in sys.argv

p = V.build_config_center(None, {})
print("页面:", type(p).__name__)
print("任务表行数:", getattr(p, "tasks_table", None) and p.tasks_table.rowCount())
print("_ACT_COL =", getattr(V, "_ACT_COL", "缺失"))
r = p.tasks_table.currentRow()
_sel = p.select_task_row(tid)
print("select_task_row(%s) = %s · currentRow=%s · 选中=%r"
      % (tid, _sel, p.tasks_table.currentRow(), p._selected_task()))
cb = p.tasks_table.cellWidget(p.tasks_table.currentRow(), getattr(V, "_ACT_COL", 12))
print("该行活跃属性下拉:", type(cb).__name__ if cb is not None else None,
      "当前值:", cb.currentText() if cb is not None else None)
if do:
    print("activate_task →", p.activate_task(tid))
else:
    print("(只检查; 加 --do 才真激活)")
