#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_signal_green.py — 核「插拔场景(绿)」区域: 全绿 · 重名信号本区加载 · 蓝区折叠且不打勾

老倪 2026-10-15 现场四条指令(逐条判):
  ① 「在插拔场景, 绿色信号, 没看到啊。你给我重启 信号分析的窗口, 加在topic」
  ② 「为什么还有很多蓝色场景的信号也加在了? 插拔是绿色信号, 如果需要重名信号, 就要在绿色区域重新加载」
  ③ 「摆盘的蓝色信号, 怎么也有 tick 小对号?」   → 非当前场景的那一份不可勾选、不带勾
  ④ 「蓝色区域你得折叠隐藏啊」                   → 非当前场景的场景组默认折叠隐藏

口径: 离屏真建 CanoeGraphicWidget (与现场同一个类/同一份真源 config/topics/scene_tags.json),
      逐行走树取 (层级, 文本, 前景色, 勾选态, 可勾选标志, 组展开态)。缺一项即 FAIL, 并打印实际取到的行。
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

GREEN = "#2e8b57"
MOD = ["动作调制_mps", "前馈速度_mps", "安全边界_mps"]
SHARED = ["光模块_x", "末端_x", "接触概率", "时间_s", "帧"]


def main() -> int:
    from PyQt5 import QtWidgets, QtCore                             # noqa: PLC0415
    import canoe_graphic as CG                                     # noqa: PLC0415

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = CG.CanoeGraphicWidget()
    w.resize(1700, 1000)
    w.show()
    grp, rows = {}, {}          # grp: 组名→{color,expanded}; rows: 组名→[(层,文本,色,勾选,可勾选)]

    def snap():
        grp.clear(); rows.clear()
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
            ck = item.checkState(0) == QtCore.Qt.Checked
            chk = bool(item.flags() & QtCore.Qt.ItemIsUserCheckable)
            if lvl == 0:
                cur = txt
                grp[txt] = {"color": col, "expanded": item.isExpanded()}
                rows.setdefault(txt, [])
            elif cur is not None:
                rows[cur].append((lvl, txt, col, ck, chk))
            it += 1

    for _ in range(30):                        # 给数据源 30 拍 (~30s) 落地
        app.processEvents()
        time.sleep(1.0)
        snap()
        g = next((k for k in rows if "插拔" in k), None)
        if g and all(any(m in t for _, t, _, _, _ in rows[g]) for m in MOD):
            break

    gkey = next((k for k in rows if "插拔" in k), None)
    bkey = next((k for k in rows if "摆盘" in k), None)
    print("=" * 88)
    print("实时监控·信号分析 目录树取证 — 插拔(绿)区域(老倪四条口径)")
    print("=" * 88)
    for g, m in grp.items():
        print("   组 %-62s %s %s (%d 行)" % (g[:62], m["color"],
                                             "展开" if m["expanded"] else "折叠", len(rows.get(g, []))))

    def _rows(key, pat=lambda t: True):
        out = []
        for _lvl, t, c, ck, chk in rows.get(key or "", []):
            t2 = t.replace("● ", "", 1).replace("○ ", "", 1)
            if pat(t2):
                out.append((t2, c, ck, chk))
        return out

    ok = bool(gkey)

    print("\n① 绿区逐行全绿 (不许混进摆盘蓝 / 未分类白)")
    dist = Counter(c for _, _, c, _, _ in rows.get(gkey or "", []))
    bad = [(t, c) for _, t, c, _, _ in rows.get(gkey or "", []) if c != GREEN]
    ok &= (not bad) and bool(dist)
    print("   配色 %s · 非绿 %d 条 %s" % (dist.most_common(), len(bad),
                                         ("→ " + str(bad[:5])) if bad else "✅"))

    print("\n② 重名信号本区重新加载: 绿区各一份(绿) + 蓝区同名各一份(蓝)")
    for s in SHARED:
        g1 = _rows(gkey, lambda t, s=s: t == s or t.endswith("." + s))
        b1 = _rows(bkey, lambda t, s=s: t == s or t.endswith("." + s))
        good = bool(g1) and bool(b1) and all(c == GREEN for _, c, _, _ in g1) and all(
            c != GREEN for _, c, _, _ in b1)
        ok &= good
        print("   %s %-12s 绿区 %-22s | 蓝区 %s" % ("✅" if good else "❌", s,
                                                    str(g1[:1]) if g1 else "缺",
                                                    str(b1[:1]) if b1 else "缺"))

    print("\n③ 蓝区(非当前场景)不打勾、也不可勾选")
    bck = [t for t, _c, ck, _ch in _rows(bkey) if ck]
    bchk = [t for t, _c, _ck, ch in _rows(bkey) if ch]
    good3 = (not bck) and (not bchk)
    ok &= good3
    print("   蓝区已勾选 %d 条%s · 仍可勾选 %d 条%s"
          % (len(bck), (" → " + str(bck[:4])) if bck else " ✅", len(bchk),
             (" → " + str(bchk[:4])) if bchk else " ✅"))

    print("\n④ 蓝区默认折叠隐藏, 绿区(当前场景)保持展开")
    bexp = (grp.get(bkey or "") or {}).get("expanded")
    gexp = (grp.get(gkey or "") or {}).get("expanded")
    good4 = (bexp is False) and (gexp is True)
    ok &= good4
    print("   %s 蓝区 expanded=%s · %s 绿区 expanded=%s"
          % ("✅" if bexp is False else "❌", bexp, "✅" if gexp is True else "❌", gexp))

    print("\n⑤ 动作调制器输出链在绿区且为绿")
    for m in MOD:
        hit = [(t, c) for t, c, _ck, _ch in _rows(gkey, lambda t, m=m: m in t)]
        good = bool(hit) and all(c == GREEN for _, c in hit)
        ok &= good
        print("   %s %-14s %s" % ("✅" if good else "❌", m, hit[:1] or "不在绿区"))

    print("\n⑥ 主窗口真的有波形 (老倪: 「信号分析, 主窗口, 没有波形信号啊」)")
    live = []
    for k in w.selected:
        b = w.store.bufs.get(k)
        if b is None or getattr(b, "n", 0) < 2:
            continue
        _t, _v = b.arrays()
        if len(_v) > 1 and max(_v) != min(_v):
            live.append((k, len(_v), round(min(_v), 4), round(max(_v), 4)))
    good6 = len(live) >= 1 and len(w.wave.items) >= 1
    ok &= good6
    print("   已选曲线 %d 条 · 曲线对象 %d 个 · 有起伏(非平线/非单点) %d 条" % (
        len(w.selected), len(w.wave.items), len(live)))
    for k, n, lo, hi in live[:6]:
        print("      ✅ %-24s n=%-4d y∈[%s, %s]" % (k, n, lo, hi))

    print("\n" + "=" * 88)
    print("结论: %s" % ("✅ 全过 — 插拔(绿)全绿 · 重名信号本区加载 · 蓝区折叠不打勾 · 主窗口有真波形" if ok else "❌ 未通过"))
    print("=" * 88)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
