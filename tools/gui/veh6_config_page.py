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
import time
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QColor, QFont  # noqa: E402
from PyQt5.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                             QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
                             QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

TASKS_J = os.path.join(ROOT, "config", "tasks", "tasks.json")
MCD_J = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
MATCH_J = os.path.join(ROOT, "config", "mcd", "match_matrix.json")
ORDERS_D = os.path.join(ROOT, "config", "orders")
BIND_J = os.path.join(ROOT, "config", "ss_task_binding.json")

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


# ── 三份交付文档 (2026-10-10): 与 config_center.py 同一份真源, 点了必出结果 ──
DOC_SCRIPTS = {
    "bundle":    ("三件套导出 (立项文档 + SOR + 协议)", "docs_bundle.py", []),
    "project":   ("项目立项文档 (Word)", "project_doc_export.py", []),
    "sor":       ("供应商 SOR 需求规格说明书 (Word)", "sor_export.py", []),
    "agreement": ("机器人数据平台合作与模型授权协议 (Word)", "agreement_export.py", []),
    "bom":       ("BOM / 成本 / ROI 算账 (不出文档)", "project_doc_export.py", ["--check"]),
}
DOC_DIRS = ["outputs/docs_bundle", "outputs/project_docs", "outputs/sor", "outputs/agreements"]


# ── 文档配置 (2026-10-10 老倪: 左侧栏增加文档配置, 内置窗口直接看生成的文档, 数据统一保证一致性) ──
DOCS = {
    "sor":       {"name": "供应商外发 SOR", "script": "sor_export.py", "rel": "outputs/sor"},
    "project":   {"name": "项目立项文档", "script": "project_doc_export.py", "rel": "outputs/project_docs"},
    "agreement": {"name": "合作协议", "script": "agreement_export.py", "rel": "outputs/agreements"},
}
# 文档 manifest 里记录过的真源 (键名来自各导出器); 有的用 source_db, 有的用 engineering_db
SRC_DEFS = [
    ("source_db",      "工程库 (单一真源)",       ["data/database/zmax/zmax_engineering.db"]),
    ("engineering_db", "工程库 (单一真源)",       ["data/database/zmax/zmax_engineering.db"]),
    ("bom",            "BOM/成本/ROI 真源",       ["config/platform/zmax_project_bom.json"]),
    ("feature_dbc",    "功能能力清单 feature.dbc", ["data/database/zmax/sources/feature.dbc", "feature.dbc"]),
    ("governance",     "数据治理真源",             ["config/platform/zmax_data_governance.json"]),
]
PLATFORM_SRC = ("平台配置真源", "config/platform/zmax_platform.json")   # manifest 未记录 ⇒ 用时间戳兜底


def _sha256(p):
    import hashlib
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def _find_src(paths):
    for p in paths:
        fp = os.path.join(ROOT, p)
        if os.path.exists(fp):
            return p, fp
    return None, None


def _manifest_shas(mp):
    """拍平 manifest 里所有 *_sha256 (三种文档 manifest 结构不同, 递归找最稳; 60 位以上才算 sha)。"""
    j = _j(mp, {}) or {}
    out = {}
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k.endswith("sha256") and len(v) == 64:
                    out[k[:-7]] = v
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(j)
    return out


def _latest_doc(kind):
    d = _newest_out_dir(DOCS[kind]["rel"])
    if not d:
        return None
    dx = glob.glob(os.path.join(d, "*.docx"))
    if not dx:
        return None
    dx = max(dx, key=os.path.getmtime)
    mp = os.path.join(d, "manifest.json")
    return {"dir": d, "docx": dx, "manifest": mp if os.path.exists(mp) else None, "mtime": os.path.getmtime(dx)}


def _doc_state(kind):
    """文档 × 真源一致性: 逐条比对 manifest 记录的 sha 与当前真源实际 sha (对不上=过期, 不能当交付件)。"""
    st = _latest_doc(kind)
    info = {"kind": kind, "name": DOCS[kind]["name"], "doc": st, "rows": []}
    if not st:
        info.update({"stale": True, "why": "还没生成过"})
        return info
    rec = _manifest_shas(st["manifest"]) if st["manifest"] else {}
    bad = []
    for key, label, cands in SRC_DEFS:
        if key not in rec:
            continue
        rel, fp = _find_src(cands)
        if not fp:
            info["rows"].append((label, rec[key][:12], "路径未找到", "⚠️"))
            bad.append(label + "(路径缺失)")
            continue
        cur = _sha256(fp)
        ok = (cur == rec[key])
        info["rows"].append((label, rec[key][:12], cur[:12], "✅" if ok else "⛔"))
        if not ok:
            bad.append(label)
    rel, fp = _find_src([PLATFORM_SRC[1]])
    if fp and os.path.getmtime(fp) > st["mtime"] + 1:
        info["rows"].append((PLATFORM_SRC[0] + " (时间戳)", "—",
                             time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp))), "⚠️"))
        bad.append(PLATFORM_SRC[0])
    info["stale"] = bool(bad)
    info["why"] = ("真源已变: " + ", ".join(bad)) if bad else "与当前真源一致"
    return info


def _doc_mark(kind):
    st = _doc_state(kind)
    return "✅" if (st["doc"] and not st["stale"]) else "⛔"


def _render_docx(path, limit=300000):
    """把生成的 .docx 按正文顺序读回文本 (段落 + 表格), 让内置窗口看到**实际交付内容**。"""
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as e:  # noqa: BLE001
        return f"⛔ 读不了 docx (python-docx 缺失?): {e}"
    try:
        d = Document(path)
    except Exception as e:  # noqa: BLE001
        return f"⛔ 打不开 {path}: {e}"
    out = []
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            t = Paragraph(child, d).text.strip()
            if t:
                out.append(t)
        elif tag == "tbl":
            tb = Table(child, d)
            for r in tb.rows:
                out.append("  | " + " | ".join(c.text.strip().replace("\n", " ") for c in r.cells) + " |")
            out.append("")
    txt = "\n".join(out)
    return txt[:limit] + ("\n\n… (面板截断, 完整内容见 docx)" if len(txt) > limit else "")


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def _render_doc_html(path):
    """把 .docx 渲染成**可读的 HTML**: 表格是真表格 (深底白字表头 + 隔行底色 + 列宽按 docx 实际比例)。

    老倪 2026-10-10: 「表格显示的非常不友好, 用眼睛看非常费劲」⇒ 预览不再用 `| a | b |` 竖线文本。
    Qt 富文本不支持 border-collapse, 用 table 的 border/cellpadding 属性 + 单元格内联色实现。
    """
    C_HEAD, C_ROW1, C_ROW2, C_TXT, C_HEAD_TXT, C_LINE = "#1F3864", "#1b222c", "#161b24", "#e8edf4", "#ffffff", "#2a3340"
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as e:  # noqa: BLE001
        return "<p>⛔ 读不了 docx (python-docx 缺失?): %s</p>" % _esc(e)
    try:
        d = Document(path)
    except Exception as e:  # noqa: BLE001
        return "<p>⛔ 打不开 %s: %s</p>" % (_esc(path), _esc(e))

    out = []
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                continue
            sty = p.style.name or ""
            if sty.startswith("Heading 1") or sty.startswith("Title"):
                out.append('<p style="font-size:14pt;font-weight:700;color:#9fc3f0;margin:16px 0 6px 0;">%s</p>' % _esc(txt))
            elif sty.startswith("Heading 2"):
                out.append('<p style="font-size:12pt;font-weight:700;color:#cfe0f5;margin:12px 0 4px 0;">%s</p>' % _esc(txt))
            elif sty.startswith("Heading"):
                out.append('<p style="font-size:11pt;font-weight:700;color:#cfe0f5;margin:10px 0 3px 0;">%s</p>' % _esc(txt))
            else:
                out.append('<p style="font-size:10pt;color:%s;margin:3px 0;">%s</p>' % (C_TXT, _esc(txt)))
        elif tag == "tbl":
            t = Table(child, d)
            ncol = len(t.rows[0].cells) if len(t.rows) else 0
            pcts = [""] * ncol
            try:
                ws = [c.width.cm if c.width else None for c in t.rows[0].cells]
                tot = sum(w for w in ws if w)
                if tot:
                    pcts = [' width="%d%%"' % max(6, int(100.0 * w / tot)) if w else "" for w in ws]
            except Exception:  # noqa: BLE001
                pass
            h = ['<table border="1" cellspacing="0" cellpadding="6" style="border-color:%s;margin:8px 0;">' % C_LINE]
            for ri, row in enumerate(t.rows):
                bg = C_HEAD if ri == 0 else (C_ROW1 if ri % 2 == 1 else C_ROW2)
                fg = C_HEAD_TXT if ri == 0 else C_TXT
                h.append("<tr>")
                for ci, c in enumerate(row.cells):
                    w = pcts[ci] if (ri == 0 and ci < len(pcts)) else ""
                    txt = _esc(c.text.strip())
                    if ri == 0 or ci == 0:
                        txt = "<b>%s</b>" % txt
                    h.append('<td%s style="color:%s;background-color:%s;">%s</td>' % (w, fg, bg, txt))
                h.append("</tr>")
            h.append("</table>")
            out.append("".join(h))
    return "".join(out) or "<p>（文档正文为空）</p>"


def _run_script(script, args=None, timeout=900):
    """真跑 tools/ 下的脚本, stdout+stderr 全抓回面板 (点了必出结果, 失败不静默)。"""
    import subprocess
    cmd = [sys.executable, os.path.join(TOOLS, script)] + list(args or [])
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"⛔ 超时 (>{timeout}s): {script} —— 没有结果就不要当成功"
    except Exception as e:  # noqa: BLE001
        return f"⛔ 执行异常: {type(e).__name__}: {e}"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if err:
        out += "\n--- stderr ---\n" + err
    if r.returncode != 0:
        out += f"\n⛔ 退出码 {r.returncode} —— 上面就是原因, 不要把这次当成功"
    return out or f"⚠️ 脚本无输出 (退出码 {r.returncode})"


def _newest_out_dir(rel):
    """最新产物目录 (按 mtime, 不能用字母序 —— 时间戳目录名字母序会排错)。"""
    ds = [d for d in glob.glob(os.path.join(ROOT, rel, "*")) if os.path.isdir(d)]
    return max(ds, key=os.path.getmtime) if ds else None


def _doc_inventory():
    """产物清单: 绝对路径 + 大小 + 时间 (老倪要可复制的绝对路径)。"""
    lines = []
    for rel in DOC_DIRS:
        d = _newest_out_dir(rel)
        if not d:
            continue
        import datetime
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(d)).strftime("%m-%d %H:%M")
        lines.append(f"[{mt}] {rel}/  →  {os.path.basename(d)}")
        for f in sorted(os.listdir(d)):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                kb = os.path.getsize(fp) / 1024.0
                lines.append(f"    {kb:8.1f} KB  {fp}")
    return "\n".join(lines) if lines else "⚠️ 还没有产物 —— 点上面任一按钮, 跑完这里就会出现绝对路径"


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

        # ── 顶栏: 返回 + 站点 / 描述 / 授权 ──
        bar = QHBoxLayout()
        d = _j(MCD_J, {}) or {}
        meta = d.get("_meta", {})
        tk = _j(TASKS_J, {}) or {}
        self.back_btn = _btn("← 返回主窗口", th)
        self.back_btn.setToolTip("回到控制台主窗口 (等价于左侧栏「← 返回首页」)")
        self.back_btn.clicked.connect(self._back_home)
        bar.addWidget(self.back_btn)
        info = QLabel(f"站点 SITE-A.ST11 · {meta.get('schema', '缺')} @ {meta.get('generated_at', '—')}"
                      f" · 任务 {len(tk.get('tasks', []))} 条")
        info.setFont(QFont("Consolas", 10))
        # 2026-10-10: QLabel 默认按全文撑宽, 顶栏按钮会被挤出窗口右缘 (真机截图实测被截) ⇒ 允许压缩
        info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info.setMinimumWidth(0)
        info.setToolTip(info.text())
        info.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        bar.addWidget(info)
        bar.addStretch()
        b_doc = _btn("📄 文档导出", th)
        b_doc.setToolTip("三份交付文档同源导出 (项目立项文档 / 供应商 SOR / 合作协议) —— 切到「文档交付」页")
        b_doc.clicked.connect(self._goto_docs)
        bar.addWidget(b_doc)
        for txt, fn in (("🔍 全链校验", "check"), ("📋 任务配置", "tasks"), ("⚙️ 工程配置", "list")):
            b = _btn(txt, th)
            b.clicked.connect(lambda _, f=fn: self._run_into(f))
            bar.addWidget(b)
        bar.addSpacing(10)          # 2026-10-10: 右侧留边, 最后一个按钮不贴窗缘 (窄窗实测会顶到边)
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
        # 文档配置 (2026-10-10): 三份外发/立项文档 + 一致性核对
        dm = [_doc_mark(k) for k in ("sor", "project", "agreement")]
        doms.append((f"文档配置  文档 {sum(1 for m in dm if m == '✅')}/3", "⛔" if "⛔" in dm else "✅",
                     ["供应商外发 SOR", "项目立项文档", "合作协议", "一致性核对"]))
        doms.append((f"工艺·工单  任务 {len(tk.get('tasks', []))}",
                     "⛔" if (tk.get("tasks") and any(t.get("blocked_by_site") for t in tk["tasks"])) else "✅",
                     [t["task_id"] for t in tk.get("tasks", [])]))
        self.tree.clear()
        for label, mark, kids in doms:
            it = QTreeWidgetItem([f"{mark} {label}"])
            for k in kids:
                QTreeWidgetItem(it, [f"   {k}"])
            self.tree.addTopLevelItem(it)
            it.setExpanded(label.startswith("工艺") or label.startswith("文档"))

    def _on_tree(self, item, _col):
        txt = item.text(0)
        if "文档" in txt or "SOR" in txt or "立项" in txt or "协议" in txt or "一致性" in txt:
            if "一致性" in txt or "文档配置" in txt:
                self._show_consistency()
            elif "SOR" in txt:
                self._show_doc("sor")
            elif "立项" in txt:
                self._show_doc("project")
            else:
                self._show_doc("agreement")
            return
        if "任务配置" in txt or "工艺" in txt:
            self.tabs.setCurrentIndex(0)
        self._run_into("tasks" if "TASK" in txt.upper() else "overview")

    # ── 右侧页签 ──
    def _build_tabs(self, d, tk, model_page):
        th = self.th
        bind = _j(BIND_J, {}) or {}
        bmap = {t["task_id"]: t for t in bind.get("tasks", [])}
        act = bind.get("active_task")
        proj = bind.get("project", {})
        # 1) 任务配置 (首屏) —— 含"状态空间工程"配置清单列
        self.tasks_table = _mk_table(
            ["任务ID", "类型", "工艺步骤", "适用段", "粒度", "启用节点", "禁用节点", "档位(开)", "活跃", "状态"],
            [[t["task_id"], t["recipe_type"],
              " → ".join(s["name"] for s in t.get("steps", [])),
              f"{len(t['applies_segments'])}/8",
              len(t.get("variants", [])),
              (len(bmap[t["task_id"]]["enabled_nodes"]) if t["task_id"] in bmap else "—"),
              (len(bmap[t["task_id"]]["disabled_nodes"]) if t["task_id"] in bmap else "—"),
              (sum(1 for v in bmap[t["task_id"]]["run_cfg"].values() if v["checked"])
               if t["task_id"] in bmap else "—"),
              ("★ 活跃" if act == t["task_id"] else ""),
              ("⛔ 缺站点几何" + str(len(t["blocked_by_site"]))) if t.get("blocked_by_site") else "✅"]
             for t in tk.get("tasks", [])], th)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(6, 6, 6, 6)
        head = QLabel(f"状态空间工程(主工程): {proj.get('nodes', '?')} 节点 / {proj.get('links', '?')} 连线"
                      f"  ·  md5 {str(proj.get('canvas_md5', ''))[:12]}  ·  承载 {len(bind.get('tasks', []))} 个任务"
                      f"  ·  活跃 {act or '—'}")
        head.setFont(QFont("Consolas", 10))
        head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l.addWidget(head)
        row = QHBoxLayout()
        for txt, fn, kw in (("🧩 刷新绑定", "bind", {}),
                            ("📋 配置清单(选中)", "bind", {"use_sel": True}),
                            ("✅ 激活选中任务", "activate", {"use_sel": True}),
                            ("📦 导出工程文件", "project", {}),
                            ("📥 写入状态空间节点", "node", {"arg": "write"}),
                            ("🏷 看节点配置", "node", {}),
                            ("🔍 全链校验", "check", {}),
                            ("📄 配方", "recipe", {}),
                            ("📋 导出 JSON", "tasks", {})):
            b = _btn(txt, th)
            b.clicked.connect(lambda _, f=fn, k=kw: self._run_selected(f, **k))
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

        # 7) 文档交付 (2026-10-10 老倪: 三份文档导出做成配置中心按钮)
        w7 = QWidget()
        l7 = QVBoxLayout(w7)
        l7.setContentsMargins(6, 6, 6, 6)
        src = QLabel("三份交付文档同一数据源: 工程库 data/database/zmax/zmax_engineering.db + 平台真源 config/platform/*.json"
                     "   ·   BOM 每项挂功能/能力   ·   成本按阶段自动核算   ·   ROI 由性能指标(节拍/成功率/人效比)算出")
        src.setWordWrap(True)
        src.setFont(QFont("Consolas", 10))
        src.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l7.addWidget(src)
        row7 = QHBoxLayout()
        for key in ("bundle", "project", "sor", "agreement", "bom"):
            label, script, args = DOC_SCRIPTS[key]
            b = _btn(("📦 " if key == "bundle" else ("🧮 " if key == "bom" else "📄 ")) + label.split(" (")[0], th)
            b.setToolTip(f"{label}\n→ tools/{script} {' '.join(args)}\n产物落在 outputs/ 下 (跑完面板给出绝对路径)")
            b.clicked.connect(lambda _, k=key: self._run_doc(k))
            row7.addWidget(b)
        row7.addStretch()
        l7.addLayout(row7)
        row7b = QHBoxLayout()
        b_copy = _btn("📋 复制产物路径", th)
        b_copy.clicked.connect(self._copy_docs)
        b_open = _btn("📂 打开产物目录", th)
        b_open.clicked.connect(self._open_docs)
        b_ref = _btn("🔍 刷新产物列表", th)
        b_ref.clicked.connect(self._copy_docs)
        for b in (b_copy, b_open, b_ref):
            row7b.addWidget(b)
        row7b.addStretch()
        l7.addLayout(row7b)
        self.docs_out = QTextEdit()
        self.docs_out.setReadOnly(True)
        self.docs_out.setFont(QFont("Consolas", 9))
        self.docs_out.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                                    f"border:1px solid {th['C_BORDER']};")
        self.docs_out.setPlainText(_doc_inventory())
        l7.addWidget(self.docs_out, 1)
        self.tabs.addTab(w7, "📄 文档交付")

        # 8) 文档预览 (2026-10-10 老倪: 内置窗口直接看根据配置生成的文档, 数据统一/一致性)
        w8 = QWidget()
        l8 = QVBoxLayout(w8)
        l8.setContentsMargins(6, 6, 6, 6)
        self.pv_head = QLabel("文档预览 — 左侧栏「📄 文档配置」点一份文档即可在这里看到它的**实际内容**")
        self.pv_head.setWordWrap(True)
        self.pv_head.setFont(QFont("Consolas", 10))
        self.pv_head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l8.addWidget(self.pv_head)
        row8 = QHBoxLayout()
        for key, lab in (("sor", "📋 看 SOR"), ("project", "📄 看立项文档"), ("agreement", "🤝 看合作协议")):
            b8 = _btn(lab, th)
            b8.clicked.connect(lambda _, k=key: self._show_doc(k))
            row8.addWidget(b8)
        b_con8 = _btn("🔍 一致性核对", th)
        b_con8.setToolTip("三份文档记录的 工程库/BOM/能力清单/治理 真源 sha 与当前真源逐一比对")
        b_con8.clicked.connect(self._show_consistency)
        row8.addWidget(b_con8)
        b_re8 = _btn("♻️ 重新生成并预览", th)
        b_re8.setToolTip("真源改过之后必须重新生成 —— 过期文档不能当交付件")
        b_re8.clicked.connect(lambda: self._show_doc(getattr(self, "_pv_kind", "sor"), force=True))
        row8.addWidget(b_re8)
        row8.addStretch()
        l8.addLayout(row8)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 9))
        self.preview.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                                   f"border:1px solid {th['C_BORDER']};")
        self.preview.setPlainText(
            "判据: 文档 manifest 里记录的 工程库/BOM/能力清单/治理 真源 sha 与当前真源**逐一比对** ——\n"
            "  对不上 = ⛔ 已过期 (老倪口径: 过期文档不能当交付件), 顶部会红字告警, 点「♻️ 重新生成并预览」。\n"
            "  三份文档同源: 都读 data/database/zmax/zmax_engineering.db + config/platform/*.json, 不手抄数字。")
        l8.addWidget(self.preview, 1)
        self.tabs.addTab(w8, "📄 文档预览")

    # ── 文档配置: 预览 + 一致性 (2026-10-10 老倪) ──
    def _pv_tab_index(self):
        for i in range(self.tabs.count()):
            if "文档预览" in self.tabs.tabText(i):
                return i
        return -1

    def _show_doc(self, kind, force=False):
        """内置窗口看文档: 没有产物就先真跑生成, 再读回 .docx 实际内容; 过期给红字告警。"""
        from PyQt5.QtWidgets import QApplication
        self._pv_kind = kind
        i = self._pv_tab_index()
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        if force or not _latest_doc(kind):
            self.out.setPlainText(f"▶ 生成 {DOCS[kind]['name']} … (数据源: 工程库 + 平台真源)")
            QApplication.processEvents()
            self.out.setPlainText(_run_script(DOCS[kind]["script"]))
            QApplication.processEvents()
        st = _doc_state(kind)
        if not st["doc"]:
            self.pv_head.setText(f"⛔ {st['name']}: 取不到产物 ({st['why']})")
            self.preview.setPlainText("生成失败 —— 看底部结果面板的日志 (退出码非 0 时那里有真原因)。")
            return
        mark = "⛔ 已过期" if st["stale"] else "✅ 与当前真源一致"
        self.pv_head.setText(
            f"{st['name']} · {os.path.basename(st['doc']['docx'])}"
            f" · 生成 {time.strftime('%m-%d %H:%M', time.localtime(st['doc']['mtime']))} · {mark} · {st['why']}\n"
            + "   ".join(f"{v} {l}: {r}→{c}" for l, r, c, v in st["rows"])
            + f"\ndocx 绝对路径: {st['doc']['docx']}")
        html = _render_doc_html(st["doc"]["docx"])
        if st["stale"]:
            html = ('<p style="color:#ff8a8a;font-size:11pt;font-weight:700;margin:6px 0;">'
                    '⛔ 一致性告警: %s —— 这份文档是用旧真源生成的, 不能当交付件, 点「♻️ 重新生成并预览」</p>'
                    '<hr style="border:1px solid #7a2b2b;">' % _esc(st["why"])) + html
        self.preview.setHtml(html)

    def _show_consistency(self):
        """三份文档 × 当前真源 一致性核对 (数据统一/一致性的判据视图)。"""
        i = self._pv_tab_index()
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        dbp = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
        L = ["═══ 三份交付文档 × 真源 一致性核对 ═══",
             f"真源: 工程库 data/database/zmax/zmax_engineering.db  (当前 sha256 {_sha256(dbp)[:16] or '?'})", ""]
        for kind in ("project", "sor", "agreement"):
            st = _doc_state(kind)
            ok = st["doc"] and not st["stale"]
            L.append(f"[{'✅' if ok else '⛔'}] {st['name']}: " + (st["why"] if st["doc"] else "还没生成 (点下面按钮或左侧栏点它)"))
            if st["doc"]:
                L.append(f"      docx: {st['doc']['docx']}")
                for l, r, c, v in st["rows"]:
                    L.append(f"      {v} {l}: 文档记录 {r} · 当前 {c}")
            L.append("")
        L.append("── 当前真源文件 (时间 · sha256 前12 · 路径) ──")
        for key, label, cands in SRC_DEFS:
            rel, fp = _find_src(cands)
            if fp:
                L.append(f"  {time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(fp)))}  "
                         f"{_sha256(fp)[:12]}  {rel}   ({label})")
        rel, fp = _find_src([PLATFORM_SRC[1]])
        if fp:
            L.append(f"  {time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(fp)))}  "
                     f"{_sha256(fp)[:12]}  {rel}   ({PLATFORM_SRC[0]} · manifest 未记录, 按时间戳判)")
        L += ["", "判据: 三份文档 manifest 记录的 sha 必须 = 当前真源 sha; 任一不符即 ⛔ 过期,",
              "      重新生成后三份的 工程库 sha 必然相同 (同源) —— 这就是『数据统一』的可验证口径。"]
        self.pv_head.setText("一致性核对: 三份文档记录的 sha vs 当前真源 (对不上 = 过期, 需重新生成)")
        self.preview.setPlainText("\n".join(L))

    # ── 文档交付 (2026-10-10) ──
    def _goto_docs(self):
        for i in range(self.tabs.count()):
            if "文档" in self.tabs.tabText(i):
                self.tabs.setCurrentIndex(i)
                self._copy_docs()
                return
        self.out.setPlainText("⛔ 文档交付页签缺失 (页面构建异常)")

    def _run_doc(self, key):
        """点按钮必出结果: 真跑导出器, 面板给日志, 右侧列出可复制的绝对路径。"""
        from PyQt5.QtWidgets import QApplication
        label, script, args = DOC_SCRIPTS[key]
        self.out.setPlainText(f"▶ {label} 运行中… (数据源: 工程库 + 平台真源)")
        QApplication.processEvents()
        self.out.setPlainText(_run_script(script, args))
        QApplication.processEvents()
        inv = _doc_inventory()
        if hasattr(self, "docs_out"):
            self.docs_out.setPlainText(inv)

    def _copy_docs(self):
        from PyQt5.QtWidgets import QApplication
        inv = _doc_inventory()
        if hasattr(self, "docs_out"):
            self.docs_out.setPlainText(inv)
        QApplication.clipboard().setText(inv)
        self.out.setPlainText("📋 产物路径已复制到剪贴板 (可直接粘到聊天/文档里):\n" + inv)

    def _open_docs(self):
        import subprocess
        d = _newest_out_dir("outputs/docs_bundle") or _newest_out_dir("outputs/project_docs")
        if not d:
            self.out.setPlainText("⚠️ 还没有产物目录 —— 先点「📦 三件套导出」")
            return
        try:
            subprocess.Popen(["xdg-open", d])
            self.out.setPlainText(f"📂 已打开: {d}")
        except Exception as e:  # noqa: BLE001
            self.out.setPlainText(f"⛔ 打不开文件管理器: {e}\n路径 (可复制): {d}")

    # ── 结果面板 ──
    def _back_home(self):
        """← 返回主窗口: 优先走控制台左侧栏的真实路径(「← 返回首页」按钮 → layer_clicked),
        退路是直接调主窗口的 _on_nav('home')。两条都不通才提示, 不静默。"""
        win = self.window()
        try:
            sb = getattr(win, "sidebar", None)
            if sb is not None:
                for b in sb.findChildren(QPushButton):
                    t = (b.text() or "")
                    if "首页" in t or "主窗口" in t:
                        b.click()                      # 走真实 UI 路径 (同步侧栏高亮 + 切栈)
                        return
        except Exception:  # noqa: BLE001
            pass
        fn = getattr(win, "_on_nav", None)
        if callable(fn):
            try:
                fn("home")
                return
            except Exception:  # noqa: BLE001
                pass
        self.out.setPlainText("⛔ 找不到主窗口的导航入口 (sidebar/_on_nav 都不在)——请直接用左侧栏「← 返回首页」")

    def _selected_task(self):
        r = self.tasks_table.currentRow()
        if r < 0:
            return None
        it = self.tasks_table.item(r, 0)
        return it.text() if it else None

    def _run_selected(self, fn, use_sel=False, **kw):
        """按钮入口: use_sel=True 时取表格选中行的任务ID传进去。"""
        if use_sel:
            tid = self._selected_task()
            if not tid:
                self.out.setPlainText("⛔ 先在任务表里选一行 (点一下任务ID那个格子)")
                return
            kw["arg"] = tid
        self._run_into(fn, **kw)

    def _run_into(self, fn, **kw):
        self.out.setPlainText(_run(fn, **kw))


def build_config_center(model_page=None, theme=None):
    """studio.py 调用入口: 返回配置中心新页 (失败时抛异常, 由 studio 兜底回退)。"""
    return ConfigCenterPage(model_page=model_page, theme=theme)
