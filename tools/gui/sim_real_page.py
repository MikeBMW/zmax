#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim_real_page.py —— 「Sim&Real · 仿真与真机场景」页的真实内容 (2026-10-10 老倪)。

老倪原话: 「场景的插拔场景，现在的显示功能不对，要能够编辑真实的已经在运行的仿真场景和真机场景；
          simulink 画布的 3D 视图，就是一个渲染出来的仿真插拔场景，你要管理和编辑这个场景；
          也要能够通过建图，VR，AR 等虚拟现实技术，给真实的现场环境添加标记，同步地图等，
          可以人工添加自定义轨迹，保护围栏等。」

设计: 页面 = 真源文件上的**编辑器** (不是说明页)。数据层 = tools/scene_edit.py (读写 data/scene/*.json,
      带备份/原子写/回读/围栏校验)。本模块只管 UI: 四张表 (对象/标记/围栏/轨迹) + 增删改 + 显示隐藏
      + 真源路径与条数 (带采集时间) + 修改后提示"运行中的仿真/AR 叠加会立即读到"。

口径: 一律经过 scene_edit.py, 不自己写 JSON (单一写路径, 免得两处逻辑打架)。
"""
import json
import os
import subprocess
import sys
import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                             QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
PY = PY if os.path.exists(PY) else sys.executable
TOOL = "tools/scene_edit.py"

C_BG2, C_BORDER, C_GRAY, C_DIM = "#131823", "#2a3441", "#9aa7b4", "#6e7b8a"
C_WHITE, C_GREEN, C_RED, C_GOLD, C_BLUE = "#e6edf3", "#00d4aa", "#ff6b6b", "#ffc857", "#4da3ff"

KINDS = [("objects", "🗺 场景对象", ["name", "center", "size", "coord", "note"]),
         ("markers", "📍 现场标记 (AR/VR)", ["name", "type", "pos", "desc"]),
         ("fences", "🛡 保护围栏", ["name", "kind", "shape", "enabled", "desc"]),
         ("trajectories", "➰ 自定义轨迹", ["name", "kind", "waypoints", "speed_hint", "desc"])]

# 新建/编辑对话框的字段定义: (键, 中文, 类型)
FIELDS = {
    "objects": [("name", "名称", "s"), ("center", "中心 x,y,z (m)", "v3"), ("size", "尺寸 x,y,z (mm)", "v3"),
                ("coord", "坐标系", "s"), ("color", "颜色(可选)", "s"), ("note", "备注", "s")],
    "markers": [("name", "名称", "s"), ("type", "类型", "marker_type"), ("pos", "位置 x,y,z (m)", "v3"),
                ("desc", "说明", "s")],
    "fences": [("name", "名称", "s"), ("kind", "形状", "fence_kind"), ("shape", "几何(JSON)", "json"),
               ("enabled", "启用", "b"), ("desc", "说明", "s")],
    "trajectories": [("name", "名称", "s"), ("kind", "来源", "traj_kind"), ("waypoints", "路点 [[x,y,z],…]", "json"),
                     ("speed_hint", "速度提示", "s"), ("desc", "说明", "s")],
}


def _run(*args, timeout=25):
    """调数据层 scene_edit.py, 返回 (ok, payload|err)。"""
    cmd = [PY, TOOL] + [str(a) for a in args]
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except Exception as e:                                                 # noqa: BLE001
        return False, "调用失败: %r" % e
    out = (r.stdout or "").strip()
    if "--json" in args:
        try:
            d = json.loads(out)
            return bool(d.get("ok", True)), d
        except Exception:                                                  # noqa: BLE001
            pass
    ok = (r.returncode == 0)
    return ok, (out or (r.stderr or "").strip())[-600:]


class _EditDialog(QDialog):
    """字段驱动的新建/编辑对话框 (按 kind 的 FIELDS 生成控件, 不做第四套表单)。"""

    def __init__(self, kind, data=None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle(("编辑 " if data else "新增 ") + dict((k, t) for k, t, _ in KINDS)[kind])
        self.setMinimumWidth(520)
        self._w = {}
        form = QFormLayout()
        data = data or {}
        for key, label, typ in FIELDS[kind]:
            v = data.get(key)
            if typ == "v3":
                w = QLineEdit(",".join(str(x) for x in v) if isinstance(v, (list, tuple)) else "")
                w.setPlaceholderText("逗号分隔, 例: 0.53,0.23,0.26")
            elif typ == "json":
                w = QPlainTextEdit(json.dumps(v, ensure_ascii=False, indent=1) if v is not None else "")
                w.setFixedHeight(96)
            elif typ == "b":
                w = QComboBox(); w.addItems(["true", "false"]); w.setCurrentText("true" if v in (None, True) else "false")
            elif typ in ("marker_type", "fence_kind", "traj_kind"):
                w = QComboBox()
                w.addItems({"marker_type": ["工位", "危险区", "检查点", "自定义"],
                            "fence_kind": ["box", "polygon"],
                            "traj_kind": ["自定义", "示教", "规划"]}[typ])
                if v:
                    w.setCurrentText(str(v))
            else:
                w = QLineEdit("" if v is None else str(v))
            self._w[key] = w
            form.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        box = QVBoxLayout()
        box.addLayout(form)
        box.addWidget(bb)
        self.setLayout(box)

    def payload(self):
        out = {}
        for key, _label, typ in FIELDS[self.kind]:
            w = self._w[key]
            if typ == "v3":
                txt = w.text().strip()
                if txt:
                    out[key] = [float(x) for x in txt.replace("，", ",").split(",") if x.strip()]
            elif typ == "json":
                txt = w.toPlainText().strip()
                if txt:
                    out[key] = json.loads(txt)
            elif typ == "b":
                out[key] = (w.currentText() == "true")
            else:
                txt = w.text().strip() if isinstance(w, QLineEdit) else w.currentText()
                if txt:
                    out[key] = txt
        return out


class SceneTab(QWidget):
    """一类实体 (对象/标记/围栏/轨迹) 的表格 + 工具栏。"""

    def __init__(self, kind, title, cols, parent=None):
        super().__init__(parent)
        self.kind, self.cols = kind, cols
        self._rows = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.lbl = QLabel("%s · —" % title)
        self.lbl.setStyleSheet("color:%s; font-size:13px; font-weight:600;" % C_WHITE)
        bar.addWidget(self.lbl)
        bar.addStretch()
        for txt, fn, clr in (("➕ 新增", self.add, C_GREEN), ("✏️ 编辑", self.edit, C_BLUE),
                             ("🗑 删除", self.remove, C_RED), ("👁 显示/隐藏", self.toggle, C_GOLD),
                             ("🔄 刷新", self.reload, C_GRAY)):
            b = QPushButton(txt)
            b.setStyleSheet("QPushButton{background:#1f2733; color:%s; border:1px solid %s;"
                            " border-radius:4px; padding:4px 10px; font-size:12px;}"
                            "QPushButton:hover{border-color:%s;}" % (clr, C_BORDER, clr))
            b.clicked.connect(fn)
            bar.addWidget(b)
        lay.addLayout(bar)
        self.tbl = QTableWidget(0, len(cols))
        self.tbl.setHorizontalHeaderLabels(cols)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setStyleSheet("QTableWidget{background:#0f1318; color:%s; gridline-color:#232c39;"
                               " border:1px solid %s; border-radius:8px; font-size:12px;}"
                               "QHeaderView::section{background:#1a2230; color:%s; border:none; padding:5px;}"
                               % (C_WHITE, C_BORDER, C_GRAY))
        lay.addWidget(self.tbl)

    # ── 数据 ───────────────────────────────────────────────────────────────
    def set_rows(self, rows):
        from PyQt5.QtWidgets import QTableWidgetItem
        self._rows = rows or []
        self.tbl.setRowCount(len(self._rows))
        for r, it in enumerate(self._rows):
            for c, col in enumerate(self.cols):
                v = it.get(col)
                if isinstance(v, (list, tuple)):
                    v = ",".join(("%.4g" % x) if isinstance(x, (int, float)) else str(x) for x in v)
                elif isinstance(v, dict):
                    v = json.dumps(v, ensure_ascii=False)
                self.tbl.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
        self.tbl.resizeColumnsToContents()
        self.lbl.setText("%s · %d 条" % (self.lbl.text().split(" · ")[0], len(self._rows)))

    def current(self):
        r = self.tbl.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    # ── 动作 ───────────────────────────────────────────────────────────────
    def reload(self):
        if hasattr(self.parent(), "_reload_all"):
            self.parent()._reload_all()

    def add(self):
        d = _EditDialog(self.kind, None, self)
        if d.exec_() != QDialog.Accepted:
            return
        try:
            payload = d.payload()
        except Exception as e:                                             # noqa: BLE001
            QMessageBox.warning(self, "输入有误", "字段解析失败: %s" % e); return
        ok, res = _run("add", "--kind", self.kind, "--data", json.dumps(payload, ensure_ascii=False), "--json")
        self._after(ok, res, "新增")

    def edit(self):
        cur = self.current()
        if not cur:
            QMessageBox.information(self, "先选一行", "请先选中要编辑的行"); return
        eid = cur.get("id") or cur.get("name")
        d = _EditDialog(self.kind, cur, self)
        if d.exec_() != QDialog.Accepted:
            return
        ok, res = _run("update", "--kind", self.kind, "--id", eid,
                       "--data", json.dumps(d.payload(), ensure_ascii=False), "--json")
        self._after(ok, res, "编辑")

    def remove(self):
        cur = self.current()
        if not cur:
            QMessageBox.information(self, "先选一行", "请先选中要删除的行"); return
        eid = cur.get("id") or cur.get("name")
        if QMessageBox.question(self, "确认删除", "删除 %s ?" % eid) != QMessageBox.Yes:
            return
        ok, res = _run("rm", "--kind", self.kind, "--id", eid, "--json")
        self._after(ok, res, "删除")

    def toggle(self):
        cur = self.current()
        if not cur:
            return
        name = cur.get("name") or cur.get("id")
        verb = "show" if cur.get("hidden") else "hide"
        ok, res = _run(verb, "--kind", self.kind, "--name", name, "--json")
        self._after(ok, res, "显隐")

    def _after(self, ok, res, what):
        if ok:
            QMessageBox.information(self, "%s 成功" % what,
                                    "已写入真源 (备份+回读核对)。运行中的仿真/AR 叠加会立即读到。")
        else:
            QMessageBox.warning(self, "%s 失败" % what, str(res)[:500])
        self.reload()


def build_body(parent=None):
    """返回 Sim&Real 页的内容控件 (studio.py 直接塞进 _build_shell)。"""
    body = QWidget(parent)
    bl = QVBoxLayout(body)
    bl.setSpacing(10)

    # ── 顶部: 真源 + 条数 + 采集时间 ─────────────────────────────────────────
    top = QLabel("读取中…")
    top.setWordWrap(True)
    top.setStyleSheet("background:%s; color:%s; border:1px solid %s; border-radius:8px;"
                      " padding:8px 12px; font-size:12px;" % (C_BG2, C_GRAY, C_BORDER))
    bl.addWidget(top)

    tabs = QTabWidget()
    bl.addWidget(tabs, 1)
    tabwidgets = {}
    tab_objs = []
    for kind, title, cols in KINDS:
        t = SceneTab(kind, title, cols, parent=tabs)
        tabs.addTab(t, title)
        tabwidgets[kind] = t
        tab_objs.append(t)

    # 3D 视图入口 (Simulink 画布渲染的仿真插拔场景)
    hint = QLabel("🧊 3D 视图 = Simulink 画布渲染的仿真插拔场景 —— 在「Simulink 模式」页画布上双击 3D/场景节点即可查看；"
                  "本页编辑的对象/标记/围栏/轨迹会被叠加到该视图与真机 AR 上。")
    hint.setWordWrap(True)
    hint.setStyleSheet("color:%s; font-size:12px;" % C_DIM)
    bl.addWidget(hint)

    state = {"paths": "", "at": ""}

    def reload_all():
        ok, d = _run("list", "--json")
        if not ok or not isinstance(d, dict):
            top.setText("❌ 读取场景真源失败: %s" % str(d)[:300])
            top.setStyleSheet("background:%s; color:%s; border:1px solid %s; border-radius:8px;"
                              " padding:8px 12px; font-size:12px;" % (C_BG2, C_RED, C_BORDER))
            return
        vis = d.get("visibility") or {}
        for kind in tabwidgets:
            rows = d.get(kind) or []
            if kind == "objects":
                hid = set(vis.get("deleted") or [])
                for r in rows:
                    r["hidden"] = (r.get("name") in hid) or (r.get("id") in hid)
            tabwidgets[kind].set_rows(rows)
        cnt = " · ".join("%s %d" % (t.split(" ", 1)[1][:4], len(d.get(k) or []))
                         for k, t, _c in KINDS)
        state["at"] = time.strftime("%H:%M:%S")
        top.setText("📁 真源 data/scene/{objects3d, overlay_spec, traj_display}.json · %s · "
                    "轨迹显示 %s · 采集 %s" % (cnt, "开" if vis.get("traj_show") else "关", state["at"]))
        top.setStyleSheet("background:%s; color:%s; border:1px solid %s; border-radius:8px;"
                          " padding:8px 12px; font-size:12px;" % (C_BG2, C_GREEN, C_BORDER))

    for t in tab_objs:
        t._reload_all = reload_all
    reload_all()
    body._reload_all = reload_all                     # 供外部 (页面刷新) 调用
    return body
