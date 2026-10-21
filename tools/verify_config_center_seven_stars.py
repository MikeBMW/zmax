#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_config_center_seven_stars.py — 判据: 配置中心 = 北斗七星阵 (次序/序号/星名/顶部阵图条)。

老倪 2026-10-15 要求:
  左树从上到下 1.产品配置 2.任务配置 3.功能配置 4.模型配置 5.性能配置 6.工程配置 7.文档配置, 前面要显示序号;
  每个配置打开的主页面最上顶部要写该星的说明 (北斗七星阵 = 状态空间工程的完备结构)。

判据 (全程离屏, 不动生产 GUI, 不写任何真源):
  ① 左树顶层恰好 7 项, 次序与序号/星名一一对应 (1.产品配置·天枢 … 7.文档配置·瑶光)
  ② 每项序号在**最前面** (标 ✅/⛔ 之后紧跟 "N. ")
  ③ 七颗星齐全且无重复 (天枢/天璇/天玑/天权/玉衡/开阳/瑶光)
  ④ 第六阵 = 工程配置 (老倪 2026-10-19「将 工单配置，替换成 工程配置」) —— 不再是"不在七星之列"的附加视图
  ⑤ 阵图条: 七个页签都拿到**该页所属星**的说明 (2026-10-19 起七页全为七星页)
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
        ("4.", "模型配置", "天权"), ("5.", "性能配置", "玉衡"), ("6.", "工程配置", "开阳"),
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
    _OPEN_IDX = page.tabs.currentIndex()          # 构造完就停在哪一页 = 用户打开配置中心看到的第一页
    _OPEN_TAB = page.tabs.tabText(_OPEN_IDX)
    # 打开那一刻左树行首标记的快照 (后面判据会切页, 不能拿切换后的状态当"初始")
    _MARKS_OPEN = [page.tree.topLevelItem(_i).text(0) for _i in range(page.tree.topLevelItemCount())]
    checks = []

    # ① 顶层 7 项 + ② 序号在最前 + ③ 星名齐全
    tops = [page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())]
    ok1 = len(tops) == 7
    checks.append(("① 左树顶层恰好 7 项 (北斗七星)", ok1, " | ".join(t[:26] for t in tops)))
    # 🎯 2026-10-17 老倪「现在太宽了」: 行里只画「序号 + 名称」, 星名不再画在行上
    #   (全文「N. 名称 · 星名」存在 item data UserRole+1, 点点选/复制照旧) ⇒ 判据按"显示行 + 全文"两处一起验。
    from PyQt5.QtCore import Qt as _Qt
    _full = [str(page.tree.topLevelItem(i).data(0, _Qt.UserRole + 1) or "") for i in range(len(tops))]
    # 🆕 2026-10-21 老倪: 行首 ✅ = 当前打开的那一页, ○ = 其它页 (就绪符挪进 tooltip)
    ok2 = all(re.match(r"^[✅○] \d\. [\u4e00-\u9fa5]+$", t) for t in tops) and all(
        (w[0] + " " + w[1] + " · " + w[2]) in f for w, f in zip(WANT, _full))
    checks.append(("② 每项显示「序号 + 名称」· 全文带星名 (不带计数/当前值)", ok2,
                   " | ".join(t for t in tops)))
    stars_in_tree = [w[2] for w in WANT if w[2] in " ".join(_full)]
    checks.append(("③ 七颗星齐全且无重复", len(stars_in_tree) == 7 == len(set(stars_in_tree)),
                   " ".join(stars_in_tree)))
    # 左树次序 == 阵法数据里的次序 (不允许两处各写一份顺序)
    checks.append(("③b 左树次序 == ss_seven_stars.STARS 次序",
                   [S.BY_KEY[k]["star"] for k in ("prod", "task", "func", "model", "perf", "eng", "doc")]
                   == stars_in_tree, " ".join(s["star"] for s in S.STARS)))

    # ④ 第六阵 = 工程配置 (2026-10-19): 左树第 6 行 + 页签都得有; 独立「工单配置」页签必须消失
    _kids = sum(page.tree.topLevelItem(i).childCount() for i in range(page.tree.topLevelItemCount()))
    _eng_tab = page._tab_index_by_title("工程配置") >= 0
    _eng_top = any("工程配置" in t for t in tops)
    _tabs_all = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    _no_order_tab = not any("工单配置" in t for t in _tabs_all)
    checks.append(("④ 第六阵=工程配置 (左树+页签) · 左树无子项 · 独立「工单配置」页签已取消",
                   _kids == 0 and _eng_top and _eng_tab and _no_order_tab,
                   "子项数=%d · 左树有工程配置=%s · 页签有工程配置=%s · 还有工单配置页签=%s"
                   % (_kids, _eng_top, _eng_tab, not _no_order_tab)))

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
                   " ; ".join(multi) if multi else "逐一实测: 七个页签各亮 1 颗 (2026-10-19 起无非七星页)"))

    # ⑨ 一页三星的页签: 点哪颗只亮哪颗 + 说明跟着换 (天玑/玉衡/天权 依次点)
    _j = page._tab_index_by_title("功能配置")
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
               ("3. 功能配置", "功能配置"), ("4. 模型配置", "模型配置"),
               ("5. 性能配置", "性能配置"), ("6. 工程配置", "工程配置"),
               ("7. 文档配置", "文档配置")]
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
    #    ⚠️ 例外 (老倪 2026-10-21): 「产品配置 本页真源: 当前 550B · 真源改于 10-19 15:36 · 三档 550A 原创版 /
    #    550B 标定版 / 550C 量产版 这句话 删掉」⇒ 天枢 (prod) 页顶**必须没有**这行, 其余六页照旧必须有。
    #    判据跟着真实现走: 读取口是 veh6_config_page.BANNER_FACT_HIDDEN, 不在这里另抄一份档名。
    _hidden = tuple(getattr(V, "BANNER_FACT_HIDDEN", ()))
    _facts = []
    for _k in ("prod", "task", "func", "model", "perf", "eng", "doc"):
        page._goto_star(_k)
        _app.processEvents()
        _f = page.star_banner.snapshot().get("fact", "")
        _facts.append("%s→%s" % (S.BY_KEY[_k]["star"], (_f[8:40] + "…") if len(_f) > 48 else _f[8:]))
        if _k in _hidden:
            _facts[-1] = "%s→(无, 已按老倪要求删)" % S.BY_KEY[_k]["star"]
            if _f.strip():
                _facts[-1] = "❌" + _facts[-1] + " 仍有:" + _f[:20]
            continue
        if not _f.startswith("本页真源: ") or len(_f) <= 9:
            _facts[-1] = "❌" + _facts[-1]
    checks.append(("⑪ 每颗星的页顶都有「本页真源: …」(%s 页已删, 左树删掉的详细值落到其余页)"
                   % "/".join(S.BY_KEY[k]["star"] for k in _hidden),
                   not any(x.startswith("❌") for x in _facts), " ; ".join(_facts)))

    # ⑫ 主页面页签次序 == 北斗次序 (老倪 2026-10-15: 「下面主页面标签的顺序也不一致,
    #    应该显示 产品配置标签, 然后是第二个任务配置, 依次顺序排列」)
    # 2026-10-19: 工单/成本报价/商业模式 并入文档配置 ⇒ 页签正好 7 个 = 七星
    _order_want = ["产品配置", "任务配置", "功能配置", "模型配置", "性能配置", "工程配置", "文档配置"]
    _order_now = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    _pos = [next((i for i, t in enumerate(_order_now) if k in t), -1) for k in _order_want]
    checks.append(("⑫ 页签恰好 7 个且次序 == 北斗次序 (1产品→2任务→…→6工程→7文档)",
                   len(_order_now) == 7 and all(x >= 0 for x in _pos) and _pos == sorted(_pos),
                   "%d 个: %s" % (len(_order_now), " | ".join(t.strip() for t in _order_now))))

    # ⑬ 点「5. 性能配置 · 玉衡」→ 顶部阵图条必须是**玉衡**, 且右页「性能配置」按钮是按下态
    #    (老倪实测: 左侧点性能配置, 右侧还显示天玑的按钮/描述)
    _it5 = next(page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())
                if "性能配置" in page.tree.topLevelItem(i).text(0))
    page._on_tree(_it5, 0)
    _app.processEvents()
    _snap5 = page.star_banner.snapshot()
    _cur5 = page.tabs.tabText(page.tabs.currentIndex()).strip()
    # 2026-10-15: 功能配置/性能配置 各自一页 ⇒ 看**那一页**自己的域按钮 (不再共用一页)
    _btns = {d: b.isChecked() for d, b in page.fpm_views["性能配置"]["btns"].items()}
    _ok13 = ("玉衡" in _snap5["title"]) and ("性能配置" in _cur5) and \
        _btns.get("性能配置") is True and sum(1 for v in _btns.values() if v) == 1
    checks.append(("⑬ 点「性能配置」→ 切到⚡性能配置页 · 顶部=玉衡 · 只有该域按钮按下",
                   _ok13, "当前页=%s ; 阵图条=%s ; 按下=%s" % (_cur5, _snap5["title"][:16],
                                                             "".join(d for d, v in _btns.items() if v) or "无")))

    # ⑭ 点「3. 功能配置」→ 天玑 · 「5. 性能配置」→ 玉衡 · 「4. 模型配置」→ 天权 (三颗星不许混成一颗)
    _pair = []
    for _want, _kw, _tabkw in (("3. 功能配置", "天玑", "功能配置"), ("5. 性能配置", "玉衡", "性能配置"),
                               ("4. 模型配置", "天权", "模型配置")):
        _it = next(page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())
                   if _want in page.tree.topLevelItem(i).text(0))
        page._on_tree(_it, 0)
        _app.processEvents()
        _t = page.star_banner.snapshot()["title"]
        _cur = page.tabs.tabText(page.tabs.currentIndex()).strip()
        _bad = (_kw not in _t) or (_tabkw not in _cur)
        _pair.append("%s→星%s 页%s%s" % (_want, _t.split(" · ")[0][:4], _cur,
                                        "" if not _bad else " ❌应显示%s/%s" % (_kw, _tabkw)))
        if _bad:
            _pair[-1] = "❌" + _pair[-1]
    checks.append(("⑭ 点功能/性能/模型三种: 星与页都各自对上",
                   not any(x.startswith("❌") for x in _pair), " ; ".join(_pair)))

    # ⑮ 老倪 2026-10-19: 「(与主控制台左侧同源: config/platform/zmax_platform.json) 在主配置中心，删掉」
    #    ⇒ 配置中心产品配置页 **不许** 再挂那块与主控制台左侧重复的 🏭 平台信息块;
    #      主控制台左侧卡面照旧读单一真源 (zmax_platform_info), 产品配置页的「平台描述 + 产品特性」块保留。
    try:
        from zmax_platform_info import zmax_platform_info as _zpi
        _pi_lines = (_zpi() or {}).get("lines") or []
    except Exception:                                                           # noqa: BLE001
        _pi_lines = []
    _src_studio = open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8").read()
    _wired = '(_zmax_platform_info() or {}).get("short")' in _src_studio
    _no_card = (getattr(page, "plat_card", None) is None) and not hasattr(page, "plat_lines")
    _page_kept = getattr(page, "plat_page_block", None) is not None
    _ok15 = bool(_pi_lines) and _wired and _no_card and _page_kept
    checks.append(("⑮ 配置中心已删 🏭 平台块 · 主控制台左侧仍单一真源 · 平台描述块保留",
                   _ok15, "模块 %d 行 | 主控制台卡面接线=%s | 配置中心无平台块=%s | 平台页块=%s"
                   % (len(_pi_lines), _wired, _no_card, _page_kept)))

    # ⑯ 合并已生效 (老倪 2026-10-15: 取消模型匹配/文档预览, 并入模型配置/文档配置)
    _tabs_now = [page.tabs.tabText(i) for i in range(page.tabs.count())]

    def _in_tab(_w, _kw):
        _i = page._tab_index_by_title(_kw)
        if _i < 0 or _w is None:
            return False
        _host = page.tabs.widget(_i)
        return (_host is _w) or bool(_host.isAncestorOf(_w))

    _gone = (not any("模型匹配" in t for t in _tabs_now)) and (not any("文档预览" in t for t in _tabs_now))
    _m1 = _in_tab(getattr(page, "match_table", None), "模型配置")
    _m2 = _in_tab(getattr(page, "preview", None), "文档配置")
    checks.append(("⑯ 「模型匹配/文档预览」页签已取消, 内容确实在合并后的页里",
                   _gone and _m1 and _m2,
                   "页签 %d 个 · 匹配表在模型配置=%s · 预览在文档配置=%s" % (len(_tabs_now), _m1, _m2)))

    # ⑰ 内容口径: 功能配置页 = 系统2/1/0 全部功能 + 汇总; 产品配置页 复用「Z-MAX 平台」页描述(含产品特性)
    try:
        from zmax_platform_info import platform_page_data as _ppd2, function_summary as _fs2
        _pdata = _ppd2()
        _fns2 = _pdata.get("functions") or []
        _smy = _fs2(_fns2)
    except Exception:                                                           # noqa: BLE001
        _pdata, _fns2, _smy = {}, [], {"text": ""}
    _ft = getattr(page, "fn_table", None)
    _pt = getattr(page, "plat_feat_table", None)
    _ok17 = (bool(_fns2) and _ft is not None and _ft.rowCount() == len(_fns2)
             and all(k in _smy["text"] for k in ("系统 2", "系统 1", "系统 0"))
             and _in_tab(_ft, "功能配置")
             and _pt is not None and _pt.rowCount() == len(_pdata.get("features") or [])
             and _in_tab(_pt, "产品配置"))
    checks.append(("⑰ 功能配置页=系统2/1/0 全部功能+汇总 · 产品配置页=平台页描述+产品特性",
                   _ok17, "功能表 %s 行 (真源 %d) · 汇总「%s」· 产品特性 %s 行 (真源 %d)"
                   % (getattr(_ft, "rowCount", lambda: "—")(), len(_fns2), _smy["text"],
                      getattr(_pt, "rowCount", lambda: "—")(), len(_pdata.get("features") or []))))

    # ⑱ 老倪 2026-10-19: 「将工单，放到文档配置选项卡，将成本/报价 商业模式的内容，都迁移到 文档配置里」
    #    ⇒ 三块必须**真的在**「📄 文档配置」页的控件树里, 且独立页签已取消。
    _doc_i = page._tab_index_by_title("文档配置")
    _doc_host = page.tabs.widget(_doc_i) if _doc_i >= 0 else None

    def _labels_in(_root):
        from PyQt5.QtWidgets import QLabel as _QL
        return [w.text() for w in (_root.findChildren(_QL) if _root is not None else []) if w.text()]

    _dl = " ".join(_labels_in(_doc_host))
    _c_orders = _in_tab(getattr(page, "order_table", None), "文档配置")
    _c_cost = ("成本/报价" in _dl) and ("成本 / 报价" in _dl)
    _c_biz = "商业模式" in _dl
    _c_no_tab = not any(k in t for t in _tabs_all for k in ("成本/报价", "商业模式"))
    checks.append(("⑱ 工单表 + 成本/报价 + 商业模式 三块都在「文档配置」页内 · 独立页签已取消",
                   _c_orders and _c_cost and _c_biz and _c_no_tab,
                   "工单表在文档页=%s · 成本块=%s · 商业模式块=%s · 无独立页签=%s"
                   % (_c_orders, _c_cost, _c_biz, _c_no_tab)))

    # ⑲ 开阳的描述整体改成「工程配置·定落地」(老倪: 「整体上调整原来的 北斗七星的 开阳的描述,
    #    因为要变更成 工程配置」) —— 名字/主司/定义/关系里不许再留工单调度的说法。
    _o6 = S.BY_KEY["eng"]
    _txt6 = "".join(str(_o6[k]) for k in ("name", "role", "bind", "q", "define", "rel"))
    _ok19 = (_o6["name"] == "工程配置" and _o6["star"] == "开阳" and _o6["bind"] == "定落地"
             and "定调度" not in _txt6 and "工单编号" not in _txt6
             and "工程" in _txt6)
    checks.append(("⑲ 开阳 = 工程配置·定落地 (描述里不再有工单调度口径)",
                   _ok19, "%s、%s · %s · %s" % (_o6["no_cn"], _o6["name"], _o6["star"], _o6["bind"])))

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

    # ⑳ 打开先看产品配置 + 左树小对号跟着当前页走 (老倪 2026-10-21 原话)
    #    「配置中心 打开的时候, 应该先显示 产品配置; 左边栏 的小对号, 应该打开哪个配置页面,
    #      小对号就对应显示相应的配置」
    _pi0 = page._tab_index_by_title("产品配置")
    _cur0 = _OPEN_IDX
    # 页面构造完就应停在产品配置页 (与"记住上次那一页"无关 —— 回放已停用)
    _open_ok = (_pi0 >= 0 and _cur0 == _pi0)
    def _marks():
        out = []
        for i in range(page.tree.topLevelItemCount()):
            it = page.tree.topLevelItem(i)
            out.append((it.text(0), it.data(0, _Qt.UserRole)))
        return out
    _m0 = [(t, None) for t in _MARKS_OPEN]          # 打开那一刻的标记 (不是切过几页之后的状态)
    _tick0 = [t for t, _ in _m0 if t.startswith("✅")]
    _one0 = (len(_tick0) == 1 and _m0[_pi0][0].startswith("✅")
             and all(t.startswith("○") for t, _ in _m0 if not t.startswith("✅")))
    # 换到任务配置页 ⇒ ✅ 必须移到第 2 行 (仍是唯一一个)
    _ti = page._tab_index_by_title("任务配置")
    page.tabs.setCurrentIndex(_ti)
    _app.processEvents()
    _m1 = _marks()
    _tick1 = [t for t, _ in _m1 if t.startswith("✅")]
    _move_ok = (len(_tick1) == 1 and _m1[_ti][0].startswith("✅")
                and not _m1[_pi0][0].startswith("✅"))
    # 再切回产品配置页 ⇒ ✅ 回到第 1 行
    page.tabs.setCurrentIndex(_pi0)
    _app.processEvents()
    _back_ok = _marks()[_pi0][0].startswith("✅")
    # 就绪状态没丢: tooltip 里仍有「真源就绪: ✅/⛔」
    _tip_ok = all("真源就绪:" in str(page.tree.topLevelItem(i).toolTip(0)) for i in range(page.tree.topLevelItemCount()))
    checks.append(("⑳ 打开先落在「产品配置」· 左树 ✅ 只标当前页 (切换跟着走, ○ 标其余; 就绪符留 tooltip)",
                   _open_ok and _one0 and _move_ok and _back_ok and _tip_ok,
                   "首屏=%s (期望 %d) · 初始✅=%s · 切任务后✅=%s · 切回=%s · tooltip就绪=%s"
                   % (_OPEN_TAB, _pi0, _tick0, _tick1, _back_ok, _tip_ok)))

    # 出图 (给人看的证据; 本判据不依赖看图)
    try:
        page.resize(1680, 940)
        page.tabs.setCurrentIndex(page._tab_index_by_title("功能配置"))
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
