#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""updown_scene_view.py — 上下料场景 · 页内 3D 渲染可编辑视图 (老倪 2026-10-10)

老倪: 「在哪呢仿真场景？删掉 Sim&Real 的功能积木部分，我要上下料的可编辑窗口，3D 渲染的场景，类似 dreamview 的 3D 场景」

为什么**不用**再开一个 pyqtgraph GLViewWidget:
  技能 `qt-gl-rendering-pitfalls` 坑 1 实测 —— pyqtgraph 的 shader 句柄绑在**第一个** GL 上下文上,
  再新建 GLViewWidget = 新上下文 ⇒ 旧句柄失效 ⇒ 那个窗口所有 GL item 全报 glGetAttribLocation 画不出来。
  所以页内第二块 3D 用 **QPainter 正交投影自绘** (同技能推荐路线): 真 3D 投影 + 深度排序 + 面/边/标签,
  零 GL 依赖 ⇒ 不会把控制台弄崩, 也不影响画布那个真 GL 3D 视图。

数据源与写路径 (与场景功能区**同一份真源、同一条写路径**):
  读: data/scene/scenes/<SCENE_ID>/{objects3d.json, overlay_spec.json}   (在役 = data/scene/)
  写: 一律 `tools/scene_edit.py --scene <ID> ...` ⇒ 备份 + 原子写 + 回读 + 回滚 (在役场景不受影响)
  操作: 左键点选 / 拖动 = 在地面(XY)平移对象 / 双击 = 改数值 / 滚轮 = 缩放 / 右键拖 = 转视角
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QInputDialog, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

C_BG = "#0b0f14"
C_GRID = "#1b2b33"
C_AXIS_X, C_AXIS_Y, C_AXIS_Z = "#e05561", "#7ddc7d", "#5aa9ff"
C_OBJ = "#00d4aa"
C_OBJ_SEL = "#ffc857"
C_MARK = "#ff8a3d"
C_FENCE = "#8b6cf0"
C_TRAJ = "#4da3ff"
C_TXT = "#e6edf3"
C_DIM = "#7d8590"


# ─────────────────────────── 数据层 ───────────────────────────
def scene_options():
    """可选场景: (标签, 场景目录, scene_id or None=在役)。"""
    out = [("(在役) 现场场景", os.path.join(ROOT, "data", "scene"), None)]
    try:
        idx = json.load(open(os.path.join(ROOT, "data", "scene", "scenes", "index.json"), encoding="utf-8"))
        for sid, v in (idx.get("named_scenes") or {}).items():
            out.append(("%s %s" % (sid, str(v.get("name") or "")[:26]),
                        os.path.join(ROOT, v.get("dir") or ("data/scene/scenes/" + sid)), sid))
    except Exception:                                                          # noqa: BLE001
        pass
    return out


def _j(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return d


def load_scene(scene_dir):
    """读一次场景真源 (渲染用; 不用起子进程)。"""
    o = _j(os.path.join(scene_dir, "objects3d.json"), {}) or {}
    v = _j(os.path.join(scene_dir, "overlay_spec.json"), {}) or {}
    return {"objects": [x for x in (o.get("objects") or []) if isinstance(x, dict)],
            "markers": [x for x in (v.get("markers") or []) if isinstance(x, dict)],
            "fences": [x for x in (v.get("fences") or []) if isinstance(x, dict)],
            "trajectories": [x for x in (v.get("trajectories") or []) if isinstance(x, dict)],
            "deleted": (v.get("deleted") or {}), "scene": v.get("scene") or "",
            "meta": o.get("meta") or {}}


def _se(scene_id, *args):
    """调 scene_edit.py (唯一写路径, 带备份/回读)。返回 (ok, dict)。"""
    argv = [sys.executable, os.path.join(ROOT, "tools", "scene_edit.py")]
    if scene_id:
        argv += ["--scene", scene_id]
    argv += list(args) + ["--json"]
    r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
    txt = r.stdout or ""
    i = txt.find("{")
    try:
        d = json.loads(txt[i:]) if i >= 0 else {}
    except Exception:                                                          # noqa: BLE001
        d = {}
    return (r.returncode == 0 and bool(d.get("ok", True))), d


# ─────────────────────────── 3D 视图 ───────────────────────────
class SceneView3D(QWidget):
    """正交投影 3D 场景视图 (可点选/拖动/双击改数值)。"""

    def __init__(self, scene_dir, scene_id=None, status_cb=None, parent=None):
        super().__init__(parent)
        self.scene_dir, self.scene_id = scene_dir, scene_id
        self.status_cb = status_cb or (lambda s: None)
        self.az, self.el, self.scale = 35.0, 32.0, 620.0     # 视角/每米像素
        self.pan = [0.0, 0.0]                                 # 屏幕平移(像素)
        self.data = load_scene(scene_dir)
        self.sel = None                                       # 选中的对象 index
        self._drag = None
        self._dragging_obj = False
        self._press = None
        self._preview = None
        self.center = self._centroid()
        self.setMinimumHeight(430)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ── 场景/数据 ──
    def set_scene(self, scene_dir, scene_id=None):
        self.scene_dir, self.scene_id = scene_dir, scene_id
        self.reload()

    def reload(self, keep_sel=True):
        """重读真源。keep_sel: 按名字找回原选中项 (写一次就丢选中 = 连续拖动会失效)。"""
        _keep = None
        if keep_sel and self.sel is not None and 0 <= self.sel < len(self.data.get("objects") or []):
            _keep = self.data["objects"][self.sel].get("name")
        self.data = load_scene(self.scene_dir)
        self.center = self._centroid()
        self.sel = None
        if _keep:
            for i, o in enumerate(self.data["objects"]):
                if o.get("name") == _keep:
                    self.sel = i
                    break
        self.update()

    def _centroid(self):
        pts = [[float(c) for c in o["center"]] for o in self.data["objects"] if isinstance(o.get("center"), list)]
        pts += [[float(c) for c in m["pos"]] for m in self.data["markers"] if isinstance(m.get("pos"), list)]
        if not pts:
            return [0.6, 0.35, 0.15]
        return [sum(p[i] for p in pts) / len(pts) for i in range(3)]

    # ── 投影 ──
    def _basis(self):
        a, e = math.radians(self.az), math.radians(self.el)
        eye = [math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)]
        fwd = [-eye[0], -eye[1], -eye[2]]
        up = [0.0, 0.0, 1.0]
        right = [fwd[1] * up[2] - fwd[2] * up[1], fwd[2] * up[0] - fwd[0] * up[2], fwd[0] * up[1] - fwd[1] * up[0]]
        n = math.sqrt(sum(x * x for x in right)) or 1e-9
        right = [x / n for x in right]
        upv = [right[1] * fwd[2] - right[2] * fwd[1], right[2] * fwd[0] - right[0] * fwd[2],
               right[0] * fwd[1] - right[1] * fwd[0]]
        return fwd, right, upv

    def _proj(self, p, basis=None):
        fwd, right, upv = basis or self._basis()
        d = [p[i] - (self.center[i] if i < 3 else 0.0) for i in range(3)]
        s = self.scale
        x = self.width() / 2 + sum(d[i] * right[i] for i in range(3)) * s + self.pan[0]
        y = self.height() / 2 - sum(d[i] * upv[i] for i in range(3)) * s + self.pan[1]
        return QPointF(x, y), sum(d[i] * fwd[i] for i in range(3))

    def _obj_box(self, o):
        c = [float(x) for x in o["center"]]
        sz = [float(x) / 1000.0 for x in (o.get("size") or [50.0, 50.0, 50.0])]
        return c, sz

    def _hidden(self, name):
        d = self.data.get("deleted") or {}
        return any(name in (lst or []) for k, lst in d.items() if k in ("arm", "local", "objects"))

    # ── 绘制 ──
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(C_BG))
        basis = self._basis()
        self._draw_grid(p, basis)
        self._draw_fences(p, basis)
        self._draw_trajectories(p, basis)
        self._draw_objects(p, basis)
        self._draw_markers(p, basis)
        self._draw_hud(p)
        p.end()

    def _line3(self, p, basis, a, b, color, width=1, dash=None):
        pa, _ = self._proj(a, basis)
        pb, _ = self._proj(b, basis)
        pen = QPen(QColor(color), width)
        if dash:
            pen.setStyle(dash)
        p.setPen(pen)
        p.drawLine(pa, pb)

    def _draw_grid(self, p, basis):
        z = 0.0
        n, step = 8, 0.1
        base = [round(self.center[0] / step) * step, round(self.center[1] / step) * step]
        for i in range(-n, n + 1):
            x = base[0] + i * step
            self._line3(p, basis, [x, base[1] - n * step, z], [x, base[1] + n * step, z], C_GRID, 1)
            y = base[1] + i * step
            self._line3(p, basis, [base[0] - n * step, y, z], [base[0] + n * step, y, z], C_GRID, 1)
        o = [base[0], base[1], z]
        self._line3(p, basis, o, [o[0] + 0.15, o[1], z], C_AXIS_X, 2)
        self._line3(p, basis, o, [o[0], o[1] + 0.15, z], C_AXIS_Y, 2)
        self._line3(p, basis, o, [o[0], o[1], z + 0.15], C_AXIS_Z, 2)

    def _box_edges(self, c, sz):
        hx, hy, hz = sz[0] / 2, sz[1] / 2, sz[2] / 2
        v = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for szs in (-1, 1):
                    v.append([c[0] + sx * hx, c[1] + sy * hy, c[2] + szs * hz])
        e = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
        return v, e

    def _draw_objects(self, p, basis):
        items = []
        for i, o in enumerate(self.data["objects"]):
            c, sz = self._obj_box(o)
            _, depth = self._proj(c, basis)
            items.append((depth, i, o, c, sz))
        for depth, i, o, c, sz in sorted(items, reverse=False):      # 远→近
            hid = self._hidden(str(o.get("name")))
            col = C_OBJ_SEL if i == self.sel else C_OBJ
            v, e = self._box_edges(c, sz)
            if not hid:
                bottom = [v[0], v[1], v[3], v[2]]
                poly = QPolygonF([self._proj(q, basis)[0] for q in bottom])
                p.setBrush(QBrush(QColor(col + "33")))
                p.setPen(Qt.NoPen)
                p.drawPolygon(poly)
            for a, b in e:
                pa, _ = self._proj(v[a], basis)
                pb, _ = self._proj(v[b], basis)
                w = 2 if i == self.sel else 1
                p.setPen(QPen(QColor(col if not hid else C_DIM), w,
                              Qt.DashLine if hid else Qt.SolidLine))
                p.drawLine(pa, pb)
            pc, _ = self._proj([c[0], c[1], c[2] + sz[2] / 2], basis)
            p.setPen(QPen(QColor(col if not hid else C_DIM)))
            p.setFont(QFont("Arial", 9, QFont.Bold if i == self.sel else QFont.Normal))
            nm = str(o.get("name"))[:22]
            p.drawText(QRectF(pc.x() - 110, pc.y() - 24, 220, 16), Qt.AlignCenter, nm)
            if i == self.sel:
                p.setFont(QFont("Arial", 8))
                p.drawText(QRectF(pc.x() - 120, pc.y() - 10, 240, 14), Qt.AlignCenter,
                           "[%.3f, %.3f, %.3f]  %smm" % (c[0], c[1], c[2], "/".join("%.0f" % x for x in (o.get("size") or []))))

    def _draw_markers(self, p, basis):
        for m in self.data["markers"]:
            if not isinstance(m.get("pos"), list):
                continue
            pos = [float(x) for x in m["pos"]]
            hid = self._hidden(str(m.get("name")))
            col = C_DIM if hid else C_MARK
            self._line3(p, basis, [pos[0], pos[1], 0.0], pos, col, 1, Qt.DashLine)
            q, _ = self._proj(pos, basis)
            r = max(2.0, (m.get("radius_m") or 0.03) * self.scale / 6.0)
            p.setBrush(QBrush(QColor(col)))
            p.setPen(QPen(QColor(col), 1))
            p.drawEllipse(q, r, r)
            p.setPen(QPen(QColor(col)))
            p.setFont(QFont("Arial", 8))
            p.drawText(QRectF(q.x() - 70, q.y() + 4, 140, 13), Qt.AlignCenter, str(m.get("name"))[:20])

    def _draw_fences(self, p, basis):
        for f in self.data["fences"]:
            c = f.get("center") or f.get("pos")
            sz = f.get("size_m")
            if not (isinstance(c, list) and len(c) == 3):
                continue
            c = [float(x) for x in c]
            if not (isinstance(sz, list) and len(sz) == 3):
                sz = [0.3, 0.3, 0.3]
            v, e = self._box_edges(c, [float(x) for x in sz])
            for a, b in e:
                self._line3(p, basis, v[a], v[b], C_FENCE, 1, Qt.DashLine)
            q, _ = self._proj([c[0], c[1], c[2] + float(sz[2]) / 2], basis)
            p.setPen(QPen(QColor(C_FENCE)))
            p.setFont(QFont("Arial", 8))
            p.drawText(QRectF(q.x() - 80, q.y() - 14, 160, 13), Qt.AlignCenter, str(f.get("name"))[:22])

    def _draw_trajectories(self, p, basis):
        for t in self.data["trajectories"]:
            wps = [w for w in (t.get("waypoints") or []) if isinstance(w, list) and len(w) == 3]
            if len(wps) < 2:
                continue
            for i in range(len(wps) - 1):
                self._line3(p, basis, [float(x) for x in wps[i]], [float(x) for x in wps[i + 1]], C_TRAJ, 2)
            for w in wps:
                q, _ = self._proj([float(x) for x in w], basis)
                p.setBrush(QBrush(QColor(C_TRAJ)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(q, 3, 3)
            q, _ = self._proj([float(x) for x in wps[0]], basis)
            p.setPen(QPen(QColor(C_TRAJ)))
            p.setFont(QFont("Arial", 8))
            p.drawText(QRectF(q.x() - 80, q.y() - 16, 160, 13), Qt.AlignCenter, str(t.get("name"))[:22])

    def _draw_hud(self, p):
        m = self.data.get("meta") or {}
        lines = ["🧭 %s" % (m.get("name") or self.data.get("scene") or "场景")[:46],
                 "对象 %d · 标记 %d · 围栏 %d · 轨迹 %d   (az %.0f° el %.0f° ×%.0f)"
                 % (len(self.data["objects"]), len(self.data["markers"]), len(self.data["fences"]),
                    len(self.data["trajectories"]), self.az, self.el, self.scale / 620.0),
                 "左键点选/拖动平移 · 双击改数值 · 滚轮缩放 · 右键拖转视角"]
        p.setFont(QFont("Arial", 9))
        y = 8
        for i, s in enumerate(lines):
            p.setPen(QPen(QColor(C_TXT if i == 0 else C_DIM)))
            p.drawText(10, y + 12, s)
            y += 15

    # ── 交互 ──
    def _hit(self, pos):
        basis = self._basis()
        best, bd = None, 14.0
        for i, o in enumerate(self.data["objects"]):
            c, sz = self._obj_box(o)
            for q in ([c, [c[0], c[1], c[2] + sz[2] / 2]] if True else []):
                pq, _ = self._proj(q, basis)
                d = math.hypot(pq.x() - pos.x(), pq.y() - pos.y())
                if d < bd:
                    best, bd = i, d
        return best

    def mousePressEvent(self, ev):
        self._press = ev.pos()
        if ev.button() == Qt.LeftButton:
            i = self._hit(ev.pos())
            self.sel = i
            self._dragging_obj = i is not None
            self.update()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not (ev.buttons() & Qt.LeftButton) or self._drag is None:
            if ev.buttons() & Qt.LeftButton and self._press is not None and not self._dragging_obj:
                d = ev.pos() - self._press
                self.pan[0] += d.x()
                self.pan[1] += d.y()
                self._press = ev.pos()
                self.update()
            elif ev.buttons() & Qt.RightButton and self._press is not None:
                d = ev.pos() - self._press
                self.az = (self.az + d.x() * 0.5) % 360
                self.el = max(-80.0, min(85.0, self.el + d.y() * 0.4))
                self._press = ev.pos()
                self.update()
            return
        # 拖动对象: 屏幕位移 → 地面(XY)位移
        fwd, right, upv = self._basis()
        dx, dy = ev.pos().x() - self._drag[0], ev.pos().y() - self._drag[1]
        det = right[0] * upv[1] - right[1] * upv[0]
        if abs(det) > 1e-6:
            s = self.scale
            bx, by = dx / s, -dy / s
            wx = (bx * upv[1] - by * right[1]) / det
            wy = (right[0] * by - upv[0] * bx) / det
            o = self.data["objects"][self.sel]
            c = [float(x) for x in o["center"]]
            self._preview = [c[0] + wx, c[1] + wy, c[2]]
            self.update()
        self._drag = (ev.pos().x(), ev.pos().y())
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if self._dragging_obj and getattr(self, "_preview", None) and self.sel is not None and self.scene_id:
            o = self.data["objects"][self.sel]
            newc = [round(v, 5) for v in self._preview]
            self._preview = None
            if newc != [round(float(x), 5) for x in o["center"]]:
                self._write({"center": newc}, "拖动平移 %s" % o.get("name"))
        self._preview = None
        self._drag = None
        self._dragging_obj = False
        self._press = None
        ev.accept()

    def wheelEvent(self, ev):
        f = 1.1 if ev.angleDelta().y() > 0 else 1 / 1.1
        self.scale = max(120.0, min(4000.0, self.scale * f))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        i = self._hit(ev.pos())
        if i is None:
            return
        self._edit_dialog(i)

    def _write(self, patch, what, kind="objects", ent_id=None):
        """经 scene_edit.py 真写 (备份+回读)。返回是否成功。"""
        if not self.scene_id:
            self.status_cb("⛔ 在役场景为只读预览: 要编辑请在下拉里选命名场景 (如 SCN-07-UP)")
            self.reload()
            return False
        o = self.data["objects"][self.sel] if (kind == "objects" and self.sel is not None) else {}
        _id = ent_id or o.get("name")
        ok, d = _se(self.scene_id, "update", "--kind", kind, "--id", str(_id), "--data", json.dumps(patch, ensure_ascii=False))
        if ok and (d.get("readback") or d.get("readback_ok")):
            self.status_cb("✅ %s · %s · 回读一致 · 备份 %s" % (what, str(_id)[:24], os.path.basename(str(d.get("backup") or "—"))))
        else:
            self.status_cb("⛔ %s 失败: %s" % (what, d.get("msg") or "见 scene_edit 输出"))
        self.reload()
        return ok

    def _edit_dialog(self, i):
        o = self.data["objects"][i]
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑对象 · %s" % str(o.get("name"))[:30])
        f = QFormLayout(dlg)
        spins = {}
        for k, vec, idx in (("X (m)", "center", 0), ("Y (m)", "center", 1), ("Z (m)", "center", 2),
                            ("长 (mm)", "size", 0), ("宽 (mm)", "size", 1), ("高 (mm)", "size", 2)):
            sp = QDoubleSpinBox()
            sp.setDecimals(3 if vec == "center" else 0)
            sp.setRange(-3.0, 3.0) if vec == "center" else sp.setRange(1.0, 2000.0)
            sp.setSingleStep(0.005 if vec == "center" else 5.0)
            sp.setValue(float((o.get(vec) or [0, 0, 0])[idx]))
            spins[(vec, idx)] = sp
            f.addRow(k, sp)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec_() != QDialog.Accepted:
            return
        patch = {"center": [round(spins[("center", i2)].value(), 5) for i2 in range(3)],
                 "size": [round(spins[("size", i2)].value(), 1) for i2 in range(3)]}
        self._write(patch, "改数值 %s" % o.get("name"))

    # ── 视角 ──
    def view(self, az, el, scale=None):
        self.az, self.el = az, el
        if scale:
            self.scale = scale
        self.pan = [0.0, 0.0]
        self.update()


# ─────────────────────────── 页面卡片 ───────────────────────────
def build_card(parent=None):
    """Sim&Real 页内卡片: 上下料场景 3D 可编辑视图 (+ 真 GL 3D 视图入口)。"""
    card = QGroupBox("🧭 场景 3D 视图 · 上下料 (可编辑)")
    card.setStyleSheet("QGroupBox{color:#00d4aa; font-weight:bold; background:#161b22;"
                       " border:1px solid #30363d; border-radius:8px; margin-top:8px;} "
                       "QGroupBox::title{subcontrol-origin:margin; left:12px; padding:0 4px;}")
    v = QVBoxLayout(card)
    v.setContentsMargins(10, 14, 10, 10)
    v.setSpacing(6)

    opts = scene_options()
    top = QHBoxLayout()
    cmb = QComboBox()
    for label, d, sid in opts:
        cmb.addItem(label, (d, sid))
    cmb.setStyleSheet("QComboBox{background:#0f1318; color:#e6edf3; border:1px solid #30363d;"
                      " border-radius:4px; padding:4px; font-size:12px;} QComboBox QAbstractItemView{background:#0f1318; color:#e6edf3;}")
    top.addWidget(QLabel("场景:"))
    top.addWidget(cmb, 1)
    st = QLabel("—")
    st.setWordWrap(True)
    st.setStyleSheet("color:#c9d1d9; font-size:11px; background:#0d1117; border:1px solid #30363d;"
                     " border-radius:4px; padding:4px;")
    card.status_label = st

    def _b(txt, tip, fn, col="#4da3ff"):
        b = QPushButton(txt)
        b.setToolTip(tip)
        b.setStyleSheet("QPushButton{background:#1f2733; color:%s; border:1px solid #2a3441; border-radius:4px;"
                        " padding:5px 8px; font-size:12px;} QPushButton:hover{border-color:%s;}" % (col, col))
        b.clicked.connect(fn)
        return b

    d0, sid0 = opts[1][1:] if len(opts) > 1 else (opts[0][1], opts[0][2])
    view = SceneView3D(d0, sid0, status_cb=lambda s: st.setText(s))
    card.view = view

    def _switch():
        d, sid = cmb.currentData()
        view.set_scene(d, sid)
        st.setText("已切到 %s · 对象 %d / 标记 %d / 围栏 %d / 轨迹 %d   (写操作只落该场景目录)"
                   % (cmb.currentText(), len(view.data["objects"]), len(view.data["markers"]),
                      len(view.data["fences"]), len(view.data["trajectories"])))

    cmb.currentIndexChanged.connect(lambda _i: _switch())
    top.addWidget(_b("🔄 刷新", "重读场景真源并重绘", lambda: (view.reload(), _switch()), "#9aa7b4"))
    top.addWidget(_b("⌂ 复位视角", "等轴视角复位", lambda: view.view(35, 32, 620.0), "#9aa7b4"))
    top.addWidget(_b("⬇ 俯视", "俯视图 (看工位布局)", lambda: view.view(0, 89, 620.0), "#9aa7b4"))
    top.addWidget(_b("➖", "缩小", lambda: (setattr(view, "scale", max(120.0, view.scale / 1.25)), view.update()), "#9aa7b4"))
    top.addWidget(_b("➕", "放大", lambda: (setattr(view, "scale", min(4000.0, view.scale * 1.25)), view.update()), "#9aa7b4"))
    v.addLayout(top)

    row2 = QHBoxLayout()
    row2.addWidget(_b("👁 显隐选中", "隐藏/显示选中对象 (deleted 黑名单)",
                      lambda: _toggle(view, st), "#ffc857"))
    row2.addWidget(_b("✏️ 编辑选中", "改选中对象的中心/尺寸 (写 scene_edit)", lambda: view._edit_dialog(view.sel) if view.sel is not None else st.setText("先点选一个对象"), "#4da3ff"))
    row2.addWidget(_b("➕ 新增对象", "在场景里新增一个对象", lambda: _add(view, st), "#00d4aa"))
    row2.addWidget(_b("🗑 删除选中", "从场景删除选中对象 (可从此面板恢复不了, 备份里有)",
                      lambda: _del(view, st), "#e05561"))
    row2.addStretch(1)
    if parent is not None:
        def _open_gl():
            try:
                m = getattr(parent.parent(), "canvas_page", None) or getattr(parent, "canvas_page", None)
                if m is not None and hasattr(m, "open_ss_3d"):
                    m.open_ss_3d(on_top=True)
                    st.setText("已打开真 GL 3D 视图 (仿真轨迹 + 🗂 场景编辑面板)")
                else:
                    st.setText("画布模块未就绪: 请先打开 Simulink 页再试")
            except Exception as e:                                             # noqa: BLE001
                st.setText("打开 GL 3D 视图失败: %r" % (e,))
        row2.addWidget(_b("🖥 真 GL 3D 视图 (仿真轨迹)", "画布那条单例 GL 3D 窗口 (同一份场景真源)", _open_gl, "#8b6cf0"))
    v.addLayout(row2)
    v.addWidget(view, 1)
    v.addWidget(st)
    _switch()
    return card


def _toggle(view, st):
    if view.sel is None:
        st.setText("先点选一个对象")
        return
    o = view.data["objects"][view.sel]
    name = str(o.get("name"))
    ok, d = _se(view.scene_id, "hide", "--kind", "objects", "--name", name)
    st.setText(("✅ 显隐切换 %s" % name[:26]) if ok else ("⛔ 显隐失败: %s" % (d.get("msg") or "")))
    view.reload()


def _add(view, st):
    if not view.scene_id:
        st.setText("⛔ 在役场景只读: 先在场景下拉里选命名场景")
        return
    name, ok = QInputDialog.getText(view, "新增对象", "对象名 (如 上下料·检查点):")
    if not (ok and name.strip()):
        return
    c = list(getattr(view, "center", [0.6, 0.35, 0.15]))
    payload = {"name": name.strip(), "center": [round(c[0], 5), round(c[1], 5), 0.15],
               "size": [80.0, 80.0, 40.0], "source": "场景 3D 视图新增", "note": "页内 3D 视图新增"}
    ok2, d = _se(view.scene_id, "add", "--kind", "objects", "--data", json.dumps(payload, ensure_ascii=False))
    st.setText(("✅ 已新增 %s (回读一致)" % name) if (ok2 and (d.get("readback") or d.get("readback_ok"))) else ("⛔ 新增失败: %s" % (d.get("msg") or "")))
    view.reload()


def _del(view, st):
    if view.sel is None:
        st.setText("先点选一个对象")
        return
    o = view.data["objects"][view.sel]
    ok, d = _se(view.scene_id, "rm", "--kind", "objects", "--id", str(o.get("name")))
    st.setText(("✅ 已删除 %s (备份在场景目录)" % str(o.get("name"))[:24]) if ok else ("⛔ 删除失败: %s" % (d.get("msg") or "")))
    view.reload()
