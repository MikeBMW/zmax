#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_spec.py — 📋 平台/子系统「功能清单」页 (2026-10-09 老倪)

老倪:
  「在主窗口左侧, System 2 之上增加 Z-MAX 方框, 描述平台产品…点击 Z-MAX / System 2 / System 1 /
    System 0 方块时能清晰打开功能清单…所有清单通过工程数据库管理…只用一个数据库文件承载所有工程数据,
    这样控制台的 GUI 就与整个工程解耦, 我可以随时迁移数据库工程文件, 用统一的 GUI 加载我的工程数据。」

设计要点 (GUI ↔ 工程数据解耦):
  · 本页**不认识任何工程文件**, 只认一个数据库文件 (默认 data/database/zmax/zmax_engineering.db)。
  · 数据全部走 tools/engineering_db.py 的 load() (纯 sqlite 读取, 不 import GUI 依赖) ⇒ 换库 = 换工程。
  · 顶部: 库路径 + 📂 打开工程数据库(文件框) + 🔁 重建(真源→库) + 📋 复制/导出(老倪: 内容要可复制可导出)。
  · 四个页签: 🏭 Z-MAX 平台 / 🧠 System 2 / 🚀 System 1 / 🔧 System 0
      Z-MAX: 平台定位 + 产品(Z700/Z100)KPI + 产品特征清单 (特征·KPI·状态·归属子系统·用到模块·能力引用)
      子系统: 角色/KPI + 三轴清单 (配置·标定·诊断) + 功能清单 (功能·行·对应模块·模块代码位置)
"""
import json
import os
import sqlite3
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
                             QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
                             QVBoxLayout, QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))
DB_DEFAULT = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")

C_BG, C_BG2, C_CARD = "#0f1318", "#131823", "#1a2230"
C_WHITE, C_GRAY, C_DIM, C_BORDER = "#e6edf3", "#9aa7b4", "#6e7b8a", "#2a3441"
C_BLUE, C_GREEN, C_GOLD, C_RED = "#4da3ff", "#00d4aa", "#ffc857", "#ff6b6b"


def _dbmod():
    import engineering_db as ed
    return ed


class PlatformSpecPage(QWidget):
    """📋 平台/子系统功能清单 (全部数据来自单一工程数据库文件)"""

    def __init__(self, db_path=None, parent=None, nav_cb=None):
        super().__init__(parent)
        self.db_path = db_path or DB_DEFAULT
        self.data = None
        self.nav_cb = nav_cb          # 打开「该子系统对应的旧功能页」(数据集/训练/硬件 …) 的回调
        self._build()
        self.reload()

    def select_system(self, sid):
        """按 system_id 选中页签 (老倪: 点 Z-MAX / System 2/1/0 方块 → 直接打开对应功能清单)"""
        want = {"zmax": "Z-MAX", "sys2": "System 2", "sys1": "System 1", "sys0": "System 0",
                "plat": "平台支撑"}.get(sid, sid)
        for i in range(self.tabs.count()):
            if want in self.tabs.tabText(i):
                self.tabs.setCurrentIndex(i)
                return True
        return False

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        t = QLabel("📋 产品配置 · 功能清单 (功能 = 系统里最小可执行能力单元)")
        t.setStyleSheet("color:%s; font-size:15pt; font-weight:700;" % C_WHITE)
        head.addWidget(t)
        head.addStretch()
        self.lbl_db = QLabel("")
        self.lbl_db.setStyleSheet("color:%s; font-size:10pt;" % C_DIM)
        head.addWidget(self.lbl_db)
        for txt, tip, fn in (("📂 打开工程数据库…", "选一个 .db 工程库 = 换一套工程数据 (GUI 不绑死工程)", self.open_db_dialog),
                             ("🔁 从真源重建", "真源 (平台JSON/.proj/标定/feature.dbc/FEATURES) → 重建单一数据库文件", self.rebuild_db),
                             ("📋 复制本页", "把当前页签的清单复制到剪贴板 (可粘贴到文档/邮件)", self.copy_page),
                             ("💾 导出 JSON", "导出当前页签数据为 JSON 文件 (外部消费者可直接用)", self.export_page),
                             ("📡 服务状态", "查看/打开只读 JSON 服务 (127.0.0.1:8798)", self.show_service)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.setStyleSheet("QPushButton{background:%s; color:%s; border:1px solid %s; border-radius:4px;"
                            " padding:6px 10px; font-size:10pt;} QPushButton:hover{border-color:%s;}"
                            % (C_CARD, C_WHITE, C_BORDER, C_BLUE))
            b.clicked.connect(fn)
            head.addWidget(b)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab{background:%s; color:%s; padding:7px 14px; font-size:11pt;}"
                               " QTabBar::tab:selected{color:%s; border-bottom:2px solid %s;}"
                               % (C_BG2, C_GRAY, C_WHITE, C_BLUE))
        root.addWidget(self.tabs, 1)

    def _mk_tab(self, title):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        self.tabs.addTab(w, title)
        return w, lay

    @staticmethod
    def _table(cols, rows, widths=None):
        tb = QTableWidget(len(rows), len(cols))
        tb.setHorizontalHeaderLabels(cols)
        tb.verticalHeader().setVisible(False)
        tb.setStyleSheet("QTableWidget{background:%s; color:%s; gridline-color:%s; font-size:10pt;}"
                         " QHeaderView::section{background:%s; color:%s; padding:5px; font-size:10pt;}"
                         % (C_BG2, C_WHITE, C_BORDER, C_CARD, C_GRAY))
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                tb.setItem(i, j, QTableWidgetItem("" if v is None else str(v)))
        tb.resizeColumnsToContents()
        if widths:
            for j, wd in enumerate(widths):
                tb.setColumnWidth(j, wd)
        tb.setEditTriggers(QTableWidget.NoEditTriggers)
        tb.setSelectionBehavior(QTableWidget.SelectRows)
        return tb

    @staticmethod
    def _kb(lay, text):
        lb = QLabel(text)
        lb.setWordWrap(True)
        lb.setStyleSheet("color:%s; font-size:10.5pt; background:%s; border:1px solid %s;"
                         " border-radius:5px; padding:8px;" % (C_GRAY, C_BG2, C_BORDER))
        lay.addWidget(lb)
        return lb

    # ── 数据 ──────────────────────────────────────────────────────────────
    def reload(self):
        try:
            self.data = _dbmod().load(self.db_path)
            self.err = None
        except Exception as e:                                                    # noqa: BLE001
            self.data, self.err = None, "%s: %s" % (type(e).__name__, e)
        while self.tabs.count():
            self.tabs.removeTab(0)
        if self.data is None:
            w, lay = self._mk_tab("⚠️ 未加载")
            self._kb(lay, "数据库读取失败或不存在:\n%s\n\n库: %s\n\n点右上「🔁 从真源重建」生成, 或「📂 打开工程数据库…」"
                          "选一个已迁移过来的 .db 工程文件。" % (self.err, self.db_path))
            self.lbl_db.setText("库: %s (缺失)" % os.path.basename(self.db_path))
            return
        d = self.data
        sz = os.path.getsize(self.db_path) / 1048576
        self.lbl_db.setText("库: %s (%.2f MB · %s)" % (os.path.basename(self.db_path), sz,
                                                     d["meta"].get("built_at", "")))
        self._tab_platform(d)
        for sid, tab in (("sys2", "🧠 System 2"), ("sys1", "🚀 System 1"), ("sys0", "🔧 System 0"),
                         ("plat", "🧩 平台支撑")):
            if any(s["system_id"] == sid for s in d["subsystems"]):
                self._tab_system(d, sid, tab)

    def _tab_platform(self, d):
        p = d["platform"]
        w, lay = self._mk_tab("🏭 Z-MAX 平台")
        self._kb(lay, "<b>%s</b><br>%s<br><br><b>架构</b>: %s<br><br><b>数据契约</b>: %s"
                 % (p.get("name"), p.get("positioning"), p.get("architecture"), p.get("data_contract")))
        products = {x["product_id"]: x for x in d["products"]}
        rows = [[x.get("name"), x.get("category"), x.get("positioning", "")[:70],
                 ", ".join("%s=%s" % (k, v) for k, v in list(json.loads(x["kpi"] or "{}").items())[:3])]
                for x in d["products"]]
        lay.addWidget(QLabel("🏷 平台产品 (产品通过 系统2/1/0 组成的全系统实现)"))
        lay.addWidget(self._table(["产品", "类别", "定位", "关键指标"], rows), 1)
        feats = [[f["pf_id"], f["product_id"], f["title"], f["kpi"], f["status"],
                  ",".join(json.loads(f["subsys"] or "[]")), f["capability_ref"],
                  "、".join(json.loads(f["module_refs"] or "[]")[:3])] for f in d["product_features"]]
        lay.addWidget(QLabel("🎯 产品特征清单 (共 %d 条 · 特征 → 子系统 → 模块 → 能力)" % len(feats)))
        lay.addWidget(self._table(["特征ID", "产品", "产品特征", "指标 KPI", "状态", "归属子系统", "能力(BO_)", "用到模块"],
                                  feats), 2)
        # 特征→子系统 链接汇总
        lk = [l for l in d["links"] if l["src_type"] == "product_feature" and l["kind"] == "归属"]
        bys = {}
        for l in lk:
            bys.setdefault(l["dst_id"], []).append(l["src_id"])
        lay.addWidget(QLabel("🔗 特征 → 子系统: " + " · ".join("%s(%d)" % (k, len(v)) for k, v in bys.items())))

    def _tab_system(self, d, sid, title):
        s = next(x for x in d["subsystems"] if x["system_id"] == sid)
        w, lay = self._mk_tab(title)
        kpi = json.loads(s["kpi"] or "{}")
        self._kb(lay, "<b>%s</b> (%s)<br>%s<br><br><b>硬件</b>: %s<br><b>KPI</b>: %s"
                 % (s["name"], s["level"], s["role"], s["hardware"],
                    " · ".join("%s=%s" % (k, v) for k, v in kpi.items())))
        ax = d["axes"].get(sid, {})
        axis_rows = []
        for a, cn in (("cfg", "配置 CFG"), ("cal", "标定 CAL"), ("dia", "诊断 DIA")):
            for i, it in enumerate(ax.get(a, [])):
                axis_rows.append([cn, i + 1, it])
        lay.addWidget(QLabel("⚙️ 本子系统功能定义三轴 (配置 · 标定 · 诊断) — 共 %d 项" % len(axis_rows)))
        lay.addWidget(self._table(["轴", "#", "项"], axis_rows, [90, 40, 900]), 1)
        fns = [x for x in d["functions"] if x["system_id"] == sid]
        rows = []
        code = {c["module_name"]: "%s:%d" % (os.path.basename(c["file"]), c["line"]) for c in d["module_code"]}
        for x in fns:
            rows.append([x["fn_id"], x["name"], x["layer"], (x["row_name"] or "")[:28],
                         x["module_ref"], code.get(x["module_ref"], "—")])
        lay.addWidget(QLabel("🧩 功能清单 (共 %d 条功能 · 每条的 配置/标定/诊断 明细见 fn_axes 表, 服务 /function/<id>)"
                            % len(rows)))
        lay.addWidget(self._table(["功能ID", "功能 (模块)", "层", "画布行", "对应模块库模块", "模块代码位置"],
                                  rows), 2)
        if self.nav_cb:
            target = {"sys2": "dataset", "sys1": "training", "sys0": "hardware", "plat": None}.get(sid)
            if target:
                bar = QHBoxLayout()
                b2 = QPushButton("→ 打开该子系统对应的功能页面 (%s)" % target)
                b2.setStyleSheet("QPushButton{background:%s; color:%s; border:1px solid %s; border-radius:4px;"
                                 " padding:5px 9px; font-size:10pt;} QPushButton:hover{border-color:%s;}"
                                 % (C_CARD, C_BLUE, C_BORDER, C_BLUE))
                b2.clicked.connect(lambda _=False, t=target: self.nav_cb(t))
                bar.addWidget(b2)
                bar.addStretch()
                lay.addLayout(bar)

    # ── 动作 ──────────────────────────────────────────────────────────────
    def open_db_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "📂 打开工程数据库 (换库 = 换工程, GUI 不绑死工程)",
                                           os.path.dirname(self.db_path), "工程库 (*.db *.sqlite *.sqlite3)")
        if p:
            self.db_path = p
            self.reload()
            self._log("📂 已加载工程数据库: %s" % p)

    def rebuild_db(self):
        try:
            cnt = _dbmod().build(self.db_path, quiet=True)
            self.reload()
            self._log("🔁 工程数据库已从真源重建: %s (功能 %d / 特征 %d / 模块 %d)"
                      % (os.path.basename(self.db_path), cnt.get("functions", 0),
                         cnt.get("product_features", 0), cnt.get("modules", 0)))
        except Exception as e:                                                    # noqa: BLE001
            QMessageBox.warning(self, "重建失败", "%s: %s" % (type(e).__name__, e))

    def current_payload(self):
        if not self.data:
            return {"ok": False, "err": self.err}
        idx = self.tabs.currentIndex()
        title = self.tabs.tabText(idx) if idx >= 0 else "?"
        d = self.data
        if "Z-MAX" in title:
            return {"tab": title, "platform": d["platform"], "products": d["products"],
                    "product_features": d["product_features"]}
        _kw = {"sys2": "System 2", "sys1": "System 1", "sys0": "System 0", "plat": "平台支撑"}
        for sid, kw in _kw.items():
            s_ = next((x for x in d["subsystems"] if x["system_id"] == sid), None)
            if s_ and kw in title:
                return {"tab": title, "system": s_, "axes": d["axes"].get(sid, {}),
                        "functions": [x for x in d["functions"] if x["system_id"] == sid]}
        return {"tab": title, "platform": d["platform"]}

    def copy_page(self):
        try:
            QApplication.clipboard().setText(json.dumps(self.current_payload(), ensure_ascii=False, indent=1))
            self._log("📋 当前页签清单已复制到剪贴板")
        except Exception as e:                                                    # noqa: BLE001
            self._log("❌ 复制失败: %s" % e)

    def export_page(self):
        p, _ = QFileDialog.getSaveFileName(self, "💾 导出当前页签", os.path.join(ROOT, "reports",
                                             "spec_%s.json" % (self.tabs.tabText(self.tabs.currentIndex()) or "tab")),
                                           "JSON (*.json)")
        if not p:
            return
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.current_payload(), f, ensure_ascii=False, indent=1)
        self._log("💾 已导出: %s" % p)

    def show_service(self):
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8798/summary", timeout=3) as r:
                d = json.loads(r.read().decode("utf-8"))
            QMessageBox.information(self, "📡 工程数据库服务",
                                    "只读服务在线: http://127.0.0.1:8798/\n\n%s"
                                    % json.dumps(d.get("data", {}), ensure_ascii=False, indent=1)[:1200])
        except Exception as e:                                                    # noqa: BLE001
            QMessageBox.information(self, "📡 工程数据库服务",
                                    "服务未启动 (或已迁移到别处)。\n\n启动:\n"
                                    "python3 tools/engineering_db.py serve --port 8798\n\n(%s)" % e)

    def _log(self, msg):
        try:
            win = self.window()
            if hasattr(win, "_log"):
                win._log(msg)
        except Exception:                                                         # noqa: BLE001
            pass
        print("[platform_spec] %s" % msg)


def selftest():
    """判据用: 离屏建页 + 明细统计 (不依赖主窗口)"""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    pg = PlatformSpecPage()
    out = {"tabs": [pg.tabs.tabText(i) for i in range(pg.tabs.count())],
           "db": pg.db_path, "err": pg.err}
    if pg.data:
        d = pg.data
        out.update({"products": len(d["products"]), "features": len(d["product_features"]),
                    "functions": len(d["functions"]), "axes": {k: len(v) for k, v in d["axes"].items()},
                    "modules": len(d["modules"]), "module_code": len(d["module_code"]),
                    "capabilities": len(d["capabilities"]), "calib": len(d["calib"]),
                    "sections": sorted(d["project"].keys()),
                    "fn_by_sys": {s["system_id"]: len([x for x in d["functions"] if x["system_id"] == s["system_id"]])
                                  for s in d["subsystems"]}})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    selftest()
