#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗺 迭代路线图 · Phase 0→4 ｜ 迭代验证 ｜ 对比分析  (Z-MAX 主控制台「评估分析」页, 老倪 2026-10-15)

老倪原话: 「按照控制台的产品迭代 roadmap phase 0开始 到phase 4 通过元任务的升级组合, 逐步实现每个阶段的
主要性能指标。我要你的迭代路线图, 在评估分析功能区, 迭代验证, 对比分析」

本控件**只显示不计算** (与 studio.EvalModule 同一条纪律: 一处真源, 多处显示), 真源就一个文件:
  zmax_data/eval/iteration_roadmap.json   (由 tools/iteration_roadmap.py 生成 — 本控件只读它)

三条硬纪律 (与全站一致):
  · 文件不在 / 字段缺失 ⇒ 一律显示「尚未生成 · 点『🔄 重跑迭代验证』生成」,**绝不显示假 0 冒充**。
  · 重跑 = subprocess 调 ./gui-venv311/bin/python tools/iteration_roadmap.py, 带超时;
    失败必须把**真实错误 + 退出码**显示在界面上 (不许静默)。
  · 颜色语义与全站一致: 达标=绿 · 未达标=红 · 未测/样本不足=灰 · 提升=绿 · 回退=红 · 持平=灰;
    数字右对齐, 单位统一一列; 实时数据标证据类 + 样本量 + 帧龄。

🔌🧩 同一页同一风格再扩一层**场景切换** (老倪 2026-10-15): 「🔌 插拔 (TASK-01-FW)」「🧩 摆盘 (TASK-06-TRAY)」,
默认显示当前激活任务(config/ss_task_binding.json 的 active_task)对应场景; 每场景三个子视图:
  (a) 组合迭代   Phase 0→4 逐阶段一行: 阶段/主题/指标数/元任务组合(carried·added·upgraded, 点击行折叠展开)/总数量/上阶段增量/准入门
  (b) 迭代验证   逐阶段 实测 vs 目标 + **配置完备性核验** (coverage N/N · missing/extra 明细 · 能否作改配置依据) + run.mode(实跑/未跑+原因)
  (c) 对比分析   ① 场景×阶段矩阵 (并列 / 只看 FW / 只看 TRAY) ② 两场景逐阶段达标率 ③ 组合增量对比 ④ 与基线 5.50.735 对比(提升/持平/回退)
  真源: zmax_data/eval/scene_phase_iteration.json (tools/scene_phase_iteration.py 产出) · 独立『🔄 重跑场景迭代』按钮
  ⇒ 缺失/未测一律显「尚未生成 / 未测」,**绝不显示假 0**。

自检 / 截图 (任一可用):
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/iteration_roadmap_panel.py --selftest
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/iteration_roadmap_panel.py \
        --shot /tmp/irm.png --tab 0 [--path <json>] [--rerun]
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/iteration_roadmap_panel.py \
        --shot /tmp/scene.png --tab 3 [--scene-json <json>] [--scene FW|TRAY] \
        [--scene-tab 0|1|2] [--scene-mode 0|1|2] [--expand] [--grab-scene] [--scene-rerun]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
                             QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
                             QToolButton, QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JSON_PATH = os.path.join(ROOT, "zmax_data", "eval", "iteration_roadmap.json")
TOOL = os.path.join(ROOT, "tools", "iteration_roadmap.py")
VENV_PY = os.path.join(ROOT, "gui-venv311", "bin", "python")

# ── 颜色语义 (与 studio.py 同色; 达标/提升=绿 · 未达标/回退=红 · 未测/样本不足/持平=灰) ──
C_GREEN = "#3fb950"
C_RED = "#f85149"
C_GRAY = "#8b949e"
C_ORANGE = "#d29922"
C_WHITE = "#e6edf3"
C_BG = "#0d1117"
C_CARD = "#1c2333"
C_BORDER = "#30363d"
C_CYAN = "#39d2c0"
SYSColor = "#39d2c0"

VC = {"达标": C_GREEN, "未达标": C_RED, "未测": C_GRAY, "样本不足": C_GRAY}   # 判定 → 色
BC = {"提升": C_GREEN, "回退": C_RED, "持平": C_GRAY, "未测": C_GRAY}          # vs 基线 → 色
# 未测 / 样本不足 排最后 (单列, 如实标注, 不冒充实测)
_VERDICT_ORDER = {"达标": 0, "未达标": 1, "样本不足": 2, "未测": 3}


def _fnum(v, unit=""):
    """数值统一格式: None ⇒ '未测' (不显示假 0); 浮点用 %.4g。"""
    if v is None or v == "":
        return "未测"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        s = "%.4g" % v
        return s
    return str(v)


def _ts_str(ts):
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        return "—"
    if ts <= 0:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _phase_key(p):
    """'Phase 3' → 3 (排序用); 无法解析给大数。"""
    try:
        return int(str(p).split()[-1])
    except (ValueError, IndexError):
        return 99


class IterationRoadmapPanel(QGroupBox):
    """评估分析页内嵌的迭代路线图控件 (只读 JSON + 重跑 + 复制/导出)。"""

    def __init__(self, parent=None, path=None):
        super().__init__("🗺 迭代路线图 · Phase 0→4 ｜ 迭代验证 ｜ 对比分析", parent)
        self.JSON = path or JSON_PATH
        self.data = None
        self.read_err = ""
        self._build()
        self.reload()

    # ─────────────────────────── 骨架 ───────────────────────────
    def _build(self):
        self.setStyleSheet(
            f"QGroupBox{{color:{C_WHITE}; font-weight:bold;"
            f" background:{C_BG}; border:1px solid {C_BORDER}; border-radius:8px;"
            f" margin-top:10px; padding:12px;}}"
            f" QGroupBox::title{{subcontrol-origin:margin; left:12px; padding:0 6px; color:{C_CYAN};}}")
        root = QVBoxLayout()
        root.setSpacing(8)

        # 头部: 元信息 (版本/基线/生成时间/生成者) + 动作按钮
        head = QHBoxLayout()
        head.setSpacing(10)
        self.lb_meta = QLabel("真源: —")
        self.lb_meta.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_meta.setWordWrap(True)
        self.lb_meta.setStyleSheet(f"color:{C_GRAY}; font-size:14px; border:none;")
        head.addWidget(self.lb_meta, 1)
        for txt, fn, hover in (
                ("🔄 重跑迭代验证", self.rerun, C_CYAN),
                ("📋 复制当前视图", self.copy_view, C_GREEN),
                ("📄 导出 Markdown", self.export_md, C_BORDER),
                ("💾 导出 CSV", self.export_csv, C_BORDER)):
            b = QPushButton(txt)
            b.setStyleSheet(
                f"QPushButton{{background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                f" border-radius:6px; padding:7px 12px; font-weight:bold;}}"
                f" QPushButton:hover{{border-color:{hover};}}")
            b.clicked.connect(fn)
            head.addWidget(b)
        root.addLayout(head)

        # 状态横幅: 尚未生成 / 读取失败 都在这 (始终可见)
        self.lb_status = QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_status.setStyleSheet(f"color:{C_ORANGE}; font-size:15px; font-weight:700; border:none;")
        self.lb_status.setVisible(False)
        root.addWidget(self.lb_status)

        # 三个子视图
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {C_BORDER}; border-radius:6px; background:{C_BG};}}"
            f" QTabBar::tab{{background:{C_CARD}; color:{C_GRAY}; padding:8px 16px;"
            f" border:1px solid {C_BORDER}; border-bottom:none; font-size:14px;}}"
            f" QTabBar::tab:selected{{color:{C_WHITE}; border-color:{C_CYAN};}}")
        self.tabs.addTab(self._build_roadmap_tab(), "🗺 迭代路线图 (Phase 0→4)")
        self.tabs.addTab(self._build_verify_tab(), "✅ 迭代验证 (实测 vs 目标)")
        self.tabs.addTab(self._build_compare_tab(), "📊 对比分析 (趋势 + 基线)")
        # 🔌🧩 2026-10-15 老倪: 场景(插拔/摆盘) × Phase 0→4 全流程迭代元任务组合 (组合迭代/迭代验证/对比分析)
        self.scene_view = ScenePhaseIterationView(self)
        self.tabs.addTab(self.scene_view, "🔌🧩 场景迭代 (插拔/摆盘 × Phase 0→4)")
        self.tabs.currentChanged.connect(lambda _i: self._render_tabs())
        root.addWidget(self.tabs, 1)

        # 重跑日志 (可复制; 失败显示真实退出码 + 错误)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 10))
        self.log.setFixedHeight(96)
        self.log.setStyleSheet(f"background:{C_BG}; color:{C_GRAY}; border:1px solid {C_BORDER};"
                               f" border-radius:6px; padding:6px;")
        root.addWidget(self.log)
        self.setLayout(root)

    # ─────────────────────────── 子视图 ①: 迭代路线图 ───────────────────────────
    def _build_roadmap_tab(self):
        self.road_host = QWidget()
        self.road_lay = QVBoxLayout(self.road_host)
        self.road_lay.setSpacing(10)
        self.road_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none; background:transparent;}}")
        scroll.setWidget(self.road_host)
        return scroll

    # ─────────────────────────── 子视图 ②: 迭代验证 ───────────────────────────
    def _build_verify_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(QLabel("筛选:"))
        self.flt = QComboBox()
        self.flt.addItems(["全部", "仅达标", "仅未达标", "仅未测/样本不足"])
        self.flt.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                               f" border-radius:4px; padding:5px 10px;")
        self.flt.currentIndexChanged.connect(lambda _i: self._render_verify())
        top.addWidget(self.flt)
        top.addStretch()
        self.lb_vsum = QLabel("—")
        self.lb_vsum.setStyleSheet(f"color:{C_WHITE}; font-size:14px; font-weight:700; border:none;")
        top.addWidget(self.lb_vsum)
        v.addLayout(top)

        self.vtab = QTableWidget(0, len(self.VCOLS))
        self.vtab.setHorizontalHeaderLabels(self.VCOLS)
        self._style_table(self.vtab)
        for i, wd in enumerate((90, 150, 96, 62, 176, 84, 96, 70, 76, 340)):
            self.vtab.setColumnWidth(i, wd)
        self.vtab.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.vtab, 1)
        return w

    VCOLS = ["阶段", "性能指标", "实测值", "单位", "目标", "判定", "证据类", "样本量", "帧龄(s)", "真源/备注"]

    # ─────────────────────────── 子视图 ③: 对比分析 ───────────────────────────
    def _build_compare_tab(self):
        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setSpacing(12)

        # ① 阶段间趋势
        g1 = QLabel("① 阶段间趋势 (P0→P4 每个指标的值序列)")
        g1.setStyleSheet(f"color:{C_CYAN}; font-size:15px; font-weight:700; border:none;")
        outer.addWidget(g1)
        self.ttab = QTableWidget(0, len(self.TCOLS))
        self.ttab.setHorizontalHeaderLabels(self.TCOLS)
        self._style_table(self.ttab)
        for i, wd in enumerate((150, 62, 70, 70, 70, 70, 70, 196, 90)):
            self.ttab.setColumnWidth(i, wd)
        _th = self.ttab.horizontalHeader()                  # 指标名这一列吃满余量 (别把空列拉宽)
        _th.setStretchLastSection(False)
        _th.setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self.ttab, 1)

        # ② 与基线对比
        g2 = QLabel("② 与基线 (5.50.735) 对比 · 提升/持平/回退 + 逐阶段达标率")
        g2.setStyleSheet(f"color:{C_CYAN}; font-size:15px; font-weight:700; border:none;")
        outer.addWidget(g2)
        self.lb_base = QLabel("—")
        self.lb_base.setWordWrap(True)
        self.lb_base.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_base.setStyleSheet(f"color:{C_WHITE}; font-size:14px; border:none;")
        outer.addWidget(self.lb_base)
        self.btab = QTableWidget(0, len(self.BCOLS))
        self.btab.setHorizontalHeaderLabels(self.BCOLS)
        self._style_table(self.btab)
        for i, wd in enumerate((90, 160, 96, 96, 92, 84)):
            self.btab.setColumnWidth(i, wd)
        _bh = self.btab.horizontalHeader()
        _bh.setStretchLastSection(False)
        _bh.setSectionResizeMode(1, QHeaderView.Stretch)    # 指标名吃余量
        outer.addWidget(self.btab, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")
        scroll.setWidget(host)
        return scroll

    TCOLS = ["性能指标", "单位", "P0", "P1", "P2", "P3", "P4", "目标", "趋势判定"]
    BCOLS = ["阶段", "性能指标", "基线", "当前", "Δ", "判定"]

    # ─────────────────────────── 通用表格样式 ───────────────────────────
    def _style_table(self, t):
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setMinimumHeight(200)
        t.setStyleSheet(
            f"QTableWidget{{background:{C_BG}; color:{C_WHITE}; gridline-color:{C_BORDER};"
            f" font-size:13px;}} QHeaderView::section{{background:{C_CARD}; color:{C_WHITE};"
            f" padding:6px; border:0;}}")

    @staticmethod
    def _item(text, color=None, bold=False, right=False):
        it = QTableWidgetItem(str(text))
        if color:
            it.setForeground(QColor(color))
        if bold:
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        if right:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    # ─────────────────────────── 读取真源 ───────────────────────────
    def reload(self):
        self.read_err = ""
        self.data = None
        if not os.path.exists(self.JSON):
            self.read_err = "尚未生成"
        else:
            try:
                with open(self.JSON, encoding="utf-8") as fh:
                    d = json.load(fh)
                if not isinstance(d, dict):
                    self.read_err = "文件格式不对 (顶层不是对象)"
                else:
                    self.data = d
            except Exception as e:                                              # noqa: BLE001
                self.read_err = "读取失败: %s" % e
        self._render_all()
        if getattr(self, "scene_view", None) is not None:
            self.scene_view.reload()        # 🔌🧩 场景迭代真源是另一个文件 ⇒ 一起刷新 (缺失也不崩)

    def _phases(self):
        ph = (self.data or {}).get("phases") or []
        return sorted([p for p in ph if isinstance(p, dict)],
                      key=lambda p: _phase_key(p.get("phase", ""))) if isinstance(ph, list) else []

    def _render_all(self):
        d = self.data
        meta = (d or {}).get("meta") or {}
        if d is None:
            self.lb_meta.setText("真源: %s ｜ 版本 — ｜ 基线 — ｜ 生成时间 —"
                                 % os.path.relpath(self.JSON, ROOT))
            if self.read_err and self.read_err != "尚未生成":
                self.lb_status.setText("⛔ 真源读取失败 — %s ｜ 点『🔄 重跑迭代验证』重新生成  (真源: %s)"
                                       % (self.read_err, os.path.relpath(self.JSON, ROOT)))
            else:
                self.lb_status.setText("⛔ 尚未生成 — 点『🔄 重跑迭代验证』生成  (真源: %s)"
                                       % os.path.relpath(self.JSON, ROOT))
            self.lb_status.setStyleSheet(f"color:{C_ORANGE}; font-size:15px; font-weight:700; border:none;")
            self.lb_status.setVisible(True)
        else:
            self.lb_meta.setText(
                "真源: %s ｜ 版本 %s ｜ 基线 %s ｜ 生成时间 %s ｜ 生成者 %s"
                % (os.path.relpath(self.JSON, ROOT), meta.get("version") or "—",
                   meta.get("baseline") or "—", _ts_str(meta.get("ts")),
                   meta.get("generated_by") or "—"))
            self.lb_status.setText("")
            self.lb_status.setVisible(False)
        self._render_roadmap()
        self._render_verify()
        self._render_compare()

    def _render_tabs(self):
        # 切页时重渲染当前页 (内容随真源更新)
        idx = self.tabs.currentIndex()
        if idx == 3:                                                            # 🔌🧩 场景迭代
            sv = getattr(self, "scene_view", None)
            if sv is not None:
                sv._render_all()
            return
        (self._render_roadmap, self._render_verify, self._render_compare)[idx]()

    # ─────────────────────────── 渲染 ①: 路线图卡 ───────────────────────────
    def _clear_layout(self, lay):
        while lay.count() > 1:                                                   # 末尾留 stretch
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _render_roadmap(self):
        self._clear_layout(self.road_lay)
        phases = self._phases()
        if not phases:
            self._hint_into(self.road_lay, "尚未生成迭代路线 — 点『🔄 重跑迭代验证』生成")
            return
        for ph in phases:
            self.road_lay.insertWidget(self.road_lay.count() - 1, self._phase_card(ph))

    def _hint_into(self, lay, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color:{C_GRAY}; font-size:15px; padding:24px; border:none;")
        lay.insertWidget(max(0, lay.count() - 1), lbl)

    def _phase_card(self, ph):
        card = QFrame()
        card.setStyleSheet(f"background:{C_CARD}; border:1px solid {C_BORDER}; border-left:3px solid {C_CYAN};"
                           f" border-radius:8px;")
        v = QVBoxLayout(card)
        v.setSpacing(6)

        head = QHBoxLayout()
        pid = QLabel(str(ph.get("phase") or "?"))
        pid.setFont(QFont("Consolas", 13, QFont.Bold))
        pid.setStyleSheet(f"color:{C_CYAN}; background:{C_CYAN}22; border:1px solid {C_CYAN}44;"
                          f" border-radius:3px; padding:2px 8px;")
        head.addWidget(pid)
        nm = QLabel(str(ph.get("name") or "—"))
        nm.setFont(QFont("Arial", 13, QFont.Bold))
        nm.setStyleSheet(f"color:{C_WHITE}; border:none; background:transparent;")
        head.addWidget(nm)
        head.addStretch()
        tm = ph.get("target_metrics") or []
        head.addWidget(self._chip("主要指标 %d 项" % len(tm), C_GRAY))
        v.addLayout(head)

        # 主要性能指标 (名称 + 目标)
        if tm:
            lbl = QLabel("主要性能指标 (目标):")
            lbl.setStyleSheet(f"color:{C_GRAY}; font-size:13px; border:none; background:transparent;")
            v.addWidget(lbl)
            for m in tm:
                if not isinstance(m, dict):
                    continue
                unit = m.get("unit") or ""
                tgt = m.get("target")
                tgt_s = ("%s %s" % (tgt, unit)).strip() if tgt not in (None, "") else "未定目标"
                row = QLabel("· %s   目标 %s" % (m.get("name") or m.get("id") or "—", tgt_s))
                row.setWordWrap(True)
                row.setTextInteractionFlags(Qt.TextSelectableByMouse)
                row.setStyleSheet(f"color:{C_WHITE}; font-size:13px; border:none; background:transparent;")
                row.setToolTip("指标 ID: %s ｜ 分组: %s" % (m.get("id") or "—", m.get("group") or "—"))
                v.addWidget(row)
        else:
            v.addWidget(self._gray("主要性能指标: 尚未提供"))

        # 元任务升级组合 (可折叠)
        mc = ph.get("meta_combo") or {}
        base = mc.get("baseline") or []
        added = mc.get("added") or []
        upg = mc.get("upgraded") or []
        if base or added or upg:
            tgl = QToolButton()
            tgl.setCheckable(True)
            tgl.setStyleSheet(f"QToolButton{{color:{C_ORANGE}; border:none; background:transparent;"
                              f" font-size:13px; font-weight:700;}}")
            tgl.setText("▸ 元任务升级组合 (基线 %d · 新增 %d · 升级 %d)"
                        % (len(base), len(added), len(upg)))
            detail = QWidget()
            dl = QVBoxLayout(detail)
            dl.setContentsMargins(16, 2, 0, 2)
            dl.setSpacing(3)
            dl.addWidget(self._gray("基线元任务: " + (", ".join(map(str, base)) if base else "—")))
            for tag, seq, clr in (("新增", added, C_GREEN), ("升级", upg, C_ORANGE)):
                if not seq:
                    continue
                for it in seq:
                    if isinstance(it, dict):
                        txt = "%s: %s  %s" % (tag, it.get("fn_id") or "—", it.get("name") or "")
                    else:
                        txt = "%s: %s" % (tag, it)
                    lb = QLabel(txt)
                    lb.setWordWrap(True)
                    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    lb.setStyleSheet(f"color:{clr}; font-size:13px; border:none; background:transparent;")
                    dl.addWidget(lb)
            if not added and not upg:
                dl.addWidget(self._gray("本阶段无新增/升级元任务"))
            detail.setVisible(False)
            tgl.toggled.connect(lambda on, d=detail, t=tgl, b=len(base), a=len(added), u=len(upg):
                                (d.setVisible(on),
                                 t.setText(("▾" if on else "▸") +
                                           " 元任务升级组合 (基线 %d · 新增 %d · 升级 %d)" % (b, a, u))))
            v.addWidget(tgl)
            v.addWidget(detail)
        else:
            v.addWidget(self._gray("元任务升级组合: 尚未提供"))
        return card

    @staticmethod
    def _gray(t):
        lb = QLabel(t)
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lb.setStyleSheet(f"color:{C_GRAY}; font-size:13px; border:none; background:transparent;")
        return lb

    @staticmethod
    def _chip(t, color):
        lb = QLabel(t)
        lb.setStyleSheet(f"color:{color}; background:{color}22; border:1px solid {color}44;"
                         f" border-radius:3px; padding:2px 8px; font-size:12px;")
        return lb

    # ─────────────────────────── 渲染 ②: 迭代验证 ───────────────────────────
    def _render_verify(self):
        phases = self._phases()
        self.vtab.setRowCount(0)
        if not phases:
            self.lb_vsum.setText("尚未生成迭代验证 — 点『🔄 重跑迭代验证』生成")
            self.lb_vsum.setStyleSheet(f"color:{C_GRAY}; font-size:14px; font-weight:700; border:none;")
            return
        f = self.flt.currentIndex()
        tot = {"达标": 0, "未达标": 0, "未测": 0, "样本不足": 0}
        rows = []                                                                # (phase, metric)
        for ph in phases:
            vd = ph.get("verification") or {}
            ms = vd.get("metrics") or []
            ms = [m for m in ms if isinstance(m, dict)]
            ms = sorted(ms, key=lambda m: _VERDICT_ORDER.get(str(m.get("verdict") or ""), 4))
            for k in tot:
                tot[k] += int(vd.get(k, 0) or 0) if not ms else 0
            for m in ms:
                v = m.get("verdict") or "未测"
                if f == 1 and v != "达标":
                    continue
                if f == 2 and v != "未达标":
                    continue
                if f == 3 and v not in ("未测", "样本不足"):
                    continue
                rows.append((ph, m))
        # 阶段汇总 (用 verification 的计数, 无 metrics 时退回逐条数)
        if not any(tot.values()):
            for ph in phases:
                for m in (ph.get("verification") or {}).get("metrics") or []:
                    k = (m or {}).get("verdict")
                    if k in tot:
                        tot[k] += 1
        self.lb_vsum.setText("达标 %d · 未达标 %d · 未测 %d · 样本不足 %d ｜ 显示 %d 行"
                             % (tot["达标"], tot["未达标"], tot["未测"], tot["样本不足"], len(rows)))
        self.lb_vsum.setStyleSheet(f"color:{C_WHITE}; font-size:14px; font-weight:700; border:none;")

        self.vtab.setRowCount(len(rows))
        for i, (ph, m) in enumerate(rows):
            v = m.get("verdict") or "未测"
            col = VC.get(v, C_GRAY)
            n = m.get("n")
            age = m.get("age_s")
            vals = [ph.get("phase") or "", m.get("name") or m.get("id") or "",
                    _fnum(m.get("value")), m.get("unit") or "", str(m.get("target") or "—"),
                    v, m.get("mode") or "未测",
                    ("—" if (n in (None, "") or v == "未测") else str(n)),
                    ("—" if age in (None, "", -1, -1.0) else "%.0f" % age),
                    m.get("src") or m.get("note") or ""]
            for j, t in enumerate(vals):
                it = self._item(t, color=(col if j == 5 else None), bold=(j == 5),
                                right=(j in (2, 7, 8)))
                if j in (2, 5) and v in ("未测", "样本不足"):
                    it.setForeground(QColor(C_GRAY))
                it.setToolTip("%s ｜ 判定 %s ｜ 证据类 %s ｜ 样本量 %s ｜ 帧龄 %s\n目标: %s\n真源: %s\n备注: %s"
                              % (m.get("name") or m.get("id"), v, m.get("mode"), n, age,
                                 m.get("target"), m.get("src"), m.get("note")))
                self.vtab.setItem(i, j, it)
        self.vtab.resizeRowsToContents()

    # ─────────────────────────── 渲染 ③: 对比分析 ───────────────────────────
    def _render_compare(self):
        cmp_ = (self.data or {}).get("comparison") or {}
        trend = cmp_.get("trend") or []
        # ① 趋势表
        self.ttab.setRowCount(0)
        if not (self._phases() or trend):
            self.lb_base.setText("尚未生成对比分析 — 点『🔄 重跑迭代验证』生成")
            self.lb_base.setStyleSheet(f"color:{C_GRAY}; font-size:14px; font-weight:700; border:none;")
            self.btab.setRowCount(0)
            self.ttab.setRowCount(1)
            for j, t in enumerate(["—"] * len(self.TCOLS)):
                self.ttab.setItem(0, j, self._item(t, color=C_GRAY))
            return
        self.ttab.setRowCount(len(trend))
        for i, t in enumerate(trend):
            if not isinstance(t, dict):
                continue
            vd = t.get("verdict") or ""
            vals = [t.get("name") or t.get("id") or "", t.get("unit") or "",
                    _fnum(t.get("p0")), _fnum(t.get("p1")), _fnum(t.get("p2")),
                    _fnum(t.get("p3")), _fnum(t.get("p4")),
                    str(t.get("target") or "—"), vd]
            for j, x in enumerate(vals):
                it = self._item(x, color=(BC.get(vd, C_GRAY) if j == 8 else None), bold=(j == 8),
                                right=(2 <= j <= 6))
                self.ttab.setItem(i, j, it)
        self.ttab.resizeRowsToContents()

        # ② 与基线对比: 计数 + 逐阶段达标率 + 明细
        phs = cmp_.get("phases") or []
        seg = []
        for p in self._phases():
            pid = p.get("phase")
            vb = p.get("vs_baseline") or {}
            seg.append("%s: 提升 %d · 持平 %d · 回退 %d"
                       % (pid, int(vb.get("improved", 0) or 0), int(vb.get("flat", 0) or 0),
                          int(vb.get("regressed", 0) or 0)))
        s = cmp_.get("summary") or {}
        prate = s.get("per_phase_pass_rate") or []
        rseg = ["%s 达标 %s/%s (%s)"
                % (r.get("phase"), r.get("pass"), r.get("total"),
                   ("%.0f%%" % (100.0 * r.get("pass", 0) / r["total"])) if r.get("total") else "—")
                for r in prate if isinstance(r, dict) and r.get("total")]
        basever = ((self.data or {}).get("meta") or {}).get("baseline") or "5.50.735"
        self.lb_base.setText("vs 基线 %s ⟶ %s\n逐阶段达标率 ⟶ %s"
                             % (basever, " ｜ ".join(seg) if seg else "无数据",
                                " ｜ ".join(rseg) if rseg else "无数据")
                             + (("\n备注: " + str(s.get("note"))) if s.get("note") else ""))
        self.lb_base.setStyleSheet(f"color:{C_WHITE}; font-size:14px; border:none;")

        det = []
        for p in self._phases():
            for it in (p.get("vs_baseline") or {}).get("items") or []:
                if isinstance(it, dict):
                    det.append((p.get("phase"), it))
        self.btab.setRowCount(len(det))
        for i, (pid, it) in enumerate(det):
            v = it.get("verdict") or "未测"
            delta = it.get("delta")
            vals = [pid or "", it.get("name") or it.get("id") or "",
                    _fnum(it.get("baseline")), _fnum(it.get("current")),
                    ("—" if delta in (None, "") else ("%+.4g" % delta)), v]
            for j, x in enumerate(vals):
                it2 = self._item(x, color=(BC.get(v, C_GRAY) if j == 5 else
                                           (C_GREEN if (j == 4 and isinstance(delta, (int, float)) and delta > 0)
                                            else (C_RED if (j == 4 and isinstance(delta, (int, float)) and delta < 0)
                                                  else None))),
                                 bold=(j == 5 and v != "未测"), right=(2 <= j <= 4))
                self.btab.setItem(i, j, it2)
        self.btab.resizeRowsToContents()

    # ─────────────────────────── 动作: 重跑 / 复制 / 导出 ───────────────────────────
    def _log(self, s):
        self.log.append("[%s] %s" % (time.strftime("%H:%M:%S"), s))

    def rerun(self):
        py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
        rel = os.path.relpath(TOOL, ROOT)
        self._log("🔄 重跑迭代验证: %s %s (只读, 不碰真值)" % (os.path.relpath(py, ROOT), rel))
        rc, err = None, ""
        try:
            p = subprocess.run([py, TOOL], capture_output=True, text=True, timeout=300, cwd=ROOT)
            rc = p.returncode
            outs = [ln for ln in (p.stdout or "").strip().splitlines() if ln.strip()]
            for ln in outs[-8:]:
                self._log("   " + ln[:200])
            if rc != 0:
                err = (p.stderr or "").strip().splitlines()[-1] if (p.stderr or "").strip() else ""
                self._log("   ⛔ 退出码 %s: %s" % (rc, err[:200]))
            else:
                self._log("   ✅ 退出码 0")
        except subprocess.TimeoutExpired:
            rc, err = "TIMEOUT", "超时 300s (已中断)"
            self._log("   ⛔ 超时: 300s 内未跑完, 已中断")
        except Exception as e:                                                   # noqa: BLE001
            rc, err = "EXC", repr(e)
            self._log("   ⛔ 启动失败: %r" % e)
        self.reload()
        if rc == 0:
            self.lb_status.setText("✅ 重跑完成 (退出码 0) · 界面已刷新")
            self.lb_status.setStyleSheet(f"color:{C_GREEN}; font-size:15px; font-weight:700; border:none;")
        else:
            self.lb_status.setText("⛔ 重跑失败 — 退出码 %s｜%s  (真源: %s)"
                                   % (rc, err or "见下方日志", os.path.relpath(self.JSON, ROOT)))
            self.lb_status.setStyleSheet(f"color:{C_RED}; font-size:15px; font-weight:700; border:none;")
        self.lb_status.setVisible(True)
        return rc

    # -- 文本化 (复制/导出) --
    def _md(self):
        L = ["# 🗺 迭代路线图 · Phase 0→4 (Z-MAX 评估分析)", ""]
        d = self.data
        if d is None:
            L.append("> ⛔ 尚未生成 — 点『🔄 重跑迭代验证』生成 (真源: %s)"
                     % os.path.relpath(self.JSON, ROOT))
            sv = getattr(self, "scene_view", None)                # 🔌🧩 场景迭代 (独立真源) 一起导出
            if sv is not None:
                L.append(sv._md_section())
            return "\n".join(L)
        meta = d.get("meta") or {}
        L.append("- 版本: %s ｜ 基线: %s ｜ 生成时间: %s ｜ 生成者: %s"
                 % (meta.get("version") or "—", meta.get("baseline") or "—",
                    _ts_str(meta.get("ts")), meta.get("generated_by") or "—"))
        L.append("- 真源: `%s`" % os.path.relpath(self.JSON, ROOT))
        for p in self._phases():
            L += ["", "## %s %s" % (p.get("phase"), p.get("name") or "")]
            L.append("| 主要指标 | 单位 | 目标 |")
            L.append("|---|---|---|")
            for m in p.get("target_metrics") or []:
                if isinstance(m, dict):
                    L.append("| %s | %s | %s |" % (m.get("name") or m.get("id"), m.get("unit") or "",
                                                   m.get("target")))
            mc = p.get("meta_combo") or {}
            L.append("")
            L.append("元任务升级组合: 基线 %s ｜ 新增 %s ｜ 升级 %s"
                     % (", ".join(map(str, mc.get("baseline") or [])) or "—",
                        ", ".join("%s %s" % (i.get("fn_id"), i.get("name"))
                                  for i in (mc.get("added") or []) if isinstance(i, dict)) or "—",
                        ", ".join("%s %s" % (i.get("fn_id"), i.get("name"))
                                  for i in (mc.get("upgraded") or []) if isinstance(i, dict)) or "—"))
            vd = p.get("verification") or {}
            L.append("")
            L.append("**迭代验证** (达标 %s / 未达标 %s / 未测 %s / 样本不足 %s):"
                     % (vd.get("pass"), vd.get("fail"), vd.get("unmeasured"), vd.get("insufficient")))
            L.append("| 指标 | 实测值 | 单位 | 目标 | 判定 | 证据类 | 样本量 | 帧龄(s) |")
            L.append("|---|---|---|---|---|---|---|---|")
            for m in vd.get("metrics") or []:
                if isinstance(m, dict):
                    L.append("| %s | %s | %s | %s | %s | %s | %s | %s |"
                             % (m.get("name") or m.get("id"), _fnum(m.get("value")), m.get("unit") or "",
                                m.get("target"), m.get("verdict"), m.get("mode"),
                                m.get("n"), m.get("age_s")))
        c = d.get("comparison") or {}
        L += ["", "## 📊 对比分析", "", "### ① 阶段间趋势", "| 指标 | 单位 | P0 | P1 | P2 | P3 | P4 | 目标 | 判定 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for t in c.get("trend") or []:
            if isinstance(t, dict):
                L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (t.get("name") or t.get("id"), t.get("unit") or "", _fnum(t.get("p0")),
                            _fnum(t.get("p1")), _fnum(t.get("p2")), _fnum(t.get("p3")), _fnum(t.get("p4")),
                            t.get("target"), t.get("verdict")))
        L += ["", "### ② 与基线对比", "| 阶段 | 指标 | 基线 | 当前 | Δ | 判定 |", "|---|---|---|---|---|---|"]
        for p in self._phases():
            for it in (p.get("vs_baseline") or {}).get("items") or []:
                if isinstance(it, dict):
                    L.append("| %s | %s | %s | %s | %s | %s |"
                             % (p.get("phase"), it.get("name") or it.get("id"), _fnum(it.get("baseline")),
                                _fnum(it.get("current")), it.get("delta"), it.get("verdict")))
        sv = getattr(self, "scene_view", None)                    # 🔌🧩 场景迭代 (独立真源) 一起导出
        if sv is not None:
            L.append(sv._md_section())
        return "\n".join(L)

    def _csv(self):
        L = ["阶段,性能指标,实测值,单位,目标,判定,证据类,样本量,帧龄(s),真源/备注"]
        for p in self._phases():
            for m in ((p.get("verification") or {}).get("metrics") or []):
                if isinstance(m, dict):
                    L.append(",".join('"%s"' % str(x).replace('"', "'") for x in
                                      (p.get("phase"), m.get("name") or m.get("id"), _fnum(m.get("value")),
                                       m.get("unit"), m.get("target"), m.get("verdict"), m.get("mode"),
                                       m.get("n"), m.get("age_s"), m.get("src") or m.get("note") or "")))
        return "\n".join(L)

    def _view_text(self):
        """当前标签页的纯文本 (复制用)。"""
        i = self.tabs.currentIndex()
        if i == 0:
            segs = []
            for p in self._phases():
                segs.append("%s %s" % (p.get("phase"), p.get("name") or ""))
                for m in p.get("target_metrics") or []:
                    if isinstance(m, dict):
                        segs.append("  · %s  目标 %s %s" % (m.get("name") or m.get("id"),
                                                            m.get("target"), m.get("unit") or ""))
                segs.append("  · 元任务升级组合: " + self._combo_text(p))
            return "\n".join(segs) if segs else "尚未生成"
        if i == 1:
            return self._table_text(self.vtab, self.VCOLS)
        if i == 3:                                                              # 🔌🧩 场景迭代 (当前子视图)
            sv = getattr(self, "scene_view", None)
            return sv._view_text() if sv is not None else "尚未生成"
        return "\n".join([self._table_text(self.ttab, self.TCOLS), "",
                          self.lb_base.text(), "",
                          self._table_text(self.btab, self.BCOLS)])

    def _combo_text(self, p):
        mc = p.get("meta_combo") or {}
        return "基线 %s ｜ 新增 %s ｜ 升级 %s" % (
            ", ".join(map(str, mc.get("baseline") or [])) or "—",
            ", ".join("%s %s" % (i.get("fn_id"), i.get("name"))
                      for i in (mc.get("added") or []) if isinstance(i, dict)) or "—",
            ", ".join("%s %s" % (i.get("fn_id"), i.get("name"))
                      for i in (mc.get("upgraded") or []) if isinstance(i, dict)) or "—")

    @staticmethod
    def _table_text(tbl, cols):
        out = ["\t".join(cols)]
        for r in range(tbl.rowCount()):
            cells = []
            for c in range(tbl.columnCount()):
                it = tbl.item(r, c)
                cells.append(it.text() if it else "")
            out.append("\t".join(cells))
        return "\n".join(out)

    def copy_view(self):
        QApplication.clipboard().setText(self._view_text())
        self._log("📋 已复制当前视图 (%s) 到剪贴板" % self.tabs.tabText(self.tabs.currentIndex()))

    def _reports_dir(self):
        d = os.path.join(ROOT, "reports")
        os.makedirs(d, exist_ok=True)
        return d

    def export_md(self):
        out = os.path.join(self._reports_dir(), "iteration_roadmap_%s.md" % time.strftime("%Y%m%d_%H%M%S"))
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(self._md())
        self._log("📄 已导出 Markdown: %s" % out)
        return out

    def export_csv(self):
        sv = getattr(self, "scene_view", None)
        scene = (self.tabs.currentIndex() == 3 and sv is not None)
        out = os.path.join(self._reports_dir(), "%s_%s.csv"
                           % ("scene_phase_iteration" if scene else "iteration_roadmap",
                              time.strftime("%Y%m%d_%H%M%S")))
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(sv._csv() if scene else self._csv())
        self._log("💾 已导出 CSV: %s%s" % (out, "  (场景迭代 · 当前子视图)" if scene else ""))
        return out


# ══════════════════════════════════════════════════════════════════════════════════════════
# 🔌🧩 场景迭代 (插拔 / 摆盘 × Phase 0→4 全流程元任务组合) — 老倪 2026-10-15
#   老倪原话: 「用插拔 摆盘场景, phase0到phase4全流程迭代元任务组合」
#             (评估分析功能区: 迭代路线图 · 迭代验证 · 对比分析)
#   真源只有一个: zmax_data/eval/scene_phase_iteration.json (tools/scene_phase_iteration.py 生成)
#   三条硬纪律同上: 缺失/未测一律如实标注 (绝不假 0) · 重跑显真实退出码+stderr · 颜色语义与全站一致。
# ══════════════════════════════════════════════════════════════════════════════════════════
SCENE_JSON_PATH = os.path.join(ROOT, "zmax_data", "eval", "scene_phase_iteration.json")
SCENE_TOOL = os.path.join(ROOT, "tools", "scene_phase_iteration.py")
BIND_JSON = os.path.join(ROOT, "config", "ss_task_binding.json")
SCENE_BTNS = (("FW", "🔌 插拔 (TASK-01-FW)"), ("TRAY", "🧩 摆盘 (TASK-06-TRAY)"))
SCENE_TASK = {"FW": "TASK-01-FW", "TRAY": "TASK-06-TRAY"}
SCENE_NAME = {"FW": "插拔", "TRAY": "摆盘"}


def _rel(p):
    try:
        return os.path.relpath(p, ROOT)
    except Exception:                                                           # noqa: BLE001
        return str(p)


def _active_task_id():
    """当前激活任务 = 绑定真源 config/ss_task_binding.json 的 active_task (与 studio 同一口径, 界面不另算)。"""
    try:
        with open(BIND_JSON, encoding="utf-8") as fh:
            d = json.load(fh)
        return str((d or {}).get("active_task") or "").strip()
    except Exception:                                                           # noqa: BLE001
        return ""


def _esc(s):
    t = "—" if s in (None, "") else str(s)
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ScenePhaseIterationView(QWidget):
    """🔌🧩 场景 × Phase 0→4 全流程迭代 (组合迭代 / 迭代验证 / 对比分析) — **只显示不计算**。

    真源: zmax_data/eval/scene_phase_iteration.json (另一个 agent 的 tools/scene_phase_iteration.py 产出)。
    本控件只读它 + 可重跑 (subprocess 带超时, 失败显真实退出码/stderr, 绝不静默) + 可复制/导出。
    文件不在 / 字段缺失 ⇒ 「尚未生成 / 未测」,**绝不显示假 0**。
    """

    CCOLS = ["阶段", "主题", "指标数", "元任务组合 (carried / added / upgraded)",
             "总数量", "相对上阶段增量", "准入门"]
    KCOLS = ["阶段", "启用节点", "组合映射", "覆盖 coverage", "missing", "extra",
             "可作改配置依据", "run.mode", "证据 / 命令", "备注"]
    VCOLS = ["阶段", "性能指标", "实测值", "单位", "目标", "判定", "证据类", "样本量", "帧龄(s)", "真源/备注"]
    MCOLS = ["性能指标", "单位", "目标", "FW p0", "FW p1", "FW p2", "FW p3", "FW p4",
             "TRAY p0", "TRAY p1", "TRAY p2", "TRAY p3", "TRAY p4", "判定"]
    PCOLS = ["阶段", "FW 达标", "FW 总数", "FW 达标率", "TRAY 达标", "TRAY 总数", "TRAY 达标率"]
    DCOLS = ["场景", "新增 (added)", "升级 (upgraded)", "末阶段总数量"]
    BCOLS = ["场景", "提升", "持平", "回退"]
    _VO = {"达标": 0, "未达标": 1, "样本不足": 2, "未测": 3}

    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.JSON = path or SCENE_JSON_PATH
        self.data = None
        self.read_err = ""
        self.scene = "FW"
        self._base = {}                     # 主行号 → 折叠态组合摘要 (展开/收起改前缀)
        self._det_of_main = {}              # 主行号 → 明细行号
        self._main_of_det = {}
        self._phase_of_main = {}            # 主行号 → 阶段名 (展开态按阶段记住)
        self._expanded = set()              # 已展开的阶段 (重渲染后保持)
        self._build()
        self.reload()

    # ─────────────────────────── 小工具 (与面板同风格) ───────────────────────────
    def _log(self, s):
        w = self.parent()                   # 本控件是 QTabWidget 的页 ⇒ parent 是内部 QStackedWidget,
        while w is not None:                # 逐级上溯找到真正的面板 (有 _log 的那个) 才不丢日志
            if hasattr(w, "_log"):
                w._log(s)
                return
            w = w.parent() if hasattr(w, "parent") else None

    @staticmethod
    def _it(text, color=None, bold=False, right=False):
        it = QTableWidgetItem(str(text))
        if color:
            it.setForeground(QColor(color))
        if bold:
            f = it.font()
            f.setBold(True)
            it.setFont(f)
        if right:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    @staticmethod
    def _style(t, minh=150):
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setMinimumHeight(minh)
        t.setStyleSheet(
            f"QTableWidget{{background:{C_BG}; color:{C_WHITE}; gridline-color:{C_BORDER};"
            f" font-size:13px;}} QHeaderView::section{{background:{C_CARD}; color:{C_WHITE};"
            f" padding:6px; border:0;}}")

    @staticmethod
    def _sect(text):
        lb = QLabel(text)
        lb.setStyleSheet(f"color:{C_CYAN}; font-size:15px; font-weight:700; border:none;")
        return lb

    @staticmethod
    def _gray(t):
        lb = QLabel(t)
        lb.setWordWrap(True)
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lb.setStyleSheet(f"color:{C_GRAY}; font-size:13px; border:none;")
        return lb

    @staticmethod
    def _combo_btn_style():
        return (f"QPushButton{{background:{C_CARD}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                f" border-radius:6px; padding:7px 12px; font-weight:bold;}}"
                f" QPushButton:hover{{border-color:{C_CYAN};}}")

    @staticmethod
    def _lst(v, limit=3):
        if v is None:
            return "尚未生成"
        if not isinstance(v, list):
            return str(v)
        if not v:
            return "无"

        def one(x):
            if isinstance(x, dict):                     # {fn_id, name, why} ⇒ 显 id + 名称
                return ("%s %s" % (x.get("fn_id") or x.get("id") or "?", x.get("name") or "")).strip()
            return str(x)

        s = ", ".join(one(x) for x in v[:limit])
        return s + (" …(+%d)" % (len(v) - limit) if len(v) > limit else "")

    # ─────────────────────────── 骨架 ───────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ① 场景切换条 (默认 = 当前激活任务对应场景)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        _l0 = QLabel("场景:")
        _l0.setStyleSheet(f"color:{C_GRAY}; font-size:14px; border:none;")
        bar.addWidget(_l0)
        self.bgrp = QButtonGroup(self)
        self.bgrp.setExclusive(True)
        self.btns = {}
        for key, txt in SCENE_BTNS:
            b = QPushButton(txt)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{C_CARD}; color:{C_GRAY}; border:1px solid {C_BORDER};"
                f" border-radius:6px; padding:7px 14px; font-weight:bold; font-size:14px;}}"
                f" QPushButton:checked{{color:#ffffff; border:2px solid {C_CYAN};"
                f" background-color:#16323a;}}"
                f" QPushButton:hover{{border-color:{C_CYAN};}}")
            b.clicked.connect(lambda _c, k=key: self.set_scene(k))
            self.bgrp.addButton(b)
            self.btns[key] = b
            bar.addWidget(b)
        self.lb_scene = QLabel("—")
        self.lb_scene.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_scene.setWordWrap(True)
        self.lb_scene.setStyleSheet(f"color:{C_WHITE}; font-size:13px; border:none;")
        bar.addWidget(self.lb_scene, 1)
        self.btn_rerun = QPushButton("🔄 重跑场景迭代")
        self.btn_rerun.setStyleSheet(self._combo_btn_style())
        self.btn_rerun.clicked.connect(self.rerun)
        bar.addWidget(self.btn_rerun)
        root.addLayout(bar)

        # ② 状态横幅 (尚未生成 / 读取失败 / 重跑结果)
        self.lb_status = QLabel("")
        self.lb_status.setWordWrap(True)
        self.lb_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_status.setStyleSheet(f"color:{C_ORANGE}; font-size:14px; font-weight:700; border:none;")
        self.lb_status.setVisible(False)
        root.addWidget(self.lb_status)

        # ③ 三个子视图 (组合迭代 / 迭代验证 / 对比分析)
        self.sub = QTabWidget()
        self.sub.setStyleSheet(
            f"QTabWidget::pane{{border:1px solid {C_BORDER}; border-radius:6px; background:{C_BG};}}"
            f" QTabBar::tab{{background:{C_CARD}; color:{C_GRAY}; padding:8px 16px;"
            f" border:1px solid {C_BORDER}; border-bottom:none; font-size:14px;}}"
            f" QTabBar::tab:selected{{color:{C_WHITE}; border-color:{C_CYAN};}}")
        self.sub.addTab(self._build_combo_tab(), "🧩 组合迭代 (Phase 0→4 元任务组合)")
        self.sub.addTab(self._build_sverify_tab(), "✅ 迭代验证 (实测 vs 目标 + 配置核验)")
        self.sub.addTab(self._build_scompare_tab(), "📊 对比分析 (场景×阶段 + 基线)")
        self.sub.currentChanged.connect(lambda _i: self._render_sub())
        root.addWidget(self.sub, 1)

    # ────────────────── 子视图 (a): 组合迭代 ──────────────────
    def _build_combo_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(6)
        top = QHBoxLayout()
        self.lb_combo_hint = QLabel("—")
        self.lb_combo_hint.setWordWrap(True)
        self.lb_combo_hint.setStyleSheet(f"color:{C_GRAY}; font-size:14px; font-weight:700; border:none;")
        top.addWidget(self.lb_combo_hint, 1)
        self.lb_combo_sum = QLabel("—")
        self.lb_combo_sum.setStyleSheet(f"color:{C_WHITE}; font-size:14px; font-weight:700; border:none;")
        top.addWidget(self.lb_combo_sum)
        v.addLayout(top)

        self.ctab = QTableWidget(0, len(self.CCOLS))
        self.ctab.setHorizontalHeaderLabels(self.CCOLS)
        self._style(self.ctab, 220)
        for i, wd in enumerate((86, 168, 68, 430, 78, 130, 190)):
            self.ctab.setColumnWidth(i, wd)
        _h = self.ctab.horizontalHeader()
        _h.setStretchLastSection(False)
        _h.setSectionResizeMode(3, QHeaderView.Stretch)      # 元任务组合列吃余量
        self.ctab.cellClicked.connect(self._on_combo_click)
        v.addWidget(self.ctab, 1)
        return w

    # ────────────────── 子视图 (b): 迭代验证 ──────────────────
    def _build_sverify_tab(self):
        host = QWidget()
        v = QVBoxLayout(host)
        v.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("筛选:"))
        self.flt = QComboBox()
        self.flt.addItems(["全部", "仅达标", "仅未达标", "仅未测/样本不足"])
        self.flt.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                               f" border-radius:4px; padding:5px 10px;")
        self.flt.currentIndexChanged.connect(lambda _i: self._render_sverify())
        top.addWidget(self.flt)
        top.addStretch(1)
        self.lb_vsum = QLabel("—")
        self.lb_vsum.setStyleSheet(f"color:{C_WHITE}; font-size:14px; font-weight:700; border:none;")
        top.addWidget(self.lb_vsum)
        v.addLayout(top)

        v.addWidget(self._sect("① 配置完备性核验 (coverage · missing/extra ⇒ 能不能作为改配置依据) + run.mode (实跑/未跑)"))
        self.ktab = QTableWidget(0, len(self.KCOLS))
        self.ktab.setHorizontalHeaderLabels(self.KCOLS)
        self._style(self.ktab, 150)
        self.ktab.setWordWrap(True)                       # 备注/extra 折行显示 (行高在渲染时按行数定)
        for i, wd in enumerate((78, 74, 74, 104, 60, 190, 186, 146, 180, 288)):
            self.ktab.setColumnWidth(i, wd)
        _kh = self.ktab.horizontalHeader()
        _kh.setStretchLastSection(False)
        _kh.setSectionResizeMode(9, QHeaderView.Stretch)  # 备注吃余量
        self.ktab.verticalHeader().setDefaultSectionSize(66)   # 备注 3 行也放得下 (行高在渲染时随行数再定表高)
        v.addWidget(self.ktab)

        v.addWidget(self._sect("② 迭代验证 · 实测 vs 目标 (每指标: 实测/单位/目标/判定/证据类/样本/帧龄/真源)"))
        self.vtab2 = QTableWidget(0, len(self.VCOLS))
        self.vtab2.setHorizontalHeaderLabels(self.VCOLS)
        self._style(self.vtab2, 460)
        for i, wd in enumerate((82, 150, 96, 62, 176, 84, 96, 70, 76, 300)):
            self.vtab2.setColumnWidth(i, wd)
        _vh = self.vtab2.horizontalHeader()
        _vh.setStretchLastSection(False)
        _vh.setSectionResizeMode(9, QHeaderView.Stretch)
        v.addWidget(self.vtab2, 1)
        v.addStretch(0)

        scroll = QScrollArea()                            # 两张表都在页内可滚, 不再被压扁 (行数多也不挤)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")
        scroll.setWidget(host)
        return scroll

    # ────────────────── 子视图 (c): 对比分析 ──────────────────
    def _build_scompare_tab(self):
        host = QWidget()
        outer = QVBoxLayout(host)
        outer.setSpacing(10)

        g1 = QHBoxLayout()
        g1.addWidget(self._sect("① 场景 × 阶段矩阵 (每指标: FW p0..p4 与 TRAY p0..p4)"))
        g1.addStretch(1)
        _l = QLabel("视图:")
        _l.setStyleSheet(f"color:{C_GRAY}; font-size:13px; border:none;")
        g1.addWidget(_l)
        self.cmode = QComboBox()
        self.cmode.addItems(["并列 (FW + TRAY)", "只看 FW", "只看 TRAY"])
        self.cmode.setStyleSheet(f"background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                                 f" border-radius:4px; padding:4px 10px;")
        self.cmode.currentIndexChanged.connect(lambda _i: self._render_matrix())
        g1.addWidget(self.cmode)
        outer.addLayout(g1)
        self.mtab = QTableWidget(0, len(self.MCOLS))
        self.mtab.setHorizontalHeaderLabels(self.MCOLS)
        self._style(self.mtab, 180)
        for i, wd in enumerate((150, 58, 140) + (76,) * 10 + (100,)):
            self.mtab.setColumnWidth(i, wd)
        _mh = self.mtab.horizontalHeader()
        _mh.setStretchLastSection(False)
        _mh.setSectionResizeMode(0, QHeaderView.Stretch)
        outer.addWidget(self.mtab, 2)

        outer.addWidget(self._sect("② 两场景逐阶段达标率 (达标 / 总数)"))
        self.ptab = QTableWidget(0, len(self.PCOLS))
        self.ptab.setHorizontalHeaderLabels(self.PCOLS)
        self._style(self.ptab, 130)
        for i, wd in enumerate((100, 90, 90, 100, 96, 96, 110)):
            self.ptab.setColumnWidth(i, wd)
        _ph2 = self.ptab.horizontalHeader()
        _ph2.setStretchLastSection(False)      # 不给最后一列吃余量 (否则「TRAY 达标率」被拉成一大格)
        outer.addWidget(self.ptab, 1)

        outer.addWidget(self._sect("③ 元任务组合增量对比 (added / upgraded)"))
        self.dtab = QTableWidget(0, len(self.DCOLS))
        self.dtab.setHorizontalHeaderLabels(self.DCOLS)
        self._style(self.dtab, 90)
        for i, wd in enumerate((110, 120, 150, 140)):
            self.dtab.setColumnWidth(i, wd)
        self.dtab.horizontalHeader().setStretchLastSection(False)
        outer.addWidget(self.dtab, 1)

        outer.addWidget(self._sect("④ 与基线对比 (提升 / 持平 / 回退)"))
        self.lb_sbase = QLabel("—")
        self.lb_sbase.setWordWrap(True)
        self.lb_sbase.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lb_sbase.setStyleSheet(f"color:{C_WHITE}; font-size:13px; border:none;")
        outer.addWidget(self.lb_sbase)
        self.btab2 = QTableWidget(0, len(self.BCOLS))
        self.btab2.setHorizontalHeaderLabels(self.BCOLS)
        self._style(self.btab2, 90)
        for i, wd in enumerate((110, 90, 90, 90)):
            self.btab2.setColumnWidth(i, wd)
        outer.addWidget(self.btab2, 1)
        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none; background:transparent;}")
        scroll.setWidget(host)
        return scroll

    # ─────────────────────────── 数据 (只读真源) ───────────────────────────
    def reload(self):
        self.read_err = ""
        self.data = None
        if not os.path.exists(self.JSON):
            self.read_err = "尚未生成"
        else:
            try:
                with open(self.JSON, encoding="utf-8") as fh:
                    d = json.load(fh)
                if not isinstance(d, dict):
                    self.read_err = "文件格式不对 (顶层不是对象)"
                else:
                    self.data = d
            except Exception as e:                                              # noqa: BLE001
                self.read_err = "读取失败: %s" % e
        self._pick_scene()
        self._render_all()

    def _scenes(self):
        sc = (self.data or {}).get("scenes") or []
        return [s for s in sc if isinstance(s, dict)] if isinstance(sc, list) else []

    def _scene(self, key=None):
        k = (self.scene if key is None else key)
        for s in self._scenes():
            if str(s.get("scene") or "").upper() == str(k).upper():
                return s
        return None

    def _sphases(self, key=None):
        s = self._scene(key) or {}
        ph = s.get("phases") or []
        return (sorted([p for p in ph if isinstance(p, dict)],
                       key=lambda p: _phase_key(p.get("phase", ""))) if isinstance(ph, list) else [])

    def _pick_scene(self):
        """默认场景 = 当前激活任务对应的场景 (绑定真源 active_task ⇒ scene.task)。"""
        keys = [str(s.get("scene") or "") for s in self._scenes() if s.get("scene")]
        if self.scene not in keys:
            act = _active_task_id()
            pick = ""
            for s in self._scenes():
                if act and str(s.get("task") or "").strip() == act:
                    pick = str(s.get("scene") or "")
                    break
            if not pick:                                    # 兜底: 按 FW → TRAY 顺序取有数据的场景
                for key, _t in SCENE_BTNS:
                    for s in self._scenes():
                        if str(s.get("scene") or "").upper() == key:
                            pick = str(s.get("scene") or "")
                            break
                    if pick:
                        break
            if not pick and keys:
                pick = keys[0]
            if pick:
                self.scene = pick
        self._sync_buttons()

    def _sync_buttons(self):
        for key, b in self.btns.items():
            b.setChecked(str(self.scene).upper() == key)

    def set_scene(self, key):
        self.scene = key
        self._sync_buttons()
        self._render_all()
        return self.scene

    def _render_all(self):
        self._render_meta()
        self._render_combo()
        self._render_sverify()
        self._render_scompare()

    def _render_sub(self):
        (self._render_combo, self._render_sverify, self._render_scompare)[self.sub.currentIndex()]()

    # ─────────────────────────── 渲染: 头部元信息 ───────────────────────────
    def _render_meta(self):
        rel = _rel(self.JSON)
        meta = (self.data or {}).get("meta") or {}
        s = self._scene() or {}
        key = str(self.scene).upper()
        nm = s.get("scene_name") or SCENE_NAME.get(key, "")
        task = s.get("task") or SCENE_TASK.get(key, "—")
        act = _active_task_id()
        star = "  ★当前激活任务" if (act and act == str(task).strip()) else ""
        if self.data is None:
            self.lb_scene.setText("真源: %s ｜ 场景 %s %s ｜ 任务 %s%s ｜ 版本 — ｜ 基线 — ｜ 生成时间 —"
                                  % (rel, key, nm, task, star))
            if self.read_err and self.read_err != "尚未生成":
                self.lb_status.setText("⛔ 真源读取失败 — %s ｜ 点『🔄 重跑场景迭代』重新生成  (真源: %s)"
                                       % (self.read_err, rel))
            else:
                self.lb_status.setText("⛔ 尚未生成 — 点『🔄 重跑场景迭代』生成  (真源: %s)" % rel)
            self.lb_status.setStyleSheet(f"color:{C_ORANGE}; font-size:14px; font-weight:700; border:none;")
            self.lb_status.setVisible(True)
        else:
            self.lb_scene.setText(
                "真源: %s ｜ 场景 %s %s ｜ 任务 %s%s ｜ 版本 %s ｜ 基线 %s ｜ 生成时间 %s ｜ 生成者 %s"
                % (rel, key, nm, task, star, meta.get("version") or "—", meta.get("baseline") or "—",
                   _ts_str(meta.get("ts")), meta.get("generated_by") or "—"))
            self.lb_status.setVisible(False)

    def _metric_count(self, p):
        for k in ("metrics_count", "n_metrics"):
            v = p.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
        for k in ("metrics", "target_metrics"):
            v = p.get(k)
            if isinstance(v, list):
                return len(v)
        ms = (p.get("verification") or {}).get("metrics")
        return len(ms) if isinstance(ms, list) else None

    # ─────────────────────────── 渲染 (a): 组合迭代 ───────────────────────────
    def _render_combo(self):
        phs = self._sphases()
        self.ctab.setRowCount(0)
        self._base, self._det_of_main, self._main_of_det = {}, {}, {}
        self._phase_of_main = {}
        rel = _rel(self.JSON)
        if not phs:
            self.lb_combo_hint.setText("尚未生成场景迭代 (%s) — 点『🔄 重跑场景迭代』生成" % rel)
            self.lb_combo_hint.setStyleSheet(f"color:{C_ORANGE}; font-size:14px; font-weight:700; border:none;")
            self.lb_combo_sum.setText("")
            return
        self.lb_combo_hint.setText("")
        smy = (self._scene() or {}).get("summary") or {}
        self.lb_combo_sum.setText(
            "本场景汇总: 达标 %s · 未达标 %s · 未测 %s ｜ 末阶段 coverage %s ｜ 阶段 %d 个"
            % (smy.get("pass", "尚未生成"), smy.get("fail", "尚未生成"),
               smy.get("unmeasured", "尚未生成"), smy.get("coverage_last") or "尚未生成", len(phs)))

        prev_total = None
        ncols = len(self.CCOLS)
        for p in phs:
            cb = p.get("combo") or {}
            carried = cb.get("carried") if isinstance(cb.get("carried"), list) else None
            added = cb.get("added") if isinstance(cb.get("added"), list) else None
            upg = cb.get("upgraded") if isinstance(cb.get("upgraded"), list) else None
            total = cb.get("total")
            if not isinstance(total, (int, float)) or isinstance(total, bool):
                total = None
            nc = self._metric_count(p)
            if total is None and (carried or added or upg):
                total = len(carried or []) + len(added or []) + len(upg or [])
                total_src = "%d (按组合条数计)" % total
            else:
                total_src = None
            delta = (total - prev_total) if (total is not None and prev_total is not None) else None
            short = self._combo_short(carried, added, upg, total)
            main = self.ctab.rowCount()
            self.ctab.insertRow(main)
            vals = [p.get("phase") or "", p.get("name") or "—",
                    ("尚未生成" if nc is None else str(nc)), "▸ " + short,
                    ("尚未生成" if total is None else str(total)),
                    ("— (首阶段)" if prev_total is None and total is not None else
                     ("尚未生成" if delta is None else ("%+d" % delta))),
                    self._entry_txt(p.get("entry"))]
            cols = [C_WHITE, C_WHITE, C_WHITE, C_ORANGE, C_WHITE, C_WHITE, None]
            for j, t in enumerate(vals):
                it = self._it(t, color=(cols[j] if cols[j] else self._entry_clr(p.get("entry"))),
                              bold=(j in (0, 4)), right=(j in (2, 4, 5)))
                if j == 5 and delta is not None:
                    it.setForeground(QColor(C_GREEN if delta > 0 else (C_RED if delta < 0 else C_GRAY)))
                if j == 3:
                    it.setToolTip("点击本格展开/收起: carried(沿用) / added(新增) / upgraded(升级), "
                                  "新增·升级显示 fn_id + 名称 + why")
                if j == 4 and total_src:
                    it.setToolTip("组合总数量 = %s" % total_src)
                self.ctab.setItem(main, j, it)

            # 明细行 (默认折叠)
            det = self.ctab.rowCount()
            self.ctab.insertRow(det)
            lbl = QLabel(self._combo_html(p, carried, added, upg, total))
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lbl.setStyleSheet(f"color:{C_WHITE}; background:{C_CARD}; border:1px solid {C_BORDER};"
                              f" border-radius:4px; font-size:13px; padding:6px;")
            self.ctab.setSpan(det, 0, 1, ncols)
            self.ctab.setCellWidget(det, 0, lbl)
            self.ctab.setRowHidden(det, True)
            self._base[main] = short
            self._det_of_main[main] = det
            self._main_of_det[det] = main
            self._phase_of_main[main] = str(p.get("phase") or p.get("name") or "")
            prev_total = total if total is not None else prev_total
        self.ctab.resizeRowsToContents()
        for row, ph in list(self._phase_of_main.items()):       # 重渲染保持展开态 (切子视图/切场景/切外层页都不丢)
            if ph and ph in self._expanded and self.ctab.isRowHidden(self._det_of_main.get(row, -1)):
                self._on_combo_click(row, 3)

    @staticmethod
    def _combo_short(carried, added, upg, total):
        def n(v):
            return "?" if v is None else str(len(v))
        s = "carried %s · added %s · upgraded %s" % (n(carried), n(added), n(upg))
        if total is not None:
            s += " · 合计 %d" % total
        return s + "   (点击展开)"

    def _combo_html(self, p, carried, added, upg, total):
        L = ["<b>%s %s</b> · 合计 %s" % (_esc(p.get("phase")), _esc(p.get("name")),
                                         "尚未生成" if total is None else total)]
        if carried is None and added is None and upg is None:
            return "<br>".join(L + ["元任务组合: 尚未生成"])
        L.append("<span style='color:%s'>carried (沿用) %d</span>: %s"
                 % (C_GRAY, len(carried or []), _esc(self._ids(carried))))
        L.append("<span style='color:%s'>added (新增) %d</span>" % (C_GREEN, len(added or [])))
        L += ["&nbsp;&nbsp;➕ <b>%s</b> %s &nbsp;— %s" % (_esc(i.get("fn_id")), _esc(i.get("name")), _esc(i.get("why")))
              for i in self._dicts(added)]
        L += ["&nbsp;&nbsp;%s" % _esc(i) for i in self._scalars(added)]
        L.append("<span style='color:%s'>upgraded (升级) %d</span>" % (C_ORANGE, len(upg or [])))
        L += ["&nbsp;&nbsp;⬆ <b>%s</b> %s &nbsp;— %s" % (_esc(i.get("fn_id")), _esc(i.get("name")), _esc(i.get("why")))
              for i in self._dicts(upg)]
        L += ["&nbsp;&nbsp;%s" % _esc(i) for i in self._scalars(upg)]
        if not (added or upg):
            L.append("本阶段无新增/升级元任务")
        return "<br>".join(L)

    @staticmethod
    def _dicts(seq):
        return [i for i in (seq or []) if isinstance(i, dict)]

    @staticmethod
    def _scalars(seq):
        return [i for i in (seq or []) if not isinstance(i, dict)]

    def _ids(self, seq):
        out = []
        for i in (seq or []):
            out.append(i.get("fn_id") or i.get("name") or "?" if isinstance(i, dict) else str(i))
        return ", ".join(out) if out else "无"

    @staticmethod
    def _entry_txt(e):
        if not isinstance(e, dict) or not e:
            return "尚未生成"
        g = lambda k: ("✔" if e.get(k) is True else ("✘" if e.get(k) is False else "?"))    # noqa: E731
        return "①%s ②%s ③%s ｜ %s" % (g("gate1_zero_regress"), g("gate2_net_gain"),
                                       g("gate3_consistency"),
                                       ("已开" if e.get("open") is True else
                                        ("未开" if e.get("open") is False else "未测")))

    @staticmethod
    def _entry_clr(e):
        if not isinstance(e, dict) or not e:
            return C_GRAY
        if e.get("open") is True and all(e.get(k) is True for k in
                                         ("gate1_zero_regress", "gate2_net_gain", "gate3_consistency")):
            return C_GREEN
        if any(e.get(k) is False for k in ("gate1_zero_regress", "gate2_net_gain", "gate3_consistency")):
            return C_RED
        return C_GRAY

    def _on_combo_click(self, row, col):
        if col != 3 or row not in self._det_of_main:
            return
        det = self._det_of_main[row]
        now_hidden = not self.ctab.isRowHidden(det)
        self.ctab.setRowHidden(det, now_hidden)
        it = self.ctab.item(row, 3)
        if it is not None:
            it.setText(("▸ " if now_hidden else "▾ ") + self._base.get(row, ""))
        ph = self._phase_of_main.get(row, "")
        if ph:                                              # 记住展开态 ⇒ 重渲染后不塌回去
            if now_hidden:
                self._expanded.discard(ph)
            else:
                self._expanded.add(ph)
        if not now_hidden:                                  # 展开: 按实际宽度算高 (否则明细被压成一行/留大片空白)
            lw = self.ctab.cellWidget(det, 0)
            if lw is not None:
                w = max(700, self.ctab.viewport().width() - 24)
                lw.setFixedWidth(w)
                h = lw.heightForWidth(w)
                if h <= 0:
                    h = lw.sizeHint().height()
                self.ctab.setRowHeight(det, max(36, h + 14))

    def expand_all(self):
        for row, det in list(self._det_of_main.items()):
            if self.ctab.isRowHidden(det):                  # 幂等: 只展开, 不把已展开的收起来
                self._on_combo_click(row, 3)

    # ─────────────────────────── 渲染 (b): 迭代验证 ───────────────────────────
    def _render_sverify(self):
        phs = self._sphases()
        self.ktab.setRowCount(0)
        self.vtab2.setRowCount(0)
        if not phs:
            self.lb_vsum.setText("尚未生成场景迭代验证 (%s) — 点『🔄 重跑场景迭代』生成" % _rel(self.JSON))
            self.lb_vsum.setStyleSheet(f"color:{C_ORANGE}; font-size:14px; font-weight:700; border:none;")
            return

        # ① 配置完备性核验 + run.mode
        self.ktab.setRowCount(len(phs))
        for i, p in enumerate(phs):
            cc = p.get("config_check") or {}
            run = p.get("run") or {}
            miss, extra = cc.get("missing"), cc.get("extra")
            ok = cc.get("pass")
            derived = False
            if not isinstance(ok, bool) and (isinstance(miss, list) or isinstance(extra, list) or cc.get("coverage")):
                ok = (not miss)                          # 工具没给 pass ⇒ 按 missing (组合映射有没有漏) 推导, 并标注
                derived = True
            nm_ = len(miss) if isinstance(miss, list) else None
            ne_ = len(extra) if isinstance(extra, list) else None
            if ok is True:
                can = "✅ 可作改配置依据 (缺 %s · 多 %s)" % (nm_, ne_)
                cclr = C_GREEN
            elif ok is False:
                can = "⛔ 不可 — 缺 %s 条 (组合映射未落到启用集) · 多 %s 条" % (nm_, ne_)
                cclr = C_RED
            else:
                can, cclr = "尚未生成", C_GRAY
            if derived and ok is not None:
                can += "  [按 missing 推导]"
            mode = run.get("mode") or ""
            mode_s = mode if mode else "未测"
            note = run.get("note") or ""
            if str(mode).strip() in ("未跑", "dry", "dry_run", "未实跑"):
                mode_s = "%s (原因见『备注』列)" % mode_s
            ev = run.get("evidence") or ""
            cmd = run.get("cmd") or ""
            vals = [p.get("phase") or "",
                    ("尚未生成" if cc.get("enabled_nodes") in (None, "") else str(cc.get("enabled_nodes"))),
                    ("尚未生成" if cc.get("combo_mapped") in (None, "") else str(cc.get("combo_mapped"))),
                    cc.get("coverage") or "尚未生成",
                    self._lst(miss), self._lst(extra), can, mode_s,
                    (ev + ("  ｜  " + cmd if cmd else "")) or "尚未生成",
                    note or p.get("note") or ""]
            for j, t in enumerate(vals):
                it = self._it(t, color=(cclr if j == 6 else (C_GREEN if (j == 7 and "实跑" in mode_s) else
                                                             (C_GRAY if j == 7 else None))),
                              bold=(j in (6, 7)), right=(j in (1, 2, 3)))
                if j in (4, 5) and isinstance(miss if j == 4 else extra, list) and (miss if j == 4 else extra):
                    it.setForeground(QColor(C_RED))
                it.setToolTip("missing (缺): %s\n\nextra (多): %s\n\n证据: %s\n命令: %s\n备注: %s"
                              % (self._lst(miss, 99), self._lst(extra, 99), ev or "—", cmd or "—", note or "—"))
                self.ktab.setItem(i, j, it)
        # 表高随行数定 ⇒ 上一版被压扁成一条缝 (行高统一 66, 超出内部滚动), 整页再滚动
        self.ktab.setFixedHeight(min(404, 34 + max(1, self.ktab.rowCount()) * 68))

        # ② 实测 vs 目标
        f = self.flt.currentIndex()
        tot = {"达标": 0, "未达标": 0, "未测": 0, "样本不足": 0}
        rows = []
        for p in phs:
            vd = p.get("verification") or {}
            ms = [m for m in (vd.get("metrics") or []) if isinstance(m, dict)]
            ms = sorted(ms, key=lambda m: self._VO.get(str(m.get("verdict") or ""), 4))
            if not ms:
                for k in tot:
                    tot[k] += int(vd.get(k, 0) or 0) if vd.get(k) is not None else 0
            for m in ms:
                v = m.get("verdict") or "未测"
                if f == 1 and v != "达标":
                    continue
                if f == 2 and v != "未达标":
                    continue
                if f == 3 and v not in ("未测", "样本不足"):
                    continue
                rows.append((p, m))
        if not any(tot.values()):
            for p in phs:
                for m in (p.get("verification") or {}).get("metrics") or []:
                    k = (m or {}).get("verdict")
                    if k in tot:
                        tot[k] += 1
        self.lb_vsum.setText("达标 %d · 未达标 %d · 未测 %d · 样本不足 %d ｜ 显示 %d 行 ｜ 场景 %s"
                             % (tot["达标"], tot["未达标"], tot["未测"], tot["样本不足"], len(rows), self.scene))
        self.lb_vsum.setStyleSheet(f"color:{C_WHITE}; font-size:14px; font-weight:700; border:none;")

        self.vtab2.setRowCount(len(rows))
        for i, (p, m) in enumerate(rows):
            v = m.get("verdict") or "未测"
            col = VC.get(v, C_GRAY)
            n, age = m.get("n"), m.get("age_s")
            vals = [p.get("phase") or "", m.get("name") or m.get("id") or "",
                    _fnum(m.get("value")), m.get("unit") or "",
                    ("尚未生成" if m.get("target") in (None, "") else str(m.get("target"))),
                    v, m.get("mode") or "未测",
                    ("—" if (n in (None, "") or v == "未测") else str(n)),
                    ("—" if age in (None, "", -1, -1.0) else "%.0f" % age),
                    m.get("src") or m.get("note") or "尚未生成"]
            for j, t in enumerate(vals):
                it = self._it(t, color=(col if j == 5 else None), bold=(j == 5), right=(j in (2, 7, 8)))
                if j in (2, 5) and v in ("未测", "样本不足"):
                    it.setForeground(QColor(C_GRAY))
                it.setToolTip("%s ｜ 判定 %s ｜ 证据类 %s ｜ 样本量 %s ｜ 帧龄 %s\n目标: %s\n真源: %s\n备注: %s"
                              % (m.get("name") or m.get("id"), v, m.get("mode"), n, age,
                                 m.get("target"), m.get("src"), m.get("note")))
                self.vtab2.setItem(i, j, it)
        self.vtab2.resizeRowsToContents()

    # ─────────────────────────── 渲染 (c): 对比分析 ───────────────────────────
    def _render_scompare(self):
        cmp_ = (self.data or {}).get("comparison") or {}
        if not self._scenes():
            for t in (self.mtab, self.ptab, self.dtab, self.btab2):
                t.setRowCount(0)
            self.lb_sbase.setText("尚未生成场景对比分析 (%s) — 点『🔄 重跑场景迭代』生成" % _rel(self.JSON))
            self.lb_sbase.setStyleSheet(f"color:{C_ORANGE}; font-size:13px; font-weight:700; border:none;")
            return
        self._render_matrix()

        # ② 逐阶段达标率
        pr = cmp_.get("pass_rate") or {}
        fw, tr = pr.get("FW") or [], pr.get("TRAY") or []
        order = []
        for r in list(fw) + list(tr):
            if isinstance(r, dict) and r.get("phase") not in order:
                order.append(r.get("phase"))
        order = sorted([o for o in order if o], key=_phase_key)
        byk = {}
        for k, seq in (("FW", fw), ("TRAY", tr)):
            for r in seq if isinstance(seq, list) else []:
                if isinstance(r, dict):
                    byk[(k, r.get("phase"))] = r

        def cellp(k, ph):
            r = byk.get((k, ph))
            if r is None:
                return ("尚未生成", "尚未生成", "尚未生成")
            pa, to = r.get("pass"), r.get("total")
            rate = ("%.0f%%" % (100.0 * pa / to)) if (isinstance(pa, (int, float)) and to) else "未测"
            return (str(pa) if pa is not None else "尚未生成",
                    str(to) if to is not None else "尚未生成", rate)

        self.ptab.setRowCount(len(order))
        for i, ph in enumerate(order):
            a, b, c = cellp("FW", ph)
            d, e, f2 = cellp("TRAY", ph)
            for j, (t, clr, rgt) in enumerate((
                    (str(ph), C_WHITE, False), (a, None, True), (b, None, True),
                    (c, C_GRAY if c == "未测" else None, True), (d, None, True), (e, None, True),
                    (f2, C_GRAY if f2 == "未测" else None, True))):
                self.ptab.setItem(i, j, self._it(t, color=clr, bold=(j == 0), right=rgt))
        self.ptab.resizeRowsToContents()

        # ③ 组合增量
        cd = cmp_.get("combo_delta") or {}
        self.dtab.setRowCount(len(SCENE_BTNS))
        for i, (key, _t) in enumerate(SCENE_BTNS):
            e = cd.get(key) or {}
            last = self._sphases(key)
            tot_last = None
            if last:
                tv = ((last[-1].get("combo") or {}).get("total"))
                if isinstance(tv, (int, float)) and not isinstance(tv, bool):
                    tot_last = tv
            vals = ["%s %s" % (key, SCENE_NAME.get(key, "")),
                    ("尚未生成" if e.get("added") is None else str(e.get("added"))),
                    ("尚未生成" if e.get("upgraded") is None else str(e.get("upgraded"))),
                    ("尚未生成" if tot_last is None else str(tot_last))]
            for j, t in enumerate(vals):
                self.dtab.setItem(i, j, self._it(t, color=(C_WHITE if j == 0 else None),
                                                 bold=(j == 0), right=(j > 0)))
        self.dtab.resizeRowsToContents()

        # ④ 与基线
        vb = cmp_.get("vs_baseline") or {}
        base = ((self.data or {}).get("meta") or {}).get("baseline") or "尚未生成"
        segs = []
        self.btab2.setRowCount(len(SCENE_BTNS))
        for i, (key, _t) in enumerate(SCENE_BTNS):
            e = vb.get(key) or {}
            vals = ["%s %s" % (key, SCENE_NAME.get(key, "")),
                    ("尚未生成" if e.get("improved") is None else str(e.get("improved"))),
                    ("尚未生成" if e.get("flat") is None else str(e.get("flat"))),
                    ("尚未生成" if e.get("regressed") is None else str(e.get("regressed")))]
            for j, t in enumerate(vals):
                clr = C_WHITE if j == 0 else (C_GREEN if (j == 1 and e.get("improved")) else
                                              (C_GRAY if (j == 2 and e.get("flat")) else
                                               (C_RED if (j == 3 and e.get("regressed")) else None)))
                self.btab2.setItem(i, j, self._it(t, color=clr, bold=(j == 0), right=(j > 0)))
            segs.append("%s: 提升 %s · 持平 %s · 回退 %s"
                        % (key, e.get("improved", "尚未生成"), e.get("flat", "尚未生成"),
                           e.get("regressed", "尚未生成")))
        self.btab2.resizeRowsToContents()
        note = cmp_.get("note") or ""
        self.lb_sbase.setText("vs 基线 %s ｜ %s%s"
                              % (base, "  ｜  ".join(segs), ("\n备注: " + str(note)) if note else ""))
        self.lb_sbase.setStyleSheet(f"color:{C_WHITE}; font-size:13px; border:none;")

    def _render_matrix(self):
        mode = self.cmode.currentIndex() if hasattr(self, "cmode") else 0
        for c in range(3, 8):                                   # FW p0..p4
            self.mtab.setColumnHidden(c, mode == 2)
        for c in range(8, 13):                                  # TRAY p0..p4
            self.mtab.setColumnHidden(c, mode == 1)
        rowsl = ((self.data or {}).get("comparison") or {}).get("matrix") or []
        rowsl = [r for r in rowsl if isinstance(r, dict)]
        self.mtab.setRowCount(len(rowsl))
        for i, r in enumerate(rowsl):
            fw, tr = r.get("FW") or {}, r.get("TRAY") or {}
            vd = r.get("verdict") or ""
            vals = [r.get("name") or r.get("id") or "", r.get("unit") or "",
                    ("尚未生成" if r.get("target") in (None, "") else str(r.get("target")))]
            vals += [_fnum(fw.get("p%d" % k)) for k in range(5)]
            vals += [_fnum(tr.get("p%d" % k)) for k in range(5)]
            vals.append(vd or "未测")
            for j, t in enumerate(vals):
                it = self._it(t, color=(BC.get(vd, C_GRAY) if j == 13 else None), bold=(j == 13),
                              right=(2 <= j <= 12))
                it.setToolTip("%s ｜ 单位 %s ｜ 目标 %s ｜ 判定 %s\nFW: %s\nTRAY: %s"
                              % (r.get("name") or r.get("id"), r.get("unit"), r.get("target"), vd, fw, tr))
                self.mtab.setItem(i, j, it)
        self.mtab.resizeRowsToContents()

    # ─────────────────────────── 动作: 重跑 ───────────────────────────
    def rerun(self):
        py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
        self._log("🔄 重跑场景迭代 (插拔/摆盘 · Phase 0→4): %s %s"
                  % (_rel(py), _rel(SCENE_TOOL)))
        rc, err = None, ""
        if not os.path.exists(SCENE_TOOL):
            self._log("   ⛔ 真源工具不存在: %s" % _rel(SCENE_TOOL))
            self.lb_status.setText("⛔ 重跑场景迭代失败 — 工具不存在: %s  (真源: %s)"
                                   % (_rel(SCENE_TOOL), _rel(self.JSON)))
            self.lb_status.setStyleSheet(f"color:{C_RED}; font-size:14px; font-weight:700; border:none;")
            self.lb_status.setVisible(True)
            self.reload()
            return "NO_TOOL"
        try:
            p = subprocess.run([py, SCENE_TOOL], capture_output=True, text=True, timeout=900, cwd=ROOT)
            rc = p.returncode
            outs = [ln for ln in (p.stdout or "").strip().splitlines() if ln.strip()]
            for ln in outs[-10:]:
                self._log("   " + ln[:220])
            if rc != 0:
                serr = (p.stderr or "").strip().splitlines()
                err = serr[-1] if serr else ""
                self._log("   ⛔ 退出码 %s: %s" % (rc, err[:220]))
            else:
                self._log("   ✅ 退出码 0")
        except subprocess.TimeoutExpired:
            rc, err = "TIMEOUT", "超时 900s (已中断)"
            self._log("   ⛔ 超时: 900s 内未跑完, 已中断")
        except Exception as e:                                                  # noqa: BLE001
            rc, err = "EXC", repr(e)
            self._log("   ⛔ 启动失败: %r" % e)
        self.reload()
        if rc == 0:
            self.lb_status.setText("✅ 重跑场景迭代完成 (退出码 0) · 界面已刷新  (真源: %s)" % _rel(self.JSON))
            self.lb_status.setStyleSheet(f"color:{C_GREEN}; font-size:14px; font-weight:700; border:none;")
        else:
            self.lb_status.setText("⛔ 重跑场景迭代失败 — 退出码 %s｜%s  (真源: %s)"
                                   % (rc, err or "见日志", _rel(self.JSON)))
            self.lb_status.setStyleSheet(f"color:{C_RED}; font-size:14px; font-weight:700; border:none;")
        self.lb_status.setVisible(True)
        return rc

    # ─────────────────────────── 复制 / 导出 ───────────────────────────
    def _view_text(self):
        """当前子视图纯文本 (复制当前视图用)。"""
        i = self.sub.currentIndex()
        if not self._sphases():
            return "场景 %s: 尚未生成 (%s)" % (self.scene, _rel(self.JSON))
        if i == 0:
            out = [self.lb_scene.text(), self.lb_combo_hint.text() or "", self.lb_combo_sum.text(), ""]
            for p in self._sphases():
                cb = p.get("combo") or {}
                out.append("%s %s ｜ 指标数 %s ｜ %s ｜ 准入门 %s"
                           % (p.get("phase"), p.get("name") or "",
                              self._metric_count(p), self._combo_short(cb.get("carried"), cb.get("added"),
                                                                       cb.get("upgraded"), cb.get("total")),
                              self._entry_txt(p.get("entry"))))
                for tag, seq in (("carried", cb.get("carried")), ("added", cb.get("added")),
                                 ("upgraded", cb.get("upgraded"))):
                    for it in self._dicts(seq):
                        out.append("    %s: %s %s — %s" % (tag, it.get("fn_id"), it.get("name"), it.get("why")))
                    if isinstance(seq, list) and self._scalars(seq):
                        out.append("    %s: %s" % (tag, ", ".join(map(str, self._scalars(seq)))))
            return "\n".join(out)
        if i == 1:
            return "\n".join([self.lb_vsum.text(), "", "① 配置完备性核验", self._tbl(self.ktab, self.KCOLS),
                              "", "② 迭代验证 (实测 vs 目标)", self._tbl(self.vtab2, self.VCOLS)])
        return "\n".join(["① 场景 × 阶段矩阵 [%s]" % self.cmode.currentText(),
                          self._tbl(self.mtab, self.MCOLS), "", "② 逐阶段达标率",
                          self._tbl(self.ptab, self.PCOLS), "", "③ 组合增量",
                          self._tbl(self.dtab, self.DCOLS), "", "④ 与基线",
                          self.lb_sbase.text(), self._tbl(self.btab2, self.BCOLS)])

    @staticmethod
    def _tbl(tbl, cols):
        out = ["\t".join(cols)]
        for r in range(tbl.rowCount()):
            cells = []
            for c in range(tbl.columnCount()):
                if tbl.isColumnHidden(c):
                    continue
                it = tbl.item(r, c)
                cells.append(it.text() if it else "")
            out.append("\t".join(cells))
        return "\n".join(out)

    def _md_section(self):
        rel = _rel(self.JSON)
        L = ["", "## 🔌🧩 场景迭代 · 插拔 / 摆盘 × Phase 0→4", ""]
        meta = (self.data or {}).get("meta") or {}
        if self.data is None:
            L.append("> ⛔ 尚未生成 — 点『🔄 重跑场景迭代』生成 (真源: `%s`)" % rel)
            return "\n".join(L)
        L.append("- 真源: `%s` ｜ 版本: %s ｜ 基线: %s ｜ 生成时间: %s"
                 % (rel, meta.get("version") or "—", meta.get("baseline") or "—", _ts_str(meta.get("ts"))))
        for key, _t in SCENE_BTNS:
            phs = self._sphases(key)
            s = self._scene(key) or {}
            L += ["", "### %s %s (任务 %s)" % (key, s.get("scene_name") or SCENE_NAME.get(key, ""),
                                               s.get("task") or SCENE_TASK.get(key, "—"))]
            if not phs:
                L.append("尚未生成")
                continue
            L += ["", "#### 组合迭代", "| 阶段 | 主题 | 指标数 | carried | added | upgraded | 总数量 | 上阶段增量 | 准入门 |",
                  "|---|---|---|---|---|---|---|---|---|"]
            prev = None
            for p in phs:
                cb = p.get("combo") or {}
                tot = cb.get("total")
                d = ("%+d" % (tot - prev)) if (isinstance(tot, (int, float)) and isinstance(prev, (int, float))) else "尚未生成"
                L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (p.get("phase"), p.get("name") or "", self._metric_count(p),
                            self._ids(cb.get("carried")),
                            ", ".join("%s %s (%s)" % (i.get("fn_id"), i.get("name"), i.get("why"))
                                      for i in self._dicts(cb.get("added"))) or "无",
                            ", ".join("%s %s (%s)" % (i.get("fn_id"), i.get("name"), i.get("why"))
                                      for i in self._dicts(cb.get("upgraded"))) or "无",
                            ("尚未生成" if tot is None else tot), d, self._entry_txt(p.get("entry"))))
                if isinstance(tot, (int, float)):
                    prev = tot
            L += ["", "#### 配置完备性核验 + run.mode", "| 阶段 | 启用节点 | 组合映射 | coverage | missing | extra | 可作改配置依据 | run.mode | 备注 |",
                  "|---|---|---|---|---|---|---|---|---|"]
            for p in phs:
                cc = p.get("config_check") or {}
                run = p.get("run") or {}
                L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (p.get("phase"), cc.get("enabled_nodes"), cc.get("combo_mapped"),
                            cc.get("coverage"), self._lst(cc.get("missing"), 9), self._lst(cc.get("extra"), 9),
                            ("✅ 可" if cc.get("pass") is True else ("⛔ 不可" if cc.get("pass") is False else "尚未生成")),
                            run.get("mode") or "未测", run.get("note") or ""))
            L += ["", "#### 迭代验证 (实测 vs 目标)",
                  "| 阶段 | 指标 | 实测 | 单位 | 目标 | 判定 | 证据类 | 样本 | 帧龄(s) | 真源 |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
            for p in phs:
                for m in (p.get("verification") or {}).get("metrics") or []:
                    if isinstance(m, dict):
                        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                                 % (p.get("phase"), m.get("name") or m.get("id"), _fnum(m.get("value")),
                                    m.get("unit") or "", m.get("target"), m.get("verdict"), m.get("mode"),
                                    m.get("n"), m.get("age_s"), m.get("src") or m.get("note") or ""))
        c = (self.data or {}).get("comparison") or {}
        L += ["", "### 对比分析", "", "#### ① 场景 × 阶段矩阵",
              "| 指标 | 单位 | 目标 | FW p0 | FW p1 | FW p2 | FW p3 | FW p4 | TRAY p0 | TRAY p1 | TRAY p2 | TRAY p3 | TRAY p4 | 判定 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in c.get("matrix") or []:
            if isinstance(r, dict):
                fw, tr = r.get("FW") or {}, r.get("TRAY") or {}
                L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                         % (r.get("name") or r.get("id"), r.get("unit"), r.get("target"),
                            *[_fnum(fw.get("p%d" % k)) for k in range(5)],
                            *[_fnum(tr.get("p%d" % k)) for k in range(5)], r.get("verdict")))
        L += ["", "#### ② 逐阶段达标率", "| 阶段 | FW 达标 | FW 总数 | TRAY 达标 | TRAY 总数 |", "|---|---|---|---|---|"]
        pr = c.get("pass_rate") or {}
        fwm = {(x or {}).get("phase"): x for x in (pr.get("FW") or []) if isinstance(x, dict)}
        trm = {(x or {}).get("phase"): x for x in (pr.get("TRAY") or []) if isinstance(x, dict)}
        for ph in sorted(set(list(fwm) + list(trm)), key=_phase_key):
            a, b = fwm.get(ph) or {}, trm.get(ph) or {}
            L.append("| %s | %s | %s | %s | %s |" % (ph, a.get("pass", "尚未生成"), a.get("total", "尚未生成"),
                                                     b.get("pass", "尚未生成"), b.get("total", "尚未生成")))
        L += ["", "#### ③ 组合增量", "| 场景 | 新增 | 升级 |", "|---|---|---|"]
        for k, _t in SCENE_BTNS:
            e = (c.get("combo_delta") or {}).get(k) or {}
            L.append("| %s | %s | %s |" % (k, e.get("added", "尚未生成"), e.get("upgraded", "尚未生成")))
        L += ["", "#### ④ 与基线对比 (基线 %s)" % (((self.data or {}).get("meta") or {}).get("baseline") or "尚未生成"),
              "| 场景 | 提升 | 持平 | 回退 |", "|---|---|---|---|"]
        for k, _t in SCENE_BTNS:
            e = (c.get("vs_baseline") or {}).get(k) or {}
            L.append("| %s | %s | %s | %s |" % (k, e.get("improved", "尚未生成"), e.get("flat", "尚未生成"),
                                                e.get("regressed", "尚未生成")))
        return "\n".join(L)

    def _csv(self):
        """当前子视图对应的 CSV (子视图 0=组合迭代 1=迭代验证 2=对比矩阵)。"""
        i = self.sub.currentIndex()
        if i == 0:
            L = ["场景,阶段,主题,指标数,carried,added,upgraded,总数量,相对上阶段增量,准入门"]
            prev = None
            for p in self._sphases():
                cb = p.get("combo") or {}
                tot = cb.get("total")
                d = ("%+d" % (tot - prev)) if (isinstance(tot, (int, float)) and isinstance(prev, (int, float))) else "尚未生成"
                L.append(",".join('"%s"' % str(x).replace('"', "'") for x in
                                  (self.scene, p.get("phase"), p.get("name") or "", self._metric_count(p),
                                   self._ids(cb.get("carried")),
                                   " | ".join("%s %s (%s)" % (x.get("fn_id"), x.get("name"), x.get("why"))
                                              for x in self._dicts(cb.get("added"))) or "无",
                                   " | ".join("%s %s (%s)" % (x.get("fn_id"), x.get("name"), x.get("why"))
                                              for x in self._dicts(cb.get("upgraded"))) or "无",
                                   ("尚未生成" if tot is None else tot), d, self._entry_txt(p.get("entry")))))
                if isinstance(tot, (int, float)):
                    prev = tot
            return "\n".join(L)
        if i == 1:
            L = ["场景,阶段,性能指标,实测值,单位,目标,判定,证据类,样本量,帧龄(s),真源/备注"]
            for p in self._sphases():
                for m in (p.get("verification") or {}).get("metrics") or []:
                    if isinstance(m, dict):
                        L.append(",".join('"%s"' % str(x).replace('"', "'") for x in
                                          (self.scene, p.get("phase"), m.get("name") or m.get("id"),
                                           _fnum(m.get("value")), m.get("unit"), m.get("target"),
                                           m.get("verdict"), m.get("mode"), m.get("n"), m.get("age_s"),
                                           m.get("src") or m.get("note") or "")))
            return "\n".join(L)
        L = ["性能指标,单位,目标,FW p0,FW p1,FW p2,FW p3,FW p4,TRAY p0,TRAY p1,TRAY p2,TRAY p3,TRAY p4,判定"]
        for r in ((self.data or {}).get("comparison") or {}).get("matrix") or []:
            if isinstance(r, dict):
                fw, tr = r.get("FW") or {}, r.get("TRAY") or {}
                L.append(",".join('"%s"' % str(x).replace('"', "'") for x in
                                  ([r.get("name") or r.get("id"), r.get("unit"), r.get("target")]
                                   + [_fnum(fw.get("p%d" % k)) for k in range(5)]
                                   + [_fnum(tr.get("p%d" % k)) for k in range(5)] + [r.get("verdict")])))
        return "\n".join(L)


# ─────────────────────────── 自检 / 截图入口 ───────────────────────────
def _selftest(args):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    panel = IterationRoadmapPanel(path=args.path)
    _wh = str(getattr(args, "wh", "") or "")
    if "x" in _wh:                                          # 截长图取证 (对比分析四段一屏看完)
        try:
            _w, _h = (int(x) for x in _wh.split("x", 1))
            panel.resize(_w, _h)
        except ValueError:
            pass
    else:
        panel.resize(1500, 1000)
    panel.show()
    app.processEvents()
    # 🔌🧩 场景迭代: 可指定另一个真源 (fixture / 缺失用例) + 选场景 + 选子视图
    sv = panel.scene_view
    if getattr(args, "scene_json", None):
        sv.JSON = args.scene_json
        sv.reload()
    if args.tab is not None:                    # 先切页: 切页会重渲染 (会在其后重设场景/子视图)
        panel.tabs.setCurrentIndex(args.tab)
        app.processEvents()
    if getattr(args, "scene", None):
        sv.set_scene(args.scene)
    if getattr(args, "scene_tab", None) is not None:
        sv.sub.setCurrentIndex(args.scene_tab)
        sv._render_sub()
    if getattr(args, "scene_mode", None) is not None:
        sv.cmode.setCurrentIndex(args.scene_mode)
    if getattr(args, "expand", False):
        sv.expand_all()
    app.processEvents()
    if getattr(args, "rerun", False):
        rc = panel.rerun()
        print("rerun_rc=%s" % rc)
        print("status: %s" % panel.lb_status.text())
    if getattr(args, "scene_rerun", False):
        print("scene_rerun_rc=%s" % sv.rerun())
    app.processEvents()
    if args.shot:
        _w = sv if getattr(args, "grab_scene", False) else panel
        _w.grab().save(args.shot)
        print("shot_saved=%s" % args.shot)
    print("meta: %s" % panel.lb_meta.text())
    print("roadmap_cards=%d" % len([w for w in panel.road_host.findChildren(QFrame)]))
    print("verify_rows=%d" % panel.vtab.rowCount())
    print("trend_rows=%d" % panel.ttab.rowCount())
    print("baseline_rows=%d" % panel.btab.rowCount())
    print("vsum: %s" % panel.lb_vsum.text())
    print("vs_baseline: %s" % panel.lb_base.text().replace("\n", " | "))
    # ── 🔌🧩 场景迭代真实读数 (截图同一份) ──
    print("scene_json: %s" % sv.JSON)
    print("scene_selected: %s" % sv.scene)
    print("scene_meta: %s" % sv.lb_scene.text())
    print("scene_status: %s" % (sv.lb_status.text() if sv.lb_status.isVisible() else "(无横幅 · 真源正常)"))
    print("scene_read_err: %s" % (sv.read_err or "(无)"))
    print("combo_rows: %d  (含折叠明细行)" % sv.ctab.rowCount())
    print("combo_sum: %s" % sv.lb_combo_sum.text())
    print("combo_hint: %s" % sv.lb_combo_hint.text())
    print("combo_expanded: %d 行可见 (折叠明细行 %d)"
          % (sum(0 if sv.ctab.isRowHidden(d) else 1 for d in sv._det_of_main.values()), len(sv._det_of_main)))
    for r in range(min(5, sv.ctab.rowCount())):
        cells = []
        for c in range(sv.ctab.columnCount()):
            it = sv.ctab.item(r, c)
            cells.append(it.text() if it else ("[明细行]" if sv.ctab.cellWidget(r, 0) else ""))
        if cells:
            print("  combo_row%d: %s" % (r, " | ".join(cells)))
    print("cfg_rows: %d" % sv.ktab.rowCount())
    for r in range(min(2, sv.ktab.rowCount())):
        print("  cfg_row%d: %s" % (r, " | ".join(sv.ktab.item(r, c).text() if sv.ktab.item(r, c) else ""
                                                 for c in range(sv.ktab.columnCount()))))
    print("sverify_rows: %d   svsum: %s" % (sv.vtab2.rowCount(), sv.lb_vsum.text()))
    for r in range(min(3, sv.vtab2.rowCount())):
        print("  sver_row%d: %s" % (r, " | ".join(sv.vtab2.item(r, c).text() if sv.vtab2.item(r, c) else ""
                                                  for c in range(sv.vtab2.columnCount()))))
    print("matrix_rows: %d  (mode=%s)" % (sv.mtab.rowCount(), sv.cmode.currentText()))
    for r in range(min(3, sv.mtab.rowCount())):
        cells = [sv.mtab.item(r, c).text() if sv.mtab.item(r, c) else "" for c in range(sv.mtab.columnCount())
                 if not sv.mtab.isColumnHidden(c)]
        print("  matrix_row%d: %s" % (r, " | ".join(cells)))
    print("passrate_rows: %d" % sv.ptab.rowCount())
    for r in range(sv.ptab.rowCount()):
        print("  prate_row%d: %s" % (r, " | ".join(sv.ptab.item(r, c).text() if sv.ptab.item(r, c) else ""
                                                   for c in range(sv.ptab.columnCount()))))
    print("combo_delta_rows: %d" % sv.dtab.rowCount())
    for r in range(sv.dtab.rowCount()):
        print("  delta_row%d: %s" % (r, " | ".join(sv.dtab.item(r, c).text() if sv.dtab.item(r, c) else ""
                                                   for c in range(sv.dtab.columnCount()))))
    print("vsbase_rows: %d" % sv.btab2.rowCount())
    for r in range(sv.btab2.rowCount()):
        print("  vsbase_row%d: %s" % (r, " | ".join(sv.btab2.item(r, c).text() if sv.btab2.item(r, c) else ""
                                                    for c in range(sv.btab2.columnCount()))))
    print("scene_vsbase: %s" % sv.lb_sbase.text().replace("\n", " | "))
    print("scene_copy_view_chars: %d" % len(sv._view_text()))
    if args.export:
        print("md=%s" % panel.export_md())
        print("csv=%s" % panel.export_csv())
    sys.stdout.flush()
    os._exit(0)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="🗺 迭代路线图面板 (评估分析页内嵌)")
    ap.add_argument("--path", default=None, help="iteration_roadmap.json 路径 (默认 zmax_data/eval/)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shot", default=None, help="截图保存路径")
    ap.add_argument("--tab", type=int, default=None, help="切到第 N 个子视图 (0/1/2 路线图页 · 3 🔌🧩场景迭代)")
    ap.add_argument("--rerun", action="store_true", help="先点一次『重跑迭代验证』")
    ap.add_argument("--export", action="store_true", help="导出 Markdown + CSV")
    # 🔌🧩 场景迭代
    ap.add_argument("--scene-json", default=None, help="scene_phase_iteration.json 路径 (默认 zmax_data/eval/)")
    ap.add_argument("--scene", default=None, help="选场景 FW / TRAY (默认=当前激活任务对应场景)")
    ap.add_argument("--scene-tab", type=int, default=None, help="场景子视图 0 组合迭代 / 1 迭代验证 / 2 对比分析")
    ap.add_argument("--scene-mode", type=int, default=None, help="对比分析矩阵视图 0 并列 / 1 只看FW / 2 只看TRAY")
    ap.add_argument("--scene-rerun", action="store_true", help="点一次『🔄 重跑场景迭代』(真实 subprocess)")
    ap.add_argument("--expand", action="store_true", help="展开组合迭代的元任务组合明细 (折叠行)")
    ap.add_argument("--grab-scene", action="store_true", help="截图只抓 🔌🧩 场景迭代控件")
    ap.add_argument("--wh", default=None, help="面板尺寸 WxH (如 1500x2200, 截长图看全对比分析四段)")
    args = ap.parse_args(argv)
    return _selftest(args)


if __name__ == "__main__":
    sys.exit(main())
