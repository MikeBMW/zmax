# -*- coding: utf-8 -*-
"""su2_traj_ball.py — 🎯 SU(2) 轨迹球 (画布右侧栏「🧮 主参数 M」页里的一块)

老倪 2026-11-03:
  「四元数不是动作本身, 但它是一把数学游标卡尺。任何三维空间中的旋转操作, 都被它精确地
   映射成了四维球面上的一段滑动轨迹 …… 这段滑动轨迹在画布的右侧栏的主参数, 增加这个 SU2
   球的轨迹, 你来设计 UI, 增加这个球的窗口; 还有, 这个窗口要可以完全隐藏。」

设计取舍 (写清楚, 免得以后有人以为是 S² 那个 Bloch 球)
  · 真身是 **S³** (单位四元数在四维单位球上), 屏幕上只能画三维 ⇒ 用**立体投影**
      p = (x,y,z) / (1.05 − w)
    极点放在 w=+1.05 (球外一点), 这样 w→1 (单位元) 时 p→0 收敛到球心, 不会像从 w=−1 投影
    那样在单位元处炸到无穷。分母恒 ≥ 0.05 ⇒ 数值安全。投影是**一一对应**的 (含 ±q 双覆盖已在
    轨迹生成侧商掉), 屏幕上量到的弧长按同一比例可换回真实旋转角 (标注换算系数)。
  · 另有 S² 视图 (Bloch: 归一化向量部 v/|v|) —— 那是"绕哪根轴", 不含"转多少"的第四维。
    两个视图可切换, 默认 S³。
  · 数据只认真源: `zmax_data/ss_live/quat_truth_calls.jsonl` (每次 observe 的 q_truth/q_fused)
    与 `quat_truth_latest.json`; 没数据就画空态, **不造假点**。
  · 轨迹 = 相邻两次观测之间按 S³ 测地线 (slerp) 补点, 所以看到的是真正"滑动"的弧, 不是折线。

对外接口
  set_trail(quats)      直接喂轨迹 (list of 4-vector) —— 引擎/画布可以逐帧推
  reload()              从真源文件重读
  set_hidden(True/False) 完全隐藏/显示 (发 hiddenChanged 信号, 宿主据此落盘记忆)
"""
from __future__ import annotations

import json
import math
import os

import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

BG = "#0d1117"
PANEL = "#161b22"
EDGE = "#30363d"
FG = "#e6edf3"
DIM = "#8b949e"
TRAIL = "#58a6ff"
NOW = "#3fb950"
MEM = "#d29922"
GRID = "#222833"

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LIVE = os.path.join(os.environ.get("ZMAX_DATA", os.path.join(_ROOT, "zmax_data")), "ss_live")
CALLS = os.path.join(LIVE, "quat_truth_calls.jsonl")
LATEST = os.path.join(LIVE, "quat_truth_latest.json")


# ── 四元数小工具 (独立于引擎, 面板可单独跑) ─────────────────────────────────
def _canon(q):
    q = np.asarray(q, float).reshape(4)
    n = np.linalg.norm(q)
    if n < 1e-12:
        return np.array([1.0, 0, 0, 0])
    q = q / n
    return -q if q[0] < 0 else q


def _slerp(a, b, t):
    a, b = _canon(a), _canon(b)
    d = float(np.dot(a, b))
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        q = a + t * (b - a)
        return q / np.linalg.norm(q)
    th = math.acos(max(-1.0, min(1.0, d)))
    return (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / math.sin(th)


def _s3_angle(a, b):
    """两点在 S³ 上的夹角 (rad) = 物理旋转角的一半。"""
    return 2.0 * math.acos(min(1.0, abs(float(np.dot(_canon(a), _canon(b))))))


def _theta_deg(q):
    q = _canon(q)
    return math.degrees(2.0 * math.atan2(float(np.linalg.norm(q[1:])), float(abs(q[0]))))


class SU2TrajBall(QWidget):
    """SU(2) 轨迹球: S³ 立体投影轨迹 + 当前点 + 记忆基准点 + 隐藏。"""

    hiddenChanged = pyqtSignal(bool)

    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self.root = root or _ROOT
        self.traj = []                      # list[np.ndarray(4)] 已 slerp 补点
        self.cur = None                     # 当前 q_fused
        self.mem = None                     # 记忆基准 q_truth
        self.meta = {}                      # err_deg / V / w / src
        self.mode = "S3"                    # S3 | S2
        self.az, self.el, self.zoom = 0.65, 0.35, 1.0
        self._drag = None
        self._hidden_by_user = False
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:%s;" % BG)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        bar = QFrame()
        bar.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:6px;}" % (PANEL, EDGE))
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 4, 6, 4)
        bl.setSpacing(6)
        self.lbl_hd = QLabel("🎯 SU(2) 轨迹球 · S³ 立体投影")
        self.lbl_hd.setStyleSheet("color:%s;font-size:12px;font-weight:bold;background:transparent;" % FG)
        bl.addWidget(self.lbl_hd)
        self.lbl_src = QLabel("源: 等待 quat_truth …")
        self.lbl_src.setStyleSheet("color:%s;font-size:10px;background:transparent;" % DIM)
        bl.addWidget(self.lbl_src, 1)
        self.btn_mode = QPushButton("S³/S²")
        self.btn_mode.setFixedWidth(56)
        self.btn_mode.setToolTip("S³=四维球面轨迹(含转多少) · S²=Bloch球(只看向哪根轴)")
        self.btn_mode.setStyleSheet(self._btn_css())
        self.btn_mode.clicked.connect(self.toggle_mode)
        bl.addWidget(self.btn_mode)
        self.btn_refresh = QPushButton("🔁")
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.setToolTip("重读真源 (quat_truth_calls.jsonl / quat_truth_latest.json)")
        self.btn_refresh.setStyleSheet(self._btn_css())
        self.btn_refresh.clicked.connect(self.reload)
        bl.addWidget(self.btn_refresh)
        self.btn_hide = QPushButton("⬇ 隐藏")
        self.btn_hide.setFixedWidth(72)
        self.btn_hide.setToolTip("完全隐藏这个窗口 (右侧栏记忆这个选择, 重启后也不弹出来)")
        self.btn_hide.setStyleSheet(self._btn_css())
        self.btn_hide.clicked.connect(lambda: self.set_hidden(True))
        bl.addWidget(self.btn_hide)
        lay.addWidget(bar)

        self.canvas = _Canvas(self)
        lay.addWidget(self.canvas, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.reload)
        self._timer.start()
        QTimer.singleShot(200, self.reload)

    @staticmethod
    def _btn_css():
        return ("QPushButton{background:#21262d;color:#c9d1d9;border:1px solid #30363d;"
                "border-radius:4px;font-size:11px;padding:2px 4px;}"
                "QPushButton:hover{background:#30363d;color:#e6edf3;}")

    # ── 数据 ────────────────────────────────────────────────────────────────
    def reload(self):
        rows = []
        try:
            with open(os.path.join(self.root, "zmax_data", "ss_live", "quat_truth_calls.jsonl"),
                      encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:                                          # noqa: BLE001
                        continue
                    q = d.get("q_fused") or d.get("q_truth")
                    if q and len(q) == 4:
                        rows.append((q, d.get("q_truth"), d))
        except Exception:                                                      # noqa: BLE001
            rows = []
        if not rows:                                                           # 退到最新契约
            try:
                with open(os.path.join(self.root, "zmax_data", "ss_live", "quat_truth_latest.json"),
                          encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("q_fused"):
                    rows = [(d["q_fused"], d.get("q_truth"), d)]
            except Exception:                                                  # noqa: BLE001
                rows = []
        if not rows:
            self.traj, self.cur, self.mem, self.meta = [], None, None, {}
            self.lbl_src.setText("源: 无 (等 quat_truth 第一次观测)")
            self.canvas.update()
            return
        quats, mems = [], []
        for qf, qt, _d in rows[-240:]:
            qf = _canon(qf)
            if quats:                                                          # 段内 slerp 补点 ⇒ 真"滑动"
                for k in range(1, 12):
                    quats.append(_slerp(quats[-1], qf, k / 12.0))
            quats.append(qf)
            if qt:
                mems.append(_canon(qt))
        self.traj = quats
        self.cur = quats[-1] if quats else None
        self.mem = mems[-1] if mems else None
        last = rows[-1][2]
        self.meta = {"err_deg": last.get("err_deg"), "V": last.get("V"),
                     "w": last.get("w_meas"), "src": last.get("src_fuse"),
                     "axis": last.get("axis"), "n": len(rows)}
        self.lbl_src.setText("源: quat_truth · %d 次观测 · %s" % (len(rows), last.get("src_fuse") or "-"))
        self.canvas.update()

    def set_trail(self, quats, mem=None):
        self.traj = [_canon(q) for q in (quats or [])]
        self.cur = self.traj[-1] if self.traj else None
        self.mem = _canon(mem) if mem is not None else None
        self.canvas.update()

    def toggle_mode(self):
        self.mode = "S2" if self.mode == "S3" else "S3"
        self.lbl_hd.setText("🎯 SU(2) 轨迹球 · " +
                            ("S³ 立体投影" if self.mode == "S3" else "S² Bloch (只看向哪根轴)"))
        self.canvas.update()

    # ── 完全隐藏 ────────────────────────────────────────────────────────────
    def set_hidden(self, flag=True, emit=True):
        """完全隐藏: 区块 + 计时器都停 (不空转, 不占布局); 宿主可用 hiddenChanged 落盘。"""
        self._hidden_by_user = bool(flag)
        if flag:
            self._timer.stop()
            super().setVisible(False)
        else:
            super().setVisible(True)
            self._timer.start()
            self.reload()
        if emit:
            self.hiddenChanged.emit(self._hidden_by_user)

    def is_hidden_by_user(self):
        return self._hidden_by_user


class _Canvas(QWidget):
    """QPainter 2.5D 画球 (不开第二个 GL 上下文, 与主窗口共存)。"""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setMinimumHeight(120)

    def _proj(self, p):
        x, y, z = float(p[0]), float(p[1]), float(p[2])
        ca, sa = math.cos(self.host.az), math.sin(self.host.az)
        ce, se = math.cos(self.host.el), math.sin(self.host.el)
        x1, z1 = x * ca - y * sa, x * sa + y * ca
        y1 = z * ce - z1 * se
        z2 = z * se + z1 * ce
        R = min(self.width(), self.height()) * 0.36 * self.host.zoom
        return self.width() / 2.0 + x1 * R, self.height() / 2.0 - y1 * R, z2

    @staticmethod
    def _stereo(q):
        """S³ → R³ 立体投影: p=(x,y,z)/(1.05−w); 极点 w=+1.05 在球外 ⇒ 无奇点。"""
        w, x, y, z = (float(v) for v in q)
        k = 1.0 / max(0.05, 1.05 - w)
        return np.array([x * k, y * k, z * k])

    def _pt_of(self, q):
        if self.host.mode == "S3":
            return self._stereo(q)
        v = np.asarray(q, float)[1:]
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-9 else np.array([0.0, 0, 1.0])

    def paintEvent(self, ev):
        h = self.host
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(BG))
        W, H = self.width(), self.height()
        R = min(W, H) * 0.36 * h.zoom
        cx, cy = W / 2.0, H / 2.0

        # 球体 + 网格
        p.setPen(QPen(QColor("#2b3240"), 1.2))
        p.drawEllipse(int(cx - R), int(cy - R), int(2 * R), int(2 * R))
        for ang in (30, 60, 90, 120, 150):
            t = math.radians(ang)
            p.setPen(QPen(QColor(GRID), 1.0))
            p.drawEllipse(int(cx - R), int(cy - R * abs(math.cos(t))), int(2 * R),
                          max(1, int(2 * R * abs(math.cos(t)))))
            p.drawEllipse(int(cx - R * abs(math.sin(t))), int(cy - R),
                          max(1, int(2 * R * abs(math.sin(t)))), int(2 * R))
        # 轴
        for vec, lab in (((1, 0, 0), "x"), ((0, 1, 0), "y"), ((0, 0, 1), "z")):
            x1, y1, _ = self._proj(vec)
            p.setPen(QPen(QColor("#3a4252"), 1.0, Qt.DashLine))
            p.drawLine(int(cx), int(cy), int(x1), int(y1))
            p.setPen(QColor(DIM))
            p.drawText(int(x1) + 2, int(y1) - 2, lab)
        p.setPen(QColor("#6b7686"))
        p.setFont(QFont("Consolas", 8))
        p.drawText(8, int(H - 6), ("S³ 立体投影 p=(x,y,z)/(1.05−w) · 拖动旋转 · 滚轮缩放"
                                   if h.mode == "S3" else "S² Bloch (v/|v|)"))

        # 轨迹 (按时间渐变蓝→亮)
        tr = h.traj
        if len(tr) > 1:
            n = len(tr)
            for i in range(1, n):
                a = 50 + int(190 * i / n)
                p.setPen(QPen(QColor(88, 166, 255, a), 1.6))
                x0, y0, _ = self._proj(self._pt_of(tr[i - 1]))
                x1, y1, _ = self._proj(self._pt_of(tr[i]))
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
            # 起点
            x0, y0, _ = self._proj(self._pt_of(tr[0]))
            p.setPen(QPen(QColor(DIM), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(x0 - 4), int(y0 - 4), 8, 8)
        # 记忆基准 (真值)
        if h.mem is not None:
            xm, ym, _ = self._proj(self._pt_of(h.mem))
            p.setPen(QPen(QColor(MEM), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(xm - 6), int(ym - 6), 12, 12)
            p.setPen(QColor(MEM))
            p.drawText(int(xm) + 8, int(ym) + 12, "q_truth")
        # 当前点
        if h.cur is not None:
            xc, yc, _ = self._proj(self._pt_of(h.cur))
            p.setPen(QPen(QColor(NOW), 2.0))
            p.setBrush(QColor(NOW))
            p.drawEllipse(int(xc - 5), int(yc - 5), 10, 10)
            p.setPen(QColor(FG))
            p.drawText(int(xc) + 8, int(yc) - 6, "q_fused")
            # 读数
            arc = 0.0
            for i in range(1, len(tr)):
                arc += _s3_angle(tr[i - 1], tr[i])
            m = h.meta or {}
            txt = "θ=%.2f°  |w|=%.4f  S³弧长=%.3f rad (≈%.1f°)  点=%d" % (
                _theta_deg(h.cur), abs(float(h.cur[0])), arc, math.degrees(2 * arc), len(tr))
            p.setPen(QColor(FG))
            p.drawText(8, 14, txt)
            m2 = "补偿误差=%.3f°  势V=%.5f  测量权重=%.2f  轴=%s" % (
                float(m.get("err_deg") or 0.0), float(m.get("V") or 0.0),
                float(m.get("w") or 0.0), m.get("axis") or "-")
            p.setPen(QColor(DIM))
            p.drawText(8, 28, m2)
        else:
            p.setPen(QColor(DIM))
            p.drawText(int(cx - 70), int(cy), "空态: 等 quat_truth 观测 (不画假点)")
        p.end()

    # 交互
    def mousePressEvent(self, e):
        self._drag = (e.x(), e.y())

    def mouseMoveEvent(self, e):
        if self._drag:
            dx, dy = e.x() - self._drag[0], e.y() - self._drag[1]
            self.host.az += dx * 0.01
            self.host.el = max(-1.5, min(1.5, self.host.el + dy * 0.01))
            self._drag = (e.x(), e.y())
            self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def wheelEvent(self, e):
        self.host.zoom = max(0.6, min(2.2, self.host.zoom * (1.1 if e.angleDelta().y() > 0 else 0.9)))
        self.update()
