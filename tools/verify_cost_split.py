#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 三档成本 / 三张工单 / 产量仿真 / 市场预期 dock / 三方分成 PPT 是否真的对得上。

四段:
  ① 成本模型自洽: 独立重算 capex/单位成本/分成比例, 与 cost_model.build_tiers() 对账; 节拍必须取 11.42 (不是 19.93)
  ② 三张工单: 文件在 + order_no 正确 + cost 快照与模型一致 + 工单配置页真能看到
  ③ ar3d 演练: /api/ar/cost 可用 + 页面装好独立 dock + 产量公式与 UPH 一致
  ④ PPT: 10 页 + 含三档关键数字 + 三方分成三方案 + 推荐混合制
跑法: gui-venv311/bin/python tools/verify_cost_split.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cost_model import build_tiers                                             # noqa: E402

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + str(detail)) if detail else ""))


def main():
    d = build_tiers()
    spec = json.load(open(os.path.join(ROOT, "tools", "spec", "cost_model.json"), encoding="utf-8"))
    by = {t["id"]: t for t in d["tiers"]}

    # ── ① 成本自洽
    chk("① 三档 A/B/C 且算力 30/80/300 TOPS",
        [t["id"] for t in d["tiers"]] == ["A", "B", "C"]
        and [t["tops"] for t in d["tiers"]] == [30, 80, 300],
        [(t["id"], t["tops"]) for t in d["tiers"]])
    chk("① 节拍取自 11.42 (不是 19.93 —— cycles≠件数)", abs(d["tact_s"] - 11.42) < 0.02, d["tact_s"])
    chk("① 几何产能 = 3600/节拍", abs(d["uph_geo"] - 3600.0 / d["tact_s"]) < 0.2, d["uph_geo"])
    for t in spec["tiers"]:
        r = by[t["id"]]
        cap = sum(float(x["qty"]) * float(x["unit"]) for x in t["bom"])
        nre = sum(float(x["qty"]) * float(x["unit"]) for x in t["nre"])
        chk("① %s capex 独立重算一致" % t["id"], abs(cap - r["capex"]) < 1, "%s vs %s" % (cap, r["capex"]))
        chk("① %s NRE 独立重算一致" % t["id"], abs(nre - r["nre_sum"]) < 1, "%s vs %s" % (nre, r["nre_sum"]))
        uc = (r["dep_year"] + r["opex_year"] + r["nre_amort"]) / r["pieces_year"]
        chk("① %s 单件成本 = (折旧+运营+NRE摊销)/产量" % t["id"], abs(uc - r["unit_cost"]) < 0.002,
            "%.5f vs %.5f" % (uc, r["unit_cost"]))
        chk("① %s 单件毛利 = 单价 − 单件成本" % t["id"],
            abs((r["price_per_piece"] - r["unit_cost"]) - r["unit_margin"]) < 0.002,
            "%.4f" % r["unit_margin"])
        chk("① %s 回收期 = (capex+NRE)/年现金" % t["id"],
            abs((r["capex"] + r["nre_sum"]) / (r["revenue_year"] - r["opex_year"]) - r["payback_years"]) < 0.02,
            "%.2f 年" % r["payback_years"])
        sp = d["split"][t["id"]]
        for k in ("s1_invest", "s2_value", "s3_hybrid"):
            tot = sum(sp[k]["pct"].values())
            chk("① %s %s 分成合计 100%%" % (t["id"], k), abs(tot - 100) < 0.6, "%.1f" % tot)
        chk("① %s 混合制 = 硬件+软件许可20%%+运营0.02/件" % t["id"],
            abs(sp["s3_hybrid"]["abs"]["sw"] - r["revenue_year"] * 0.20) < 1
            and abs(sp["s3_hybrid"]["abs"]["op"] - r["pieces_year"] * 0.02) < 1,
            "sw %.0f · op %.0f" % (sp["s3_hybrid"]["abs"]["sw"], sp["s3_hybrid"]["abs"]["op"]))
    chk("① 三档单件成本递增 (A<B<C)", by["A"]["unit_cost"] < by["B"]["unit_cost"] < by["C"]["unit_cost"],
        [round(by[k]["unit_cost"], 4) for k in "ABC"])
    chk("① 三档毛利率在 50~85%% 之间 (口径合理)", all(50 <= by[k]["gross_margin_pct"] <= 85 for k in "ABC"),
        [by[k]["gross_margin_pct"] for k in "ABC"])

    # ── ② 三张工单
    for tid, no in (("A", "T1"), ("B", "T2"), ("C", "T3")):
        fp = os.path.join(ROOT, "config", "orders", "BS_SCN-07-AOI-%s.json" % no)
        chk("② %s 工单文件在" % no, os.path.exists(fp), os.path.relpath(fp, ROOT))
        if os.path.exists(fp):
            o = json.load(open(fp, encoding="utf-8"))
            ident = o.get("identity") or {}
            chk("② %s order_no 正确 (%s)" % (no, ident.get("order_no")),
                ident.get("order_no") == "BS-SCN-07-AOI-%s-0001" % no, ident.get("order_no"))
            chk("② %s identity.tier = %s" % (no, tid), ident.get("tier") == tid, ident.get("tier"))
            co = o.get("cost") or {}
            r = by[tid]
            chk("② %s 工单 cost 快照与模型一致" % no,
                abs(float(co.get("capex") or 0) - r["capex"]) < 1
                and abs(float(co.get("unit_cost") or 0) - r["unit_cost"]) < 0.002
                and int(co.get("pieces_year") or 0) == r["pieces_year"],
                "capex %s / unit %s / 年产 %s" % (co.get("capex"), co.get("unit_cost"), co.get("pieces_year")))
            chk("② %s 工单写了产能与单价" % no,
                "件/h" in str((o.get("targets") or {}).get("产能 UPH", ""))
                and "元/件" in str((o.get("targets") or {}).get("加工单价", "")),
                (o.get("targets") or {}).get("加工单价"))

    # 工单配置页真的看得到三张
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import veh6_config_page as V
    page = V.ConfigCenterPage()
    # 工单表按老倪 2026-10-19 的定案放在「📄 文档配置」页 (工单配置 tab 已并入), 这里不看 tab 名只看表
    rows = getattr(page, "order_table", None)
    _tabof = "?"
    if rows is not None:
        for i in range(page.tabs.count()):
            _t = page.tabs.widget(i)
            if _t is not None and _t.isAncestorOf(rows):
                _tabof = page.tabs.tabText(i)
                break
    chk("② 工单表在配置中心页内 (%s)" % _tabof, rows is not None, rows.rowCount() if rows else "无")
    if rows is not None:
        chk("② 工单表存在", rows is not None, rows.rowCount() if rows else "无")
        if rows is not None:
            nos = [(rows.item(r, 0).text() if rows.item(r, 0) else "") for r in range(rows.rowCount())]
            for no in ("T1", "T2", "T3"):
                chk("② 工单表含 %s" % no, any(no in x for x in nos), [x for x in nos if no in x][:2])
            chk("② 工单表行数 = 真源工单数", rows.rowCount() == len([f for f in os.listdir(os.path.join(ROOT, "config", "orders")) if f.startswith("BS_")]),
                "%d 行" % rows.rowCount())

    # ── ③ ar3d 演练
    import urllib.request
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:8797/api/ar/cost", timeout=6).read().decode()
        api = json.loads(raw)
    except Exception as e:                                                      # noqa: BLE001
        api = None
        chk("③ /api/ar/cost 可用", False, repr(e))
    if api:
        chk("③ /api/ar/cost 可用", api.get("ok") is True, "ok")
        chk("③ API 三档与模型一致",
            [t["unit_cost"] for t in api["tiers"]] == [by[k]["unit_cost"] for k in "ABC"],
            [t["unit_cost"] for t in api["tiers"]])
        chk("③ API 带三张工单且都在盘上", len(api["orders"]) == 3 and all(o["exists"] for o in api["orders"]),
            [o["order_no"] for o in api["orders"]])
        chk("③ API 市场预期 8h 班产量 = UPH×8×OEE",
            all(abs(m["pieces_per_shift8h"] - api["uph_geo"] * 8 * by[m["tier"]]["oee"]) < 2 for m in api["market"]),
            [(m["tier"], m["pieces_per_shift8h"]) for m in api["market"]])
        chk("③ API 带三方分成三方案", all(k in (api["split"].get("C") or {}) for k in ("s1_invest", "s2_value", "s3_hybrid")),
            list((api["split"].get("C") or {}).keys()))
    html = open(os.path.join(ROOT, "tools", "web", "tcp-ar.html"), encoding="utf-8").read()
    chk("③ ar3d 页装了独立 dock (#mktDock)", 'id="mktDock"' in html, "有" if 'id="mktDock"' in html else "缺")
    chk("③ dock 固定在屏幕下方 (position:fixed bottom:0)", "position:fixed;left:0;right:0;bottom:0" in html, "已核")
    chk("③ 主区不被遮挡 (body padding-bottom)", "body{padding-bottom:" in html, "已核")
    chk("③ dock 有工单选择 + 安排生产 + 倍速", all(x in html for x in ('id="mkTier"', 'id="mkStart"', 'id="mkSpeed"')),
        "已核")
    chk("③ dock 显示 9 个指标 + 市场预期 + 三方分成",
        all(('id="%s"' % k) in html for k in ("mkPc", "mkHr", "mkUph", "mkVal", "mkBatch", "mkPy", "mkRev",
                                             "mkGross", "mkPb", "mkUnit", "mkExpect", "mkSplit")), "已核")
    chk("③ 暴露 __PROD__ 测试钩子", "window.__PROD__" in html, "已核")
    chk("③ dock 数据来自 /api/ar/cost (不另存数字)", "fetch('/api/ar/cost')" in html, "已核")
    # 产量公式 (与页面一致): pieces = floor(simT / tact)
    simT = 3600 * 60                                                        # tick(3600) @ x60 = 60 演练小时
    pieces = int(simT / d["tact_s"])
    chk("③ 演练 60h 产量与节拍一致", abs(pieces - 18914) <= 3, "%d 件 (期望 ≈18914)" % pieces)
    chk("③ 演练产值 = 件数 × 单价", abs(pieces * by["A"]["price_per_piece"] - 6619.9) < 5,
        "%.2f 元" % (pieces * by["A"]["price_per_piece"]))

    # ── ④ PPT
    from pptx import Presentation
    ppt = os.path.join(ROOT, "docs", "deliverables", "任务7_三档成本与三方分成.pptx")
    chk("④ PPT 存在", os.path.exists(ppt), os.path.relpath(ppt, ROOT))
    if os.path.exists(ppt):
        prs = Presentation(ppt)
        chk("④ PPT 页数 ≥9", len(prs.slides._sldIdLst) >= 9, "%d 页" % len(prs.slides._sldIdLst))
        txt = []
        for sl in prs.slides:
            for sh in sl.shapes:
                if sh.has_text_frame:
                    txt.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    for row in sh.table.rows:
                        for c in row.cells:
                            txt.append(c.text)
        allt = " ".join(txt)
        for kw, why in (("%.4f" % by["A"]["unit_cost"], "A 单件成本"), ("%.4f" % by["C"]["unit_cost"], "C 单件成本"),
                        ("315.2", "UPH"), ("三方分成", "三方分成页"),
                        ("混合制", "推荐方案"), ("T1", "工单 T1"), ("T3", "工单 T3"),
                        ("机器人本体硬件", "三方名")):
            chk("④ PPT 含 %s (%s)" % (kw, why), kw in allt, "有" if kw in allt else "缺")
        for k in "ABC":
            pct = d["split"][k]["s3_hybrid"]["pct"]
            chk("④ PPT 含 %s 档混合制比例 (%.1f/%.1f/%.1f)" % (k, pct["hw"], pct["sw"], pct["op"]),
                all(("%.1f%%" % pct[x]) in allt for x in ("hw", "sw", "op")), "已核")

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
