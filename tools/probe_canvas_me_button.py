#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针: 画布(状态空间工程)工具栏新按钮「🧠 模型引擎」在**真机窗口宽**下到底看不看得见。

背景: 2026-10-10 出过 "btn_ss_3d 建了对象但没挂进布局 = 用户看不到" ⇒ 新按钮必须查可见性,
不能只看源码里有。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.chdir("/home/ubuntu/zmax")

from PyQt5.QtCore import QPoint  # noqa: E402
from PyQt5.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])
import simulink_module as SM  # noqa: E402

W = int(sys.argv[1]) if len(sys.argv) > 1 else 1400          # 控制台窗口实际宽 (实机 1400)
tm = SM.SimulinkModule()
tm.resize(W, 900)
tm.show()
app.processEvents()

b = getattr(tm, "btn_me_win", None)
print("模块尺寸: %dx%d" % (tm.width(), tm.height()))
if b is None:
    print("✗ 没有 btn_me_win")
    sys.exit(1)
tl_origin = b.mapToGlobal(QPoint(0, 0))
mod_right = tm.mapToGlobal(QPoint(tm.width(), 0)).x()
print("按钮: %r visible=%s 全局 x=%d..%d y=%d" % (b.text(), b.isVisible(), tl_origin.x(),
                                                  tl_origin.x() + b.width(), tl_origin.y()))
print("模块右边界 x=%d ⇒ 按钮%s" % (mod_right, "完整可见" if tl_origin.x() + b.width() <= mod_right else "被右边界裁掉!"))
btns = [x for x in tm.findChildren(QPushButton) if x.isVisible()]
rows = {}
for x in btns:
    rows.setdefault(x.mapToGlobal(QPoint(0, 0)).y(), []).append((x.mapToGlobal(QPoint(0, 0)).x(), x.text()))
for y in sorted(rows)[:5]:
    line = sorted(rows[y])
    print("  工具排行 y=%d: %s" % (y, " | ".join("%s@%d" % (t[:14], x) for x, t in line)[:150]))
sys.stdout.flush()
os._exit(0)
