#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_config_page.py — 离屏真渲染「配置中心」页 + 截图 + 量左栏宽度(取证用, 不动正在跑的控制台)

用法:
  gui-venv311/bin/python tools/render_config_page.py [宽 高 输出png]
默认 1600x900 → /tmp/cc_after_1600x900.png
判据: 每个窗口尺寸下 ①左栏宽度 ≥ 内容需求宽度(最长条目不被截) ②右栏仍 ≥ 400px
只读: 建页 → 快照 → 退出; 不连网络、不写工程唯一依据。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication, QSplitter                                             # noqa: E402


def rows_of(tree):
    """(文本, 深度, 像素宽) 全部条目。"""
    fm = tree.fontMetrics()
    out, stack = [], [(tree.topLevelItem(i), 0) for i in range(tree.topLevelItemCount())]
    while stack:
        it, d = stack.pop()
        if it is None:
            continue
        out.append((it.text(0), d, fm.horizontalAdvance(it.text(0))))
        for i in range(it.childCount()):
            stack.append((it.child(i), d + 1))
    return out


def render(w, h, out):
    import veh6_config_page as V                                                                # noqa: E402
    app = QApplication.instance() or QApplication([])
    pg = V.ConfigCenterPage()
    pg.resize(w, h)
    pg.show()
    app.processEvents()
    for _ in range(3):                       # 让 singleShot(_apply_tree_width) 真的跑过
        app.processEvents()
    pg.grab().save(out)
    sp = pg.findChild(QSplitter)
    rows = rows_of(pg.tree)
    ind = pg.tree.indentation()
    need = pg._tree_need_width()
    avail = pg.tree.viewport().width()
    worst = max(((t, d, px) for t, d, px in rows), key=lambda r: r[1] * ind + r[2])
    print({"page": (pg.width(), pg.height()), "splitter": sp.sizes() if sp else None,
           "tree_w": pg.tree.width(), "avail_px": avail, "need_px": need,
           "worst_row": worst[0], "worst_px": worst[1] * ind + worst[2],
           "clipped": (worst[1] * ind + worst[2]) > avail,
           "right_w": (sp.sizes()[1] if sp else None), "png": out})
    return pg


if __name__ == "__main__":
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    o = sys.argv[3] if len(sys.argv) > 3 else "/tmp/cc_after_%dx%d.png" % (w, h)
    render(w, h, o)
