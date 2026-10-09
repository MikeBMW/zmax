# -*- coding: utf-8 -*-
"""VEH.6 配置中心 · 页面 (主要工程配置 = 任务配置)

老倪 2026-10-09: 「主要工程配置, 例如 上下料的任务配置」⇒ 任务配置是首屏。
结构: 左五域树 + 右工作区(页签, 首屏=任务配置) + 底部结果面板(点了必出结果)。

本文件只依赖 PyQt5 + json, **不 import studio** (颜色由 studio 传进来), 保证可离屏单测。
每个按钮都调用 tools/config_center.py 的同一份函数 (一份逻辑两处用), 输出抓到面板里。
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QColor, QFont  # noqa: E402
from PyQt5.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                             QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                             QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

TASKS_J = os.path.join(ROOT, "config", "tasks", "tasks.json")
MCD_J = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
MATCH_J = os.path.join(ROOT, "config", "mcd", "match_matrix.json")
ORDERS_D = os.path.join(ROOT, "config", "orders")

DEFAULT_THEME = {"C_BG": "#11151c", "C_BG2": "#161b24", "C_CARD": "#1b222c", "C_BORDER": "#2a3340",
                 "C_WHITE": "#e8edf4", "C_GRAY": "#8b98a8", "C_GREEN": "#3fbf7f", "C_RED": "#e05a5a",
                 "C_YELLOW": "#e0b64a", "C_BLUE": "#4a90e0"}


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _run(fn, **kw):
    """跑 config_center 的同名命令, 抓 stdout 成文本 (点了必出结果)。"""
    import argparse
    import config_center as cc
    a = argparse.Namespace(json=False, scene=kw.get("scene"), task=kw.get("task"),
                           cmd=kw.get("cmd", fn), arg=kw.get("arg"))
    buf = io.StringIO()
    target = getattr(cc, f"cmd_{fn}", None)
    with redirect_stdout(buf):
        if target is None:
            print(f"⛔ 未实现的命令: {fn}")
        else:
            try:
                target(a)
            except SystemExit:
                pass
            except Exception as e:  # noqa: BLE001
                print(f"⛔ 执行异常: {type(e).__name__}: {e}")
    return buf.getvalue()


def _mk_table(headers, rows, theme, widths=None):
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setFont(QFont("Consolas", 10))
    t.setStyleSheet(f"QTableWidget{{color:{theme['C_WHITE']};background:{theme['C_CARD']};"
                    f"gridline-color:{theme['C_BORDER']};border:1px solid {theme['C_BORDER']};}}"
                    f"QHeaderView::section{{background:{theme['C_BG2']};color:{theme['C_GRAY']};"
                    f"border:none;padding:6px;}}")
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            s = str(val)
            if s.startswith("⛔") or "缺失" in s:
                it.setForeground(QColor(theme["C_RED"]))
            elif s.startswith("✅"):
                it.setForeground(QColor(theme["C_GREEN"]))
            t.setItem(r, c, it)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    if widths:
        for i, w in enumerate(widths):
            if w:
                t.setColumnWidth(i, w)
    return t


def _btn(text, theme):
    b = QPushButton(text)
    b.setFont(QFont("Arial", 10))
    b.setStyleSheet(f"background:{theme['C_CARD']};color:{theme['C_WHITE']};"
                    f"border:1px solid {theme['C_BORDER']};border-radius:4px;padding:5px 12px;")
    return b


class ConfigCenterPage(QWidget):
    """左五域树 + 右工作区 (首屏=任务配置) + 底部结果面板。"""

    def __init__(self, model_page=None, theme=None):
        super().__init__()
        th = dict(DEFAULT_THEME)
        th.update(theme or {})
        self.th = th
        self.setStyleSheet(f"background:{th['C_BG']};")

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── 顶栏: 站点 / 描述 / 授权 ──
        bar = QHBoxLayout()
        d = _j(MCD_J, {}) or {}
        meta = d.get("_meta", {})
        tk = _j(TASKS_J, {}) or {}
        info = QLabel(f"站点 SITE-A.ST11   ·   描述 {meta.get('schema', '缺')} @ {meta.get('generated_at', '—')}"
                      f"   ·   任务 {len(tk.get('tasks', []))} 条   ·   授权: 无")
        info.setFont(QFont("Consolas", 10))
        info.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        bar.addWidget(info)
        bar.addStretch()
        for txt, fn in (("🔍 全链校验", "check"), ("📋 任务配置", "tasks"), ("⚙️ 工程配置", "list")):
            b = _btn(txt, th)
            b.clicked.connect(lambda _, f=fn: self._run_into(f))
            bar.addWidget(b)
        root.addLayout(bar)

        # ── 左树 + 右页签 ──
        sp = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFont(QFont("Arial", 10))
        self.tree.setStyleSheet(f"QTreeWidget{{color:{th['C_WHITE']};background:{th['C_CARD']};"
                                f"border:1px solid {th['C_BORDER']};}}")
        self._fill_tree(d, tk)
        self.tree.itemDoubleClicked.connect(self._on_tree)
        sp.addWidget(self.tree)

        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Arial", 10))
        self.tabs.setStyleSheet(f"QTabWidget::pane{{border:1px solid {th['C_BORDER']};}}"
                                f"QTabBar::tab{{background:{th['C_BG2']};color:{th['C_GRAY']};padding:6px 14px;}}"
                                f"QTabBar::tab:selected{{background:{th['C_CARD']};color:{th['C_WHITE']};}}")
        self._build_tabs(d, tk, model_page)
        sp.addWidget(self.tabs)
        sp.setSizes([230, 1000])
        root.addWidget(sp, 1)

        # ── 底部结果面板 (点了必出结果) ──
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setFixedHeight(168)
        self.out.setFont(QFont("Consolas", 9))
        self.out.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                               f"border:1px solid {th['C_BORDER']};")
        self.out.setPlainText(_run("overview"))
        root.addWidget(self.out)
        self.setLayout(root)

    # ── 左侧域树 ──
    def _fill_tree(self, d, tk):
        chars = d.get("CHARACTERISTIC", [])
        doms = []
        for dom in ("模型配置", "工程配置", "功能配置", "性能配置"):
            cs = [c for c in chars if c.get("domain") == dom]
            rd = sum(1 for c in cs if c.get("ready"))
            doms.append((f"{dom}  {rd}/{len(cs)}", "⛔" if rd < len(cs) else "✅",
                         [c["id"] for c in cs if not c.get("ready")]))
        doms.append((f"工艺·工单  任务 {len(tk.get('tasks', []))}",
                     "⛔" if (tk.get("tasks") and any(t.get("blocked_by_site") for t in tk["tasks"])) else "✅",
                     [t["task_id"] for t in tk.get("tasks", [])]))
        self.tree.clear()
        for label, mark, kids in doms:
            it = QTreeWidgetItem([f"{mark} {label}"])
            for k in kids:
                QTreeWidgetItem(it, [f"   {k}"])
            self.tree.addTopLevelItem(it)
            it.setExpanded(label.startswith("工艺"))

    def _on_tree(self, item, _col):
        txt = item.text(0)
        if "任务配置" in txt or "工艺" in txt:
            self.tabs.setCurrentIndex(0)
        self._run_into("tasks" if "TASK" in txt.upper() else "overview")

    # ── 右侧页签 ──
    def _build_tabs(self, d, tk, model_page):
        th = self.th
        # 1) 任务配置 (首屏)
        self.tasks_table = _mk_table(
            ["任务ID", "类型", "适用段", "粒度", "步骤", "触发", "目标", "状态"],
            [[t["task_id"], t["recipe_type"], f"{len(t['applies_segments'])}/8",
              len(t.get("variants", [])), " → ".join(s["name"] for s in t.get("steps", [])),
              t["trigger"], json.dumps(t.get("targets", {}), ensure_ascii=False),
              ("⛔ 缺站点几何" + str(len(t["blocked_by_site"]))) if t.get("blocked_by_site") else "✅"]
             for t in tk.get("tasks", [])], th)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        for txt, fn, kw in (("✅ 生成工单", "order", {"scene": "SCN-02-HANDLE"}),
                            ("🔍 全链校验", "check", {}),
                            ("📄 配方", "recipe", {}),
                            ("🧱 变体", "variants", {}),
                            ("📋 导出 JSON", "tasks", {})):
            b = _btn(txt, th)
            b.clicked.connect(lambda _, f=fn, k=kw: self._run_into(f, **k))
            row.addWidget(b)
        row.addStretch()
        l.addLayout(row); l.addWidget(self.tasks_table, 1)
        self.tabs.addTab(w, "📋 任务配置")

        # 2) 工程配置 (参数表三列)
        cs = [c for c in d.get("CHARACTERISTIC", []) if c.get("domain") == "工程配置"]
        t2 = _mk_table(["参数", "级", "权限", "真源", "测量: 当前值", "诊断: 判据"],
                       [[c["id"], c["grade"], c["perm"], str(c["src"]).split("#")[0],
                         ("缺失 ⛔" if c.get("value") is None else str(c.get("value"))[:22]),
                         str(c["judge"])[:60]] for c in cs], th)
        w2 = QWidget(); l2 = QVBoxLayout(w2); l2.setContentsMargins(6, 6, 6, 6); l2.addWidget(t2)
        self.tabs.addTab(w2, "⚙️ 工程配置")

        # 3) 功能·性能·模型 (参数表)
        cs3 = [c for c in d.get("CHARACTERISTIC", []) if c.get("domain") in ("功能配置", "性能配置", "模型配置")]
        t3 = _mk_table(["域", "参数", "级", "权限", "真源", "值", "判据"],
                       [[c["domain"], c["id"], c["grade"], c["perm"], str(c["src"]).split("#")[0],
                         ("缺失 ⛔" if c.get("value") is None else str(c.get("value"))[:20]),
                         str(c["judge"])[:48]] for c in cs3], th)
        w3 = QWidget(); l3 = QVBoxLayout(w3); l3.setContentsMargins(6, 6, 6, 6); l3.addWidget(t3)
        self.tabs.addTab(w3, "🧩 功能·性能·模型")

        # 4) 工单
        rows = []
        for f in sorted(glob.glob(os.path.join(ORDERS_D, "BS_*.json"))):
            b = _j(f, {}) or {}
            i, r = b.get("identity", {}), b.get("readiness", {})
            rows.append([i.get("order_no", ""), i.get("name", ""), len(b.get("bom", [])),
                         len(b.get("process", [])), f"{r.get('site_ok', '?')}/9",
                         "⛔ 站点几何" if r.get("site_missing") else "✅"])
        t4 = _mk_table(["工单号", "场景", "BOM", "步骤", "站点就绪", "状态"], rows, th)
        w4 = QWidget(); l4 = QVBoxLayout(w4); l4.setContentsMargins(6, 6, 6, 6)
        r4 = QHBoxLayout()
        b4 = _btn("📋 工单列表", th); b4.clicked.connect(lambda: self._run_into("orders")); r4.addWidget(b4)
        r4.addStretch(); l4.addLayout(r4); l4.addWidget(t4, 1)
        self.tabs.addTab(w4, "🎯 工单")

        # 5) 模型 × 工程配置
        m = _j(MATCH_J, {}) or {}
        keys = (m.get("_meta", {}).get("site_keys") or [])
        rows5 = [[r["model"], r["layer"], r["domain"],
                  " ".join("✅" if r["cells"].get(k) == "OK" else
                           ("⛔" if r["cells"].get(k) == "缺项" else "·") for k in keys),
                  "✅" if r["usable_now"] else "⛔ " + r.get("verdict", "")[:40]]
                 for r in m.get("MODELS", [])]
        t5 = _mk_table(["模型", "层", "域", "工程配置(9 项)", "判定"], rows5, th)
        w5 = QWidget(); l5 = QVBoxLayout(w5); l5.setContentsMargins(6, 6, 6, 6); l5.addWidget(t5)
        self.tabs.addTab(w5, "🧠 模型匹配")

        # 6) 现有模型配置页 (整块搬进来, 不重写)
        if model_page is not None:
            self.tabs.addTab(model_page, "🧠 模型配置")

    # ── 结果面板 ──
    def _run_into(self, fn, **kw):
        self.out.setPlainText(_run(fn, **kw))

    def _run_noop(self):
        pass


def build_config_center(model_page=None, theme=None):
    """studio.py 调用入口: 返回配置中心新页 (失败时抛异常, 由 studio 兜底回退)。"""
    return ConfigCenterPage(model_page=model_page, theme=theme)
