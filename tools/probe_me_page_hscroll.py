#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针: 功能区页面里那个 1900 宽的面板, 在**控制台窗口只有 1400 宽**时, 老倪能不能滚到右边的权重路径列?

面板固定设计宽 1900 (与弹窗一致) ⇒ 父容器更窄时必须给**横向滚动**, 否则右侧列永远看不见 = 比修前更糟。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.chdir("/home/ubuntu/zmax")

from PyQt5.QtWidgets import QApplication, QScrollArea  # noqa: E402

app = QApplication.instance() or QApplication([])
import studio as S  # noqa: E402

tm = S.TrainingModule()
tm.show()
app.processEvents()

p = getattr(tm, "me_panel", None)
print("面板: %s 宽=%s (设计宽 %s)" % (type(p).__name__, p.width(), p.minimumWidth()))
par, chain = p.parent(), []
while par is not None:
    chain.append("%s(%sx%s)" % (type(par).__name__, par.width(), par.height()))
    if isinstance(par, QScrollArea):
        hb = par.horizontalScrollBar()
        print("  ✔ 找到页面级 QScrollArea: 视口宽=%s 内容宽=%s 横滚 max=%s 策略=%s"
              % (par.viewport().width(), par.widget().width() if par.widget() else "?", hb.maximum(), hb.isVisible()))
    par = par.parent()
print("父链: " + " ← ".join(chain[:8]))
sys.stdout.flush()
os._exit(0)
