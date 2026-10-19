#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_config_center_text_copy.py — 判据: 配置中心**所有文字都能用鼠标选中/复制**。

老倪 2026-10-19: 「为什么配置中心『选一个产品 =原子写回真源』这段话, 用鼠标选不了文字呢?
                 应该所有文字都可以被选中, 复制。你全都改一下」

判据 (全程离屏, 不写任何真源):
  ① 建页后: 页面内 **每一个 QLabel** 都带 TextSelectableByMouse + TextSelectableByKeyboard (0 例外)
  ② 点名的「选一个产品 = 原子写回真源 …」那行: 真·鼠标拖选 → selectedText() 拿到字 (不是只看 flags)
  ③ 八个页签逐个切过去 (含动态刷新的表格/特性页): 每页 QLabel 仍 100% 可选中
  ④ 后建的 QLabel (app 级 eventFilter 兜底): show+polish 之后自动可选中
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_center_text_copy.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_NEED = None


def _flags_ok(lb) -> bool:
    from PyQt5.QtCore import Qt
    f = lb.textInteractionFlags()
    return bool(f & Qt.TextSelectableByMouse) and bool(f & Qt.TextSelectableByKeyboard)


def _audit(widget, name, checks):
    from PyQt5.QtWidgets import QLabel
    lbs = widget.findChildren(QLabel)
    bad = [lb for lb in lbs if not _flags_ok(lb)]
    sample = " ; ".join((lb.text() or "")[:24].replace("\n", " ") for lb in bad[:4])
    checks.append(("①/③ %s: QLabel 全部可选中" % name,
                   not bad, "%d 个标签, 不可选中 %d 个%s" % (len(lbs), len(bad),
                                                          (" → " + sample) if bad else "")))


def main() -> int:
    from PyQt5.QtCore import Qt, QPoint
    from PyQt5.QtWidgets import QApplication, QLabel
    import veh6_config_page as V

    app = QApplication.instance() or QApplication([])
    page = V.ConfigCenterPage(model_page=None)
    page.resize(1600, 950)
    page.show()
    app.processEvents()

    checks = []
    _audit(page, "整页首次构建", checks)

    # ② 指名一行: 真·鼠标拖选 (QTest.mouseMove 不带按键状态 ⇒ 手工发带左键的 QMouseEvent)
    from PyQt5.QtCore import QEvent, QPointF
    from PyQt5.QtGui import QMouseEvent
    tgt = None
    for lb in page.findChildren(QLabel):
        if "产品配置 —— 产品标识" in (lb.text() or ""):
            tgt = lb
            break
    got = ""
    if tgt is not None:
        _i = page._tab_index_by_title("产品配置")
        if _i >= 0:
            page.tabs.setCurrentIndex(_i)
        app.processEvents()
        _y = max(1, tgt.height() // 2)
        _x0, _x1 = 2, min(tgt.width() - 2, 300)
        _send = lambda t, x, btn, held: QApplication.sendEvent(
            tgt, QMouseEvent(t, QPointF(x, _y), btn, held, Qt.NoModifier))
        _send(QEvent.MouseButtonPress, _x0, Qt.LeftButton, Qt.LeftButton)
        for _x in range(_x0 + 6, _x1, 6):
            _send(QEvent.MouseMove, _x, Qt.NoButton, Qt.LeftButton)
        _send(QEvent.MouseButtonRelease, _x1, Qt.LeftButton, Qt.NoButton)
        app.processEvents()
        got = (tgt.selectedText() or "").strip()
    checks.append(("② 「🏷 产品配置 —— 产品标识…」鼠标拖选真能选中文字",
                   tgt is not None and bool(got),
                   ("选中: 「%s」" % got[:34]) if got else ("找不到该行" if tgt is None else "拖选后 selectedText() 为空")))

    # ③ 八个页签逐个切
    for i in range(page.tabs.count()):
        page.tabs.setCurrentIndex(i)
        app.processEvents()
        _audit(page.tabs.widget(i), "页签[%d] %s" % (i, page.tabs.tabText(i)), checks)

    # ④ 后建的 QLabel (eventFilter 兜底)
    late = QLabel("动态新增的一行文字 (刷新后才出现)", page.tabs)
    late.show()
    app.processEvents()
    checks.append(("④ 后建 QLabel 自动可选中 (app 级 eventFilter 兜底)",
                   _flags_ok(late), "flags=%s" % int(late.textInteractionFlags())))

    # ⑤ 左树条目: 真按 Ctrl+C → 剪贴板拿到条目全文 (树不是 QLabel, 靠快捷键/右键菜单)
    from PyQt5.QtTest import QTest
    page.activateWindow()
    app.processEvents()
    it = page.tree.topLevelItem(2)                 # 3. 功能配置
    page.tree.setCurrentItem(it)
    page.tree.setFocus()
    app.processEvents()
    QApplication.clipboard().setText("__before__")
    QTest.keyClick(page.tree, Qt.Key_C, Qt.ControlModifier)
    app.processEvents()
    _clip = (QApplication.clipboard().text() or "").strip()
    _want_tree = page._item_text(it)
    checks.append(("⑤ 左树选中条目 Ctrl+C → 剪贴板 = 条目全文 (去掉 ⛔/✅ 标记)",
                   bool(_want_tree) and _clip == _want_tree,
                   "条目「%s」→ 剪贴板「%s」" % (_want_tree, _clip[:40])))

    # ⑥ 表格: 选中单元格 Ctrl+C → TSV (Excel 直接粘)
    _tbl = getattr(page, "fn_table", None)
    _ok6, _d6 = False, "本页没有可测表格"
    if _tbl is not None and _tbl.rowCount() >= 1:
        _i = page._tab_index_by_title("功能配置")
        if _i >= 0:
            page.tabs.setCurrentIndex(_i)
        app.processEvents()
        _tbl.selectRow(0)
        _tbl.setFocus()
        app.processEvents()
        QApplication.clipboard().setText("__before__")
        QTest.keyClick(_tbl, Qt.Key_C, Qt.ControlModifier)
        app.processEvents()
        _clip2 = (QApplication.clipboard().text() or "").strip()
        _exp = page._table_sel_text(_tbl).strip()
        _ok6 = bool(_exp) and _clip2 == _exp
        _d6 = "表格 %dx%d · 选中行 0 → 剪贴板「%s」" % (_tbl.rowCount(), _tbl.columnCount(), _clip2[:48])
    checks.append(("⑥ 表格选中单元格 Ctrl+C → TSV 复制", _ok6, _d6))

    # ⑦ 不许把已有复制行为弄坏: 底部信息窗 (QTextEdit) 里 Ctrl+C 仍复制它自己选中/全文
    page.out.setFocus()
    page.out.selectAll()
    app.processEvents()
    QApplication.clipboard().setText("__before__")
    QTest.keyClick(page.out, Qt.Key_C, Qt.ControlModifier)
    app.processEvents()
    _clip3 = (QApplication.clipboard().text() or "").strip()
    checks.append(("⑦ 信息窗 QTextEdit 的 Ctrl+C 照旧可用 (没被页级快捷键抢走)",
                   bool(_clip3) and _clip3 != "__before__" and _clip3 in (page.out.toPlainText() or "").strip(),
                   "剪贴板 %d 字 / 信息窗 %d 字" % (len(_clip3), len(page.out.toPlainText() or ""))))

    ok = 0
    for name, good, detail in checks:
        print(("  ✅ " if good else "  ❌ ") + name + "  · " + detail)
        ok += bool(good)
    print("\n%s %d/%d" % ("✅ PASS" if ok == len(checks) else "❌ FAIL", ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
