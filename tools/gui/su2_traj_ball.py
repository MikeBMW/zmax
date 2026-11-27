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

import glob
import json
import math
import os
import time

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
# ▶运行 = ss_engine_loop (10Hz) 把每拍 p=SU(2) 四元数写进 /dev/shm 的 tap。
# 画布 ssobs 节点的 quat_truth observe 只在节点被逐点执行时才写 ⇒ 光点运行不会新增
# ⇒ 轨迹球必须以运行流为首选源, 否则永远停在旧轨迹/空态。
RUN_TAP_DIR = os.environ.get("ZMAX_SS_ENGINE_TAP_DIR") or "/dev/shm/zmax_ss_engine"
RUN_TAP_FRESH_S = 5.0


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
                                "经线=循环形状(南极→北极 正向 / 北极→南极 返回, 换右邻经线)")
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
    def load_run_stream(self):
        """① 运行流 (首选): ss_engine_loop 的 tap, 10Hz 每拍 p=SU(2) 四元数。
        返回 True 表示已用运行流填充 traj/cur; 流陈旧(>5s)或不存在 ⇒ False 走真值源。"""
        try:
            taps = [p for p in glob.glob(os.path.join(RUN_TAP_DIR, "engine_*.jsonl"))
                    if os.path.getsize(p) > 0]
            if not taps:
                return False
            tap = max(taps, key=os.path.getmtime)
            age = time.time() - os.path.getmtime(tap)
            if age > RUN_TAP_FRESH_S:                       # 没在跑: 那条流不算数
                return False
            rows = []
            with open(tap, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:                       # noqa: BLE001
                        continue
                    q = d.get("p")
                    if isinstance(q, (list, tuple)) and len(q) == 4:
                        rows.append((q, d.get("cycle"), d.get("ts_str")))
            if not rows:
                return False
            quats = [_canon(q) for q, _c, _t in rows[-120:]]
            self.traj, self.cur, self.mem = quats, quats[-1], None
            c, ts_s = rows[-1][1], rows[-1][2]
            self.meta = {"src": os.path.basename(tap), "age_s": round(age, 2),
                         "cycle": c, "ts": ts_s, "n": len(rows)}
            self.lbl_src.setText("源: 运行流 %s · cycle %s · %d 拍 · 帧龄 %.1fs"
                                 % (os.path.basename(tap), c, len(rows), age))
            self.canvas.update()
            return True
        except Exception:                                   # noqa: BLE001
            return False

    def reload(self):
        if self.load_run_stream():                          # ▶运行 后的活真源
            return
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
    # ── 规范化「操作循环」: 南极 → 北极 (正向) / 北极 → 南极 (返回, 右邻经线) ──────
    #   老倪 2026-11-03: 「每次起点定义为南极点, 终点定义为北极点, 沿一条经线做正向操作;
    #   再从北极返回南极点 (标识: 从终点返回起点), 但是另一条经线 —— 相邻两条;
    #   每次操作都沿一条经线从南极去北极, 返回沿右侧相邻经线, 周而复始, 循环工作。」
    #   实现: 轨迹先切成**操作段** (增量旋转反向 / 换轴 ⇒ 新的一段); 第 j 段:
    #     · 经度 lon_j = lon0 + j·Δ  (每次都换到右边相邻的一条经线, Δ 默认 20°)
    #     · 偶数 j = 正向: 纬度 −90° → +90° (南极→北极)
    #     · 奇数 j = 返回: 纬度 +90° → −90° (北极→南极)
    #   所以屏幕上永远是"一根经线从上到下/从下到上", 相邻经线并排, 一圈一圈往右排。
    MERIDIAN_STEP_DEG = 20.0

    def cycle_points(self):
        tr = self.traj
        if len(tr) < 2:
            return None
        # ① 切成操作段: 增量旋转与上一段方向相反 (点积<0) 或轴向偏 >25° ⇒ 新段
        sweeps, cur = [], {"vecs": [], "angles": [], "axis": None}
        prev_u = None
        for i in range(1, len(tr)):
            r = _canon(_qmul(np.array([tr[i - 1][0], -tr[i - 1][1], -tr[i - 1][2], -tr[i - 1][3]]),
                             _canon(tr[i])))
            v = r[1:]
            n = float(np.linalg.norm(v))
            a = 2.0 * math.atan2(n, float(abs(r[0])))
            if n < 1e-6 or a < 1e-9:
                continue                                   # 这一步没动: 跳过 (别当换段)
            u = v / n
            if cur["axis"] is None:
                cur["axis"] = u
            else:
                same_axis = float(np.dot(u, cur["axis"])) > math.cos(math.radians(25))
                same_dir = (prev_u is None) or float(np.dot(u, prev_u)) > 0
                if not same_axis or not same_dir:
                    if cur["angles"]:
                        sweeps.append(cur)
                    cur = {"vecs": [], "angles": [], "axis": u}
            cur["vecs"].append(u)
            cur["angles"].append(a)
            prev_u = u
        if cur["angles"]:
            sweeps.append(cur)
        if not sweeps:
            return None
        # ② 每段 → 一条经线上的南北极往返
        out, lon0 = [], 8.0
        for j, sw in enumerate(sweeps):
            tot = float(sum(sw["angles"])) or 1e-9
            acc, pts, lats = 0.0, [], []
            forward = (j % 2 == 0)
            lon = lon0 + j * self.MERIDIAN_STEP_DEG
            lon = ((lon + 180) % 360) - 180
            # 进度用"走这一步之前"的累计角 ⇒ 首点正好落在极点上 (南极/北极), 末点补一个 pr=1 收在另一极
            for a in list(sw["angles"]) + [0.0]:
                pr = acc / tot
                lat = -90.0 + 180.0 * pr if forward else 90.0 - 180.0 * pr
                lats.append(lat)
                la, lo = math.radians(lat), math.radians(lon)
                pts.append(np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)]))
                acc += a
            dev = 0.0
            if sw["axis"] is not None:
                dev = float(np.degrees(math.acos(max(-1.0, min(1.0, abs(float(np.dot(sw["vecs"][-1], sw["vecs"][0])))
                                                                  if sw["vecs"] else 1.0)))))
            out.append({"j": j, "forward": forward, "lon": lon, "lat0": lats[0] if lats else None,
                        "lat1": lats[-1] if lats else None, "pts": pts, "lats": lats,
                        "angle_deg": math.degrees(tot), "axis_dev_deg": dev,
                        "n": len(pts), "axis": sw["axis"]})
        return {"sweeps": out, "n_sweeps": len(out),
                "n_cycles": (len(out) + 1) // 2,
                "cur": out[-1], "meridian_step": self.MERIDIAN_STEP_DEG}

    def canon_points(self):
        """兼容旧名: 返回循环结构的扁平点列 (给旧调用方)。"""
        cp = self.cycle_points()
        if not cp:
            return None
        pts = [p for sw in cp["sweeps"] for p in sw["pts"]]
        lats = [v for sw in cp["sweeps"] for v in sw["lats"]]
        return {"pts": pts, "lat": lats, "lat_end": lats[-1] if lats else 0.0,
                "dev_deg": max((sw["axis_dev_deg"] for sw in cp["sweeps"]), default=0.0),
                "span_deg": 0.0, "circ_std": 0.0, "n_sweeps": cp["n_sweeps"],
                "n_cycles": cp["n_cycles"], "a_max": 1.0, "a_total": 0.0,
                "u_ref": cp["cur"]["axis"] if cp["cur"]["axis"] is not None else np.array([0, 0, 1.0]),
                "near_pi": 0}


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
                  "CANON": "循环经线 (南极→北极 / 北极→南极)"}
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
                    "CANON": "每次操作: 一根经线 南极→北极 (正向) · 返回: 右侧相邻经线 北极→南极 · 周而复始"}[h.mode])

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
        """循环规范视图: 南极→北极 (正向, 一条经线) / 北极→南极 (返回, 右邻经线)。"""
        cp = self.host.cycle_points()
        # 赤道 (虚线) + 南北极
        p.setPen(QPen(QColor("#2f3b4a"), 1.0, Qt.DashLine))
        eq = [self._proj((math.cos(2 * math.pi * k / 72), math.sin(2 * math.pi * k / 72), 0.0))
              for k in range(73)]
        for i in range(1, len(eq)):
            p.drawLine(int(eq[i - 1][0]), int(eq[i - 1][1]), int(eq[i][0]), int(eq[i][1]))
        for vec, lab, col in (((0.0, 0, -1.0), "南极 −90° (起点)", "#58a6ff"),
                              ((0.0, 0, 1.0), "北极 +90° (终点)", "#d29922")):
            x, y, _ = self._proj(vec)
            p.setPen(QPen(QColor(col), 2.0))
            p.setBrush(QColor(col))
            p.drawEllipse(int(x - 5), int(y - 5), 10, 10)
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(col))
            p.drawText(int(x) + 8, int(y) + (14 if vec[2] < 0 else -6), lab)
        if not cp:
            p.setPen(QColor(DIM))
            p.drawText(int(cx) - 70, int(cy) + 20, "空态: 轨迹点不足")
            return
        # 每条操作段的一条经线 (正向蓝 / 返回橙), 当前段加粗
        for sw in cp["sweeps"]:
            col = QColor("#58a6ff") if sw["forward"] else QColor("#d29922")
            cur = (sw is cp["cur"])
            col.setAlpha(230 if cur else 70)
            p.setPen(QPen(col, 2.0 if cur else 1.0))
            mer = []
            for lat in range(-90, 91, 5):
                la, lo = math.radians(lat), math.radians(sw["lon"])
                mer.append(self._proj((math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))))
            for i in range(1, len(mer)):
                p.drawLine(int(mer[i - 1][0]), int(mer[i - 1][1]), int(mer[i][0]), int(mer[i][1]))
        # 轨迹 (按段上色) + 方向箭头
        for sw in cp["sweeps"]:
            pts = sw["pts"]
            col = QColor("#58a6ff") if sw["forward"] else QColor("#d29922")
            for i in range(1, len(pts)):
                a = 90 + int(150 * i / max(1, len(pts)))
                c2 = QColor(col); c2.setAlpha(a)
                p.setPen(QPen(c2, 1.8))
                x0, y0, _ = self._proj(pts[i - 1])
                x1, y1, _ = self._proj(pts[i])
                p.drawLine(int(x0), int(y0), int(x1), int(y1))
            if pts:
                x1, y1, _ = self._proj(pts[-1])
                p.setPen(QPen(col, 2.2))
                p.setBrush(col)
                p.drawEllipse(int(x1 - 4), int(y1 - 4), 8, 8)
        cur = cp["cur"]
        # 读数
        p.setPen(QColor(FG))
        p.drawText(8, 14, "循环 %d · 操作 %d 段 · 当前第 %d 段 %s · 经线 %+.0f°" %
                   (cp["n_cycles"], cp["n_sweeps"], cur["j"] + 1,
                    "正向 南极→北极" if cur["forward"] else "返回 北极→南极", cur["lon"]))
        p.setPen(QColor(DIM))
        p.drawText(8, 28, "本段纬度 %.0f°→%.0f° · 转角 %.1f° · 轴稳定度偏差 %.2f° · 相邻经线间隔 %.0f°" %
                   (cur["lat0"] or 0.0, cur["lat1"] or 0.0, cur["angle_deg"],
                    cur["axis_dev_deg"], cp["meridian_step"]))
        p.setPen(QColor("#6b7686"))
        p.drawText(8, 42, "蓝=正向(南→北) 橙=返回(北→南) · 每次操作换一条右侧相邻经线 · 周而复始")

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
