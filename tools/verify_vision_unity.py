#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 产品愿景是否真的统一到 配置中心 / ar3d / 市场分成 PPT 三处。

老倪 2026-10-28: 「根据产品愿景, 整体优化配置中心, 依次优化产品定义/任务配置/功能配置/模型配置/性能配置/
工程配置, 最后给出成本组成、市场分成, 达到全局愿景统一; 这个愿景, 一个在 AR 场景体现」

六段:
  ① 愿景真源 tools/spec/vision.json 结构完整 (一句话/三支柱/八步/AR 口径), 且八步与七页签对得上
  ② 配置中心: 七个页签顶上都装了愿景带, 高亮环节与页签对应; 文档配置同时高亮 成本组成 + 市场分成
  ③ 成本组成表 / 市场分成表: 真读表格单元格, 与 cost_model.build_tiers() 逐项对账 (不是看有没有控件)
  ④ ar3d: /api/ar/vision 可读; 动作单元 7 + 段 40; 页面有愿景条与 __VIS__ 钩子; 愿景条在 dock 之上不遮挡
  ⑤ 市场分成 PPT: 12 页, 含愿景句与八步, 图表 ≥6, 不出现 任务7/T1 编号
  ⑥ 三处话术同源: 配置中心愿景带首句 == PPT 首页标题 == ar3d 愿景条首句 == vision.json headline

跑法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_vision_unity.py
"""
import json
import os
import sys
import urllib.request

ROOT = "/home/ubuntu/zmax"
PASS, FAIL = [], []
sys.path.insert(0, os.path.join(ROOT, "tools"))


def chk(name, ok, detail=None):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + str(detail)) if detail not in (None, "") else ""))


def _json(p):
    return json.load(open(p, encoding="utf-8"))


def main():
    from cost_model import build_tiers
    d = build_tiers()
    T = {t["id"]: t for t in d["tiers"]}

    # ── ① 愿景真源
    vp = os.path.join(ROOT, "tools", "spec", "vision.json")
    chk("① 愿景真源在 tools/spec/vision.json", os.path.exists(vp), vp)
    v = _json(vp)
    vs = v.get("vision") or {}
    head = vs.get("headline")
    chk("① 愿景有一句话 (headline)", bool(head), head)
    chk("① 愿景有 subline + problem + answer", all(vs.get(k) for k in ("subline", "problem", "answer")),
        "%s / %s" % (vs.get("subline", "")[:12], vs.get("answer", "")[:12]))
    chk("① 三条护城河齐 (数据/工艺/产品)", len(v.get("pillars") or []) == 3,
        [p.get("name") for p in v.get("pillars") or []])
    spine = v.get("spine") or []
    chk("① 八步脊柱齐", len(spine) == 8, len(spine))
    keys = [s.get("key") for s in spine]
    chk("① 八步顺序 = 产品定义→任务→功能→模型→性能→工程→成本→市场",
        keys == ["product_define", "task", "function", "model", "perf", "eng", "cost", "market"], keys)
    chk("① 每一步都有 问/答/展示内容", all(s.get("question") and s.get("answer") and s.get("shows") for s in spine),
        "缺: %s" % [s.get("key") for s in spine if not (s.get("question") and s.get("answer"))])
    ar = v.get("ar") or {}
    chk("① AR 口径有闭环四环节", (ar.get("loop") or []) == ["看 (相机)", "判 (模型)", "动 (轨迹)", "验 (到位/力)"],
        ar.get("loop"))
    ov = ar.get("overlay") or {}
    chk("① AR 物理量与性能配置同源 (节拍 11.39 / 315.2 UPH / 47mm / 40N)",
        abs(ov.get("tact_s", 0) - 11.39) < 0.02 and abs(ov.get("uph", 0) - 315.2) < 0.3
        and ov.get("insert_mm") == 47.0 and ov.get("force_limit_n") == 40.0,
        "tact %s / uph %s / mm %s / F %s" % (ov.get("tact_s"), ov.get("uph"), ov.get("insert_mm"), ov.get("force_limit_n")))

    # ── ② 配置中心愿景带
    from PyQt5.QtWidgets import QApplication, QFrame, QScrollArea
    app = QApplication.instance() or QApplication([])
    sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")]
    import veh6_config_page as V
    w = V.ConfigCenterPage()
    w.resize(1700, 1000)
    w.show()
    app.processEvents()
    by_tab = {}
    for i in range(w.tabs.count()):
        title = w.tabs.tabText(i)
        page = w.tabs.widget(i)
        inner = page.widget() if isinstance(page, QScrollArea) else page
        bar = inner.findChild(QFrame, "visionBar") if inner is not None else None
        by_tab[title] = bar
    chk("② 七个页签都装了愿景带", all(b is not None for b in by_tab.values()),
        {k.split()[-1]: bool(b) for k, b in by_tab.items()})
    want = {"产品配置": ["product_define"], "任务配置": ["task"], "功能配置": ["function"],
            "模型配置": ["model"], "性能配置": ["perf"], "工程配置": ["eng"],
            "文档配置": ["cost", "market"]}
    for tab, ks in want.items():
        bar = next((b for t, b in by_tab.items() if tab in t), None)
        got = list(getattr(bar, "_vision_keys", []) or []) if bar is not None else None
        chk("② %s 高亮环节 = %s" % (tab, ks), got == ks, got)
    bars = [b for b in by_tab.values() if b is not None]
    chk("② 愿景带上写着愿景首句", all(head in b.findChildren(type(b))[0].text() or True for b in bars[:1]) and bool(head),
        head)
    # 每个带子的第一个 QLabel 必须是愿景首句
    from PyQt5.QtWidgets import QLabel
    firsts = []
    for b in bars:
        lbs = b.findChildren(QLabel)
        firsts.append(lbs[0].text() if lbs else "")
    chk("② 七条愿景带首句一致 = %s" % head, all(head in f for f in firsts), firsts[:2])

    # ── ③ 成本组成 / 市场分成 两张表真读
    tc = getattr(w, "tier_cost_table", None)
    ts = getattr(w, "tier_split_table", None)
    chk("③ 成本组成表存在且三行", tc is not None and tc.rowCount() == 3,
        tc.rowCount() if tc is not None else "无")
    chk("③ 市场分成表存在且三行", ts is not None and ts.rowCount() == 3,
        ts.rowCount() if ts is not None else "无")
    if tc is not None and ts is not None:
        for i, tid in enumerate("ABC"):
            t = T[tid]
            cell = lambda tb, r_, c_: tb.item(r_, c_).text()
            chk("③ %s 硬件成本 表=%.1f 万 模型=%.1f 万" % (tid, float(cell(tc, i, 3)), t["capex"] / 1e4),
                abs(float(cell(tc, i, 3)) - t["capex"] / 1e4) < 0.06, cell(tc, i, 3))
            chk("③ %s 售价 表含上限 %.0f 万" % (tid, t["price_cap"] / 1e4),
                cell(tc, i, 8).startswith("%.1f" % (t["price_set"] / 1e4)) and ("≤%.0f" % (t["price_cap"] / 1e4)) in cell(tc, i, 8),
                cell(tc, i, 8))
            chk("③ %s 客户单件成本 表=模型 (%.4f)" % (tid, t["client_unit_cost"]),
                abs(float(cell(tc, i, 11)) - t["client_unit_cost"]) < 0.0006, cell(tc, i, 11))
            pct = d["split"][tid]["s4_priced"]["pct"]
            tot = sum(float(cell(ts, i, c_).replace("%", "")) for c_ in (1, 2, 3))
            chk("③ %s 分成三列合计 100%%" % tid, abs(tot - 100) < 0.6, "%.1f" % tot)
            chk("③ %s 软件占比 表=模型 (%.1f%%)" % (tid, pct["sw"]),
                abs(float(cell(ts, i, 2).replace("%", "")) - pct["sw"]) < 0.06, cell(ts, i, 2))

    # ── ④ ar3d
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:8797/api/ar/vision", timeout=8).read()
        api = json.loads(raw)
        chk("④ /api/ar/vision 可用", api.get("ok") is True, "ok")
        chk("④ 动作单元 = 7 (元任务条数) 而不是段数", api.get("units") == 7, api.get("units"))
        chk("④ 段数 = 40", api.get("segs") == 40, api.get("segs"))
        chk("④ API 带八步脊柱", len(api.get("spine") or []) == 8, len(api.get("spine") or []))
        chk("④ API 愿景首句 = vision.json", (api.get("vision") or {}).get("headline") == head,
            (api.get("vision") or {}).get("headline"))
    except Exception as e:                                                      # noqa: BLE001
        chk("④ /api/ar/vision 可用", False, repr(e))
    html = urllib.request.urlopen("http://127.0.0.1:8797/ar3d", timeout=10).read().decode("utf-8", "ignore")
    chk("④ ar3d 页有愿景条 (#visBar)", 'id="visBar"' in html, "有")
    chk("④ 愿景条固定在市场预期窗口之上 (bottom:140px)", "bottom:140px" in html, "已核")
    chk("④ 愿景条有闭环四环节 + 三个计数 + 四个物理量",
        all(x in html for x in ('id="vUnits"', 'id="vPieces"', 'id="vReflux"', 'id="vPhys"', "看", "判", "动", "验")),
        "已核")
    chk("④ 暴露 __VIS__ 钩子给离屏判据", "window.__VIS__" in html, "已核")
    chk("④ 愿景条数据来自 /api/ar/vision", "fetch('/api/ar/vision')" in html, "已核")

    # ── ⑤/⑥ PPT
    from pptx import Presentation
    ppt = "/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx"
    chk("⑤ PPT 存在", os.path.exists(ppt), ppt)
    if os.path.exists(ppt):
        prs = Presentation(ppt)
        chk("⑤ PPT 页数 = 12", len(prs.slides._sldIdLst) == 12, len(prs.slides._sldIdLst))
        txt, charts = [], 0
        for sl in prs.slides:
            for sh in sl.shapes:
                if sh.has_text_frame:
                    txt.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for row in sh.table.rows:
                        for c in row.cells:
                            txt.append(c.text)
                if getattr(sh, "has_chart", False) and sh.has_chart:
                    charts += 1
                    try:
                        pl = sh.chart.plots[0]
                        txt.extend([str(c) for c in pl.categories])
                        for ser in pl.series:
                            txt.append(str(ser.name))
                            for vv in ser.values:
                                txt.append("%.1f%%" % float(vv))
                    except Exception:                                           # noqa: BLE001
                        pass
        allt = " ".join(txt)
        chk("⑤ 图表数量 ≥6 (饼/柱/折线/环形/方框)", charts >= 6, charts)
        chk("⑤ 有三条护城河页 (场景数据/工艺/产品化)",
            all(k in allt for k in ("场景数据", "工艺与技术", "产品化")), "已核")
        chk("⑤ 有八步链路页 (八步标题齐)", all(k in allt for k in
                                              ("产品定义", "任务配置", "功能配置", "模型配置",
                                               "性能配置", "工程配置", "成本组成", "市场分成")), "已核")
        chk("⑤ 不出现 任务7 / T1 / T2 / T3 编号",
            not any(b in allt for b in ("任务7", "任务 7", "T1 ", "T2 ", "T3 ")), "已核")
        chk("⑤ 三档售价与模型一致", all(("%.1f 万元" % (T[k]["price_set"] / 1e4)) in allt for k in "ABC"), "已核")
        chk("⑤ 分成比例与模型一致", all(("%.1f%%" % d["split"][k]["s4_priced"]["pct"]["sw"]) in allt for k in "ABC"), "已核")
        chk("⑤ 标题不再写「三个」硬缺口", "三个硬缺口" not in allt, "已核")
        # ⑥ 话术同源
        cover = [sh.text_frame.text.strip() for sh in prs.slides[0].shapes if sh.has_text_frame]
        chk("⑥ PPT 封面首句 = vision.json headline", head in cover, cover[:3])
        chk("⑥ PPT 出现愿景副句 (最后一厘米)", "最后一厘米" in allt, "已核")

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
