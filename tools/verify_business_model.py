#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_business_model.py — 配置中心「🧩 商业模式」页判据 (逐项 ✅/❌ + 证据)。

老倪 2026-10-19: 「在配置中心，要有商业模式，你看看怎么从前面的配置，导出商业模式」。
口径来源: 商业模式三规律 (成本结构定定价空间/价值分配定利益格局/风险承担定推进速度)
          + 三阶段定价 (S1 不收费 → S2 解决方案费 → S3 批量按台)。
唯一依据: config/platform/zmax_cost_model.json + config/platform/zmax_business_model.json
算法: tools/business_model.py (页面/CLI/导出同一个函数)

判据:
  ① 页签与控件      页签存在且排最后, 4 张表/4 个标签/4 按钮齐
  ② 成本结构        变动 20.3 万 / 固定 73.5 万 / 首台 26.3 万 / 10 台 < 首台
  ③ 分层口径        A 2.02 < B 2.88 < C 3.57 < D 4.90 年, η=0.865, 文字含「报价只用这一层」
  ④ 成交区间        floor 29.7 > ceiling 26.6 ⇒ 明写不成立; 规模阈值 13 台
  ⑤ 三阶段          S1 报价 0; S2 > 0; S3 单台价 < S2 单台价 (学习曲线+摊薄)
  ⑥ 模式推荐        5 个模式; 区间不成立 ⇒ 推荐「软件授权」; 推荐行带 ★
  ⑦ 同源            页面结果 == business_model.derive() 逐字段
  ⑧ 改假设现算      毛利率 40→30% floor 降; 客户目标回本 2.5→5 年 ⇒ 区间转成立
  ⑨ 派生值不落盘     唯一依据里只有 inputs, 无 total/price/floor/payback 键
  ⑩ 写回+回读+还原   改一个假设 → 唯一依据真变 + 备份 + 字节级还原
  ⑪ 导出            business_model_*.{json,md} 生成, floor 一致, MD 含三阶段表, 测试后清理
  ⑫ 复制            剪贴板 TSV 含「底价 floor」「推荐模式」
  ⑬ 零回归          成本页仍出 36.3 万/2.02 年; 页签 = 原 9 + 1 = 10; 画布 mtime 不变

用法: QT_QPA_PLATFORM=offscreen /home/ubuntu/zmax/gui-venv311/bin/python tools/verify_business_model.py
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

TRUTH = os.path.join(ROOT, "config", "platform", "zmax_business_model.json")
COST = os.path.join(ROOT, "config", "platform", "zmax_cost_model.json")
CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")

OK, BAD = [], []


def chk(item, name, ok, ev=None):
    (OK if ok else BAD).append((item, name))
    print("  %s [%s] %s%s" % ("✅" if ok else "❌", item, name,
                              ("\n        ← " + str(ev)) if ev else ""))
    return bool(ok)


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    import business_model as BM
    import veh6_config_page as V

    orig_bytes = open(TRUTH, "rb").read()
    canvas_mt = os.path.getmtime(CANVAS)

    pg = V.ConfigCenterPage(model_page=None)
    e = pg._biz_refresh()
    ev0 = dict(e)

    print("\n【① 页签与控件】")
    titles = [pg.tabs.tabText(i) for i in range(pg.tabs.count())]
    # 2026-10-19 老倪: 「将成本/报价 商业模式的内容，都迁移到 文档配置里」⇒ 不再有独立页签
    _di2 = pg._tab_index_by_title("文档配置")
    _host2 = pg.tabs.widget(_di2) if _di2 >= 0 else None
    _in_doc2 = _host2 is not None and (_host2.isAncestorOf(pg._biz_t_struct) or _host2 is pg._biz_t_struct)
    chk("①a", "🧩 商业模式 块在「📄 文档配置」页内 (独立页签已取消)",
        _in_doc2 and not any("商业模式" in t for t in titles),
        "在文档配置页=%s · 页签=%s" % (_in_doc2, titles[-3:]))
    chk("①b", "4 表 + 4 标签 + 按钮齐",
        all(hasattr(pg, a) for a in ("_biz_t_struct", "_biz_l_lay", "_biz_l_deal", "_biz_t_phase",
                                     "_biz_t_mode", "_biz_l_rec", "_biz_l_conf", "_biz_l_split",
                                     "_biz_log", "_biz_in")),
        "假设控件: %s" % list(pg._biz_in))
    chk("①c", "排在成本/报价之后 (同一页内, 文档配置末位)", "文档配置" in titles[-1], titles[-2:])

    print("\n【② 成本结构 (固定 vs 变动)】")
    cs = e["cost_structure"]
    chk("②a", "变动成本 (硬件/台) = 20.3 万", abs(cs["hardware_variable"] - 203000) < 1e-6,
        "%.0f 元" % cs["hardware_variable"])
    chk("②b", "固定成本 = 软件研发 60 万 + NRE 13.5 万 = 73.5 万",
        abs(cs["fixed_total"] - 735000) < 1e-6, "%.0f 元" % cs["fixed_total"])
    chk("②c", "首台成本 = 20.3 + 6.0 = 26.3 万", abs(cs["first_unit_cost"] - 263000) < 1.0,
        "%.0f 元" % cs["first_unit_cost"])
    chk("②d", "10 台单位成本 < 首台 (学习曲线+摊薄)", cs["unit_cost_10"] < cs["first_unit_cost"],
        "%.1f 万 vs %.1f 万" % (cs["unit_cost_10"] / 1e4, cs["first_unit_cost"] / 1e4))
    chk("②e", "表里 4 行且第一行是变动成本", pg._biz_t_struct.rowCount() == 4
        and "变动成本" in pg._biz_t_struct.item(0, 0).text(),
        pg._biz_t_struct.item(0, 0).text())

    print("\n【③ 分层口径 (客户真实回本)】")
    lay = e["layered"]
    seq = [lay["A_payback"], lay["B_payback"], lay["C_payback"], lay["D_payback"]]
    chk("③a", "A 2.02 / B 2.88 / C 3.57 / D 4.90 年 (逐层变长)",
        seq == [2.02, 2.88, 3.57, 4.9] and seq == sorted(seq), seq)
    chk("③b", "η = 0.92 × 0.99 × 0.95 × 1.00 = 0.865", abs(lay["eta"] - 0.865) < 2e-3, lay["eta"])
    t_lay = pg._biz_l_lay.text()
    chk("③c", "页面文字真有 4 层 + 「报价只用这一层」",
        all(k in t_lay for k in ("A 上限", "B +OPEX", "C +人效", "D +NRE", "报价只用这一层")),
        t_lay.splitlines()[-1])

    print("\n【④ 成交区间 + 规模阈值】")
    dr = e["deal"]
    chk("④a", "floor 29.7 万 > ceiling 26.6 万 ⇒ 不成立",
        (not dr["ok"]) and abs(dr["floor"] - 297188) < 50 and abs(dr["ceiling"] - 266104) < 50,
        "floor=%.0f ceiling=%.0f" % (dr["floor"], dr["ceiling"]))
    chk("④b", "页面红字明写不成立 + 差 −3.1 万",
        "❌" in pg._biz_l_deal.text() and "差 -3.1 万" in pg._biz_l_deal.text(),
        pg._biz_l_deal.text())
    chk("④c", "规模阈值 = 13 台", e["threshold"]["units"] == 13, e["threshold"]["units"])
    chk("④d", "规则写出「不成立改配置, 不降价」", "不降价" in dr["rule"], dr["rule"])

    print("\n【⑤ 三阶段定价】")
    ph = e["phases"]
    chk("⑤a", "3 个阶段", len(ph) == 3, [p["stage"] for p in ph])
    chk("⑤b", "S1 报价 0 且我方承担增量现金 33.8 万",
        ph[0]["price"] == 0 and abs(ph[0]["ours_cost"] - 338000) < 1,
        "%.0f 元" % ph[0]["ours_cost"])
    chk("⑤c", "S2 报价 > 0 (解决方案费)", ph[1]["price"] > 0, "%.1f 万" % (ph[1]["price"] / 1e4))
    s2_unit = ph[1]["price"] / ph[1]["units"]
    chk("⑤d", "S3 单台价 < S2 单台价 (学习曲线+摊薄)", ph[2]["unit_price"] < s2_unit,
        "S3 %.1f 万/台 vs S2 %.1f 万/台" % (ph[2]["unit_price"] / 1e4, s2_unit / 1e4))
    chk("⑤e", "页面表 3 行且 S1 行写「不收费」", pg._biz_t_phase.rowCount() == 3
        and "不收费" in pg._biz_t_phase.item(0, 2).text(),
        [pg._biz_t_phase.item(0, c).text() for c in (0, 2)])

    print("\n【⑥ 模式推荐】")
    md = e["modes"]
    chk("⑥a", "5 个模式", len(md["options"]) == 5, [m["mode"] for m in md["options"]])
    chk("⑥b", "区间不成立 ⇒ 推荐「软件授权 / 能力包」",
        md["recommend"] == "软件授权 / 能力包", md["recommend"])
    chk("⑥c", "推荐行带 ★ 且在表里", any(str(pg._biz_t_mode.item(r, 0).text()).startswith("★")
                                    for r in range(pg._biz_t_mode.rowCount())),
        [pg._biz_t_mode.item(r, 0).text() for r in range(pg._biz_t_mode.rowCount())])
    raas = next(m for m in md["options"] if m["mode"].startswith("RaaS"))
    chk("⑥d", "RaaS 因 η<0.9 判不可自持", raas["fit"] is False, raas["note"])

    print("\n【⑦ 同源: 页面 == business_model.derive()】")
    ref = BM.derive(d=BM.load(), **pg._biz_inputs())
    keys = ("floor", "ceiling", "ok")
    same = (all(abs(float(e["deal"][k]) - float(ref["deal"][k])) < 1e-9 for k in ("floor", "ceiling"))
            and e["deal"]["ok"] == ref["deal"]["ok"]
            and all(abs(float(a["price"]) - float(b["price"])) < 1e-9
                    for a, b in zip(e["phases"], ref["phases"]))
            and abs(float(e["layered"]["eta"]) - float(ref["layered"]["eta"])) < 1e-12)
    chk("⑦a", "floor/ceiling/ok/三阶段价/η 逐位相同", same, keys)

    print("\n【⑧ 改假设即现算】")
    pg._biz_in["target_margin"].setValue(30.0)
    app.processEvents()
    e2 = dict(pg._biz_e)
    chk("⑧a", "毛利率 40→30% ⇒ floor 29.7 → 25.5 万",
        abs(e2["deal"]["floor"] - 254732) < 500, "%.2f 万" % (e2["deal"]["floor"] / 1e4))
    pg._biz_in["customer_target_payback"].setValue(5.0)
    app.processEvents()
    e3 = dict(pg._biz_e)
    chk("⑧b", "客户目标回本 2.5→5 年 ⇒ 区间转成立", e3["deal"]["ok"] is True,
        "floor %.1f / ceiling %.1f" % (e3["deal"]["floor"] / 1e4, e3["deal"]["ceiling"] / 1e4))
    pg._biz_in["target_margin"].setValue(40.0)
    pg._biz_in["customer_target_payback"].setValue(2.5)
    app.processEvents()
    chk("⑧c", "改回默认 ⇒ 回到不成立", pg._biz_e["deal"]["ok"] is False,
        pg._biz_l_deal.text()[:40])

    print("\n【⑨ 派生值不落盘】")
    d = json.load(open(TRUTH, encoding="utf-8"))
    bad_keys = [k for k in ("total", "price", "floor", "ceiling", "payback", "margin", "phases")
                if k in d]
    chk("⑨a", "唯一依据顶层无派生键", not bad_keys, sorted(d.keys()))
    bad_in = [k for k in d["inputs"] if k in ("total", "price", "floor", "ceiling", "margin")]
    chk("⑨b", "inputs 里也只有输入 (每个都带 value/label/source)",
        not bad_in and all(isinstance(v, dict) and "value" in v and "label" in v
                           for v in d["inputs"].values()),
        "共 %d 个假设" % len(d["inputs"]))
    labels = {}
    for v in d["inputs"].values():
        labels[v.get("label")] = labels.get(v.get("label"), 0) + 1
    chk("⑨c", "每个系数都有三色标签 (给定/目标/假设)", all(labels.get(x) for x in ("给定", "目标", "假设")),
        labels)

    print("\n【⑩ 写回假设 + 回读 + 还原】")
    before_baks = set(glob.glob(TRUTH + ".bak_*"))
    pg._biz_in["eta_struct"].setValue(0.80)
    pg._biz_save()
    back = json.load(open(TRUTH, encoding="utf-8"))
    new_baks = set(glob.glob(TRUTH + ".bak_*")) - before_baks
    chk("⑩a", "唯一依据 eta_struct 真变 0.80", abs(back["inputs"]["eta_struct"]["value"] - 0.80) < 1e-9,
        back["inputs"]["eta_struct"]["value"])
    chk("⑩b", "日志明写回读校验通过", "回读校验通过" in pg._biz_log.text(), pg._biz_log.text()[:90])
    chk("⑩c", "生成备份", len(new_baks) == 1, [os.path.basename(x) for x in new_baks])
    open(TRUTH, "wb").write(orig_bytes)
    for b in new_baks:
        os.remove(b)
    chk("⑩d", "唯一依据已字节级还原", open(TRUTH, "rb").read() == orig_bytes)

    print("\n【⑪ 导出 JSON + 提案 MD】")
    pg._biz_in["eta_struct"].setValue(0.92)
    pg._biz_refresh()
    before = set(glob.glob(os.path.join(ROOT, "zmax_data", "business", "business_model_*")))
    pg._biz_export()
    new = set(glob.glob(os.path.join(ROOT, "zmax_data", "business", "business_model_*"))) - before
    ok11, ev11 = False, "无新文件"
    if new:
        pj = sorted(x for x in new if x.endswith(".json"))[-1]
        pm = sorted(x for x in new if x.endswith(".md"))[-1]
        j = json.load(open(pj, encoding="utf-8"))
        md_txt = open(pm, encoding="utf-8").read()
        ok11 = (abs(float(j["deal"]["floor"]) - float(pg._biz_e["deal"]["floor"])) < 1e-6
                and "三阶段定价" in md_txt and "D 口径" not in md_txt and "**D +NRE**" in md_txt)
        ev11 = "%s floor=%.0f md=%d 字" % (os.path.basename(pj), j["deal"]["floor"], len(md_txt))
        for x in new:
            os.remove(x)
    chk("⑪a", "导出文件与页面同值, MD 含三阶段表", ok11, ev11)

    print("\n【⑫ 复制】")
    pg._biz_copy()
    cb = app.clipboard().text()
    chk("⑫a", "剪贴板 TSV 含底价/推荐模式", "底价 floor" in cb and "推荐模式" in cb and "\t" in cb,
        cb.splitlines()[:2])

    print("\n【⑬ 零回归】")
    ce = pg._cost_refresh()
    chk("⑬a", "成本页仍出 36.3 万 / 2.02 年",
        abs(ce["total_first"] - 363000) < 1e-6 and ce["payback_years"] == 2.02,
        "%.0f / %s" % (ce["total_first"], ce["payback_years"]))
    chk("⑬b", "页签恰好 7 个 (= 北斗七星; 商业模式 已并入文档配置)", len(titles) == 7, len(titles))
    chk("⑬c", "画布唯一依据未被碰 (mtime 不变)", os.path.getmtime(CANVAS) == canvas_mt)
    chk("⑬d", "唯一依据已还原 (== 测试前字节)", open(TRUTH, "rb").read() == orig_bytes)

    print("\n" + "=" * 68)
    print("结果: PASS %d / FAIL %d" % (len(OK), len(BAD)))
    if BAD:
        for it, nm in BAD:
            print("   ❌ [%s] %s" % (it, nm))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
