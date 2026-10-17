#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_gravity_signals.py — 核「万有引力表」的力**真的**进了插拔场景的信号分析窗口

老倪 2026-10-16: 「将万有引力的所有信号, 都加到插拔场景的信号分析窗口, 我要运行检查」
                + 「集中显示力的大小」/「力的大小, 和力的实部即可」

判定口径 (每条都要真跑真读, 判据自己不看图、不靠肉眼):
  ① 信号全集: 表里**真实存在的每一格**都在 (8 项 × L2/L3/L4/L5 × (力大小·实部) + 8 行合力×2 +
     4 列合力×2 + 总合力×2 + 标量 4 = 94), 一个不多一个不少
  ② 口径: 力的大小 == 表算的 |F|; 实部 == 表算的 q[0] (=|F|/u_ref); 逐格对账 (1e-9)
  ③ 合力可加: 总合力实部 == 全表 32 格实部之和 (逐位相加, 老倪要按数字对账)
  ④ 场景: 每个页面键 gravity.* 打标 = 插拔场景 (绿 #2e8b57) —— 不许掉进"基础场景/白"
  ⑤ 接线: canoe_graphic.HOST_SOURCES 有 gravity 源 · OUT_NODE_RULES 认 gravity.* · DEFAULT_3D 勾了它
  ⑥ 在发: 源文件新鲜 (≤5s) + 隔一拍时间_s 前进且力值在变 (不是定格)
  ⑦ 页面真建: 离屏建 CanoeGraphicWidget → "插拔场景"组下真有这 94 行, 且当前场景行**可勾选**
     (老倪要能直接勾上画波形); 94 条一条不少 (防 flatten_json 48 键上限静默截断)
"""
from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

FRAME = os.path.join(ROOT, "zmax_data", "ss_live", "gravity_trace.json")
GREEN = "#2e8b57"
FULL_SCENE = "插拔场景"
RES = []
N_SIG = 8 * 4 * 2 + 8 * 2 + 4 * 2 + 2 + 4          # 64 + 16 + 8 + 2 + 4 = 94


def chk(name, ok, detail=""):
    RES.append((bool(ok), name, detail))
    print("%s %s%s" % ("✅" if ok else "❌", name, ("  · " + detail) if detail else ""))
    return ok


def _frame():
    with open(FRAME, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    import gravity_table as GT

    f = GT.GravityField()
    rows = f.rows
    s = _frame().get("s") or {}

    # ── ① 全集 ──
    want = set()
    for r in rows:
        st = r["stage"]
        for lk, _n in GT.LAYERS:
            c = r["cells"].get(lk) or {}
            if c.get("mag") is not None:
                want.add("%s·%s 力大小_mps" % (st, lk))
            if c.get("q"):
                want.add("%s·%s 实部" % (st, lk))
        want.add("%s·合力 力大小_mps" % st)
        want.add("%s·合力 实部" % st)
    for lk, _n in GT.LAYERS:
        want.add("列%s·合力 力大小_mps" % lk)
        want.add("列%s·合力 实部" % lk)
    want |= {"总合力 力大小_mps", "总合力 实部", "参考速度 u_ref_mps", "一致度", "主力层号", "主力项序号"}
    miss = sorted(want - set(s))
    extra = sorted(set(s) - want)
    chk("① 信号全集 = 表上每一格 (共 %d 条)" % N_SIG, len(s) == N_SIG and not miss and not extra,
        "帧内 %d 条 · 缺 %s · 多 %s" % (len(s), miss[:3] or "无", extra[:3] or "无"))

    # ── ② 口径逐格对账 ──
    bad = []
    for r in rows:
        st = r["stage"]
        for lk, _n in GT.LAYERS:
            c = r["cells"].get(lk) or {}
            if c.get("mag") is not None:
                k = "%s·%s 力大小_mps" % (st, lk)
                if abs(float(s.get(k, -9)) - float(c["mag"])) > 1e-9:
                    bad.append(k)
            if c.get("q"):
                k2 = "%s·%s 实部" % (st, lk)
                if abs(float(s.get(k2, -9)) - float(c["q"][0])) > 1e-9:
                    bad.append(k2)
    chk("② 力的大小=|F| · 实部=|F|/u_ref (逐格 1e-9 对账)", not bad, "不一致 %d 项 %s" % (len(bad), bad[:3]))

    # ── ③ 合力可加 (总合力实部 == 全表格实部之和) ──
    _sum = sum(float(s.get("%s·%s 实部" % (r["stage"], lk), 0.0)) for r in rows for lk, _n in GT.LAYERS)
    chk("③ 总合力实部 == 全表 32 格实部之和 (可逐位相加对账)",
        abs(_sum - float(s.get("总合力 实部", 0.0))) < 1e-6,
        "Σ格=%.9f vs 帧=%.9f" % (_sum, float(s.get("总合力 实部", -1))))

    # ── ④ 场景标签 ──
    import sig_scene_tags as SST
    _bad = [k for k in s if SST.tag("gravity." + k) != FULL_SCENE]
    _col = SST.color("gravity." + "总合力 实部")
    chk("④ 全部 %d 条打标=插拔场景 · 绿 %s" % (len(s), GREEN), not _bad and _col == GREEN,
        "非插拔 %s · 取色 %s" % (_bad[:3] or "无", _col))

    # ── ⑤ 页面接线 ──
    import canoe_graphic as CG
    _hs = dict((p, r) for p, r in CG.HOST_SOURCES)
    _ok_src = _hs.get("gravity") == "zmax_data/ss_live/gravity_trace.json"
    _ok_node = any(pre == "gravity." for pre, _n in CG.CanoeGraphicWidget.OUT_NODE_RULES)
    _ok_def = any(str(k).startswith("gravity.") for k in CG.CanoeGraphicWidget.DEFAULT_3D)
    chk("⑤ 页面接线: HOST_SOURCES + 输出节点 + 首屏默认曲线", _ok_src and _ok_node and _ok_def,
        "源=%s 节点=%s 默认=%s" % (_ok_src, _ok_node, _ok_def))

    # ── ⑥ 在发 + 在动 ──
    _age = time.time() - os.path.getmtime(FRAME)
    t1, a1 = _frame().get("时间_s"), float(s.get("总合力 实部", 0.0))
    time.sleep(2.2)
    s2 = _frame()
    t2, a2 = s2.get("时间_s"), float((s2.get("s") or {}).get("总合力 实部", 0.0))
    chk("⑥ 源在发 (帧龄 ≤5s) 且时间/力值在推进", _age <= 5.0 and t2 > t1 and abs(a2 - a1) > 1e-9,
        "帧龄 %.1fs · 时间_s %.1f→%.1f · 总合力实部 %.4f→%.4f" % (_age, t1, t2, a1, a2))

    # ── ⑦ 离屏真建页面: 94 行进插拔场景组且可勾选 ──
    from PyQt5 import QtWidgets, QtCore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = CG.CanoeGraphicWidget()
    w.resize(1700, 1000)
    w.show()
    _t0 = time.time()
    while time.time() - _t0 < 25:
        app.processEvents()
        if sum(1 for k in w.store.keys() if k.startswith("gravity.")) >= N_SIG:
            break
        time.sleep(0.3)
    _in_store = [k for k in w.store.keys() if k.startswith("gravity.")]
    grp = None
    it = QtWidgets.QTreeWidgetItemIterator(w.tree)
    while it.value():
        i = it.value()
        if i.data(0, QtCore.Qt.UserRole + 1) == "scene:" + FULL_SCENE:
            grp = i
            break
        it += 1
    _rows, _checkable, _checked, _keys = [], 0, 0, set()
    _want_set = set(want)
    if grp is not None:
        for j in range(grp.childCount()):
            c = grp.child(j)
            _raw = c.data(0, QtCore.Qt.UserRole)
            _k = str(_raw) if _raw else c.text(0)
            # 行上存的是页面键 (带来源前缀) 或"去前缀的短名"(列表显示用) ⇒ 两种都归一后与期望键集比
            for _cand in (_k, _k.split(".", 1)[1] if "." in _k else _k, c.text(0)):
                if _cand in _want_set:
                    _rows.append(c); _keys.add(_cand)
                    if c.flags() & QtCore.Qt.ItemIsUserCheckable:
                        _checkable += 1
                    if c.checkState(0) == QtCore.Qt.Checked:
                        _checked += 1
                    break
    chk("⑦ 页面: store 进 94 条 (未被 48 键上限截断)", len(_in_store) == N_SIG, "store %d 条" % len(_in_store))
    chk("⑧ 页面: 「插拔场景」组下有这 94 行且可勾选 (当前场景)", len(_keys) == N_SIG and _checkable == N_SIG,
        "组内命中 %d 行 · 可勾选 %d · 已勾 %d · 缺 %s"
        % (len(_keys), _checkable, _checked, sorted(_want_set - _keys)[:4] or "无"))
    if grp is not None:
        chk("⑨ 页面: 插拔场景组展开 (一眼看到, 不用点开)", grp.isExpanded(), "expanded=%s" % grp.isExpanded())

    _bad = [x for x in RES if not x[0]]
    print("\n%s 共 %d 条 · 通过 %d · 失败 %d" % ("🟢 PASS" if not _bad else "🔴 FAIL", len(RES), len(RES) - len(_bad), len(_bad)))
    for _b in _bad:
        print("   ❌ %s · %s" % (_b[1], _b[2]))
    return 0 if not _bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
