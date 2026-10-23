#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ppt_deck_window.py — 控制台内嵌「行业分析 PPT」查看窗（PyQt5 + QtWebEngine）。

为什么单独成文件：
- Python 侧不做 pptx 解析/渲染（那会引一堆依赖）；渲染在服务端(8793 /eval/ppt)做，
  这里只是一个浏览器壳 —— 与 ar_web_window 同思路：一个窗口一个 QWebEngineView。
- QtWebEngineWidgets 的 import 顺序由 studio.py 在模块导入期保证（见那里注释），
  本文件只在窗口实例化时才 import，避免污染启动。

对外：
    available() -> bool
    open_deck(url: str) -> bool       # 已在开则前移；不可用则返回 False（调用方退回系统浏览器）
"""
from __future__ import annotations

import os


def available() -> bool:
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception:                                               # noqa: BLE001
        return False


_WIN = None


def _make(url: str):
    from PyQt5.QtCore import QUrl, Qt
    from PyQt5.QtGui import QDesktopServices
    from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                                 QPushButton, QToolBar, QAction)
    from PyQt5.QtWebEngineWidgets import QWebEngineView

    class DeckWindow(QMainWindow):
        def __init__(self, u: str):
            super().__init__()
            self.setWindowTitle("📊 行业分析 PPT · 幻灯片预览")
            self.resize(1180, 860)
            self.setStyleSheet("QMainWindow{background:#0d1117;} QLabel{color:#8b949e;}"
                               "QToolBar{background:#161b22; border:0; spacing:8px; padding:6px;}"
                               "QPushButton{background:#161b22; color:#e6edf3; border:1px solid #30363d;"
                               " border-radius:7px; padding:6px 12px; font-size:13px;}"
                               "QPushButton:hover{border-color:#58a6ff; color:#58a6ff;}")
            self.url = u
            tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)
            b_re = QPushButton("⟳ 刷新"); b_re.clicked.connect(lambda: self.view.reload())
            b_out = QPushButton("↗ 在浏览器打开")
            b_out.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.view.url().toString())))
            b_close = QPushButton("✕ 关闭"); b_close.clicked.connect(self.close)
            for b in (b_re, b_out):
                tb.addWidget(b)
            sp = QLabel(" "); sp.setStyleSheet("QLabel{border:none;}")
            tb.addWidget(sp)
            self.lb = QLabel(""); tb.addSeparator()
            tb.addWidget(self.lb)
            spacer = QWidget(); spacer.setFixedWidth(8); tb.addWidget(spacer)
            tb.addWidget(b_close)
            self.view = QWebEngineView(self)
            self.view.setUrl(QUrl(u))
            self.view.loadFinished.connect(self._loaded)
            self.setCentralWidget(self.view)

        def _loaded(self, ok):
            self.lb.setText(("已加载 · " if ok else "⚠ 加载失败 · ") + self.url)

    return DeckWindow(url)


def open_deck(url: str) -> bool:
    """打开（或前移）PPT 预览窗。不可用返回 False，调用方退回系统浏览器。"""
    global _WIN
    if not available():
        return False
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return False
    try:
        if _WIN is not None:
            _WIN.show(); _WIN.raise_(); _WIN.activateWindow()
            if _WIN.url != url:
                _WIN.url = url
                _WIN.view.setUrl(__import__("PyQt5.QtCore", fromlist=["QUrl"]).QUrl(url))
            return True
        _WIN = _make(url)
        _WIN.show()
        return True
    except Exception as _e:                                          # noqa: BLE001
        print("⚠️ PPT 预览窗打开失败: %r" % (_e,), flush=True)
        return False


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    print("available:", available())
    u = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8793/eval/ppt"
    open_deck(u)
    sys.exit(app.exec_())
