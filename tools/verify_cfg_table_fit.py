#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 配置通道表在**真机尺寸**下必须整张看得完 (老倪 2026-10-14「表只渲染到版本行就收边」的回归守卫)。

背景 (父链取证): 表自己尺寸对 (21 行 / 内容高 ≤ 控件高 / 表内 max=0), 但页面里那个**内层 QScrollArea
最小高只有 600px** 会把 1522px 的表切成前 5 行。本判据两条:
  ① 表内: 内容高 ≤ 控件高, 且表自身竖滚动 max == 0  (行没被自己裁)
  ② 表外: 最近的那个 QScrollArea 祖先的**视口高 ≥ 表高**, 且它自身竖滚动 max == 0 (没被外层再切一层)
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_cfg_table_fit.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt5.QtWidgets import QApplication, QTableWidget, QScrollArea                   # noqa: E402

app = QApplication.instance() or QApplication([])
import studio                                                                         # noqa: E402

W, H = (int(os.environ.get("ZMAX_W") or 3200), int(os.environ.get("ZMAX_H") or 2000))
win = studio.StudioMainWindow()
  # ⚡ 2026-10-19 页面改按需建 ⇒ 判据/探针先强制全部真建 (线上由后台泵做)
win.materialize_all()
win.resize(W, H)
win.show()
try:
    win._on_nav("training")
except Exception:                                                                     # noqa: BLE001
    pass
t0 = time.time()
while time.time() - t0 < 8:            # 让页面就位后的 800/2500/6000ms 定时器跑完
    app.processEvents()
    time.sleep(0.02)

t = win.findChild(QTableWidget, "cfg_matrix_table")
res = []


def chk(name, cond, extra=""):
    res.append(("✓" if cond else "✗") + " " + name + (" :: %s" % (extra,) if extra else ""))


chk("① 配置通道表存在且 21 行 × 5 列", t is not None and t.rowCount() == 21 and t.columnCount() == 5,
    ("%dx%d" % (t.rowCount(), t.columnCount())) if t is not None else "找不到")
if t is not None:
    need = sum(t.rowHeight(r) for r in range(t.rowCount()))
    vs = t.verticalScrollBar()
    chk("② 表内没被自己裁 (内容高 ≤ 控件高, 表内滚动 max=0)",
        need <= t.height() and vs.maximum() == 0, "内容 %d vs 控件 %d, max=%d" % (need, t.height(), vs.maximum()))
    par, found = t.parentWidget(), None
    while par is not None:
        if isinstance(par, QScrollArea):
            found = par
            break
        par = par.parentWidget()
    if found is None:
        chk("③ 表在页面滚动区里", False, "父链上没有 QScrollArea")
    else:
        chk("③ 表没被外层滚动区裁 (外层视口高 ≥ 表高, 外层滚动 max=0)",
            found.viewport().height() >= t.height() and found.verticalScrollBar().maximum() == 0,
            "外层视口 %d vs 表 %d, max=%d" % (found.viewport().height(), t.height(),
                                              found.verticalScrollBar().maximum()))

print("\n".join(res))
ok = sum(1 for r in res if r.startswith("✓"))
print("\n判据汇总: %d/%d PASS" % (ok, len(res)))
sys.stdout.flush()
os._exit(0 if ok == len(res) else 1)
