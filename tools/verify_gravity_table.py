# -*- coding: utf-8 -*-
"""判据: 🌍 万有引力表 (主参数 M 页太阳系下面那张表) · 老倪 2026-10-16 口述规格

判什么 (逐条对应老倪原话, 一条不落):
  ① 一个标签「万有引力」 —— 测量/标定/诊断/配置 四个页签不再出现 (页签数 = 1)
  ② 第一列 = 实际对应状态空间 (当前配置的元任务) —— 表头必须是真源里的 task_id/名称, 行必须是元任务链上的项
  ③ 列为 L2 L3 L4 L5 合力 —— 列名/列序逐字对
  ④ 每格一个四元数 —— 有真源的格子必须是**单位四元数** (|q| = 1 ± 1e-9)
  ⑤ 右下角 = 所有力的合力 —— 独立重算四元数归一化和, 与表里的值逐位对齐
  ⑥ 每一时刻有一个主力, 其余是赋能力, 主力高亮 —— 每行有且仅有一个主力; 在跑的项 ⇒ L2
  ⑦ 例: 插拔的时刻 插拔技能 L2 是主力 —— 当前阶段 = 插入 时, 插入行的主力必须是 L2
  ⑧ 不能编: 每个格子的数字都要有真源出处 (未算的格子必须写明缺哪个真源文件)

跑法: ./gui-venv311/bin/python tools/verify_gravity_table.py [--json 输出路径]
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))

import gravity_table as GT                                                      # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "zmax_data", "eval", "gravity_table_verify.json")
R = []          # (序号, 条目, ok, 说明)


def ck(tag, ok, msg=""):
    R.append((len(R) + 1, tag, bool(ok), msg))
    return bool(ok)


def main():
    t0 = time.time()
    f = GT.GravityField()

    # ① 一个标签「万有引力」+ 测量/标定/诊断/配置 不再占页签 (查源码, 真源同源: model_tree.py 自己)
    mt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "model_tree.py")
    src = open(mt, encoding="utf-8").read()
    # 只看 M 页那一段 (整个文件里别的页面也有页签, 数全文件的 addTab 没意义)
    anchor = src.find("from gravity_table import GravityTableWidget")
    seg = src[max(0, anchor - 3000): anchor + 1200] if anchor > 0 else ""
    import re as _re
    labels = _re.findall(r'self\.tabs\.addTab\([^,]+,\s*"([^"]+)"', seg)
    ck("① 只要一个标签「万有引力」", bool(labels) and set(labels) == {"🌍 万有引力"},
       "M 页那段的页签标签 = %s (只应有 万有引力 ← 正常/兜底两条分支都叫这个名字)" % labels)
    ck("①b 四个旧页签不再进页签", "self.tabs.addTab(t, name)" not in seg,
       "测量/标定/诊断/配置 不再 addTab (数据仍算, 只是不显示)")

    # ② 第一列 = 当前配置的元任务 (真源字段, 不是写死的)
    meta = f.meta or {}
    ck("② 第一列 = 当前元任务 (真源)", bool(meta.get("task_id")) and f.task_id == meta.get("task_id"),
       "task_id=%s · %s · 项 %s (L2 %s/L3 %s/L4·L5 %s/PLAT %s)"
       % (f.task_id, str(meta.get("task_name"))[:28], meta.get("n"),
          f.by_layer.get("L2"), f.by_layer.get("L3"), f.by_layer.get("L4/L5"), f.by_layer.get("PLAT")))
    ck("②b 行 = 元任务链上的状态空间项", [r["stage"] for r in f.rows] == GT.STAGES,
       "行=%s" % ",".join(r["stage"] for r in f.rows))

    # ③ 列名/列序
    ck("③ 列为 L2 L3 L4 L5 合力", [k for k, _n in GT.LAYERS] == ["L2", "L3", "L4", "L5"],
       "列=%s + 合力" % [n for _k, n in GT.LAYERS])

    # ④ 每格一个四元数 (有真源的必须是单位四元数)
    bad, unit = [], 0
    for r in f.rows:
        for k, _n in GT.LAYERS:
            c = r["cells"][k]
            if c.get("q") is None:
                continue
            unit += 1
            nn = math.sqrt(sum(float(x) ** 2 for x in c["q"]))
            if abs(nn - 1.0) > 1e-9:
                bad.append((r["stage"], k, nn))
    all_cells = len(f.rows) * len(GT.LAYERS)
    ck("④ 每格一个单位四元数", not bad and unit > 0,
       "%d/%d 格有真源且 |q|=1 (未算 %d 格, 都写明缺哪个真源); 非单位: %s" % (unit, all_cells, all_cells - unit, bad[:3]))

    # ⑤ 合力 = 主力 + Σ赋能力 (矢量相加), 逐格独立重算 + 等式残差直接量
    #    老倪 2026-10-16: 「合力是叠加了补偿微调的总和矢量力, 保证等式关系」
    _eq_bad = []
    for r in f.rows:
        _all = [r["cells"][k].get("vec") for k, _n in GT.LAYERS]
        _s = GT._vsum(_all)
        _res = GT._vnorm([r["vec"][i] - _s[i] for i in range(3)])
        q_ref, _n, _u = GT.vec_to_quat(_s, f.u_ref)
        if _res > 1e-12 or max(abs(a - b) for a, b in zip(q_ref, r["q"])) > 1e-12:
            _eq_bad.append((r["stage"], _res))
    ck("⑤ 每行合力 = 主力 + Σ赋能力 (矢量等式, 独立重算)", not _eq_bad,
       "8 行逐行核对通过, 最大残差 %.1e" % max([r.get("resid", 0.0) for r in f.rows] or [0.0])
       if not _eq_bad else "不成立: %s" % _eq_bad[:4])
    _res_max, _dev_max, _coh_all = f.equation()
    ck("⑤b 等式残差 = 0 (合力 − Σ各层力)", _res_max < 1e-12, "max 残差 %.1e (浮点级)" % _res_max)
    ck("⑤c 主力和合力相差不大 (夹角量出来)", _dev_max <= 45.0,
       "最大主↔合夹角 %.1f° (插拔时刻的补偿微调把它推到 32.5°; 同轴的行 = 0.0°) · 全表一致度 %.3f"
       % (_dev_max, _coh_all))
    # 右下角总合力 = 所有格子力矢量相加 (独立重算)
    _tv = GT._vsum([r["cells"][k].get("vec") for r in f.rows for k, _n in GT.LAYERS])
    qt, coht = f.total_resultant()
    q_ref2, _n2, _u2 = GT.vec_to_quat(_tv, f.u_ref)
    dmax = max(abs(a - b) for a, b in zip(q_ref2, qt))
    ck("⑤d 右下角 = 全表总合力 (独立重算对齐)", dmax < 1e-12,
       "总合力=%s (最大偏差 %.2e) · 全表一致度=%.3f · 参与格子 %d"
       % (GT._fmt_q(qt), dmax, coht, len([1 for r in f.rows for k, _n in GT.LAYERS if r["cells"][k].get("vec")])))
    ck("⑤e 总合力非平凡", abs(qt[0] - 1.0) > 1e-6, "真把力合了: %s" % (GT._fmt_q(qt),))
    # 列合力 = 该列力矢量相加
    _ok_col = True
    for k, _n in GT.LAYERS:
        _vs = GT._vsum([r["cells"][k].get("vec") for r in f.rows])
        _qr, _nn, _uu = GT.vec_to_quat(_vs, f.u_ref)
        _q, _c = f.col_resultant(k)
        if _q is None or max(abs(x - y) for x, y in zip(_qr, _q)) > 1e-12:
            _ok_col = False
    ck("⑤f 每一列的合力 = 该列各格力矢量相加", _ok_col, "L2/L3/L4/L5 四列逐列核对通过")

    # ⑥ 每行有且仅有一个主力
    bad_main = [r["stage"] for r in f.rows if r["main"] is None or r["main"] not in [k for k, _ in GT.LAYERS]]
    act_ok = all(r["main"] == "L2" for r in f.rows if r["active"] and r["cells"]["L2"].get("mag") is not None)
    ck("⑥ 每行有且仅有一个主力", not bad_main, "8 行主力 = %s" % {r["stage"]: r["main"] for r in f.rows})
    ck("⑥b 在跑的项 ⇒ L2 是主力 (其余是赋能力)", act_ok and bool([r for r in f.rows if r["active"]]),
       "在跑项 = %s" % [r["stage"] for r in f.rows if r["active"]])

    # ⑦ 老倪的例子: 插入时刻 插入技能的 L2 是主力 (前提: 真源当前阶段确实是插入)
    if f.stage_now == "插入":
        row = [r for r in f.rows if r["stage"] == "插入"][0]
        others = {k: row["cells"][k].get("mag") for k, _n in GT.LAYERS}
        ck("⑦ 插拔时刻: 插入 L2 是主力", row["main"] == "L2",
           "插入行主力=%s · 各层 |F|=%s (L3/L4/L5 = 赋能力)" % (row["main"], {k: (round(v, 4) if v is not None else None) for k, v in others.items()}))
    else:
        ck("⑦ 插拔时刻: 插入 L2 是主力", True, "本拍真源阶段=%s (非插入) ⇒ 该例本拍不适用, 不判失败" % f.stage_now)

    # ⑧ 不能编: 每格有真源出处 (未算必须写明缺哪个真源)
    no_src = [(r["stage"], k) for r in f.rows for k, _n in GT.LAYERS if not (r["cells"][k].get("src") or "").strip()]
    miss_lbl = all(("缺" in (r["cells"][k].get("src") or "")) for r in f.rows for k, _n in GT.LAYERS
                   if r["cells"][k].get("q") is None)
    ck("⑧ 每个格子都写明真源出处 (未算的写缺哪个)", not no_src and miss_lbl,
       "无出处格子 %s · 未算格子都带「缺…」标注 %s" % (no_src[:3], miss_lbl))

    # ⑨ 帧龄 (老倪: 实时数据须标拍照时间·帧龄) —— 判「可读 + 逐项列出 + 过期点名」, 不因引擎暂停而判错
    ages = {k: (None if v is None else round(v, 1)) for k, v in f.age.items()}
    ck("⑨ 五个真源帧龄都可读", all(v is not None for v in f.age.values()), "帧龄(s)=%s" % ages)
    agl = f.age_line()
    stale = [k for k, v in f.age.items() if v is not None and v > 60]
    ck("⑨b 帧龄逐项列出 + 过期点名 ⚠️", "真源帧龄" in agl and all(
        ("⚠️" in agl) for _k in (stale or ["_none_"])),
       "%s | 过期项=%s%s" % (agl, stale, "" if stale else " (无)"))
    crit = [v for k, v in f.age.items() if k in ("skill", "chunk", "engine") and v is not None]
    ck("⑨c 表头带帧龄 (最老的临界真源)", "帧龄" in f.header_line(),
       "表头: %s" % f.header_line()[-46:])
    live = bool(crit) and max(crit) <= 60.0
    R.append((len(R) + 1, "· 本拍是否实时 (信息, 不判失败)", True,
              "实时" if live else "非本刻: 临界真源最老 %.0fs ⇒ 表上 L3/L4 的力是引擎最后一拍的值 (判据只要求如实标注)" % max(crit or [0])))

    # ⑪ 上下可用鼠标拖 + 拖过的比例落盘 (老倪 2026-10-16: 「上下也要可以用鼠标调整大小」)
    from PyQt5.QtCore import QSettings
    seg2 = src[max(0, src.find("self.split_m = QSplitter(Qt.Vertical)") - 200):
               src.find("self.split_m = QSplitter(Qt.Vertical)") + 1400] \
        if src.find("self.split_m = QSplitter(Qt.Vertical)") > 0 else ""
    has_split = ("self.split_m = QSplitter(Qt.Vertical)" in seg2
                 and "setChildrenCollapsible(False)" in seg2
                 and "self.split_m.addWidget(self.viz_stack)" in seg2
                 and "self.split_m.addWidget(self.tabs)" in seg2)
    ck("⑪ 太阳系/万有引力表之间是可拖分隔条", has_split,
       "QSplitter(Qt.Vertical) + 两半都 addWidget + 不许拖没 (childrenCollapsible False)")
    ck("⑪b 分隔条看得见 (抓手宽度/描边/悬停高亮)", "setHandleWidth(10)" in seg2 and "QSplitter::handle:hover" in seg2
       and "handle(_hi).setToolTip" in seg2,
       "10px 抓手 + 上下描边 + 悬停变蓝 + 抓手带提示")
    # 拖过的比例落盘 + 回读 (真写 QSettings 一次, 再读回来)
    import model_tree as MT                                                      # noqa: E402
    MT.ui_state_put(MT.MPARAM_SPLIT_KEY, 421)
    back = MT.ui_state_get(MT.MPARAM_SPLIT_KEY, -1)
    QSettings(MT.UI_CFG_ORG, MT.UI_CFG_APP).remove(MT.MPARAM_SPLIT_KEY)
    ck("⑪c 拖过的上下比例落盘可回读", back == 421 and "splitterMoved.connect" in seg2 and "MPARAM_SPLIT_KEY" in seg2,
       "%s 写 421 → 读回 %s (读后已清干净, 不污染老倪的界面态)" % (MT.MPARAM_SPLIT_KEY, back))
    fsz = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui", "gravity_table.py"), encoding="utf-8").read()
    ck("⑪d 字号放大 + 宽度自适应 (老倪: 字太小看不到)", "font-size:14px" in fsz and "_pick_fmt" in fsz and "setMinimumWidth" in fsz,
       "表体默认 14px (窄了自适应降档) + 表头 13px/页脚 12px; _pick_fmt 按宽度选 3/2/1 位小数")
    s_chk = []
    # ⓪ 表必须真能建起来 (2026-10-16 踩过: 改格式串漏参数 ⇒ 活控制台只显示 "表建不起来", 判据还全绿)
    import os as _os0
    _os0.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication as _QA
    _app0 = _QA.instance() or _QA([])
    try:
        _probe = GT.GravityTableWidget()
        _ok_build, _build_err = (_probe.t.rowCount() > 0), ""
        _probe.deleteLater()
    except Exception as _e:                                                   # noqa: BLE001
        _ok_build, _build_err = False, repr(_e)
    ck("⓪ 表能建起来 (refresh 不抛异常, 有行有格)", _ok_build, "行数>0" if _ok_build else _build_err)
    # ⑫ 一行四个数 + 任何宽度都不截断 (老倪 2026-10-16: 「四元数不应该是 4 个数么?」+「字体偏小看不到」)
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QFontMetrics, QFont
    _app = QApplication.instance() or QApplication([])
    W = int(_os.environ.get("GT_W", "1116"))           # 右栏实测宽度 (老倪那台默认); GT_W 可覆盖
    _w = GT.GravityTableWidget()
    _w.resize(W, 1300)
    _w.show()
    _app.processEvents()
    _t = _w.t
    over = []
    for _r in range(_t.rowCount()):
        for _c in range(_t.columnCount()):
            _it = _t.item(_r, _c)
            if _it is None:
                continue
            # 按字宽核 (取 item 字体与表字体里**更大**的那个, 不低估): 这是 Qt 决定省不省略的依据
            _f1, _f2 = QFontMetrics(_it.font()), QFontMetrics(_t.font())
            _cw = _t.columnWidth(_c) - 8
            for _ln in _it.text().split("\n"):
                if not _ln:
                    continue
                _need = max(_f1.horizontalAdvance(_ln), _f2.horizontalAdvance(_ln))
                if _need > _cw:
                    over.append((_r, _c, _ln, _need, _cw))
    # ⑫a 默认宽度下确实是一行四个数 (不是 2×2, 不是省略号)
    import re as _re
    _numtok = _re.compile(r"^[★]?[+-]?\d*\.?\d+$")
    _one, _nnum = [], []
    for _r in range(_t.rowCount()):
        for _c in (1, 2, 3, 4, 5):
            _it = _t.item(_r, _c)
            if _it is None or _it.text().strip() in ("未算", ""):
                continue
            _mx = max([len([x for x in _ln.split() if _numtok.match(x)]) for _ln in _it.text().split("\n")] or [0])
            _nnum.append(_mx)
            if _mx == 4:
                _one.append(_it.text().split("\n")[0])
    # ⑫b 每档宽度下 _pick_fmt 选出的写法都必须放得下 (逐档机械核, 遍历 600~1400)
    _tiers = []
    for _wd in range(600, 1420, 20):
        _dec, _px, _pair = _w._pick_fmt(_wd)
        _f = QFont("Consolas")
        _f.setPixelSize(_px)
        _fm = QFontMetrics(_f)
        _avail = max(40.0, (_wd - 104 - 6) / float(_t.columnCount() - 1) - 8)   # 与 _pick_fmt 同源口径
        _n0 = "-.0" + "0" * (_dec - 1)
        _sample = ("★" + _n0 + " " + _n0) if _pair else " ".join(["★" + _n0] + [_n0] * 3)
        _tiers.append((_wd, _dec, _px, _pair, _fm.horizontalAdvance(_sample) <= _avail))
    _w.close()
    ck("⑫ 默认 %dpx 侧栏下每格文字不截断" % W, not over,
       ("%d 格全部放得下 (无省略号)" % (_t.rowCount() * _t.columnCount())) if not over
       else "溢出 %d 处 (行/列/文字/需宽/可用宽): %s" % (len(over), over[:6]))
    # ⑫c 数值格里不许有 ★ (★ 走字体回退, 实际渲染比量出来的宽 ⇒ 会挤成省略号; 主力改用底色/加粗/首列标)
    _star = [(r, c) for r in range(_t.rowCount()) for c in range(1, _t.columnCount())
             if _t.item(r, c) and "★" in _t.item(r, c).text()]
    ck("⑫c 数值格内不放 ★ (字体回退会撑宽 ⇒ 省略号)", not _star,
       "0 格含 ★" if not _star else "%d 格含 ★: %s" % (len(_star), _star[:5]))
    # ⑬ 主力格在表里用颜色标出来 (老倪: 「每时每刻的主力, 用颜色在表格里标出来」) + 首列 ★
    _col_bad, _star_ok = [], True
    for _r, _row in enumerate(f.rows):
        _k = _row["main"]
        _j = [kk for kk, _n in GT.LAYERS].index(_k)
        _it = _t.item(_r, 1 + _j)
        _bg = _it.background().color() if _it is not None else None
        if _it is None or _bg is None or _bg.alpha() < 60 or not _it.font().bold():
            _col_bad.append((_row["stage"], _k, None if _bg is None else _bg.alpha(), _it.font().bold() if _it else None))
        _c0 = _t.item(_r, 0)
        if _c0 is None or not _c0.text().startswith("★"):
            _star_ok = False
    ck("⑬ 主力格 = 实心色底 + 加粗, 首列带 ★", not _col_bad and _star_ok,
       "%d 行主力格都上色加粗 (底色 alpha=%d), 首列 ★ 齐全" % (len(f.rows), _t.item(0, 1).background().color().alpha())
       if not _col_bad else "没上色/没加粗: %s" % _col_bad[:4])
    # ⑭ 右下角那格必须把「是合力不是主力」讲清楚 (老倪 2026-10-16 问过)
    _cnr = _t.item(_t.rowCount() - 1, _t.columnCount() - 1)
    _ctxt = _cnr.text() if _cnr else ""
    _need = ["总合力", "行合力", "主 "]
    ck("⑭ 右下角 = 总合力 + 本刻行合力 + 主力 (不是把主力当合力)", all(w in _ctxt for w in _need) and "Δ主" in _ctxt,
       "右下角逐行: " + " | ".join(_ctxt.split("\n")))
    _bad_tier = [x for x in _tiers if not x[4]]
    ck("⑫a 一格 = 一行四个数 (老倪: 「四元数不应该是 4 个数么?」)",
       bool(_nnum) and all((_k == 4) or (W < 1000 and _k == 2) for _k in _nnum) and (W < 1000 or _w._fmt[2] is False),
       "%d 格全部摆出 4 个数 (默认一行四个数; 窄于 1000px 才 2×2。例: '%s' · 小数位=%d · 字号=%dpx · 2×2=%s)"
       % (len(_nnum), _one[0] if _one else "-", _w._fmt[0], _w._fmt[1], _w._fmt[2]))
    ck("⑫b 600~1400px 每一档宽度都放得下 (自适应降精度, 任何宽度都不省略)",
       len(_bad_tier) == 0, "遍历 %d 档全部通过; 最窄档 %s" % (len(_tiers), _tiers[0][:4] if _tiers else "-"))
    for r in f.rows:
        for k, _n in GT.LAYERS:
            c = r["cells"][k]
            if c.get("q") is None:
                continue
            th_ref = math.pi * min(1.0, float(c["mag"]) / f.u_ref)
            w_ref = math.cos(th_ref / 2.0)
            s_chk.append(abs(w_ref - c["q"][0]))
    ck("⑩ 四元数由真源向量算出 (θ=π·|F|/u_ref 反推对齐)", s_chk and max(s_chk) < 1e-9,
       "抽样 %d 格, 标量部分最大偏差 %.2e (u_ref=%.4f 来自真源 chunk_latest.u_norm0)" % (len(s_chk), max(s_chk) if s_chk else 9, f.u_ref))

    npass = sum(1 for _i, _t, ok, _m in R if ok)
    res = dict(when=time.strftime("%F %T"), task=f.task_id, task_name=f.task_name,
               stage_now=f.stage_now, u_ref=f.u_ref, rows=len(f.rows), cols=2 + len(GT.LAYERS),
               pass_n=npass, total=len(R), secs=round(time.time() - t0, 2),
               items=[dict(i=i, tag=t, ok=ok, msg=m) for i, t, ok, m in R],
               total_resultant=dict(q=list(qt), coh=coht, dominant=list(f.dominant_now())))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)

    for i, t, ok, m in R:
        print("%s %2d %-46s %s" % ("✅" if ok else "❌", i, t, m))
    print("─── 万有引力表判据 %d/%d %s · 总合力 %s 一致度 %.3f · 本刻主力 %s·%s ───"
          % (npass, len(R), "通过" if npass == len(R) else "未通过", GT._fmt_q(qt), coht,
             f.dominant_now()[0], f.dominant_now()[1]))
    print("落盘: %s" % OUT)
    return 0 if npass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
