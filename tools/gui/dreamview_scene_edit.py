#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dreamview_scene_edit.py — 给已打开的 DreamView3D **动态挂上「场景编辑」能力** (2026-10-10 老倪)

老倪原话: 「simulink 画布的 3D 视图，就是一个渲染出来的仿真插拔场景，你要管理和编辑这个场景」。

口径 (硬约束):
  · **不改 ss_dreamview.py / studio.py / simulink_module.py** —— 本文件只做动态挂载 (monkey-patch):
    给 DreamView3D 实例装一个侧边小面板 + 右键菜单 + 一层「场景对象叠加」GL 子层, 全在本文件里。
  · **幂等**: attach_scene_edit(dv) 重复调用返回同一个挂载器, 不重复加面板/图层/菜单。
  · 所有写操作**一律经 tools/scene_edit.py** (备份/原子写/回读/回滚), 本文件不自己写 JSON。
  · 编辑对话框**复用** sim_real_page._EditDialog (不另起第四套表单)。
  · 成功写后**真刷新** 3D 视图里该对象的位置/大小 —— 由本文件挂的叠加层重建实现 (真实可见);
    若刷新做不到就显式提示「需要重开视图」, 绝不假装已刷新。

用法 (由主节点接线):
    from dreamview_scene_edit import attach_scene_edit
    dv = DreamView3D(tr)          # 已打开的 3D 视图
    att = attach_scene_edit(dv)   # 挂上场景编辑 (幂等)
    att.refresh_list(); att.refresh_overlay()
"""
from __future__ import annotations

import json
import os
import sys

from PyQt5.QtCore import Qt, QEvent, QObject
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout)

# 本文件与 ss_dreamview / sim_real_page / scene_edit 同处 tools/gui / tools 体系
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = os.path.dirname(os.path.dirname(_HERE))          # /home/ubuntu/zmax
SCENE_DIR = os.environ.get("ZMAX_SCENE_DIR", os.path.join(ROOT, "data", "scene"))
OBJECTS3D = os.path.join(SCENE_DIR, "objects3d.json")

_C_DEFAULT = (0.95, 0.72, 0.10, 0.55)   # 场景对象叠加默认色 (半透明金)
_C_HIDDEN = (0.45, 0.48, 0.52, 0.18)    # 隐藏态 (灰暗)

# 无头/自动化下模态对话框会阻塞 → offscreen 或显式 env 时静默 (仍写入 + 刷新)
_QUIET = (os.environ.get("ZMAX_SCENE_EDIT_QUIET") == "1"
          or os.environ.get("QT_QPA_PLATFORM") == "offscreen")


def _info(parent, title, text):
    if _QUIET:
        print("[scene-edit] %s: %s" % (title, str(text).replace("\n", " | ")))
        return
    QMessageBox.information(parent, title, text)


def _warn(parent, title, text):
    if _QUIET:
        print("[scene-edit] ⚠ %s: %s" % (title, str(text).replace("\n", " | ")))
        return
    QMessageBox.warning(parent, title, text)


# ══════════════════════ 数据层桥 (只经 scene_edit) ══════════════════════
def _se_run(*args):
    """调 tools/scene_edit.py (复用 sim_real_page._run 同一条路径; 尊重 ZMAX_SCENE_DIR)。"""
    from sim_real_page import _run
    return _run(*args)


SCENE_WHITELIST = ("SS-EPI-CORNER", "SIM-PEG-L4", "SCN-07-UP")      # 3D场景 首位 (老倪口径)


def _scene_options():
    """可选场景: 3D场景 (与操作视频同源) · 插拔场景 · 上下料场景 (+ 在役现场场景, 只读收尾)。

    老倪 2026-10-10: 「其它场景先不用搞」+「Sim&Real 改成 3D场景，就是一个程序」⇒ 这里只列 3 条,
    且 3D场景 排第一 (进页默认就是它)。
    """
    out = []
    for sid in SCENE_WHITELIST:
        d = os.path.join(ROOT, "data", "scene", "scenes", sid)
        if not os.path.isdir(d):
            continue
        label = {"SS-EPI-CORNER": "🧭 3D场景 (与操作视频同源)",
                 "SIM-PEG-L4": "🔧 插拔场景 (对齐 metaworld 真模型)",
                 "SCN-07-UP": "📦 上下料场景"}.get(sid, sid)
        n = 0
        try:
            n = len((json.load(open(os.path.join(d, "objects3d.json"), encoding="utf-8")) or {}).get("objects") or [])
        except Exception:                                                      # noqa: BLE001
            pass
        out.append(("%s   %d 对象" % (label, n), d))
    out.append(("(在役) 现场场景 (只读)", os.path.join(ROOT, "data", "scene")))
    return out


def _list_view():
    """scene_edit list --json → 场景总览 dict (objects/markers/visibility)。"""
    ok, d = _se_run("list", "--json")
    if ok and isinstance(d, dict):
        return d
    # 退路: 只读 objects3d.json (绝不写)
    try:
        with open(OBJECTS3D, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                          # noqa: BLE001
        return {}


def _objects():
    return _list_view().get("objects") or []


def _deleted_flat(view=None):
    v = view if isinstance(view, dict) else _list_view()
    vis = v.get("visibility") or {}
    return set(vis.get("deleted") or [])


def _is_hidden(name, deleted):
    return name in deleted or ("sim|%s" % name) in deleted


def _color_of(o):
    c = o.get("color")
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        return (float(c[0]), float(c[1]), float(c[2]), 0.55)
    if isinstance(c, str):
        col = QColor(c)
        if col.isValid():
            return (col.redF(), col.greenF(), col.blueF(), 0.55)
    return _C_DEFAULT


# ══════════════════════ 挂载器 ══════════════════════
class SceneEditAttacher(QObject):
    """DreamView3D 的场景编辑挂载器: 侧边面板 + 右键菜单 + 对象叠加层。"""

    def __init__(self, dreamview):
        super().__init__(dreamview)
        self.dv = dreamview
        self.panel = None
        self.overlay_items = []          # 叠加层的 GL item 列表
        self._overlay_names = {}
        self._native_rebuild = True      # 写后是否调 DreamView3D 的原生重建钩子

    # ── 安装 ──
    def install(self):
        self._build_panel()
        self.dv.view.installEventFilter(self)     # 右键菜单
        self.refresh_list()
        self.refresh_overlay()

    def _build_panel(self):
        if self.panel is not None:
            return
        p = QFrame()
        p.setFixedWidth(224)
        p.setStyleSheet("QFrame{background:#161b22; border:1px solid #30363d; border-radius:6px;}")
        v = QVBoxLayout(p)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        t = QLabel("🗂 场景编辑")
        t.setStyleSheet("color:#00d4aa; font-size:14px; font-weight:700;")
        v.addWidget(t)
        hint = QLabel("列出 objects3d.json 对象 → 选中编辑/隐藏/新增\n(写操作经 scene_edit.py · 备份+回读)")
        hint.setStyleSheet("color:#8b949e; font-size:10px;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        # 场景选择 (含「SCN-07-UP 上下料」) — 切换即对该场景目录编辑
        self.cmb_scene = QComboBox()
        for label, d in _scene_options():
            self.cmb_scene.addItem(label, d)
        # 当前 ZMAX_SCENE_DIR 若已指向某命名场景, 选中它
        _cur = os.path.abspath(SCENE_DIR)
        for i in range(self.cmb_scene.count()):
            if os.path.abspath(self.cmb_scene.itemData(i)) == _cur:
                self.cmb_scene.setCurrentIndex(i)
                break
        self.cmb_scene.setStyleSheet(
            "QComboBox{background:#0f1318; color:#e6edf3; border:1px solid #30363d; border-radius:4px;"
            " font-size:11px; padding:3px;} QComboBox QAbstractItemView{background:#0f1318; color:#e6edf3;}")
        self.cmb_scene.setToolTip("选场景后在它上面编辑 (命名场景与在役场景目录隔离, 互不影响)")
        self.cmb_scene.currentIndexChanged.connect(lambda _i: self.switch_scene())
        v.addWidget(self.cmb_scene)
        self.lst = QListWidget()
        self.lst.setStyleSheet(
            "QListWidget{background:#0f1318; color:#e6edf3; border:1px solid #30363d;"
            " border-radius:6px; font-size:12px;}")
        self.lst.itemDoubleClicked.connect(lambda _i: self.edit_selected())
        v.addWidget(self.lst, 1)

        def _b(txt, tip, fn, col):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setStyleSheet(
                "QPushButton{background:#1f2733; color:%s; border:1px solid #2a3441;"
                " border-radius:4px; padding:4px 6px; font-size:11px;}"
                "QPushButton:hover{border-color:%s;}" % (col, col))
            b.clicked.connect(fn)
            return b

        row1 = QHBoxLayout(); row1.setSpacing(4)
        row1.addWidget(_b("✏️ 编辑", "编辑选中对象 (复用 _EditDialog)", self.edit_selected, "#4da3ff"))
        row1.addWidget(_b("👁 显隐", "隐藏/显示选中对象 (deleted 黑名单)", self.toggle_selected, "#ffc857"))
        v.addLayout(row1)
        row2 = QHBoxLayout(); row2.setSpacing(4)
        row2.addWidget(_b("➕ 新增", "新增场景对象", self.add_object, "#00d4aa"))
        row2.addWidget(_b("🔄 刷新", "重读真源 + 重建叠加层", self.reload, "#9aa7b4"))
        v.addLayout(row2)
        v.addWidget(_b("🔁 重建 3D 视图", "调 DreamView3D 原生重建钩子 (若提供)", self.rebuild_view, "#9aa7b4"))

        self.status = QLabel("—")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "color:#c9d1d9; font-size:10px; background:#0d1117;"
            " border:1px solid #30363d; border-radius:4px; padding:4px;")
        v.addWidget(self.status)

        # 插入到主布局: 原「图层面板」之后 (index 1), 不动原面板
        try:
            lay = self.dv.layout()
            if lay is not None:
                lay.insertWidget(1, p)
            else:
                p.setParent(self.dv)
        except Exception:                                                      # noqa: BLE001
            p.setParent(self.dv)
        self.panel = p

    # ── 列表 ──
    def refresh_list(self):
        view = _list_view()
        objs = view.get("objects") or []
        deleted = _deleted_flat(view)
        keep = self.selected_name()          # 保留当前选中 (reload 后不丢选中)
        self.lst.clear()
        for o in objs:
            name = o.get("name")
            c = o.get("center") or []
            hid = _is_hidden(name, deleted)
            it = QListWidgetItem("%s%s   %s" % ("👁 " if not hid else "🕶 ", name,
                                                [round(x, 3) for x in c] if c else ""))
            it.setData(Qt.UserRole, name)
            if hid:
                it.setForeground(QColor("#6e7b8a"))
            self.lst.addItem(it)
        if keep is not None:
            for i in range(self.lst.count()):
                if self.lst.item(i).data(Qt.UserRole) == keep:
                    self.lst.setCurrentRow(i)
                    break
        self._set_status("对象 %d 个 (隐藏 %d) · 真源 %s"
                         % (len(objs), sum(1 for o in objs if _is_hidden(o.get("name"), deleted)),
                            OBJECTS3D))

    def switch_scene(self):
        """切到下拉选中的场景目录 (设 ZMAX_SCENE_DIR ⇒ 后续 scene_edit 调用都作用于该目录)。"""
        d = self.cmb_scene.currentData()
        if not d:
            return
        os.environ["ZMAX_SCENE_DIR"] = d
        globals()["SCENE_DIR"] = d
        name = self.cmb_scene.currentText()
        self._set_status("已切到场景: %s\n目录: %s\n(写操作只影响该目录; 在役场景不动)" % (name, d))
        try:
            self.refresh_list()
            self.refresh_overlay()
        except Exception as e:                                                  # noqa: BLE001
            self._set_status("切换后刷新失败: %s" % e)

    def selected_name(self):
        it = self.lst.currentItem()
        return it.data(Qt.UserRole) if it is not None else None

    def _set_status(self, txt):
        try:
            self.status.setText(txt)
        except Exception:                                                      # noqa: BLE001
            pass

    # ── 叠加层 (真实刷新目标) ──
    def _remove_overlay(self):
        for it in self.overlay_items:
            try:
                self.dv.view.removeItem(it)
            except Exception:                                                  # noqa: BLE001
                pass
        self.overlay_items = []
        self._overlay_names = {}

    def refresh_overlay(self):
        """按 objects3d.json 重建 3D 叠加盒 (位置/大小真值) — 这就是"编辑后刷新 3D 里该对象"的机制。"""
        self._remove_overlay()
        try:
            import numpy as np
            import pyqtgraph.opengl as gl
            from ss_dreamview import _box_mesh
        except Exception as e:                                                 # noqa: BLE001
            self._set_status("叠加层不可用 (缺 pyqtgraph/ss_dreamview): %s" % e)
            return 0
        view = _list_view()
        deleted = _deleted_flat(view)
        n = 0
        for o in view.get("objects") or []:
            name = o.get("name")
            center = o.get("center")
            size = o.get("size")
            if not (isinstance(center, list) and len(center) == 3
                    and isinstance(size, list) and len(size) == 3):
                continue
            hid = _is_hidden(name, deleted)
            col = _C_HIDDEN if hid else _color_of(o)
            cz = [float(x) for x in center]
            sz = [float(x) / 1000.0 for x in size]          # mm → m
            try:
                mesh = _box_mesh(cz, sz)
                item = gl.GLMeshItem(meshdata=mesh, color=col, smooth=False,
                                     shader='shaded' if not hid else None, drawEdges=True,
                                     edgeColor=(0.9, 0.9, 0.95, 0.5 if not hid else 0.12))
                item.setGLOptions("translucent")
                self.dv.view.addItem(item)
                self.overlay_items.append(item)
                self._overlay_names[name] = item
                n += 1
            except Exception:                                                  # noqa: BLE001
                pass
        try:
            self.dv.view.update()
        except Exception:                                                      # noqa: BLE001
            pass
        return n

    def rebuild_view(self):
        """调 DreamView3D 的原生重建钩子 (若提供): _build_scene()。"""
        fn = getattr(self.dv, "_build_scene", None)
        if callable(fn):
            try:
                fn()
                self._set_status("✓ 已调 DreamView3D._build_scene() 原生重建")
                return True
            except Exception as e:                                             # noqa: BLE001
                self._set_status("原生重建失败: %s" % e)
                return False
        self._set_status("DreamView3D 无重建钩子 → 需重开视图")
        return False

    # ── 写后刷新 (真刷新, 不假装) ──
    def refresh_after_write(self, obj_name):
        """写成功后的刷新:
          ① 重建叠加层 → 3D 里该对象的位置/大小**真实更新** (可见);
          ② 若 DreamView3D 提供原生重建钩子则一并调用 (但它不绘制 objects3d 对象)。"""
        n = self.refresh_overlay()
        self.refresh_list()
        rebuild = "已调 _build_scene()" if self._native_rebuild and self.rebuild_view() \
            else "原生几何不含 objects3d 对象(固定仿真场景)"
        if obj_name in self._overlay_names:
            self._set_status("✓ 已刷新 3D 叠加层: %s 位置/大小已更新 (%d 盒)\n"
                             "   %s" % (obj_name, n, rebuild))
            return {"refreshed": True, "in_view": True, "n_boxes": n}
        self._set_status("⚠ 已写入真源; 但 %s 未出现在 3D 叠加层 "
                         "(对象表无有效 center/size) — 需重开视图" % obj_name)
        return {"refreshed": False, "in_view": False, "n_boxes": n}

    # ── 动作 ──
    def reload(self):
        self.refresh_list()
        self.refresh_overlay()

    def edit_selected(self):
        name = self.selected_name()
        if not name:
            _info(self.panel, "先选一行", "请先选中要编辑的对象")
            return
        cur = next((o for o in _objects() if o.get("name") == name), None)
        if cur is None:
            _warn(self.panel, "找不到对象", "真源里找不到 %s" % name)
            return
        from sim_real_page import _EditDialog          # 复用 (不另起表单)
        dlg = _EditDialog("objects", cur, self.panel)
        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            payload = dlg.payload()
        except Exception as e:                                                 # noqa: BLE001
            _warn(self.panel, "输入有误", "字段解析失败: %s" % e)
            return
        self.apply_object_update(name, payload)

    def add_object(self):
        from sim_real_page import _EditDialog
        dlg = _EditDialog("objects", None, self.panel)
        if dlg.exec_() != QDialog.Accepted:
            return
        try:
            payload = dlg.payload()
        except Exception as e:                                                 # noqa: BLE001
            _warn(self.panel, "输入有误", "字段解析失败: %s" % e)
            return
        ok, res = self.apply_object_add(payload)
        self._after(ok, res, "新增", payload.get("name"))

    def apply_object_add(self, payload):
        """走 scene_edit.py add 真写; 成功后刷新叠加层。返回 (ok, payload)。"""
        ok, res = _se_run("add", "--kind", "objects",
                          "--data", json.dumps(payload, ensure_ascii=False), "--json")
        if ok:
            self.refresh_after_write(payload.get("name"))
        return ok, res

    def toggle_selected(self):
        name = self.selected_name()
        if not name:
            return
        deleted = _deleted_flat()
        verb = "show" if _is_hidden(name, deleted) else "hide"
        ok, res = _se_run(verb, "--kind", "objects", "--name", name, "--json")
        self._after(ok, res, "显隐", name, refresh_only=True)

    # ── 核心写路径: update --kind objects --id <name> --data ... --json ──
    def apply_object_update(self, name, data):
        """走 scene_edit.py update 真写; 成功后刷新 3D 视图里该对象。返回 (ok, payload)。"""
        ok, res = _se_run("update", "--kind", "objects", "--id", name,
                          "--data", json.dumps(data, ensure_ascii=False), "--json")
        refresh = None
        if ok:
            refresh = self.refresh_after_write(name)
        self._after(ok, res, "编辑", name, refresh=refresh)
        return ok, res

    def _after(self, ok, res, what, name=None, refresh=None, refresh_only=False):
        if ok:
            if refresh is None and name is not None:
                refresh = self.refresh_after_write(name) if not refresh_only else None
            msg = "已写入真源 (备份+原子写+回读核对)。"
            if isinstance(refresh, dict):
                msg += "\n3D 叠加层: %s" % ("✓ 该对象位置/大小已刷新" if refresh.get("in_view")
                                            else "⚠ 未刷新, 需重开视图")
            _info(self.panel, "%s 成功" % what, msg)
        else:
            _warn(self.panel, "%s 失败" % what, str(res)[:500])
        self.reload()

    # ── 右键菜单 ──
    def eventFilter(self, obj, ev):
        try:
            if obj is self.dv.view and ev.type() == QEvent.ContextMenu:
                self._context_menu(ev)
                return True
        except Exception:                                                      # noqa: BLE001
            pass
        return super().eventFilter(obj, ev)

    def _context_menu(self, ev):
        m = QMenu(self.dv.view)
        head = m.addAction("🗂 场景编辑 — 选中对象:")
        head.setEnabled(False)
        view = _list_view()
        deleted = _deleted_flat(view)
        sel = self.selected_name()
        menu = {}
        for o in view.get("objects") or []:
            name = o.get("name")
            a = m.addAction("%s%s" % ("🕶 " if _is_hidden(name, deleted) else "👁 ", name))
            a.setCheckable(True)
            a.setChecked(name == sel)
            menu[a] = name
        m.addSeparator()
        act_refresh = m.addAction("🔄 刷新 (重读真源 + 重建叠加层)")
        act_add = m.addAction("➕ 新增对象")
        gp = ev.globalPos()
        chosen = m.exec_(gp)
        if chosen is None:
            return
        if chosen is act_refresh:
            self.reload()
        elif chosen is act_add:
            self.add_object()
        elif chosen in menu:
            name = menu[chosen]
            # 选中并高亮
            for i in range(self.lst.count()):
                if self.lst.item(i).data(Qt.UserRole) == name:
                    self.lst.setCurrentRow(i)
                    break
            self.edit_selected()


# ══════════════════════ 对外: 幂等挂载 ══════════════════════
def attach_scene_edit(dreamview):
    """给已打开的 DreamView3D 挂上场景编辑能力 (幂等: 重复调用返回同一挂载器)。"""
    if dreamview is None:
        raise ValueError("attach_scene_edit: dreamview 为 None")
    exist = getattr(dreamview, "_scene_edit_attacher", None)
    if exist is not None:
        try:
            # 类型/鸭子检查: 面板还在就用; 否则重建
            if getattr(exist, "panel", None) is not None:
                return exist
        except Exception:                                                      # noqa: BLE001
            pass
    att = SceneEditAttacher(dreamview)
    att.install()
    dreamview._scene_edit_attacher = att
    # 方便调用方: dv.scene_edit_refresh()
    try:
        dreamview.scene_edit_refresh = att.refresh_after_write
        dreamview.scene_edit = att
    except Exception:                                                          # noqa: BLE001
        pass
    return att


def build_embedded(parent=None, scene_id="SS-EPI-CORNER"):
    """Sim&Real 页主视图 = **真的 DreamView3D** —— 与画布「🧭 3D 视图」/独立「3D场景」窗口同一个程序。

    老倪 2026-10-10: 「sim real场景的页面，与 3D场景的页面不一样，要改成一模一样，就是同一个东西」
    ⇒ 不再用 QPainter 仿画一个, 而是把**同一个 DreamView3D 实例**嵌进页里 (同一个 GL 上下文, 同一套图层),
      并把场景编辑能力 (侧边面板 + 右键菜单 + 对象叠加层) 挂在它身上。
    """
    import ss_dreamview as DV
    from PyQt5.QtWidgets import QWidget

    d = os.path.join(ROOT, "data", "scene", "scenes", scene_id)
    if os.path.isdir(d):                       # 默认就对着 3D场景 那条编辑
        os.environ["ZMAX_SCENE_DIR"] = d
        globals()["SCENE_DIR"] = d
        globals()["OBJECTS3D"] = os.path.join(d, "objects3d.json")

    card = QWidget(parent)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)

    tr, meta = DV.load_episode()
    dv = DV.get_or_create_dreamview(tr=tr, meta=meta, parent=card)
    dv.setParent(card)
    dv.setWindowFlags(Qt.Widget)               # 内嵌: 去掉顶层窗口标志
    dv.setWindowTitle("3D场景")
    lay.addWidget(dv, 1)

    att = attach_scene_edit(dv)

    bar = QHBoxLayout()
    bar.setSpacing(6)

    def _mk(txt, tip, fn, col="#00d4aa"):
        b = QPushButton(txt)
        b.setToolTip(tip)
        b.setStyleSheet("QPushButton{background:#1f2733; color:%s; border:1px solid #2a3441;"
                        " border-radius:4px; padding:4px 10px; font-size:12px;}"
                        "QPushButton:hover{border-color:%s;}" % (col, col))
        b.clicked.connect(lambda: fn())
        return b

    def _detach():
        """把这块视图拎出来做独立窗口 (还是同一个实例/同一个 GL 上下文, 不是新开)。"""
        try:
            dv.setParent(None)
            dv.setWindowFlags(Qt.Window)
            dv.setWindowTitle("3D场景")
            dv.resize(1300, 900)
            dv.show()
        except Exception as e:                                                  # noqa: BLE001
            pass
        att._set_status("已拎出为独立窗口 (同一个视图实例)")

    bar.addWidget(_mk("🗗 独立窗口", "把这块 3D 视图拎成独立窗口 (同一个实例)", _detach))
    bar.addWidget(_mk("🔄 刷新", "重读真源 + 重建对象叠加层", lambda: (att.refresh_list(),
                                                                      att.refresh_overlay()), "#9aa7b4"))
    bar.addWidget(_mk("🔁 重建 3D", "调 DreamView3D 原生重建 (场景变体/图元变了时用)", lambda: att.rebuild_view(),
                      "#9aa7b4"))
    bar.addStretch(1)
    lay.insertLayout(0, bar)
    try:
        att.refresh_list()
        att.refresh_overlay()
    except Exception:                                                           # noqa: BLE001
        pass
    card.attacher = att
    card.dreamview = dv
    return card
