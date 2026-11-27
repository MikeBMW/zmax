#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌀 相空间 (phase space) 视图 —— 横轴 Θ 位置、纵轴 p 动量, 每条流线是一条相轨迹。

老倪 2026-10-25: 「在主参数的下部，增加在相空间 phase space 中绘制运动轨迹的视图；绘制一个二维图，
纵轴是 p phase，横轴是 Θ；其中一个轴是位置，一个轴是动量；每个流线是相空间的轨迹」

口径 (与 src/lerobot/manifold/state_space_energy.py 同一套参数, 不另立一套):
    轴向单自由度受迫阻尼振子 (SK07 插入段的主模态):
        Θ̇ = p / m
        ṗ = −k_ax·Θ − b·p/m ,   b = α·k_ax
    哈密顿量  H = p²/(2m) + ½·k_ax·Θ²   (椭圆等能线)
    参数取 hamiltonian.json 里的真值 (k_ax=400 N/m · α=0.15 · m=3.643 kg ⇒ ζ=0.786 欠阻尼)

图上画什么:
    · 流线 (细线族)  = 从不同初值出发的**相轨迹**, 都螺旋收敛到原点 (0,0)=平衡点
    · 等能线 (虚线)  = 当前 H 对应的椭圆, 半径 ∝ √(2H/k)
    · 亮点 + 尾迹     = 真机/引擎这一帧的 (Θ, p) 与最近 N 帧走过的轨迹 (实测, 不是示意)
数据源: zmax_data/ss_live/hamiltonian.json (节点 ss_grav_h 每帧落; 缺就显「未出数」, 不造点)
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

try:
    import pyqtgraph as pg
except Exception:                                                          # noqa: BLE001
    pg = None


def _live_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "zmax_data", "ss_live", "hamiltonian.json")


def _streamlines(k: float, b: float, m: float, n: int = 26, t_end: float = 3.0,
                 dt: float = 4e-4):
    """相轨迹族: 从 Θ0 = ±[6..60]mm, p0=0 出发积分到收敛。返回 [(q_mm, p), ...]。"""
    out = []
    for q0 in np.concatenate([np.linspace(6e-3, 60e-3, n // 2), -np.linspace(6e-3, 60e-3, n // 2)]):
        q, p = float(q0), 0.0
        qs, ps = [q], [p]
        steps = int(t_end / dt)
        for _ in range(steps):
            a = -k * q - b * p / m
            p += a * dt
            q += (p / m) * dt
            qs.append(q)
            ps.append(p)
            if abs(q) < 2e-5 and abs(p) < 2e-4:
                break
        out.append((np.array(qs) * 1000.0, np.array(ps)))
    return out


class PhaseSpaceView(QWidget):
    """横轴 Θ(mm) · 纵轴 p(kg·m/s) 的相图: 流线族 + 等能线 + 实测尾迹。"""

    def __init__(self, parent=None):
        super(PhaseSpaceView, self).__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self.lbl = QLabel("🌀 相空间 (Θ, p) —— 等待 ss_grav_h 出数…")
        self.lbl.setStyleSheet("color:#8b949e;font-size:12px;font-family:Consolas,monospace;")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)

        if pg is None:
            lay.addWidget(QLabel("pyqtgraph 不可用, 相图无法绘制"))
            self.pw = None
            return
        pg.setConfigOptions(antialias=True, background="#0d1117", foreground="#8b949e")
        self.pw = pg.PlotWidget()
        self.pw.setMinimumHeight(240)
        self.pw.showGrid(x=True, y=True, alpha=0.18)
        self.pw.setLabel("bottom", "Θ 位置偏差 (mm)")
        self.pw.setLabel("left", "p 动量 (kg·m/s)")
        self.pw.getAxis("bottom").setStyle(tickFont=None)
        for ax in ("bottom", "left"):
            a = self.pw.getAxis(ax)
            a.setPen(pg.mkPen("#30363d"))
            a.setTextPen(pg.mkPen("#8b949e"))
        self.pw.addLine(x=0, pen=pg.mkPen("#30363d", width=1, style=Qt.DashLine))
        self.pw.addLine(y=0, pen=pg.mkPen("#30363d", width=1, style=Qt.DashLine))
        lay.addWidget(self.pw, 1)

        self._streams_drawn = False
        self._trail = []          # [(Θ_mm, p)]
        self._trail_curve = None
        self._point = None
        self._econt = None
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    # ── 流线/等能线只在参数确定后画一次 (参数变了才重画) ──
    def _draw_portrait(self, k, b, m, H):
        if self.pw is None:
            return
        self.pw.clear()
        self.pw.addLine(x=0, pen=pg.mkPen("#30363d", width=1, style=Qt.DashLine))
        self.pw.addLine(y=0, pen=pg.mkPen("#30363d", width=1, style=Qt.DashLine))
        # 流线族: 颜色随初值能量变化 (暗→亮), 都是**真积分出来的相轨迹**
        for qs, ps in _streamlines(k, b, m):
            e0 = 0.5 * k * (qs[0] / 1000.0) ** 2
            t = float(np.clip(e0 / max(0.5 * k * 0.06 ** 2, 1e-12), 0.0, 1.0))
            col = (int(60 + 120 * t), int(110 + 100 * t), int(190 + 60 * t))
            self.pw.plot(qs, ps, pen=pg.mkPen(col, width=1))
        # 等能线: p²/(2m) + ½kΘ² = H ⇒ 椭圆
        if H and H > 1e-9:
            a = 1000.0 * np.sqrt(2 * H / k)                    # 半轴 Θ (mm)
            bb = np.sqrt(2 * m * H)                            # 半轴 p
            th = np.linspace(0, 2 * np.pi, 240)
            self._econt = self.pw.plot(a * np.cos(th), bb * np.sin(th),
                                       pen=pg.mkPen("#ffd479", width=1, style=Qt.DashLine))
        self.pw.setXRange(-75, 75, padding=0)
        self.pw.setYRange(-0.9, 0.9, padding=0)
        self._trail_curve = self.pw.plot([], [], pen=pg.mkPen("#7ee787", width=2))
        self._point = self.pw.plot([], [], pen=None, symbol="o", symbolSize=9,
                                   symbolBrush="#3fb950", symbolPen="#7ee787")
        self._streams_drawn = (k, b, m)

    def refresh(self):
        try:
            d = json.load(open(_live_path(), encoding="utf-8"))
        except Exception as e:                                              # noqa: BLE001
            self.lbl.setText("🌀 相空间: 节点未出数 (%s: %s)" % (type(e).__name__, e))
            return
        try:
            m = float(d.get("mass_kg") or 3.643)
            k = float((d.get("K_diag") or [0, 0, 400])[2])
            alpha = float(d.get("alpha") or 0.15)
            b = alpha * k
            xi = d.get("xi") or [0] * 6
            xe = d.get("xi_e") or [0] * 6
            theta_mm = float(xe[2]) * 1000.0          # 轴向位置偏差
            p = m * float(xi[2])                      # 轴向动量
            H = float(d.get("H") or 0.0)
            age = max(0.0, time.time() - float(d.get("ts") or 0.0))
            if self.pw is not None and (not self._streams_drawn or
                                        abs(self._streams_drawn[0] - k) > 1e-9):
                self._draw_portrait(k, b, m, H)
            if self.pw is not None and self._trail_curve is not None:
                self._trail.append((theta_mm, p))
                if len(self._trail) > 400:
                    self._trail = self._trail[-400:]
                xs = [t[0] for t in self._trail]
                ys = [t[1] for t in self._trail]
                self._trail_curve.setData(xs, ys)
                self._point.setData([theta_mm], [p])
            zeta = b / (2 * np.sqrt(k * m)) if k > 0 and m > 0 else 0.0
            self.lbl.setText(
                "🌀 相空间 Θ-p │ k_ax %.0f N/m · α %.2f (ζ=%.2f) · m %.3f kg │ "
                "Θ %+.1f mm · p %+.3f kg·m/s │ H %.4f J │ 帧龄 %.1fs%s"
                % (k, alpha, zeta, m, theta_mm, p, H, age, "  ⏸陈旧" if age > 5 else ""))
            self.lbl.setToolTip(
                "Θ = 轴向位置偏差 (xi_e[2]) · p = m·v_z (轴向动量)\n"
                "流线 = 从 Θ0=±6..60mm 出发积分出的相轨迹 (同一 k/α/m, 螺旋收敛到原点)\n"
                "琥珀虚线 = 当前 H 的等能线 p²/(2m)+½kΘ²=H · 绿点+尾迹 = 实测帧\n"
                "数据源: %s" % str(d.get("src", ""))[:100])
        except Exception as e:                                              # noqa: BLE001
            self.lbl.setText("🌀 相空间: 字段不全 (%s: %s)" % (type(e).__name__, e))
