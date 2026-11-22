#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌀 哈密顿量相空间独立窗口 (真机口径, 只读)

老倪: 「哈密顿量的窗口呢？画到一个窗口的相空间」——控制台里的相空间面板要重启控制台才刷新,
      所以这里另起一个独立窗口: 自己读桥、自己算, 不碰 studio.py, 也不写 hamiltonian.json。

口径 (与 src/lerobot/manifold/state_space_energy.py 同参数, 不另立一套):
    横轴 Θ (mm)  = 参考目标 z − 实测 z   (参考取 real_traj_joints.json 最近帧的 p[2])
    纵轴 p       = m·v_z                 (kg·m/s, v 用 >=0.4s 窗口差分, 5Hz 单帧差分不可用)
    U = ½(k_ax·Δz² + k_lat·(Δx²+Δy²)) · K = ½·m·|v|²     H = K + U
    m=3.643 kg · k_ax=400 N/m · k_lat=80 N/m · α=0.15

数据源:
    真机  http://127.0.0.1:39071/status  (10~20Hz, endInRef + jointPos)
    兜底  zmax_data/ss_live/hamiltonian.json (会标 src; 若 src 写着 metaworld/simulation 就是仿真数)

用法:
    DISPLAY=:0 ./gui-venv311/bin/python tools/gui/phase_window.py            # 真机
    DISPLAY=:0 ./gui-venv311/bin/python tools/gui/phase_window.py --jsonl    # 同时落盘
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request
from collections import deque

import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

import pyqtgraph as pg

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVE = os.path.join(ROOT, "zmax_data", "ss_live", "hamiltonian.json")
TRAJ = os.path.join(ROOT, "zmax_data", "rokae_sdk", "real_traj_joints.json")
BRIDGE = "http://127.0.0.1:39071/status"

MASS = 3.643
K_AX = 400.0
K_LAT = 80.0
ALPHA = 0.15


def http_json(url: str, timeout: float = 1.5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class PhaseWindow(QWidget):
    def __init__(self, log_jsonl: bool = False):
        super().__init__()
        self.setWindowTitle("哈密顿量相空间 · 真机口径 (H = K + U)")
        self.resize(980, 700)
        self.log_fh = None
        if log_jsonl:
            d = os.path.join(ROOT, "zmax_data", "ss_live")
            os.makedirs(d, exist_ok=True)
            self.log_fh = open(os.path.join(d, "phase_real_%s.jsonl" % time.strftime("%Y%m%d")), "a")

        self.head = QLabel("等桥…")
        self.head.setStyleSheet("font-family:monospace;font-size:12px;color:#ddd")
        self.head.setWordWrap(True)

        self.pw = pg.PlotWidget(background="#111")
        self.pw.showGrid(x=True, y=True, alpha=0.25)
        self.pw.setLabel("bottom", "Θ = 目标z − 实测z", units="mm")
        self.pw.setLabel("left", "p_z = m·v_z", units="kg·m/s")
        self.curve = self.pw.plot([], [], pen=pg.mkPen("#4fc3f7", width=1), name="尾迹")
        self.dot = self.pw.plot([], [], pen=None, symbol="o", symbolSize=10,
                               symbolBrush="#ff5252", symbolPen=pg.mkPen("#fff"))
        self.ell = self.pw.plot([], [], pen=pg.mkPen("#ffd54f", width=1, style=Qt.DashLine))

        lay = QVBoxLayout(self)
        lay.addWidget(self.head)
        lay.addWidget(self.pw, 1)

        fr = json.load(open(TRAJ, encoding="utf-8"))
        self.frames = fr["frames"]
        self.nfr = len(self.frames)
        self.tail = deque(maxlen=2000)
        self.hist = deque(maxlen=400)          # (t, xyz) 用于 >=0.4s 窗口差分
        self.last_ts = None
        self.last_xy = None
        self.src = "真机 bridge"
        self.tmr = QTimer(self)
        self.tmr.timeout.connect(self.tick)
        self.tmr.start(50)                     # 20Hz

    # ── 数据 ────────────────────────────────────────────────────────────
    def _nearest_frame(self, q):
        best, bi = 1e9, 0
        for i, f in enumerate(self.frames):
            dv = max(abs(f["j"][k] - q[k]) for k in range(6))
            if dv < best:
                best, bi = dv, i
        return bi, best

    def tick(self):
        st = None
        try:
            d = http_json(BRIDGE)
            st = d.get("status") or d
        except Exception:                                              # noqa: BLE001
            st = None
        if st and st.get("endInRef") and st.get("jointPos"):
            self.src = "真机 bridge"
            pos = np.array([float(v) for v in st["endInRef"][:3]], dtype=float)
            q = [float(v) for v in st["jointPos"][:6]]
            ci, cdev = self._nearest_frame(q)
            tgt = np.array([float(v) for v in self.frames[ci]["p"][:3]], dtype=float)
            now = time.time()
            if self.last_ts is not None and now - self.last_ts < 0.02:
                return
            self.last_ts = now
            self.hist.append((now, pos))
            v = np.zeros(3)
            if len(self.hist) >= 2:
                t0, p0 = self.hist[0]
                if now - t0 >= 0.4:
                    v = (pos - p0) / (now - t0)
            d_ax = tgt - pos
            U = 0.5 * (K_LAT * (d_ax[0] ** 2 + d_ax[1] ** 2) + K_AX * d_ax[2] ** 2)
            K = 0.5 * MASS * float(v @ v)
            H = K + U
            th = d_ax[2] * 1000.0
            p = MASS * float(v[2])
            age = 0.0
            if st.get("ts"):
                age = max(0.0, now - float(st["ts"]))
            self.paint(th, p, H, K, U, "帧#%d/%d (Δq %.2f°) · 帧龄 %.1fs · card %s"
                       % (ci + 1, self.nfr, cdev, age, st.get("powerState")))
            self.sample(now, ci, th, p, H, K, U, pos, tgt, "real")
            return

        # 兜底: 引擎落盘的 hamiltonian.json (可能是仿真, 照实标)
        try:
            h = json.load(open(LIVE, encoding="utf-8"))
        except Exception:                                              # noqa: BLE001
            self.head.setText("无数据: 桥不可达且 hamiltonian.json 读不到")
            return
        src = str(h.get("src") or h.get("writer") or "?")
        sim = ("metaworld" in src) or ("仿真" in src) or ("sim" in src.lower())
        th = float(h.get("xi_e", [0, 0, 0])[2]) * 1000.0
        H = float(h.get("H") or 0.0)
        K = float(h.get("K") or 0.0)
        U = float(h.get("U") or 0.0)
        p = MASS * math.sqrt(max(0.0, 2 * K / MASS)) * (1.0 if th >= 0 else -1.0)
        age = max(0.0, time.time() - float(h.get("ts") or 0))
        self.src = "仿真 hamiltonian.json" if sim else "引擎 hamiltonian.json"
        self.paint(th, p, H, K, U, "⚠ 非真机: src=%s · 陈旧 %.1fs" % (src[:42], age))
        self.sample(time.time(), -1, th, p, H, K, U, [0, 0, 0], [0, 0, 0], "json")

    def sample(self, ts, ci, th, p, H, K, U, pos, tgt, kind):
        if self.log_fh:
            self.log_fh.write(json.dumps({
                "ts": round(ts, 3), "src": kind, "i": ci, "th_mm": round(th, 3),
                "p": round(p, 6), "H": round(H, 5), "K": round(K, 5), "U": round(U, 5),
                "tcp": [round(float(x), 5) for x in pos], "tgt": [round(float(x), 5) for x in tgt],
            }, ensure_ascii=False) + "\n")
            self.log_fh.flush()

    # ── 画 ──────────────────────────────────────────────────────────────
    def paint(self, th, p, H, K, U, extra):
        self.tail.append((th, p))
        xs = [a for a, _ in self.tail]
        ys = [b for _, b in self.tail]
        self.curve.setData(xs, ys)
        self.dot.setData([th], [p])
        # 等能椭圆 H = p²/2m + ½k Θ²  ⇒ 半轴 Θ=√(2H/k)·1000mm, p=√(2mH)
        if H > 1e-9:
            a = math.sqrt(2 * H / K_AX) * 1000.0
            b = math.sqrt(2 * MASS * H)
            tt = np.linspace(0, 2 * np.pi, 181)
            self.ell.setData(a * np.cos(tt), b * np.sin(tt))
        else:
            self.ell.setData([], [])
        # 自动缩放: 尾迹/点/等能椭圆要出框才放大, 留 15% 余量
        ex = xs + [th] + (list(self.ell.getData()[0]) if H > 1e-9 else [])
        ey = ys + [p] + (list(self.ell.getData()[1]) if H > 1e-9 else [])
        if ex:
            x0, x1 = min(ex), max(ex)
            y0, y1 = min(ey), max(ey)
            sx = max(1e-6, (x1 - x0) * 0.15)
            sy = max(1e-6, (y1 - y0) * 0.15)
            vb = self.pw.viewRange()
            need = (x0 - sx < vb[0][0]) or (x1 + sx > vb[0][1]) or (y0 - sy < vb[1][0]) or (y1 + sy > vb[1][1])
            if need:
                self.pw.setXRange(x0 - sx, x1 + sx, padding=0)
                self.pw.setYRange(y0 - sy, y1 + sy, padding=0)
        self.head.setText(
            "<span style='color:#4fc3f7'>%s</span> │ Θ=%+.1f mm · p=%+.4f kg·m/s │ "
            "<b>H=%.3f J</b> (K=%.3f U=%.3f) │ ζ=%.3f │ %s"
            % (self.src, th, p, H, K, U, ALPHA * K_AX / (2.0 * math.sqrt(K_AX * MASS)), extra))


def main() -> int:
    app = QApplication(sys.argv)
    w = PhaseWindow(log_jsonl=("--jsonl" in sys.argv))
    w.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
