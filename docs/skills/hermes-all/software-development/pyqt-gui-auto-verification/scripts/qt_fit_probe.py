#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 Qt 控件"几何/截断"离屏探针 —— 判"有没有被裁/被硬切"用数字, 不靠读屏目检。

为什么要它: 读屏子代理给的"缺行/缺列头"可能是**旧构建**的图(见 SKILL.md 证据绑定进程那一节),
而"行被裁"在这种无滚动条+内容超高的界面里看不出提示 ⇒ 用几何量说话。

用法:
  python qt_fit_probe.py --path tools/gui --module studio --class StudioMainWindow \\
         --object-name cfg_matrix_table --nav training --width 1920 --height 1080
  # 退出码: 0 = 没发现被裁/被切; 1 = 有 (可直接当判据用)

参数:
  --module/--class   被测窗口模块与类名 (无参构造)
  --object-name      目标控件 objectName (QTableWidget/QWidget 均可; 不给则列出所有 QTableWidget)
  --nav <key>        构造后调 window._on_nav(<key>) 切页 (没有这个方法就跳过)
  --rows/--cols      不给 --object-name 时按行/列数挑表
  --json             输出 JSON (入报告)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", action="append", default=[], help="sys.path 前置目录 (可多次)")
    ap.add_argument("--module", required=True)
    ap.add_argument("--class", dest="cls", required=True)
    ap.add_argument("--object-name", default="")
    ap.add_argument("--nav", default="")
    ap.add_argument("--rows", type=int, default=0)
    ap.add_argument("--cols", type=int, default=0)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--wait", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for p in a.path + [os.getcwd()]:
        sys.path.insert(0, p)

    from PyQt5.QtGui import QFontMetrics                                          # noqa: PLC0415
    from PyQt5.QtWidgets import (QAbstractScrollArea, QApplication,               # noqa: PLC0415
                                 QTableWidget, QWidget)

    app = QApplication.instance() or QApplication(sys.argv)
    win = getattr(importlib.import_module(a.module), a.cls)()
    win.resize(a.width, a.height)
    win.show()
    if a.nav and hasattr(win, "_on_nav"):
        try:
            win._on_nav(a.nav)
        except Exception:                                                          # noqa: BLE001
            pass
    t0 = time.time()
    while time.time() - t0 < a.wait:
        app.processEvents()
        time.sleep(0.02)

    rep: dict = {"window": "%s.%s" % (a.module, a.cls), "widgets": [], "problems": []}

    def probe_widget(w, tag):
        info = {"tag": tag, "cls": type(w).__name__, "size": [w.width(), w.height()],
                "visible": w.isVisible()}
        chain, par = [], w.parent()
        while par is not None:
            if isinstance(par, QAbstractScrollArea):
                vs = par.verticalScrollBar()
                chain.append({"cls": type(par).__name__, "v": vs.value(), "max": vs.maximum()})
            par = par.parent()
        info["outer_scroll"] = chain
        top = w.mapTo(win, w.rect().topLeft())
        info["window_y"] = [top.y(), top.y() + w.height(), win.height()]
        if isinstance(w, QTableWidget):
            hh, vs, hs = w.horizontalHeader(), w.verticalScrollBar(), w.horizontalScrollBar()
            rows = [w.rowHeight(r) for r in range(w.rowCount())]
            need = sum(rows) + (hh.height() if hh.isVisible() else 0) + w.frameWidth() * 2 + 4
            info.update({"rows": w.rowCount(), "cols": w.columnCount(), "header_visible": hh.isVisible(),
                         "first_visible_row": w.rowAt(0), "vscroll": [vs.value(), vs.maximum()],
                         "hscroll": [hs.value(), hs.maximum()], "content_need_h": need,
                         "fits": need <= w.height() + 2, "word_wrap": w.wordWrap()})
            if info["first_visible_row"] > 0:
                rep["problems"].append("%s: 顶部被裁 (首可见行=%d)" % (tag, info["first_visible_row"]))
            if not info["fits"]:
                rep["problems"].append("%s: 内容 %dpx > 控件 %dpx ⇒ 底部行看不见"
                                       % (tag, need, w.height()))
            fm = QFontMetrics(w.font())
            bad = []
            for r in range(w.rowCount()):
                for c in range(w.columnCount()):
                    it = w.item(r, c)
                    if it is None:
                        continue
                    span = w.columnSpan(r, c) or 1
                    avail = sum(w.columnWidth(c + k) for k in range(span))
                    if avail <= 0:
                        continue
                    need_w = fm.horizontalAdvance(it.text()) + 12
                    if need_w <= avail:
                        continue
                    lines = -(-need_w // avail)
                    need_h = lines * (fm.height() + 6)
                    if w.wordWrap() and w.rowHeight(r) + 4 >= need_h:
                        continue                                              # 换行放得下 = 没丢字
                    bad.append({"row": r, "col": c, "need_px": need_w, "avail_px": avail,
                                "row_h": w.rowHeight(r), "text": it.text()[:60]})
            info["truncated"] = bad
            for b in bad:
                rep["problems"].append("%s: 行%d列%d 文字 %dpx > 可用 %dpx (行高%d) ⇒ 硬切: %s"
                                       % (tag, b["row"], b["col"], b["need_px"], b["avail_px"],
                                          b["row_h"], b["text"]))
        rep["widgets"].append(info)

    target = win.findChild(QWidget, a.object_name) if a.object_name else None
    if target is None:
        cands = win.findChildren(QTableWidget)
        if a.rows and a.cols:
            cands = [t for t in cands if t.rowCount() == a.rows and t.columnCount() == a.cols]
        rep["candidates"] = [{"name": t.objectName(), "rows": t.rowCount(), "cols": t.columnCount()}
                             for t in win.findChildren(QTableWidget)]
        for t in cands[:3]:
            probe_widget(t, t.objectName() or "(无名表)")
    else:
        probe_widget(target, a.object_name)

    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for w in rep["widgets"]:
            print("[%s] %s %sx%s 可见=%s 内容高=%s 装得下=%s 首可见行=%s 竖滚动=%s 换行=%s"
                  % (w["tag"], w["cls"], w["size"][0], w["size"][1], w["visible"],
                     w.get("content_need_h"), w.get("fits"), w.get("first_visible_row"),
                     w.get("vscroll"), w.get("word_wrap")))
            print("     外层滚动: %s | 窗口坐标: %s" % (w["outer_scroll"], w["window_y"]))
            for b in (w.get("truncated") or [])[:8]:
                print("     ✂ 行%d列%d %dpx>%dpx: %s" % (b["row"], b["col"], b["need_px"],
                                                          b["avail_px"], b["text"]))
        print("\n结论: %s" % ("干净 (无被裁/无硬切)" if not rep["problems"]
                              else "%d 处问题" % len(rep["problems"])))
        for p in rep["problems"]:
            print("  - " + p)

    sys.stdout.flush()
    os._exit(1 if rep["problems"] else 0)          # 跳过 teardown (残留线程会在退出时 abort)


if __name__ == "__main__":
    main()
