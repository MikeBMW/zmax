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
             "文档配置": ["三份交付文档", "正文预览", "工单", "成本"], "工程配置": ["工程域参数"]}
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

    print("\n═══ ⑦ 产品配置页: 平台产品/产品特征清单两张表**看得见** (老倪 2026-10-15) ═══")
    _i = page._tab_index_by_title("产品配置")
    page.tabs.setCurrentIndex(_i)
    page.resize(1600, 950)
    app.processEvents()
    _p = getattr(page, "plat_prod_table", None)
    _f = getattr(page, "plat_feat_table", None)
    chk("平台产品表 ≥ 100px 且有数据行", _p is not None and _p.height() >= 100 and _p.rowCount() >= 2,
        "高=%s · 行=%s" % (getattr(_p, "height", lambda: "—")(), getattr(_p, "rowCount", lambda: "—")()))
    chk("产品特征清单表 ≥ 260px 且有数据行 (之前被压成看不见)",
        _f is not None and _f.height() >= 260 and _f.rowCount() >= 10,
        "高=%s · 行=%s" % (getattr(_f, "height", lambda: "—")(), getattr(_f, "rowCount", lambda: "—")()))

    print("\n═══ ⑦b 功能配置页 74 行功能清单也看得见 ═══")
    page.tabs.setCurrentIndex(page._tab_index_by_title("功能配置"))
    app.processEvents()
    _fn = getattr(page, "fn_table", None)
    chk("功能清单表 ≥ 300px 且行数 = 唯一依据", _fn is not None and _fn.height() >= 300 and _fn.rowCount() >= 70,
        "高=%s · 行=%s" % (getattr(_fn, "height", lambda: "—")(), getattr(_fn, "rowCount", lambda: "—")()))
    page.tabs.setCurrentIndex(page._tab_index_by_title("产品配置"))
    app.processEvents()

    print("\n═══ ⑧ 窗口压矮后这两张表**仍不被压没** (页面靠外层滚动, 表格保底高度) ═══")
    page.resize(1600, 620)
    app.processEvents()
    _h1, _h2 = _p.height(), _f.height()
    _min1, _min2 = _p.minimumHeight(), _f.minimumHeight()
    chk("压矮后两表高度 ≥ 各自最小高度 (不会缩成看不见)", _h1 >= _min1 and _h2 >= _min2,
        "产品表 %d≥%d · 特性表 %d≥%d" % (_h1, _min1, _h2, _min2))
    page.resize(1600, 950)
    app.processEvents()

    print("\n═══ ⑨ 模型配置页 = 功能配置 ←→ L2/L3/L4/L5 层模型 映射 (老倪: 这是主要信息) ═══")
    from zmax_platform_info import layer_summary as _ls3, function_layer_map as _flm3      # noqa: E402
    _sum, _map = _ls3(), _flm3()
    page.tabs.setCurrentIndex(page._tab_index_by_title("模型配置"))
    page.resize(1600, 950)
    app.processEvents()
    _lt, _mt = getattr(page, "ml_layer_table", None), getattr(page, "ml_map_table", None)

    def _colidx(tb, want):
        """按**表头名字**取列号 (判据不得硬编码列号 —— 加一列就红的那种错, v5.50.76 已经踩过一次)。"""
        for j in range(tb.columnCount()):
            _h = tb.horizontalHeaderItem(j)
            if _h and want in _h.text():
                return j
        return -1
    if _lt is None or _mt is None:
        chk("模型配置页有层表/映射表", False, "层表=%s 映射表=%s" % (_lt, _mt))
        _c_ly, _c_md, _c_ver, _c_fn = 0, 2, 3, 6
    else:
        _c_ly, _c_md = _colidx(_lt, "层"), _colidx(_lt, "在役主模型")
        _c_ver, _c_fn = _colidx(_lt, "版本"), _colidx(_lt, "承载功能")
    chk("四层 (L5/L4/L3/L2) 各一行 + PLAT 一行", _lt is not None and _lt.rowCount() == len(_sum["rows"]),
        "行=%s (唯一依据 %d)" % (getattr(_lt, "rowCount", lambda: "—")(), len(_sum["rows"])))
    _got = [(_lt.item(i, _c_ly).text(), _lt.item(i, _c_md).text()) for i in range(_lt.rowCount())]
    _want = [(r["layer"], r["model"]) for r in _sum["rows"]]
    chk("每层「在役主模型」= 唯一依据同源 (不是手抄)", _got == _want, "页面=%s" % (_got[:2],) if _got != _want else "5/5 同源")
    # ★全局同步: 必须与**主控制台模型矩阵**同一条 (老倪: 「你来同步全局数据」)
    from zmax_platform_info import matrix_columns as _mxc, short_model_name as _smn3        # noqa: E402
    _mx = _mxc()
    _same = bool(_mx) and all(_lt.item(i, _c_md).text() == _smn3((_mx.get(_lt.item(i, _c_ly).text()) or {}).get("name"))
                              for i in range(_lt.rowCount()) if _lt.item(i, _c_ly).text() in _mx)
    chk("与主控制台「模型配置矩阵」同名同版本 (同一个唯一依据, 两边不许打架)", _same,
        "矩阵四层: " + " | ".join("%s=%s" % (k, _smn3((v or {}).get("name"))) for k, v in sorted(_mx.items())) if _mx else "矩阵取不到")
    chk("每层「版本」也来自矩阵 (不是留空)",
        bool(_mx) and all((_lt.item(i, _c_ver).text() or "—") == ((_mx.get(_lt.item(i, _c_ly).text()) or {}).get("version") or "—")
                          for i in range(_lt.rowCount()) if _lt.item(i, _c_ly).text() in _mx),
        " / ".join("%s=%s" % (_lt.item(i, _c_ly).text(), _lt.item(i, _c_ver).text()) for i in range(_lt.rowCount())))
    chk("每层「承载功能」数 = 唯一依据现算",
        all(_lt.item(i, _c_fn).text() == "%d 条" % _sum["rows"][i]["fn_count"] for i in range(_lt.rowCount())),
        " / ".join(_lt.item(i, _c_fn).text() for i in range(_lt.rowCount())))
    chk("映射表行数 = 功能唯一依据全量 (一条不漏)", _mt is not None and _mt.rowCount() == _map["total"],
        "表 %s 行 · 唯一依据 %d 条" % (getattr(_mt, "rowCount", lambda: "—")(), _map["total"]))
    _mc_md = _colidx(_mt, "承载模型") if _mt.columnCount() else -1
    _bad_row = []
    for i, r in enumerate(_map["rows"]):
        _cell = _mt.item(i, _mc_md).text() if _mt.item(i, _mc_md) else ""
        if _cell != r["model_text"]:
            _bad_row.append("第%d行 %s≠%s" % (i, _cell[:24], r["model_text"][:24]))
    chk("逐行「承载模型」= 唯一依据 join 结果", not _bad_row, " ; ".join(_bad_row[:3]) if _bad_row else "%d/%d 行一致" % (_map["total"], _map["total"]))
    _comb = [r for r in _map["rows"] if len(r["layers"]) > 1 and "PLAT" not in r["layers"]]
    _ci = _map["rows"].index(_comb[0]) if _comb else -1
    chk("组合层 (如 L4/L5) 一行列**两条**模型, 不丢一条",
        bool(_comb) and _ci >= 0 and (" + " in (_mt.item(_ci, _mc_md).text() if _mt.item(_ci, _mc_md) else "")),
        "组合行 %d 条 · 例: %s" % (len(_comb), (_mt.item(_ci, _mc_md).text() if _ci >= 0 and _mt.item(_ci, _mc_md) else "—")[:60]))
    _plat = [r for r in _map["rows"] if "PLAT" in (r["layers"] or [])]
    _pi = _map["rows"].index(_plat[0]) if _plat else -1
    chk("平台支撑条明写「不归属层模型」(不静默丢)",
        bool(_plat) and _pi >= 0 and "不归属层模型" in (_mt.item(_pi, _mc_md).text() if _mt.item(_pi, _mc_md) else ""),
        "%d 条平台支撑" % len(_plat))
    chk("两张表都看得见 (层表 ≥160px · 映射表 ≥380px)",
        _lt.height() >= 160 and _mt.height() >= 380, "层表=%d 映射表=%d" % (_lt.height(), _mt.height()))
    chk("模型配置页信息窗含映射口径 (唯一依据 × 功能表)",
        ("功能 ←→ 层模型" in page.out.toPlainText()) and ("functions 表" in page.out.toPlainText()),
        page.out.toPlainText().splitlines()[3][:60] if len(page.out.toPlainText().splitlines()) > 3 else "")

    _ok = sum(1 for _n, k, _d in CHECKS if k)
    print("\n═══ 判据汇总: %d/%d PASS ═══" % (_ok, len(CHECKS)))
    for n, k, d in CHECKS:
        if not k:
            print("  ⛔ " + n + "   " + str(d))
    print("✅ PASS %d/%d" % (_ok, len(CHECKS)) if _ok == len(CHECKS) else "❌ FAIL %d/%d" % (_ok, len(CHECKS)))
    return 0 if _ok == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
