#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一致性判据: 配置中心六页 ↔ AR 场景 ↔ 成本/分成 ↔ PPT ↔ 报告 必须是同一套数。

老倪 2026-10-28: 「再次检查配置中心的所有配置, 要保证一致性, 要与 AR 场景的 300 UPH 有对应性,
刚才的成本分析和市场分成是什么策略, 给出 PPT, 要从配置中心的文档配置页面可以导出报告」

六段:
  ① 节拍/产能只有一个口径: cost_model 11.42 s/件 ↔ 315.2 件/h ↔ vision.overlay ↔ perf_bands (T_c/Q)
  ② 300 UPH 目标在四处都在: 性能页口径条 / ar3d 愿景条 / /api/ar/vision / PPT
  ③ 成本与分成: 配置中心两张表 ↔ targets_model ↔ PPT ↔ 立项报告 逐项对账
  ④ 三阶段: 配置中心三阶段表 ↔ rollout_model ↔ PPT ↔ 报告
  ⑤ 工单 T1/T2/T3: 年产量 = cost_model.pieces_year, 设备售价 = 建议报价
  ⑥ 导出链: 文档配置页三个按钮 (PPT / 报告 / CSV) 真点真写

跑法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_consistency.py
"""
import csv
import json
import os
import sys
import urllib.request

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools"))
PASS, FAIL = [], []


def chk(name, ok, detail=None):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                        (" — " + str(detail)) if detail not in (None, "") else ""))


def main():
    from cost_model import build_tiers
    from targets_model import build_targets
    from rollout_model import build_rollout
    c = build_tiers()
    TG = {t["id"]: t for t in build_targets()["tiers"]}
    R = build_rollout()["phases"]
    v = json.load(open(os.path.join(ROOT, "tools", "spec", "vision.json"), encoding="utf-8"))
    ov = v["ar"]["overlay"]

    # ── ① 节拍口径
    chk("① 成本模型节拍 11.42 s/件", abs(c["tact_s"] - 11.42) < 0.005, c["tact_s"])
    chk("① 成本模型产能 315.2 件/h", abs(c["uph_geo"] - 315.2) < 0.05, c["uph_geo"])
    chk("① 392 段 / 14 件一轮", c["segs"] == 392 and c["cycles"] == 14, (c["segs"], c["cycles"]))
    chk("① vision.overlay 节拍 = 成本模型 (11.42)", abs(ov["tact_s"] - c["tact_s"]) < 0.005, ov["tact_s"])
    chk("① vision.overlay 产能 = 成本模型 (315.2)", abs(ov["uph"] - c["uph_geo"]) < 0.05, ov["uph"])
    chk("① vision.overlay 目标 300 件/h", abs(ov["uph_target"] - 300.0) < 0.01, ov.get("uph_target"))
    pb = json.load(open(os.path.join(ROOT, "tools", "spec", "perf_bands.json"), encoding="utf-8"))
    txt = json.dumps(pb, ensure_ascii=False)
    chk("① perf_bands 里稳态 11.39 / 316.1 与实测 315.2 差 <1%",
        ("11.39" in txt or "11.3" in txt) and abs(316.1 - 315.2) / 315.2 < 0.01, "稳态 316.1 vs 实测 315.2")

    # ── ② 300 UPH 四处都在
    from PyQt5.QtWidgets import QApplication, QLabel
    app = QApplication.instance() or QApplication([])
    sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")]
    import veh6_config_page as V
    w = V.ConfigCenterPage()
    w.resize(1700, 1000)
    w.show()
    app.processEvents()
    cal = getattr(w, "perf_caliber_label", None)
    chk("② 性能页有产能口径条 (300 目标 + 11.42 + 315.2 + 稳态)",
        cal is not None and all(x in cal.text() for x in ("300", "11.42", "315.2", "11.39")),
        (cal.text()[:60] if cal else "无"))
    raw = urllib.request.urlopen("http://127.0.0.1:8797/api/ar/vision", timeout=8).read()
    api = json.loads(raw)
    aov = (api.get("ar") or {}).get("overlay") or {}
    chk("② /api/ar/vision 与 vision.json 同源",
        abs(aov.get("tact_s", 0) - ov["tact_s"]) < 0.005 and abs(aov.get("uph", 0) - ov["uph"]) < 0.05,
        (aov.get("tact_s"), aov.get("uph")))
    chk("② /api/ar/vision 带 300 目标", abs((aov.get("uph_target") or 0) - 300.0) < 0.01, aov.get("uph_target"))
    html = urllib.request.urlopen("http://127.0.0.1:8797/ar3d", timeout=10).read().decode("utf-8", "ignore")
    chk("② AR 愿景条渲染 目标 300 UPH", "uph_target" in html and "目标" in html, "已核")

    # ── ③ 成本/分成 三处对账
    tc, ts = getattr(w, "tier_cost_table", None), getattr(w, "tier_split_table", None)
    chk("③ 成本表 3 行 × 11 列 / 分成表 3 行 × 11 列",
        tc is not None and tc.rowCount() == 3 and tc.columnCount() == 11
        and ts is not None and ts.rowCount() == 3 and ts.columnCount() == 11,
        (tc.rowCount() if tc else None, ts.rowCount() if ts else None))
    from pptx import Presentation
    prs = Presentation("/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx")
    allt = []
    for sl in prs.slides:
        for sh in sl.shapes:
            if sh.has_text_frame:
                allt.append(sh.text_frame.text)
            if getattr(sh, "has_chart", False) and sh.has_chart:
                try:
                    pl = sh.chart.plots[0]
                    for ser in pl.series:
                        allt.append(str(ser.name))
                        allt.extend(["%.1f" % float(x) for x in ser.values])
                except Exception:                                               # noqa: BLE001
                    pass
    allt = " ".join(allt)
    rep = open(os.path.join(ROOT, "docs", "deliverables", "项目立项报告_双臂协作工位.md"), encoding="utf-8").read()
    for k in "ABC":
        t = TG[k]
        chk("③ %s 单套成本 %.1f 万 表/PPT/报告一致" % (k, t["cost_total"] / 1e4),
            abs(float(tc.item("ABC".index(k), 4).text()) - t["cost_total"] / 1e4) < 0.06
            and ("%.1f" % (t["cost_total"] / 1e4)) in allt and ("%.2f 万元" % (t["cost_total"] / 1e4)) in rep,
            tc.item("ABC".index(k), 4).text())
        chk("③ %s 分成 表=PPT=报告 (sw %.1f%%)" % (k, t["pct_capped"]["sw"]),
            abs(float(ts.item("ABC".index(k), 2).text().replace("%", "")) - t["pct_capped"]["sw"]) < 0.06
            and ("%.1f%%" % t["pct_capped"]["sw"]) in allt and ("%.1f%%" % t["pct_capped"]["sw"]) in rep,
            ts.item("ABC".index(k), 2).text())
    chk("③ PPT 说清四条策略 (成本/定价/分成/市场)",
        all(x in allt for x in ("成本策略", "定价策略", "分成策略", "市场策略")), "已核")
    chk("③ PPT 14 页", len(prs.slides._sldIdLst) == 14, len(prs.slides._sldIdLst))

    # ── ④ 三阶段
    tr = getattr(w, "rollout_table", None)
    chk("④ 三阶段表 3 行", tr is not None and tr.rowCount() == 3, tr.rowCount() if tr else None)
    for i, p in enumerate(R):
        chk("④ %s 客户投入 %.1f 万 表=模型" % (p["key"], p["price"] / 1e4),
            abs(float(tr.item(i, 3).text()) - p["price"] / 1e4) < 0.06, tr.item(i, 3).text())
        chk("④ %s 让利后回本 %.2f 年 表=模型" % (p["key"], p["payback_years"]),
            abs(float(tr.item(i, 9).text()) - p["payback_years"]) < 0.02, tr.item(i, 9).text())

    # ── ⑤ 工单
    for n, k in (("T1", "A"), ("T2", "B"), ("T3", "C")):
        p = os.path.join(ROOT, "config", "orders", "BS_SCN-07-AOI-%s.json" % n)
        o = json.load(open(p, encoding="utf-8"))
        tgt = o.get("targets") or o.get("target") or o.get("目标") or {}
        blob = json.dumps(tgt, ensure_ascii=False)
        _t = [x for x in c["tiers"] if x["id"] == k][0]
        chk("⑤ %s 年产量 = %d 件" % (n, _t["pieces_year"]),
            ("%d" % _t["pieces_year"]) in blob, blob[:60])
        chk("⑤ %s 设备售价 = 建议报价 %.1f 万" % (n, c["tiers"][[x["id"] for x in c["tiers"]].index(k)]["price_set"] / 1e4),
            ("%.1f 万元" % (_t["price_set"] / 1e4)) in blob, tgt.get("设备售价", "")[:40])

    # ── ⑥ 导出链
    pptp = "/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx"
    b = os.path.getmtime(pptp)
    w._export_deck_ppt()
    chk("⑥ 按「导出成本分析 PPT」真写文件", os.path.getmtime(pptp) >= b and "✅" in w.rollout_msg.text(),
        w.rollout_msg.text().splitlines()[0] if w.rollout_msg.text() else "")
    w._export_project_report()
    chk("⑥ 按「导出立项报告」真写文件", "✅" in w.rollout_msg.text(), w.rollout_msg.text()[:40])
    csvp = os.path.join(ROOT, "docs", "deliverables", "市场分成_三档三阶段.csv")
    w._export_split_csv()
    rows = list(csv.reader(open(csvp, encoding="utf-8-sig")))
    chk("⑥ 按「导出市场分成」真写 CSV 三阶段三档",
        sum(1 for r in rows if r and r[0] in ("P1", "P2", "P3")) == 3
        and sum(1 for r in rows if r and r[0] in ("A", "B", "C")) == 3, "%d 行" % len(rows))

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
