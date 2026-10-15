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

自检 / 截图 (任一可用):
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/iteration_roadmap_panel.py --selftest
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/iteration_roadmap_panel.py \
        --shot /tmp/irm.png --tab 0 [--path <json>] [--rerun]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QApplication, QComboBox, QFrame, QGroupBox, QHBoxLayout,
                             QHeaderView, QLabel, QPushButton, QScrollArea, QTabWidget,
                             QTableWidget, QTableWidgetItem, QTextEdit, QToolButton,
                             QVBoxLayout, QWidget)

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
        out = os.path.join(self._reports_dir(), "iteration_roadmap_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(self._csv())
        self._log("💾 已导出 CSV: %s" % out)
        return out


# ─────────────────────────── 自检 / 截图入口 ───────────────────────────
def _selftest(args):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    panel = IterationRoadmapPanel(path=args.path)
    panel.resize(1500, 1000)
    panel.show()
    app.processEvents()
    if args.rerun:
        rc = panel.rerun()
        print("rerun_rc=%s" % rc)
        print("status: %s" % panel.lb_status.text())
    if args.tab is not None:
        panel.tabs.setCurrentIndex(args.tab)
        app.processEvents()
    if args.shot:
        panel.grab().save(args.shot)
        print("shot_saved=%s" % args.shot)
    print("meta: %s" % panel.lb_meta.text())
    print("roadmap_cards=%d" % len([w for w in panel.road_host.findChildren(QFrame)]))
    print("verify_rows=%d" % panel.vtab.rowCount())
    print("trend_rows=%d" % panel.ttab.rowCount())
    print("baseline_rows=%d" % panel.btab.rowCount())
    print("vsum: %s" % panel.lb_vsum.text())
    print("vs_baseline: %s" % panel.lb_base.text().replace("\n", " | "))
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
    ap.add_argument("--tab", type=int, default=None, help="切到第 N 个子视图 (0/1/2)")
    ap.add_argument("--rerun", action="store_true", help="先点一次『重跑迭代验证』")
    ap.add_argument("--export", action="store_true", help="导出 Markdown + CSV")
    args = ap.parse_args(argv)
    return _selftest(args)


if __name__ == "__main__":
    sys.exit(main())
