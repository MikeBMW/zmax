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


def _qmul(a, b):
    aw, ax, ay, az = (float(v) for v in a)
    bw, bx, by, bz = (float(v) for v in b)
    return np.array([aw * bw - ax * bx - ay * by - az * bz,
                     aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw])


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
        self.mode = "S3"                    # S3 | S2 | CANON(规范化经线: 赤道→北极)
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
        self.btn_mode = QPushButton("S³")
        self.btn_mode.setFixedWidth(64)
        self.btn_mode.setToolTip("切换视图: S³=四维球面真实轨迹 · S²=Bloch(只看向哪根轴) · "
                                "经线=规范化形状(赤道→北极, 同轴=同一条经线)")
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

        # 默认看「规范化经线」(老倪 2026-11-03: 「规范成某一条经线, 从赤道到北极」), 上次选择会被记住
        try:
            from PyQt5.QtCore import QSettings
            _m = str(QSettings("ZMAX", "studio").value("mparam/su2_mode", "CANON"))
            if _m in self.MODE_SEQ:
                self.mode = _m
                self.lbl_hd.setText("🎯 SU(2) 轨迹球 · " + self.MODE_TITLE[self.mode])
                self.btn_mode.setText(self.MODE_TAG[self.mode])
        except Exception:                                                      # noqa: BLE001
            pass
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

    # ── 规范化轨迹 (老倪: 「能不能规范成一条经线, 从赤道到北极」) ─────────────
    def canon_points(self):
        """把轨迹**规范化**成球面坐标 (纬度=进度, 经度=轴向)。

        物理含义: 每个点相对起点的旋转 r_i = q_i ⊗ q_0⁻¹ 有 (角度 a_i, 轴 u_i)。
          · 纬度 lat_i = 90° · a_i / a_max   ⇒ 赤道(0°)→北极(90°) 就是"转了多少"的进度
          · 经度 lon_i = 有符号角(u_i, u_ref) ⇒ 同一根轴 = 同一条经线, 换轴才换经线
        所以单轴旋转画出来是**严丝合缝的一条经线 (赤道→北极)**; 多轴混合才会分叉, 分叉多少
        就用"规范性偏差 RMS"给数字 (不糊)。
        ⚠ 角度接近 0 时旋转轴是病态的 (r≈单位元 ⇒ v≈0, 方向纯噪声) ⇒ 这些点**继承最近的有效轴**,
          否则会在起点附近甩出一大段假经度 (第一版就踩了, 单轴 90° 测出经度跨度 90°)。
        """
        tr = self.traj
        if len(tr) < 2:
            return None
        q0 = _canon(tr[0])
        q0i = np.array([q0[0], -q0[1], -q0[2], -q0[3]])
        angs, axes = [], []
        for q in tr:
            r = _canon(_qmul(q0i, _canon(q)))
            v = r[1:]
            n = float(np.linalg.norm(v))
            angs.append(2.0 * math.atan2(n, float(abs(r[0]))))
            axes.append((v / n) if n > 1e-6 else None)          # 病态轴先标 None
        good = [i for i, a in enumerate(axes) if a is not None]
        if not good:
            return None
        # 有效轴按角度加权 ⇒ 主轴 (整段转向的代表轴)
        wsum = np.zeros(3)
        for i in good:
            wsum += angs[i] * axes[i]
        u_ref = wsum / np.linalg.norm(wsum) if np.linalg.norm(wsum) > 1e-9 else axes[good[-1]]
        # 病态点继承"最近的有效轴"
        for i in range(len(axes)):
            if axes[i] is None:
                k = min(good, key=lambda j: abs(j - i))
                axes[i] = axes[k]
        # π 附近轴的正负号是同一旋转的两种写法 (q 与 −q) ⇒ 按连续性定号, 否则经度会整段甩到对面
        amb = 0
        for i in range(1, len(axes)):
            if abs(angs[i] - math.pi) < 0.15:
                if float(np.dot(axes[i], axes[i - 1])) < 0:
                    axes[i] = -axes[i]
                amb += 1
        a_max = max(angs) if max(angs) > 1e-9 else 1.0
        ref_dir = self._lon_ref(u_ref)
        pts, lons, lats = [], [], []
        for a, u in zip(angs, axes):
            c = float(np.clip(np.dot(u, u_ref), -1, 1))
            nrm = np.cross(u_ref, u)
            nn = float(np.linalg.norm(nrm))
            off = math.atan2(nn, c)                                    # 与主轴夹角
            sign = 1.0
            if nn > 1e-12:
                sign = 1.0 if float(np.dot(nrm / nn, ref_dir)) >= 0 else -1.0
            lon = math.degrees(off) * sign
            lat = 90.0 * min(1.0, a / a_max)
            lons.append(lon); lats.append(lat)
            la, lo = math.radians(lat), math.radians(lon)
            pts.append(np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)]))
        # 圆周统计: 经度是角度, 直接 max−min 会在 ±180° 处把同一根经线算成 180° 跨度
        _lr = np.radians(np.asarray(lons, float))
        _R = float(np.hypot(np.cos(_lr).mean(), np.sin(_lr).mean()))
        circ_std = math.degrees(math.sqrt(max(0.0, -2.0 * math.log(max(_R, 1e-12)))))
        _mean = math.degrees(math.atan2(float(np.sin(_lr).mean()), float(np.cos(_lr).mean())))
        span = 2.0 * max([abs(((v - _mean + 180) % 360) - 180) for v in lons] or [0.0])
        lons = [((v + 180) % 360) - 180 for v in lons]          # 归一到 (-180,180]
        dev = float(np.sqrt(np.mean([v * v for v in lons])))    # 规范度: 相对主经线的 RMS 偏离
        _ = circ_std
        return {"pts": pts, "lon": lons, "lat": lats, "a_max": a_max,
                "a_total": float(sum(angs)), "u_ref": u_ref, "dev_deg": dev,
                "lat_end": lats[-1], "near_pi": amb, "span_deg": span, "circ_std": circ_std}

    @staticmethod
    def _lon_ref(u_ref):
        """给主轴定一个固定的经度参考方向 (与 u_ref 垂直), 保证同一根轴经度符号稳定。"""
        t = np.array([0.0, 0, 1.0])
        if abs(float(np.dot(t, u_ref))) > 0.95:
            t = np.array([1.0, 0, 0])
        d = np.cross(u_ref, t)
        n = np.linalg.norm(d)
        return d / n if n > 1e-12 else np.array([1.0, 0, 0])

    def set_trail(self, quats, mem=None):
        self.traj = [_canon(q) for q in (quats or [])]
        self.cur = self.traj[-1] if self.traj else None
        self.mem = _canon(mem) if mem is not None else None
        self.canvas.update()

    MODE_SEQ = ("S3", "S2", "CANON")
    MODE_TITLE = {"S3": "S³ 立体投影", "S2": "S² Bloch (只看向哪根轴)",
                  "CANON": "规范化经线 (赤道→北极)"}
    MODE_TAG = {"S3": "S³", "S2": "S²", "CANON": "经线"}

    def toggle_mode(self):
        i = self.MODE_SEQ.index(self.mode) if self.mode in self.MODE_SEQ else 0
        self.mode = self.MODE_SEQ[(i + 1) % len(self.MODE_SEQ)]
        self.lbl_hd.setText("🎯 SU(2) 轨迹球 · " + self.MODE_TITLE[self.mode])
        self.btn_mode.setText(self.MODE_TAG[self.mode])
        try:
            from PyQt5.QtCore import QSettings
            _q = QSettings("ZMAX", "studio")
            _q.setValue("mparam/su2_mode", self.mode)
            _q.sync()
        except Exception:                                                      # noqa: BLE001
            pass
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
        p.drawText(8, int(H - 6),
                   {"S3": "S³ 立体投影 p=(x,y,z)/(1.05−w) · 拖动旋转 · 滚轮缩放",
                    "S2": "S² Bloch (v/|v|) · 只看「绕哪根轴」",
                    "CANON": "规范化经线: 纬度=转了多少(0→90°) · 经度=轴向(同轴=同一条经线)"}[h.mode])

        # ══ 规范化经线视图: 赤道 → 北极 ══
        if h.mode == "CANON":
            self._paint_canon(p, int(cx), int(cy), R)
            p.end()
            return

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

    def _paint_canon(self, p, cx, cy, R):
        """球 + 赤道 + 主经线 + 刻度(0/30/60/90) + 规范化轨迹 (赤道→北极)。"""
        from PyQt5.QtCore import QPointF
        # 赤道
        p.setPen(QPen(QColor("#3a4252"), 1.4))
        eq = []
        for k in range(73):
            t = 2 * math.pi * k / 72
            eq.append(self._proj((math.cos(t), math.sin(t), 0.0)))
        for i in range(1, len(eq)):
            p.drawLine(int(eq[i - 1][0]), int(eq[i - 1][1]), int(eq[i][0]), int(eq[i][1]))
        # 主经线 (经度 0)
        p.setPen(QPen(QColor("#2f3b4a"), 1.2, Qt.DashLine))
        mer = [self._proj((math.cos(math.radians(l)), 0.0, math.sin(math.radians(l))))
               for l in range(-90, 91, 5)]
        for i in range(1, len(mer)):
            p.drawLine(int(mer[i - 1][0]), int(mer[i - 1][1]), int(mer[i][0]), int(mer[i][1]))
        # 刻度 0/30/60/90 (纬度)
        p.setFont(QFont("Consolas", 8))
        for lat in (0, 30, 60, 90):
            x, y, _ = self._proj((math.cos(math.radians(lat)), 0.0, math.sin(math.radians(lat))))
            p.setPen(QPen(QColor("#4a5566"), 1.2))
            p.drawLine(int(x - 4), int(y), int(x + 4), int(y))
            p.setPen(QColor(DIM))
            p.drawText(int(x + 6), int(y) + 3, "%d°" % lat)
        # 北极 (目标) 与赤道 (起点) 标签
        xn, yn, _ = self._proj((0.0, 0.0, 1.0))
        p.setPen(QColor("#8b949e"))
        p.drawText(int(xn) + 8, int(yn) - 6, "北极 90°=转到位")
        xq, yq, _ = self._proj((1.0, 0.0, 0.0))
        p.drawText(int(xq) + 6, int(yq) + 12, "赤道 0°=起点")

        cp = self.host.canon_points()
        if not cp:
            p.setPen(QColor(DIM))
            p.drawText(int(cx) - 60, int(cy) + 20, "空态: 轨迹点不足")
            return
        pts = cp["pts"]
        n = len(pts)
        for i in range(1, n):
            a = 50 + int(190 * i / n)
            p.setPen(QPen(QColor(88, 166, 255, a), 1.8))
            x0, y0, _ = self._proj(pts[i - 1])
            x1, y1, _ = self._proj(pts[i])
            p.drawLine(int(x0), int(y0), int(x1), int(y1))
        xc, yc, _ = self._proj(pts[-1])
        p.setPen(QPen(QColor(NOW), 2.0))
        p.setBrush(QColor(NOW))
        p.drawEllipse(int(xc - 5), int(yc - 5), 10, 10)
        # 读数: 规范性偏差 + 进度
        p.setPen(QColor(FG))
        p.drawText(8, 14, "规范性偏差 RMS=%.1f° 经度跨度=%.1f° 进度=%.1f°" %
                   (cp["dev_deg"], cp["span_deg"], cp["lat_end"]))
        p.setPen(QColor(DIM))
        p.drawText(8, 28, "归一化分母 a_max=%.1f° 累计角=%.1f° 主轴=(%.2f,%.2f,%.2f)" %
                   (math.degrees(cp["a_max"]), math.degrees(cp["a_total"]), *cp["u_ref"]))
        if cp["dev_deg"] < 1.0:
            p.setPen(QColor(NOW))
            p.drawText(8, 42, "✔ 单轴: 正好一条经线 (赤道→北极)")

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
