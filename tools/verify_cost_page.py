#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_cost_page.py — 配置中心「💰 成本/报价」页判据 (逐项 ✅/❌ + 证据)。

老倪 2026-10-19: 「从配置中心，直接预计出成本价格」。
给定口径: 硬件 20.3 万 + 软件 16 万 = 36.3 万; 1 工位 × 2 班 × 1 人 × 9 万/人·年 = 18 万/年;
          静态回本 2.02 年; 替代力控臂 31.8 万 ⇒ 1.77 年。

判据:
  ① 页签在             「💰 成本/报价」页签存在, 且控件齐 (BOM表/6假设/结果4行/4按钮)
  ② 默认口径           列表值 = 20.3 / 16.0 / 36.3 万, 年节省 18.0 万, 回本 2.02 年
  ③ 页面文字           结果标签里真出现 36.3 万 / 18.0 万 / 2.02 年 (不是只存变量)
  ④ 改工位数即现算      stations 1→2: 年节省 36.0 万, 回本 1.01 年 (valueChanged 真触发)
  ⑤ 改人力成本          labor 9→10 万: 年节省 20.0 万, 回本 1.82 年
  ⑥ 替代臂             单套 31.8 万 ⇒ 回本 1.77 年 (默认口径下)
  ⑦ 同源               页面结果 == tools/cost_model.py 对同一组输入的计算 (逐字段)
  ⑧ BOM                 表行数 == 真源硬件项数+1, 合计行 = 203,000
  ⑨ 写回真源+回读       改 stations=2 → 写入 → 真源 line.stations==2 且回读 ok; 备份生成; 之后字节级还原
  ⑩ 导出 JSON           zmax_data/cost/cost_estimate_*.json 生成, total_first 与页面一致; 导出物自清理
  ⑪ 复制                剪贴板拿到 TSV, 含「单套合计」
  ⑫ 零回归              其余页签仍在 / 画布真源 mtime 不变 / 真源跑完与原字节一致

用法: QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_cost_page.py
退出码: 0 = 全过; 2 = 有 ❌。
"""
from __future__ import annotations

import glob
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools"),
           os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TRUTH = os.path.join(ROOT, "config", "platform", "zmax_cost_model.json")
CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")

OK, BAD = [], []


def chk(item, name, ok, ev=""):
    (OK if ok else BAD).append((item, name))
    print("  %s [%s] %s%s" % ("✅" if ok else "❌", item, name,
                              ("\n        ← " + str(ev)) if ev else ""))
    return bool(ok)


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    import cost_model as CM
    import veh6_config_page as V

    orig_bytes = open(TRUTH, "rb").read()
    canvas_mt = os.path.getmtime(CANVAS)

    pg = V.ConfigCenterPage(model_page=None)
    e = pg._cost_refresh()
    ev0 = dict(pg._cost_e)

    print("\n【① 页签与控件】")
    titles = [pg.tabs.tabText(i) for i in range(pg.tabs.count())]
    # 2026-10-19 老倪: 「将成本/报价 商业模式的内容，都迁移到 文档配置里」⇒ 不再有独立页签
    _di = pg._tab_index_by_title("文档配置")
    _host = pg.tabs.widget(_di) if _di >= 0 else None
    _in_doc = _host is not None and (_host.isAncestorOf(pg._cost_bom) or _host is pg._cost_bom)
    chk("①a", "💰 成本/报价 块在「📄 文档配置」页内 (独立页签已取消)",
        _in_doc and not any("成本/报价" in t for t in titles),
        "在文档配置页=%s · 页签=%s" % (_in_doc, titles))
    chk("①b", "BOM 表 + 6 个假设 + 结果 4 行 + 日志行都在",
        all(hasattr(pg, a) for a in ("_cost_bom", "_cost_in", "_cost_l_total", "_cost_l_annual",
                                     "_cost_l_payback", "_cost_l_alt", "_cost_log")),
        "假设控件: %s" % list(pg._cost_in))
    chk("①c", "页签 = 北斗七星 7 页 (文档配置在末位)", len(titles) == 7 and "文档配置" in titles[-1], titles[-3:])

    print("\n【② 默认口径 = 老倪给的数】")
    chk("②a", "硬件 20.3 万", abs(e["hardware"] - 203000) < 1e-6, "%.0f 元" % e["hardware"])
    chk("②b", "软件 16 万", abs(e["software"] - 160000) < 1e-6, "%.0f 元" % e["software"])
    chk("②c", "单套 36.3 万", abs(e["total_first"] - 363000) < 1e-6, "%.0f 元" % e["total_first"])
    chk("②d", "年节省 18 万", abs(e["annual_save"] - 180000) < 1e-6, "%.0f 元" % e["annual_save"])
    chk("②e", "静态回本 2.02 年", e["payback_years"] == 2.02, e["payback_years"])

    print("\n【③ 页面文字真有这些数】")
    t_total = pg._cost_l_total.text()
    t_ann = pg._cost_l_annual.text()
    t_pay = pg._cost_l_payback.text()
    t_alt = pg._cost_l_alt.text()
    chk("③a", "单套投入行含 36.3 万", "36.3 万" in t_total, t_total)
    chk("③b", "年节省行含 18.0 万", "18.0 万" in t_ann, t_ann)
    chk("③c", "回本行含 2.02 年", "2.02 年" in t_pay, t_pay)

    print("\n【④ 改工位数 → 现算 (1→2)】")
    pg._cost_in["stations"].setValue(2)
    app.processEvents()
    e2 = dict(pg._cost_e)
    chk("④a", "年节省变 36 万", abs(e2["annual_save"] - 360000) < 1e-6, "%.0f 元" % e2["annual_save"])
    chk("④b", "回本变 1.01 年", e2["payback_years"] == 1.01, e2["payback_years"])
    chk("④c", "标签同步 (36.0 万 / 1.01 年)",
        "36.0 万" in pg._cost_l_annual.text() and "1.01 年" in pg._cost_l_payback.text(),
        pg._cost_l_payback.text())

    print("\n【⑤ 改人力成本 9 → 10 万】")
    pg._cost_in["stations"].setValue(1)
    pg._cost_in["labor"].setValue(10.0)
    app.processEvents()
    e3 = dict(pg._cost_e)
    chk("⑤a", "年节省 = 2 人 × 10 万 = 20 万", abs(e3["annual_save"] - 200000) < 1e-6,
        "%.0f 元" % e3["annual_save"])
    chk("⑤b", "回本 1.82 年", e3["payback_years"] == 1.82, e3["payback_years"])

    print("\n【⑥ 替代力控臂】")
    chk("⑥a", "单套 31.8 万 / 回本 1.77 年",
        abs(e3["total_alt"] - 318000) < 1e-6 and e3["payback_years_alt"] == 1.59,
        "alt_total=%.0f payback_alt=%s" % (e3["total_alt"], e3["payback_years_alt"]))
    pg._cost_in["labor"].setValue(9.0)
    app.processEvents()
    chk("⑥b", "回默认人力后替代臂回本 1.77 年", pg._cost_e["payback_years_alt"] == 1.77,
        pg._cost_e["payback_years_alt"])
    chk("⑥c", "说明行写清「不计折现/质量损耗/增产」",
        "不计折现" in pg._cost_l_alt.text(), pg._cost_l_alt.text()[:80])

    print("\n【⑦ 同源: 页面 == cost_model.py】")
    inp = pg._cost_inputs()
    ref = CM.estimate(CM.load(), **inp)
    keys = ("hardware", "software", "total_first", "total_alt", "annual_save",
            "payback_years", "payback_years_alt")
    same = all(abs(float(pg._cost_e[k]) - float(ref[k])) < 1e-9 for k in keys)
    chk("⑦a", "7 个关键字段逐位相同", same,
        " / ".join("%s=%s" % (k, pg._cost_e[k]) for k in ("total_first", "annual_save", "payback_years")))

    print("\n【⑧ BOM 表 = 真源逐项】")
    d = CM.load()
    n_hw = len(d.get("hardware") or [])
    chk("⑧a", "行数 = 硬件项数 + 合计行", pg._cost_bom.rowCount() == n_hw + 1,
        "%d 行 (硬件 %d 项)" % (pg._cost_bom.rowCount(), n_hw))
    chk("⑧b", "合计行 = 203,000", pg._cost_bom.item(n_hw, 2).text() == "203,000",
        pg._cost_bom.item(n_hw, 2).text())

    print("\n【⑨ 写回真源 + 回读 + 还原】")
    before_baks = set(glob.glob(TRUTH + ".bak_*"))
    pg._cost_in["stations"].setValue(2)
    pg._cost_save()
    back = json.load(open(TRUTH, encoding="utf-8"))
    new_baks = set(glob.glob(TRUTH + ".bak_*")) - before_baks
    chk("⑨a", "真源 line.stations 真变 2", back["line"]["stations"] == 2, back["line"])
    chk("⑨b", "日志明写回读校验通过", "回读校验通过" in pg._cost_log.text(), pg._cost_log.text()[:90])
    chk("⑨c", "生成了备份", len(new_baks) == 1, list(new_baks))
    chk("⑨d", "派生值不落盘 (真源里没有 total/payback 键)",
        not any(k in back for k in ("total", "payback_years", "annual_save")),
        sorted(back.keys()))
    open(TRUTH, "wb").write(orig_bytes)                      # 字节级还原
    for b in new_baks:
        os.remove(b)
    chk("⑨e", "真源已字节级还原", open(TRUTH, "rb").read() == orig_bytes)

    print("\n【⑩ 导出 JSON】")
    pg._cost_refresh()
    before = set(glob.glob(os.path.join(ROOT, "zmax_data", "cost", "cost_estimate_*.json")))
    pg._cost_export()
    new = set(glob.glob(os.path.join(ROOT, "zmax_data", "cost", "cost_estimate_*.json"))) - before
    ok10 = False
    ev10 = "无新文件"
    if new:
        p = sorted(new)[-1]
        j = json.load(open(p, encoding="utf-8"))
        ok10 = abs(float(j["total_first"]) - float(pg._cost_e["total_first"])) < 1e-6
        ev10 = "%s total_first=%s" % (os.path.basename(p), j["total_first"])
        os.remove(p)
    chk("⑩a", "导出文件生成且 total_first 与页面一致", ok10, ev10)

    print("\n【⑪ 复制】")
    pg._cost_copy()
    cb = app.clipboard().text()
    chk("⑪a", "剪贴板是 TSV 且含单套合计", "单套合计" in cb and "\t" in cb, cb.splitlines()[:3])

    print("\n【⑫ 零回归】")
    chk("⑫a", "画布真源未被碰 (mtime 不变)", os.path.getmtime(CANVAS) == canvas_mt,
        os.path.getmtime(CANVAS))
    chk("⑫b", "页签恰好 7 个 (= 北斗七星; 成本/报价 已并入文档配置)", len(titles) == 7, titles)
    chk("⑫c", "真源已还原 (== 测试前字节)", open(TRUTH, "rb").read() == orig_bytes)

    print("\n" + "=" * 68)
    print("结果: PASS %d / FAIL %d" % (len(OK), len(BAD)))
    if BAD:
        for it, nm in BAD:
            print("   ❌ [%s] %s" % (it, nm))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
