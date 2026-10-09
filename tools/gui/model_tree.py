#!/usr/bin/env python3
"""📚 数据字典 Model Tree — 画布数学化改造 (2026-08-12 老倪)
参考 MATLAB Workspace / 数据字典: 右侧面板树形展示画布节点参数,
可标定/调节; 数学分析: 节点→传递函数→状态空间→复数空间稳定性

视图切换 (下拉菜单):
  📚 数据字典 — 树形: 系统参数 + 节点(按行) + 参数(名=值, 双击编辑写回画布)
  ⚙️ 参数标定 — 同树形, 参数行可直接编辑 (标定)
  🧮 数学分析 — 系统传递函数/状态空间/零极点(复数平面) + 稳定性判定
"""
import os
import math
import sys
import json
import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (QWidget, QFrame, QVBoxLayout, QComboBox,
                             QTreeWidget, QTreeWidgetItem, QLabel, QInputDialog,
                             QHBoxLayout, QPushButton, QDoubleSpinBox,
                             QGroupBox, QFormLayout, QMessageBox, QTabWidget,
                             QScrollArea, QFileDialog,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QMenu, QDialog, QCheckBox, QApplication)
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QImage, QPixmap
# ══════════════════════════════════════════════════════════════════
# 🧊 2026-10-09 老倪「没有联系的全注释掉」: 原「前馈PD/PM/数学」分析内核
#   (node_transfer / series_chain / main_chain / tf_to_ss / analyze_system) 已挪出 →
#   tools/gui/_model_tree_ffpd_legacy.py (停用, 不 import; 取证见该文件头)。
#   ⇒ 依赖它们的 8 个部件 (现场标定/参数标定/性能指标/场景状态/运行汇总/工程需求/数学分析/复平面图)
#     一并停用 —— 它们读的 z700_internal/gain_schedule 在状态空间画布上是 0 处 = 与工程无实质联系。
# ══════════════════════════════════════════════════════════════════
# 🧊 2026-10-09: 8 个停用部件 (StageCalibrationWidget/PolePlacementWidget/FreeResponsePlot/
#   PoleZeroPlot/PerformanceWidget/SceneStateWidget/EngineeringReqWidget/RunSummaryWidget)
#   已挪到 tools/gui/_model_tree_ffpd_legacy.py —— 面板不再构造它们 (原位置留此注记便于复活)。


# ════════════════════════════════════════════════════════════════
# 🔌 数据总线 (CANoe Trace 风格, 2026-08-22 老倪)
# 状态空间六层节点间流动的所有接口数据, 时间顺序逐行显示:
#   时间 | 通道(模块) | 接口(信号) | 方向(▶IN/◀OUT) | 数据
# 双模: 🔁时间顺序(每次传输一行=数据流) / 📌固定格式(每接口一行, 值=最新快照)
# ════════════════════════════════════════════════════════════════
class DataBusTrace(QWidget):
    # 后台渲染完成 → 主线程弹窗 (跨线程安全: emit 自动队列投递到主线程)
    _render_done = pyqtSignal(str, float, object, object)  # camera_name, t_val, img(PIL Image), err
    _bbox_done = pyqtSignal(str, float, object, object)    # 检测框渲染

    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.module = module
        self._fix_map = {}   # 固定格式: (mod, dirn, name) -> 行号
        self._render_done.connect(self._show_render_window)
        self._bbox_done.connect(self._show_bbox_window)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # 控制条: 双模切换 + 计数
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["🔁 时间顺序", "📌 固定格式"])
        self.cmb_mode.setToolTip("时间顺序=每次传输一行(数据流); 固定格式=每接口一行(值刷新)")
        self.cmb_mode.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.cmb_mode, 1)
        self.lbl_cnt = QLabel("")
        self.lbl_cnt.setStyleSheet("color:#9aa4b2;font-size:18px;background:transparent;border:none;")
        bar.addWidget(self.lbl_cnt)
        lay.addLayout(bar)

        # CANoe Trace 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["⏱ 时间", "🔗 通道", "📋 接口", "⬅➡ 方向", "📊 数据"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.Interactive)   # 数据列可拖宽看完整向量
        self.table.setColumnWidth(4, 640)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)   # 🐛 2026-08-22 老倪: 字体17px, 行高须够否则裁字
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setWordWrap(False)
        self.table.setStyleSheet(
            "QTableWidget{background:#0d1117;color:#e6edf3;border:1px solid #30363d;"
            "gridline-color:#21262d;font-size:20px;font-family:Consolas,monospace;}"
            "QTableWidget::item{padding:2px 4px;}"
            "QTableWidget::item:selected{background:#1f6feb;color:#ffffff;}"
            "QHeaderView::section{background:#161b22;color:#9aa4b2;border:none;"
            "border-bottom:1px solid #30363d;padding:6px;font-size:18px;font-weight:bold;}")
        self.table.currentCellChanged.connect(self._on_select)
        self.table.cellClicked.connect(self._on_cell_click)   # 🔬 点击→结构化详情 (2026-08-23)
        self._struct_dlg = None
        # 🎨 右键视觉信号 → 渲染 RGB-D 图片 (2026-08-22 老倪)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self.table, 1)

    _IN_C = QColor("#58a6ff")
    _OUT_C = QColor("#3fb950")

    def _flush(self, rows, note):
        """一次性填充 rows (每行 (t, mod, name, dirn, val)) — refresh/append 复用"""
        self.table.clearSpans()
        self.table.setRowCount(len(rows))
        for r, (t, mod, name, dirn, val) in enumerate(rows):
            c0 = QTableWidgetItem(f"{t:.2f}"); c0.setData(Qt.UserRole, t)
            c0.setForeground(QColor("#9aa4b2"))
            c1 = QTableWidgetItem(mod)
            c1.setForeground(QColor("#c9d1d9"))
            c2 = QTableWidgetItem(name)
            c2.setForeground(QColor("#c9d1d9"))
            c3 = QTableWidgetItem("▶IN" if dirn == "in" else "◀OUT")
            c3.setForeground(self._IN_C if dirn == "in" else self._OUT_C)
            c4 = QTableWidgetItem(_sig_val(val))
            c4.setForeground(QColor("#e6edf3"))
            c4.setData(Qt.UserRole, val)   # 🔬 存原始向量供结构化详情
            self.table.setItem(r, 0, c0)
            self.table.setItem(r, 1, c1)
            self.table.setItem(r, 2, c2)
            self.table.setItem(r, 3, c3)
            self.table.setItem(r, 4, c4)
        self.lbl_cnt.setText(note)

    def refresh(self):
        """完整重建 (切视图时加载完整时序 / 固定格式)"""
        tr = getattr(self.module, "_ss_tr", None)
        if not tr or not tr.get("io_trace"):
            self._flush([], "")
            self.table.clearSpans()
            self.table.setRowCount(1)
            self.table.setSpan(0, 0, 1, 5)
            it = QTableWidgetItem("⚠️ 暂无数据 — 点「▶ 运行」跑一次状态空间仿真后自动出数据总线")
            it.setForeground(QColor("#9aa4b2"))
            self.table.setItem(0, 0, it)
            return
        time_order = self.cmb_mode.currentIndex() == 0
        rows = []
        if time_order:
            # 🐛 v3.4.6: io_trace 已逐帧全量 (引擎每步一帧) — 静态视图全量铺 500×60 行会卡,
            #   抽稀到 ≤150 帧 (运行中动态 feed 仍是逐帧滚动, 不受影响)
            _trc = tr["io_trace"]
            _n = len(_trc)
            _stp = max(1, _n // 150)
            _sel = _trc[::_stp]
            if _sel[-1] is not _trc[-1]:
                _sel = _sel + [_trc[-1]]
            for t, io in _sel:
                for mod, ports in io.items():
                    for dirn in ("in", "out"):
                        for name, val in ports.get(dirn, []):
                            rows.append((t, mod, name, dirn, val))
            note = (f"{len(rows)} 条接口 · {_n} 帧"
                    + (f" (抽稀显示 {len(_sel)} 帧)" if len(_sel) < _n else ""))
        else:
            t, io = tr["io_trace"][-1]
            for mod, ports in io.items():
                for dirn in ("in", "out"):
                    for name, val in ports.get(dirn, []):
                        rows.append((t, mod, name, dirn, val))
            note = f"{len(rows)} 条接口 (最新快照 t={t:.2f}s)"
        self._flush(rows, note)
        self.table.scrollToBottom()

    def begin_stream(self):
        """▶ 运行开始: 清空, 按当前模式准备动态播放 (2026-08-22 老倪)"""
        self.table.clearSpans()
        self.table.setRowCount(0)
        self._fix_map = {}
        self.lbl_cnt.setText("⏳ 等待数据流…")

    def append_snapshot(self, t, io):
        """动态追加一个快照的接口行 (时间顺序模式, 不清空) — 运行中逐帧滚动"""
        if self.cmb_mode.currentIndex() != 0:
            return   # 固定格式模式不走动态追加
        rows = []
        for mod, ports in io.items():
            for dirn in ("in", "out"):
                for name, val in ports.get(dirn, []):
                    rows.append((t, mod, name, dirn, val))
        start = self.table.rowCount()
        self.table.clearSpans()
        self.table.setRowCount(start + len(rows))
        for i, (t_, mod, name, dirn, val) in enumerate(rows):
            r = start + i
            c0 = QTableWidgetItem(f"{t_:.2f}"); c0.setData(Qt.UserRole, t_)
            c0.setForeground(QColor("#9aa4b2"))
            c1 = QTableWidgetItem(mod)
            c1.setForeground(QColor("#c9d1d9"))
            c2 = QTableWidgetItem(name)
            c2.setForeground(QColor("#c9d1d9"))
            c3 = QTableWidgetItem("▶IN" if dirn == "in" else "◀OUT")
            c3.setForeground(self._IN_C if dirn == "in" else self._OUT_C)
            c4 = QTableWidgetItem(_sig_val(val))
            c4.setForeground(QColor("#e6edf3"))
            c4.setData(Qt.UserRole, val)   # 🔬 存原始向量供结构化详情
            self.table.setItem(r, 0, c0)
            self.table.setItem(r, 1, c1)
            self.table.setItem(r, 2, c2)
            self.table.setItem(r, 3, c3)
            self.table.setItem(r, 4, c4)
        self.lbl_cnt.setText(f"{self.table.rowCount()} 条接口 · t={t:.2f}s")
        self.table.scrollToBottom()

    def update_snapshot(self, t, io):
        """固定格式: 信号固定行不变, 时间/数据实时刷新 (CANoe 固定格式显示, 2026-08-22)"""
        if self.cmb_mode.currentIndex() != 1:
            return
        # 第一次: 建立固定行 (每接口一行, 只含通道/接口/方向)
        if not self._fix_map:
            rows = []
            for mod, ports in io.items():
                for dirn in ("in", "out"):
                    for name, val in ports.get(dirn, []):
                        rows.append((mod, name, dirn))
            self.table.clearSpans()
            self.table.setRowCount(len(rows))
            for r, (mod, name, dirn) in enumerate(rows):
                c1 = QTableWidgetItem(mod)
                c1.setForeground(QColor("#c9d1d9"))
                c2 = QTableWidgetItem(name)
                c2.setForeground(QColor("#c9d1d9"))
                c3 = QTableWidgetItem("▶IN" if dirn == "in" else "◀OUT")
                c3.setForeground(self._IN_C if dirn == "in" else self._OUT_C)
                self.table.setItem(r, 1, c1)
                self.table.setItem(r, 2, c2)
                self.table.setItem(r, 3, c3)
            self._fix_map = {(mod, dirn, name): i for i, (mod, name, dirn) in enumerate(rows)}
        # 每帧刷新: 时间列 + 数据列 (行位置不变, 值随时间变)
        for mod, ports in io.items():
            for dirn in ("in", "out"):
                for name, val in ports.get(dirn, []):
                    r = self._fix_map.get((mod, dirn, name))
                    if r is None:
                        continue
                    c0 = QTableWidgetItem(f"{t:.2f}"); c0.setData(Qt.UserRole, t)
                    c0.setForeground(QColor("#9aa4b2"))
                    self.table.setItem(r, 0, c0)
                    c4 = QTableWidgetItem(_sig_val(val))
                    c4.setForeground(QColor("#e6edf3"))
                    c4.setData(Qt.UserRole, val)   # 🔬 存原始向量供结构化详情
                    self.table.setItem(r, 4, c4)
        self.lbl_cnt.setText(f"{self.table.rowCount()} 个信号 · t={t:.2f}s")

    def feed(self, t, io):
        """运行中喂入一个快照: 时间顺序=追加行 / 固定格式=刷新固定行"""
        if self.cmb_mode.currentIndex() == 0:
            self.append_snapshot(t, io)
        else:
            self.update_snapshot(t, io)

    def _on_context_menu(self, pos):
        """🎨 右键视觉信号 → 渲染 RGB-D 多视角 (2026-08-22/23 老倪)"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        name_item = self.table.item(row, 2)
        if name_item is None:
            return
        name = name_item.text()
        is_bbox = "检测框" in name
        is_visual = any(k in name for k in ("RGB-D", "图像流", "视觉", "rgbd", "状态流", "坐标"))
        if not (is_bbox or is_visual):
            return
        _menu_qss = ("QMenu { background:#161b22; color:#e6edf3; border:1px solid #30363d; } "
                     "QMenu::item { color:#e6edf3; padding:6px 22px; } "
                     "QMenu::item:selected { background:#1f6feb; color:#ffffff; } "
                     "QMenu::item:disabled { color:#57606a; }")
        menu = QMenu(self)
        menu.setStyleSheet(_menu_qss)
        if is_bbox:
            bbox_menu = menu.addMenu("🖼 渲染检测框 (bounding box · 选视角)")
            bbox_menu.setStyleSheet(_menu_qss)
            for cam, label in _MW_CAMERAS:
                act = bbox_menu.addAction(label)
                act.triggered.connect(lambda checked=False, r=row, c=cam: self._render_bbox(r, c))
        else:
            render_menu = menu.addMenu("🎨 渲染 RGB-D 图片 (选相机视角)")
            render_menu.setStyleSheet(_menu_qss)
            for cam, label in _MW_CAMERAS:
                act = render_menu.addAction(label)
                act.triggered.connect(lambda checked=False, r=row, c=cam: self._render_rgbd(r, c))
            render_menu.addSeparator()
            act_all = render_menu.addAction("🖼 打开全部 7 视角 (并排)")
            act_all.triggered.connect(lambda checked=False, r=row: self._render_all_views(r))
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def _render_rgbd(self, row, camera_name="corner2"):
        """后台渲染该行对应时刻的 RGB-D (真实 metaworld 视角) → 非模态独立窗口显示"""
        tr = getattr(self.module, "_ss_tr", None)
        if not tr or not tr.get("x"):
            return
        t_item = self.table.item(row, 0)
        t = t_item.data(Qt.UserRole) if t_item is not None else None
        import numpy as np
        t_arr = np.asarray(tr["t"])
        idx = int(np.argmin(np.abs(t_arr - t))) if t is not None else len(t_arr) - 1
        t_val = float(tr["t"][idx])
        self._spawn_render(idx, t_val, camera_name)

    def _spawn_render(self, idx, t_val, camera_name):
        """后台线程渲染 → 完成回主线程弹窗 (metaworld 渲染慢, 不卡 UI)"""
        tr = getattr(self.module, "_ss_tr", None)
        import threading

        def _work():
            err = None
            img = None
            try:
                img = render_rgbd_frame(tr, idx, camera_name)
            except Exception as ex:
                err = str(ex)
            self._render_done.emit(camera_name, t_val, img, err)
        threading.Thread(target=_work, daemon=True).start()

    def _render_all_views(self, row):
        """🖼 打开全部 7 视角窗口 (后台串行渲染, 逐个弹出, 可并排拖动对比)"""
        tr = getattr(self.module, "_ss_tr", None)
        if not tr or not tr.get("x"):
            return
        t_item = self.table.item(row, 0)
        t = t_item.data(Qt.UserRole) if t_item is not None else None
        import numpy as np
        t_arr = np.asarray(tr["t"])
        idx = int(np.argmin(np.abs(t_arr - t))) if t is not None else len(t_arr) - 1
        t_val = float(tr["t"][idx])
        import threading

        def _work_all():
            for cam, _label in _MW_CAMERAS:
                err = None
                img = None
                try:
                    img = render_rgbd_frame(tr, idx, cam)
                except Exception as ex:
                    err = str(ex)
                self._render_done.emit(cam, t_val, img, err)
        threading.Thread(target=_work_all, daemon=True).start()

    def _show_render_window(self, camera_name, t_val, img, err=None):
        """主线程显示独立非模态渲染窗口 (可拖动, 可同时开多个)"""
        if err is not None or img is None:
            QMessageBox.warning(self, "渲染失败", err or "渲染结果为空")
            return
        img = img.convert("RGB")
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        pm = QPixmap.fromImage(qimg)
        # 大图/高分屏缩放, 窗口别超出屏幕
        max_w, max_h = 1280, 820
        if pm.width() > max_w or pm.height() > max_h:
            pm = pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # 独立顶层窗口 (无 parent → WM 给独立标题栏, 可自由拖动, 不跟随主窗口)
        dlg = QDialog(None)
        dlg.setWindowTitle(f"🎨 RGB-D · {camera_name} · t={t_val:.2f}s")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setStyleSheet("QDialog{background:#0d1117;}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(6, 6, 6, 6)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(pm)
        lay.addWidget(lbl)
        dlg.adjustSize()
        # 保持引用防 GC (清理已关闭的旧窗口引用)
        if not hasattr(self, "_render_windows"):
            self._render_windows = []
        self._render_windows = [w for w in self._render_windows if w.isVisible()]
        self._render_windows.append(dlg)
        dlg.show()

    def _render_bbox(self, row, camera_name="corner2"):
        """🖼 后台渲染 YOLO 检测框 (bounding box) → 非模态独立窗口"""
        tr = getattr(self.module, "_ss_tr", None)
        if not tr or not tr.get("x"):
            return
        t_item = self.table.item(row, 0)
        t = t_item.data(Qt.UserRole) if t_item is not None else None
        import numpy as np
        t_arr = np.asarray(tr["t"])
        idx = int(np.argmin(np.abs(t_arr - t))) if t is not None else len(t_arr) - 1
        t_val = float(tr["t"][idx])
        import threading

        def _work():
            err = None
            img = None
            try:
                img = render_bbox_frame(idx, camera_name)
            except Exception as ex:
                err = str(ex)
            self._bbox_done.emit(camera_name, t_val, img, err)
        threading.Thread(target=_work, daemon=True).start()

    def _show_bbox_window(self, camera_name, t_val, img, err=None):
        """主线程显示检测框渲染窗口 (独立非模态, 可拖动)"""
        if err is not None or img is None:
            QMessageBox.warning(self, "渲染失败", err or "渲染结果为空")
            return
        img = img.convert("RGB")
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        pm = QPixmap.fromImage(qimg)
        max_w, max_h = 900, 760
        if pm.width() > max_w or pm.height() > max_h:
            pm = pm.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        dlg = QDialog(None)
        dlg.setWindowTitle(f"🖼 检测框 · {camera_name} · t={t_val:.2f}s")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setStyleSheet("QDialog{background:#0d1117;}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(6, 6, 6, 6)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setPixmap(pm)
        lay.addWidget(lbl)
        dlg.adjustSize()
        if not hasattr(self, "_render_windows"):
            self._render_windows = []
        self._render_windows = [w for w in self._render_windows if w.isVisible()]
        self._render_windows.append(dlg)
        dlg.show()

    def _on_cell_click(self, row, col):
        """🔬 点击数据行 → 若数据是向量, 结构化显示子结构 (2026-08-23 老倪)"""
        val_item = self.table.item(row, 4)
        if val_item is None:
            return
        val = val_item.data(Qt.UserRole)
        if val is None:
            return
        name_item = self.table.item(row, 2)
        name = name_item.text() if name_item is not None else ""
        groups = _struct_fields(name, val)
        if not groups:
            return
        t_item = self.table.item(row, 0)
        t = t_item.data(Qt.UserRole) if t_item is not None else 0.0
        self._show_struct_detail(name, t, groups)

    def _show_struct_detail(self, name, t, groups):
        """结构化详情面板 (非模态复用, 点击更新内容)"""
        dlg = getattr(self, "_struct_dlg", None)
        if dlg is None or not dlg.isVisible():
            dlg = QDialog(None)
            dlg.setWindowTitle("🔬 结构化详情")
            dlg.setStyleSheet(
                "QDialog{background:#0d1117;}"
                "QTreeWidget{background:#0d1117;color:#e6edf3;border:1px solid #30363d;"
                "font-size:15px;font-family:Consolas,monospace;}"
                "QTreeWidget::item{padding:3px 4px;}"
                "QTreeWidget::item:selected{background:#1f6feb;}"
                "QHeaderView::section{background:#161b22;color:#9aa4b2;border:none;"
                "border-bottom:1px solid #30363d;padding:4px;font-weight:bold;}")
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(8, 8, 8, 8)
            self._struct_hdr = QLabel()
            self._struct_hdr.setStyleSheet("color:#58a6ff;font-size:15px;font-weight:bold;"
                                           "background:transparent;border:none;")
            self._struct_hdr.setWordWrap(True)
            lay.addWidget(self._struct_hdr)
            self._struct_tree = QTreeWidget()
            self._struct_tree.setHeaderLabels(["字段", "值"])
            self._struct_tree.setColumnWidth(0, 200)
            lay.addWidget(self._struct_tree, 1)
            self._struct_dlg = dlg
        self._struct_hdr.setText(f"{name}  ·  t={t:.2f}s")
        tree = self._struct_tree
        tree.clear()
        for grp, fields in groups:
            top = QTreeWidgetItem([grp, f"{len(fields)} 维"])
            top.setForeground(0, QColor("#d29922"))
            top.setForeground(1, QColor("#8b949e"))
            for fname, fval in fields:
                sub = QTreeWidgetItem([fname, f"{fval:.4f}"])
                sub.setForeground(0, QColor("#c9d1d9"))
                sub.setForeground(1, QColor("#e6edf3"))
                top.addChild(sub)
            tree.addTopLevelItem(top)
        tree.expandAll()
        self._struct_dlg.show()
        self._struct_dlg.raise_()
        self._struct_dlg.activateWindow()

    def _on_select(self, row, col):
        """选中行 → 高亮画布对应连线 (模块名 + 方向)"""
        if row < 0:
            return
        hl = getattr(self.module, "highlight_ss_links", None)
        if hl is None:
            return
        mod_it = self.table.item(row, 1)
        dir_it = self.table.item(row, 3)
        if mod_it is None or dir_it is None:
            return
        dirn = "in" if "IN" in dir_it.text() else "out"
        hl(mod_it.text(), dirn)


# ════════════════════════════════════════════════════════════════
# 🔬 结构化字段解析 (2026-08-23 老倪: 39D/43D 一排数 → 点击看子结构)
# ════════════════════════════════════════════════════════════════
_FRAME18_GROUPS = [
    ("末端位置", ["x", "y", "z"]),        # [0:3]
    ("夹爪开度", ["开度"]),                 # [3]
    ("末端速度", ["vx", "vy", "vz"]),      # [4:7]
    ("peg 位置", ["x", "y", "z"]),         # [7:10]
    ("孔位", ["x", "y", "z"]),             # [10:13]
    ("孔位姿态", ["rx", "ry", "rz"]),      # [13:16]
    ("预留", ["r0", "r1"]),                # [16:18]
]
_TACTILE4_NAMES = ["夹爪", "接触", "预留0", "预留1"]
_VEC3_NAMES = ["x", "y", "z"]
_VEC6_NAMES = ["Fx", "Fy", "Fz", "Tx", "Ty", "Tz"]


def _flat_18(v):
    """18D → [(name, value)] 扁平字段 (按组细分命名)"""
    out = []
    off = 0
    for grp, subs in _FRAME18_GROUPS:
        for s in subs:
            out.append((f"{grp}·{s}", float(v[off])))
            off += 1
    return out


def _struct_fields(name, val):
    """接口名 + 值 → 结构化分组 [(group, [(name, value), ...]), ...]; 不可结构化返回 None"""
    if isinstance(val, str) or isinstance(val, (bool, np.bool_)):
        return None
    v = np.asarray(val, dtype=float).ravel()
    n = v.size
    if n <= 1:
        return None
    if n == 39:   # 39D 视觉结构 (当前18 + 上一18 + 目标3)
        return [
            ("当前帧 cur (18D)", _flat_18(v[:18])),
            ("上一帧 prev (18D)", _flat_18(v[18:36])),
            ("目标 target (3D)", [("x", float(v[36])), ("y", float(v[37])), ("z", float(v[38]))]),
        ]
    if n == 43:   # 43D = 39D + 触觉4
        g = _struct_fields("", v[:39])
        g.append(("触觉 tactile (4D)", [(nm, float(v[39 + i])) for i, nm in enumerate(_TACTILE4_NAMES)]))
        return g
    if n == 18:   # 18D 帧结构
        return [("帧 (18D)", _flat_18(v))]
    if n == 4:
        if "夹爪" in name:
            return [("指令 u (4D)", [("x", float(v[0])), ("y", float(v[1])), ("z", float(v[2])), ("夹爪", float(v[3]))])]
        if "预测力" in name or "潜状态" in name or "latent" in name.lower():
            return [("潜状态 latent (4D)", [("x", float(v[0])), ("y", float(v[1])), ("z", float(v[2])), ("预测力", float(v[3]))])]
        return [("向量 (4D)", [(f"d{i}", float(v[i])) for i in range(4)])]
    if n == 3:
        return [("坐标 (3D)", [(nm, float(v[i])) for i, nm in enumerate(_VEC3_NAMES)])]
    if n == 6:
        return [("力觉 (6D)", [(nm, float(v[i])) for i, nm in enumerate(_VEC6_NAMES)])]
    return [("向量 (%dD)" % n, [(f"d{i}", float(v[i])) for i in range(n)])]


# ════════════════════════════════════════════════════════════════
# 右侧数据字典面板
# ════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# ⚙️ 配置 · 运行开关  (2026-10-09 老倪)
# ══════════════════════════════════════════════════════════════════════════════
class RunConfigWidget(QWidget):
    """⚙️ 配置 · 运行开关 —— 画布工具栏上那 6 个档位/策略开关的**归位页**。

    老倪 (2026-10-09): 「①⚡引擎快演 ②🚀L3全链 ③🧠流形yaw ④🤖L4 INTACT ⑤🎯L4意图 ⑥🧩L2兼容
    —— 再次检查是否有功能, 将这些功能整合进画布右侧的『参数标定』侧边页面,
    这个页面对应工程的 测量/诊断/标定/配置」。

    做法: **开关对象本身不换** (同一个 QCheckBox 被 re-parent 到本页) ⇒ 引擎与全部运行路径
    读 self.chk_* 一字不用改 (零回退); 本页只给每个开关配「作用 / 在引擎哪一行生效 /
    实测代价 / 适用档位」, 让"这个勾到底改了啥"一眼可查、可复制。
    """

    # (属性名, 分组, 适用档位, 作用, 在引擎哪一行生效, 代价/边界, 是否风险)
    ROWS = [
        ("chk_engine_demo", "运行方式", "全部档位",
         "勾 = 引擎简化世界快速演示 (<0.1s, YOLO 仅末尾采样 1 次)\n"
         "不勾 = 真实化运行: metaworld 物理 + 每帧渲染 → YOLO detect_3d",
         "simulink_module.py:7150 分流 _start_state_space_sim / _start_real_sim",
         "不勾 ≈5-9 分钟/轮 · 快演只用来验「接线通不通」, 判精度必须不勾", False),
        ("chk_l3_full", "任务链", "仅 L2 档有效",
         "勾 = 跑满 13 段 (插入 → 拔出 → AOI 检测 → 放回)\n"
         "不勾 = 插装即完成 (8 段演示)",
         "simulink_module.py:13601 → _l3_mode=\"full\"",
         "档位 L3/L4 自动 full (勾选框不起作用) · 实测 20-40s/轮", False),
        ("chk_mani_yaw", "策略", "仅 L4 演示档",
         "勾 = L4 演示 ② 段「夹爪绕 z 转 90°」由**流形预测器**决策 (Arm B)\n"
         "不勾 = 脚本开环写死 (Arm A, 作对照)",
         "simulink_module.py:13680 → 引擎 state_space_sim_real.py:407/2511 (mani_yaw=)",
         "用途就是拿它做 A/B, 看流形预测器与脚本开环差多少", False),
        ("chk_intact_exec", "模型接管", "仅 L4 档",
         "勾 = SS_INTACT=1: L4 档 u_ff 槽位交给 INTACT 真推理 (每 8 步一次,\n"
         "权重走软链指针 intact_l4_current) · 不勾 = 回 L4Demo 稳定演示",
         "引擎 state_space_sim_real.py:435 (os.environ SS_INTACT)",
         "⚠️ 域内微调 ckpt 离线判闸未过 (MAE≈常数基线) ⇒ 本档可能失败", True),
        ("chk_l4_dit", "模型接管", "仅 L4 档",
         "勾 = SS_L4_DIT=1, β=0.5, 每 16 步一次真前向, 与 INTACT 融合\n"
         "u = (1−β)·u_L4 + β·u_DiT · 不勾 = 纯 INTACT (逐位零回退)",
         "引擎 state_space_sim_real.py:1316 / 1479",
         "⚠️ 条件投影未训练 (随机小初始化): 通道真参与前向, 增益待训练; "
         "|z_t→流形6维| 实测不可标定 (R²≤0)", True),
        ("chk_l2_compat", "模型接管", "仅 L4 档",
         "勾 = SS_USE_MLP=1 + YOLO 每帧真检测 (L2 在 L4 档内**真跑**: 前馈蒸馏 MLP 真身 + 真实视觉)\n"
         "不勾 = 回 R0 真值 + 解析前馈",
         "引擎 state_space_sim_real.py:546 (os.environ SS_USE_MLP)",
         "⚠️ 实测代价 (seed104/120 步): 终点距离 0.42mm → 6.82mm (16×), 耗时 2.1× "
         "⇒ 要精度优先请取消勾选", True),
    ]
    # 原厂默认 (「↺ 恢复默认」按这个还原, 与既有实测口径一致)
    DEFAULTS = {"chk_engine_demo": False, "chk_l3_full": False, "chk_mani_yaw": True,
                "chk_intact_exec": True, "chk_l4_dit": True, "chk_l2_compat": True}

    def __init__(self, module=None, parent=None):
        super().__init__(parent)
        self.module = module
        self._cks = {}       # 属性名 → 真开关控件 (从画布工具栏搬来的那一个)
        self._slots = {}     # 属性名 → 放开关的横向布局
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(8)

        self.lbl_hd = QLabel("⚙️ 配置 · 运行开关 (档位 / 策略)")
        self.lbl_hd.setStyleSheet("color:#e6edf3;font-size:16px;font-weight:bold;background:transparent;")
        lay.addWidget(self.lbl_hd)
        self.lbl_sub = QLabel("本页 = 工程的「配置」面 (对应 测量 / 诊断 / 标定 / 配置 四轴)。"
                              "开关只服务状态空间画布的 ▶运行 / ⏭单步; 改完**下一次运行即生效**, 不用重启。")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet("color:#9aa4b2;font-size:12px;background:transparent;")
        lay.addWidget(self.lbl_sub)

        self.lbl_cap = QLabel("当前档位: —")
        self.lbl_cap.setStyleSheet("color:#ffd700;font-size:14px;font-weight:bold;background:transparent;")
        lay.addWidget(self.lbl_cap)

        for g in ("运行方式", "任务链", "策略", "模型接管"):
            rows = [r for r in self.ROWS if r[1] == g]
            if not rows:
                continue
            card = QFrame()
            card.setStyleSheet("QFrame{background:#161b22;border:1px solid #30363d;border-radius:6px;}")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 6, 8, 6)
            cl.setSpacing(6)
            t = QLabel(g)
            t.setStyleSheet("color:#58a6ff;font-size:13px;font-weight:bold;background:transparent;"
                            "border:none;")
            cl.addWidget(t)
            for (key, _g, cap, use, where, cost, risk) in rows:
                cl.addWidget(self._mk_row(key, cap, use, where, cost, risk))
            lay.addWidget(card)

        # 诊断行 (可复制) + 两个按钮
        self.lbl_state = QLabel("")
        self.lbl_state.setWordWrap(True)
        self.lbl_state.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_state.setStyleSheet("color:#7ee787;font-size:12px;font-family:Consolas,monospace;"
                                     "background:#0d1117;border:1px solid #21262d;border-radius:5px;"
                                     "padding:6px;")
        lay.addWidget(self.lbl_state)
        hb = QHBoxLayout()
        hb.setSpacing(6)
        b1 = QPushButton("↺ 恢复默认")
        b1.setToolTip("恢复出厂默认: 快演✗ / 全链✗ / 流形yaw✓ / INTACT✓ / DiT✓ / L2兼容✓")
        b1.clicked.connect(self._restore)
        b2 = QPushButton("📋 复制当前配置")
        b2.setToolTip("把这 6 个开关的当前状态复制到剪贴板 (可粘进工单/交接记录)")
        b2.clicked.connect(self._copy)
        for b in (b1, b2):
            b.setStyleSheet("QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
                            "border-radius:4px;padding:3px 10px;font-size:13px;}"
                            "QPushButton:hover{background:#30363d;}")
            hb.addWidget(b)
        hb.addStretch(1)
        lay.addLayout(hb)
        lay.addStretch(1)

    # ── 单行: 开关槽 + 适用档位 + 作用 + 生效位置 + 代价 ──
    def _mk_row(self, key, cap, use, where, cost, risk):
        f = QFrame()
        f.setStyleSheet("QFrame{background:#0d1117;border:1px solid #21262d;border-radius:5px;}")
        v = QVBoxLayout(f)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        top.addWidget(holder, 1)
        chip = QLabel(cap)
        chip.setStyleSheet("color:#8b949e;font-size:11px;background:#21262d;"
                           "border:1px solid #30363d;border-radius:8px;padding:1px 6px;")
        top.addWidget(chip, 0)
        v.addLayout(top)
        for text, color, size in ((use, "#c9d1d9", 12),
                                  ("生效: " + where, "#8b949e", 11),
                                  (("代价: " if risk else "") + cost,
                                   ("#f0883e" if risk else "#8b949e"), 11)):
            lb = QLabel(text)
            lb.setWordWrap(True)
            lb.setStyleSheet(f"color:{color};font-size:{size}px;background:transparent;border:none;")
            v.addWidget(lb)
        self._slots[key] = hl
        return f

    # ── 把画布工具栏上的 6 个开关搬进来 (同一个控件对象, 行为零改变) ──
    def attach_switches(self, mapping):
        got = 0
        for key, chk in (mapping or {}).items():
            sl = self._slots.get(key)
            if sl is None or chk is None:
                continue
            try:
                chk.setStyleSheet(
                    "QCheckBox{color:#c9d1d9;font-size:14px;background:transparent;padding:2px;}"
                    "QCheckBox:checked{color:#3fb950;font-weight:bold;}")
            except Exception:
                pass
            sl.addWidget(chk)          # 自动 re-parent (工具栏那边同时被移走)
            try:
                chk.stateChanged.connect(self._on_toggle)
            except Exception:
                pass
            self._cks[key] = chk
            got += 1
        self.refresh()
        return got

    def _on_toggle(self, *_a):
        self.refresh()

    # ── 档位 (能力档位节点 cap_level) ──
    def _cap(self):
        lvl = None
        try:
            for n in getattr(self.module, "nodes", []) or []:
                p = n.get("params", {}) or {}
                if p.get("cap_switch"):
                    lvl = p.get("cap_level") or lvl
        except Exception:
            pass
        if lvl is None:
            lvl = getattr(self.module, "_cap_level", None)
        lvl = str(lvl or "L2").upper()
        return {"L4D": "L4"}.get(lvl, lvl)

    def refresh(self):
        cap = self._cap()
        self.lbl_cap.setText(f"当前档位: {cap}   (画布「能力档位」节点 cap_level)")
        parts = []
        for (key, _g, capuse, _u, _w, _c, _r) in self.ROWS:
            chk = self._cks.get(key)
            if chk is None:
                continue
            nm = (chk.text() or key).strip()
            hit = ("全部档位" in capuse) or (cap in capuse)
            parts.append(f"{nm}={'开' if chk.isChecked() else '关'}{'' if hit else '(本档无效)'}")
        self.lbl_state.setText(" · ".join(parts) if parts else "⚠️ 开关未接入")

    def _restore(self):
        for key, val in self.DEFAULTS.items():
            c = self._cks.get(key)
            if c is not None:
                try:
                    c.setChecked(bool(val))
                except Exception:
                    pass
        self.refresh()

    def _copy(self):
        try:
            QApplication.clipboard().setText(
                f"Z-MAX 运行开关 · 档位 {self._cap()} · " + self.lbl_state.text())
        except Exception:
            pass


class MasterParamMView(QWidget):
    """🧮 主参数 M · 测量 / 标定 / 诊断 / 配置 —— 状态空间工程 ←→ 配置中心的**唯一收口口**。

    老倪 (2026-10-09): 「右边的侧边栏, 重点是 配置 和 标定, 以及主参数 M; 其它的功能要精简」。

    数据源 = **画布上的节点**「🧮 标定诊断测量 · 主参数 M」(id `n_calib_mani`) 的 params:
      cfg_entries (9 条真源路径) · cfg_snapshot (就绪度/缺口/任务/断言/模型匹配) ·
      measure_view · calib_view · diagnose_view · task_layer
    —— 这些是 `tools/ss_node_sync.py` 从真源文件同步进节点的**快照**, 文件仍是唯一真源;
    所以本页跟状态空间工程是**真连接**(节点在画布上, 快照来自真源, 写 M 走
    `tools/zmax_params.py::write_manifold_M` = 范围校验 + 只改 manifold_engine 键, 不整表重合并)。
    """
    NODE_ID = "n_calib_mani"

    def __init__(self, module=None, parent=None):
        super().__init__(parent)
        self.module = module
        # 仓库根 = tools/gui/model_tree.py 往上三层 (少一层会把真源/工具路径拼错, 体检真踩到过)
        self._root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.lbl_hd = QLabel("🧮 主参数 M · 测量 / 标定 / 诊断 / 配置")
        self.lbl_hd.setStyleSheet("color:#e6edf3;font-size:16px;font-weight:bold;background:transparent;")
        lay.addWidget(self.lbl_hd)
        self.lbl_node = QLabel("…")
        self.lbl_node.setWordWrap(True)
        self.lbl_node.setStyleSheet("color:#8b949e;font-size:12px;font-family:Consolas,monospace;"
                                    "background:transparent;")
        lay.addWidget(self.lbl_node)

        # ── M 写入行 (标定的主标量; 三段纪律在 zmax_params.write_manifold_M 里) ──
        mbar = QFrame()
        mbar.setStyleSheet("QFrame{background:#161b22;border:1px solid #30363d;border-radius:6px;}")
        ml = QHBoxLayout(mbar)
        ml.setContentsMargins(8, 6, 8, 6)
        ml.setSpacing(8)
        ml.addWidget(QLabel("主参数 M"))
        self.sp_M = QDoubleSpinBox()
        self.sp_M.setRange(0.0, 8.0)
        self.sp_M.setSingleStep(0.1)
        self.sp_M.setDecimals(3)
        self.sp_M.setValue(1.0)
        self.sp_M.setToolTip("M 范围 [0,8] (G0 结构参数, 非自由拟合)。M→0 = 无惯性 (旧一阶过阻尼, 零回归)")
        self.sp_M.setStyleSheet("QDoubleSpinBox{background:#0d1117;color:#e6edf3;border:1px solid #30363d;"
                                "border-radius:4px;padding:2px 6px;font-size:13px;}")
        ml.addWidget(self.sp_M)
        self.chk_inertia = QCheckBox("inertia")
        self.chk_inertia.setToolTip("勾 = 有惯性二阶 (Δx=F·dt²/M); 不勾 = 零回归 (与旧版一阶过阻尼逐位相同)")
        self.chk_inertia.setStyleSheet("QCheckBox{color:#c9d1d9;font-size:13px;background:transparent;}")
        ml.addWidget(self.chk_inertia)
        self.btn_write_M = QPushButton("✏️ 写 M")
        self.btn_write_M.setToolTip("写真源 config/calib/zmax_manifold.json (只改 manifold_engine 键, 范围校验, "
                                    "不整表重合并) → 流形引擎/画布节点下次读到")
        self.btn_write_M.clicked.connect(self._write_M)
        ml.addWidget(self.btn_write_M)
        ml.addStretch(1)
        self.btn_sync = QPushButton("📥 从真源同步到节点")
        self.btn_sync.setToolTip("跑 tools/ss_node_sync.py: 把 9 条真源 (mcd/参数注册表/匹配矩阵/任务/绑定/工单/"
                                 "工程文件/站点标定/流形标定) 的快照写进画布 M 节点")
        self.btn_sync.clicked.connect(self._sync_node)
        self.btn_refresh = QPushButton("🔁 刷新")
        self.btn_refresh.setToolTip("重新从画布 M 节点读快照 (不跑脚本)")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_copy = QPushButton("📋 复制摘要")
        self.btn_copy.clicked.connect(self._copy)
        for b in (self.btn_sync, self.btn_refresh, self.btn_copy):
            ml.addWidget(b)
        for b in (self.btn_write_M, self.btn_sync, self.btn_refresh, self.btn_copy):
            b.setStyleSheet("QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
                            "border-radius:4px;padding:3px 8px;font-size:12px;}"
                            "QPushButton:hover{background:#30363d;}")
        lay.addWidget(mbar)

        # ── 四视角页签 (测量/标定/诊断/配置) ──
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:1px solid #30363d;background:#0d1117;}"
                                "QTabBar::tab{background:#161b22;color:#8b949e;padding:4px 10px;font-size:12px;}"
                                "QTabBar::tab:selected{background:#0d1117;color:#e6edf3;}")
        self.tbl = {}
        for key, name in (("measure", "📏 测量"), ("calib", "🎛 标定"),
                          ("diag", "🔍 诊断"), ("cfg", "🔧 配置")):
            t = QTableWidget(0, 2)
            t.setHorizontalHeaderLabels(["项", "值"])
            t.verticalHeader().setVisible(False)
            t.setWordWrap(True)
            t.setColumnWidth(0, 96)
            t.setStyleSheet("QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#21262d;"
                            "font-size:12px;font-family:Consolas,monospace;border:none;}"
                            "QHeaderView::section{background:#161b22;color:#8b949e;border:none;padding:3px;}")
            self.tbl[key] = t
            self.tabs.addTab(t, name)
        lay.addWidget(self.tabs, 1)

        self.lbl_cmd = QLabel("")
        self.lbl_cmd.setWordWrap(True)
        self.lbl_cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_cmd.setStyleSheet("color:#7ee787;font-size:11px;font-family:Consolas,monospace;"
                                   "background:#0d1117;border:1px solid #21262d;border-radius:5px;padding:6px;")
        lay.addWidget(self.lbl_cmd)
        self.refresh()

    # ── 找画布上的 M 节点 (id 优先, 语义/名字兜底: 画布另存为会重编 id) ──
    def _node(self):
        for n in (getattr(self.module, "nodes", None) or []):
            p = n.get("params", {}) or {}
            if n.get("id") == self.NODE_ID or p.get("manifold_calib") is True:
                return n
        for n in (getattr(self.module, "nodes", None) or []):
            if "主参数" in (n.get("name") or ""):
                return n
        return None

    @staticmethod
    def _fill(table, rows):
        table.setRowCount(0)
        for k, v in rows:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(str(k)))
            it = QTableWidgetItem("" if v is None else str(v))
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)   # 值可选中复制
            table.setItem(r, 1, it)
        table.resizeRowsToContents()

    def refresh(self):
        n = self._node()
        if n is None:
            self.lbl_node.setText("⚠️ 当前画布没有「🧮 标定诊断测量 · 主参数 M」节点 —— "
                                  "打开状态空间工程, 或先运行 tools/canvas_add_manifold_calib.py")
            for t in self.tbl.values():
                t.setRowCount(0)
            self.lbl_cmd.setText("python3 tools/canvas_add_manifold_calib.py   # 把 M 节点加进当前画布")
            return
        p = n.get("params", {}) or {}
        snap = p.get("cfg_snapshot", {}) or {}
        prj = snap.get("project", {}) or {}
        self.lbl_node.setText(
            f"节点: {n.get('name', '?')}\n"
            f"  id={n.get('id')} · 快照 {snap.get('mcd_generated_at', '—')} · 画布 {prj.get('nodes', '?')} 节点 "
            f"/ {prj.get('links', '?')} 连线 · 节点回读 {snap.get('node_readback_at') or '(未回读)'}")
        try:
            self.sp_M.setValue(float(p.get("M", 1.0)))
            self.chk_inertia.setChecked(bool(p.get("inertia", False)))
        except Exception:
            pass
        mv, cv, dv, tl = (p.get("measure_view") or {}, p.get("calib_view") or {},
                          p.get("diagnose_view") or {}, p.get("task_layer") or {})
        self._fill(self.tbl["measure"], [
            ("视图", mv.get("视图", "—")),
            ("测量量", mv.get("测量量", "—")),
            ("源", "\n".join(mv.get("源") or [])),
            ("判据", mv.get("判据", "—")),
            ("命令", mv.get("命令", "—")),
        ])
        self._fill(self.tbl["calib"], [
            ("视图", cv.get("视图", "—")),
            ("可标参数", cv.get("可标参数", "—")),
            ("主参数 M", cv.get("主参数M", f"M={p.get('M')} · 范围 {p.get('M_range')} · inertia={p.get('inertia')}")),
            ("M 含义", p.get("M_meaning", "—")),
            ("M 非自由", p.get("M_not_free", "—")),
            ("零回归", p.get("zero_regression", "—")),
            ("真源", cv.get("真源", "—")),
            ("命令", cv.get("命令", "—")),
        ])
        self._fill(self.tbl["diag"], [
            ("视图", dv.get("视图", "—")),
            ("断言", f"{dv.get('断言', '—')} (自动 {snap.get('assertions_auto', '—')})"),
            ("故障码", " ".join(dv.get("故障码") or [])),
            ("站点缺口", "\n".join(dv.get("站点缺口") or [])),
            ("参数缺口", "\n".join(snap.get("gaps") or [])),
            ("模型匹配", f"{snap.get('models_matched', '—')} 受阻 {snap.get('models_blocked') or []}"),
            ("命令", dv.get("命令", "—")),
        ])
        ent = p.get("cfg_entries") or {}
        self._fill(self.tbl["cfg"], [
            ("就绪度", f"{snap.get('params_ready', '—')}/{snap.get('params_total', '—')} (缺 {snap.get('params_gap', '—')})"),
            ("域分布", " · ".join(f"{k} {v}" for k, v in (snap.get("by_domain") or {}).items())),
            ("任务", f"{snap.get('tasks', tl.get('任务数', '—'))} 个 · 活跃 {snap.get('active_task', tl.get('活跃', '—'))} "
                     f"· 段覆盖 {tl.get('段覆盖', '—')} 节点"),
            ("工单", snap.get("orders", "—")),
        ] + [("真源 " + k, v) for k, v in ent.items()])
        self.lbl_cmd.setText(" · ".join(x for x in (
            mv.get("命令"), cv.get("命令"), dv.get("命令"), tl.get("命令")) if x))

    # ── ✏️ 写 M (真源 + 范围校验 + 只改 manifold_engine 键; 回来立刻回读) ──
    def _write_M(self):
        import subprocess
        v = float(self.sp_M.value())
        iner = bool(self.chk_inertia.isChecked())
        code = ("import sys, json; sys.path.insert(0, %r);"
                "import zmax_params as zp;"
                "print(json.dumps(zp.write_manifold_M(%r, %r), ensure_ascii=False))"
                % (os.path.join(self._root, "tools"), v, iner))
        try:
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               timeout=60, cwd=self._root)
            out = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
            if r.returncode == 0 and out:
                self._log(f"✏️ 主参数 M 已写入真源: {out}")
                # 回读真源确认
                self._sync_node(silent=True)
            else:
                self._log(f"❌ 写 M 失败 (exit={r.returncode}): {(r.stderr or '')[-300:]}")
        except Exception as ex:
            self._log(f"❌ 写 M 异常: {ex}")

    # ── 📥 从真源同步到节点 (ss_node_sync) ──
    def _sync_node(self, silent=False):
        import subprocess
        tool = os.path.join(self._root, "tools", "ss_node_sync.py")
        try:
            r = subprocess.run([sys.executable, tool], capture_output=True, text=True,
                               timeout=180, cwd=self._root)
            tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
            self._log(("📥 节点同步: " if not silent else "📥 回读校验: ") + (tail or f"exit={r.returncode}"))
        except Exception as ex:
            self._log(f"❌ 节点同步异常: {ex}")
        self.refresh()

    def _copy(self):
        try:
            QApplication.clipboard().setText(self.lbl_node.text() + "\n" + self.lbl_cmd.text())
        except Exception:
            pass

    def _log(self, msg):
        try:
            self.module._log(msg)
        except Exception:
            pass


class MeasureHub(QWidget):
    """📏 测量 · 数据字典 / 状态空间变量 / 数据总线 —— 三个测量视图收进**一行一个页签**
    (2026-10-09 老倪: 「测量类的有三行, 太多了, 只保留一行」)。

    实现是「搬, 不是复制」: 三个控件对象 (`tree` / `ss_tree` / `bus`) 由 dock 创建后被
    `attach()` **re-parent** 进本组件的 QTabWidget ⇒ 外部代码读 `dock.tree` 等一字不改, 零回退。
    """
    TABS = (("tree", "📚 数据字典"), ("ss_tree", "🎛 状态空间变量"), ("bus", "🔌 数据总线"))

    def __init__(self, dock=None, parent=None):
        super().__init__(parent)
        self.dock = dock
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane{border:1px solid #30363d;background:transparent;}"
                                "QTabBar::tab{background:#161b22;color:#8b949e;padding:3px 9px;font-size:12px;}"
                                "QTabBar::tab:selected{background:#0d1117;color:#e6edf3;}")
        lay.addWidget(self.tabs, 1)
        self._w = {}
        self.tabs.currentChanged.connect(self._on_tab)

    def attach(self, tree, ss_tree, bus):
        self._w = {"tree": tree, "ss_tree": ss_tree, "bus": bus}
        for key, name in self.TABS:
            w = self._w[key]
            w.setParent(None)          # 从 dock 的布局里摘出来
            w.setVisible(True)
            self.tabs.addTab(w, name)  # 同一个对象, 换了父
        return self

    def _cur_key(self):
        i = self.tabs.currentIndex()
        return self.TABS[i][0] if 0 <= i < len(self.TABS) else "tree"

    def _on_tab(self, _i):
        self.refresh_current()

    def refresh_current(self):
        """只刷当前页签 (省算力); 失败不抛, 记日志。"""
        k = self._cur_key()
        try:
            if k == "tree":
                self.dock.refresh()
            elif k == "ss_tree":
                self.dock._show_state_space()
            else:
                self._w["bus"].refresh()
        except Exception as ex:
            try:
                self.dock.module._log(f"⚠️ 测量页({k})刷新失败: {ex}")
            except Exception:
                pass

    def show_tab(self, key):
        for i, (k, _n) in enumerate(self.TABS):
            if k == key:
                self.tabs.setCurrentIndex(i)   # 触发 _on_tab → 刷该签
                return True
        return False


class CalibTruthView(QWidget):
    """🎛 标定 · 真源标定注册表 (只读) + 未标定项的**可执行**补救命令 (2026-10-09 老倪: 「增加一个标定类」)。

    真源 = `config/calib/zmax_calib.json` (由 `tools/zmax_params.py --sync` 合并生成; 所有层读它,
    禁止硬编码内外参)。本页与状态空间工程真连接: 引擎/视觉读的就是这些键, 而 `T_base_cam` /
    `plane_z` / `cell_geometry` 三项 **未标定** —— 正是阻塞 5 条工单与真机域模型的共同根因。
    本页**只读展示 + 给命令**; 唯一的写口 = 主参数 M (在「🧮 主参数 M」页, 走 write_manifold_M
    的范围校验 + 只改目标键 + 回读三段纪律), 避免在面板上开第二个写口。
    """
    # 仓库根 = tools/gui/model_tree.py 往上三层 (本文件在 tools/gui/ 下)
    CALIB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "config", "calib", "zmax_calib.json")
    # 未标定项 → 现场标定命令 (零运动/只读采集, 人工确认)
    FIX = {
        "cell_geometry": "gui-venv311/bin/python tools/ss_geom_calib.py --record peg_head|goal|aoi"
                         "   # 零运动示教: 人工拖到位后确认",
        "T_base_cam": "gui-venv311/bin/python tools/board_handeye_solve.py"
                      "   # 零运动人工拖动 10+ 位姿采板 → 解外参",
        "plane_z": "# 现场用夹爪或塞尺量一次台面高度 → 写 config/calib/zmax_calib.json 的 plane_z.value",
        "depth_scale": "gui-venv311/bin/python tools/probe_r1_yolo_calib.py   # 仿真单目深度专用, 真机走米制",
    }

    def __init__(self, module=None, parent=None):
        super().__init__(parent)
        self.module = module
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        self.lbl_hd = QLabel("🎛 标定 · 真源参数与缺口")
        self.lbl_hd.setStyleSheet("color:#e6edf3;font-size:16px;font-weight:bold;background:transparent;")
        lay.addWidget(self.lbl_hd)
        self.lbl_src = QLabel("…")
        self.lbl_src.setWordWrap(True)
        self.lbl_src.setStyleSheet("color:#8b949e;font-size:12px;font-family:Consolas,monospace;"
                                   "background:transparent;")
        lay.addWidget(self.lbl_src)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_refresh = QPushButton("🔁 刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_copy = QPushButton("📋 复制全部")
        self.btn_copy.setToolTip("把标定注册表逐行复制到剪贴板 (含未标定项与补救命令)")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_path = QPushButton("📂 复制真源路径")
        self.btn_path.clicked.connect(lambda: self._clip(self.CALIB))
        for b in (self.btn_refresh, self.btn_copy, self.btn_path):
            b.setStyleSheet("QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
                            "border-radius:4px;padding:3px 8px;font-size:12px;}"
                            "QPushButton:hover{background:#30363d;}")
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["参数", "值", "状态", "真源 / 补救"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setWordWrap(True)
        self.tbl.setColumnWidth(0, 108)
        self.tbl.setColumnWidth(1, 190)
        self.tbl.setColumnWidth(2, 62)
        self.tbl.setStyleSheet("QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#21262d;"
                               "font-size:12px;font-family:Consolas,monospace;border:none;}"
                               "QHeaderView::section{background:#161b22;color:#8b949e;border:none;padding:3px;}")
        lay.addWidget(self.tbl, 1)
        self.lbl_cmd = QLabel("")
        self.lbl_cmd.setWordWrap(True)
        self.lbl_cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_cmd.setStyleSheet("color:#ffa657;font-size:11px;font-family:Consolas,monospace;"
                                   "background:#0d1117;border:1px solid #21262d;border-radius:5px;padding:6px;")
        lay.addWidget(self.lbl_cmd)
        self.refresh()

    # ── 值 → 一行摘要 ──
    @staticmethod
    def _brief(k, d):
        v = d.get("value", d)
        if isinstance(v, list):
            return "[" + ", ".join(f"{x:.4g}" if isinstance(x, float) else str(x) for x in v[:6]) + \
                   (" …]" if len(v) > 6 else "]")
        if isinstance(v, dict):
            return " · ".join(f"{a}={b if not isinstance(b, float) else round(b, 4)}"
                              for a, b in list(v.items())[:4] if not a.startswith("_"))
        if isinstance(v, float):
            return f"{v:.4g}"
        return str(v)

    def _rows(self):
        try:
            d = json.load(open(self.CALIB, encoding="utf-8"))
        except Exception as ex:
            return None, {}, f"⚠️ 读不到真源 {self.CALIB}: {ex}"
        rows = []
        for k, v in d.items():
            if k.startswith("_"):
                continue
            v = v if isinstance(v, dict) else {"value": v}
            raw = v.get("value", v.get("points", v))
            uncal = (raw is None)
            src = v.get("_src") or ""
            why = v.get("_reason") or ""
            rows.append({
                "k": k,
                "val": "—" if uncal else self._brief(k, v),
                "st": "⚠️ 未标定" if uncal else "✅ 有值",
                "note": (f"补救: {self.FIX.get(k, '')}" if uncal else src),
                "why": why,
                "uncal": uncal,
            })
        return rows, d, ""

    def refresh(self):
        rows, d, err = self._rows()
        if rows is None:
            self.lbl_src.setText(err)
            self.tbl.setRowCount(0)
            return
        miss = [r["k"] for r in rows if r["uncal"]]
        self.lbl_src.setText(
            f"真源 {self.CALIB}\n  _generated_at {d.get('_generated_at', '—')} · "
            f"{len(rows)} 个参数段 · 未标定 {len(miss)} 项 {miss or ''}\n"
            f"  所有层读本文件 (禁硬编码内外参); 唯一写口 = 「🧮 主参数 M」页的 M (三段纪律)")
        self.tbl.setRowCount(0)
        for r in rows:
            i = self.tbl.rowCount()
            self.tbl.insertRow(i)
            for c, txt in enumerate((r["k"], r["val"], r["st"], r["note"] or r["why"])):
                it = QTableWidgetItem(str(txt))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if r["uncal"]:
                    it.setForeground(QColor("#ffa657"))
                self.tbl.setItem(i, c, it)
        self.tbl.resizeRowsToContents()
        cmds = "\n".join(self.FIX[k] for k in miss if k in self.FIX)
        self.lbl_cmd.setText(("⚠️ " + " / ".join(miss) + " 未标定 —— 现场标定命令:\n" + cmds)
                             if cmds else "✅ 真源无未标定缺口")

    def _text(self):
        out = [self.lbl_src.text(), ""]
        for r in range(self.tbl.rowCount()):
            out.append(" | ".join(self.tbl.item(r, c).text() for c in range(4)))
        return "\n".join(out) + "\n\n" + self.lbl_cmd.text()

    def _copy(self):
        self._clip(self._text())

    @staticmethod
    def _clip(t):
        try:
            QApplication.clipboard().setText(t)
        except Exception:
            pass


class ModelTreeDock(QWidget):
    export_done = pyqtSignal(str)  # 🐛 2026-08-19: 导出上传走后台线程, 完成信号回主线程
    """📚 数据字典 (Model Tree) — 画布节点参数树 + 标定 + 数学分析
    🐛 2026-08-14: QDockWidget → QWidget (SimulinkModule 是 QWidget 非 QMainWindow,
    addDockWidget 不存在 → 面板一直没显示; 改嵌入右侧 split 列)"""

    def __init__(self, module, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelTreeDock")
        self.setMinimumWidth(300)
        self.module = module

        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # 下拉菜单: 视图切换 —— 🧭 2026-10-09 老倪: 「这个页面对应工程的 测量 诊断 标定 配置」
        #   ⇒ 视图**按四轴分组命名** (顺序=轴序), 索引→视图的映射改成表驱动 (见 _switch_view)
        hdr = QHBoxLayout()
        hdr.setSpacing(4)
        self.cmb_view = QComboBox()
        # 🧭 2026-10-09 老倪「重点 = 配置 + 标定 + 主参数 M」: 只剩 5 项, 全部与工程有真连接
        # 🧭 2026-10-09 老倪: 「测量类只保留一行 + 增加一个标定类」→ 4 行, 全部真连接
        self.cmb_view.addItems(["🧮 主参数 M · 测量/标定/诊断/配置",
                                "📏 测量 · 数据字典 / 状态空间变量 / 数据总线",
                                "🎛 标定 · 真源参数与缺口",
                                "🔧 配置 · 运行开关"])

        self.cmb_view.currentIndexChanged.connect(self._switch_view)
        hdr.addWidget(self.cmb_view, 1)
        # 🧩 导出能力库 Excel (2026-08-19 老倪: feature 导出 → datadrive.world 可下载)
        self.btn_export = QPushButton("导出")
        self.btn_export.setStyleSheet(
            "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
            "border-radius:4px;padding:3px 10px;font-size:15px;}"
            "QPushButton:hover{background:#30363d;}")
        self.btn_export.setToolTip("导出能力库 feature.dbc → Excel, 上传 datadrive.world 可下载")
        self.btn_export.clicked.connect(self._export_feature)
        hdr.addWidget(self.btn_export)
        # 🧩 导入第三方模型 (2026-08-19 老倪: 标准格式一键导入 → 加载进平台)
        self.btn_import = QPushButton("导入")
        self.btn_import.setStyleSheet(
            "QPushButton{background:#21262d;color:#e6edf3;border:1px solid #30363d;"
            "border-radius:4px;padding:3px 10px;font-size:15px;}"
            "QPushButton:hover{background:#30363d;}")
        self.btn_import.setToolTip("导入第三方模型包 (zip/目录, 标准格式 zmax-model-v1)")
        self.btn_import.clicked.connect(self._import_model)
        hdr.addWidget(self.btn_import)
        lay.addLayout(hdr)

        # 🔗 连线数据横幅 (2026-08-21 老倪: 左键选连线 → 右侧高亮显示数据类型+数值,
        # 仿 Simulink 信号属性面板 — 金色边框深色卡片, 默认隐藏)
        self.link_card = QFrame()
        self.link_card.setFrameShape(QFrame.NoFrame)
        self.link_card.setStyleSheet(
            "QFrame{background:#161b22;border:1px solid #d29922;border-radius:6px;}")
        self.link_card.setVisible(False)
        _lc = QVBoxLayout(self.link_card)
        _lc.setContentsMargins(10, 8, 10, 8)
        _lc.setSpacing(4)
        self.link_title = QLabel("🔗 连线数据")
        self.link_title.setStyleSheet("color:#d29922;font-weight:bold;font-size:16px;"
                                      "background:transparent;border:none;")
        self.link_body = QLabel("")
        self.link_body.setStyleSheet("color:#e6edf3;font-size:15px;font-family:Consolas,monospace;"
                                     "background:transparent;border:none;")
        self.link_body.setWordWrap(True)
        self.link_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _lc.addWidget(self.link_title)
        _lc.addWidget(self.link_body)
        lay.addWidget(self.link_card)

        # ────────────────────────────────────────────────────────────────────────────────────────────
        # 🧊 已停用 (2026-10-09 老倪: 没联系就注释掉): 现场标定/性能指标/场景状态/运行汇总/工程需求
        # ────────────────────────────────────────────────────────────────────────────────────────────
        # # 📐 2026-08-15 老倪: 现场标定向导 (3步标定法, 只看物理现象)
        # self.stage_calib = StageCalibrationWidget(module)
        # self.stage_calib._pp_ref = None
        # self.stage_calib.setVisible(False)
        # lay.addWidget(self.stage_calib)

        # # 📊 2026-08-15 老倪: 性能指标列表 (插拔动作分解: 时间/速度/加速度/能量/质量)
        # self.perf = PerformanceWidget(module)
        # self.perf.setVisible(False)
        # lay.addWidget(self.perf)

        # # 🎯 2026-08-15 老倪: 场景状态定义 (PM 视角, 每状态可验收性能指标)
        # self.scene_state = SceneStateWidget(module)
        # self.scene_state.setVisible(False)
        # lay.addWidget(self.scene_state)

        # # 🚀 2026-08-15 老倪: 运行汇总 (点运行 → 状态+性能+数学+稳定性 一页全出)
        # self.run_summary = RunSummaryWidget(module)
        # self.run_summary.setVisible(False)
        # lay.addWidget(self.run_summary)

        # # 📋 2026-08-15 老倪: 工程需求 (系统总输入, 驱动全链路)
        # self.eng_req = EngineeringReqWidget(module)
        # self.eng_req.setVisible(False)
        # lay.addWidget(self.eng_req)

        # ⚙️ 2026-10-09 老倪: 「将①~⑥这 6 个运行开关整合进右侧『参数标定』侧边页面」
        #   (本页 = 工程的「配置」面; 开关对象由画布 re-parent 进来, 见 attach_run_switches)
        self.run_cfg = RunConfigWidget(module)
        self.run_cfg.setVisible(False)
        lay.addWidget(self.run_cfg)

        # 🧮 2026-10-09 老倪: 右侧栏重点 = 配置 + 标定 + 主参数 M —— 本页就是那个收口口
        self.mparam = MasterParamMView(module)
        self.mparam.setVisible(False)
        lay.addWidget(self.mparam, 1)

        # 🎛 2026-10-09 老倪: 「增加一个标定类」→ 真源标定注册表 (config/calib/zmax_calib.json 只读)
        #   + 未标定项 (T_base_cam/plane_z/cell_geometry) 的可执行现场标定命令
        self.calib = CalibTruthView(module)
        self.calib.setVisible(False)
        lay.addWidget(self.calib, 1)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color:#9aa4b2; font-size:14px; background:transparent; border:none;")
        self.lbl_hint.setWordWrap(True)
        # 🐛 2026-08-19: 链接可选中/可点击 (导出提示)
        self.lbl_hint.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextBrowserInteraction)
        self.lbl_hint.setOpenExternalLinks(True)
        lay.addWidget(self.lbl_hint)

        # ────────────────────────────────────────────────────────────────────────────────────────────
        # 🧊 已停用: 极点配置(参数标定) — 写回要求画布有 z700_internal 节点, 状态空间画布 0 处
        # ────────────────────────────────────────────────────────────────────────────────────────────
        # # 🎯 2026-08-15 老倪: 极点配置设计器 (参数标定视图, 性能指标→ζ/ωₙ→Kp/Kd)
        # self.pole_place = PolePlacementWidget(module)
        # self.pole_place.tree = None
        # self.pole_place.setVisible(False)
        # lay.addWidget(self.pole_place)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_item_dbl)
        # lay.addWidget(self.tree, 1)   # 🧊 已收进 MeasureHub (一行一个页签)
        # 🎛 状态空间 · 信号监控树 (2026-08-20 老倪: Simulink 风格全量变量监控)
        self.ss_tree = QTreeWidget()
        self.ss_tree.setHeaderHidden(True)
        self.ss_tree.setVisible(False)
        # 🎯 选中变量 → 高亮画布对应连线 (2026-08-20 老倪: 变量↔连线对应)
        self.ss_tree.currentItemChanged.connect(self._on_ss_select)
        # lay.addWidget(self.ss_tree, 1)   # 🧊 已收进 MeasureHub (一行一个页签)
        # 🔌 数据总线 (CANoe Trace 风格, 2026-08-22 老倪: 状态空间接口数据时间顺序监视)
        self.bus = DataBusTrace(module)
        self.bus.setVisible(False)
        # lay.addWidget(self.bus, 1)   # 🧊 已收进 MeasureHub (一行一个页签)

        # 📏 2026-10-09 老倪: 「测量类的有三行, 太多了, 只保留一行」→ 收进一个「测量」页 (3 页签,
        #   控件还是 tree/ss_tree/bus 这**三个原对象**, re-parent 进 hub ⇒ 外部读 self.tree 不受影响)
        self.measure = MeasureHub(self).attach(self.tree, self.ss_tree, self.bus)
        self.measure.setVisible(False)
        lay.addWidget(self.measure, 1)
        # ────────────────────────────────────────────────────────────────────────────────────────────
        # 🧊 已停用: 上面两处对停用部件的引用
        # ────────────────────────────────────────────────────────────────────────────────────────────
        # # 🎯 2026-08-15: 极点配置写回后刷新树 (树创建后才挂引用)
        # self.pole_place.tree = self.tree
        # # 📐 2026-08-15: 现场标定写回后刷新树
        # self.stage_calib._pp_ref = self.pole_place

        # ────────────────────────────────────────────────────────────────────────────────────────────
        # 🧊 已停用: 数学分析 (传函/极点/复平面/自由响应) — analyze_system 走默认参数分支
        # ────────────────────────────────────────────────────────────────────────────────────────────
        # # 数学分析视图控件 (默认隐藏)
        # self.lbl_math = QLabel("")
        # self.lbl_math.setStyleSheet("color:#c9d1d9; font-size:15px; font-family:Consolas; background:transparent;")
        # self.lbl_math.setWordWrap(True)
        # self.lbl_math.setVisible(False)
        # lay.addWidget(self.lbl_math)
        # self.plot = PoleZeroPlot()
        # self.plot.setVisible(False)
        # lay.addWidget(self.plot)
        # # 🐛 2026-08-15 老倪: 特征解物理含义 — 自由响应曲线 (σ衰减/ω振荡/前馈补偿)
        # self.response = FreeResponsePlot()
        # self.response.setVisible(False)
        # lay.addWidget(self.response)

        self.setLayout(lay)  # QWidget 布局 (原 QDockWidget.setWidget(root))
        # 🐛 2026-08-14 老倪: 右侧面板黑字看不清 → 深色背景+白色字体
        self.setStyleSheet("""
            ModelTreeDock { background:#0d1117; }
            QTreeWidget { background:#0d1117; color:#e6edf3; border:1px solid #30363d;
                          font-size:17px; font-family:Consolas,monospace; }
            QTreeWidget::item { color:#e6edf3; padding:4px; }
            QTreeWidget::item:selected { background:#1f6feb; color:#ffffff; }
            QTreeWidget::branch { background:#0d1117; }
            QComboBox { background:#161b22; color:#e6edf3; border:1px solid #30363d;
                        padding:3px; font-size:16px; }
            QComboBox QAbstractItemView { background:#161b22; color:#e6edf3;
                                          selection-background-color:#1f6feb; }
            QLabel { color:#e6edf3; }
        """)
        self.export_done.connect(self._on_export_done)
        self._switch_view(0)   # 🧮 默认停在「主参数 M」页 (配置 + 标定 收口口)

    # ── 导出能力库 Excel (2026-08-19 老倪) ──
    def _export_feature(self):
        """导出能力库 feature.dbc → Excel, 上传 datadrive.world 可下载
        🐛 2026-08-19 主线程跑 sshpass scp 卡 60s = 按钮没反应 → 后台线程 + 信号"""
        self.lbl_hint.setText("⏳ 正在导出并上传 datadrive.world…")
        self.btn_export.setEnabled(False)
        import threading

        def _work():
            msg = "⚠️ 导出失败"
            try:
                from feature_dbc import upload_excel
                path, url = upload_excel()
                msg = (f'✅ 已导出并上传: <a href="{url}" style="color:#58a6ff;">'
                       f'{url}</a> (点击打开/选中复制)') if url \
                    else f"✅ 已导出(本机): {path}"
            except Exception as ex:
                msg = f"⚠️ 导出失败: {ex}"
            self.export_done.emit(msg)

        threading.Thread(target=_work, daemon=True).start()

    def _on_export_done(self, msg):
        self.lbl_hint.setText(msg)
        try:
            self.btn_export.setEnabled(True)
        except Exception:
            pass

    # ── 导入第三方模型 (2026-08-19 老倪) ──
    def _import_model(self):
        """选模型包 → 一键导入 (校验/注册/挂载/冒烟) → 刷新树"""
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择第三方模型包 (zip)",
                                              "", "模型包 (*.zip);;所有文件 (*)")
        if not path:
            return
        self.lbl_hint.setText("⏳ 正在校验并导入模型包…")
        self.btn_import.setEnabled(False)
        import threading

        def _work():
            msg = "⚠️ 导入失败"
            try:
                from model_importer import import_model
                ok, node, m = import_model(path)
                msg = m
            except Exception as ex:
                msg = f"⚠️ 导入异常: {ex}"
            self.export_done.emit(msg)

        threading.Thread(target=_work, daemon=True).start()

    def _on_export_done(self, msg):
        self.lbl_hint.setText(msg)
        try:
            self.btn_export.setEnabled(True)
            self.btn_import.setEnabled(True)
        except Exception:
            pass
        # 导入成功后刷新树 (能力库出现新节点)
        try:
            if "导入成功" in msg:
                self.refresh()
        except Exception:
            pass

    # ── 视图切换 ──
    def attach_run_switches(self, mapping):
        """⚙️ 把画布工具栏上的 6 个运行开关搬进「🔧 配置 · 运行开关」页 (2026-10-09 老倪)。
        开关对象不换 (re-parent) ⇒ 引擎/运行路径读 self.chk_* 不受影响。"""
        try:
            return self.run_cfg.attach_switches(mapping)
        except Exception as ex:
            try:
                self.module._log(f"⚠️ 运行开关页接入失败: {ex}")
            except Exception:
                pass
            return 0

    # 视图键顺序 = cmb_view 条目顺序 (🧭 2026-10-09 老倪: 测量收 1 行 + 加标定页 ⇒ 4 行)
    VIEW_KEYS = ("mparam", "measure", "calib", "run_cfg")

    def _switch_view(self, idx):
        """视图切换 (表驱动: 以后加视图只改 VIEW_KEYS + cmb_view 两处)。

        2026-10-09 停用 (注释掉; 取证见 tools/gui/_model_tree_ffpd_legacy.py 头):
        perf / scene_state / run_summary / eng_req / pole_place / stage_calib / math ——
        它们读画布上的 z700_internal 节点与 gain_schedule, 而状态空间画布 (state_space_obs.json)
        这两样都是 0 处 ⇒ 显示的是 analyze_system() 里的硬编码默认值, 与工程无实质联系。"""
        k = self.VIEW_KEYS[idx] if 0 <= idx < len(self.VIEW_KEYS) else "mparam"
        v = {name: (name == k) for name in self.VIEW_KEYS}
        self.mparam.setVisible(v["mparam"])
        self.measure.setVisible(v["measure"])
        self.calib.setVisible(v["calib"])
        self.run_cfg.setVisible(v["run_cfg"])
        # 懒刷新 (只在切到的视图刷新, 省算力)
        if v["mparam"]:
            self.mparam.refresh()
        elif v["measure"]:
            self.measure.refresh_current()
        elif v["calib"]:
            self.calib.refresh()
        elif v["run_cfg"]:
            self.run_cfg.refresh()

    # ── 数据字典树 (系统参数 + 节点 + 参数) ──

    def refresh(self):
        self.tree.clear()
        self.lbl_hint.setText("画布节点参数一览 · 双击参数值可标定/调节 (写回画布)")
        # 🧩 能力数据库 feature.dbc (2026-08-19 老倪: 参考 CANoe DBC, 文件即配置事实 —
        #   同一平台/容器配置不同模型; 缺失时自动从能力库生成)
        try:
            import feature_dbc as _fdb
            _dbc = _fdb.load_dbc()
            if _dbc is None:
                from model_feature import (FEATURE_LIBRARY, MODEL_MANIFESTS,
                                           DATAFLOW_STAGES, INTERFACE_DEFS)
                _fdb.write_dbc(FEATURE_LIBRARY, MODEL_MANIFESTS,
                               DATAFLOW_STAGES, INTERFACE_DEFS)
                _dbc = _fdb.load_dbc()
            if _dbc:
                _item = _fdb.build_tree_from_dbc(
                    _dbc, self.module,
                    lambda texts: QTreeWidgetItem(texts), Qt.UserRole)
                if _item is not None:
                    self.tree.addTopLevelItem(_item)
        except Exception:
            pass
        # 系统参数
        sys_root = QTreeWidgetItem(["⚙ 系统参数"])
        self.tree.addTopLevelItem(sys_root)
        dt = getattr(self.module, "_sim_dt", 0.01)
        QTreeWidgetItem(sys_root, ["采样周期 dt", f"{dt:.4f} s"])
        n_sys = sum(1 for n in self.module.nodes if n.get("type") != "row_bg")
        QTreeWidgetItem(sys_root, ["功能节点数", str(n_sys)])
        # 节点 (按行分组: y 坐标)
        rows = {}
        for n in self.module.nodes:
            if n.get("type") == "row_bg":
                continue
            rows.setdefault(round(n.get("y", 0) / 10), []).append(n)
        for y in sorted(rows):
            grp = QTreeWidgetItem([f"行 y={y * 10}"])
            self.tree.addTopLevelItem(grp)
            for n in sorted(rows[y], key=lambda x: x.get("x", 0)):
                nitem = QTreeWidgetItem([f"{n.get('name', '?')}"])
                nitem.setData(0, Qt.UserRole, n)
                grp.addChild(nitem)
                params = n.get("params", {})
                for k, v in params.items():
                    if isinstance(v, dict):
                        continue
                    # 🐛 2026-08-15 老倪: "数据字典对应上了么" — limit 数组参数被跳过
                    #   (list 是标定值如 limit=[-1,1]) → 格式化成 "[−1, 1]" 显示,
                    #   双击标定时按逗号解析回 list
                    if isinstance(v, list):
                        disp = "[" + ", ".join(str(x) for x in v) + "]"
                        pit = QTreeWidgetItem([f"  {k}", disp])
                        pit.setData(0, Qt.UserRole, (n, k))
                        nitem.addChild(pit)
                        continue
                    pit = QTreeWidgetItem([f"  {k}", str(v)])
                    pit.setData(0, Qt.UserRole, (n, k))
                    nitem.addChild(pit)
        self.tree.expandAll()

    # ── 双击参数 → 标定 (写回画布节点) ──

        # 🧮 2026-10-09 老倪: 画布加载/变更时 (load_flow_file → model_tree.refresh) 若当前停在
        #   「主参数 M」页, 一并刷新快照 —— 否则切页才刷新会让人看到旧值 (体检时真踩到)。
        try:
            _k = list(getattr(self, "VIEW_KEYS", ()))
            _i = self.cmb_view.currentIndex()
            _cur = _k[_i] if 0 <= _i < len(_k) else "mparam"
            _wname = {"mparam": "mparam", "measure": "measure", "calib": "calib",
                      "run_cfg": "run_cfg"}.get(_cur, "")
            _w = getattr(self, _wname, None) if _wname else None
            if _w is not None and hasattr(_w, "refresh"):
                _w.refresh()               # 不依赖 isVisible (窗口隐藏/离屏也要刷新, 体检踩到过)
        except Exception:
            pass
    def _on_item_dbl(self, item, col):
        data = item.data(0, Qt.UserRole)
        if not data or not isinstance(data, tuple) or len(data) != 2:
            return
        node, key = data
        cur = node.get("params", {}).get(key, "")
        val, ok = QInputDialog.getText(self, f"标定参数: {node.get('name')}",
                                       f"{key} =", text=str(cur))
        if not ok:
            return
        try:
            old = node["params"][key]
            if isinstance(old, bool):
                node["params"][key] = val.lower() in ("true", "1", "yes", "是")
            elif isinstance(old, (int, float)):
                node["params"][key] = type(old)(float(val))
            elif isinstance(old, list):
                # 🐛 2026-08-15 老倪: limit 数组标定 — 输入 "−1, 1" 或 "[−1, 1]" 解析回 list
                import re as _re
                parts = [p.strip() for p in _re.split(r"[,\s\[\]]+", val) if p.strip()]
                node["params"][key] = [float(p) for p in parts]
            else:
                node["params"][key] = val
        except Exception:
            node["params"][key] = val
        self.module._refresh_node(node)
        self.module._log(f"⚙️ 标定 [{node.get('name')}] {key} = {node['params'][key]}")
        self.refresh()

    # 🧊 2026-10-09 停用: _show_math() 用 analyze_system() (已挪到 _model_tree_ffpd_legacy.py)。
    #   需要时从 legacy 文件 import 回来; 面板已不再有「数学分析」入口。

    # 🧊 2026-10-09 停用 (整段注释掉): _show_math() 依赖 analyze_system() —— 已挪到
    #   tools/gui/_model_tree_ffpd_legacy.py; 面板不再有「数学分析」入口。
    #     def _show_math(self):
    #         try:
    #             res = analyze_system(self.module)
    #         except Exception as ex:
    #             self.lbl_math.setText(f"⚠️ 数学分析失败: {ex}")
    #             return
    #         chain = res["chain"]
    #         names = " → ".join(n.get("name", "?") for n in chain[:6])
    #         if len(chain) > 6:
    #             names += " …"
    #         num, den = res["num"], res["den"]
    #         def _poly(p):
    #             return "".join(f"{c:+.3g}s^{len(p) - 1 - i} " for i, c in enumerate(p))
    #         poles = ", ".join(f"{z.real:.3f}{z.imag:+.3f}i" for z in res["poles"]) or "无"
    #         zeros = ", ".join(f"{z.real:.3f}{z.imag:+.3f}i" for z in res["zeros"]) or "无"
    #         A, B, C, D = res["A"], res["B"], res["C"], res["D"]
    #         txt = (f"🧮 系统数学化 (主链路 {len(chain)} 节点)\n"
    #                f"链路: {names}\n\n"
    #                f"G(s) = N(s)/D(s)\n  N = {_poly(num)}\n  D = {_poly(den)}\n\n"
    #                f"状态空间 (可控标准型, 阶数 n={A.shape[0]})\n"
    #                f"  ẋ = Ax + Bu\n  y = Cx + Du\n"
    #                f"  A = {A.tolist()}\n  B = {B.tolist()}\n  C = {C.tolist()}\n  D = {D.tolist()}\n\n"
    #                f"极点 (复数空间): {poles}\n"
    #                f"零点: {zeros}\n"
    #                f"稳定性: {'✅ 稳定 (全部极点 Re<0)' if res['stable'] else '❌ 不稳定 (存在 Re≥0 极点)'}")
    #         # 🐛 2026-08-15 老倪: 前馈 PD 顶层 — 纯规则前馈PD 二阶模型完整代数推导
    #         # (时域方程 → 拉普拉斯 → 闭环传函 → 特征方程 → 特征解 → 增益调度)
    #         if res.get("ff_pd"):
    #             fp = res["ff_pd"]
    #             Kp, Kd = fp["Kp"], fp["Kd"]
    #             K_obs, Kff, F_gain = fp["K_obs"], fp["K_ff"], fp["F_gain"]
    #             m2, b2, k2, limit = fp["m"], fp["b"], fp["k"], fp["limit"]
    #             # 特征方程系数: m·s² + (b+Kd)s + (k+Kp) = 0
    #             # 判别式: Δ = (b+Kd)² − 4m(k+Kp)
    #             a_c, b_c, c_c = m2, b2 + Kd, k2 + Kp
    #             disc = b_c * b_c - 4 * a_c * c_c
    #             wn = math.sqrt(c_c / a_c) if c_c > 0 else 0.0
    #             zeta = b_c / (2 * math.sqrt(a_c * c_c)) if a_c * c_c > 0 else 0.0
    #             if disc >= 0:
    #                 s1 = (-b_c + math.sqrt(disc)) / (2 * a_c)
    #                 s2 = (-b_c - math.sqrt(disc)) / (2 * a_c)
    #                 pole_str = f"{s1:.3f}, {s2:.3f}"
    #             else:
    #                 re_p = -b_c / (2 * a_c)
    #                 im_p = math.sqrt(-disc) / (2 * a_c)
    #                 s1, s2 = complex(re_p, im_p), complex(re_p, -im_p)
    #                 pole_str = f"{re_p:.3f} ± j{im_p:.3f}"
    #             tau = -1.0 / zeta / wn if zeta > 0 and wn > 0 else 0.0
    #             txt += (f"\n\n⚙️ 纯规则前馈PD (L2层, 可解析)\n"
    #                     f"  ┌ 时域: m·ẍ + b·ẋ + k·x = F(t)\n"
    #                     f"  │      F = K_ff·r + Kp·e + Kd·ė   (e = r − x)\n"
    #                     f"  ├ s域: [m·s²+(b+Kd)s+(k+Kp)]·X = [Kd·s+(K_ff+Kp)]·R\n"
    #                     f"  └ 闭环: G_cl(s) = (Kd·s + {F_gain + Kp:.3f}) / "
    #                     f"({m2:g}·s² + {b_c:g}·s + {c_c:g})\n\n"
    #                     f"── 特征方程 (根的位置) ──\n"
    #                     f"  {m2:g}·s² + {b_c:g}·s + {c_c:g} = 0\n"
    #                     f"  特征解 s₁,₂ = {pole_str}\n"
    #                     f"  ωₙ = {wn:.3f} rad/s · ζ = {zeta:.3f} "
    #                     f"({'欠阻尼·超调' if zeta < 1 else '临界/过阻尼·无超调'})\n"
    #                     f"  K_ff={F_gain:.3f} 不进特征方程 → 只移零点, 不改稳定性 ✅\n\n"
    #                     f"── 前馈补偿效果 ──\n"
    #                     f"  纯反馈静差 e_ss = {fp['e_ss_nofb']:.4f} → 前馈后 {fp['e_ss']:.4f} "
    #                     f"(削减 {100 * (1 - fp['e_ss'] / fp['e_ss_nofb']):.1f}%)\n"
    #                     f"  限幅 ±{limit} = 饱和阻尼 (非线性 D), 防超调\n\n"
    #                     f"── 增益调度根轨迹 (各阶段特征根) ──\n"
    #                     f"  (Mp=超调 Ts=稳定时间±2%  — 工程师验证: 看曲线不看复数)")
    #             for st in fp["root_locus"]:
    #                 p0 = st["poles"][0]
    #                 txt += (f"\n  {st['stage']}: Kp={st['Kp']:.1f} Kd={st['Kd']:.1f}  "
    #                         f"ωₙ={st['wn']:.2f} ζ={st['zeta']:.2f}  "
    #                         f"s={p0.real:.2f}{p0.imag:+.2f}j\n"
    #                         f"     Mp={st['Mp'] * 100:.1f}%  Ts={st['Ts']:.2f}s  "
    #                         f"Tp={st['Tp']:.2f}s  {st['type']}"
    #                         + (f"\n     🖐 {st['feel']}" if st["feel"] else ""))
    #             txt += ("\n\n  📌 增益调度 = 各阶段换特征多项式系数 (根在复平面跳跃)\n"
    #                     "  📌 完整 MLP+状态机系统非线性 → 无全域特征方程, 用局部线性化\n"
    #                     "  📌 验收: 阶跃超调<5% · 猛推回正≤2次震荡 · 插入力曲线平滑S型")
    #         self.lbl_math.setText(txt)
    #         self.plot.set_data(res["poles"], res["zeros"], res["stable"],
    #                            res.get("ff_pd", {}).get("root_locus"))

    #     # ── 状态空间设计 (2026-08-12 老倪: 经典控制 ↔ 双脑网络同构) ──
    def _show_state_space(self):
        """🎛 状态空间 · 信号监控 (Simulink 风格全量变量监控)"""
        try:
            self.ss_tree.clear()
            tr = getattr(self.module, "_ss_tr", None)
            if not tr or not tr.get("io"):
                self.ss_tree.addTopLevelItem(
                    QTreeWidgetItem(["⚠️ 暂无仿真数据 — 点「▶ 运行」跑一次状态空间仿真后自动出全量变量"]))
                return
            io = tr["io"]
            done = bool(tr["done"][-1]) if tr.get("done") else False
            t_end = tr["t"][-1] if tr.get("t") else 0.0
            dist = tr["dist"][-1] if tr.get("dist") else 0.0
            contact = max(tr["contact_p"]) if tr.get("contact_p") else 0.0
            res = max(tr["residual"]) if tr.get("residual") else 0.0
            stage = tr["stage"][-1] if tr.get("stage") else "?"
            st = QTreeWidgetItem(["📊 仿真状态"])
            QTreeWidgetItem(st, [f"结果 = {'✅ 插入完成' if done else '⚠️ 未完成'}"])
            QTreeWidgetItem(st, [f"用时 = {t_end:.2f}s"])
            QTreeWidgetItem(st, [f"最终距离 = {dist:.4f}m"])
            QTreeWidgetItem(st, [f"接触概率峰值 = {contact:.2f}"])
            QTreeWidgetItem(st, [f"残差峰值 = {res:.4f}"])
            QTreeWidgetItem(st, [f"阶段 = {stage}"])
            self.ss_tree.addTopLevelItem(st)
            for mod, ports in io.items():
                mroot = QTreeWidgetItem([mod])
                for dirn in ("in", "out"):
                    sigs = ports.get(dirn, [])
                    label = "▶ IN 输入" if dirn == "in" else "◀ OUT 输出"
                    dnode = QTreeWidgetItem([label])
                    for name, val in sigs:
                        dnode.addChild(QTreeWidgetItem([f"{name} [{_sig_shape(val)}] = {_sig_val(val)}"]))
                    mroot.addChild(dnode)
                self.ss_tree.addTopLevelItem(mroot)
            self.ss_tree.expandAll()
        except Exception as ex:
            self.ss_tree.clear()
            self.ss_tree.addTopLevelItem(QTreeWidgetItem([f"⚠️ 变量监控失败: {ex}"]))

    def _on_ss_select(self, cur, prev):
        """🎯 选中右侧变量 → 高亮画布对应连线 (2026-08-20 老倪: 变量↔连线对应)
        变量树层级: 模块名 → (▶IN输入/◀OUT输出) → 变量。向上找 IN/OUT 方向 + 模块名,
        再调 SimulinkModule.highlight_ss_links 高亮该模块的输入/输出连线 (金色加粗)。"""
        try:
            hl = getattr(self.module, "highlight_ss_links", None)
            if hl is None:
                return
            if cur is None:
                hl(None, None)   # 空选 → 清除全部高亮
                return
            # 向上找 IN/OUT 方向节点
            node = cur
            direction = None
            while node is not None:
                txt = node.text(0)
                if "IN 输入" in txt:
                    direction = "in"
                    break
                if "OUT 输出" in txt:
                    direction = "out"
                    break
                node = node.parent()
            module_name = None
            if direction and node is not None:
                mroot = node.parent()
                if mroot is not None:
                    module_name = mroot.text(0)
            hl(module_name, direction)
        except Exception:
            pass

    def show_link_data(self, info):
        """🔗 选中连线 → 右侧横幅显示连线数据 (Simulink 信号属性风格, 2026-08-21 老倪)
        数据流 src→dst + 类型 + 标签 + 端口 + 数值 (仿真值 / 默认类型)。"""
        try:
            from html import escape
            lbl = info.get("label", "") or "—"
            meta = info.get("src_type_cn", "?")
            f_port = info.get("f_port", "out1")
            t_port = info.get("t_port", "in1")
            value = escape(str(info.get("value", "—")))
            sim = info.get("simulated", False)
            sim_tag = "📈 仿真值" if sim else "📋 默认类型"
            html = (
                f"<b>{escape(str(info.get('src_name', '?')))} → "
                f"{escape(str(info.get('dst_name', '?')))}</b><br>"
                f"类型: {escape(str(meta))} &nbsp;·&nbsp; 标签: {escape(str(lbl))} "
                f"&nbsp;·&nbsp; 端口: {escape(str(f_port))} → {escape(str(t_port))}<br>"
                f"<span style='color:#58a6ff;'>{sim_tag}</span>: "
                f"<span style='color:#7ee787;'>{value}</span>"
            )
            self.link_body.setText(html)
            self.link_card.setVisible(True)
            self.link_card.raise_()
        except Exception:
            pass


def _sig_shape(v):
    """返回变量形状: 标量 / 数组 shape 元组"""
    import numpy as _np
    if isinstance(v, str):
        return "str"
    a = _np.asarray(v)
    if a.ndim == 0:
        return "标量"
    return str(tuple(a.shape))


# ═══ 🎨 RGB-D 俯视图渲染 (2026-08-22 老倪: 数据总线右键 → 渲染成图片) ═══
_RGBD_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


def _rgbd_font(size, mono=False):
    from PIL import ImageFont
    mono_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    cands = [mono_path] if mono else _RGBD_FONT_CANDIDATES
    for f in cands:
        if os.path.isfile(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _ss_project(pt, cam, R, f, W, H, cx, cy):
    """透视投影 3D→2D, 返回 (u, v, depth) 或 (None,None,None)"""
    import numpy as np
    pc = R @ (np.asarray(pt, dtype=float) - np.asarray(cam, dtype=float))
    z = -pc[2]
    if z < 0.05:
        return None, None, None
    u = f * pc[0] / z + cx
    v = -f * pc[1] / z + cy
    return u, v, z


def _ss_draw_box(d, cam, R, f, W, H, cx, cy, center, size, fill):
    """透视投影画 3D 长方体 (画家算法: 远面先画)"""
    x0, y0, z0 = center
    sx, sy, sz = size
    verts = [(x0 + dx * sx / 2, y0 + dy * sy / 2, z0 + dz * sz / 2)
             for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 5, 7, 6), (0, 1, 5, 4),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 3, 7, 5)]
    proj = [_ss_project(v, cam, R, f, W, H, cx, cy) for v in verts]
    fl = []
    for fc in faces:
        pts = [proj[i] for i in fc]
        if any(p[0] is None for p in pts):
            continue
        avgz = sum(p[2] for p in pts) / 4.0
        fl.append((avgz, [(p[0], p[1]) for p in pts]))
    fl.sort(key=lambda a: -a[0])
    for _, pts in fl:
        d.polygon(pts, fill=fill)


_MW_RENDER_CACHE = {}  # {camera_name: {"frames":..,"dists":..}} 按相机视角懒加载缓存
import threading as _threading_mw
_MW_RENDER_LOCK = _threading_mw.Lock()  # 并发开多视角时串行化环境创建 (EGL 上下文防冲突)

# 真实数据有的 7 个相机视角 (2026-08-23 老倪: 右键要能选不同视角)
_MW_CAMERAS = [
    ("corner2", "corner2 角落 · 模型训练视角"),
    ("gripperPOV", "gripperPOV 夹爪第一视角(腕部)"),
    ("behindGripper", "behindGripper 夹爪后方"),
    ("topview", "topview 俯视"),
    ("corner", "corner 角落"),
    ("corner3", "corner3 角落3"),
    ("corner4", "corner4 角落4"),
]


def _get_metaworld_view(camera_name="corner2"):
    """懒加载指定相机视角的 metaworld 环境 + 官方专家策略, 预渲染真实插拔轨迹帧 (2026-08-23 老倪: 真实RGB+多视角)"""
    global _MW_RENDER_CACHE
    with _MW_RENDER_LOCK:
        if camera_name in _MW_RENDER_CACHE:
            return _MW_RENDER_CACHE[camera_name] or None
        cache = {}
        try:
            import os
            try:
                from mujoco_gl import setup_mujoco_gl as _setup_gl  # 平台自适应 (mac cgl / win wgl)
                _setup_gl("egl")
            except Exception:
                os.environ.setdefault("MUJOCO_GL", "egl")
            os.environ.setdefault("DISPLAY", ":0")
            import numpy as np
            import metaworld as mw
            from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
            mt1 = mw.MT1("peg-insert-side-v3")
            env = mt1.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name=camera_name)
            env.set_task(mt1.train_tasks[0])
            env._freeze_rand_vec = False
            pol = SawyerPegInsertionSideV3Policy()
            pid = env.model.site("pegGrasp").id
            hid = env.model.site("hole").id
            hbid = env.model.body("hand").id
            cid = env.model.cam(camera_name).id
            obs, _info = env.reset(seed=1)
            obs = np.asarray(obs, dtype=np.float64)
            cam = {"pos": np.asarray(env.model.cam_pos[cid], dtype=float),
                   "mat": np.asarray(env.model.cam_mat0[cid], dtype=float).reshape(3, 3).T,
                   "fovy": float(env.model.cam_fovy[cid])}
            frames, dists, peg_traj, hole_traj, hand_traj = [], [], [], [], []
            for _step in range(150):
                act = np.asarray(pol.get_action(obs), dtype=np.float64)
                obs, _r, _term, _trunc, _i = env.step(act)
                obs = np.asarray(obs, dtype=np.float64)
                peg = env.data.site_xpos[pid]
                hole = env.data.site_xpos[hid]
                hand = env.data.xpos[hbid]
                dists.append(float(np.linalg.norm(peg[:2] - hole[:2])))
                peg_traj.append(peg.copy())
                hole_traj.append(hole.copy())
                hand_traj.append(hand.copy())
                frames.append(np.rot90((np.zeros((480, 480, 3), dtype=np.uint8) if (__import__('sys').platform == 'darwin' and __import__('os').environ.get('SS_MAC_RENDER') != '1') else np.asarray(env.render())), k=2))  # 180°旋转方向修正
            H, W = frames[0].shape[:2]
            cam["W"], cam["H"] = W, H
            cache = {"frames": frames, "dists": np.asarray(dists),
                     "peg": np.asarray(peg_traj), "hole": np.asarray(hole_traj),
                     "hand": np.asarray(hand_traj), "cam": cam}
        except Exception:
            cache = {}
        _MW_RENDER_CACHE[camera_name] = cache
        return cache or None


# 🗑 2026-10-09 老倪「没有用的都删掉」: 原 `_project_3d_to_2d(p, cam)` 全仓零调用 (仅定义无引用) → 已删除。
#    3D→2D 投影现由画布 overlay 链路各自的实现负责 (simulink_module / state_space_sim_real)。


_YOLO_MODEL = None


def _yolo_weights_path():
    """训练好的 YOLO 光模块 权重 (best.pt) — 搜索候选路径 (ultralytics runs_dir 可能改)"""
    import os
    _root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    _cands = [
        os.path.join(_root, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt"),
        os.path.join(_root, "outputs", "yolo_peg", "peg_v1", "weights", "best.pt"),
    ]
    for c in _cands:
        if os.path.exists(c):
            return c
    return _cands[0]


def _get_yolo_model():
    """懒加载训练好的 YOLO 权重 (全局缓存; 后台线程调用, 首次加载较慢)"""
    global _YOLO_MODEL
    if _YOLO_MODEL is None:
        from ultralytics import YOLO
        _YOLO_MODEL = YOLO(_yolo_weights_path())
    return _YOLO_MODEL


def _detect_frame(frame, conf=0.25):
    """真实 YOLO 推理: frame(RGB uint8) → [(cls, conf, x1, y1, x2, y2)]"""
    import cv2
    model = _get_yolo_model()
    img_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)  # ultralytics 数组必须 BGR
    res = model.predict(img_bgr, conf=conf, verbose=False)[0]
    out = []
    for b in res.boxes:
        cls = res.names[int(b.cls)]
        cf = float(b.conf[0])
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        out.append((cls, cf, x1, y1, x2, y2))
    return out


def render_bbox_frame(idx, camera_name="corner2"):
    """🖼 渲染真实 YOLO 检测框: metaworld 相机视角 + YOLO 模型真推理 (框+conf 都是模型输出, 2026-08-23)"""
    from PIL import Image, ImageDraw
    mw = _get_metaworld_view(camera_name)
    if not mw or not mw.get("frames"):
        return None
    idx = int(np.clip(idx, 0, len(mw["frames"]) - 1))
    frame = mw["frames"][idx]
    img = Image.fromarray(frame).convert("RGB")
    d = ImageDraw.Draw(img)
    f = _rgbd_font(14)
    try:
        dets = _detect_frame(frame)
    except Exception as ex:
        d.text((8, 8), f"YOLO 推理失败: {str(ex)[:60]}", font=_rgbd_font(13), fill="#ff5555")
        return img
    if not dets:
        d.text((8, 8), f"YOLO 无检测 (conf<0.25) · {camera_name} · 帧#{idx}", font=_rgbd_font(15), fill="#ffa500")
        return img
    colors = {"hand": "#58a6ff", "光模块": "#00d4aa", "hole": "#ffa500"}
    for cls, cf, x1, y1, x2, y2 in dets:
        color = colors.get(cls, "#e6edf3")
        d.rectangle([int(x1), int(y1), int(x2), int(y2)], outline=color, width=3)
        d.text((int(x1), max(0, int(y1) - 16)), f"{cls} {cf:.2f}", font=f, fill=color)
    d.text((8, 8), f"YOLO 检测 · {camera_name} · 帧#{idx} · {len(dets)} 目标", font=_rgbd_font(15), fill="#ffffff")
    return img


def render_rgbd_frame(tr, idx, camera_name="corner2"):
    """渲染 RGB-D 图像: 真实 metaworld 渲染 (优先, 可选相机视角) + Depth; 失败退回 3D 透视手绘 (2026-08-22/23 老倪)"""
    from PIL import Image, ImageDraw
    import numpy as np
    from state_space_sim import HOLE_POS, X0
    x = np.asarray(tr["x"])[idx]

    # ── 🎨 真实 metaworld 渲染 (2026-08-23 老倪: 优先真实RGB, 失败退回手绘) ──
    mw = _get_metaworld_view(camera_name)
    if mw and mw.get("frames"):
        try:
            _cur = float(np.linalg.norm(x[:2] - HOLE_POS[:2]))
            _d0 = float(np.linalg.norm(X0[:2] - HOLE_POS[:2]))
            _prog = float(np.clip(1.0 - _cur / max(_d0, 1e-6), 0.0, 1.0))
            _mw0 = float(mw["dists"][0])
            _mwe = float(mw["dists"].min())
            _target = _mw0 - _prog * (_mw0 - _mwe)
            _fi = int(np.argmin(np.abs(mw["dists"] - _target)))
            _frame = mw["frames"][_fi]
            _rgb = Image.fromarray(_frame)
            _dep = Image.fromarray(_frame).convert("L")
            _W, _H = _rgb.size
            _gap = 12
            _out = Image.new("RGB", (_W * 2 + _gap, _H), "#0d1117")
            _out.paste(_rgb, (0, 0))
            _out.paste(_dep.convert("RGB"), (_W + _gap, 0))
            _d = ImageDraw.Draw(_out)
            _f = _rgbd_font(16)
            _stage = tr["stage"][idx].replace("阶段 ", "")
            _d.text((12, 8), f"t={tr['t'][idx]:.2f}s · {_stage} · {camera_name}", font=_f, fill="#ffffff")
            _d.text((12, _H - 24), f"插拔进度 {_prog * 100:.0f}%", font=_f, fill="#ffffff")
            return _out
        except Exception:
            pass
    g = float(tr["gripper"][idx])
    stage = tr["stage"][idx].replace("阶段 ", "")
    t = tr["t"][idx]
    W = H = 500
    # 相机 (斜上方偏左前, 看向工作区)
    cam = (0.05, -0.55, 0.42)
    target = (0.22, 0.0, 0.03)
    up = (0, 0, 1)
    f = 520
    cx, cy = W / 2.0, H / 2.0
    fwd = np.array(target) - np.array(cam)
    fwd = fwd / np.linalg.norm(fwd)
    right = np.cross(fwd, up)
    right = right / np.linalg.norm(right)
    up2 = np.cross(right, fwd)
    R = np.array([right, up2, -fwd])

    # ── RGB 图 (3D 透视场景) ──
    img = Image.new("RGB", (W, H), "#0d1117")
    d = ImageDraw.Draw(img)
    # 工作台平面 (z=0)
    corners = [(-0.05, -0.20, 0.0), (0.42, -0.20, 0.0), (0.42, 0.20, 0.0), (-0.05, 0.20, 0.0)]
    pc = [_ss_project(c, cam, R, f, W, H, cx, cy) for c in corners]
    if all(p[0] is not None for p in pc):
        d.polygon([(p[0], p[1]) for p in pc], fill="#2a3038")
    # 插座 (孔位, 深红座)
    _ss_draw_box(d, cam, R, f, W, H, cx, cy, (HOLE_POS[0], HOLE_POS[1], 0.02), (0.08, 0.08, 0.04), "#7a2520")
    # 光模块 光模块 (金色金属壳, 随末端移动)
    _ss_draw_box(d, cam, R, f, W, H, cx, cy, (x[0], x[1], x[2]), (0.055, 0.032, 0.032), "#c9a227")
    # 末端夹爪 (蓝色, 在光模块上方抓着)
    _ss_draw_box(d, cam, R, f, W, H, cx, cy, (x[0], x[1], x[2] + 0.038), (0.065, 0.045, 0.02), "#3d7dd8")
    # 标签
    f_ = _rgbd_font(15)
    d.text((12, 8), f"t={t:.2f}s · {stage}", font=f_, fill="#c9d1d9")

    # ── Depth 图 (灰度深度: 近亮远暗) ──
    dep = Image.new("L", (W, H), 18)
    dd = ImageDraw.Draw(dep)
    if all(p[0] is not None for p in pc):
        dd.polygon([(p[0], p[1]) for p in pc], fill=40)
    _ss_draw_box(dd, cam, R, f, W, H, cx, cy, (HOLE_POS[0], HOLE_POS[1], 0.02), (0.08, 0.08, 0.04), 150)
    _ss_draw_box(dd, cam, R, f, W, H, cx, cy, (x[0], x[1], x[2]), (0.055, 0.032, 0.032), 220)
    _ss_draw_box(dd, cam, R, f, W, H, cx, cy, (x[0], x[1], x[2] + 0.038), (0.065, 0.045, 0.02), 245)
    dd.text((12, 8), "Depth", font=f_, fill=180)
    dd.text((12, H - 26), f"peg z={x[2]:.3f}m", font=f_, fill=160)

    # ── 并排合成 RGB + Depth ──
    gap = 12
    out = Image.new("RGB", (W * 2 + gap, H), "#0d1117")
    out.paste(img, (0, 0))
    out.paste(dep.convert("RGB"), (W + gap, 0))
    return out


def _sig_val(v):
    """返回变量数值: 标量→4位小数, 向量→完整显示所有维度(不省略)"""
    import numpy as _np
    if isinstance(v, str):
        return v
    if isinstance(v, (bool, _np.bool_)):
        return "True" if v else "False"
    a = _np.asarray(v)
    if a.ndim == 0:
        return f"{float(a):.4f}"
    flat = _np.asarray(a, dtype=float).ravel()
    return "[" + ", ".join(f"{x:.4f}" for x in flat) + "]"


# 🗑 2026-10-09 老倪「没有用的都删掉」: 原 `_fmt_sig(v)` (仅 `return _sig_val(v)`) 全仓零调用 → 已删除。
#    (同文件 _sig_val 仍在用; 这个只是一层没人调的别名壳)

