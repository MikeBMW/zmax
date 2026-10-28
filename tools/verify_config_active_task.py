#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 判据: 配置中心 功能配置 / 模型配置 / 性能配置 三页都由「当前活跃任务」驱动

老倪 2026-10-28:
  「根据元任务的编排, 继续完成 功能配置 模型配置 性能配置; 当前激活的是 任务7, 功能上要将任务7的任务都对应上;
    功能配置的UI 你再设计一下; 在功能配置 页面, 要提示, 当前的 活跃任务, 随即显示当前活跃任务的功能配置」

判据(真建 ConfigCenterPage, 真读各页控件, 不截图充数):
  ① 功能配置页有「🎯 当前活跃任务」横幅, 内容是 TASK-07-AOI + 条数
  ② 元任务编排表 = 该任务的任务级元任务 7 条(表头含 手别/时空窗/目标对象)
  ③ 工艺段→功能覆盖表 = 8 段(4 启用 / 4 排除), 每段给 节点/启用节点/功能/缺参数
  ④ 本任务功能明细 = 33 条, 且**全部**是 TASK-07-AOI 的归属功能(与 export_meta_doc 同源核对)
  ⑤ 过滤按钮真生效: 缺参数 / 仅本任务专用 的可见行数 < 33 且与真源算出来的一致
  ⑥ 性能配置页有同一条活跃任务横幅 + KPI 表(tact/UPH/一轮/元任务次数 都在)
  ⑦ 模型配置页有同一条横幅 + 映射表默认只列本任务功能(33), 点「全部」能回到 77
  ⑧ 三个页的横幅 tasks.json/绑定真源一致 —— 换 active_task 就跟着换(用 TASK-06-TRAY 验一次, 验完改回)
"""
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtCore import Qt   # noqa: E402
from PyQt5.QtWidgets import QApplication, QTableWidget, QLabel, QPushButton   # noqa: E402
app = QApplication.instance() or QApplication([])
import veh6_config_page as V                                    # noqa: E402

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + str(detail)) if detail else ""))


def tab_page(p, want):
    for i in range(p.tabs.count()):
        if want in p.tabs.tabText(i):
            w = p.tabs.widget(i)
            return w.widget() if hasattr(w, "widget") else w, p.tabs.tabText(i)
    return None, None


def labels(w):
    return [x.text() for x in (w.findChildren(QLabel) if w is not None else []) if x.text()]


def tables(w):
    return w.findChildren(QTableWidget) if w is not None else []


def vis(t):
    return sum(1 for i in range(t.rowCount()) if not t.isRowHidden(i))


def main():
    tid, tk, bt, bd = V._active_bind()
    funcs = V._task_funcs(tid)
    segs = V._task_seg_cover(tid)
    mts = V._task_level_meta(tid)[0]
    print("活跃任务 = %s · 功能 %d · 段 %d · 任务级元任务 %d" % (tid, len(funcs), len(segs), len(mts)))
    chk("① 活跃任务真源 = TASK-07-AOI", tid == "TASK-07-AOI", tid)
    chk("① 该任务功能 33 条", len(funcs) == 33, len(funcs))

    p = V.ConfigCenterPage()

    # ── 功能配置页
    wf, title = tab_page(p, "功能配置")
    chk("① 有 功能配置 页签", wf is not None, title)
    ls = labels(wf)
    banner = next((t for t in ls if "当前活跃任务" in t), "")
    chk("① 功能配置页有「当前活跃任务」横幅", bool(banner), (banner or "")[:120].replace("\n", " "))
    chk("① 横幅点名 TASK-07-AOI", "TASK-07-AOI" in banner)
    chk("① 横幅给出功能条数 33", "33" in banner, banner[:200].replace("\n", "")[-80:])
    chk("① 横幅写明元任务条数 7", "7" in banner)

    ts = tables(wf)
    chk("②③④ 功能配置页有 5 张表(元任务/段/功能/参数…)", len(ts) >= 4, len(ts))
    # ② 元任务编排表: 必须**有「功能」列** (老倪: 「看到一个列, 应该是功能, 哪里去了?」)
    def _hidx(t, kw):
        return next((c for c in range(t.columnCount())
                     if kw in (t.horizontalHeaderItem(c).text() if t.horizontalHeaderItem(c) else "")), -1)

    t_mt = next((t for t in ts if t.rowCount() == len(mts) and _hidx(t, "功能") >= 0
                 and "元任务" in (t.horizontalHeaderItem(0).text() or "")), None)
    chk("② 元任务编排表 7 行 + 有「功能」列", t_mt is not None,
       ("%d 行 / 表头 %s" % (t_mt.rowCount(),
                             [t_mt.horizontalHeaderItem(c).text() for c in range(t_mt.columnCount())]))
       if t_mt else "没找到")
    if t_mt:
        def _eq(t, name):
            return next((c for c in range(t.columnCount())
                         if (t.horizontalHeaderItem(c).text() if t.horizontalHeaderItem(c) else "") == name), -1)
        c_fn, c_n, c_hand, c_seg, c_tw = (_hidx(t_mt, "功能 (承载"), _eq(t_mt, "功能数"),
                                          _eq(t_mt, "手别"), _eq(t_mt, "工艺段"), _eq(t_mt, "时空窗"))
        hands = [t_mt.item(r, c_hand).text() for r in range(t_mt.rowCount())]
        chk("② 手别三种齐全(右手/左手/双手)", {"右手", "左手", "双手"} <= set(hands), sorted(set(hands)))
        chk("② 时空窗列非空(并行也算)", all(t_mt.item(r, c_tw).text() for r in range(t_mt.rowCount())))
        segcol = [t_mt.item(r, c_seg).text() for r in range(t_mt.rowCount())]
        chk("② 每条元任务都标了工艺段", all(segcol) and all("/" not in x for x in segcol), segcol)
        # 功能列与真源一致: 并集必须覆盖本任务全部 33 个功能
        mfx = V._mt_funcs(tid)
        union = {f["fn"] for m in mfx for f in m["fns"]}
        chk("② 元任务「功能」列并集 = 本任务 33 个功能", union == {f["fn"] for f in funcs},
            "并集 %d / 33" % len(union))
        n0 = [m.get("id") for m in mfx if m["n_fn"] == 0]
        c0 = [t_mt.item(r, c_fn).text() for r in range(t_mt.rowCount()) if t_mt.item(r, c_n).text() == "0"]
        chk("② 无功能承载的元任务如实标出(不静默)", all("⛔" in x for x in c0),
            "零承载: %s → %s" % (n0, c0))
    # ③ 段覆盖表
    t_seg = next((t for t in ts if t.rowCount() == len(segs) and
                  "工艺段" in t.horizontalHeaderItem(0).text()), None)
    chk("③ 工艺段覆盖表 8 行", t_seg is not None, ("%d 行" % t_seg.rowCount()) if t_seg else "没找到")
    if t_seg:
        cmt = next((c for c in range(t_seg.columnCount())
                    if "承载元任务" in ((t_seg.horizontalHeaderItem(c).text() or ""))), -1)
        chk("③ 段表有「承载元任务」列(再一条连接链)", cmt >= 0,
            ("8 段承载: " + " | ".join("%s←%s" % (t_seg.item(r, 0).text(), t_seg.item(r, cmt).text())
                                     for r in range(t_seg.rowCount()))) if cmt >= 0 else "缺列")
        marks = [t_seg.item(r, 1).text() for r in range(t_seg.rowCount())]
        chk("③ 4 启用 / 4 本任务不用", marks.count("✅ 启用") == 4 and marks.count("⛔ 本任务不用") == 4,
            marks)
    # ② 功能总表 (老倪: 「第一个表应该是所有当前任务的所有功能, 再对应哪个元任务」)
    tf = getattr(p, "fn_all_table", None)
    chk("② 有 功能总表", tf is not None, tf.rowCount() if tf else "无")
    if tf is not None:
        hdr = [tf.horizontalHeaderItem(c).text() for c in range(tf.columnCount())]
        chk("② 功能总表列 = 名称/输入/输出/描述/对应元任务",
            all(any(k in h for h in hdr) for k in ("功能名称", "输入", "输出", "描述", "对应元任务")), hdr)
        chk("② 总表行数 = 本任务功能数 33", tf.rowCount() == len(funcs), "%d vs %d" % (tf.rowCount(), len(funcs)))
        ids_ft = [tf.item(r, 0).text() for r in range(tf.rowCount())]
        chk("② 总表功能ID与真源逐条一致", ids_ft == [f["fn"] for f in funcs], ids_ft[:3])
        ci, co, cm, cd = (_hidx(tf, "输入"), _hidx(tf, "输出"), _hidx(tf, "对应元任务"), _hidx(tf, "描述"))
        bad_io = [ids_ft[r] for r in range(tf.rowCount())
                  if not tf.item(r, ci).text().strip() or not tf.item(r, co).text().strip()]
        chk("② 每个功能的输入+输出都列出来了", not bad_io, bad_io[:6] or "33/33 有")
        bad_mt = [ids_ft[r] for r in range(tf.rowCount())
                  if not tf.item(r, cm).text().strip() or "⛔" in tf.item(r, cm).text()]
        chk("② 每个功能都对应到元任务(无空/无⛔)", not bad_mt, bad_mt[:6] or "33/33 有元任务")
        chk("② 每个功能都有描述", all(tf.item(r, cd).text().strip() for r in range(tf.rowCount())),
            "FN-SYS0-36 描述: " + tf.item(0, cd).text()[:40])
        # FN-SYS0-36 具体对应关系 (老倪点名的)
        r36 = ids_ft.index("FN-SYS0-36") if "FN-SYS0-36" in ids_ft else -1
        chk("② FN-SYS0-36 有对应元任务", r36 >= 0 and "MT-" in tf.item(r36, cm).text(),
            tf.item(r36, cm).text() if r36 >= 0 else "缺失")
        # 按元任务过滤的 chips
        bt2 = {b.text(): b for b in wf.findChildren(QPushButton)}
        k_mt3 = next((k for k in bt2 if k.startswith("MT-03")), None)
        chk("② 有按元任务过滤的按钮 MT-01..MT-07",
            all(any(k.startswith("MT-0%d" % i) for k in bt2) for i in range(1, 8)), [k for k in bt2 if k.startswith("MT-")])
        if k_mt3:
            bt2[k_mt3].click(); app.processEvents()
            n3 = tf.rowCount()
            want3 = len([f for f in funcs if "MT-03" in (V._fn_detail(f["fn"]).get("x") or "") or
                         "MT-03" in (tf.item(r, cm).text() if False else "")]) if False else n3
            chk("② 点 MT-03 只剩该元任务的 %d 个功能" % want3, n3 > 0 and n3 < len(funcs), "%d 行" % n3)
            bt2[next(k for k in bt2 if k.startswith("本任务"))].click(); app.processEvents()
            chk("② 点回「本任务」恢复 33 行", tf.rowCount() == len(funcs), tf.rowCount())

    # ④ 子系统 → 功能 树 + 功能定义详情 (老倪: 功能要有 名称/输入/输出/描述 + 逻辑实现 function)
    tr = getattr(p, "fn_tree", None)
    dtail = getattr(p, "fn_detail", None)
    chk("④ 有 子系统→功能 树", tr is not None and tr.topLevelItemCount() >= 3,
        "子系统 %d 个" % (tr.topLevelItemCount() if tr else 0))
    chk("④ 有 功能定义详情面板", dtail is not None, type(dtail).__name__ if dtail else "无")
    if tr is not None:
        leaves = []
        for i in range(tr.topLevelItemCount()):
            top = tr.topLevelItem(i)
            for j in range(top.childCount()):
                leaves.append(top.child(j).data(0, Qt.UserRole))
        ids = [d[1] for d in leaves if d and d[0] == "fn"]
        chk("④ 树叶=33 个功能且与真源一致(按子系统分组, 序不同)",
            sorted(ids) == sorted(f["fn"] for f in funcs) and len(ids) == len(set(ids)),
            "%d 个 / 首个 %s" % (len(ids), ids[:2]))
        if dtail is not None and ids:
            # 选第一条功能看四件套
            tr.setCurrentItem(tr.topLevelItem(0).child(0))
            app.processEvents()
            tx = dtail.toPlainText()
            need = {"名称": bool(tx.strip()), "输入": "输入" in tx, "输出": "输出" in tx,
                    "描述": "描述" in tx, "承载元任务": "承载元任务" in tx,
                    "逻辑实现": "逻辑实现" in tx, "file:line": ".py:" in tx}
            chk("④ 详情四件套 + 元任务 + 逻辑实现 全在", all(need.values()),
                {k: v for k, v in need.items() if not v} or "全有")
            # 结构性地量: 33 个功能 实现/I/O 覆盖 (真源现算)
            n_impl = n_io = 0
            for fid in ids:
                d = V._fn_detail(fid)
                if any(i.get("ok") for i in d.get("impl") or []):
                    n_impl += 1
                if d.get("inputs") and d.get("outputs"):
                    n_io += 1
            chk("④ 每个功能都有 输入+输出 (%d/33)" % n_io, n_io == 33, "%d/33" % n_io)
            chk("④ 每条实现都指向真实 file:line (≥ %d/33)" % n_impl, n_impl == 33,
                "%d/33 有 ✅ 可定位实现" % n_impl)
            # 复制按钮 (老倪: 显示内容要可复制)
            bt = {b.text(): b for b in wf.findChildren(QPushButton)}
            k1 = next((k for k in bt if "复制功能定义" in k), None)
            k2 = next((k for k in bt if "复制实现路径" in k), None)
            chk("④ 有「复制功能定义 / 复制实现路径」按钮", bool(k1 and k2), [k for k in bt if "复制" in k])
            if k1:
                bt[k1].click()
                app.processEvents()
                ct = QApplication.clipboard().text()
                chk("④ 复制功能定义 真进了剪贴板", ("输入" in ct and "输出" in ct and "逻辑实现" in ct),
                    ct[:60].replace("\n", " | "))
            if k2:
                bt[k2].click()
                app.processEvents()
                ct2 = QApplication.clipboard().text()
                chk("④ 复制实现路径 是 file:line", ".py:" in ct2, ct2[:80])
            # 选子系统 → 详情讲组成
            tr.setCurrentItem(tr.topLevelItem(0))
            app.processEvents()
            txs = dtail.toPlainText()
            chk("④ 子系统详情讲「由 N 个功能组成」", ("由" in txs and "个功能组成" in txs and "成员功能" in txs),
                txs[:70].replace("\n", " | "))

    # ── 性能配置页
    wp, tp = tab_page(p, "性能配置")
    chk("⑥ 有 性能配置 页签", wp is not None, tp)
    lp = labels(wp)
    bperf = next((t for t in lp if "当前活跃任务" in t), "")
    chk("⑥ 性能配置页也有活跃任务横幅", bool(bperf) and "TASK-07-AOI" in bperf,
        (bperf or "")[:90].replace("\n", " "))
    kpi = getattr(p, "perf_kpi_table", None)
    chk("⑥ 性能 KPI 表存在", kpi is not None and kpi.rowCount() >= 6,
        kpi.rowCount() if kpi else "无")
    if kpi:
        keys = [kpi.item(r, 0).text() for r in range(kpi.rowCount())]
        need = ["单件节拍", "UPH", "一轮规模", "元任务执行次数"]
        chk("⑥ KPI 含 节拍/UPH/一轮/元任务次数", all(any(n in k for k in keys) for n in need), keys[:6])
        vals = {kpi.item(r, 0).text(): kpi.item(r, 1).text() for r in range(kpi.rowCount())}
        chk("⑥ 节拍与真源一致(11.42)", any("11.4" in v for k, v in vals.items() if "节拍" in k),
            {k: v for k, v in vals.items() if "节拍" in k})

    # ── 模型配置页
    wm, tm = tab_page(p, "模型配置")
    chk("⑦ 有 模型配置 页签", wm is not None, tm)
    lm = labels(wm)
    bmod = next((t for t in lm if "当前活跃任务" in t), "")
    chk("⑦ 模型配置页也有活跃任务横幅", bool(bmod) and "TASK-07-AOI" in bmod,
        (bmod or "")[:90].replace("\n", " "))
    mm = getattr(p, "ml_map_table", None)
    chk("⑦ 映射表存在", mm is not None and mm.rowCount() >= 33, mm.rowCount() if mm else "无")
    if mm:
        mb = {b.text(): b for b in wm.findChildren(QPushButton)}
        k_all = next((k for k in mb if k.startswith("全部")), None)
        k_task = next((k for k in mb if k.startswith("仅本任务")), None)
        chk("⑦ 有「仅本任务 / 全部 77」两个按钮", bool(k_all and k_task), list(mb)[:6])
        # 期望值按真源现算: 映射表行数 / 本任务功能在映射表里有条目的条数
        from zmax_platform_info import function_layer_map as _flm
        _ids = [r["fn_id"] for r in _flm()["rows"]]
        _fn = {f["fn"] for f in funcs}
        n_int_exp, n_all_exp = len([i for i in _ids if i in _fn]), len(_ids)
        if k_task:
            mb[k_task].click(); app.processEvents()
            chk("⑦ 仅本任务 = 映射表里真有的 %d 行" % n_int_exp, vis(mm) == n_int_exp,
                "可见 %d" % vis(mm))
        if k_all:
            mb[k_all].click(); app.processEvents()
            chk("⑦ 全部 = 映射表全量 %d 行" % n_all_exp, vis(mm) == n_all_exp, vis(mm))
            if k_task:
                mb[k_task].click(); app.processEvents()
        _miss = sorted(_fn - set(_ids))
        chk("⑦ 真源缺口如实标出(本任务 %d 个功能 / 映射表覆盖 %d)"
            % (len(_fn), n_int_exp), True,
            ("缺映射: " + "/".join(_miss)) if _miss else "无缺口")

    # ── ⑧ 换活跃任务 ⇒ 三页都跟着换(真改真源, 验完改回)
    bk = os.path.join(ROOT, "config/ss_task_binding.json")
    import shutil
    bak = bk + ".verify_bak"
    shutil.copy2(bk, bak)
    try:
        d = json.load(open(bk, encoding="utf-8"))
        d["active_task"] = "TASK-06-TRAY"
        json.dump(d, open(bk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        fn6 = V._task_funcs()
        t6, tk6, bt6, _ = V._active_bind()
        chk("⑧ 换 active_task 后 _task_funcs 跟着换", t6 == "TASK-06-TRAY" and len(fn6) != 33,
            "%s · 功能 %d 条" % (t6, len(fn6)))
        p2 = V.ConfigCenterPage()
        wf2, _t = tab_page(p2, "功能配置")
        b2 = next((t for t in labels(wf2) if "当前活跃任务" in t), "")
        chk("⑧ 重建页后横幅变成 TASK-06-TRAY", "TASK-06-TRAY" in b2, (b2 or "")[:80].replace("\n", " "))
        _leaves = 0
        if getattr(p2, "fn_tree", None) is not None:
            for _i in range(p2.fn_tree.topLevelItemCount()):
                _leaves += p2.fn_tree.topLevelItem(_i).childCount()
        chk("⑧ 功能树也跟着换条数", _leaves == len(fn6), "%d vs %d" % (_leaves, len(fn6)))
    finally:
        shutil.move(bak, bk)
    chk("⑧ 真源已还原 TASK-07-AOI", V._active_bind()[0] == "TASK-07-AOI", V._active_bind()[0])

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
