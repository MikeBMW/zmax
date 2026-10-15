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
    good6 = len(live) >= 3 and len(w.wave.items) >= 1        # ≥3 条真在动: 冻结的链路必须判失败
    ok &= good6
    print("   已选曲线 %d 条 · 曲线对象 %d 个 · 有起伏(非平线/非单点) %d 条" % (
        len(w.selected), len(w.wave.items), len(live)))
    for k, n, lo, hi in live[:6]:
        print("      ✅ %-24s n=%-4d y∈[%s, %s]" % (k, n, lo, hi))

    print("\n⑦ 与场景同步的时间轴线 + 标记线 (老倪: 「与场景同步的时间轴线呢?」)")
    try:
        _plots = list(getattr(w.wave, "plots", []) or [])
        _show = [i for i, pp in enumerate(_plots)
                 if getattr(pp.getAxis("bottom"), "style", {}).get("showValues", True)]
        _ax_ok = bool(_plots) and _show == [len(_plots) - 1]          # 只最下面一张显示时刻刻度
        # 标记线口径 = 跟 3D 播放游标 (pb.t_s), 不是"最新样本": 老倪要的是**和 3D 场景同一时刻**。
        # 3D 停播时竖线按设计留在"停下的那一刻"(_pb_last) ⇒ 那时按 _pb_last 校, 都没得校就算 N/A(不判失败)。
        _mk_ok, _mk_na, _pb = False, False, getattr(w.wave, "pb", None) or {}
        try:
            _scene_x = _pb.get("t_s") if _pb.get("fresh") else None
            _src_txt = "3D 播放游标"
            if _scene_x is None:
                _scene_x = (getattr(w.wave, "_pb_last", None) or {}).get("t_s")
                _src_txt = "3D 停播 → 竖线留在停下的那一刻"
            if getattr(w.wave, "marks", None) and _scene_x is not None:
                _mk_ok = abs(float(w.wave.marks[0].value()) - float(_scene_x)) < 1e-6
            elif not getattr(w.wave, "marks", None):
                _mk_ok = False
            else:
                _mk_na = True
        except Exception:                                                      # noqa: BLE001
            _mk_ok = False
        # 轴标签: 只要视图里有"场景源"(trace_live/engine_trace 这类带 时间_s 的)就必须是「场景时刻」
        _has_scene = any((w.store.bufs.get(k) is not None
                          and getattr(w.store.bufs[k], "scene", False)) for k in w.selected)
        _lab_ok = (any("场景时刻" in str(pp.getAxis("bottom").labelText) for pp in _plots)
                   if _has_scene else True)
        ok &= (_ax_ok and (_mk_ok or _mk_na) and _lab_ok)
        print("   %s 整列共用一条时间轴 (子图 %d 张, 显示刻度的是第 %s 张)"
              % ("✅" if _ax_ok else "❌", len(_plots), (_show[-1] + 1) if _show else "无"))
        print("   %s 标记线 == 场景时刻 %s  [%s]"
              % ("✅" if _mk_ok else ("⏭ N/A" if _mk_na else "❌"),
                 (round(float(_scene_x), 3) if _scene_x is not None else "—"), _src_txt))
        print("   %s 轴标签 = 场景时刻 (可切换绝对时刻)" % ("✅" if _lab_ok else "❌"))
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 取时间轴/标记线失败: %s" % _e)

    print("\n⑧ 子图自上而下顺序 == 树上勾选行自上而下顺序 (老倪: 「应该与信号上下顺序一致」)")
    try:
        _tree_order = []
        for _o in w._all_items():
            _k = _o.data(0, QtCore.Qt.UserRole)
            if _k and _o.checkState(0) == QtCore.Qt.Checked and _k not in _tree_order:
                _tree_order.append(_k)
        _plot_order = [k for k in w.wave.curves]
        _ord_ok = _plot_order == _tree_order
        ok &= _ord_ok
        print("   %s 树序   %s" % ("✅" if _ord_ok else "❌", [x.split(".")[-1] for x in _tree_order[:10]]))
        print("     子图序 %s" % [x.split(".")[-1] for x in _plot_order[:10]])
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 取顺序失败: %s" % _e)

    print("\n⑨ 信号表列: 帧龄 → 输出节点 (老倪: 「删除 列 帧龄, 增加输出这个信号的节点名称」)")
    try:
        _heads = [w.tree.headerItem().text(i) for i in range(w.tree.columnCount())]
        # 窗口已滚到别处也能查: 遍历所有行统计"输出节点"列是否都有值
        _tot = _named = _age_col = 0
        _samples = []
        for _o in w._all_items():
            _k = _o.data(0, QtCore.Qt.UserRole)
            if not _k:
                continue
            _tot += 1
            _c2 = _o.text(2)
            if _c2 and _c2 != "-":
                _named += 1
                if len(_samples) < 4:
                    _samples.append((_o.text(0)[:14], _c2))
            if "s" == _c2[-1:] and _c2[:-1].replace(".", "").isdigit():
                _age_col += 1                     # 这一列里还有"帧龄样式"的值 ⇒ 没删干净
        _ok9 = (_heads[2] == "输出节点") and ("帧龄" not in _heads) and _tot > 0 \
            and _named >= _tot * 0.9 and _age_col == 0
        ok &= _ok9
        print("   %s 表头 %s" % ("✅" if _ok9 else "❌", _heads))
        print("     有节点名的行 %d/%d · 列里残留帧龄值 %d" % (_named, _tot, _age_col))
        for _n, _node in _samples:
            print("       %-16s ← %s" % (_n, _node))
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 取列信息失败: %s" % _e)

    print("\n" + "=" * 88)
    print("结论: %s" % ("✅ 全过 — 插拔(绿)全绿 · 重名信号本区加载 · 蓝区折叠不打勾 · 主窗口有真波形" if ok else "❌ 未通过"))
    print("=" * 88)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
