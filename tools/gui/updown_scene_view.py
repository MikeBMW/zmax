#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""updown_scene_view.py — 场景编辑器 · 3D 可编辑视图 (唯一一个) (老倪 2026-10-10)

老倪口径 (逐条对号):
  · 「在哪呢仿真场景？删掉 Sim&Real 的功能积木部分，我要上下料的可编辑窗口，3D 渲染的场景，类似 dreamview 的 3D 场景」
  · 「Sim&Real功能区，删掉下面的 L2 L3 L4，只保留可编辑窗口，大一些，现在太小了，图像都看不到」
  · 「这个页面要有多个场景要管理，上下料，还有之前的插拔场景，要有切换，用户可以选择要编辑的场景元素，位置，轨迹等」
  · 「只需要一个场景编辑器即可，你怎么还搞两个？要大一点的窗口，边沿可以拖拽放大」

设计:
  · **唯一**场景编辑器。旧的表格编辑器 (sim_real_page.build_body) 不再挂到 Sim&Real 页; 该文件只留共享助手。
  · 四类元素都能选/改: 对象(objects) 位置+尺寸 · 标记(markers) 位置+半径+类型 · 围栏(fences) 位置+尺寸 · 轨迹(trajectories) 航点。
  · 多场景切换: data/scene/scenes/index.json 注册的**全部**命名场景 (上下料 SCN-07-UP / 插拔 SCN-01-PEG / 5 个作业场景)
    + 在役现场场景 (只读预览)。
  · 窗口大 + 边沿可拖: 3D 视图 与 元素面板 之间是 QSplitter, **拖分隔条即放大视图**; 另有「⛶ 视图全屏 / ⤡ 还原」。
  · 写操作一律经 tools/scene_edit.py (备份 + 原子写 + 回读 + 回滚); 在役现场场景只读。
  · 为什么不新开第二个 GL 窗口: pyqtgraph shader 句柄绑**第一个** GL 上下文, 第二窗口全画不出来
    (技能 qt-gl-rendering-pitfalls 坑 1) ⇒ 页内走 QPainter 正交投影自绘, 零 GL 依赖, 不干扰画布那条真 GL 3D 视图。
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time

from PyQt5.QtCore import QRectF, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QSizePolicy, QSplitter, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SCENES_ROOT = os.path.join(ROOT, "data", "scene", "scenes")
LIVE_DIR = os.path.join(ROOT, "data", "scene")
INDEX = os.path.join(SCENES_ROOT, "index.json")

KINDS = ("objects", "markers", "fences", "trajectories")
KIND_CN = {"objects": "对象", "markers": "标记", "fences": "围栏", "trajectories": "轨迹"}
MARKER_TYPES = ("工位", "危险区", "检查点", "自定义")
TRAJ_KINDS = ("自定义", "示教", "规划")

C_BG, C_GRID, C_TXT, C_DIM = "#0b0f14", "#1b2b33", "#e6edf3", "#7d8590"
C_AXIS_X, C_AXIS_Y, C_AXIS_Z = "#e05561", "#7ddc7d", "#5aa9ff"
C_OBJ, C_OBJ_SEL = "#00d4aa", "#ffc857"
C_MARK, C_FENCE, C_TRAJ = "#ff8a3d", "#8b6cf0", "#4da3ff"


# ─────────────────────────── 数据层 ───────────────────────────
# 老倪 2026-10-10: 「现在已有的场景是插拔场景，和上下料场景；其它场景先不用搞」
#   ⇒ 只把这俩放进下拉 (其余场景的定义/文件都不动, 只是不露脸, 可随时加回来)
SCENE_WHITELIST = ("SS-EPI-CORNER", "SS-TRAY-PLACE", "SIM-PEG-L4", "SCN-07-UP")   # 3D场景/摆盘 先
SCENE_LABEL = {"SIM-PEG-L4": "🔧 插拔场景 (对齐 metaworld 真模型)",
               "SCN-07-UP": "📦 上下料场景",
               # 老倪 2026-10-10: 「先把这个场景复制到你的场景编辑窗口里」— 就是画布 3D 分层视图正在跑的那条
               "SS-EPI-CORNER": "🧭 3D场景 (与操作视频同源 · 复制自你正在跑的那条)"}


def scene_options():
    """可选场景: (标签, 场景目录, scene_id or None=在役只读)。"""
    out = []      # 老倪 2026-10-10: 只要 插拔场景 + 上下料场景 (在役预览/其它场景都不露脸)
    try:
        with open(INDEX, encoding="utf-8") as f:
            idx = json.load(f)
        _sc = idx.get("named_scenes") or {}
        for sid in [x for x in SCENE_WHITELIST if x in _sc]:
            v = _sc[sid]
            _run = v.get("run") or None
            _label = SCENE_LABEL.get(sid) or (str(v.get("name") or "")[:26])
            out.append(("%s%s   %d 对象/%d 标记/%d 围栏/%d 轨迹"
                        % (_label, "   ▶可运行" if _run else "",
                           v.get("n_objects", 0), v.get("n_markers", 0),
                           v.get("n_fences", 0), v.get("n_trajectories", 0)),
                        os.path.join(SCENES_ROOT, sid), sid, _run))
    except Exception:                                                          # noqa: BLE001
        pass
    if len(out) == 1 and os.path.isdir(SCENES_ROOT):
        for d in sorted(os.listdir(SCENES_ROOT)):
            if os.path.isdir(os.path.join(SCENES_ROOT, d)):
                out.append((d, os.path.join(SCENES_ROOT, d), d, None))
    return out


def _obj_color(o):
    """对象自带颜色 → #rrggbb; scene_edit 的 color 支持 [r,g,b] 0~1 或 'rrggbb'/'#rrggbb'。"""
    c = (o or {}).get("color")
    try:
        if isinstance(c, (list, tuple)) and len(c) == 3:
            return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(float(v) * 255)))) for v in c)
        if isinstance(c, str) and c.strip():
            t = c.strip().lstrip("#")
            return t if len(t) == 6 else None
    except Exception:                                                           # noqa: BLE001
        return None
    return None


def _j(p, d):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return d


def load_scene(scene_dir, scene_id=None):
    """读一个场景: 四类元素 + 元信息 (名称/是否只读)。"""
    o = _j(os.path.join(scene_dir, "objects3d.json"), {}) or {}
    v = _j(os.path.join(scene_dir, "overlay_spec.json"), {}) or {}
    return {"objects": [x for x in (o.get("objects") or []) if isinstance(x, dict)],
            "markers": [x for x in (v.get("markers") or []) if isinstance(x, dict)],
            "fences": [x for x in (v.get("fences") or []) if isinstance(x, dict)],
            "trajectories": [x for x in (v.get("trajectories") or []) if isinstance(x, dict)],
            "deleted": (v.get("deleted") or {}), "fence_note": v.get("fence_note"),
            "kind": o.get("kind") or v.get("kind"),        # episode / sim: 决定要不要自动套 corner2 机位
            "sim": bool(o.get("sim")),
            "meta": {"id": scene_id, "dir": scene_dir, "read_only": scene_id is None,
                     "name": (o.get("scene_name") or (o.get("meta") or {}).get("name")
                              or o.get("scene_id") or scene_id or "现场场景"),
                     "source": o.get("source") or v.get("source") or ""}}


def _se(scene_id, *args):
    """调 scene_edit.py (唯一写路径, 带备份/回读)。返回 (ok, dict)。"""
    if not scene_id:
        return False, {"msg": "在役现场场景只读"}
    argv = [sys.executable, os.path.join(ROOT, "tools", "scene_edit.py"), "--scene", str(scene_id)]
    argv += [str(a) for a in args] + ["--json"]
    try:
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=40)
    except Exception as e:                                                     # noqa: BLE001
        return False, {"msg": "调 scene_edit 失败: %r" % (e,)}
    txt = r.stdout or ""
    i = txt.find("{")
    try:
        d = json.loads(txt[i:]) if i >= 0 else {}
    except Exception:                                                          # noqa: BLE001
        d = {}
    return (r.returncode == 0 and bool(d.get("ok", True))), d


def _sim_mod():
    """仿真场景真源模块 (失败=None ⇒ 退回普通场景写路径)。"""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import sim_scene_def as _S
        return _S
    except Exception:                                                          # noqa: BLE001
        return None


def ent_id(item, kind):
    """元素的写回标识: 优先 id, 退回 name (objects 老数据可能只有 name)。"""
    if not isinstance(item, dict):
        return None
    return item.get("id") or item.get("name")


def anchor_of(item, kind):
    """可拖动锚点 (世界坐标 m) 或 None。"""
    if kind == "objects":
        c = item.get("center")
    elif kind == "markers":
        c = item.get("pos")
    elif kind == "fences":
        sh = item.get("shape") if isinstance(item.get("shape"), dict) else {}
        c = sh.get("center") or item.get("center")
    else:
        return None
    return [float(x) for x in c] if isinstance(c, list) and len(c) == 3 else None


def size_of(item, kind):
    """元素尺寸 (m)。"""
    if kind == "objects":
        s = item.get("size")
        if isinstance(s, list) and len(s) == 3:
            v = [float(x) for x in s]
            return [x / 1000.0 for x in v] if max(v) > 20 else v       # 老数据是 mm
        return [0.05, 0.05, 0.05]
    if kind == "markers":
        r = float(item.get("radius_m") or 0.03)
        return [r * 2, r * 2, r * 2]
    if kind == "fences":
        sh = item.get("shape") if isinstance(item.get("shape"), dict) else {}
        s = sh.get("size") or item.get("size_m")
        if isinstance(s, list) and len(s) == 3:
            return [float(x) for x in s]
        return [0.3, 0.3, 0.3]
    return [0.05, 0.05, 0.05]


def move_patch(item, kind, xyz, wp=None):
    """拖动 ⇒ scene_edit update 的 patch。"""
    if kind == "objects":
        return {"center": [round(v, 5) for v in xyz]}
    if kind == "markers":
        return {"pos": [round(v, 5) for v in xyz]}
    if kind == "fences":
        sh = dict(item.get("shape") or {})
        sh["center"] = [round(v, 5) for v in xyz]
        sh.setdefault("size", [0.3, 0.3, 0.3])
        return {"kind": item.get("kind") or "box", "shape": sh}
    if kind == "trajectories" and wp is not None:
        wps = [list(w) for w in (item.get("waypoints") or [])]
        if 0 <= wp < len(wps):
            wps[wp] = [round(v, 5) for v in xyz]
        return {"waypoints": wps}
    return {}


# ─────────────────────────── 运行线程 (GUI 不卡) ───────────────────────────
class RunThread(QThread):
    """在后台跑仿真入口 (如 tools/gen_l4_demo_video.py), 逐行回吐日志给 UI。"""

    line = pyqtSignal(str)
    done = pyqtSignal(int)

    def __init__(self, cmd, cwd, env=None, parent=None):
        super().__init__(parent)
        self.cmd, self.cwd, self.env = list(cmd), cwd, env

    def run(self):                                                             # noqa: D102
        rc = -1
        try:
            p = subprocess.Popen(self.cmd, cwd=self.cwd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 env={**(self.env or os.environ), "PYTHONUNBUFFERED": "1"})
            for ln in p.stdout:                                                # type: ignore[union-attr]
                self.line.emit(ln.rstrip())
            rc = p.wait()
        except Exception as e:                                                 # noqa: BLE001
            self.line.emit("启动失败: %r" % (e,))
        self.done.emit(rc)


# ─────────────────────────── 3D 视图 ───────────────────────────
class SceneView3D(QWidget):
    """正交投影 3D 场景视图: 点选/拖动/双击改数值 (四类元素通用)。"""

    def __init__(self, scene_dir, scene_id=None, status_cb=None, parent=None):
        super().__init__(parent)
        self.scene_dir, self.scene_id = scene_dir, scene_id
        self.status_cb = status_cb or (lambda s: None)
        self.data = load_scene(scene_dir, scene_id)
        self.az, self.el, self.scale = 35.0, 32.0, 620.0
        self.pan = [0.0, 0.0]
        self.sel = None                       # {"kind","i","wp"} | None
        self.kind_filter = None               # None=全部, 否则只点选该类
        self.on_select = None                 # 卡片回填元素列表
        self._press = None
        self._drag = None
        self._preview = None
        self._dragging = False
        self._manual_scale = False
        self.center = [0.6, 0.35, 0.15]
        self.setMinimumHeight(780)          # 老倪: 「还是太小，变大一些」(再放大一档; 分隔条/独立窗口还能更大)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.fit_view()

    # ── 场景/数据 ──
    def set_scene(self, scene_dir, scene_id=None):
        self.scene_dir, self.scene_id = scene_dir, scene_id
        self.data = load_scene(scene_dir, scene_id)
        self.sel = None
        self._preview = None
        self._manual_scale = False
        self.fit_view()
        if (self.data or {}).get("kind") == "episode":      # 3D场景: 进场景即用操作视频同一机位
            self.apply_corner2_view()
        self.update()
        if self.on_select:
            self.on_select(None)

    def _item(self, sel):
        if not sel:
            return None
        lst = self.data.get(sel.get("kind")) or []
        i = sel.get("i")
        return lst[i] if isinstance(i, int) and 0 <= i < len(lst) else None

    def _all_points(self):
        pts = []
        for k in KINDS:
            for it in (self.data.get(k) or []):
                if k == "trajectories":
                    for w in (it.get("waypoints") or []):
                        if isinstance(w, list) and len(w) == 3:
                            pts.append([float(x) for x in w])
                    continue
                a = anchor_of(it, k)
                if not a:
                    continue
                sz = size_of(it, k)
                pts += self._box_edges(a, sz)[0]
        return pts

    def fit_view(self):
        """自适应取景: 让整个场景投到视口里 (约占 90% 宽 / 70% 高)。

        老倪: 「大一些，现在太小了，图像都看不到」—— 之前 scale 写死 620px/m,
        大场景撑出画面、小场景缩成一小撮 ⇒ 按投影包围盒真算。
        """
        pts = self._all_points()
        if not pts or self.width() < 60:
            return
        self.center = [(min(p[i] for p in pts) + max(p[i] for p in pts)) / 2.0 for i in range(3)]
        self.pan = [0.0, 0.0]
        _, right, upv = self._basis()
        mx = my = 1e-6
        for p in pts:
            d = [p[i] - self.center[i] for i in range(3)]
            mx = max(mx, abs(sum(d[i] * right[i] for i in range(3))))
            my = max(my, abs(sum(d[i] * upv[i] for i in range(3))))
        self.scale = max(60.0, min(9000.0, min(self.width() * 0.45 / mx, self.height() * 0.35 / my)))
        self._manual_scale = False
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._manual_scale:
            self.fit_view()

    def reload(self):
        """重读真源。按 id/name 找回原选中项 (写一次就丢选中 ⇒ 连续拖动第二次会失效)。"""
        _keep = None
        if self.sel:
            it = self._item(self.sel)
            if it is not None:
                _keep = (self.sel["kind"], ent_id(it, self.sel["kind"]), self.sel.get("wp"))
        self.data = load_scene(self.scene_dir, self.scene_id)
        self.sel = None
        self._preview = None
        if _keep and _keep[1] is not None:
            for i, it in enumerate(self.data.get(_keep[0]) or []):
                if str(ent_id(it, _keep[0])) == str(_keep[1]):
                    self.sel = {"kind": _keep[0], "i": i, "wp": _keep[2]}
                    break
        self.fit_view()
        self.update()
        if self.on_select:
            self.on_select(self.sel)
        return self.data

    # ── 投影 ──
    def apply_corner2_view(self):
        """切到 corner2 机位 —— 与操作视频 / 3D场景窗口**同一个相机** (外参取自 episode meta 真值)。

        老倪 2026-10-10: 「把现在的3D场景迁移到主界面 Sim&Real 的场景里, 一会在这个场景上编辑」
        ⇒ 编辑器里看到的这条场景, 视角也得是他在窗口里看的那个, 不然"编辑的"和"看到的"对不上。
        """
        try:
            import sim_scene_def as _S
            _t = _S.episode_truth()
            cam = [float(v) for v in _t["cam_pos"]]
        except Exception:                                                       # noqa: BLE001
            return False
        self.fit_view()
        tgt = [0.0, 0.6, 0.13]                       # 桌心 / 孔口高度 (与 3D场景窗口同锚点)
        self.center = list(tgt)
        v = [cam[i] - tgt[i] for i in range(3)]
        n = (sum(x * x for x in v) ** 0.5) or 1.0
        e = [x / n for x in v]
        self.az = math.degrees(math.atan2(e[0], e[1]))
        self.el = math.degrees(math.asin(max(-1.0, min(1.0, e[2]))))
        self.pan = [0.0, 0.0]
        self._manual_scale = False
        self.update()
        return True

    def _basis(self):
        a, e = math.radians(self.az), math.radians(self.el)
        eye = [math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)]
        fwd = [-eye[0], -eye[1], -eye[2]]
        up = [0.0, 0.0, 1.0]
        right = [fwd[1] * up[2] - fwd[2] * up[1], fwd[2] * up[0] - fwd[0] * up[2],
                 fwd[0] * up[1] - fwd[1] * up[0]]
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
        return QRectF(x, y, 0, 0).topLeft(), sum(d[i] * fwd[i] for i in range(3))

    def _box_edges(self, c, sz):
        hx, hy, hz = sz[0] / 2, sz[1] / 2, sz[2] / 2
        v = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for szz in (-1, 1):
                    v.append([c[0] + sx * hx, c[1] + sy * hy, c[2] + szz * hz])
        e = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
        return v, e

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
        step, n = 0.1, 10
        base = [round(self.center[0] / step) * step, round(self.center[1] / step) * step]
        for i in range(-n, n + 1):
            x = base[0] + i * step
            self._line3(p, basis, [x, base[1] - n * step, 0.0], [x, base[1] + n * step, 0.0], C_GRID, 1)
            y = base[1] + i * step
            self._line3(p, basis, [base[0] - n * step, y, 0.0], [base[0] + n * step, y, 0.0], C_GRID, 1)
        o = [base[0], base[1], 0.0]
        ln = max(0.08, min(0.5, 60.0 / max(self.scale, 1.0)))
        self._line3(p, basis, o, [o[0] + ln, o[1], 0.0], C_AXIS_X, 2)
        self._line3(p, basis, o, [o[0], o[1] + ln, 0.0], C_AXIS_Y, 2)
        self._line3(p, basis, o, [o[0], o[1], o[2] + ln], C_AXIS_Z, 2)

    def _selq(self, kind, i, wp=None):
        s = self.sel or {}
        if s.get("kind") != kind or s.get("i") != i:
            return False
        return s.get("wp") == wp if (kind == "trajectories" and wp is not None) else True

    def _draw_objects(self, p, basis):
        items = []
        for i, o in enumerate(self.data["objects"]):
            c = anchor_of(o, "objects")
            if not c:
                continue
            sz = size_of(o, "objects")
            _, depth = self._proj(c, basis)
            items.append((depth, i, o, c, sz))
        for _depth, i, o, c, sz in sorted(items, reverse=False):      # 远→近
            hid = self._hidden(str(o.get("name")))
            sel = self._selq("objects", i)
            # 对象自带颜色 (如机器人本体 = 浅灰) 优先, 否则默认青绿 —— 老倪要看得出"哪是机器人"
            _oc = _obj_color(o)
            col = C_OBJ_SEL if sel else (C_DIM if hid else (_oc or C_OBJ))
            v, e = self._box_edges(c, sz)
            bottom = [v[0], v[1], v[3], v[2]]
            p.setBrush(QBrush(QColor(col + "33")))
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([self._proj(q, basis)[0] for q in bottom]))
            for a, b in e:
                pa, _ = self._proj(v[a], basis)
                pb, _ = self._proj(v[b], basis)
                p.setPen(QPen(QColor(col), 2 if sel else 1, Qt.DashLine if hid else Qt.SolidLine))
                p.drawLine(pa, pb)
            pc, _ = self._proj([c[0], c[1], c[2] + sz[2] / 2], basis)
            p.setPen(QPen(QColor(col)))
            p.setFont(QFont("Arial", 10, QFont.Bold if sel else QFont.Normal))
            p.drawText(QRectF(pc.x() - 120, pc.y() - 26, 240, 16), Qt.AlignCenter, str(o.get("name"))[:26])
            if sel:
                p.setFont(QFont("Arial", 8))
                p.drawText(QRectF(pc.x() - 150, pc.y() - 12, 300, 14), Qt.AlignCenter,
                           "对象 · [%.3f, %.3f, %.3f] m · %.0f×%.0f×%.0f mm"
                           % (c[0], c[1], c[2], sz[0] * 1000, sz[1] * 1000, sz[2] * 1000))

    def _draw_markers(self, p, basis):
        for i, m in enumerate(self.data["markers"]):
            pos = anchor_of(m, "markers")
            if not pos:
                continue
            sel = self._selq("markers", i)
            col = C_OBJ_SEL if sel else C_MARK
            self._line3(p, basis, [pos[0], pos[1], 0.0], pos, col, 2 if sel else 1, Qt.DashLine)
            q, _ = self._proj(pos, basis)
            r = max(4.0, float(m.get("radius_m") or 0.03) * self.scale * 0.5)
            p.setBrush(QBrush(QColor(col + ("cc" if sel else "88"))))
            p.setPen(QPen(QColor(col), 2 if sel else 1))
            p.drawEllipse(q, r, r)
            p.setPen(QPen(QColor(col)))
            p.setFont(QFont("Arial", 9, QFont.Bold if sel else QFont.Normal))
            p.drawText(QRectF(q.x() - 90, q.y() + r + 3, 180, 14), Qt.AlignCenter, "标记 · " + str(m.get("name"))[:20])
            if sel:
                p.setFont(QFont("Arial", 8))
                p.drawText(QRectF(q.x() - 150, q.y() - r - 16, 300, 13), Qt.AlignCenter,
                           "[%.3f, %.3f, %.3f] m · r=%.0fmm · %s"
                           % (pos[0], pos[1], pos[2], float(m.get("radius_m") or 0.03) * 1000, m.get("type") or "自定义"))

    def _draw_fences(self, p, basis):
        for i, f in enumerate(self.data["fences"]):
            c = anchor_of(f, "fences")
            if not c:
                continue
            sel = self._selq("fences", i)
            col = C_OBJ_SEL if sel else C_FENCE
            sz = size_of(f, "fences")
            v, e = self._box_edges(c, sz)
            for a, b in e:
                self._line3(p, basis, v[a], v[b], col, 2 if sel else 1, Qt.DashLine)
            q, _ = self._proj([c[0], c[1], c[2] + sz[2] / 2], basis)
            p.setPen(QPen(QColor(col)))
            p.setFont(QFont("Arial", 9, QFont.Bold if sel else QFont.Normal))
            p.drawText(QRectF(q.x() - 95, q.y() - 16, 190, 14), Qt.AlignCenter, "围栏 · " + str(f.get("name"))[:20])
            if sel:
                p.setFont(QFont("Arial", 8))
                p.drawText(QRectF(q.x() - 150, q.y() - 3, 300, 13), Qt.AlignCenter,
                           "%.2f×%.2f×%.2f m" % (sz[0], sz[1], sz[2]))

    def _draw_trajectories(self, p, basis):
        for i, t in enumerate(self.data["trajectories"]):
            wps = [w for w in (t.get("waypoints") or []) if isinstance(w, list) and len(w) == 3]
            if len(wps) < 2:
                continue
            s = self.sel or {}
            base_sel = (s.get("kind") == "trajectories" and s.get("i") == i)
            col = C_OBJ_SEL if base_sel else C_TRAJ

            def _pt(k):
                w = [float(x) for x in wps[k]]
                if base_sel and self._preview and s.get("wp") == k:
                    return [float(x) for x in self._preview]
                return w

            for k in range(len(wps) - 1):
                self._line3(p, basis, _pt(k), _pt(k + 1), col, 3 if base_sel else 2)
            for k, w in enumerate(wps):
                wsel = base_sel and s.get("wp") == k
                q, _ = self._proj(_pt(k), basis)
                r = 7 if wsel else 4
                p.setBrush(QBrush(QColor(C_OBJ_SEL if wsel else col)))
                p.setPen(QPen(QColor(C_OBJ_SEL if wsel else col), 2 if wsel else 1))
                p.drawRect(QRectF(q.x() - r / 2.0, q.y() - r / 2.0, r, r))
                if wsel:
                    pos = _pt(k)
                    p.setPen(QPen(QColor(C_OBJ_SEL)))
                    p.setFont(QFont("Arial", 8, QFont.Bold))
                    p.drawText(QRectF(q.x() - 90, q.y() - 26, 180, 13), Qt.AlignCenter,
                               "P%d [%.3f, %.3f, %.3f]" % (k, pos[0], pos[1], pos[2]))
            q0, _ = self._proj([float(x) for x in wps[0]], basis)
            p.setPen(QPen(QColor(col)))
            p.setFont(QFont("Arial", 9, QFont.Bold if base_sel else QFont.Normal))
            p.drawText(QRectF(q0.x() - 100, q0.y() + 6, 200, 14), Qt.AlignCenter,
                       "轨迹 · " + str(t.get("name"))[:20] + " (%d 点)" % len(wps))

    def _draw_hud(self, p):
        m = self.data.get("meta") or {}
        s = self.sel or {}
        cur = self._item(s)
        lines = ["🧭 %s%s" % (m.get("name") or "场景", "   (在役 · 只读预览)" if m.get("read_only") else ""),
                 "对象 %d · 标记 %d · 围栏 %d · 轨迹 %d    视角 az %.0f° el %.0f°  ×%.2f"
                 % (len(self.data["objects"]), len(self.data["markers"]), len(self.data["fences"]),
                    len(self.data["trajectories"]), self.az, self.el, self.scale / 620.0),
                 ("选中: %s · %s%s" % (KIND_CN.get(s.get("kind"), ""), str(ent_id(cur, s.get("kind")))[:26],
                                    ("  航点 P%s" % s.get("wp")) if s.get("kind") == "trajectories" else ""))
                 if cur else "选中: —   左键点选 · 拖动=地面平移 · 双击=改数值 · 右键拖=转视角 · 滚轮=缩放"]
        p.setFont(QFont("Arial", 9))
        y = 6
        for i, txt in enumerate(lines):
            p.setPen(QPen(QColor(C_TXT if i == 0 else (C_OBJ_SEL if (i == 2 and cur) else C_DIM))))
            p.drawText(10, y + 12, txt)
            y += 15

    # ── 交互 ──
    def _cands(self):
        out = []
        kinds = (self.kind_filter,) if self.kind_filter else KINDS
        for k in kinds:
            for i, it in enumerate(self.data.get(k) or []):
                if k == "trajectories":
                    for wi, w in enumerate(it.get("waypoints") or []):
                        if isinstance(w, list) and len(w) == 3:
                            out.append((k, i, wi, [float(x) for x in w]))
                    continue
                a = anchor_of(it, k)
                if a:
                    out.append((k, i, None, a))
        return out

    def _hit(self, pos):
        """⇒ {"kind","i","wp"} | None (只在当前类型过滤内命中)。"""
        basis = self._basis()
        best, bd = None, 16.0
        for k, i, wi, a in self._cands():
            q, _ = self._proj(a, basis)
            d = math.hypot(q.x() - pos.x(), q.y() - pos.y())
            if d < bd:
                best, bd = {"kind": k, "i": i, "wp": wi}, d
        return best

    def _set_sel(self, sel):
        self.sel = sel
        self._preview = None
        if self.on_select:
            self.on_select(sel)
        self.update()

    def mousePressEvent(self, ev):
        self._press = ev.pos()
        if ev.button() == Qt.LeftButton:
            sel = self._hit(ev.pos())
            self._set_sel(sel)
            self._dragging = sel is not None
            self._drag = (ev.pos().x(), ev.pos().y()) if sel else None
            if sel is None:
                self.status_cb("已取消选中 (在空处左键拖动 = 平移视图)")
        ev.accept()

    def mouseMoveEvent(self, ev):
        if (ev.buttons() & Qt.LeftButton) and self._dragging and self._drag is not None:
            _fwd, right, upv = self._basis()
            dx, dy = ev.pos().x() - self._drag[0], ev.pos().y() - self._drag[1]
            det = right[0] * upv[1] - right[1] * upv[0]
            if abs(det) > 1e-6 and self.sel:
                bx, by = dx / self.scale, -dy / self.scale
                wx = (bx * upv[1] - by * right[1]) / det
                wy = (right[0] * by - upv[0] * bx) / det
                it = self._item(self.sel)
                if it is not None:
                    if self.sel["kind"] == "trajectories" and self.sel.get("wp") is not None:
                        wps = [w for w in (it.get("waypoints") or []) if isinstance(w, list) and len(w) == 3]
                        base = self._preview or ([float(x) for x in wps[self.sel["wp"]]]
                                                 if self.sel["wp"] < len(wps) else None)
                    else:
                        base = self._preview or anchor_of(it, self.sel["kind"])
                    if base:
                        self._preview = [base[0] + wx, base[1] + wy, base[2]]
                        self.update()
            self._drag = (ev.pos().x(), ev.pos().y())
            ev.accept()
            return
        if (ev.buttons() & Qt.LeftButton) and self._press is not None:
            d = ev.pos() - self._press
            self.pan[0] += d.x()
            self.pan[1] += d.y()
            self._press = ev.pos()
            self.update()
        elif (ev.buttons() & Qt.RightButton) and self._press is not None:
            d = ev.pos() - self._press
            self.az = (self.az + d.x() * 0.5) % 360
            self.el = max(-80.0, min(85.0, self.el + d.y() * 0.4))
            self._press = ev.pos()
            self.update()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        s, it = self.sel or {}, None
        if self._dragging and self._preview:
            it = self._item(s)
            if it is None:
                pass
            elif not self.scene_id:
                self.status_cb("⛔ 在役现场场景只读: 编辑请在上方场景下拉选命名场景 (如 SCN-07-UP / SCN-01-PEG)")
            else:
                k = s["kind"]
                patch = move_patch(it, k, self._preview, s.get("wp"))
                base = (anchor_of(it, k) if k != "trajectories" else
                        ([float(x) for x in (it.get("waypoints") or [])[s["wp"]]] if s.get("wp") is not None else None))
                newv = patch.get("waypoints", [None])[s["wp"]] if k == "trajectories" else (patch.get("center") or patch.get("pos"))
                if patch and base and newv and [round(float(x), 5) for x in base] != [round(float(x), 5) for x in newv]:
                    self._write(patch, "拖动%s %s%s" % (KIND_CN.get(k, k), str(ent_id(it, k))[:22],
                                                     (" 航点P%s" % s.get("wp")) if k == "trajectories" else ""), k)
        self._preview = None
        self._drag = None
        self._dragging = False
        self._press = None
        self.update()
        ev.accept()

    def wheelEvent(self, ev):
        f = 1.1 if ev.angleDelta().y() > 0 else 1 / 1.1
        self.scale = max(60.0, min(9000.0, self.scale * f))
        self._manual_scale = True
        self.update()

    def mouseDoubleClickEvent(self, ev):
        sel = self._hit(ev.pos())
        if sel is None:
            return
        self._set_sel(sel)
        D = ElementDialog(self.data, sel, self)
        if D.exec_() == QDialog.Accepted:
            self._write(D.payload(), "改数值 %s" % str(ent_id(self._item(sel), sel["kind"]))[:22], sel["kind"])

    def _write(self, patch, what, kind="objects", ent_id_=None):
        if not patch:
            return False
        if not self.scene_id:
            self.status_cb("⛔ 在役现场场景只读: 写操作只落 data/scene/scenes/<ID>/")
            self.reload()
            return False
        it = self._item(self.sel) if (self.sel and self.sel.get("kind") == kind) else None
        _id = ent_id_ or (ent_id(it, kind) if it else None)
        # 🎯 仿真场景 (SIM-*): 几何真源是 data/scene/sim/sim_scenes.json ⇒ 写它, 再重建场景目录;
        #    否则改了产物目录但物理/视觉仍按真源 → 就是"假接入" (老倪零容忍)
        _S = _sim_mod()
        if _S is not None and _S.is_sim_scene(self.scene_id):
            r = _S.apply_patch(kind, str(_id), patch, scene_id=self.scene_id)
            if r.get("ok"):
                self.status_cb("✅ %s · %s · 已写仿真场景真源 (备份 %s) · 物理与视觉同步"
                               % (what, str(_id)[:26], str(r.get("backup"))))
            else:
                self.status_cb("⛔ %s 失败: %s" % (what, r.get("msg")))
            self.reload()
            return bool(r.get("ok"))
        ok, d = _se(self.scene_id, "update", "--kind", kind, "--id", str(_id),
                    "--data", json.dumps(patch, ensure_ascii=False))
        if ok and (d.get("readback") or d.get("readback_ok")):
            self.status_cb("✅ %s · %s · 回读一致 · 备份 %s"
                           % (what, str(_id)[:26], os.path.basename(str(d.get("backup") or "—"))))
        else:
            self.status_cb("⛔ %s 失败: %s" % (what, d.get("msg") or "见 scene_edit 输出"))
        self.reload()
        return ok

    def view(self, az, el, scale=None):
        self.az, self.el = az, el
        self.pan = [0.0, 0.0]
        if scale:
            self.scale, self._manual_scale = scale, True
        else:
            self._manual_scale = False
            self.fit_view()
        self.update()


# ─────────────────────────── 编辑对话框 (四类元素) ───────────────────────────
class ElementDialog(QDialog):
    """按元素类型给表单: 对象/标记/围栏 (数值) · 轨迹 (航点表)。"""

    def __init__(self, data, sel, parent=None):
        super().__init__(parent)
        self.data, self.sel = data, sel
        self.kind = sel["kind"]
        self.item = data[self.kind][sel["i"]]
        self.setWindowTitle("编辑%s · %s" % (KIND_CN[self.kind], str(self.item.get("name"))[:34]))
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        if self.kind == "trajectories":
            self._build_traj(lay)
        else:
            self._build_vec(lay)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _spin(self, val, lo, hi, dec=3, step=0.005):
        sp = QDoubleSpinBox()
        sp.setDecimals(dec)
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(float(val))
        return sp

    def _build_vec(self, lay):
        it, k = self.item, self.kind
        a = anchor_of(it, k) or [0.0, 0.0, 0.0]
        sz = size_of(it, k)
        f = QFormLayout()
        self.sp = {("pos", i): self._spin(a[i], -3.0, 3.0) for i in range(3)}
        lab = {"objects": "中心", "markers": "位置", "fences": "中心"}[k]
        for i, ax in enumerate("XYZ"):
            f.addRow("%s%s (m)" % (lab, ax), self.sp[("pos", i)])
        if k == "markers":
            self.sp[("r", 0)] = self._spin((it.get("radius_m") or 0.03) * 1000, 1.0, 500.0, 0, 5.0)
            f.addRow("半径 (mm)", self.sp[("r", 0)])
            self.typ = QComboBox()
            self.typ.addItems(MARKER_TYPES)
            self.typ.setCurrentText(it.get("type") if it.get("type") in MARKER_TYPES else "自定义")
            f.addRow("类型", self.typ)
        else:
            mm = (k == "objects")
            for i, ax in enumerate("XYZ"):
                self.sp[("size", i)] = self._spin(sz[i] * (1000.0 if mm else 1.0), 1.0 if mm else 0.01,
                                                  3000.0 if mm else 5.0, 1 if mm else 3, 5.0 if mm else 0.01)
                f.addRow("尺寸%s (%s)" % (ax, "mm" if mm else "m"), self.sp[("size", i)])
        lay.addLayout(f)

    def _build_traj(self, lay):
        it = self.item
        self.wps = [list(w) for w in (it.get("waypoints") or []) if isinstance(w, list) and len(w) == 3]
        f = QFormLayout()
        self.nmk = QComboBox()
        self.nmk.addItems(TRAJ_KINDS)
        self.nmk.setCurrentText(it.get("kind") if it.get("kind") in TRAJ_KINDS else "自定义")
        f.addRow("类型", self.nmk)
        lay.addLayout(f)
        self.tbl = QTableWidget(len(self.wps), 4)
        self.tbl.setHorizontalHeaderLabels(["航点", "X (m)", "Y (m)", "Z (m)"])
        self._fill_tbl()
        self.tbl.setMinimumHeight(220)
        lay.addWidget(self.tbl)
        row = QHBoxLayout()
        b_add = QPushButton("➕ 末尾加航点")
        b_add.clicked.connect(self._add_wp)
        b_del = QPushButton("🗑 删选中航点")
        b_del.clicked.connect(self._del_wp)
        row.addWidget(b_add)
        row.addWidget(b_del)
        lay.addLayout(row)
        lab = QLabel("提示: 也可在 3D 视图里直接拖某个航点方块 (先把右侧『可编辑类型』切到轨迹)。")
        lab.setStyleSheet("color:#7d8590; font-size:11px;")
        lay.addWidget(lab)

    def _fill_tbl(self):
        self.tbl.setRowCount(len(self.wps))
        for r, w in enumerate(self.wps):
            self.tbl.setItem(r, 0, QTableWidgetItem("P%d" % r))
            for c in range(3):
                self.tbl.setItem(r, c + 1, QTableWidgetItem("%.5f" % float(w[c])))

    def _add_wp(self):
        base = self.wps[-1] if self.wps else [0.0, 0.0, 0.15]
        self.wps.append([round(float(base[0]) + 0.05, 5), float(base[1]), float(base[2])])
        self._fill_tbl()

    def _del_wp(self):
        r = self.tbl.currentRow()
        if r is not None and 0 <= r < len(self.wps) and len(self.wps) > 2:
            self.wps.pop(r)
            self._fill_tbl()

    def payload(self):
        if self.kind == "trajectories":
            out = []
            for r in range(self.tbl.rowCount()):
                vals = []
                for c in range(3):
                    cell = self.tbl.item(r, c + 1)
                    try:
                        vals.append(round(float(cell.text()), 5))
                    except Exception:                                              # noqa: BLE001
                        vals.append(round(float(self.wps[r][c]), 5))
                out.append(vals)
            if len(out) < 2:
                out = out + [[round(out[-1][0] + 0.05, 5), out[-1][1], out[-1][2]]] if out else []
            return {"kind": self.nmk.currentText(), "waypoints": out}
        a = [round(self.sp[("pos", i)].value(), 5) for i in range(3)]
        if self.kind == "markers":
            return {"pos": a, "radius_m": round(self.sp[("r", 0)].value() / 1000.0, 5),
                    "type": self.typ.currentText()}
        if self.kind == "objects":
            return {"center": a, "size": [round(self.sp[("size", i)].value() / 1000.0, 5) for i in range(3)]}
        sh = dict(self.item.get("shape") or {})
        sh["center"] = a
        sh["size"] = [round(self.sp[("size", i)].value(), 5) for i in range(3)]
        return {"kind": self.item.get("kind") or "box", "shape": sh}


# ─────────────────────────── 页面卡片 (唯一场景编辑器) ───────────────────────────
def build_card(parent=None):
    card = QGroupBox("🧭 场景编辑器 · 3D 可编辑视图 (多场景切换 · 拖中间分隔条可放大)")
    card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    card.setStyleSheet("QGroupBox{color:#00d4aa; font-weight:bold; background:#161b22;"
                       " border:1px solid #30363d; border-radius:8px; margin-top:8px;}"
                       "QGroupBox::title{subcontrol-origin:margin; left:12px; padding:0 4px;}")
    v = QVBoxLayout(card)
    v.setContentsMargins(10, 14, 10, 10)
    v.setSpacing(6)
    BTN = ("QPushButton{background:#1f2733; color:%s; border:1px solid #2a3441; border-radius:4px;"
           " padding:5px 9px; font-size:12px;} QPushButton:hover{border-color:%s;}")
    CMB = ("QComboBox{background:#0f1318; color:#e6edf3; border:1px solid #30363d; border-radius:4px;"
           " padding:4px; font-size:12px;} QComboBox QAbstractItemView{background:#0f1318; color:#e6edf3;}")

    def _b(txt, tip, fn, col="#4da3ff"):
        b = QPushButton(txt)
        b.setToolTip(tip)
        b.setStyleSheet(BTN % (col, col))
        b.clicked.connect(fn)
        return b

    st = QLabel("—")
    st.setWordWrap(True)
    st.setStyleSheet("color:#c9d1d9; font-size:11px; background:#0d1117; border:1px solid #30363d;"
                     " border-radius:4px; padding:4px;")
    card.status_label = st
    card.status_cb = lambda s: st.setText(s)

    opts = scene_options()
    cmb = QComboBox()
    cmb.setStyleSheet(CMB)
    for label, d, sid, run in opts:
        cmb.addItem(label, {"dir": d, "sid": sid, "run": run})
    cmb.setCurrentIndex(next((i for i, o in enumerate(opts) if o[2]), 0))     # 默认第一个命名场景
    d0, sid0 = cmb.currentData()["dir"], cmb.currentData()["sid"]
    view = SceneView3D(d0, sid0, status_cb=lambda s: st.setText(s))
    card.view = view
    panel = QWidget()
    pl = QVBoxLayout(panel)
    pl.setContentsMargins(0, 0, 0, 0)
    pl.setSpacing(4)
    kc = QComboBox()
    kc.setStyleSheet(CMB)
    lst = QListWidget()
    lst.setStyleSheet("QListWidget{background:#0f1318; color:#e6edf3; border:1px solid #30363d;"
                      " border-radius:4px; font-size:12px;} QListWidget::item:selected{background:#1f3b34;}")
    lst.setMinimumHeight(140)

    def _repop():
        for i in range(kc.count()):
            k = kc.itemData(i)
            kc.setItemText(i, "全部类型" if k is None else "%s (%d)" % (KIND_CN[k], len(view.data.get(k) or [])))
        lst.clear()
        k = kc.currentData()
        for kk in ((k,) if k else KINDS):
            for i, it in enumerate(view.data.get(kk) or []):
                a = anchor_of(it, kk)
                txt = "%s · %s" % (KIND_CN[kk], str(it.get("name"))[:28])
                if kk == "trajectories":
                    txt += " · %d 航点" % len(it.get("waypoints") or [])
                elif a:
                    txt += " · [%.3f, %.3f, %.3f]" % (a[0], a[1], a[2])
                row = QListWidgetItem(txt)
                row.setData(Qt.UserRole, {"kind": kk, "i": i, "wp": None})
                lst.addItem(row)
        _sync_list()

    def _sync_list():
        s = view.sel or {}
        for r in range(lst.count()):
            d = lst.item(r).data(Qt.UserRole) or {}
            if d.get("kind") == s.get("kind") and d.get("i") == s.get("i"):
                lst.setCurrentRow(r)
                return
        lst.clearSelection()

    def _on_view_select(sel):
        _sync_list()
        it = view._item(sel) if sel else None
        if it:
            st.setText("已选中 %s: %s%s   (在 3D 里拖动=改位置, 双击=改数值)"
                       % (KIND_CN.get(sel["kind"], ""), str(ent_id(it, sel["kind"]))[:28],
                          ("  航点 P%s" % sel.get("wp")) if sel.get("kind") == "trajectories" else ""))

    view.on_select = _on_view_select

    def _on_row(*_a):
        it = lst.currentItem()
        if it is not None:
            view._set_sel(it.data(Qt.UserRole))

    lst.itemClicked.connect(_on_row)
    lst.currentItemChanged.connect(lambda *_: _on_row())

    def _switch():
        _d = cmb.currentData()
        d, sid, run = _d["dir"], _d["sid"], _d.get("run")
        view.kind_filter = kc.currentData()
        view.set_scene(d, sid)
        _repop()
        _is_epi = str(sid or "") == "SS-EPI-CORNER"
        b_run.setEnabled(bool(run))
        b_run.setText("▶ 重跑同源 episode" if _is_epi else "▶ 运行仿真")
        b_run.setToolTip(("▶ 运行该场景: %s %s (约 %ss)" % (run.get("tool"), " ".join(str(a) for a in (run.get("args") or [])),
                                                       run.get("eta_s"))) if run else
                         "该场景没有运行入口 (只有仿真/回放场景可运行)")
        b_seed.setVisible(_is_epi)
        b_seed.setEnabled(_is_epi)
        b_cam.setVisible(_is_epi)
        _epi_info = ""
        if _is_epi:
            _S = _sim_mod()
            try:
                _t = _S.episode_truth()
                if _t.get("ok"):
                    _epi_info = ("\n   🎬 同源对 %s · %d 帧 · seed=%s · 成功率 %s · 帧龄 %.1fh · 视频 %s"
                                 % (os.path.basename(_t["npz"]), _t["steps"], _t.get("seed"), _t.get("success"),
                                    _t["age_s"] / 3600, os.path.basename(_t["mp4"])))
                    if "自洽" not in str(_t.get("why")):
                        _epi_info += "\n   ⚠️ " + str(_t.get("why"))
            except Exception:                                                   # noqa: BLE001
                pass
        st.setText("已切到 %s%s · 对象 %d / 标记 %d / 围栏 %d / 轨迹 %d   (写操作只落该场景目录; 在役场景只读)%s"
                   % (cmb.currentText(), "" if sid else "  ⚠️只读",
                      len(view.data["objects"]), len(view.data["markers"]),
                      len(view.data["fences"]), len(view.data["trajectories"]), _epi_info))

    cmb.currentIndexChanged.connect(lambda _i: _switch())
    kc.currentIndexChanged.connect(lambda *_: (setattr(view, "kind_filter", kc.currentData()), _repop()))

    def _cur():
        return view._item(view.sel), (view.sel or {})

    def _full(on):
        panel.setVisible(not on)
        st.setText("3D 视图已全屏 (拖视图与面板之间的分隔条可再调比例)" if on else "已还原: 3D 视图 + 元素面板")

    top = QHBoxLayout()
    top.addWidget(QLabel("场景:"))
    top.addWidget(cmb, 3)
    b_run = _b("▶ 运行仿真", "运行该场景 (画布 3D 视图同源的引擎入口)", lambda: _run_sim(), "#3fb950")
    b_run.setEnabled(False)
    top.addWidget(b_run)

    def _bump_seed():
        """🎲 换布局: 改 episode 场景的 seed (metaworld 随机化布局的唯一真旋钮) → 立刻重跑出新的同源对。"""
        _S = _sim_mod()
        _sid = (cmb.currentData() or {}).get("sid")
        if _S is None or str(_sid) != "SS-EPI-CORNER":
            st.setText("🎲 换布局 只对「与操作视频同源」的 episode 场景有效")
            return
        try:
            _cur = int((_S.load()["scenes"].get("SS-EPI-CORNER") or {}).get("seed", 0))
            r = _S.set_seed(_cur + 1)
        except Exception as e:                                                  # noqa: BLE001
            st.setText("⛔ 换 seed 失败: %r" % e)
            return
        st.setText("🎲 %s\n   正在重跑 episode (新布局)… 日志在下面刷新" % r["msg"])
        _run_sim()

    def _cam_corner2():
        """🎥 切到 corner2 机位 (与操作视频/3D场景窗口同一相机)。"""
        if view.apply_corner2_view():
            try:
                import sim_scene_def as _S
                _t = _S.episode_truth()
                st.setText("🎥 已切到 corner2 视角 (与操作视频/3D场景同一机位: pos=%s fovy=%s)"
                           % ([round(float(x), 2) for x in _t["cam_pos"]], _t.get("cam_fovy")))
            except Exception:                                                   # noqa: BLE001
                st.setText("🎥 已切到 corner2 视角 (与操作视频同一机位)")
        else:
            st.setText("⛔ 取 corner2 外参失败 (episode 真值不可用)")

    b_cam = _b("🎥 corner2 视角", "切到操作视频/3D 分层视图的同一机位 (cad 外参取自 episode 真值)",
               lambda: _cam_corner2(), "#00d4aa")
    b_cam.setVisible(False)
    top.addWidget(b_cam)
    b_seed = _b("🎲 换布局 (seed+1)", "改 metaworld 随机化布局的 seed 并立刻重跑 episode (点了必出结果)",
                lambda: _bump_seed(), "#d29922")
    b_seed.setVisible(False)
    top.addWidget(b_seed)
    top.addWidget(_b("🔄 刷新", "重读场景真源并重绘", lambda: (view.reload(), _repop()), "#9aa7b4"))
    def _popout():
        """🗗 独立窗口: 把当前场景放进一个独立大窗口 (可最大化/拖边沿) — 老倪: 「窗口还是太小, 变大一些」"""
        _d = cmb.currentData() or {}
        _po = getattr(card, "_pop", None)
        if _po is None or not _po.isVisible():
            _po = QDialog(card.window())
            _po.setWindowTitle("🧭 场景编辑器 · 独立窗口")
            _po.setSizeGripEnabled(True)
            _lay = QVBoxLayout(_po)
            _lay.setContentsMargins(4, 4, 4, 4)
            _v2 = SceneView3D(_d.get("dir"), _d.get("sid"),
                              status_cb=lambda m: (st.setText(str(m)), None)[1])
            _v2.setMinimumHeight(700)
            _lay.addWidget(_v2)
            card._pop, card._popview = _po, _v2
            _po.resize(1600, 1050)
            _po.showMaximized()          # 直接超大: 老倪要的"变大"
        else:
            _po.raise_()
            _po.activateWindow()
        card._popview.kind_filter = kc.currentData()
        card._popview.set_scene(_d.get("dir"), _d.get("sid"))
        card._popview.reload()
        if getattr(card, "_pop", None) is not None:
            card._pop.setWindowTitle("🧭 场景编辑器 · 独立窗口 — %s%s"
                                     % (_d.get("sid") or "在役只读", "  (只读)" if not _d.get("sid") else ""))
        st.setText("🗗 已在独立窗口打开当前场景 (可最大化/拖边沿放大; 编辑同样写真源)")

    top.addWidget(_b("🗗 独立窗口", "把当前场景放进独立窗口 (可最大化, 比页内大得多)",
                     lambda: _popout(), "#00d4aa"))
    top.addWidget(_b("⛶ 视图全屏", "隐藏元素面板, 3D 视图占满整页", lambda: _full(True), "#00d4aa"))
    top.addWidget(_b("⤡ 还原", "恢复 3D 视图 + 元素面板", lambda: _full(False), "#9aa7b4"))
    top.addWidget(_b("⤢ 自适应", "整场自动取景, 撑满视口", lambda: view.fit_view(), "#00d4aa"))
    top.addWidget(_b("⌂ 复位视角", "等轴视角 + 自动取景", lambda: view.view(35, 32), "#9aa7b4"))
    top.addWidget(_b("⬇ 俯视", "俯视图 (看工位布局)", lambda: view.view(0, 89), "#9aa7b4"))
    top.addWidget(_b("➖", "缩小", lambda: (setattr(view, "scale", max(60.0, view.scale / 1.25)),
                                        setattr(view, "_manual_scale", True), view.update()), "#9aa7b4"))
    top.addWidget(_b("➕", "放大", lambda: (setattr(view, "scale", min(9000.0, view.scale * 1.25)),
                                        setattr(view, "_manual_scale", True), view.update()), "#9aa7b4"))
    if parent is not None:
        def _open_gl():
            try:
                m = getattr(parent.parent(), "canvas_page", None) or getattr(parent, "canvas_page", None)
                if m is not None and hasattr(m, "open_ss_3d"):
                    m.open_ss_3d(on_top=True)
                    st.setText("已打开真 GL 3D 视图 (仿真轨迹, 同一份场景真源)")
                else:
                    st.setText("画布模块未就绪: 先打开 Simulink 页再试")
            except Exception as e:                                             # noqa: BLE001
                st.setText("打开 GL 3D 视图失败: %r" % (e,))
        top.addWidget(_b("🖥 真 GL 3D 视图", "画布那条单例 GL 3D 窗口 (仿真轨迹)", _open_gl, "#8b6cf0"))
    v.addLayout(top)

    r2 = QHBoxLayout()
    r2.addWidget(QLabel("可编辑类型:"))
    kc.addItem("全部类型", None)
    for k in KINDS:
        kc.addItem(KIND_CN[k], k)
    r2.addWidget(kc, 2)
    r2.addWidget(QLabel("元素:"))
    r2.addWidget(lst, 5)
    pl.addLayout(r2)

    def _run_sim():
        """▶ 运行场景: 真起子进程跑入口, 日志实时回吐, 完了报产物+时间 (老倪要看真跑)。"""
        _sid = (cmb.currentData() or {}).get("sid")
        run = (cmb.currentData() or {}).get("run")
        if not run:
            st.setText("该场景没有运行入口 (只有仿真场景可运行: 如 SIM-PEG-L4 插拔光模块)")
            return
        tool = str(run.get("tool") or "")
        args = [str(a) for a in (run.get("args") or [])]
        script = os.path.join(ROOT, tool)
        if not tool or not os.path.exists(script):
            st.setText("⛔ 运行入口不存在: %s" % tool)
            return
        # 与画布 L4 档同一条调用 (cwd=tools + MUJOCO_GL=egl/MUJOCO_EGL_DEVICE=0, 否则 headless 渲染起不来)
        _S = _sim_mod()
        _cwd, _env = os.path.dirname(script), {}
        if _S is not None:
            try:
                _t, _a, _eta, _prod, _cwd, _env = _S.run_cmd(_sid)
            except Exception:                                                  # noqa: BLE001
                pass
        _env = {**os.environ, **(_env or {})}
        b_run.setEnabled(False)
        _tail = []
        if getattr(card, "_th", None) is not None and card._th.isRunning():
            st.setText("⛔ 上一次运行还没结束 (等待或重启控制台)")
            b_run.setEnabled(True)
            return
        st.setText("▶ 正在运行 %s %s … (约 %ss; 日志实时刷新)" % (tool, " ".join(str(a) for a in args), run.get("eta_s")))
        th = RunThread([sys.executable, script] + args, _cwd, env=_env)
        card._th = th

        def _on_line(t):
            _tail.append(t)
            del _tail[:-40]
            st.setText("▶ 运行中 …" + chr(10) + chr(10).join(_tail[-6:]))

        def _on_done(rc):
            b_run.setEnabled(True)
            extra = ""
            prod = run.get("product")
            if prod:
                p = os.path.join(ROOT, prod)
                if os.path.exists(p):
                    extra = "  产物 %s (%.1f MB · 更新于 %s)" % (
                        prod, os.path.getsize(p) / 1e6, time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(p))))
            st.setText(("✅ 运行完成 (rc=%d)%s\n" % (rc, extra)) + "\n".join(_tail[-6:]))

        th.line.connect(_on_line)
        th.done.connect(_on_done)
        th.start()

    def _edit():
        it, s = _cur()
        if not it:
            st.setText("先在 3D 视图或元素列表里点选一个元素")
            return
        D = ElementDialog(view.data, s, card)
        if D.exec_() == QDialog.Accepted:
            view._write(D.payload(), "改数值 %s" % str(ent_id(it, s["kind"]))[:22], s["kind"])
            _repop()

    def _toggle():
        it, s = _cur()
        if not it or s.get("kind") != "objects":
            st.setText("显隐只作用于对象: 先选一个对象")
            return
        if not view.scene_id:
            st.setText("⛔ 在役现场场景只读")
            return
        ok, d = _se(view.scene_id, "hide", "--kind", "objects", "--id", str(ent_id(it, "objects")))
        if not ok:
            ok, d = _se(view.scene_id, "hide", "--kind", "objects", "--name", str(it.get("name")))
        st.setText(("✅ 显隐切换 %s" % str(it.get("name"))[:26]) if ok else ("⛔ 显隐失败: %s" % (d.get("msg") or "")))
        view.reload()
        _repop()

    def _template(kind):
        c = list(getattr(view, "center", [0.6, 0.35, 0.15]))
        if kind == "objects":
            return {"name": "新对象", "center": [round(c[0], 5), round(c[1], 5), 0.15],
                    "size": [80.0, 80.0, 40.0], "source": "场景编辑器新增"}
        if kind == "markers":
            return {"name": "新标记", "type": "工位", "pos": [round(c[0], 5), round(c[1], 5), 0.15], "radius_m": 0.05}
        if kind == "fences":
            return {"name": "新围栏", "kind": "box", "enabled": True,
                    "shape": {"center": [round(c[0], 5), round(c[1], 5), 0.2], "size": [0.4, 0.4, 0.4]}}
        return {"name": "新轨迹", "kind": "自定义",
                "waypoints": [[round(c[0], 5), round(c[1], 5), 0.15],
                              [round(c[0] + 0.1, 5), round(c[1], 5), 0.15]]}

    def _add():
        if not view.scene_id:
            st.setText("⛔ 在役现场场景只读: 先在上方场景下拉里选命名场景")
            return
        k = kc.currentData() or "objects"
        nm, ok = QInputDialog.getText(card, "新增%s" % KIND_CN[k], "%s名称:" % KIND_CN[k])
        if not (ok and nm.strip()):
            return
        pl_ = _template(k)
        pl_["name"] = nm.strip()
        _S = _sim_mod()
        if _S is not None and _S.is_sim_scene(view.scene_id):
            r = _S.add_item(k, pl_, scene_id=view.scene_id)
            st.setText(("✅ 已新增%s %s (写仿真场景真源)" % (KIND_CN[k], nm.strip()))
                       if r.get("ok") else ("⛔ 新增失败: %s" % r.get("msg")))
            view.reload()
            _repop()
            return
        ok2, d = _se(view.scene_id, "add", "--kind", k, "--data", json.dumps(pl_, ensure_ascii=False))
        st.setText(("✅ 已新增%s %s (回读一致)" % (KIND_CN[k], nm.strip()))
                   if (ok2 and (d.get("readback") or d.get("readback_ok")))
                   else ("⛔ 新增失败: %s" % (d.get("msg") or "")))
        view.reload()
        _repop()

    def _dup():
        it, s = _cur()
        if not it or not view.scene_id:
            st.setText("先选一个元素 (且当前场景可编辑)")
            return
        k = s["kind"]
        pl_ = {kk: vv for kk, vv in it.items() if kk != "id"}
        pl_["name"] = "%s 副本" % str(it.get("name"))[:24]
        for key in ("center", "pos"):
            if isinstance(pl_.get(key), list):
                pl_[key] = [round(pl_[key][0] + 0.05, 5)] + list(pl_[key][1:])
        if k == "fences" and isinstance(pl_.get("shape"), dict):
            c = list(pl_["shape"].get("center") or [0, 0, 0])
            sh = dict(pl_["shape"])
            sh["center"] = [round(c[0] + 0.05, 5)] + c[1:]
            pl_["shape"] = sh
        if k == "trajectories" and pl_.get("waypoints"):
            pl_["waypoints"] = [[round(w[0] + 0.05, 5)] + list(w[1:]) for w in pl_["waypoints"]]
        ok2, d = _se(view.scene_id, "add", "--kind", k, "--data", json.dumps(pl_, ensure_ascii=False))
        st.setText(("✅ 已复制 %s" % pl_["name"][:24]) if ok2 else ("⛔ 复制失败: %s" % (d.get("msg") or "")))
        view.reload()
        _repop()

    def _del():
        it, s = _cur()
        if not it:
            st.setText("先选一个元素")
            return
        if not view.scene_id:
            st.setText("⛔ 在役现场场景只读")
            return
        k = s["kind"]
        _S = _sim_mod()
        if _S is not None and _S.is_sim_scene(view.scene_id):
            r = _S.del_item(k, str(ent_id(it, k)), scene_id=view.scene_id)
            st.setText(("✅ 已删除%s %s (写仿真场景真源)" % (KIND_CN[k], str(it.get("name"))[:24]))
                       if r.get("ok") else ("⛔ 删除失败: %s" % r.get("msg")))
            view.reload()
            _repop()
            return
        ok, d = _se(view.scene_id, "rm", "--kind", k, "--id", str(ent_id(it, k)))
        st.setText(("✅ 已删除%s %s (备份在场景目录)" % (KIND_CN[k], str(it.get("name"))[:24])) if ok
                   else ("⛔ 删除失败: %s" % (d.get("msg") or "")))
        view.reload()
        _repop()

    r3 = QHBoxLayout()
    for b in (_b("✏️ 编辑选中", "改位置/尺寸/航点 (视图里双击元素也行)", _edit),
              _b("👁 显隐(对象)", "隐藏/显示选中对象 (deleted 黑名单)", _toggle, "#ffc857"),
              _b("➕ 新增", "在当前场景新增该类元素", _add, "#00d4aa"),
              _b("📄 复制选中", "以选中元素为模板新增 (偏移 50mm)", _dup, "#8b6cf0"),
              _b("🗑 删除选中", "删除选中元素 (scene_edit 有备份)", _del, "#e05561")):
        r3.addWidget(b)
    r3.addStretch(1)
    pl.addLayout(r3)
    tip = QLabel("元素列表 ↔ 3D 视图 双向联动 · 3D 里拖动=改位置(轨迹=拖单个航点方块) · 双击=改数值 · "
                 "拖视图中缝的分隔条 = 放大/缩小视图")
    tip.setStyleSheet("color:#7d8590; font-size:11px;")
    tip.setWordWrap(True)
    pl.addWidget(tip)

    split = QSplitter(Qt.Vertical)
    split.addWidget(view)
    split.addWidget(panel)
    split.setStretchFactor(0, 8)
    split.setStretchFactor(1, 1)
    split.setChildrenCollapsible(False)
    split.setHandleWidth(9)
    split.setStyleSheet("QSplitter::handle{background:#30363d;}"
                        "QSplitter::handle:hover{background:#00d4aa;}")
    card.splitter = split
    card.panel = panel
    v.addWidget(split, 1)
    v.addWidget(st)

    _repop()
    _switch()
    return card
