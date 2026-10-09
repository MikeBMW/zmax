#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_strip.py —— 控制台「实时数据条」(2026-10-10 老倪: UI 要与全系统数据同步)。

问题: 各功能页原来把数字写死在文案里 (或读错路径), 数据一变界面就说谎, 且没人知道数据是不是新鲜的。
本组件: 一条小卡 —— 跑一个**只读**工具 (输出 JSON) → 定时刷新 → 显示关键字段 + **采集时间** + 刷新按钮。
      用 QProcess 起子进程, 不阻塞 GUI; 工具挂了就显红字并保留上一次的值 (不假装正常)。

用法:
    strip = LiveStrip("📊 数据资产", ["tools/dataset_inventory.py", "--json"], _fmt)
    layout.addWidget(strip)

fmt(payload, err) -> (summary:str, detail:str, ok:bool)
"""
import json
import os
import sys
import time

from PyQt5.QtCore import QProcess, QTimer
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

C_BG2, C_BORDER, C_GRAY, C_DIM = "#131823", "#2a3441", "#9aa7b4", "#6e7b8a"
C_WHITE, C_GREEN, C_RED, C_GOLD = "#e6edf3", "#00d4aa", "#ff6b6b", "#ffc857"


class LiveStrip(QFrame):
    """实时数据条 —— 子进程跑只读工具, 定时把 JSON 摘要贴上来 (带采集时间)。"""

    def __init__(self, title, cmd, fmt, interval_s=10, parent=None):
        super().__init__(parent)
        self._title = title
        self._cmd = cmd
        self._fmt = fmt
        self._interval = max(2, int(interval_s))
        self._proc = None
        self._buf = b""
        self._last_ok = None
        self._last_at = None

        self.setStyleSheet("background:%s; border:1px solid %s; border-radius:8px;" % (C_BG2, C_BORDER))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        self.lbl_t = QLabel(title)
        self.lbl_t.setStyleSheet("color:%s; background:transparent; border:none; font-size:13px; font-weight:600;"
                                 % C_WHITE)
        lay.addWidget(self.lbl_t)

        self.lbl_s = QLabel("采集…")
        self.lbl_s.setStyleSheet("color:%s; background:transparent; border:none; font-size:13px;" % C_GRAY)
        lay.addWidget(self.lbl_s, 1)

        self.lbl_at = QLabel("")
        self.lbl_at.setStyleSheet("color:%s; background:transparent; border:none; font-size:11px;" % C_DIM)
        lay.addWidget(self.lbl_at)

        self.btn = QPushButton("刷新")
        self.btn.setFixedWidth(56)
        self.btn.setStyleSheet(
            "QPushButton{background:#1f2733; color:%s; border:1px solid %s; border-radius:4px; padding:3px 8px;"
            " font-size:12px;} QPushButton:hover{border-color:%s;}" % (C_WHITE, C_BORDER, C_GREEN))
        self.btn.clicked.connect(self.refresh)
        lay.addWidget(self.btn)

        self._tm = QTimer(self)
        self._tm.setInterval(self._interval * 1000)
        self._tm.timeout.connect(self.refresh)
        self.refresh()
        self._tm.start()

    # ── 采集 ────────────────────────────────────────────────────────────────
    def refresh(self):
        if self._proc is not None:
            return                                     # 上一轮还没回, 不叠进程
        self._buf = b""
        p = QProcess()                                 # 不挂 parent: 由 self._proc 显式持有/销毁,
        self._proc = p                                 #   否则父控件先析构会 delete 掉还在跑的 QProcess →
        p.setWorkingDirectory(ROOT)                    #   'QProcess: Destroyed while process is still running' → abort
        p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(self._on_out_ready)
        p.finished.connect(self._on_finished)
        p.start(sys.executable if getattr(sys, "frozen", False) else self._py(), self._cmd)

    def stop(self):
        """停掉在飞的采集进程 (窗口关闭/换页时调), 避免进程悬挂与已删对象访问。"""
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            p.readyReadStandardOutput.disconnect()
            p.finished.disconnect()
        except Exception:                                                  # noqa: BLE001
            pass
        try:
            if p.state() != QProcess.NotRunning:
                p.kill()
                p.waitForFinished(300)
        except Exception:                                                  # noqa: BLE001
            pass
        try:
            p.deleteLater()
        except Exception:                                                  # noqa: BLE001
            pass

    def closeEvent(self, e):
        try:
            self._tm.stop()
        except Exception:                                                  # noqa: BLE001
            pass
        self.stop()
        super().closeEvent(e)

    @staticmethod
    def _py():
        """优先用 GUI 自带 venv 的解释器 (与 studio 同环境), 否则用当前解释器。"""
        v = os.path.join(ROOT, "gui-venv311", "bin", "python")
        return v if os.path.exists(v) else sys.executable

    def _on_out_ready(self):
        p = self.sender()
        if p is None:
            return
        try:
            self._buf += bytes(p.readAllStandardOutput())
        except RuntimeError:                                               # C++ 对象已删, 忽略
            pass

    def _on_finished(self, code, _st=0):
        p = self.sender()
        self._proc = None
        try:
            if p is not None:
                self._buf += bytes(p.readAllStandardOutput())
                p.deleteLater()
        except (RuntimeError, AttributeError):
            pass
        payload, err = None, None
        txt = ""
        try:
            txt = self._buf.decode("utf-8", "replace").strip()
            payload = json.loads(txt) if txt else None
            if payload is None:
                err = "工具没输出 JSON (exit=%s)" % code
        except Exception:                                                       # noqa: BLE001
            # 合并通道下 stderr 的告警/日志会混在 JSON 前后 (如 [redaction] 断言 ...) ⇒
            # 退一步取"第一个 { 到最后一个 }" 之间的片段再解析; 仍失败才算真错。
            payload, err = None, None
            a, b = txt.find("{"), txt.rfind("}")
            frag = txt[a:b + 1] if (a >= 0 and b > a) else ""
            if frag:
                try:
                    payload = json.loads(frag)
                except Exception as e2:                                        # noqa: BLE001
                    err = "JSON 解析失败: %s" % e2
            if payload is None and err is None:
                err = "工具没输出 JSON (exit=%s)" % code
        try:
            summary, detail, ok = self._fmt(payload, err)
        except Exception as e:                                             # noqa: BLE001
            summary, detail, ok = "格式化失败: %s" % e, "", False
        self.lbl_s.setText(summary)
        self.lbl_s.setToolTip(detail or "")
        self.lbl_s.setStyleSheet("color:%s; background:transparent; border:none; font-size:13px;"
                                 % (C_GREEN if ok else C_RED))
        if ok:
            self._last_ok = summary
            self._last_at = time.strftime("%H:%M:%S")
            self.lbl_at.setText("采集 %s" % self._last_at)
        else:
            # 失败不掩盖: 红字 + 保留上次值参考
            self.lbl_at.setText(("上次 %s" % self._last_at) if self._last_at else "")
        self._after_payload(payload)


    def _after_payload(self, payload):
        """采集回调结束后的钩子 (LiveStrip 无动作, LiveTable 拿去填表)。"""

    def _build_table_into(self, layout):
        """把明细表挂到页面自己的布局上 (放哪由页面决定), 返回表格对象。"""
        from PyQt5.QtWidgets import QTableWidget
        self._tbl = QTableWidget(0, 1)
        self._tbl.setStyleSheet(
            "QTableWidget{background:#0f1318; color:%s; gridline-color:#232c39; border:1px solid %s;"
            " border-radius:8px; font-size:12px;} QHeaderView::section{background:#1a2230; color:%s;"
            " border:none; padding:5px; font-weight:600;}" % (C_WHITE, C_BORDER, C_GRAY))
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._tbl)
        return self._tbl


class LiveTable(LiveStrip):
    """实时明细表 —— 与 LiveStrip 同一套采集机制, 额外把 rows() 填进一张表 (只读, 可复制)。"""

    def __init__(self, title, cmd, fmt, rows, interval_s=60, max_rows=300, parent=None):
        self._rows_fn = rows
        self._tbl = None
        self._max_rows = max_rows
        super().__init__(title, cmd, fmt, interval_s=interval_s, parent=parent)

    def _after_payload(self, payload):
        if self._tbl is None:
            return
        from PyQt5.QtWidgets import QTableWidgetItem
        err = None if payload is not None else "no payload"
        try:
            cols, rows = self._rows_fn(payload, err)
        except Exception:                                                  # noqa: BLE001
            return
        if not cols:
            return                                                         # 失败保留旧表 (不闪空)
        self._tbl.setColumnCount(len(cols))
        self._tbl.setHorizontalHeaderLabels(cols)
        self._tbl.setRowCount(min(len(rows), self._max_rows))
        for r, row in enumerate(rows[:self._max_rows]):
            for c, v in enumerate(row):
                self._tbl.setItem(r, c, QTableWidgetItem("" if v is None else str(v)))
        self._tbl.resizeColumnsToContents()
        last = self._tbl.columnCount() - 1
        if self._tbl.columnWidth(last) > 520:
            self._tbl.setColumnWidth(last, 520)                            # 路径列别把表撑爆


# ── 三页面的取数函数 (工具 JSON → 一行摘要) ─────────────────────────────
def rows_dataset(p, err):
    """数据集页明细表: 类别 / 大小 / 最新时间 / 路径 (按大小降序, 只取前 300 条防卡)。"""
    if err:
        return [], []
    it = sorted(p.get("items") or [], key=lambda i: -(i.get("size_bytes") or 0))[:300]
    cols = ["类别", "名称", "大小", "最新时间", "路径"]
    rows = [[i.get("category"), i.get("name"), i.get("size_human"), i.get("latest_mtime_str"),
             i.get("path")] for i in it]
    return cols, rows


def rows_models(p, err):
    """模型引擎明细表: 层 / 名称 / 大小 / 最新时间 / 报告 / 路径。"""
    if err:
        return [], []
    cols = ["层", "名称", "大小", "最新时间", "训练报告", "路径"]
    rows = []
    for m in (p.get("models") or []):
        sz = m.get("size") or m.get("size_bytes") or 0
        rows.append([m.get("layer"), m.get("name"), _human(sz), m.get("mtime"),
                     m.get("report") or "—", m.get("path")])
    for t in (p.get("training") or []):
        rows.append([t.get("layer"), "▶ 正在训练 (pid %s)" % t.get("pid"), "—", "%ss" % t.get("elapsed_s"),
                     t.get("progress") or "", t.get("cmd") or ""])
    return cols, rows


def fmt_remote(p, err):
    """远程监控/大屏同源 一行摘要 → (摘要, 详情, ok)。"""
    if err or not isinstance(p, dict):
        return "采集失败: %s" % (err or "无数据"), "", False
    eps = p.get("endpoints") or []
    ok = sum(1 for e in eps if e.get("ok"))
    stale = sum(1 for e in eps if e.get("stale"))
    ss = p.get("same_source") or []
    good = sum(1 for x in ss if x.get("consistent") is True)
    bad = sum(1 for x in ss if x.get("consistent") is False)
    nc = sum(1 for x in ss if x.get("consistent") is None)
    s = ("端点 %d/%d 通 · 过期 %d · 同源 %d 条 (一致 %d / 不一致 %d / 不可比 %d)"
         % (ok, len(eps), stale, len(ss), good, bad, nc))
    det = "\n".join("%-28s %-12s %s  age=%s%s"
                    % (e.get("name") or "", e.get("owner") or "",
                       (e.get("status") if e.get("ok") else ("ERR " + str(e.get("err"))[:50])),
                       e.get("data_age_s"), "  STALE" if e.get("stale") else "")
                    for e in eps)
    det += "\n\n同源判定:\n" + "\n".join(
        "  [%s] %s  %s%s" % ("一致" if x.get("consistent") is True else
                            ("不一致" if x.get("consistent") is False else "不可比"),
                            x.get("fact"), "  ".join("%s=%s" % (s2.get("name"), s2.get("value"))
                                                     for s2 in (x.get("sources") or [])),
                            ("  " + x.get("note")) if x.get("note") else "")
        for x in ss)
    return s, det, True


def rows_remote(p, err):
    """端点明细: 端点 / 归属 / 状态 / 数据龄 / 标记。"""
    if err or not isinstance(p, dict):
        return [], []
    cols = ["端点", "归属", "状态", "数据龄(s)", "标记"]
    out = []
    for e in p.get("endpoints") or []:
        age = e.get("data_age_s")
        out.append([e.get("name") or "", e.get("owner") or "",
                    str(e.get("status") if e.get("ok") else ("ERR: " + str(e.get("err"))[:40])),
                    ("%.2f" % age) if isinstance(age, (int, float)) else "—",
                    ("⏸ STALE" if e.get("stale") else ("✅" if e.get("ok") else "❌"))])
    return cols, out


def _human(b):
    try:
        b = float(b)
    except (TypeError, ValueError):
        return str(b)
    for u, d in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if b >= d:
            return "%.1f %s" % (b / d, u)
    return "%d B" % b


def fmt_dataset(p, err):
    if err:
        return "采集失败: %s" % err, "", False
    it = p.get("items") or []
    gb = lambda b: "%.1f GB" % (b / 1e9)                                   # noqa: E731
    by = {}
    for i in it:
        c = by.setdefault(i.get("category"), [0, 0])
        c[0] += 1
        c[1] += i.get("size_bytes") or 0
    d, g, m = by.get("downloaded", [0, 0]), by.get("generated", [0, 0]), by.get("map", [0, 0])
    s = ("已下载 %d 条/%s · 已生成 %d 条/%s · 建图 %d 条/%s · 共 %d 条/%s"
         % (d[0], gb(d[1]), g[0], gb(g[1]), m[0], gb(m[1]), len(it), gb(sum(x[1] for x in by.values()))))
    det = "\n".join("%s  %s  %s" % (i.get("category"), i.get("size_human"), i.get("path")) for i in it[:40])
    return s, det, True


def fmt_models(p, err):
    if err:
        return "采集失败: %s" % err, "", False
    g = p.get("gpu") or {}
    tr = p.get("training") or []
    ms = p.get("models") or []
    s = ("GPU %s%% · 显存 %s/%s MiB · %s°C · %sW · 在跑训练 %d · 模型 %d 条"
         % (g.get("util"), int(g.get("mem_used") or 0), int(g.get("mem_total") or 0),
            g.get("temp"), g.get("power"), len(tr), len(ms)))
    if tr:
        s += " · " + " ".join("%s(pid %s)" % (t.get("layer"), t.get("pid")) for t in tr[:3])
    det = "\n".join("%s  %s  %s  %s" % (m.get("layer"), m.get("name"), m.get("path"),
                                        m.get("mtime") or "") for m in ms[:20])
    return s, det, True


def fmt_arch(p, err):
    if err:
        return "采集失败: %s" % err, "", False
    n, e = p.get("nodes") or [], p.get("edges") or []
    kinds = {}
    for x in n:
        kinds[x.get("kind")] = kinds.get(x.get("kind"), 0) + 1
    s = "节点 %d · 边 %d · %s" % (len(n), len(e),
                                  " ".join("%s=%d" % (k, v) for k, v in sorted(kinds.items())))
    return s, "", True
