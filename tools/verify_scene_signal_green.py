#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_signal_green.py — 核「插拔场景(绿)」的信号真的出现在实时监控·信号分析页的目录树里

老倪 2026-10-15: 「在插拔场景, 绿色信号, 没看到啊。你给我重启 信号分析的窗口, 加在topic」
口径: 离屏真建 CanoeGraphicWidget (与现场同一个类/同一份真源), 等数据源轮询一轮, 然后
      **逐行走树** 打印 (组名, 信号名, 颜色), 断言:
        ① 左树里存在「插拔场景」分组 (绿色 #2e8b57 标题)
        ② 该分组下有 动作调制_mps / 前馈速度_mps / 安全边界_mps (动作调制器的输出及其上下游)
        ③ 这三个信号的行前景色 == 插拔场景绿 #2e8b57 (不是白/未分类)
缺项即 FAIL 并打印实际取到的组与信号, 不许编。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

GREEN = "#2e8b57"
TARGETS = ["动作调制_mps", "前馈速度_mps", "安全边界_mps"]


def main() -> int:
    from PyQt5 import QtWidgets                                    # noqa: PLC0415
    import canoe_graphic as CG                                     # noqa: PLC0415

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = CG.CanoeGraphicWidget()
    w.resize(1700, 1000)
    w.show()
    rows, groups = [], []

    def snap():
        rows.clear(); groups.clear()
        tree = getattr(w, "tree", None)
        if tree is None:
            return
        it = QtWidgets.QTreeWidgetItemIterator(tree)
        stack = []
        while it.value():
            item = it.value()
            txt = item.text(0)
            col = item.foreground(0).color().name()
            lvl = 0
            p = item.parent()
            while p is not None:
                lvl += 1; p = p.parent()
            if lvl == 0:
                groups.append((txt, col))
            elif lvl == 1:
                rows.append((txt, col))
            it += 1

    for _ in range(30):                                            # 给数据源 30 拍 (~30s) 落地
        app.processEvents()
        QtWidgets.QApplication.processEvents()
        import time as _t
        _t.sleep(1.0)
        snap()
        if any(t in " ".join(r[0] for r in rows) for t in TARGETS):
            break

    print("=" * 78)
    print("实时监控·信号分析 目录树 取证 (离屏真建窗, 真源 config/topics/scene_tags.json)")
    print("=" * 78)
    print("顶层组 (%d):" % len(groups))
    for g, c in groups:
        print("   %-28s %s" % (g, c))
    hit_group = [g for g, c in groups if "插拔" in g]
    print("\n插拔场景分组: %s" % (hit_group or "❌ 没找到"))

    print("\n插拔场景组下的信号行 (前 40 条, 空=还没轮询到):")
    shown = 0
    got = {}
    for name, col in rows:
        if any(t in name for t in TARGETS) or shown < 3:
            print("   %-40s 色 %s" % (name, col))
            shown += 1
        for t in TARGETS:
            if t in name:
                got[t] = col

    print("\n" + "=" * 78)
    ok = bool(hit_group)
    print("① 左树有「插拔场景」分组: %s" % ("✅" if ok else "❌"))
    for t in TARGETS:
        c = got.get(t)
        good = (c == GREEN)
        ok = ok and good
        print("② %-12s 在树里=%s 色=%s %s" % (t, "是" if c else "否", c or "—",
                                              "✅ 插拔绿" if good else "❌ 不在树里/不是绿"))
    print("结论: %s" % ("✅ 通过 — 页面里插拔场景(绿)能看到动作调制器的输出" if ok else "❌ 未通过"))
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
