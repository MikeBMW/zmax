#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot_canvas_flow.py — 出两张画布证据图 (离屏真渲染, 不截屏):
 ① 全图 (含行带) —— 看"左上→右下"的整体走向与紧凑度
 ② 前馈加速器 → 动作调制器 局部 —— 老倪点名要看的那一段
产物: /tmp/canvas_flow_all.png · /tmp/canvas_flow_pair.png
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtGui, QtWidgets                    # noqa: E402
import simulink_module as SM                                  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
m = SM.SimulinkModule()
m.resize(1600, 1000)
m.open_state_space()
for _ in range(60):
    app.processEvents()

cv = getattr(m, "canvas", None) or getattr(m, "_canvas", None)
scn = cv.scene()


def render(rect, path, max_px=2200):
    r = rect.toRect()
    w, h = max(1, r.width()), max(1, r.height())
    scale = min(1.0, max_px / float(max(w, h)))
    img = QtGui.QImage(int(w * scale), int(h * scale), QtGui.QImage.Format_ARGB32)
    img.fill(QtGui.QColor(13, 17, 23))
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    scn.render(p, QtCore.QRectF(0, 0, w * scale, h * scale), QtCore.QRectF(w and r.x() or 0, r.y(), w, h))
    p.end()
    img.save(path)
    print("已出 %s (%dx%d, 源区 %d,%d %dx%d)" % (path, img.width(), img.height(), r.x(), r.y(), w, h))


allrect = scn.itemsBoundingRect()
render(allrect, "/tmp/canvas_flow_all.png")

by_name = {}
for k, it in (getattr(m, "_items", {}) or {}).items():
    nd = getattr(it, "node", None) or {}
    by_name[str(nd.get("name", ""))] = it
# 老倪 2026-10-15 新要的: 状态校正器 → 融合定位建图 这条回灌线
for _nm in ("🧪 状态校正器", "📡 融合定位建图", "⚡ 前馈加速器", "🧭 动作调制器"):
    if _nm not in by_name:
        print("⚠️ 名字没对上: %r" % _nm)
cs, sn = by_name.get("🧪 状态校正器"), by_name.get("📡 融合定位建图")
if cs and sn:
    rect = cs.sceneBoundingRect().united(sn.sceneBoundingRect()).adjusted(-360, -300, 360, 300)
    render(rect, "/tmp/canvas_innov_to_sensor.png")

a, b = by_name.get("⚡ 前馈加速器"), by_name.get("🧭 动作调制器")
if a and b:
    ra, rb = a.sceneBoundingRect(), b.sceneBoundingRect()
    rect = ra.united(rb).adjusted(-420, -260, 420, 260)
    render(rect, "/tmp/canvas_flow_pair.png")
else:
    print("没找到这两个节点: %s / %s" % (bool(a), bool(b)))
