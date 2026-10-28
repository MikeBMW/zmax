#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出图: 🧩SAM3 → 🧿DeepSeek-VL 那条线的**定点证据图** (老倪目检用)。

要点: 用 `QGraphicsScene.render(painter, target, source)` 按**场景坐标**切图 ——
不依赖视口滚动/布局 (离屏下 `centerOn` 常不生效, 出图会变成同一张 ⇒ 假证据, 已实测踩过)。
只读画布, 不写任何唯一依据。

用法:
    python tools/shot_seg_dsvl_link.py <out.png> [全览|src|dst|mid]
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets, QtCore, QtGui                                             # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                          # noqa: E402

FLOW = "/home/ubuntu/zmax/flows/state_space_obs.json"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/cache/scratch/seg_dsvl_all.png"
MODE = sys.argv[2] if len(sys.argv) > 2 else "全览"
W, H = 3040, 1500

m = SM.SimulinkModule()
m.resize(W, H)
m.load_flow_file(FLOW, confirm=False)
app.processEvents()

hit = None
for it in m.canvas._scene.items():
    if isinstance(it, SM.SimLinkItem):
        try:
            if "开放词汇分割" in ((it.src.node or {}).get("name") or "") and \
               "DeepSeek" in ((it.dst.node or {}).get("name") or ""):
                hit = it
                break
        except Exception:                                                             # noqa: BLE001
            pass
assert hit is not None, "没找到 🧩→🧿 那条线 (先跑 verify_seg_dsvl_canvas_link.py)"

src, dst = hit.src, hit.dst
rs, rd = src.sceneBoundingRect(), dst.sceneBoundingRect()
print("源: %s @(%.0f,%.0f)" % (src.node.get("name"), src.pos().x(), src.pos().y()))
print("标: %s @(%.0f,%.0f)" % (dst.node.get("name"), dst.pos().x(), dst.pos().y()))
print("标签: %s" % (hit.link.get("label"),))

if MODE == "src":
    region = QtCore.QRectF(rs.left() - 120, rs.top() - 420, 1900, 940)
elif MODE == "dst":
    region = QtCore.QRectF(rd.left() - 900, rd.top() - 120, 1900, 700)
elif MODE == "mid":
    region = hit.sceneBoundingRect().adjusted(-260, -160, 260, 160)
else:                                                                        # 全览(含两端)
    region = rs.united(rd).adjusted(-260, -140, 260, 140)

img = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32)
img.fill(QtCore.Qt.black)
p = QtGui.QPainter(img)
p.setRenderHint(QtGui.QPainter.Antialiasing, True)
m.canvas._scene.render(p, QtCore.QRectF(0, 0, W, H), region)
p.end()
img.save(OUT)
print("模式=%s 场景区域=(%.0f,%.0f,%.0fx%.0f) 缩放=%.3f → %s (%dx%d)" % (
    MODE, region.x(), region.y(), region.width(), region.height(),
    min(W / max(1.0, region.width()), H / max(1.0, region.height())), OUT, img.width(), img.height()))
