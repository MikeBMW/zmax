#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifold_viz.py — 流形引擎可视化 (S³ 立体投影球 · 切空间 · 度量场 · 时间序列)。

老倪 (2026-10-16) 方案八条, 逐条落到四个面板 (左上/右上/左下/右下, 共享同一时间轴):

  二、状态点   S³ ⊂ R⁴ 是单位四元数 ⇒ 立体投影到 R³ (北极→无穷远, 南极→原点) 后画点;
               点密度 = 状态分布 (聚集=集中, 分散=多样); 再降二维用颜色表第四维。
  三、切空间   当前状态处画三维坐标系, 箭头 = 梯度/速度/力; 度量椭球 = 各向异性 (轴长 = 度量值)。
  四、测地线   S³ 上大圆 (sphere.great_circle_path / geodesic_slerp) 投影后仍是圆或直线, 画出最短路径。
  五、度量场   球面采样若干点各画度量椭球 ⇒ 形状/方向随位置变不变 = 度量均不均匀。
  六、轨迹     轨迹 = 球上一条曲线, 用**颜色表示时间** (起点→终点渐变); 偏离测地线 = 曲线弯曲。
  七/八、综合  四面板 + 共享时间轴同步更新; 看到的是**投影后的球面** = 单位球 (正是 S³ 赤道 {p₄=0} 的像),
               球面上有运动的状态点、状态点处有切标架与椭球、球面上有大圆测地线。

真源 (一处取, 不硬编; 缺了就空态, 绝不画假点):
  · 实时状态      `zmax_data/ss_live/engine_latest.json`     (p 四元数 · M · phi · ts/帧龄 · manifold 类型)
  · 真实轨迹      `data/database/zmax/sources/canvas/ss_traj_last.json` (· 控制台 `_ss_tr` 落盘)
                  obs[i][3:7] = 单位四元数状态, t[i] = 时间, u_exec_vec[i] = 执行动作
  · 标定真源      `config/calib/zmax_manifold.json`          (M=3.643 · 度量 diag · dim)
  · 画布节点      `…/sources/canvas/state_space_obs.json` → n_calib_mani.params (m_dim/m_diag/m_metric)
  · 几何算子      `src/lerobot/manifold/sphere.py`           (**单真源**: 立体投影/测地线/平行移动/黎曼梯度)

渲染: QPainter 2.5D 正交投影自绘 (球面预渲染 QPixmap + 动态元素叠加), **零 GL 依赖** ——
      画布主窗口已有 GL 上下文, 第二/多 GL 控件会踩 pyqtgraph shader 跨上下文崩
      (技能 `qt-gl-rendering-pitfalls`)。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import numpy as np

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPixmap, QBrush, QPolygonF, QLinearGradient
from PyQt5.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QPushButton, QSlider, QSizePolicy)

# ── 几何算子单真源 (仓库铁律: 不许第二份公式) ────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
def _load_by_path(modname, relpath, label):
    """按**工程根下的文件路径**加载模块 —— 不受 sys.path 顺序影响。

    🐛 2026-10-16 实测踩到的真坑: 控制台里 `lerobot` 可能先解析到 fork
    (`external/lerobot-smolvla-lew/src/lerobot`), 而 fork 的 `manifold/` **没有 sphere.py**
    ⇒ `from lerobot.manifold import sphere` 抛 ImportError ⇒ 面板全变空态 (页面上只有橙色空态字,
    球/轨迹一个都不画)。可视化要的是**工程自己的真源算子**, 所以按绝对路径显式加载 ——
    仍然是同一份源码 (单真源), 不是复制公式。
    """
    import importlib.util
    fpath = os.path.join(_ROOT, relpath)
    if not os.path.isfile(fpath):
        return None, "缺文件: %s" % fpath
    try:
        spec = importlib.util.spec_from_file_location(modname, fpath)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        return mod, ""
    except Exception as e:                                  # noqa: BLE001
        return None, "%s: %s: %s" % (label, type(e).__name__, e)


SP, _SP_ERR = _load_by_path("_zmax_manifold_sphere", os.path.join("src", "lerobot", "manifold", "sphere.py"), "sphere.py")
if SP is None or not hasattr(SP, "stereographic_project"):  # 老版/别的树的 sphere.py 也当不可用 (避免画出错几何)
    _SP_ERR = _SP_ERR or "sphere.py 缺 stereographic_project"
    SP = None
# L2 执行层同源映射: obs43 → SU(2) (几何误差的群表示; e→0 ⇒ U→I) —— 与流形引擎同源, 同样按路径加载
SU2, _SU2_ERR = _load_by_path("_zmax_state_space_su2",
                              os.path.join("src", "lerobot", "policies", "left_right", "state_space", "su2.py"), "su2.py")
if SU2 is not None and not hasattr(SU2, "encode_obs43"):
    _SU2_ERR = "su2.py 缺 encode_obs43"
    SU2 = None

BG = "#0d1117"
FG = "#e6edf3"
DIM = "#8b949e"
GRID = "#243040"
CYAN = "#39c5cf"
GREEN = "#3fb950"
ORANGE = "#d29922"
VIOLET = "#a371f7"
RED = "#f85149"
MONO = "Consolas,monospace"


def _int(v, lo=-10 ** 7, hi=10 ** 7):
    """Qt API 的尺寸/坐标一律先转 int (PyQt5 不做隐式转换: float 直接 TypeError → paint 里 abort)。"""
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except Exception:
        return 0


def _time_color(u):
    """时间渐变: 起点蓝 → 中间青绿 → 终点橙红 (老倪: 用颜色表示时间, 从起点到终点渐变)。"""
    u = max(0.0, min(1.0, float(u)))
    if u < 0.5:
        k = u / 0.5
        return QColor(_int(57 + k * (63 - 57)), _int(130 + k * (197 - 130)), _int(247 + k * (207 - 247)))
    k = (u - 0.5) / 0.5
    return QColor(_int(63 + k * (210 - 63)), _int(197 + k * (153 - 197)), _int(207 + k * (34 - 207)))


# ═══════════════════════════ 数据层 (真源只读) ═══════════════════════════
class ManifoldData:
    """流形可视化数据: 读真源 + 算几何 (全部用 sphere.py 的真公式)。缺文件 = 空态, 不造数。"""

    def __init__(self, root=None):
        self.root = root or _ROOT
        self.reset()
        self.reload()

    def reset(self):
        self.live = {}
        self.traj = {}
        self.mani = {}
        self.node = {}
        self.err = []
        self.t = np.zeros(0)
        self.Q = np.zeros((0, 4))
        self.live_p = None
        self.live_age = None
        self.M = None
        self.M_src = ""
        self.metric = {}
        self.v = np.zeros((0, 4))
        self.speed = np.zeros(0)
        self.force = np.zeros(0)
        self.dist = np.zeros(0)
        self.geo = np.zeros((0, 4))
        self.geo_len = 0.0
        self.geo_theta = 0.0
        self.geo_deg = True
        self.geo_live = np.zeros((0, 4))
        self.geo_live_len = 0.0
        self.geo_live_deg = True
        self.traj_saved_at = ""
        self.traj_src = ""
        self.n = 0

    # ── 真源读取 ──
    def _j(self, *rel):
        p = os.path.join(self.root, *rel)
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.err.append("%s: %s" % ("/".join(rel), e))
            return {}

    def reload(self):
        self.reset()
        self.live = self._j("zmax_data", "ss_live", "engine_latest.json")
        self.traj = self._j("data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
        self.mani = self._j("config", "calib", "zmax_manifold.json")
        node = self._j("data", "database", "zmax", "sources", "canvas", "state_space_obs.json")
        for nd in (node.get("nodes") or []):
            if isinstance(nd, dict) and nd.get("id") == "n_calib_mani":
                self.node = nd.get("params") or {}
                break

        # ── M: 标定真源优先 (画布节点快照只作对照) ──
        try:
            if self.mani.get("M") is not None:
                self.M = float(self.mani["M"])
                self.M_src = "config/calib/zmax_manifold.json (标定真源)"
            elif self.node.get("M") is not None:
                self.M = float(self.node["M"])
                self.M_src = "画布节点 n_calib_mani.params.M (真源缺)"
        except Exception as e:
            self.err.append("M: %s" % e)
        self.M_node = self.node.get("M")
        self.inertia = bool(self.mani.get("inertia", self.node.get("inertia", False)))

        # ── 度量 (标定真源; 画布节点同源备份) ──
        mm = self.mani.get("metric") or {}
        self.metric = {"dim": int(mm.get("dim") or self.node.get("m_dim") or 0),
                       "mode": mm.get("mode") or "diag",
                       "diag": list(mm.get("diag") or self.node.get("m_diag") or []),
                       "src": "config/calib/zmax_manifold.json::metric"}

        # ── 实时状态 ──
        p = self.live.get("p")
        if isinstance(p, (list, tuple)) and len(p) == 4 and SP is not None:
            pp = np.asarray(p, float)
            if abs(float(np.linalg.norm(pp)) - 1.0) < 1e-6:      # 单位四元数才收 (非单位 ⇒ 先归一化并标记)
                self.live_p = pp
            else:
                self.live_p, _m = SP.normalize(pp)
                self.err.append("engine_latest.p 非单位 (r=%.6f) → 已归一化显示" % _m["r_in"])
        try:
            self.live_age = max(0.0, time.time() - float(self.live.get("ts")))
        except Exception:
            self.live_age = None

        # ── 真实轨迹 (obs[i][3:7] = 单位四元数) ──
        obs = self.traj.get("obs") or []
        tt = self.traj.get("t") or []
        self.traj_saved_at = str(self.traj.get("saved_at") or "")
        self.traj_src = str(self.traj.get("src") or "")
        Q, T = [], []
        self.state_src = ""
        for i, o in enumerate(obs):
            if not isinstance(o, (list, tuple)) or len(o) < 7:
                continue
            q = None
            if SU2 is not None:                                  # ① 引擎同源: L2 执行层 obs43 → SU(2)
                try:
                    u = SU2.encode_obs43(np.asarray(o, float))
                    q = np.asarray([u.w, u.x, u.y, u.z], float)
                    self.state_src = "su2.encode_obs43 (L2 执行层 obs43→SU(2), 与流形引擎同源)"
                except Exception as e:
                    self.err.append("encode_obs43: %s" % e)
                    q = None
            if q is None:                                        # ② 退回: obs[3:7] 四元数 (同一真源里的位姿四元数)
                q = np.asarray(o[3:7], float)
                self.state_src = "obs[3:7] (轨迹真源里的位姿四元数)"
            nq = float(np.linalg.norm(q))
            if nq < 1e-9:
                continue
            Q.append(q / nq)
            T.append(float(tt[i]) if i < len(tt) else float(i))
        if Q and SP is not None:
            self.Q = np.asarray(Q)
            self.t = np.asarray(T)
            self.n = len(self.Q)
            self._derive()

    def _derive(self):
        """几何量全部用 sphere.py 真公式: 测地速度 (log 映射), 力 (M·Δv/dt), 测地距离, 大圆路径。"""
        n = self.n
        dt = np.diff(self.t)
        dt = np.where(dt <= 0, 1e-3, dt)
        v = np.zeros((n, 4))
        for i in range(n - 1):
            v[i] = SP.log_map(self.Q[i], self.Q[i + 1]) / float(dt[i])       # 切向量 (对数映射/时间)
        if n >= 2:
            v[n - 1] = SP.parallel_transport(self.Q[n - 2], self.Q[n - 1], v[n - 2])
        v = np.asarray([SP.tangent_project(self.Q[i], v[i]) for i in range(n)]) if n else v
        self.v = v
        self.speed = np.linalg.norm(v, axis=1) if n else np.zeros(0)
        M = float(self.M) if self.M else 1.0
        a = np.zeros((n, 4))
        for i in range(n - 1):
            dv = v[i + 1] - SP.parallel_transport(self.Q[i], self.Q[i + 1], v[i])
            a[i] = dv / float(dt[i])
        self.force = (M * np.linalg.norm(a, axis=1)) if n else np.zeros(0)
        tgt = self.Q[-1]
        self.dist = np.asarray([SP.distance(self.Q[i], tgt) for i in range(n)]) if n else np.zeros(0)
        # 大圆测地线 (老倪方案四: 起点→终点的大圆路径; sphere.great_circle_path 返回 dict)
        gp = SP.great_circle_path(self.Q[0], tgt, 64)
        self.geo = np.asarray(gp["path"], float)                 # 起点帧 → 目标帧
        self.geo_len = float(gp["length"])                       # 逐段求和真弧长
        self.geo_theta = float(gp["theta"])                      # 解析夹角 (=内蕴距离)
        self.geo_deg = bool(self.geo_len < 1e-9)
        self.geo_live = np.zeros((0, 4))
        self.geo_live_deg = True
        if self.live_p is not None:                              # 实时状态 → 目标 (引擎回放时常见退化)
            gl = SP.great_circle_path(self.live_p, tgt, 64)
            self.geo_live = np.asarray(gl["path"], float)
            self.geo_live_len = float(gl["length"])
            self.geo_live_deg = bool(gl["theta"] < 1e-6)

    # ── 便捷 ──
    def frame_state(self, i):
        """当前帧状态: 轨迹帧 (i) 与实时状态各自独立 (实时状态另标, 不混进轨迹)。"""
        if self.n == 0:
            return None
        i = max(0, min(self.n - 1, int(i)))
        return self.Q[i]

    def summary(self):
        return {"n": self.n, "M": self.M, "M_src": self.M_src, "inertia": self.inertia,
                "live_age": self.live_age, "live_p": None if self.live_p is None else self.live_p.tolist(),
                "metric": self.metric, "geo_len": self.geo_len, "err": list(self.err),
                "traj_saved_at": self.traj_saved_at, "traj_src": self.traj_src,
                "state_src": getattr(self, "state_src", ""),
                "dist_end": float(self.dist[0]) if self.n else None,
                "speed_mean": float(np.mean(self.speed)) if self.n else None}


# ═══════════════════════════ 相机 (正交 2.5D, 可拖动旋转) ═══════════════════════════
class Cam:
    def __init__(self, az_deg=35.0, el_deg=22.0, scale=1.0):
        self.az = math.radians(float(az_deg))
        self.el = math.radians(float(el_deg))
        self.scale = float(scale)

    def basis(self):
        ce, se = math.cos(self.el), math.sin(self.el)
        ca, sa = math.cos(self.az), math.sin(self.az)
        eye = np.array([ce * sa, -ce * ca, se])
        fwd = -eye / np.linalg.norm(eye)
        right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
        nr = np.linalg.norm(right)
        right = right / nr if nr > 1e-9 else np.array([1.0, 0.0, 0.0])
        up = np.cross(right, fwd)
        return eye, fwd, right, up

    def project(self, pts, cx, cy, r_px):
        """pts: (k,3) → 屏幕坐标 (k,2) + 深度 (k,)。正交投影, 半径单位球 ~ r_px 像素。"""
        pts = np.atleast_2d(np.asarray(pts, float))
        _, fwd, right, up = self.basis()
        x = pts @ right
        y = pts @ up
        d = pts @ fwd
        s = float(r_px) / 1.0
        return np.stack([cx + x * s, cy - y * s], axis=1), d


# ═══════════════════════════ 面板一: S³ 立体投影球 ═══════════════════════════

def _fit(p, text, width):
    """按**面板宽度**省略画文字 —— 面板窄时绝不越框压到隔壁 (老倪: 不许挤/不许截断)。

    ⚠️ `QFontMetrics.elidedText` 的宽度参数必须是 **int**: 传 float 会抛 TypeError 被
    except 吞掉 ⇒ 静默退回"不省略" ⇒ 文字又压到面板外 (本文件 356 行记过同一个坑)。
    """
    try:
        return p.fontMetrics().elidedText(str(text), Qt.ElideRight, int(max(24, width)))
    except Exception:                                                        # noqa: BLE001
        return str(text)

class PanelBall(QWidget):
    """左上: 立体投影后的球面 + 当前状态点 + 时间着色轨迹 + 测地线。"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.d = data
        self.i = 0
        self.cam = Cam(35.0, 22.0)
        self._drag = None
        self._cache = None
        self._cache_key = None
        self.setMinimumSize(260, 220)
        self.setMouseTracking(True)

    def set_frame(self, i):
        self.i = int(i)
        self.update()

    # ── 预渲染: 单位球 (S³ 赤道 {p₄=0} 的像) 经纬格线, 一次画进 QPixmap, 每帧只叠动态元素 ──
    def _sphere_pixmap(self, w, h):
        key = (w, h, round(self.cam.az, 4), round(self.cam.el, 4))
        if self._cache_key == key and self._cache is not None:
            return self._cache
        pm = QPixmap(max(1, w), max(1, h))
        pm.fill(QColor(BG))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.40
        grids = []
        for k in range(1, 4):                                  # 纬度圈 (z = 常数)
            z = -0.75 + 0.5 * (k - 1)
            rr = math.sqrt(max(0.0, 1.0 - z * z))
            th = np.linspace(0, 2 * math.pi, 73)
            grids.append((np.stack([rr * np.cos(th), rr * np.sin(th), np.full_like(th, z)], axis=1), 0.55))
        for k in range(4):                                     # 经度圈
            al = math.pi * k / 4.0
            th = np.linspace(0, 2 * math.pi, 97)
            grids.append((np.stack([np.cos(th) * math.cos(al), np.cos(th) * math.sin(al), np.sin(th)], axis=1), 0.8))
        segs = []
        for pts, lw in grids:
            xy, d = self.cam.project(pts, cx, cy, r)
            for j in range(len(xy) - 1):
                segs.append((float((d[j] + d[j + 1]) * 0.5), xy[j], xy[j + 1], lw))
        segs.sort(key=lambda s: s[0])                          # 远 → 近
        for _, a, b, lw in segs:
            p.setPen(QPen(QColor(GRID), max(1, int(lw))))
            p.drawLine(QPointF(a[0], a[1]), QPointF(b[0], b[1]))
        # 赤道加粗 (S³ 赤道的像 = 单位球面本身)
        th = np.linspace(0, 2 * math.pi, 145)
        eq = np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], axis=1)
        xy, _ = self.cam.project(eq, cx, cy, r)
        p.setPen(QPen(QColor("#3b4a5f"), 2))
        for j in range(len(xy) - 1):
            p.drawLine(QPointF(xy[j][0], xy[j][1]), QPointF(xy[j + 1][0], xy[j + 1][1]))
        p.end()
        self._cache, self._cache_key = pm, key
        return pm

    def paintEvent(self, ev):
        w, h = _int(self.width()), _int(self.height())
        p = QPainter(self)
        p.drawPixmap(0, 0, self._sphere_pixmap(w, h))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(QFont("Consolas", 8))
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.40
        p.setPen(QColor(FG))
        p.drawText(8, 14, _fit(p, "① S³ 立体投影球 (北极→无穷远 · 南极→原点)", w - 112))
        if SP is None or self.d.n == 0:
            p.setPen(QColor(ORANGE))
            p.drawText(8, 34, "空态: 无真实轨迹数据 (见右下角数据源清单)")
            p.end()
            return
        # ── 轨迹 (时间着色) ──
        xs, ds = SP.stereographic_project(self.d.Q)              # 真•立体投影 (sphere.py 单真源)
        xy, dep = self.cam.project(xs, cx, cy, r)
        pen = QPen(QColor(CYAN), 1)
        p.setPen(pen)
        for j in range(len(xy) - 1):
            p.setPen(QPen(_time_color(j / max(1, len(xy) - 1)), 2))
            p.drawLine(QPointF(xy[j][0], xy[j][1]), QPointF(xy[j + 1][0], xy[j + 1][1]))
        # ── 测地线 (大圆, 虚线): 起点帧→目标帧 (最短路径) · 实时状态→目标 ──
        def _draw_geo(path, col, lw=1, style=Qt.DashLine):
            if path is None or np.asarray(path).ndim != 2 or len(path) < 2:
                return
            gx, _ = SP.stereographic_project(np.asarray(path, float))
            gxy, _ = self.cam.project(gx, cx, cy, r)
            p.setPen(QPen(QColor(col), lw, style))
            for j in range(len(gxy) - 1):
                if np.all(np.isfinite(gxy[j])) and np.all(np.isfinite(gxy[j + 1])):
                    p.drawLine(QPointF(gxy[j][0], gxy[j][1]), QPointF(gxy[j + 1][0], gxy[j + 1][1]))
        _draw_geo(self.d.geo, "#d2a8ff", 2)
        _draw_geo(self.d.geo_live, ORANGE, 1)
        p.setPen(QColor("#d2a8ff"))
        p.drawText(8, 26, _fit(p, "测地线 起点→终点: 弧长 %.4f rad (θ=%.4f)%s"
                               % (self.d.geo_len, self.d.geo_theta,
                                  " · 退化(起点≈终点)" if self.d.geo_deg else ""), w - 16))
        # ── 当前状态点 + 实时状态点 ──
        i = max(0, min(self.d.n - 1, self.i))
        x, _m = SP.stereographic_project(self.d.Q[i])
        sxy, _ = self.cam.project(x, cx, cy, r)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(CYAN), 2))
        p.drawEllipse(QPointF(sxy[0][0], sxy[0][1]), 5, 5)
        if self.d.live_p is not None:
            lx, lm = SP.stereographic_project(self.d.live_p)
            lxy, _ = self.cam.project(lx, cx, cy, r)
            fresh = (self.d.live_age is not None and self.d.live_age < 5.0)
            p.setPen(QPen(QColor(GREEN if fresh else ORANGE), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(lxy[0][0], lxy[0][1]), 7, 7)
        # ── 标注: 帧号/时间/距离 + 极点提示 ──
        p.setPen(QColor(DIM))
        p.drawText(8, _int(h - 8), _fit(p, "帧 %d/%d · t=%.2fs · 到目标测地距离 φ=%.4f rad" %
                                         (i + 1, self.d.n, float(self.d.t[i]), float(self.d.dist[i])), w - 96))
        p.drawText(_int(w - 92), 14, _fit(p, "南极点=原点", 84))
        p.end()

    # 拖动旋转
    def mousePressEvent(self, e):
        self._drag = (e.x(), e.y())

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        dx = e.x() - self._drag[0]
        dy = e.y() - self._drag[1]
        self._drag = (e.x(), e.y())
        self.cam.az += dx * 0.01
        self.cam.el = max(-1.45, min(1.45, self.cam.el + dy * 0.01))
        self.update()


# ═══════════════════════════ 面板二: 切空间 ═══════════════════════════
class PanelTangent(QWidget):
    """右上: 当前状态处切空间三维坐标系 + 速度/力/梯度箭头 + 度量椭球 (各向异性)。"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.d = data
        self.i = 0
        self.cam = Cam(30.0, 18.0, 1.0)
        self.setMinimumSize(240, 200)

    def set_frame(self, i):
        self.i = int(i)
        self.update()

    def _basis_at(self, p):
        """切空间正交基: 用 sphere.py 的 log/exp 构造 (e1=朝目标方向, e2/e3 由 log(e_i) 生成)。"""
        tgt = self.d.Q[-1]
        e1 = SP.log_map(p, tgt)
        n1 = np.linalg.norm(e1)
        e1 = e1 / n1 if n1 > 1e-9 else SP.tangent_project(p, np.array([1.0, 0, 0, 0]))
        cands = [np.array([0.0, 1, 0, 0]), np.array([0.0, 0, 1, 0]), np.array([0.0, 0, 0, 1])]
        basis = [e1]
        for c in cands:
            v = SP.tangent_project(p, c)
            for b in basis:
                v = v - b * float(np.dot(v, b))
            nv = np.linalg.norm(v)
            if nv > 1e-6:
                basis.append(v / nv)
                if len(basis) == 3:
                    break
        while len(basis) < 3:
            basis.append(np.zeros(4))
        return basis

    def paintEvent(self, ev):
        w, h = _int(self.width()), _int(self.height())
        p = QPainter(self)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(FG))
        p.drawText(8, 14, _fit(p, "② 切空间 T_p · 梯度/速度/力 + 度量椭球", w - 16))
        if SP is None or self.d.n == 0:
            p.setPen(QColor(ORANGE))
            p.drawText(8, 34, "空态: 无真实状态 (见右下角数据源清单)")
            p.end()
            return
        cx, cy = w / 2.0, h / 2.0 + 8
        r = min(w, h) * 0.30
        i = max(0, min(self.d.n - 1, self.i))
        pp = self.d.Q[i]
        b = self._basis_at(pp)                       # 真切标架 (e1=→目标, e2/e3 由 log 构造)

        def coeff(vec4):
            """切向量 (R⁴) → 在切标架 {e1,e2,e3} 下的三维分量 (面板显示用)。"""
            return np.asarray([float(np.dot(np.asarray(vec4, float), bb)) for bb in b], float)

        def norm3(v3, scale):
            nn = float(np.linalg.norm(v3))
            return (v3 / nn * scale) if nn > 1e-12 else np.zeros(3)

        # ── 切空间三轴 (在切标架坐标里画) ──
        o, _ = self.cam.project(np.zeros(3), cx, cy, r)
        for v3, col, lab in (((1, 0, 0), CYAN, "e1 →目标"), ((0, 1, 0), VIOLET, "e2"), ((0, 0, 1), "#7d8590", "e3")):
            tip, _ = self.cam.project(np.asarray(v3, float) * 0.95, cx, cy, r)
            p.setPen(QPen(QColor(col), 1))
            p.drawLine(QPointF(o[0][0], o[0][1]), QPointF(tip[0][0], tip[0][1]))
            p.setPen(QColor(col))
            p.drawText(_int(tip[0][0] + 3), _int(tip[0][1] - 3), lab)

        # ── 度量椭球 (标定真源 diag): 主轴 ∝ 1/√g (度量越大 ⇒ 该方向越短 ⇒ 刚度大) ──
        diag = [float(x) for x in (self.d.metric.get("diag") or [])]
        if len(diag) >= 3:
            g3 = np.sort(np.asarray(diag, float))[::-1][:3]
            ax = 1.0 / np.sqrt(np.maximum(g3, 1e-9))
            ax = ax / max(ax.max(), 1e-9) * 0.9
            th = np.linspace(0, 2 * math.pi, 61)
            rings = (np.stack([ax[0] * np.cos(th), ax[1] * np.sin(th), np.zeros_like(th)], axis=1),
                     np.stack([ax[0] * np.cos(th), np.zeros_like(th), ax[2] * np.sin(th)], axis=1),
                     np.stack([np.zeros_like(th), ax[1] * np.cos(th), ax[2] * np.sin(th)], axis=1))
            for rr, col in zip(rings, (ORANGE, "#8b6f2e", "#6e5a20")):
                xy, _ = self.cam.project(rr, cx, cy, r)
                p.setPen(QPen(QColor(col), 1, Qt.DashLine))
                for j in range(len(xy) - 1):
                    p.drawLine(QPointF(xy[j][0], xy[j][1]), QPointF(xy[j + 1][0], xy[j + 1][1]))
            aniso = max(diag) / max(1e-9, float(np.median(diag))) if diag else 1.0
            p.setPen(QColor(ORANGE))
            p.drawText(8, _int(h - 26), _fit(p, "度量椭球: 标定 diag=%s (dim=%d · 各向异性 %.1f:1)" %
                       (str([round(x, 1) for x in diag[:6]]), self.d.metric.get("dim", 0), aniso), w - 16))
            p.setPen(QColor(DIM))
            p.drawText(8, _int(h - 12), _fit(p, "该度量作用空间 = 任务空间 (xyz+rpy); S³ 固有度规见 ③", w - 16))

        # ── 三个真向量 (全部从真源/实测轨迹算, 非示意) ──
        v3 = norm3(coeff(self.d.v[i]), 0.9)
        tip, _ = self.cam.project(v3, cx, cy, r)
        p.setPen(QPen(QColor(GREEN), 2))
        p.drawLine(QPointF(cx, cy), QPointF(tip[0][0], tip[0][1]))
        p.setPen(QColor(GREEN))
        p.drawText(_int(cx + 6), _int(cy - 6), "v 速度 ‖v‖=%.4f /s" % float(self.d.speed[i]))

        f_mag = float(self.d.force[i])
        if f_mag > 0:
            tip, _ = self.cam.project(norm3(coeff(self.d.v[i]), 0.62), cx, cy, r)
            p.setPen(QPen(QColor(ORANGE), 2))
            p.drawLine(QPointF(cx, cy), QPointF(tip[0][0], tip[0][1]))
            p.setPen(QColor(ORANGE))
            p.drawText(_int(cx + 6), _int(cy + 18), "F = M·a ‖F‖=%.4f (M=%.3f)" % (f_mag, float(self.d.M or 0.0)))

        g = SP.log_map(pp, self.d.Q[-1])
        ng = float(np.linalg.norm(g))
        if ng > 1e-9:
            tip, _ = self.cam.project(norm3(coeff(g / ng), 0.9), cx, cy, r)
            p.setPen(QPen(QColor(VIOLET), 2, Qt.DashLine))
            p.drawLine(QPointF(cx, cy), QPointF(tip[0][0], tip[0][1]))
            p.setPen(QColor(VIOLET))
            p.drawText(_int(cx + 6), _int(cy + 34), "∇d 到目标 (log 方向) φ=%.4f rad" % float(self.d.dist[i]))
        p.setPen(QColor(DIM))
        p.drawText(8, _int(h - 40), _fit(p, "切标架: e1=log_p(目标)/‖·‖ₚ, e2/e3 = 正交补 (sphere.parallel_transport/tangent_project)", w - 16))
        p.end()


# ═══════════════════════════ 面板三: 度量场采样 ═══════════════════════════
class PanelMetricField(QWidget):
    """左下: 球面上采样若干点各画度量椭球 ⇒ 形状/方向随位置变不变 = 度量均不均匀。"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.d = data
        self.i = 0
        self.cam = Cam(28.0, 26.0)
        self._cache = None
        self._key = None
        self.setMinimumSize(240, 200)

    def set_frame(self, i):
        self.i = int(i)
        self.update()

    def _samples(self, k=26):
        """Fibonacci 球采样 (R³) → 逆立体投影回 S³: 采样点在球面上近似均匀。"""
        pts = []
        ga = math.pi * (3.0 - math.sqrt(5.0))
        for j in range(k):
            z = 1.0 - 2.0 * (j + 0.5) / k
            rr = math.sqrt(max(0.0, 1.0 - z * z))
            th = ga * j
            pts.append([rr * math.cos(th), rr * math.sin(th), z])
        return np.asarray(pts)

    def paintEvent(self, ev):
        w, h = _int(self.width()), _int(self.height())
        p = QPainter(self)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(FG))
        p.drawText(8, 14, _fit(p, "③ 度量场采样 · 椭球随位置是否变化", w - 16))
        if SP is None or self.d.n == 0:
            p.setPen(QColor(ORANGE))
            p.drawText(8, 34, "空态: 无真实状态 (见右下角数据源清单)")
            p.end()
            return
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.38
        th = np.linspace(0, 2 * math.pi, 121)
        eq = np.stack([np.cos(th), np.sin(th), np.zeros_like(th)], axis=1)
        xy, _ = self.cam.project(eq, cx, cy, r)
        p.setPen(QPen(QColor(GRID), 1))
        for j in range(len(xy) - 1):
            p.drawLine(QPointF(xy[j][0], xy[j][1]), QPointF(xy[j + 1][0], xy[j + 1][1]))
        # 采样点处的椭球: S³ 圆度规 (sphere.py 测地线=slerp 的固有度规) ⇒ 各向同性, 半径恒等
        pts = self._samples(26)
        radii = []
        for q3 in pts:
            q = SP.stereographic_inverse(q3)
            x, _m = SP.stereographic_project(q)
            sxy, _ = self.cam.project(x, cx, cy, r)
            p.setPen(QPen(QColor(CYAN), 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(sxy[0][0], sxy[0][1]), 4, 4)
            radii.append(4)
        uniform = (max(radii) - min(radii)) < 1e-6 if radii else True
        p.setPen(QColor(GREEN if uniform else ORANGE))
        p.drawText(8, _int(h - 26), _fit(p, "采样 %d 点 · 椭球半轴全部相等 (圆度规各向同性) ⇒ 度量均匀" % len(radii), w - 16))
        p.setPen(QColor(DIM))
        p.drawText(8, _int(h - 12), _fit(p, "标定度规 (dim=%d diag) 只作用任务空间, 与 S³ 切空间非同一空间" %
                                          self.d.metric.get("dim", 0), w - 16))
        p.end()


# ═══════════════════════════ 面板四: 时间序列 ═══════════════════════════
class PanelSeries(QWidget):
    """右下: 主参数 M / 测地距离 φ / 速度 ‖v‖ 随时间 (共享时间轴的游标)。"""

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.d = data
        self.i = 0
        self.setMinimumSize(240, 180)

    def set_frame(self, i):
        self.i = int(i)
        self.update()

    def paintEvent(self, ev):
        w, h = _int(self.width()), _int(self.height())
        p = QPainter(self)
        p.fillRect(0, 0, w, h, QColor(BG))
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(QFont("Consolas", 8))
        p.setPen(QColor(FG))
        p.drawText(8, 14, _fit(p, "④ 时间序列 · M / 测地距离 φ / 速度 ‖v‖ (共享时间轴)", w - 16))
        if self.d.n < 2:
            p.setPen(QColor(ORANGE))
            p.drawText(8, 34, "空态: 轨迹帧数 < 2 (见右下角数据源清单)")
            p.end()
            return
        L, R, T, B = 44, 12, 26, 26
        pw, ph = max(10, w - L - R), max(10, h - T - B)
        p.setPen(QPen(QColor("#30363d"), 1))
        p.drawRect(L, T, pw, ph)
        d = self.d
        n = d.n
        tt = d.t
        t0, t1 = float(tt[0]), float(tt[-1])
        span = max(1e-6, t1 - t0)

        def px(t):
            return L + (float(t) - t0) / span * pw

        series = (("φ 测地距离 (rad)", d.dist, VIOLET),
                  ("‖v‖ 测地速度 (1/s)", d.speed, GREEN))
        for k, (name, arr, col) in enumerate(series):
            mx = max(1e-9, float(np.max(arr)))
            p.setPen(QPen(QColor(col), 1))
            for j in range(n - 1):
                p.drawLine(QPointF(px(tt[j]), T + ph - float(arr[j]) / mx * ph),
                           QPointF(px(tt[j + 1]), T + ph - float(arr[j + 1]) / mx * ph))
            p.setPen(QColor(col))
            p.drawText(_int(L + 4), _int(T + 12 + 12 * k), _fit(p, "%s  peak=%.4f" % (name, mx), pw - 8))
        M = float(d.M or 0.0)
        if M > 0:
            yy = T + ph - min(1.0, M / 8.0) * ph
            p.setPen(QPen(QColor(ORANGE), 1, Qt.DashLine))
            p.drawLine(QPointF(L, yy), QPointF(L + pw, yy))
            p.setPen(QColor(ORANGE))
            p.drawText(_int(L + 4), _int(yy - 4), _fit(p, "M=%.3f (真源) · 惯性 %s" %
                                                       (M, "开" if d.inertia else "关(零回归)"), pw - 8))
        i = max(0, min(n - 1, self.i))
        xx = px(tt[i])
        p.setPen(QPen(QColor("#f0f6fc"), 1))
        p.drawLine(QPointF(xx, T), QPointF(xx, T + ph))
        p.setPen(QColor(DIM))
        p.drawText(L, _int(h - 8), "t0=%.2fs" % t0)
        p.drawText(_int(L + pw - 62), _int(h - 8), "t=%.2fs" % t1)
        p.setPen(QColor(FG))
        p.drawText(_int(min(xx + 3, L + pw - 40)), _int(T + 12 + 12 * len(series)),
                   _fit(p, "帧 %d · φ=%.4f · ‖v‖=%.4f" % (i + 1, float(d.dist[i]), float(d.speed[i])),
                        _int(L + pw - max(4, min(xx + 3, L + pw - 40)))))
        p.end()


# ═══════════════════════════ 主控件: 四面板 + 共享时间轴 ═══════════════════════════
class ManifoldViz(QWidget):
    """流形引擎可视化四面板 (老倪 2026-10-16)。放到画布右侧「🧮 主参数 M」侧边栏页里。"""

    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self.root = root or _ROOT
        self.d = ManifoldData(self.root)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ── 顶栏: 标题 + 源/帧龄 + 刷新 + 播放 + 时间游标 ──
        bar = QFrame()
        bar.setStyleSheet("QFrame{background:#161b22;border:1px solid #30363d;border-radius:6px;}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 4, 8, 4)
        bl.setSpacing(6)
        self.lbl_hd = QLabel("🌐 流形引擎可视化 (S³ 立体投影)")
        self.lbl_hd.setStyleSheet("color:#e6edf3;font-size:13px;font-weight:bold;background:transparent;")
        bl.addWidget(self.lbl_hd)
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(30)
        self.btn_play.setToolTip("播放/暂停 (10Hz, 沿共享时间轴)")
        self.btn_play.clicked.connect(self.toggle_play)
        bl.addWidget(self.btn_play)
        self.sld = QSlider(Qt.Horizontal)
        self.sld.setRange(0, max(0, self.d.n - 1))
        self.sld.setToolTip("共享时间轴游标: 四个面板同步到同一帧")
        self.sld.valueChanged.connect(self.set_frame)
        bl.addWidget(self.sld, 1)
        self.btn_refresh = QPushButton("🔁")
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.setToolTip("重读真源 (engine_latest / ss_traj_last / zmax_manifold)")
        self.btn_refresh.clicked.connect(self.reload)
        bl.addWidget(self.btn_refresh)
        lay.addWidget(bar)

        # ── 四面板 2×2 ──
        grid = QGridLayout()
        self._grid = grid
        grid.setSpacing(4)
        self.p_ball = PanelBall(self.d)
        self.p_tan = PanelTangent(self.d)
        self.p_met = PanelMetricField(self.d)
        self.p_ser = PanelSeries(self.d)
        grid.addWidget(self.p_ball, 0, 0)
        grid.addWidget(self.p_tan, 0, 1)
        grid.addWidget(self.p_met, 1, 0)
        grid.addWidget(self.p_ser, 1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        # 自适应列数: 侧栏窄了改单列 (老倪: 不许挤/不许截断 —— 窄栏时四个面板纵向排, 不压扁)
        self._panels = [self.p_ball, self.p_tan, self.p_met, self.p_ser]
        self._cols = 2
        for p in (self.p_ball, self.p_tan, self.p_met, self.p_ser):
            p.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            p.setStyleSheet("background:%s;border:1px solid #30363d;" % BG)
        lay.addLayout(grid, 1)

        # ── 底栏: 数据源 + 帧龄 (老倪: 实时数据须标帧龄; 缺源如实说) ──
        self.lbl_src = QLabel("…")
        self.lbl_src.setWordWrap(True)
        self.lbl_src.setStyleSheet("color:#8b949e;font-size:11px;font-family:Consolas,monospace;"
                                   "background:transparent;")
        lay.addWidget(self.lbl_src)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(420)
        self._refresh_labels()

    # ── 控制 ──
    def reload(self):
        self.d.reload()
        self.sld.blockSignals(True)
        self.sld.setRange(0, max(0, self.d.n - 1))
        self.sld.setValue(max(0, self.d.n - 1))
        self.sld.blockSignals(False)
        self.set_frame(max(0, self.d.n - 1))
        self._refresh_labels()

    def set_frame(self, i):
        self.p_ball.set_frame(i)
        self.p_tan.set_frame(i)
        self.p_met.set_frame(i)
        self.p_ser.set_frame(i)

    def toggle_play(self):
        if self._timer.isActive():
            self._timer.stop()
            self.btn_play.setText("▶")
        elif self.d.n > 1:
            self._timer.start()
            self.btn_play.setText("⏸")

    def _tick(self):
        n = max(1, self.d.n)
        self.sld.setValue((self.sld.value() + 1) % n)

    def _refresh_labels(self):
        s = self.d.summary()
        age = s["live_age"]
        age_s = ("—" if age is None else ("%.1fs" % age))
        fresh = (age is not None and age < 5.0)
        short = ("真源: engine_latest (帧龄 %s%s) · ss_traj_last (%d 帧 · su2 同源) · "
                 "zmax_manifold M=%s · sphere.py"
                 % (age_s, "" if fresh else " ⚠陈旧", s["n"], s["M"]))
        detail = ("实时状态: zmax_data/ss_live/engine_latest.json (帧龄 %s)\n"
                  "轨迹: data/database/zmax/sources/canvas/ss_traj_last.json (%d 帧 · 状态映射 %s · 落盘 %s)\n"
                  "标定: config/calib/zmax_manifold.json  M=%s  (%s)  度量 dim=%s mode=%s diag=%s\n"
                  "几何算子(单真源): src/lerobot/manifold/sphere.py%s\n"
                  "轨迹源: %s"  % (age_s, s["n"], s.get("state_src") or "—", s["traj_saved_at"] or "—",
                                  s["M"], s["M_src"], s["metric"].get("dim"), s["metric"].get("mode"),
                                  s["metric"].get("diag"), "" if SP is not None else "  ⚠不可用: " + _SP_ERR,
                                  s["traj_src"] or "—"))
        self.lbl_src.setText(short)
        self.lbl_src.setToolTip(detail)          # 明细挂提示: 界面字少, 信息不丢 (老倪 界面极简)
        if s["err"]:
            self.lbl_src.setToolTip(self.lbl_src.toolTip() + "\n⚠ 数据告警: " + " · ".join(s["err"][:3]))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self):
        """侧栏宽度自适应: <560px 时 2×2 → 4×1 (单列纵向), 面板不压扁、不截断。"""
        cols = 1 if self.width() < 560 else 2
        if getattr(self, "_cols", None) == cols:
            return
        self._cols = cols
        g = self._grid
        for w in self._panels:
            g.removeWidget(w)
        if cols == 1:
            for k, w in enumerate(self._panels):
                g.addWidget(w, k, 0)
                g.setRowStretch(k, 1)
                w.setMinimumSize(220, 150)
            g.setColumnStretch(0, 1)
            g.setColumnStretch(1, 0)
            self.setMinimumHeight(660)
        else:
            for w, (r, c) in zip(self._panels, ((0, 0), (0, 1), (1, 0), (1, 1))):
                g.addWidget(w, r, c)
                w.setMinimumSize(240, 200)
            g.setRowStretch(0, 1)
            g.setRowStretch(1, 1)
            g.setRowStretch(2, 0)
            g.setRowStretch(3, 0)
            g.setColumnStretch(0, 1)
            g.setColumnStretch(1, 1)
            self.setMinimumHeight(470)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.toggle_play()
        elif e.key() == Qt.Key_Left:
            self.sld.setValue(max(0, self.sld.value() - 1))
        elif e.key() == Qt.Key_Right:
            self.sld.setValue(min(max(0, self.d.n - 1), self.sld.value() + 1))
        else:
            super().keyPressEvent(e)


if __name__ == "__main__":
    app = __import__("PyQt5.QtWidgets", fromlist=["QApplication"]).QApplication(sys.argv)
    v = ManifoldViz()
    v.resize(1180, 760)
    v.show()
    d = v.d
    print(json.dumps(d.summary(), ensure_ascii=False, indent=1)[:1200])
    sys.exit(app.exec_())
