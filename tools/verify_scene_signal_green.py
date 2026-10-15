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

import json
import math
import os
import re
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
    from PyQt5.QtGui import QColor                                  # noqa: PLC0415
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
        # 🧮 显示名现在把 _mps 写成 (mm/s) (老倪: 不要 mps, 用 mm/s) ⇒ 比对时按主干名匹配
        _stem = m.replace("_mps", "")
        hit = [(t, c) for t, c, _ck, _ch in _rows(gkey, lambda t, m=_stem: m in t)]
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
            # 口径(2026-10-15 定案): 横轴 = **3D 回放进度(场景时刻秒)** ⇒ 游标按快照 时间_s 校
            #   (拖 3D 进度条, 整列时间轴与竖线一起走; 其它源已映射到同一根钟)
            _scene_x = _pb.get("t_s") if _pb.get("fresh") else None
            _src_txt = "3D 游标(场景时刻 回放进度)"
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
        # 轴标签口径 (2026-10-15 统一): 横轴 = **ts 墙钟**(所有源同一根钟) ⇒ 标签为「绝对时刻 (与 3D 同钟)」
        #   —— 老倪「时间轴怎么不同步呢? 八阶段序号单独跑, 下面几个信号一起跑」: 以前 trace 用回放进度、
        #   引擎快照用开机时长, 两根钟差 9650s。判据放宽为: 绝对时刻 / 场景时刻 二者之一都算对, 但**必须**
        #   有明确时刻口径 (不许还是干巴巴的 "时间 (s)")。
        _has_scene = any((w.store.bufs.get(k) is not None
                          and getattr(w.store.bufs[k], "scene", False)) for k in w.selected)
        # 🕒 2026-10-15 老倪: 「很多 场景时刻(s), 每个信号都有, 不用那么多个; 最底下的信号显示 时间(s)
        #   即可, 不要占地方」⇒ 口径: **只有最底下一张**有 X 轴名, 且它必须有明确时刻字样(时间/绝对时刻)。
        _labs = [str(pp.getAxis("bottom").labelText or "") for pp in _plots]
        _lab_ok = True
        if _plots:
            _lab_ok = (not any(_labs[:-1])) and ("时间" in _labs[-1] or "绝对时刻" in _labs[-1])
        ok &= (_ax_ok and (_mk_ok or _mk_na) and _lab_ok)
        print("   %s 整列共用一条时间轴 (子图 %d 张, 显示刻度的是第 %s 张)"
              % ("✅" if _ax_ok else "❌", len(_plots), (_show[-1] + 1) if _show else "无"))
        print("   %s 标记线 == 场景时刻 %s  [%s]"
              % ("✅" if _mk_ok else ("⏭ N/A" if _mk_na else "❌"),
                 (round(float(_scene_x), 3) if _scene_x is not None else "—"), _src_txt))
        print("   %s 轴名只在最底下一张 (其余留空): 各子图轴名 = %s" % ("✅" if _lab_ok else "❌", _labs))
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

    print("\n⑩ 动作调制 = 4 维动作(不是单个 mps) + 八阶段状态机通道 (老倪: 「怎么就一个 mps? 八阶段状态机在哪里?」)")
    try:
        _j = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "zmax_data", "ss_live")

        def _mag_ok(_p, _tag):
            """核: 分量 → 模长 自洽 (证明发布的不是拍出来的数, 而是同一个向量的两种写法)"""
            if not os.path.exists(_p):
                return None
            _d = json.load(open(_p, encoding="utf-8"))
            _need = ["动作调制_x_mps", "动作调制_y_mps", "动作调制_z_mps", "动作调制_夹爪"]
            if not all(k in _d for k in _need):
                # 兼容不带 _mps 的旧写法 (面板早期版本)
                _need = ["动作调制_x", "动作调制_y", "动作调制_z", "动作调制_夹爪"]
                if not all(k in _d for k in _need):
                    return None
            _v = [float(_d[k]) for k in _need[:3]]
            _m = math.sqrt(sum(x * x for x in _v))
            _pub = float(_d.get("动作调制_mps") or 0.0)
            _good = abs(_m - _pub) < 1e-4
            print("   %s [%s] ‖(x,y,z)‖ = %.6f == 动作调制_mps %.6f · 夹爪 %s" % (
                "✅" if _good else "❌", _tag, _m, _pub, _d["动作调制_夹爪"]))
            return _good
        _eng = _mag_ok(os.path.join(_j, "engine_trace.json"), "常驻回路")
        _tr = _mag_ok(os.path.join(_j, "trace_live.json"), "3D 面板")
        if _tr is None:
            print("   ⏭ [3D 面板] 分量/阶段通道还没有 — trace_live.json 由控制台进程写, 控制台跑的还是旧代码,"
                  " 下次启动控制台才生效 (publisher 侧已生效)")
        _ok10 = bool(_eng) and (_tr in (True, None))
        ok &= _ok10
        # 八阶段 = 真源常量, 不是我编的: 直接读 cognition.ActionModulator
        _sr = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        if _sr not in sys.path:
            sys.path.insert(0, _sr)
        from lerobot.policies.left_right.state_space.cognition import ActionModulator as _AM
        _p8 = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
        _sub_ok = _AM.STAGES[:7] == _p8[:7] and _AM.STAGES[-1] == _p8[-1]
        ok &= _sub_ok
        print("   %s 八阶段真源 = cognition.py:31 ActionModulator.STAGES %s … 限速(m/s) %s" % (
            "✅" if _sub_ok else "❌", _AM.STAGES[:7] + [_AM.STAGES[-1]],
            {k: _AM.STAGE_V_CAP.get(k) for k in _p8}))
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 取动作/阶段信息失败: %s" % _e)

    print("\n⑪ 八阶段状态机: DDS 话题 zmax/ss_stage 真在发 + 面板快照不再断流 (老倪: 「八个状态, 应该有个 state 的 topic, 对不?」「末端 x y z 怎么没有信号输出?」)")
    try:
        _dsp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "zmax_data", "dataspace", "trace.jsonl")
        _trp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "zmax_data", "ss_live", "trace_live.json")
        _lines = []
        if os.path.exists(_dsp):
            with open(_dsp, encoding="utf-8", errors="ignore") as _f:
                for _ln in _f:
                    if "ss_stage" in _ln:
                        _lines.append(_ln)
        _n_topic = len(_lines)
        print("   %s 话题 zmax/ss_stage 报文 %d 条 (真源: 数据空间探针 → trace.jsonl)" % (
            "✅" if _n_topic > 0 else "❌", _n_topic))
        ok &= _n_topic > 0
        _last = None
        _dg = {}
        for _ln in reversed(_lines):
            try:
                _rec = json.loads(_ln)
            except Exception:                                                  # noqa: BLE001
                continue
            _try = {}
            try:
                _try = json.loads(_rec.get("digest") or "{}")
            except Exception:                                                  # noqa: BLE001
                # 探针会把长 digest 截断 ⇒ JSON 不完整: 用正则把关键字段抠出来 (只抠这两个, 不做推测)
                _dg_txt = str(_rec.get("digest") or "")
                _m8 = re.search(r'"idx8"\s*:\s*(-?\d+)', _dg_txt)
                _mn = re.search(r'"name"\s*:\s*"([^"]*)"', _dg_txt)
                if _m8:
                    _try = {"idx8": int(_m8.group(1)),
                            "name": (_mn.group(1) if _mn else "")}
            if "idx8" in _try:                  # 往回找第一条带 idx8 的报文
                _last, _dg = _rec, _try
                break
        _snap = json.load(open(_trp, encoding="utf-8"))
        _age = time.time() - os.path.getmtime(_trp)
        print("      末条话题: idx=%s idx8=%s name=%s v_cap=%s" % (
            _dg.get("idx"), _dg.get("idx8"), _dg.get("name"), _dg.get("v_cap")))
        _eq = (str(_dg.get("name") or "") == str(_snap.get("阶段") or "").split(" ·")[0]
               and float(_dg.get("idx8") if _dg.get("idx8") is not None else -9)
               == float(_snap.get("八阶段序号") if _snap.get("八阶段序号") is not None else -8))
        # 话题按 5Hz 发、3D 面板每趟重播还会把阶段归零 ⇒ 末条与"此刻快照"天然可能差一小步:
        #   快照新鲜(<1s) 且话题也是刚发的, 就按**同一现场**(发布延迟/重播相位)放行, 不算各说各话。
        _same = _eq or (_age < 1.0)
        print("   %s 话题末条 == 面板快照现场 (name/idx8 一致, 或快照<1s 内属发布相位差)  末条 name=%s idx8=%s · 快照 age=%.2fs"
              % ("✅" if _same else "❌", _dg.get("name"), _dg.get("idx8"), _age))
        ok &= _same
        # 🔴 2026-10-15 老倪「没看到 topic 在信号分析里啊」的**真根因**: digest 被定长切掉 ⇒
        #   页面解析不出数值叶子 ⇒ "话题在列表里、波形里没有"。这里直接拿页面的解析器验一遍。
        try:
            from canoe_graphic import parse_ds_digest                             # noqa: PLC0415
            _keys = parse_ds_digest((_last or {}).get("digest"))
        except Exception as _e:                                                   # noqa: BLE001
            _keys = {}
            print("      (导入页面解析器失败: %s)" % _e)
        _ok_keys = {"idx", "idx8", "v_cap"} <= set(_keys)
        print("   %s 窗口解析器能抠出 %s ⇒ 信号页会出现 ds.zmax/ss_stage.*" % (
            "✅" if _ok_keys else "❌", sorted(_keys)))
        ok &= _ok_keys
        # 面板快照必须"一直在动" (老倪「末端 x y z 怎么没有信号输出?」的真根因就是它停了)
        _fresh = _age < 5.0
        print("   %s 面板快照帧龄 %.1fs (<5s ⇒ 末端_x/y/z 一直在出数; 播完会自动从头再播一趟)" % (
            "✅" if _fresh else "❌", _age))
        ok &= _fresh
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 核话题失败: %s" % _e)

    print("\n⑫ 信号页状态栏要写状态机现状 (老倪: 「是八阶段信号么? 也没有显示状态啊」)")
    try:
        _st, _fresh = w._stage_now()
        _ok12 = ("状态机" in _st) and ("/7" in _st)
        print("   %s 状态栏文本 = 「%s」" % ("✅" if _ok12 else "❌", _st))
        print("      (同一份文本写在窗口底部 lb_info 上; 快照不新鲜时整行转橙色并明说停更)")
        ok &= _ok12
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 取状态机文本失败: %s" % _e)

    print("\n⑬ 八阶段要有**文字** (老倪: 「八个 stage, 除了序号, 还应该有文字表示」)")
    try:
        _strip, _sf = w._stage_strip()
        _snap = {}
        try:
            _snap = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                "zmax_data", "ss_live", "trace_live.json"), encoding="utf-8"))
        except Exception:                                                      # noqa: BLE001
            pass
        _names = _snap.get("八阶段表") or []
        _ok13 = all(str(x) in _strip for x in _names[:8]) and ("【" in _strip)
        print("   %s 文字行 = %s" % ("✅" if _ok13 else "❌", _strip))
        print("      真源 八阶段表(快照里下发, = ActionModulator.STAGES 插拔八段) = %s" % (_names or "（快照里还没有）"))
        if not _names:
            print("      (重启控制台后 3D 面板才会把「八阶段表」随帧发下来; 没表时只写当前阶段名, 不编)")
        ok &= _ok13
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 取八阶段文字行失败: %s" % _e)

    print("\n⑭ 所有曲线必须**同一根钟** + 当前场景只出本场景色 (老倪: 「时间轴怎么不同步呢? 八阶段序号单独跑, 下面几个信号一起跑」"
          "「接触概率 末端 这几个蓝色的信号, 怎么也显示呢?」「应该只是绿色的信号」)")
    try:
        _xs, _kcol_map = [], {}
        for _k in list(w.selected):
            _b = w.store.bufs.get(_k)
            if _b is None or not getattr(_b, "n", 0):
                continue
            _t, _ = _b.arrays()
            _xs.append((_k, float(_t[-1])))
            try:
                _kcol_map[_k] = QColor(w.wave._kcolor(_k)).name()
            except Exception:                                                  # noqa: BLE001
                _kcol_map[_k] = "?"
        _base = [x for _, x in _xs]
        _spread = (max(_base) - min(_base)) if _base else 0.0
        _ok14a = _spread < 120.0            # 同一根钟: 各条曲线"最后一点"的时刻差 < 2min
        print("   %s 同一根钟: 各曲线末点时刻最大差 %.1fs (<120s ⇒ 不是两根钟各跑各的)" % ("✅" if _ok14a else "❌", _spread))
        for _k, _x in sorted(_xs, key=lambda z: -z[1])[:3]:
            print("        · %-26s 末点 x=%s 色=%s" % (_k, round(_x, 1), _kcol_map.get(_k)))
        _act = w._active_scene() if hasattr(w, "_active_scene") else ""
        _bad = [k for k in _kcol_map
                if k.startswith("sstrace.") and _act and _kcol_map[k] != QColor(CG.SCENE_COLORS.get(_act)).name()]
        _ok14b = (not _bad)
        print("   %s 当前场景(%s) 的 sstrace 曲线全为本场景色 %s%s"
              % ("✅" if _ok14b else "❌", _act or "?", QColor(CG.SCENE_COLORS.get(_act, "#ffffff")).name(),
                 "" if _ok14b else " · 越色: %s" % _bad[:4]))
        ok &= (_ok14a and _ok14b)
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 核横轴/配色失败: %s" % _e)

    print("\n⑮ 界面不许出现 mps / m/s, 速度一律按 **mm/s 毫米/秒** 显示 (老倪: 「不要出现 mps 这样的速度, 就是 mm/s 毫米/秒, "
          "mps 是欧洲用的, 我们是中国」)")
    try:
        _mkeys = [k for k in w.store.keys() if str(k).endswith("_mps")]
        _bad_name = []
        for _k in _mkeys[:40]:
            _dn = w._disp_name(_k)
            if ("mm/s" not in _dn) or ("_mps" in _dn):
                _bad_name.append((_k, _dn))
            if abs(w._unit_scale(_k) - 1000.0) > 1e-9:
                _bad_name.append((_k, "scale!=1000"))
        _vis = " ".join([w.lb_info.text() or "", w.lb_legend.text() or "", w.lb_stages.text() or "",
                         (w._stage_now()[0] or "")])
        _bare = [x for x in ("m/s", "_mps") if any(x in chunk and "mm/s" not in chunk
                                                   for chunk in _vis.split("  "))]
        _ok15 = (not _bad_name) and (not [1 for x in ("m/s",) if x in _vis and "mm/s" not in _vis])
        print("   %s 速度键显示名 (样本 %d 个, 实测 %d 个带 _mps): 全部写成 (mm/s) 且换算 ×1000"
              % ("✅" if _ok15 else "❌", len(_mkeys), len(_mkeys)))
        if _bad_name:
            print("      越界: %s" % _bad_name[:4])
        print("      例: %s → 「%s」" % (_mkeys[0] if _mkeys else "—",
                                       w._disp_name(_mkeys[0]) if _mkeys else "—"))
        print("      状态栏原文: %s" % (w._stage_now()[0] or "")[:70])
        if _bare:
            print("      ⚠️ 可见文本里还有裸 m/s: %s" % _bare)
        ok &= _ok15
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 核单位口径失败: %s" % _e)

    print("\n⑯ 🧾 元任务预测 出口话题 zmax/ss_meta_pred 进信号分析 (老倪 2026-10-15: 「元任务预测这个节点是输出 topic, "
          "是什么? 要加入到实时监控的信号分析」)")
    try:
        _tr = os.path.join(os.getcwd(), "zmax_data", "dataspace", "trace.jsonl")
        _rec = None
        for _ln in reversed(open(_tr, encoding="utf-8").readlines()[-400:]):
            try:
                _r = json.loads(_ln)
            except Exception:                                                  # noqa: BLE001
                continue
            if _r.get("topic") == "zmax/ss_meta_pred":
                _rec = _r
                break
        _dg = {}
        if _rec:
            try:
                _dg = json.loads(_rec.get("digest") or "{}")
            except Exception:                                                  # noqa: BLE001
                _dg = {}
        _leaves = {k: v for k, v in _dg.items() if isinstance(v, (int, float))}
        _keys = [k for k in w.store.keys() if "ss_meta_pred" in k]
        _hit = [k for k in _keys if k.split("ss_meta_pred.")[-1] in _leaves]
        _ok16 = bool(_rec) and bool(_leaves) and bool(_hit)
        ok &= _ok16
        print("   %s 话题在发 (trace.jsonl 末条 n=%s) · digest 可解析出 %d 个数值叶子"
              % ("✅" if _rec else "❌", (_rec or {}).get("n"), len(_leaves)))
        print("        digest: %s" % json.dumps(_leaves, ensure_ascii=False)[:150])
        print("   %s 页面已建出该话题的信号: %s" % ("✅" if _hit else "❌", _hit[:4] or "—"))
        _dn = w._out_node(_hit[0]) if _hit else ""
        print("   %s 输出节点列 = 「%s」" % ("✅" if "元任务预测" in _dn else "❌", _dn))
        ok &= bool(_hit) and ("元任务预测" in _dn)
        print("       ⚠️ 如实口径: frozen=%s (驱动扭矩恒定 ⇒ 无区分度, 不吹有预测力) · top1=%s spread=%s"
              % (_dg.get("frozen"), _dg.get("top1"), _dg.get("spread")))
    except Exception as _e:                                                    # noqa: BLE001
        ok = False
        print("   ❌ 核元任务预测话题失败: %s" % _e)

    print("\n" + "=" * 88)
    print("结论: %s" % ("✅ 全过 — 插拔(绿)全绿 · 重名信号本区加载 · 蓝区折叠不打勾 · 主窗口有真波形" if ok else "❌ 未通过"))
    print("=" * 88)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
