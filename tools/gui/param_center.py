#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""param_center.py — 🎛 参数中心 (全局可改数字 · 交互式编辑 · 改数即链动)  2026-10-09 老倪

老倪:
  「全局梳理所有可以更改的数字, 有默认值, 有调试参数, 有最大最小值; 当改变任意数值, 均可链动
    功能·性能·代码逻辑; 从顶层产品性能的数据改变, 直接调整代码; 中间的代码要完整映射这个全局架构。」

本页 = 数字的**唯一交互面** (数据面在 tools/param_registry.py, 真源在 config/… + 源码):
  · 左: 分类树 (🟡标定 / 🔵画布 / 🟣代码 / 🟢产品性能 / 🟠运行开关) + 搜索 + 「只看可写/只看缺口」过滤
  · 右: 数字表 —— 当前值·默认·最小·最大·单位·状态·真源位置·归属, 用颜色区分用途与状态
  · 双击一行 = 改数: 弹校验框 (范围/档位) → 先**预览影响链** (功能/模块/系统/KPI/代码位置) → 点「应用」才落真源
  · 落真源走 param_registry.set_param(write=True): 备份 → 写 → 回读核对; 代码常量写坏语法立即回滚
  · 下部: 影响链 + 改数事件日志 (每一步都可观察)
"""
import json
import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))

C_BG, C_BG2, C_CARD = "#0f1318", "#131823", "#1a2230"
C_WHITE, C_GRAY, C_DIM, C_BORDER = "#e6edf3", "#9aa7b4", "#6e7b8a", "#2a3441"
C_BLUE, C_GREEN, C_GOLD, C_RED = "#4da3ff", "#00d4aa", "#ffc857", "#ff6b6b"
CAT_ICON = {"calib": "🟡", "canvas": "🔵", "code": "🟣", "platform": "🟢", "switch": "🟠"}


def _pr():
    import param_registry as p
    return p


class ParamCenterPage(QWidget):
    """🎛 参数中心 —— 全局数字的梳理/编辑/链动面"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reg = None
        self.err = None
        self.cur_cat = None
        self.rows = []
        self._build()
        self.reload()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("🎛 参数中心 · 数据库服务")
        t.setStyleSheet("color:%s; font-size:15pt; font-weight:700;" % C_WHITE)
        head.addWidget(t)
        head.addStretch()
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color:%s; font-size:10pt;" % C_DIM)
        head.addWidget(self.lbl_info)
        for txt, tip, fn in (("🔁 重建工程库", "把真源(含最新参数)重新装进单一数据库文件", self.rebuild_db),
                             ("📋 复制清单", "复制当前过滤后的数字清单 (可贴到文档)", self.copy_rows),
                             ("💾 导出 JSON", "导出当前过滤后的数字清单", self.export_rows),
                             ("🔄 刷新", "重新扫描真源 (改了文件后点这里)", self.reload)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setStyleSheet("QPushButton{background:%s; color:%s; border:1px solid %s; border-radius:4px;"
                            " padding:6px 10px; font-size:10pt;} QPushButton:hover{border-color:%s;}"
                            % (C_CARD, C_WHITE, C_BORDER, C_BLUE))
            b.clicked.connect(fn)
            head.addWidget(b)
        root.addLayout(head)

        bar = QHBoxLayout()
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("🔎 搜数字 (名字/真源路径/单位, 如 insert_depth · plane_z · mm)…")
        self.ed_search.setStyleSheet("QLineEdit{background:%s; color:%s; border:1px solid %s; border-radius:4px;"
                                     " padding:6px; font-size:10.5pt;}" % (C_BG2, C_WHITE, C_BORDER))
        self.ed_search.textChanged.connect(self._refill)
        bar.addWidget(self.ed_search, 3)
        self.cb_writable = QCheckBox("只看可写")
        self.cb_gap = QCheckBox("只看缺口/未定义")
        for cb in (self.cb_writable, self.cb_gap):
            cb.setStyleSheet("QCheckBox{color:%s; font-size:10.5pt;}" % C_GRAY)
            cb.stateChanged.connect(self._refill)
            bar.addWidget(cb)
        bar.addStretch()
        bar.addWidget(QLabel("用途:"))
        self.lbl_legend = QLabel("  ".join("%s%s" % (CAT_ICON[k], v) for k, v in
                                          (("calib", "标定"), ("canvas", "画布"), ("code", "代码"),
                                           ("platform", "产品性能"), ("switch", "开关/调试"))))
        self.lbl_legend.setStyleSheet("color:%s; font-size:10pt;" % C_GRAY)
        bar.addWidget(self.lbl_legend)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["分类 / 真源 (改数面)"])
        self.tree.setStyleSheet("QTreeWidget{background:%s; color:%s; border:1px solid %s; font-size:10.5pt;}"
                                " QTreeWidget::item:selected{background:%s;}"
                                % (C_BG2, C_WHITE, C_BORDER, C_CARD))
        self.tree.itemClicked.connect(self._on_tree)
        split.addWidget(self.tree)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["用途", "数字", "当前值", "默认", "最小", "最大", "单位", "状态", "真源位置"])
        self.table.setStyleSheet("QTableWidget{background:%s; color:%s; gridline-color:%s; font-size:10pt;}"
                                 " QHeaderView::section{background:%s; color:%s; padding:5px;}"
                                 % (C_BG2, C_WHITE, C_BORDER, C_CARD, C_GRAY))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.doubleClicked.connect(self._edit_current)
        rl.addWidget(self.table, 3)

        self.txt = QTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setStyleSheet("QTextEdit{background:%s; color:%s; border:1px solid %s; font-size:10pt;}"
                               % (C_BG2, C_WHITE, C_BORDER))
        rl.addWidget(self.txt, 2)
        split.addWidget(right)
        split.setSizes([330, 900])
        root.addWidget(split, 1)

        hint = QLabel("双击一行 = 改这个数字 (先预览影响链, 再落真源) · 数字落盘前一律备份 · "
                      "代码常量写坏语法立即回滚 · 所有改动直接记入唯一工程库的 param_events 表")
        hint.setStyleSheet("color:%s; font-size:9.5pt;" % C_DIM)
        root.addWidget(hint)

    # ── 数据 ──────────────────────────────────────────────────────────────
    def reload(self):
        try:
            self.reg = _pr().registry()
            self.err = None
        except Exception as e:                                                    # noqa: BLE001
            self.reg, self.err = None, "%s: %s" % (type(e).__name__, e)
        if self.reg is None:
            self.lbl_info.setText("参数注册表读取失败: %s" % self.err)
            return
        g = self.reg["groups"]
        self.lbl_info.setText("共 %d 个数字 · %s" % (
            len(self.reg["params"]), " ".join("%s%s=%d" % (CAT_ICON.get(k, ""), k, len(v)) for k, v in sorted(g.items()))))
        self.tree.clear()
        allit = QTreeWidgetItem(["🌐 全部数字 (%d)" % len(self.reg["params"])])
        allit.setData(0, Qt.UserRole, None)
        self.tree.addTopLevelItem(allit)
        for cat, items in sorted(g.items()):
            srcs = {}
            for p in items:
                srcs.setdefault(p["source"], []).append(p)
            it = QTreeWidgetItem(["%s %s (%d)" % (CAT_ICON.get(cat, ""), p["cat_cn"], len(items))])
            it.setData(0, Qt.UserRole, cat)
            it.setForeground(0, QColor(items[0]["color"]))
            for src, ps in sorted(srcs.items()):
                sub = QTreeWidgetItem(["📄 %s (%d)" % (src, len(ps))])
                sub.setData(0, Qt.UserRole, "%s|%s" % (cat, src))
                it.addChild(sub)
            self.tree.addTopLevelItem(it)
        self.tree.expandItem(allit)
        self.cur_cat = None
        self._refill()

    def _filtered(self):
        kw = (self.ed_search.text() or "").strip().lower()
        only_w = self.cb_writable.isChecked()
        only_g = self.cb_gap.isChecked()
        out = []
        for p in self.reg["params"]:
            if self.cur_cat:
                if "|" in self.cur_cat:
                    cat, src = self.cur_cat.split("|", 1)
                    if p["group"] != cat or p["source"] != src:
                        continue
                elif p["group"] != self.cur_cat:
                    continue
            if only_w and not p["writable"]:
                continue
            if only_g and ("缺口" not in p["status"] and "未定义" not in p["status"]):
                continue
            if kw and kw not in ("%s %s %s %s" % (p["param_id"], p["cn"], p["source"], p["unit"])).lower():
                continue
            out.append(p)
        return out

    def _refill(self):
        if not self.reg:
            return
        self.rows = self._filtered()
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.rows))
        for i, p in enumerate(self.rows):
            vals = ["%s%s" % (CAT_ICON.get(p["group"], ""), p["cat_cn"]), p["cn"] or p["name"],
                    _fmt(p["value"]), _fmt(p["default"]), _fmt(p["min"]), _fmt(p["max"]), p["unit"],
                    p["status"], "%s %s" % (p["source"].split("/")[-1], p["ref"].replace("json:", "·"))]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j in (0, 2, 7):
                    it.setForeground(QColor(p["color"] if j != 7 else
                                            (C_RED if ("缺口" in p["status"] or "未定义" in p["status"]) else
                                             (C_GOLD if p["status"] == "已定义" else C_DIM))))
                if not p["writable"]:
                    it.setForeground(QColor(C_DIM))
                if j == 2:
                    f = QFont()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(1, 300)
        self.table.setColumnWidth(8, 340)
        self._show_log()

    def _on_tree(self, item, col):
        v = item.data(0, Qt.UserRole)
        self.cur_cat = v
        self._refill()

    # ── 改数: 预览 → 应用 ─────────────────────────────────────────────────
    def _edit_current(self):
        i = self.table.currentRow()
        if i < 0 or i >= len(self.rows):
            return
        p = self.rows[i]
        if not p["writable"]:
            self.txt.setPlainText("🔒 %s 是只读项 (产品/性能指标真源在 zmax_platform.json, 请在「功能清单」页改)。"
                                  % p["cn"])
            return
        if p["kind"] == "enum" and p.get("choices"):
            val, ok = QInputDialog.getItem(self, "改档位 · %s" % p["cn"],
                                           "档位 (真源: %s):" % p["source"], [str(c) for c in p["choices"]],
                                           max(0, [str(c) for c in p["choices"]].index(str(p["value"]))
                                               if str(p["value"]) in [str(c) for c in p["choices"]] else 0), False)
        elif p["kind"] == "bool":
            val, ok = QInputDialog.getItem(self, "改开关 · %s" % p["cn"], "值 (真源: %s):" % p["source"],
                                           ["true", "false"], 0 if p["value"] else 1, False)
        else:
            rng = "范围 %s ~ %s %s" % (_fmt(p["min"]), _fmt(p["max"]), p["unit"])
            val, ok = QInputDialog.getText(self, "改数字 · %s" % p["cn"],
                                           "%s\n当前 %s · 默认 %s\n%s\n真源: %s"
                                           % (p["cn"], _fmt(p["value"]), _fmt(p["default"]), rng, p["source"]),
                                           text=_fmt(p["value"]))
        if not ok or val is None or val == "":
            return
        prev = _pr().set_param(p["param_id"], val, write=False)          # ① 先校验 (不落盘)
        if not prev.get("ok"):
            QMessageBox.warning(self, "校验未通过", prev.get("err", "?"))
            return
        chain = prev.get("chain") or {}
        lines = ["参数: %s (%s)" % (p["cn"], p["param_id"]),
                 "改动: %s → %s %s" % (_fmt(prev["old"]), _fmt(prev["new"]), p["unit"]),
                 "分类: %s · 真源: %s (%s)" % (p["cat_cn"], p["source"], p["ref"]),
                 "", "── 链动影响 ──"]
        if chain.get("systems"):
            lines.append("· 子系统: %s" % " ".join(chain["systems"]))
        if chain.get("functions"):
            lines.append("· 功能: %s" % " / ".join(chain["functions"][:8]))
        if chain.get("modules"):
            lines.append("· 模块: %s" % " / ".join(chain["modules"][:8]))
        if chain.get("code"):
            for cc in chain["code"]:
                lines.append("· 代码: %s:%s  %s" % (cc.get("file"), cc.get("line"), cc.get("symbol")))
        if chain.get("kpis"):
            lines.append("· 性能(KPI): %s" % " | ".join(chain["kpis"][:4]))
        if p.get("impact"):
            lines.append("· 说明: %s" % p["impact"])
        lines += ["", "点「应用」= 备份真源 → 写入 → 回读核对 (写坏立即回滚)"]
        dlg = QDialog(self)
        dlg.setWindowTitle("应用改动 · %s" % p["cn"])
        dl = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setPlainText("\n".join(lines))
        te.setReadOnly(True)
        te.setMinimumSize(760, 420)
        te.setStyleSheet("QTextEdit{background:%s; color:%s; font-size:10.5pt;}" % (C_BG2, C_WHITE))
        dl.addWidget(te)
        bb = QDialogButtonBox()
        b_ok = bb.addButton("✅ 应用 (写回真源)", QDialogButtonBox.AcceptRole)
        b_no = bb.addButton("取消", QDialogButtonBox.RejectRole)
        b_ok.setStyleSheet("QPushButton{background:%s; color:%s; padding:6px 12px; border-radius:4px;}"
                           % (C_CARD, C_GREEN))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)
        if dlg.exec_() != QDialog.Accepted:
            self.txt.setPlainText("已取消 (未落盘)。\n\n" + "\n".join(lines))
            return
        res = _pr().set_param(p["param_id"], val, write=True)             # ② 落真源
        self.txt.setPlainText("════ 改数结果 ════\n" + json.dumps(
            {k: res.get(k) for k in ("ok", "param", "cn", "old", "new", "unit", "msg", "written")},
            ensure_ascii=False, indent=1) + "\n\n── 链动影响 ──\n" + "\n".join(lines[6:]))
        self.reload()
        self._log_to_main("🎛 改数 %s: %s → %s %s (%s)" % (p["cn"], _fmt(prev["old"]), _fmt(prev["new"]),
                                                          p["unit"], "已写回真源" if res.get("ok") else "失败"))

    def _show_log(self):
        # 改数事件 = 唯一工程库 param_events 表 (2026-10-09 起不再有 param_events.jsonl)
        try:
            import importlib.util as iu
            sp = iu.spec_from_file_location("_edb_ev", os.path.join(ROOT, "tools", "engineering_db.py"))
            m = iu.module_from_spec(sp)
            sp.loader.exec_module(m)
            evs = m.read_param_events()
        except Exception as e:                                                  # noqa: BLE001
            evs = []
            self._log_to_main("读取改数事件失败: %r" % (e,))
        n = len(evs)
        head = ("── 改数事件 (可观察: 每一步都留痕在唯一工程库 data/database/zmax/zmax_engineering.db 的 "
                "param_events 表, 共 %d 条) ──\n" % n)
        tail = ["%s  %s  %s → %s  %s" % (e.get("ts"), e.get("cn"), e.get("old"), e.get("new"),
                                         e.get("msg") or "") for e in evs[-12:]]
        self.txt.setPlainText(head + "\n".join(tail) if tail else head + "(还没有改数记录)")

    # ── 顶部动作 ──────────────────────────────────────────────────────────
    def rebuild_db(self):
        try:
            import importlib.util as iu
            sp = iu.spec_from_file_location("_edb", os.path.join(ROOT, "tools", "engineering_db.py"))
            m = iu.module_from_spec(sp)
            sp.loader.exec_module(m)                                              # type: ignore[union-attr]
            cnt = m.build(quiet=True)
            self._log_to_main("🔁 工程库已重建: 参数 %d / 功能 %d / 模块 %d"
                              % (cnt.get("params", 0), cnt.get("functions", 0), cnt.get("modules", 0)))
        except Exception as e:                                                    # noqa: BLE001
            QMessageBox.warning(self, "重建失败", "%s: %s" % (type(e).__name__, e))

    def copy_rows(self):
        txt = "\n".join("\t".join([p["cat_cn"], p["cn"], _fmt(p["value"]), _fmt(p["default"]), _fmt(p["min"]),
                                   _fmt(p["max"]), p["unit"], p["status"], p["source"], p["ref"]])
                        for p in self.rows)
        QApplication.clipboard().setText("用途\t数字\t当前\t默认\t最小\t最大\t单位\t状态\t真源\t位置\n" + txt)
        self._log_to_main("📋 已复制 %d 个数字的清单到剪贴板" % len(self.rows))

    def export_rows(self):
        p = os.path.join(ROOT, "reports", "params_export.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"count": len(self.rows), "params": self.rows}, f, ensure_ascii=False, indent=1)
        self._log_to_main("💾 已导出 %d 个数字 → %s" % (len(self.rows), p))

    def _log_to_main(self, msg):
        try:
            w = self.window()
            if hasattr(w, "_log"):
                w._log(msg)
        except Exception:                                                         # noqa: BLE001
            pass
        print("[param_center] %s" % msg)


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return ("%.6g" % v)
    return str(v)


def selftest():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    pg = ParamCenterPage()
    out = {"err": pg.err, "rows": len(pg.rows), "table_rows": pg.table.rowCount(),
           "tree_top": pg.tree.topLevelItemCount(),
           "cats": {k: len(v) for k, v in (pg.reg["groups"] if pg.reg else {}).items()}}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    selftest()
