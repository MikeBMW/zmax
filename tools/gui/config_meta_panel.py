#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_meta_panel.py — 🧬 配置中心「功能元数据」页 (独立 QWidget, 不自建窗口)  2026-10-10

老倪:
  「左侧栏的配置中心, 我可以定义元数据; 所有功能, 要通过功能模块的 配置中心 修改, 要可以配置所有的功能」
  「系统架构要根据实际情况同步修改 … 表现 系统层 即 功能配置 参数数值 的关系」

本页 = 元数据层 (tools/config_meta.py) 的**交互面**, 与 param_center.py (数字层) 互补:
  左: 功能树   子系统 → 功能 (74 个, ✅完整 / ❌缺维度 一眼可辨)
  右上: 选中功能的元数据表单 —— 字段(输入/输出) · 参数清单(范围/单位/默认/枚举) · 归属子系统与层 ·
        依赖的功能/参数/产品特征 · 验证方法
  右下: 参数当前值表 (值从 tools/param_registry.py 实时读, 不是库里快照) + 「影响链」(该功能用到哪些参数)
  顶部: 刷新 (重读 SQLite/JSON + 重读 param_registry) · 重建元数据 (调 config_meta.build)

只交新文件: 不建窗口 (QWidget), 不碰 studio.py / param_center.py / engineering_db.py; 接线由主节点做。
"""
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                             QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

C_BG, C_BG2, C_CARD = "#0f1318", "#131823", "#1a2230"
C_WHITE, C_GRAY, C_DIM, C_BORDER = "#e6edf3", "#9aa7b4", "#6e7b8a", "#2a3441"
C_BLUE, C_GREEN, C_GOLD, C_RED = "#4da3ff", "#00d4aa", "#ffc857", "#ff6b6b"
SYS_ICON = {"sys2": "🧠 System 2", "sys1": "🚀 System 1", "sys0": "🔧 System 0", "plat": "🏭 平台"}
CAT_ICON = {"calib": "🟡", "canvas": "🔵", "code": "🟣", "platform": "🟢", "switch": "🟠",
            "space": "🩷", "teach": "📍"}


def _cm():
    import config_meta as c
    return c


def _pr():
    try:
        import param_registry as p
        return p
    except Exception:                                                          # noqa: BLE001
        return None


class ConfigMetaPanel(QWidget):
    """🧬 功能元数据页 —— 74 个功能的字段/范围/单位/依赖/验证 + 参数当前值 + 影响链。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.meta = None
        self.reg = None
        self.err = None
        self._cur_fn = None
        self._build()
        self.reload()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("🧬 配置中心 · 功能元数据")
        t.setStyleSheet("color:%s; font-size:15pt; font-weight:700;" % C_WHITE)
        head.addWidget(t)
        head.addStretch()
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color:%s; font-size:10pt;" % C_GRAY)
        head.addWidget(self.lbl_info)
        for txt, tip, fn in (("🔄 刷新", "重读工程库元数据 + param_registry 当前值", self.reload),
                             ("🧬 重建元数据", "调 tools/config_meta.py build 从工程库+param_registry 重生成", self.rebuild)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setStyleSheet("QPushButton{background:%s; color:%s; border:1px solid %s; border-radius:4px;"
                            " padding:6px 10px; font-size:10pt;} QPushButton:hover{border-color:%s;}"
                            % (C_CARD, C_WHITE, C_BORDER, C_BLUE))
            b.clicked.connect(fn)
            head.addWidget(b)
        root.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        # 左: 子系统 → 功能 树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["子系统 / 功能 (配置面)"])
        self.tree.setStyleSheet("QTreeWidget{background:%s; color:%s; border:1px solid %s; font-size:10.5pt;}"
                                " QTreeWidget::item:selected{background:%s;}"
                                % (C_BG2, C_WHITE, C_BORDER, C_CARD))
        self.tree.itemClicked.connect(self._on_tree)
        split.addWidget(self.tree)

        # 右: 元数据 + 参数值 + 影响链
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        self.lbl_fn = QLabel("← 选一个功能看它的元数据")
        self.lbl_fn.setWordWrap(True)
        self.lbl_fn.setStyleSheet("color:%s; font-size:12pt; font-weight:700;" % C_WHITE)
        rl.addWidget(self.lbl_fn)

        self.meta_tree = QTreeWidget()
        self.meta_tree.setHeaderLabels(["项", "值"])
        self.meta_tree.setColumnWidth(0, 210)
        self.meta_tree.setStyleSheet("QTreeWidget{background:%s; color:%s; border:1px solid %s; font-size:10pt;}"
                                     % (C_BG2, C_WHITE, C_BORDER))
        rl.addWidget(self.meta_tree, 3)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["用途", "参数", "当前值", "默认", "范围/档位", "单位", "真源"])
        self.table.setStyleSheet("QTableWidget{background:%s; color:%s; gridline-color:%s; font-size:10pt;}"
                                 " QHeaderView::section{background:%s; color:%s; padding:5px;}"
                                 % (C_BG2, C_WHITE, C_BORDER, C_CARD, C_GRAY))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        rl.addWidget(self.table, 3)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setStyleSheet("QTextEdit{background:%s; color:%s; border:1px solid %s; font-size:10pt;}"
                               % (C_BG2, C_WHITE, C_BORDER))
        rl.addWidget(self.txt, 2)
        split.addWidget(right)
        split.setSizes([340, 980])
        root.addWidget(split, 1)

        hint = QLabel("元数据真源: data/database/zmax/config_meta.json (从工程库 + param_registry 生成) · "
                      "参数当前值实时读 param_registry · 「参数值」由 数字层(参数中心) 改, 「字段定义」由本页看")
        hint.setStyleSheet("color:%s; font-size:9.5pt;" % C_GRAY)
        root.addWidget(hint)

    # ── 数据 ──────────────────────────────────────────────────────────────
    def reload(self):
        self.err = None
        try:
            self.meta = _cm().load()
        except Exception as e:                                                 # noqa: BLE001
            self.meta, self.err = None, "%s: %s" % (type(e).__name__, e)
        # 数字面当前值 (实时)
        pr = _pr()
        self.reg = {}
        if pr is not None:
            try:
                self.reg = {p["param_id"]: p for p in pr.registry()["params"]}
            except Exception:                                                  # noqa: BLE001
                self.reg = {}
        if self.meta is None:
            self.lbl_info.setText("元数据读取失败: %s" % self.err)
            return
        c = self.meta["coverage"]
        self.lbl_info.setText("%d 功能 · 完整 %d · 不完整 %d · 参数 %d (物理单位 %.0f%%)" %
                              (c["total"], c["complete"], len(c["incomplete"]),
                               c["params_total"], c["physical_unit_ratio"] * 100))
        self._fill_tree()
        if self._cur_fn and self._cur_fn in self.meta["functions"]:
            self._show(self._cur_fn)

    def _fill_tree(self):
        keep = self._cur_fn
        self.tree.clear()
        fns = self.meta["functions"]
        by_sys = {}
        for fid, r in fns.items():
            by_sys.setdefault(r["system_id"], []).append((fid, r))
        order = {"sys2": 0, "sys1": 1, "sys0": 2, "plat": 3}
        for sid in sorted(by_sys, key=lambda s: order.get(s, 9)):
            items = sorted(by_sys[sid], key=lambda x: x[0])
            ncomp = sum(1 for _, r in items if r["completeness"]["complete"])
            top = QTreeWidgetItem(["%s  (%d/%d 完整)" % (SYS_ICON.get(sid, sid), ncomp, len(items))])
            top.setForeground(0, QColor(C_GOLD))
            for fid, r in items:
                mark = "✅" if r["completeness"]["complete"] else "❌"
                it = QTreeWidgetItem(["%s %s %s" % (mark, fid, r["name"][:34])])
                it.setData(0, Qt.UserRole, fid)
                if not r["completeness"]["complete"]:
                    it.setForeground(0, QColor(C_RED))
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        if keep:
            self._select_fn(keep)

    def _select_fn(self, fid):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.data(0, Qt.UserRole) == fid:
                    self.tree.setCurrentItem(ch)
                    return

    def _on_tree(self, item):
        fid = item.data(0, Qt.UserRole)
        if fid:
            self._show(fid)

    def _show(self, fid):
        r = self.meta["functions"].get(fid)
        if not r:
            return
        self._cur_fn = fid
        cc = r["completeness"]
        self.lbl_fn.setText("%s  %s    %s" % (fid, r["name"],
                                              "✅ 完整" if cc["complete"] else "❌ 缺 " + ",".join(cc["missing"])))
        # 元数据表单
        mt = self.meta_tree
        mt.clear()

        def sect(title, color=C_GOLD):
            it = QTreeWidgetItem([title, ""])
            it.setForeground(0, QColor(color))
            mt.addTopLevelItem(it)
            return it

        def row(parent, k, v, color=C_WHITE):
            it = QTreeWidgetItem(["  " + k, str(v)])
            it.setForeground(1, QColor(color))
            parent.addChild(it)
            return it

        top = sect("归属")
        row(top, "子系统", "%s (%s)" % (r["subsystem"], r["system_id"]))
        row(top, "层", r["layer"])
        row(top, "模块", r["module_ref"])
        row(top, "代码源", r["code_file"] or "(未声明)")

        f = r["fields"]
        top = sect("字段 · 输入/输出")
        row(top, "输入", "; ".join(f["inputs"]) or "(未定义)", C_WHITE if f["inputs"] else C_DIM)
        row(top, "输出", "; ".join(f["outputs"]) or "(未定义)", C_WHITE if f["outputs"] else C_DIM)
        if f["declared_flags"]:
            row(top, "节点声明标记", ", ".join("%s=%s" % (k, f["declared_flags"][k])
                                              for k in list(f["declared_flags"])[:8]), C_GRAY)

        top = sect("参数清单 (%d)" % len(f["parameters"]))
        for p in f["parameters"][:60]:
            rng = ("[%s, %s]" % (p["min"], p["max"])) if p["min"] is not None else (
                ("档位: " + ",".join(map(str, p["choices"]))) if p["choices"] else "范围未定义")
            row(top, "%s %s" % (CAT_ICON.get(p["cat"], ""), p["id"]),
                "%s %s 默认%s %s" % (str(p["value"])[:12], p["unit"] or "-", str(p["default"])[:10], rng))
        if len(f["parameters"]) > 60:
            row(top, "…", "另 %d 个参数" % (len(f["parameters"]) - 60), C_DIM)

        d = r["deps"]
        top = sect("依赖")
        row(top, "依赖功能", "; ".join(d["functions"]) or "(无)", C_WHITE if d["functions"] else C_DIM)
        row(top, "依赖产品特征", ", ".join(d["product_features"]) or "(无)", C_WHITE if d["product_features"] else C_DIM)
        row(top, "依赖模块", d["module"] or "(无)")

        top = sect("验证方法 (%d)" % r["verification"]["count"])
        for m in r["verification"]["methods"]:
            row(top, "•", m)
        for i in range(mt.topLevelItemCount()):
            mt.topLevelItem(i).setExpanded(True)

        # 参数当前值表 (实时)
        self.table.setRowCount(0)
        for p in f["parameters"]:
            rp = self.reg.get(p["id"], {})
            val = rp.get("value", p["value"])
            rows = self.table.rowCount()
            self.table.insertRow(rows)
            rng = ("[%s, %s]" % (p["min"], p["max"])) if p["min"] is not None else (
                ("档位: " + ",".join(map(str, p["choices"]))) if p["choices"] else "范围未定义")
            cells = [CAT_ICON.get(p["cat"], p["cat"] or ""), p["id"], str(val), str(p["default"]),
                     rng, p["unit"] or "-", (p["source"] or "")[:44]]
            for c, txt in enumerate(cells):
                self.table.setItem(rows, c, QTableWidgetItem(txt))
        self.table.resizeColumnsToContents()

        # 影响链
        lines = ["🧩 「%s」用到哪些参数 (影响链)" % r["name"], ""]
        groups = {}
        for p in f["parameters"]:
            groups.setdefault(p["cat"] or "other", []).append(p["id"])
        for cat, ids in groups.items():
            lines.append("  %s %s (%d):" % (CAT_ICON.get(cat, ""), cat, len(ids)))
            for pid in ids[:16]:
                rp = self.reg.get(pid, {})
                lines.append("     • %s  →  当前 %s  (真源 %s)" %
                             (pid, rp.get("value", "?"), rp.get("source", "?")))
            if len(ids) > 16:
                lines.append("     … 另 %d 个" % (len(ids) - 16))
        lines += ["", "参数值在「🎛 参数中心」改 (数字层) · 本页负责功能↔参数↔子系统 的字段关系 (元数据层)。"]
        self.txt.setPlainText("\n".join(lines))

    def rebuild(self):
        pr = _cm()
        try:
            pr.build(force=True, quiet=True)
        except Exception as e:                                                 # noqa: BLE001
            self.lbl_info.setText("重建失败: %r" % (e,))
            return
        # 重载模块缓存 (避免旧 dict)
        import importlib
        importlib.reload(pr)
        self.reload()


def build_page():
    """给主节点接线用的便捷工厂 (返回 QWidget, 可 stack.addWidget)。"""
    return ConfigMetaPanel()


def _selftest():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    w = ConfigMetaPanel()
    w.resize(1500, 900)
    w.show()
    for _ in range(6):
        app.processEvents()
    ok = True
    ok &= w.tree.topLevelItemCount() == 4
    ok &= w.meta["coverage"]["total"] == 74
    w._show("FN-SYS0-37")
    app.processEvents()
    ok &= w.table.rowCount() > 0
    print("SELFTEST", "PASS" if ok else "FAIL",
          "tree_tops=%d rows=%d complete=%d/74" %
          (w.tree.topLevelItemCount(), w.table.rowCount(), w.meta["coverage"]["complete"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
