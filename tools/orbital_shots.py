#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/orbital_shots.py — 球心引力架构取证出图 (只读, 离屏)

老倪看图要用的三张: ① 在役实拍 (由控制台 mparam_shot 出) ② 连拍条 (4 帧, 查线闪不闪)
③ 斜视角+放大 (查三维感/有没有被切)。本工具出后两张 —— 都是**真渲染 grab()**, 不是另画一套。

用法: QT_QPA_PLATFORM=offscreen python3 tools/orbital_shots.py
输出: reports/ui_shots/orbital_frames.png · reports/ui_shots/orbital_arch_tilt.png
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))

from PyQt5.QtCore import Qt                                                  # noqa: E402
from PyQt5.QtGui import QImage, QPainter                                    # noqa: E402
from PyQt5.QtWidgets import QApplication                                    # noqa: E402

import orbital_arch as OA                                                    # noqa: E402

W, H = 682, 1391
OUT = os.path.join(ROOT, "reports/ui_shots")


def main():
    app = QApplication(sys.argv)
    v = OA.OrbitalArchView()
    v.resize(W, 620)
    v.show()
    app.processEvents()
    # ② 连拍条: 4 帧 (相位推进 ⇒ 虚线在流动), 排成 4 行
    imgs = []
    for i in range(4):
        v._phase = (v._phase + 0.9) % 12.0
        v.update()
        app.processEvents()
        imgs.append(v.grab().toImage())
    strip = QImage(W, 620 * 4, QImage.Format_RGB32)
    strip.fill(Qt.black)
    p = QPainter(strip)
    for i, im in enumerate(imgs):
        p.drawImage(0, i * 620, im)
    p.end()
    f1 = os.path.join(OUT, "orbital_frames.png")
    strip.save(f1)
    print("✓ %s (%d×%d)" % (f1, strip.width(), strip.height()))
    # ③ 斜视角 + 放大
    v.yaw, v.zoom = 0.62, 1.57
    v.pitch = 0.72
    v.update()
    app.processEvents()
    im = v.grab().toImage()
    f2 = os.path.join(OUT, "orbital_arch_tilt.png")
    im.save(f2)
    print("✓ %s (yaw=%.2f pitch=%.2f zoom=%.2f)" % (f2, v.yaw, v.pitch, v.zoom))
    return 0


if __name__ == "__main__":
    sys.exit(main())
