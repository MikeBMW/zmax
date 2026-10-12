#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_config_tree_width.py — 判据: 配置中心左侧栏「适配宽度 + 可拖 + 记得住」

老倪 2026-10-12: 「你看现在的配置中心，左侧栏，无法更改宽度，字体都挡住了。改适配宽度」

改前真因(离屏真渲染实测): 树没设最小宽度 ⇒ 分割条在窄布局下把左栏压到 **71px**(内容需求 174px+),
文本被截; 且句柄只有 4px, 不好拖。

判据(全部真渲染, 不靠读代码):
  ① 需求宽度按**内容实测**算: need == 最长条目(含缩进) + 图标/边框/滚动条/余量; 且 ≥150
  ② 初始宽度 = 需求宽度, 且**不被截**(最长条目像素 ≤ 可用宽度)
  ③ **压不没**: 强行 setSizes([1, 50]) 后 左栏仍 ≥ 需求宽度(childrenCollapsible=False + 最小宽度)
  ④ **可拖**: 把分隔条拖到 320 ⇒ 左栏真的变 320(右栏让出), 且落盘记住
  ⑤ **记得住**: 新开一个页面 ⇒ 自动沿用 320(而不是回到默认)
  ⑥ 右栏仍可用: 任何情况下右栏宽度 ≥ 400px(别为了左栏把工作区挤没)
  ⑦ 文本不截: 每个窗口/拖动状态下, 最长条目都能完整显示
用法: gui-venv311/bin/python tools/verify_config_tree_width.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtCore import QSettings                                                              # noqa: E402
from PyQt5.QtWidgets import QApplication, QSplitter                                             # noqa: E402

OK, FAIL = [], []


def ck(name, cond, ev=""):
    (OK if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("   ← " + str(ev)) if ev else ""))
    return bool(cond)


def worst_px(tree):
    fm = tree.fontMetrics()
    ind = max(12, tree.indentation())
    best = (0, "")
    stack = [(tree.topLevelItem(i), 0) for i in range(tree.topLevelItemCount())]
    while stack:
        it, d = stack.pop()
        if it is None:
            continue
        px = d * ind + fm.horizontalAdvance(it.text(0))
        if px > best[0]:
            best = (px, it.text(0))
        for i in range(it.childCount()):
            stack.append((it.child(i), d + 1))
    return best


def main():
    import veh6_config_page as V                                                                # noqa: E402
    app = QApplication.instance() or QApplication([])
    st = QSettings("ZMAX", "Console")
    KEY = "config_center/tree_width"
    prev = st.value(KEY, None)
    try:
        st.remove(KEY)                                  # 从"没记过"起跑
        pg = V.ConfigCenterPage()
        pg.show()
        for _ in range(3):
            app.processEvents()
        sp = pg.findChild(QSplitter)
        need = pg._tree_need_width()
        wpx, wtext = worst_px(pg.tree)
        ck("① 需求宽度=按内容实测(≥150 且 ≥最长条目+56)", need >= 150 and need >= wpx + 56,
           "need=%d · 最长 '%s'=%dpx" % (need, wtext, wpx))
        ck("② 初始左栏 = 需求宽度", abs(pg.tree.width() - need) <= 2, "tree=%d need=%d" % (pg.tree.width(), need))
        ck("②b 初始不截字", wpx <= pg.tree.viewport().width(),
           "%dpx ≤ %dpx" % (wpx, pg.tree.viewport().width()))

        # ③ 压不没
        sp.setSizes([1, 50])
        for _ in range(3):
            app.processEvents()
        ck("③ 强压(setSizes[1,50])后左栏仍 ≥ 需求宽度", pg.tree.width() >= need - 2,
           "tree=%d need=%d sizes=%s" % (pg.tree.width(), need, sp.sizes()))

        # ④ 可拖宽并记住(目标 = 需求宽度+60 ⇒ 与 DPI 无关)
        #    注: 离屏下页面被"最小尺寸"顶着, 没有余量可拖 ⇒ 先把页面放到比最小尺寸更宽(2200),
        #    这才是真机最大化窗口的形态(有余量), 拖拽才可测。
        tgt = need + 60
        # 页面要放到"最小尺寸 + 300"余量才拖得动(右栏最小值随 DPI 变, 不能写死 2200)
        _w = need + pg.tabs.minimumSizeHint().width() + 300
        pg.setMinimumWidth(_w)
        pg.resize(_w, 900)
        for _ in range(3):
            app.processEvents()
        sp.setSizes([tgt, max(1, sp.width() - tgt)])
        for _ in range(2):
            app.processEvents()
        pg._on_tree_split_moved(tgt, 0)                 # 等价于用户拖完(触发落盘)
        ck("④ 拖宽到 需求+60 生效(窗口有余量时)", abs(pg.tree.width() - tgt) <= 2,
           "tree=%d tgt=%d sp=%s sp_w=%d" % (pg.tree.width(), tgt, sp.sizes(), sp.width()))
        ck("④b 宽度已落盘", int(st.value(KEY, 0) or 0) == pg.tree.width(), st.value(KEY))
        sp.setSizes([100, max(1, sp.width() - 100)])    # 试着拖到比内容还窄
        for _ in range(2):
            app.processEvents()
        ck("④c 拖到比内容窄(100)被拒, 仍 ≥ 需求", pg.tree.width() >= need,
           "tree=%d need=%d" % (pg.tree.width(), need))

        # ⑤ 新开页面沿用(同样放到有余量的宽度)
        pg2 = V.ConfigCenterPage()
        pg2.setMinimumWidth(_w)
        pg2.resize(_w, 900)
        pg2.show()
        for _ in range(3):
            app.processEvents()
        ck("⑤ 新开页面沿用记过的宽度", abs(pg2.tree.width() - tgt) <= 2, "tree=%d" % pg2.tree.width())

        # ⑥⑦ 右栏可用 + 不截字
        sp2 = pg2.findChild(QSplitter)
        ck("⑥ 右栏仍 ≥400px", (sp2.sizes()[1] if sp2 else 0) >= 400, sp2.sizes() if sp2 else None)
        ck("⑦ 拖后仍不截字", worst_px(pg2.tree)[0] <= pg2.tree.viewport().width(),
           "%dpx ≤ %dpx" % (worst_px(pg2.tree)[0], pg2.tree.viewport().width()))
    finally:
        if prev is None:
            st.remove(KEY)
        else:
            st.setValue(KEY, prev)
        st.sync()
    print("\n%s  (%d PASS / %d FAIL)" % ("★ 全部通过 ✓" if not FAIL else "✗ 有失败项", len(OK), len(FAIL)))
    return 0 if not FAIL else 2


if __name__ == "__main__":
    raise SystemExit(main())
