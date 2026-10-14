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
    # 与 studio 同一条构造路径 (传一个容器当 model_page ⇒ 「🧠 模型配置」页签才会建出来;
    # 直接 ConfigCenterPage() 会少那个页签, 判"点模型配置跳哪"就会判错 —— 2026-10-15 实测)
    from PyQt5.QtWidgets import QWidget as _QW
    page = V.build_config_center(_QW())
    checks = []

    # ① 顶层 7 项 + ② 序号在最前 + ③ 星名齐全
    tops = [page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())]
    ok1 = len(tops) == 7
    checks.append(("① 左树顶层恰好 7 项 (北斗七星)", ok1, " | ".join(t[:26] for t in tops)))
    _want_lbl = ["%s %s %s · %s" % ("%s", w[0], w[1], w[2]) for w in WANT]
    ok2 = all(re.match(r"^[✅⛔] \d\. [\u4e00-\u9fa5]+ · [\u4e00-\u9fa5]{2}$", t) for t in tops) and all(
        (w[0] + " " + w[1] + " · " + w[2]) in t for w, t in zip(WANT, tops))
    checks.append(("② 每项正好「序号 + 名称 · 星名」(不带计数/当前值)", ok2,
                   " | ".join(t for t in tops)))
    stars_in_tree = [w[2] for w in WANT if w[2] in " ".join(tops)]
    checks.append(("③ 七颗星齐全且无重复", len(stars_in_tree) == 7 == len(set(stars_in_tree)),
                   " ".join(stars_in_tree)))
    # 左树次序 == 阵法数据里的次序 (不允许两处各写一份顺序)
    checks.append(("③b 左树次序 == ss_seven_stars.STARS 次序",
                   [S.BY_KEY[k]["star"] for k in ("prod", "task", "func", "model", "perf", "order", "doc")]
                   == stars_in_tree, " ".join(s["star"] for s in S.STARS)))

    # ④ 左树只留 7 行 (无子项) · 「工程配置」页签仍在 (功能没丢, 从配置页进)
    _kids = sum(page.tree.topLevelItem(i).childCount() for i in range(page.tree.topLevelItemCount()))
    _eng_tab = page._tab_index_by_title("工程配置") >= 0
    checks.append(("④ 左树无子项 (只 7 行) · 「工程配置」页签健在 (功能没丢)",
                   _kids == 0 and _eng_tab and not any("工程配置" in t for t in tops),
                   "子项数=%d · 工程配置页签=%s" % (_kids, "有" if _eng_tab else "无")))

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

    # ⑧ 一致性: 任何一页下**恰好一颗**星亮 (老倪 2026-10-15: 点天玑时天权/玉衡跟着亮 = 错)
    multi = []
    for i in range(page.tabs.count()):
        page.tabs.setCurrentIndex(i)
        _app.processEvents()
        _t = page.tabs.tabText(i)
        lit = page.star_banner.snapshot()["lit"]
        _want = 1 if S.keys_for_tab(_t) else 0      # 七星页=恰好 1 颗; 非七星页(阵法总览)=0 颗
        if len(lit) != _want:
            multi.append("%s→亮%d颗(%s) 应为%d" % (_t.strip(), len(lit), "/".join(lit) or "无", _want))
    checks.append(("⑧ 七星页恰好一颗星亮 · 非七星页 0 颗 (不许一页亮三颗)", not multi,
                   " ; ".join(multi) if multi else "逐一实测: 七星页 1 颗 / 工程配置页 0 颗(总览)"))

    # ⑨ 一页三星的页签: 点哪颗只亮哪颗 + 说明跟着换 (天玑/玉衡/天权 依次点)
    _j = page._tab_index_by_title("功能·性能·模型")
    page.tabs.setCurrentIndex(_j)
    _app.processEvents()
    one_by_one = []
    for k, star, bind in (("func", "天玑", "定能力"), ("perf", "玉衡", "定指标"), ("model", "天权", "定算法")):
        page._goto_star(k)
        _app.processEvents()
        snap = page.star_banner.snapshot()
        one_by_one.append("%s→亮[%s]标题%s" % (star, "/".join(snap["lit"]) or "无",
                                             star if star in snap["title"] else "✗" + snap["title"][:12]))
    good = all(("%s→亮[%s]" % (st, k)) in "".join(one_by_one)
               for k, st in (("func", "天玑"), ("perf", "玉衡"), ("model", "天权")))
    checks.append(("⑨ 点天玑/玉衡/天权 各只亮各自那一颗 (同一页内)", good, " ; ".join(one_by_one)))

    # ⑩ 点左树每个星项 → **必须切到对应配置页** (老倪 2026-10-15: 产品配置能跳, 任务配置不跳)
    #    根因: 序号 "2." 的点被"参数 ID 分支"当成参数 ID ⇒ 页面不动。这里逐项模拟点击验证。
    _EXPECT = [("1. 产品配置", "产品配置"), ("2. 任务配置", "任务配置"),
               ("3. 功能配置", "功能·性能·模型"), ("4. 模型配置", "模型配置"),
               ("5. 性能配置", "功能·性能·模型"), ("6. 工单配置", "工单配置"),
               ("7. 文档配置", "文档交付")]
    _jump = []
    for _i in range(page.tree.topLevelItemCount()):
        _it = page.tree.topLevelItem(_i)
        _t = _it.text(0)
        _exp = next((e for k, e in _EXPECT if k in _t), None)
        page.tabs.setCurrentIndex(0)                     # 先挪走, 证明是"点出来的"而不是"本来就在"
        page._on_tree(_it, 0)
        _app.processEvents()
        _cur = page.tabs.tabText(page.tabs.currentIndex())
        _ok = (_exp is not None) and (_exp in _cur)
        _jump.append("%s→%s%s" % (_t.split(" · ")[0], _cur.strip(), "" if _ok else " ❌应到" + str(_exp)))
        if not _ok:
            _jump[-1] = "❌" + _jump[-1]
    checks.append(("⑩ 点左树七项各自跳到对应配置页 (含任务/工单/文档)",
                   not any(x.startswith("❌") for x in _jump), " ; ".join(_jump)))

    # ⑪ 详细信息在配置页: 每颗星那页顶部都要有「本页真源: …」且非空
    _facts = []
    for _k in ("prod", "task", "func", "model", "perf", "order", "doc"):
        page._goto_star(_k)
        _app.processEvents()
        _f = page.star_banner.snapshot().get("fact", "")
        _facts.append("%s→%s" % (S.BY_KEY[_k]["star"], (_f[8:40] + "…") if len(_f) > 48 else _f[8:]))
        if not _f.startswith("本页真源: ") or len(_f) <= 9:
            _facts[-1] = "❌" + _facts[-1]
    checks.append(("⑪ 每颗星的页顶都有「本页真源: …」(左树删掉的详细值落到这里)",
                   not any(x.startswith("❌") for x in _facts), " ; ".join(_facts)))

    # ⑫ 主页面页签次序 == 北斗次序 (老倪 2026-10-15: 「下面主页面标签的顺序也不一致,
    #    应该显示 产品配置标签, 然后是第二个任务配置, 依次顺序排列」)
    _order_want = ["产品配置", "任务配置", "功能·性能·模型", "模型配置", "工单配置", "文档交付",
                   "工程配置", "模型匹配", "文档预览"]
    _order_now = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    _pos = [next((i for i, t in enumerate(_order_now) if k in t), -1) for k in _order_want]
    checks.append(("⑫ 页签次序 == 北斗次序 (1产品→2任务→…→7文档→非七星视图)",
                   all(x >= 0 for x in _pos) and _pos == sorted(_pos),
                   " | ".join("→".join([t.strip() for t in _order_now])[:150].split("→"))[:150]))

    # ⑬ 点「5. 性能配置 · 玉衡」→ 顶部阵图条必须是**玉衡**, 且右页「性能配置」按钮是按下态
    #    (老倪实测: 左侧点性能配置, 右侧还显示天玑的按钮/描述)
    _it5 = next(page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())
                if "性能配置" in page.tree.topLevelItem(i).text(0))
    page._on_tree(_it5, 0)
    _app.processEvents()
    _snap5 = page.star_banner.snapshot()
    _btns = {d: b.isChecked() for d, b in getattr(page, "tab3_btns", {}).items()}
    _ok13 = ("玉衡" in _snap5["title"]) and _btns.get("性能配置") is True and \
        sum(1 for v in _btns.values() if v) == 1
    checks.append(("⑬ 点「性能配置」→ 顶部=玉衡 且右页只有「性能配置」按钮按下",
                   _ok13, "阵图条标题=%s ; 按钮按下=%s" % (_snap5["title"][:18],
                                                       "".join(d for d, v in _btns.items() if v) or "无")))

    # ⑭ 同理 点「3. 功能配置」→ 天玑 ; 点「4. 模型配置」→ 天权 (同一页三星不许显示成同一颗)
    _pair = []
    for _want, _kw in (("3. 功能配置", "天玑"), ("4. 模型配置", "天权"), ("5. 性能配置", "玉衡")):
        _it = next(page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())
                   if _want in page.tree.topLevelItem(i).text(0))
        page._on_tree(_it, 0)
        _app.processEvents()
        _t = page.star_banner.snapshot()["title"]
        _on = [d for d, b in getattr(page, "tab3_btns", {}).items() if b.isChecked()]
        _pair.append("%s→%s%s" % (_want, _t.split(" · ")[0][:4], "" if _kw in _t else " ❌应" + _kw))
        if _kw not in _t:
            _pair[-1] = "❌" + _pair[-1]
    checks.append(("⑭ 点功能/模型/性能三种都显示各自那颗 (同一页三星)",
                   not any(x.startswith("❌") for x in _pair), " ; ".join(_pair)))

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
