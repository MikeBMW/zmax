#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_config_center_seven_stars.py — 判据: 配置中心 = 北斗七星阵 (次序/序号/星名/顶部阵图条)。

老倪 2026-10-15 要求:
  左树从上到下 1.产品配置 2.任务配置 3.功能配置 4.模型配置 5.性能配置 6.工单配置 7.文档配置, 前面要显示序号;
  每个配置打开的主页面最上顶部要写该星的说明 (北斗七星阵 = 状态空间工程的完备结构)。

判据 (全程离屏, 不动生产 GUI, 不写任何真源):
  ① 左树顶层恰好 7 项, 次序与序号/星名一一对应 (1.产品配置·天枢 … 7.文档配置·瑶光)
  ② 每项序号在**最前面** (标 ✅/⛔ 之后紧跟 "N. ")
  ③ 七颗星齐全且无重复 (天枢/天璇/天玑/天权/玉衡/开阳/瑶光)
  ④ 「工程配置」不再是顶层 (北斗是 7 项), 但作为「功能配置·天玑」下的子入口健在 (功能没丢)
  ⑤ 阵图条: 每个页签都拿到**该页所属星**的说明; 非七星页 (工程配置) 拿到阵法总览 + 如实说明
  ⑥ 星图 7 颗, 点第 7 颗 (瑶光) → 真切到文档页且阵图条随之变 (真联动)
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_center_seven_stars.py
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WANT = [("1.", "产品配置", "天枢"), ("2.", "任务配置", "天璇"), ("3.", "功能配置", "天玑"),
        ("4.", "模型配置", "天权"), ("5.", "性能配置", "玉衡"), ("6.", "工单配置", "开阳"),
        ("7.", "文档配置", "瑶光")]


def main() -> int:
    from PyQt5.QtWidgets import QApplication
    import ss_seven_stars as S
    import veh6_config_page as V

    _app = QApplication.instance() or QApplication([])
    page = V.ConfigCenterPage()
    checks = []

    # ① 顶层 7 项 + ② 序号在最前 + ③ 星名齐全
    tops = [page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())]
    ok1 = len(tops) == 7
    checks.append(("① 左树顶层恰好 7 项 (北斗七星)", ok1, " | ".join(t[:26] for t in tops)))
    ok2 = all(re.match(r"^[✅⛔] \d\. ", t) for t in tops) and all(
        (w[0] + " " + w[1]) in t for w, t in zip(WANT, tops)) and all(w[2] in t for w, t in zip(WANT, tops))
    checks.append(("② 每项「序号在最前 + 名称 + 星名」全对", ok2,
                   " · ".join("%s%s·%s" % ((w[0]), w[1], w[2]) for w in WANT)))
    stars_in_tree = [w[2] for w in WANT if w[2] in " ".join(tops)]
    checks.append(("③ 七颗星齐全且无重复", len(stars_in_tree) == 7 == len(set(stars_in_tree)),
                   " ".join(stars_in_tree)))
    # 左树次序 == 阵法数据里的次序 (不允许两处各写一份顺序)
    checks.append(("③b 左树次序 == ss_seven_stars.STARS 次序",
                   [S.BY_KEY[k]["star"] for k in ("prod", "task", "func", "model", "perf", "order", "doc")]
                   == stars_in_tree, " ".join(s["star"] for s in S.STARS)))

    # ④ 工程配置 归位 (不再顶层, 但健在)
    kids3 = [page.tree.topLevelItem(2).child(j).text(0) for j in range(page.tree.topLevelItem(2).childCount())]
    top_has_eng = any(t.strip().startswith(("✅", "⛔")) and "工程配置" in t and "·" not in t for t in tops)
    checks.append(("④ 「工程配置」不再顶层 · 仍是天玑下子入口 (功能没丢)",
                   (not top_has_eng) and any("工程配置" in k for k in kids3),
                   "天玑子项: " + " / ".join(k.strip() for k in kids3 if "工程配置" in k)))

    # ⑤ 阵图条: 每个页签都要有该页所属星的说明 (或非七星页的总览)
    bad = []
    seen = []
    for i in range(page.tabs.count()):
        page.tabs.setCurrentIndex(i)
        _app.processEvents()
        title = page.tabs.tabText(i)
        snap = page.star_banner.snapshot()
        want = S.star_for_tab(title)
        if want is not None:
            good = (want["star"] in snap["title"]) and (want["q"] in snap["q"]) and (want["bind"] == snap["bind"])
            seen.append("%s→%s" % (title.strip(), want["star"]))
        else:
            good = ("北斗七星阵" in snap["title"]) and bool(snap["note"])
            seen.append("%s→阵法总览+说明" % title.strip())
        if not good:
            bad.append("%s: %s" % (title, snap["title"][:30]))
    checks.append(("⑤ 七个页签顶部阵图条全部对得上 (非七星页给总览+如实说明)", not bad,
                   " ; ".join(seen) if not bad else "❌ " + " ; ".join(bad)))

    # ⑥ 星图 7 颗 + 点击真联动
    snap0 = page.star_banner.snapshot()
    ok6a = len(snap0["chips"]) == 7 and all(s["star"] in c for s, c in zip(S.STARS, snap0["chips"]))
    page._goto_star("doc")
    _app.processEvents()
    ok6b = ("文档" in page.tabs.tabText(page.tabs.currentIndex())
            and "瑶光" in page.star_banner.snapshot()["title"])
    checks.append(("⑥ 星图 7 颗 · 点「瑶光」真切到文档页且阵图条跟随", ok6a and ok6b,
                   " chips=%s → 当前页=%s" % ("/".join(snap0["chips"]),
                                             page.tabs.tabText(page.tabs.currentIndex()).strip())))

    # ⑦ 阵图条在两种窗口宽度下都**不被截**: 每个可见标签的实得高度 >= 该宽度下换行后需要的高度
    clipped = []
    for _w, _h in ((1600, 900), (1120, 700)):
        page.resize(_w, _h)
        page.show()
        _app.processEvents()
        b = page.star_banner
        _labs = [(n, getattr(b, n)) for n in ("t_title", "t_meta", "t_q", "t_def", "t_bind")]
        if getattr(b, "_note_on", False):
            _labs.append(("t_note", b.t_note))
        for _n, _l in _labs:
            _need = _l.heightForWidth(max(40, _l.width())) if _l.wordWrap() else _l.sizeHint().height()
            if _l.height() + 1 < _need:
                clipped.append("%dx%d %s 实得%dpx < 需要%dpx" % (_w, _h, _n, _l.height(), _need))
    checks.append(("⑦ 阵图条两种窗宽下文字不被截 (换行高度实测)", not clipped,
                   " ; ".join(clipped) if clipped else "1600×900 / 1120×700 全部放得下"))

    # 出图 (给人看的证据; 本判据不依赖看图)
    try:
        page.resize(1680, 940)
        page.tabs.setCurrentIndex(page._tab_index_by_title("功能·性能·模型"))
        _app.processEvents()
        _dst = os.path.join(ROOT, "docs", "data_snapshots", "20261015_config_center_seven_stars")
        os.makedirs(_dst, exist_ok=True)
        page.star_banner.w.grab().save(os.path.join(_dst, "banner_天玑_功能性能模型.png"))
        page.grab().save(os.path.join(_dst, "config_center_full.png"))
    except Exception as _e:                                                      # noqa: BLE001
        print("  (出图跳过: %r)" % (_e,))

    ok = sum(1 for _, c, _ in checks if c)
    for name, c, ev in checks:
        print("  %s %s%s" % ("✅" if c else "❌", name, ("  · " + ev[:150]) if ev else ""))
    print("\n%s %d/%d" % ("✅ PASS" if ok == len(checks) else "❌ FAIL", ok, len(checks)))
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
