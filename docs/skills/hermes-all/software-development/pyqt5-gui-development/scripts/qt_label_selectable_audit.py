#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qt_label_selectable_audit.py — 审计一个 QWidget 页面里“文字能不能被鼠标选中/复制”。

用法 (离屏即可，不动生产窗口):
    QT_QPA_PLATFORM=offscreen python qt_label_selectable_audit.py \
        --path <项目根> --module veh6_config_page --class ConfigCenterPage [--tabs]

判据:
  ① 页面内每个 QLabel 都带 TextSelectableByMouse + TextSelectableByKeyboard (默认 NoTextInteraction ⇒ 选不了)
  ② 每个页签切过去再查一遍 (动态刷新/换页后建的标签也算)
  ③ 后建的 QLabel (show + polish) 自动带上 (app 级 eventFilter 保障; 没有就红)
  ④ 真发一次鼠标拖选: selectedText() 非空 (QTest.mouseMove 不带按键状态, 必须手工 QMouseEvent)

退出码 0 = 全过。仅依赖 PyQt5。
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys


def _sel(lb) -> bool:
    from PyQt5.QtCore import Qt
    f = lb.textInteractionFlags()
    return bool(f & Qt.TextSelectableByMouse) and bool(f & Qt.TextSelectableByKeyboard)


def audit(widget, name) -> tuple[bool, str]:
    from PyQt5.QtWidgets import QLabel
    lbs = widget.findChildren(QLabel)
    bad = [lb for lb in lbs if not _sel(lb)]
    sample = " ; ".join((lb.text() or "")[:24].replace("\n", " ") for lb in bad[:4])
    return (not bad), "%s: %d 个标签, 不可选中 %d%s" % (
        name, len(lbs), len(bad), (" → " + sample) if bad else "")


def drag_select(lb) -> str:
    """真发一次拖选 (press + N×move(带左键) + release), 返回 selectedText。"""
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication
    _y = max(1, lb.height() // 2)
    _x0, _x1 = 2, max(4, min(lb.width() - 2, 300))

    def send(t, x, btn, held):
        QApplication.sendEvent(lb, QMouseEvent(t, QPointF(x, _y), btn, held, Qt.NoModifier))

    send(QEvent.MouseButtonPress, _x0, Qt.LeftButton, Qt.LeftButton)
    for x in range(_x0 + 6, _x1, 6):
        send(QEvent.MouseMove, x, Qt.NoButton, Qt.LeftButton)
    send(QEvent.MouseButtonRelease, _x1, Qt.LeftButton, Qt.NoButton)
    QApplication.processEvents()
    return (lb.selectedText() or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=os.getcwd(), help="项目根 (会加入 sys.path)")
    ap.add_argument("--module", required=True, help="包含页面类的模块名")
    ap.add_argument("--class", dest="cls", required=True, help="页面类名 (无参可构造)")
    ap.add_argument("--tabs", action="store_true", help="逐页签切过去各查一遍")
    ap.add_argument("--size", default="1600x950")
    a = ap.parse_args()

    for p in (a.path, os.path.join(a.path, "tools"), os.path.join(a.path, "tools", "gui")):
        if p not in sys.path:
            sys.path.insert(0, p)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    cls = getattr(importlib.import_module(a.module), a.cls)
    page = cls()
    w, h = (int(x) for x in a.size.lower().split("x"))
    page.resize(w, h)
    page.show()
    app.processEvents()

    checks = [audit(page, "整页")]

    if a.tabs and hasattr(page, "tabs"):
        for i in range(page.tabs.count()):
            page.tabs.setCurrentIndex(i)
            app.processEvents()
            checks.append(audit(page.tabs.widget(i), "页签[%d] %s" % (i, page.tabs.tabText(i))))

    late = QLabel("动态新增的一行文字 (show 之后应自动可选中)", page)
    late.show()
    app.processEvents()
    checks.append((_sel(late), "后建 QLabel 自动可选中 (app 级 eventFilter)"))

    cand = next((lb for lb in page.findChildren(QLabel) if _sel(lb) and len(lb.text() or "") > 8), None)
    got = drag_select(cand) if cand is not None else ""
    checks.append((bool(got), "真拖选: 「%s」" % (got[:34] or "拖选后 selectedText() 为空")))

    ok = 0
    for good, detail in checks:
        print(("  ✅ " if good else "  ❌ ") + detail)
        ok += bool(good)
    print("\n%s %d/%d" % ("✅ PASS" if ok == len(checks) else "❌ FAIL", ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
