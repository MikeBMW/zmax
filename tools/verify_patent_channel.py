#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_patent_channel.py — 专利申请渠道 + 文档 (导出/预览) 判据。

老倪 2026-10-15:
  「注意，预留所有功能的专利申请渠道；在配置中心，文档配置 增加专利 导出和预览功能，通SOR 项目立项，等文档同级别；
   你来根据先有状态空间工程，设计专利申请的内容，要有层次，逻辑，要保证全局数据真实，可靠，能落地，形成专有知识产权」

判据 (真跑真读, 不看图):
  ① 真源: config/patents/patent_registry.json 存在、schema 对、件数 ≥ 8
  ② 内容: 每件必需字段齐全 (编号/标题/层次/代号/类型/状态/摘要/问题/方案/效果/权项/实施例/落地引用/挂载功能)
  ③ 渠道: 74 条功能**逐条**挂上 (主挂或关联) —— 未挂 0 条; 且 fn_ids 无孤儿 (库里有这个功能)
  ④ 不许空专利: 每件主挂+关联 > 0
  ⑤ 层次: 层次分类 ≥ 4 类; 每件星位属于北斗七星
  ⑥ 逻辑: 问题 ≥2 · 方案 ≥4 · 效果 ≥2 · 权项 ≥3 · 实施例 ≥2
  ⑦ 落地: 每件落地引用 ≥2 条, 且**逐条真实存在** (文件/目录在仓库里)
  ⑧ 数据真实: 文档里的统计 = 真源现算 (工程库 functions/product_features/canvas_nodes + 主控台模型矩阵)
  ⑨ 导出: 12 件 md + docx 全落地非空, 总览清单含"渠道 100% 预留"
  ⑩ 同源: 文档内"挂载功能表"行数 == 该专利挂载数
  ⑪ 文档配置页: 专利块在位 (表 12 行) 且与 SOR/立项/合作协议**同一页签**(同级别) + 共用同一预览窗
  ⑫ 功能配置页: 74 行专利渠道列无"渠道未闭合" + 有「📜 该功能专利申请草稿」按钮
  ⑬ 交互: 选中一行功能 → 预览闸门真的打开该功能主挂专利正文
  ⑭ 复制: 功能↔专利渠道清单可复制 (74 行 + 表头)

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_patent_channel.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import patent_center as PC                                                       # noqa: E402

CHECKS = []


def chk(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print(("  ✅ " if ok else "  ⛔ ") + name + ("   " + str(detail) if detail else ""))


REQ = ("pat_id", "title", "layer", "star", "codename", "type", "status", "abstract",
       "problems", "solution", "effects", "claims", "embodiment", "impl_refs", "fn_ids")


def main():
    reg = PC.load_registry()
    pats = reg.get("patents", [])
    cov = PC.coverage()
    facts = PC.live_facts()

    print("═══ ① 真源 ═══")
    chk("真源存在 + schema 对 + 件数 ≥ 8", reg.get("schema") == "zmax-patent-registry/1" and len(pats) >= 8,
        "%s · %d 件" % (os.path.relpath(PC.REG_J, ROOT), len(pats)))

    print("\n═══ ② 内容字段 (层次/逻辑要写全) ═══")
    bad = [(p.get("pat_id"), [k for k in REQ if not p.get(k)]) for p in pats if any(not p.get(k) for k in REQ)]
    chk("每件必需字段齐全", not bad, "%s" % (bad[:3] if bad else "12/12 齐全"))

    print("\n═══ ③ 专利申请渠道: 功能逐条挂上 (老倪: 预留**所有**功能的渠道) ═══")
    chk("功能覆盖 %d/%d, 未挂 0 条" % (cov["covered"], cov["total_fn"]),
        cov["covered"] == cov["total_fn"] and not cov["uncovered"],
        "未挂: %s" % (cov["uncovered"] or "无"))
    _lib = {f["fn_id"] for f in PC.fn_rows()}
    _orphan = sorted({fid for p in pats for fid in (p.get("fn_ids") or []) + (p.get("fn_ids_related") or [])
                      if fid not in _lib})
    chk("挂载的功能编号无孤儿 (都在工程库 functions 表里)", not _orphan, "%s" % (_orphan or "0 个孤儿"))

    print("\n═══ ④⑤ 不许空专利 · 层次与星位 ═══")
    _empty = [p["pat_id"] for p in pats if not (p.get("fn_ids") or p.get("fn_ids_related"))]
    chk("每件专利至少挂 1 条功能", not _empty, "%s" % (_empty or "12/12 都挂了功能"))
    _lay = sorted({p.get("layer") for p in pats})
    chk("层次分类 ≥ 4 类 (体系/数学/模型/执行/标定/视觉 分级)", len(_lay) >= 4, "%d 类: %s" % (len(_lay), " · ".join(_lay)))
    _stars = {"天枢", "天璇", "天玑", "天权", "玉衡", "开阳", "瑶光"}
    _badstar = [p["pat_id"] for p in pats if p.get("star") not in _stars]
    chk("每件星位属于北斗七星 (阵法结构一致)", not _badstar, "%s" % (_badstar or "12/12 合法"))

    print("\n═══ ⑥ 逻辑完整度 (问题→方案→效果→权项→实施例) ═══")
    _thin = []
    for p in pats:
        n = {"problems": 2, "solution": 4, "effects": 2, "claims": 3, "embodiment": 2}
        for k, want in n.items():
            if len(p.get(k) or []) < want:
                _thin.append("%s.%s(%d<%d)" % (p["pat_id"], k, len(p.get(k) or []), want))
    chk("件件 问题≥2 方案≥4 效果≥2 权项≥3 实施例≥2", not _thin, "%s" % (_thin[:4] or "12/12 达标"))

    print("\n═══ ⑦ 落地: 落地引用必须真实存在 ═══")
    _miss, _n = [], 0
    for p in pats:
        refs = p.get("impl_refs") or []
        _n += len(refs)
        if len(refs) < 2:
            _miss.append("%s(引用%d条<2)" % (p["pat_id"], len(refs)))
        for r in refs:
            if not os.path.exists(os.path.join(ROOT, r)):
                _miss.append("%s:%s" % (p["pat_id"], r))
    chk("每件 ≥2 条落地引用 且**逐条存在** (共 %d 条)" % _n, not _miss, "%s" % (_miss[:4] or "%d 条全部存在" % _n))

    print("\n═══ ⑧ 数据真实: 文档里的统计 = 真源现算 ═══")
    _txt = PC.draft_text(pats[0], cov=cov, facts=facts)
    _want = [str(facts.get("fn_total")), str(facts.get("pf_total")), str(facts.get("nodes"))]
    _ok8 = all(w in _txt for w in _want if w) and "生成时间" in _txt
    chk("正文含现算的功能数/产品特征数/节点数 (非手写)", _ok8, "功能 %s · 特征 %s · 节点 %s"
        % (facts.get("fn_total"), facts.get("pf_total"), facts.get("nodes")))
    _lay9 = " · ".join("%s %s" % (k, v) for k, v in sorted((facts.get("fn_by_layer") or {}).items()))
    chk("按层分布与工程库现算一致", _lay9 in _txt, _lay9)
    _mx = [v.split(" (")[0] for v in (facts.get("matrix") or {}).values()]
    chk("四层在役模型名与主控台模型矩阵同源", all(m in _txt for m in _mx if m), " · ".join(_mx))

    print("\n═══ ⑨⑩ 导出产物 (md+docx) 与同源核对 ═══")
    _md = [f for f in os.listdir(os.path.join(ROOT, "docs", "patents")) if f.endswith(".md")]
    _dx = [f for f in os.listdir(os.path.join(ROOT, "docs", "patents")) if f.endswith(".docx")]
    _idx = os.path.join(ROOT, "docs", "patents", "00_专利申请渠道清单.md")
    chk("12 件 md + 12 件 docx + 总览清单都落地", len(_md) >= len(pats) + 1 and len(_dx) >= len(pats) and os.path.exists(_idx),
        "md %d · docx %d · 清单 %s" % (len(_md), len(_dx), os.path.exists(_idx)))
    _itxt = open(_idx, encoding="utf-8").read() if os.path.exists(_idx) else ""
    chk("总览清单写明渠道 100% 预留 + 真源数据", ("100%" in _itxt or "渠道 100% 预留" in _itxt) and "已挂渠道" in _itxt,
        _itxt.splitlines()[8][:70] if len(_itxt.splitlines()) > 8 else "")
    _p0, _mine = pats[1], [x for x in cov["per_fn"]
                           if pats[1]["pat_id"] in (x["pat_primary"] + x["pat_related"])]
    _t0 = PC.draft_text(_p0, cov=cov, facts=facts)
    _rows = [l for l in _t0.splitlines() if l.startswith("| FN-")]
    chk("文档内挂载功能表行数 == 该专利挂载数", len(_rows) == len(_mine),
        "%s: 表 %d 行 · 真源 %d 条" % (_p0["pat_id"], len(_rows), len(_mine)))
    chk("每行挂载功能带真源符号或模块 (可点到代码)",
        sum(1 for l in _rows if "`" in l) >= int(0.9 * max(1, len(_rows))),
        "%d/%d 行带真源符号" % (sum(1 for l in _rows if "`" in l), len(_rows)))

    print("\n═══ ⑪⑫⑬⑭ 控制台 UI: 与 SOR/立项/协议 同级 + 功能渠道可点 ═══")
    from PyQt5.QtWidgets import QApplication, QPushButton                             # noqa: E402
    import veh6_config_page as V                                                      # noqa: E402
    app = QApplication.instance() or QApplication(sys.argv)
    page = V.build_config_center(None, None)
    page.resize(1600, 950)
    page.show()
    app.processEvents()
    _pt = getattr(page, "pat_table", None)
    chk("文档配置页有专利块: 表 %s 行 / %s 列" % (getattr(_pt, "rowCount", lambda: "—")(),
                                                 getattr(_pt, "columnCount", lambda: "—")()),
        _pt is not None and _pt.rowCount() == len(pats) and _pt.columnCount() >= 6)
    _di = page._tab_index_by_title("文档配置")
    _host = page.tabs.widget(_di)
    _inner = _host.widget() if hasattr(_host, "widget") else _host
    _in_same = _inner is not None and _inner.isAncestorOf(_pt)
    _has_preview = getattr(page, "preview", None) is not None and _inner is not None and _inner.isAncestorOf(page.preview)
    chk("专利块与 SOR/立项/合作协议 在**同一页签**且共用同一预览窗", _in_same and _has_preview,
        "同页=%s · 共用预览=%s" % (_in_same, _has_preview))
    _btns = [b.text() for b in _inner.findChildren(QPushButton)] if _inner is not None else []
    chk("专利块按钮齐: 预览 / 导出选中 / 导出全部 / 复制渠道", all(any(k in t for t in _btns) for k in
                                                              ("预览选中专利", "导出选中", "导出全部专利", "复制功能↔专利渠道清单")),
        " · ".join(t for t in _btns if "专利" in t)[:90])
    _fn = getattr(page, "fn_table", None)
    _last = (_fn.columnCount() - 1) if _fn is not None else -1
    _vals = [_fn.item(i, _last).text() if _fn.item(i, _last) else "" for i in range(getattr(_fn, "rowCount", lambda: 0)())]
    chk("功能配置页 74 行都有专利渠道 (无'渠道未闭合')",
        _fn is not None and len(_vals) == cov["total_fn"] and not any("渠道未闭合" in v for v in _vals),
        "行 %d · 空白 %d 行" % (len(_vals), sum(1 for v in _vals if not v.strip())))
    _fb = [b.text() for b in page.findChildren(QPushButton)]
    chk("功能配置页有「📜 该功能专利申请草稿」入口", any("该功能专利申请草稿" in t for t in _fb),
        " · ".join(t for t in _fb if "专利" in t)[:80])
    page.tabs.setCurrentIndex(page._tab_index_by_title("功能配置"))
    app.processEvents()
    _fn.selectRow(30)
    app.processEvents()
    page._show_function_patent()
    app.processEvents()
    _pv = page.preview.toPlainText()
    _mine30 = cov["per_fn"][30]
    _pid = (_mine30["pat_primary"] or _mine30["pat_related"])[0]
    _title = next(p["title"] for p in pats if p["pat_id"] == _pid)
    chk("选中功能行 → 预览窗真的打开该功能主挂专利正文", _title in _pv and _pid in page.pv_head.text(),
        "%s → %s" % (_mine30["fn_id"], _pid))
    page._copy_patent_channels()
    app.processEvents()
    _clip = QApplication.clipboard().text()
    chk("功能↔专利渠道清单可复制 (74 行 + 表头)", len(_clip.splitlines()) == cov["total_fn"] + 1,
        "%d 行 (含表头)" % len(_clip.splitlines()))

    _ok = sum(1 for _n, k, _d in CHECKS if k)
    print("\n═══ 判据汇总: %d/%d PASS ═══" % (_ok, len(CHECKS)))
    for n, k, d in CHECKS:
        if not k:
            print("  ⛔ " + n + "   " + str(d))
    print("✅ PASS %d/%d" % (_ok, len(CHECKS)) if _ok == len(CHECKS) else "❌ FAIL %d/%d" % (_ok, len(CHECKS)))
    return 0 if _ok == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
