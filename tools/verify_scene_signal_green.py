#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_signal_green.py — 核「插拔场景(绿)」区域: 全绿 + 重名信号在本区域重新加载

老倪 2026-10-15 两条现场指令:
  「在插拔场景, 绿色信号, 没看到啊。你给我重启 信号分析的窗口, 加在topic」
  「为什么还有很多蓝色场景的信号也加在了? 插拔是绿色信号, 如果需要重名信号, 就要在绿色区域重新加载」

口径(离屏真建 CanoeGraphicWidget, 与现场同一个类/同一份真源 config/topics/scene_tags.json):
  ① 左树「🟢 插拔场景 …」组**逐行**都是绿 #2e8b57 (不许混进摆盘蓝/未分类白)
  ② 多场景共写源 (trace_live.json → sstrace.*) 的重名信号在绿组里**也有一份**(重新加载):
     光模块_x / 末端_x / 接触概率 / 时间_s / 帧 —— 旧口径按标签二选一 ⇒ 这些键全跑到蓝组, 插拔区看着缺一半
  ③ 动作调制器的输出 动作调制_mps (及上下游 前馈速度_mps / 安全边界_mps) 在绿组里且为绿
  ④ 蓝组「🔵 摆盘场景」里同名键各有一份且都是蓝 (两区域各自加载, 互不改色)
缺项即 FAIL 并打印实际取到的行, 不许编。
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

GREEN, BLUE = "#2e8b57", "#1f6feb"
MOD = ["动作调制_mps", "前馈速度_mps", "安全边界_mps"]
SHARED = ["光模块_x", "末端_x", "接触概率", "时间_s", "帧"]


def main() -> int:
    from PyQt5 import QtWidgets                                    # noqa: PLC0415
    import canoe_graphic as CG                                     # noqa: PLC0415

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = CG.CanoeGraphicWidget()
    w.resize(1700, 1000)
    w.show()
    groups, rows = [], {}

    def snap():
        groups.clear(); rows.clear()
        it = QtWidgets.QTreeWidgetItemIterator(w.tree)
        cur = None
        while it.value():
            item = it.value()
            lvl = 0
            p = item.parent()
            while p is not None:
                lvl += 1; p = p.parent()
            col = item.foreground(0).color().name()
            txt = item.text(0)
            if lvl == 0:
                cur = txt
                groups.append((txt, col))
                rows.setdefault(txt, [])
            elif cur is not None:
                rows[cur].append((lvl, txt, col))
            it += 1

    for _ in range(30):                        # 给数据源 30 拍 (~30s) 落地
        app.processEvents()
        time.sleep(1.0)
        snap()
        g = next((k for k in rows if "插拔" in k), None)
        if g and all(any(m in t for _, t, _ in rows[g]) for m in MOD):
            break

    print("=" * 84)
    print("实时监控·信号分析 目录树取证 — 插拔(绿)区域: 全绿 + 重名信号区域内重新加载")
    print("=" * 84)
    for g, c in groups:
        print("   组 %-66s %s (%d 行)" % (g[:66], c, len(rows.get(g, []))))

    gkey = next((k for k in rows if "插拔" in k), None)
    bkey = next((k for k in rows if "摆盘" in k), None)
    ok = bool(gkey)

    print("\n① 插拔(绿)组内配色分布:", Counter(c for _, _, c in rows.get(gkey or "", [])).most_common())
    bad = [(t, c) for _, t, c in rows.get(gkey or "", []) if c != GREEN]
    ok &= not bad
    print("   %s 组内非绿行 %d 条%s" % ("✅" if not bad else "❌", len(bad),
                                        ("  → " + str(bad[:6])) if bad else ""))

    def _flat(key):
        return {t.replace("● ", "", 1).replace("○ ", "", 1): c for _, t, c in rows.get(key or "", [])}

    gset, bset = _flat(gkey), _flat(bkey)

    print("\n② 重名信号在绿组里重新加载, 蓝组同名各有一份:")
    for s in SHARED:
        gh = [(k, v) for k, v in gset.items() if k == s or k.endswith("." + s)]
        bh = [(k, v) for k, v in bset.items() if k == s or k.endswith("." + s)]
        g_ok = bool(gh) and all(v == GREEN for _, v in gh)
        b_ok = bool(bh) and all(v == BLUE for _, v in bh)
        ok &= (g_ok and b_ok)
        print("   %s 绿 %-12s %-24s | %s 蓝 %s" % ("✅" if g_ok else "❌", s, gh[:1] or "不在绿组",
                                                   "✅" if b_ok else "❌", bh[:1] or "不在蓝组"))

    print("\n③ 动作调制器输出链在绿组:")
    for m in MOD:
        hit = [(k, v) for k, v in gset.items() if m in k]
        good = bool(hit) and all(v == GREEN for _, v in hit)
        ok &= good
        print("   %s %-14s %s" % ("✅" if good else "❌", m, hit[:1] or "不在绿组"))

    print("\n" + "=" * 84)
    print("结论: %s" % ("✅ 通过 — 插拔场景(绿)区域全绿, 重名信号已在绿区重新加载" if ok else "❌ 未通过"))
    print("=" * 84)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
