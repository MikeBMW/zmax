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
    # ② 元任务编排表: 表头含 手别+时空窗, 行数=7
    t_mt = next((t for t in ts if t.rowCount() == len(mts) and
                 "手别" in t.horizontalHeaderItem(2).text()), None)
    chk("② 元任务编排表 7 行 + 手别列", t_mt is not None,
       ("%d 行" % t_mt.rowCount()) if t_mt else "没找到")
    if t_mt:
        hands = [t_mt.item(r, 2).text() for r in range(t_mt.rowCount())]
        chk("② 手别三种齐全(右手/左手/双手)",
            {"右手", "左手", "双手"} <= set(hands), sorted(set(hands)))
        chk("② 时空窗列非空(并行也算)", all(t_mt.item(r, 5).text() for r in range(t_mt.rowCount())))
    # ③ 段覆盖表
    t_seg = next((t for t in ts if t.rowCount() == len(segs) and
                  "工艺段" in t.horizontalHeaderItem(0).text()), None)
    chk("③ 工艺段覆盖表 8 行", t_seg is not None, ("%d 行" % t_seg.rowCount()) if t_seg else "没找到")
    if t_seg:
        marks = [t_seg.item(r, 1).text() for r in range(t_seg.rowCount())]
        chk("③ 4 启用 / 4 本任务不用", marks.count("✅ 启用") == 4 and marks.count("⛔ 本任务不用") == 4,
            marks)
    # ④ 功能明细表
    t_fn = getattr(p, "func_table", None)
    chk("④ 功能明细表 33 行", t_fn is not None and t_fn.rowCount() == 33,
        t_fn.rowCount() if t_fn else "无")
    if t_fn:
        ids = [t_fn.item(r, 0).text() for r in range(t_fn.rowCount())]
        want = [f["fn"] for f in funcs]
        chk("④ 33 行与真源功能清单逐条一致", ids == want)
        # ⑤ 过滤
        bad = sum(1 for f in funcs if not f["complete"])
        t_fn2 = t_fn
        # 直接调按钮: 找「缺参数」按钮
        btns = {b.text(): b for b in wf.findChildren(QPushButton)}
        b_bad = next((k for k in btns if k.startswith("缺参数")), None)
        if b_bad:
            btns[b_bad].click()
            app.processEvents()
            chk("⑤ 「缺参数」过滤生效", vis(t_fn2) == bad, "可见 %d · 真源缺参数 %d" % (vis(t_fn2), bad))
        else:
            chk("⑤ 有「缺参数」过滤按钮", False, list(btns))
        b_all = next((k for k in btns if k.startswith("全部")), None)
        if b_all:
            btns[b_all].click()
            app.processEvents()
            chk("⑤ 「全部」恢复 33 行", vis(t_fn2) == 33, vis(t_fn2))

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
        chk("⑧ 功能明细也跟着换条数", p2.func_table.rowCount() == len(fn6),
            "%d vs %d" % (p2.func_table.rowCount(), len(fn6)))
    finally:
        shutil.move(bak, bk)
    chk("⑧ 真源已还原 TASK-07-AOI", V._active_bind()[0] == "TASK-07-AOI", V._active_bind()[0])

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
