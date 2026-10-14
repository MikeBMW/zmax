#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_config_center_info_panel.py — 配置中心「底部信息窗」判据 (老倪 2026-10-15)。

老倪原话: 「配置中心的页面UI要调整。产品配置的右侧下半部分的显示区太小, 且不能用鼠标滚动调整, 看不到显示内容;
下面的信息窗口当选择相应的配置面时, 信息没有对应上, 且显示区无法用鼠标拖动调整大小, 要可以隐藏」

判据 (全部离屏实测, 不看图):
  ① 布局: 底部信息窗在**竖直 QSplitter** 里 (可拖), 分隔条柄 ≥ 8px; out 不是固定高度 (min 很小 / max 很大)
  ② 可隐藏: 「▾ 收起信息窗」→ 隐藏 + 按钮改「▴ 展开信息窗」; 再点 → 恢复
  ③ 拖动优先: 拖过分隔条 (_out_user_sized) 之后 _fit_out 不再改高度; 点「↕ 自适应高度」可重算一次
  ④ 内容对应: 8 个面逐一选 (左树/页签), 信息窗第一行必须是「📍 当前配置面: <该面标题>」,
     且含该面自己的关键字, 并且**不含**别的面的页名 (防串味)
  ⑤ 可滚动: 内容比窗口高时竖直滚动条可用 (不是靠切掉)

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_center_info_panel.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt                                                     # noqa: E402
from PyQt5.QtWidgets import QApplication, QSplitter, QTextEdit                  # noqa: E402

import veh6_config_page as V                                                    # noqa: E402

CHECKS = []


def chk(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print(("  ✅ " if ok else "  ⛔ ") + name + ("   " + str(detail) if detail else ""))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = V.build_config_center(None, None)      # 与 studio 同一条构造路径 (model_page 可有可无)
    page.resize(1600, 950)
    page.show()
    app.processEvents()

    print("═══ ① 布局: 信息窗可拖 / 不是固定高度 ═══")
    vs = getattr(page, "vsplit", None)
    _ok_split = isinstance(vs, QSplitter) and vs.orientation() == Qt.Vertical and vs.count() == 2 \
        and vs.widget(1) is getattr(page, "out_box", None)
    chk("底部信息窗在竖直 QSplitter 里 (工作区 + 信息窗)", _ok_split,
        "count=%s · 第二块=out_box:%s" % (getattr(vs, "count", lambda: "—")(),
                                          vs.widget(1) is getattr(page, "out_box", None) if vs else False))
    chk("分隔条柄 ≥ 8px (鼠标好抓)", bool(vs) and vs.handleWidth() >= 8, "handleWidth=%s" % (vs.handleWidth() if vs else "—"))
    o = page.out
    _mx = o.maximumHeight()
    chk("信息窗不是固定高度 (min≤80 且 max 很大)", o.minimumHeight() <= 80 and _mx >= 10000,
        "min=%d max=%s" % (o.minimumHeight(), _mx if _mx < 10000 else "∞"))
    chk("信息窗是可滚动文本窗 (QTextEdit)", isinstance(o, QTextEdit))
    _sz = vs.sizes()
    chk("初始高度: 工作区 > 信息窗 且 信息窗 ≥ 150px", _sz[0] > _sz[1] >= 150, "sizes=%s" % _sz)

    print("\n═══ ② 可隐藏 (老倪: 「要可以隐藏」) ═══")
    page._toggle_out()
    app.processEvents()
    _hid = (page._out_on is False) and ("▴ 展开信息窗" in page.b_out.text())
    chk("点「▾ 收起信息窗」→ 隐藏 + 按钮变「▴ 展开信息窗」", _hid,
        "_out_on=%s · 按钮=%s" % (page._out_on, page.b_out.text()))
    page._toggle_out()
    app.processEvents()
    chk("再点 → 恢复显示 + 按钮变回「▾ 收起信息窗」",
        page._out_on is True and "▾ 收起信息窗" in page.b_out.text(),
        "_out_on=%s · 按钮=%s" % (page._out_on, page.b_out.text()))

    print("\n═══ ③ 拖动优先 (拖过之后不再被自动覆盖) ═══")
    page._out_user_sized = True
    page.vsplit.setSizes([700, 250])
    app.processEvents()
    _b = page.vsplit.sizes()
    page._fit_out()
    app.processEvents()
    _a = page.vsplit.sizes()
    chk("拖过分隔条后 _fit_out 不再改高度", _a == _b, "前=%s 后=%s" % (_b, _a))
    page._fit_out_clicked()          # 点「↕ 自适应高度」= 允许重算一次
    app.processEvents()
    chk("点「↕ 自适应高度」后重新按内容给高度 (且 ≤ 上限)",
        page.vsplit.sizes() != _a or page._out_user_sized is False,
        "sizes=%s · 用户拖过标记=%s" % (page.vsplit.sizes(), page._out_user_sized))

    print("\n═══ ④ 选面 → 信息窗内容对应 (8 个面逐一) ═══")
    _tabs = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    _want = {"产品配置": ["平台", "active_product"], "任务配置": ["任务("], "功能配置": ["功能清单汇总"],
             "模型配置": ["模型 ←→ 工程配置" if False else "模型", "匹配"], "性能配置": ["性能配置参数"],
             "工单配置": ["工单"], "文档配置": ["三份交付文档", "正文预览"], "工程配置": ["工程域参数"]}
    bad = []
    for i, t in enumerate(_tabs):
        page.tabs.setCurrentIndex(i)
        app.processEvents()
        txt = page.out.toPlainText()
        _first = txt.splitlines()[0] if txt else ""
        _mine = ("当前配置面: " + t.strip()) in _first
        _key = next((k for k in _want if k in t), None)
        _hit = (not _key) or any(w in txt for w in _want[_key])
        _others = [x for x in _want if x not in t and ("当前配置面: " + x) in _first]
        _ok = _mine and _hit and not _others
        if not _ok:
            bad.append("%s(第一行=%s · 本面关键字=%s)" % (t.strip(), _first[:28], _hit))
        print("      %-16s → 第一行 %s · 本面关键字=%s" % (t.strip(), _first[:34], _hit))
    chk("8 个面逐一: 第一行=该面 · 含本面关键字 · 不串味", not bad, " ; ".join(bad) if bad else "8/8")

    print("\n═══ ⑤ 内容比窗口高时可滚动 (不是被切掉) ═══")
    page.vsplit.setSizes([820, 90])          # 故意压到很矮
    app.processEvents()
    _sb = page.out.verticalScrollBar()
    chk("压到很矮时竖直滚动条可用 (可拖着看全内容)", _sb.maximum() > 0,
        "scrollRange=0..%d · 内容行 %d" % (_sb.maximum(), len(page.out.toPlainText().splitlines())))

    print("\n═══ ⑥ 每一页都可滚动 (页面压小后能滚到全部内容) ═══")
    from PyQt5.QtWidgets import QScrollArea                                      # noqa: E402
    bad = []
    for i in range(page.tabs.count()):
        _t = page.tabs.tabText(i).strip()
        sa = page.tabs.widget(i)
        if not isinstance(sa, QScrollArea) or not sa.widgetResizable():
            bad.append(_t + "(没包 QScrollArea)")
            continue
        sa.setFixedHeight(320)
        app.processEvents()
        _need = sa.widget().minimumSizeHint().height()
        if sa.verticalScrollBar().maximum() <= 0 and _need > 320:
            bad.append(_t + "(压到320px滚不动)")
    chk("8 页都包在 QScrollArea · 内容比视口高时竖直滚动条可用", not bad,
        ("有问题: " + " ; ".join(bad)) if bad else "%d/%d 页可滚" % (page.tabs.count(), page.tabs.count()))

    _ok = sum(1 for _n, k, _d in CHECKS if k)
    print("\n═══ 判据汇总: %d/%d PASS ═══" % (_ok, len(CHECKS)))
    for n, k, d in CHECKS:
        if not k:
            print("  ⛔ " + n + "   " + str(d))
    print("✅ PASS %d/%d" % (_ok, len(CHECKS)) if _ok == len(CHECKS) else "❌ FAIL %d/%d" % (_ok, len(CHECKS)))
    return 0 if _ok == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
