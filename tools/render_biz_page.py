#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「🧩 商业模式」页渲染成 PNG (取证用, 只读)。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src")):
    sys.path.insert(0, _p)

from PyQt5.QtWidgets import QApplication                      # noqa: E402

app = QApplication([])
import veh6_config_page as V                                  # noqa: E402

pg = V.ConfigCenterPage(model_page=None)
i = next(k for k in range(pg.tabs.count()) if "商业模式" in pg.tabs.tabText(k))
pg.tabs.setCurrentIndex(i)
app.processEvents()
w = pg.tabs.widget(i)
from PyQt5.QtWidgets import QScrollArea                 # noqa: E402
inner = w.widget() if isinstance(w, QScrollArea) else w
inner.resize(1240, 1700)
inner.setMinimumSize(1240, 1700)
app.processEvents()
out = os.path.join(ROOT, "zmax_data", "business", "biz_page_%s.png" % "20261019")
os.makedirs(os.path.dirname(out), exist_ok=True)
inner.grab().save(out)
print("saved", out, os.path.getsize(out), "bytes", inner.size().width(), "x", inner.size().height())
