#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_task_cfg_height.py — 量「配置中心 · 任务配置」页的真实几何 (只读, 离屏)。

为什么有这个工具 (老倪 2026-10-15): 「任务配置的窗口, 太矮了, 看不到任务, 调高, 优化UI显示」
—— 这类"看不到内容"的投诉**不能靠看图下结论**, 要能把 窗口尺寸 → 任务表高度 → 可见行数
逐档量出来 (表头 / 每行真实行高 / 表内滚动条 / 页内滚动条 / 信息窗高度 / vsplit)。

三条判据 (全部只看数字):
  ① 任务表**表内**滚动条 max == 0  ⇒ 全部任务行都渲染在表内 (窗口再矮也不压扁)
  ② 任务表整块落在页面视口内      ⇒ 打开就能看全, 不用先滚页面
  ③ 页内容高 ≤ 页面视口高         ⇒ 整页一屏放得下 (元任务表也看得见)

用法:
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_task_cfg_height.py
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_task_cfg_height.py --shot
      (--shot 另存 reports/ui_shots/taskcfg_*.png — 真机目检用)

两条路径都测 (与在役代码同一条构造路径, 判据不复制粘贴):
  A. 独立窗口 (画布工具栏 🗂 配置中心): QDialog + ConfigCenterPage, 尺寸按
     tools/gui/simulink_module.py 里那条屏幕可用区公式算 (屏宽×0.62 / 屏高×0.92, 上限 1700×1700)
  B. 主控制台容器 (studio 里的配置中心页): 页面直接 resize 到容器尺寸
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout                 # noqa: E402

import veh6_config_page as V                                                   # noqa: E402

WANT_SHOT = "--shot" in sys.argv
SHOT_DIR = os.path.join(ROOT, "reports", "ui_shots")

# 独立窗口尺寸公式 —— 与 tools/gui/simulink_module.py 的配置中心独立窗口同一份口径
DLG_W_FRAC, DLG_H_FRAC, DLG_W_CAP, DLG_H_CAP = 0.62, 0.92, 1700, 1700

RESULT = []


def measure(page, sa, label):
    t = page.tasks_table
    mt = getattr(page, "meta_table", None)
    inner = sa.widget()
    vp = sa.viewport().height()
    rowsum = sum(t.rowHeight(r) for r in range(t.rowCount()))
    y0 = t.mapTo(inner, t.rect().topLeft()).y()
    r = {
        "label": label,
        "tasks_h": t.height(),
        "tasks_vp": t.viewport().height(),
        "tasks_rows": t.rowCount(),
        "row_h_sum": rowsum,
        "rows_shown_by_vp": t.viewport().height() // max(1, t.rowHeight(0)),
        "table_vbar": t.verticalScrollBar().maximum(),
        "page_h": inner.height(),
        "page_minh": inner.minimumSizeHint().height(),
        "sa_vp": vp,
        "page_vbar": sa.verticalScrollBar().maximum(),
        "tasks_y0": y0,
        "tasks_y1": y0 + t.height(),
        "meta_h": mt.height() if mt else None,
        "out_h": page.out.height(),
        "vsplit": list(page.vsplit.sizes()),
    }
    r["c1_all_rows_in_table"] = (r["table_vbar"] == 0)
    r["c2_table_fully_visible"] = (r["tasks_y1"] <= vp)
    r["c3_page_fits"] = (r["page_vbar"] == 0)
    RESULT.append(r)
    print("  【%s】" % label)
    print("    任务表高 %d · 表内视口 %d · %d 行真实行高合计 %d (≈%d 行装得下) ⇒ 表内滚动条 max=%d  %s"
          % (r["tasks_h"], r["tasks_vp"], r["tasks_rows"], rowsum, r["rows_shown_by_vp"],
             r["table_vbar"], "✅ 全部任务行在表内" if r["c1_all_rows_in_table"] else "⛔ 被压扁"))
    print("    任务表在页内 y %d..%d (页面视口 %d) ⇒ %s"
          % (y0, r["tasks_y1"], vp,
             "✅ 打开即看全" if r["c2_table_fully_visible"]
             else "⚠ 页要滚 %dpx" % (r["tasks_y1"] - vp)))
    print("    页内容 %d / 页最小 %d / 页面视口 %d ⇒ 页面滚动条 max=%d  %s"
          % (r["page_h"], r["page_minh"], vp, r["page_vbar"],
             "✅ 整页一屏放得下" if r["c3_page_fits"] else "⚠ 页要滚 %dpx" % r["page_vbar"]))
    print("    元任务表高 %s · 信息窗 %d · vsplit %s" % (r["meta_h"], r["out_h"], r["vsplit"]))


def shot(w, tag, page):
    if not WANT_SHOT:
        return
    os.makedirs(SHOT_DIR, exist_ok=True)
    p = os.path.join(SHOT_DIR, "taskcfg_%s.png" % tag)
    page.grab().save(p)
    print("    📄 出图 %s" % p)


def _select_task_tab(app, page):
    for i in range(page.tabs.count()):
        if "任务配置" in page.tabs.tabText(i):
            page.tabs.setCurrentIndex(i)
    for _ in range(12):
        app.processEvents()


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    print("═══ A. 独立窗口 (画布工具栏 🗂 配置中心) ═══")
    for AW, AH, tag in ((3200, 1940, "本机 3200x2000 屏"), (1920, 1040, "常见 1920x1080 屏")):
        W = max(1280, min(DLG_W_CAP, int(AW * DLG_W_FRAC)))
        H = max(980, min(DLG_H_CAP, int(AH * DLG_H_FRAC)))
        dlg = QDialog()
        dlg.resize(W, H)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        page = V.ConfigCenterPage(model_page=None)
        lay.addWidget(page, 1)
        dlg.show()
        for _ in range(12):
            app.processEvents()
        _select_task_tab(app, page)
        print("\n──────── %s ⇒ 默认窗口 %dx%d ────────" % (tag, W, H))
        measure(page, page.tabs.widget(page.tabs.currentIndex()), "%s 默认窗口 %dx%d" % (tag, W, H))
        shot(W, "%dx%d" % (W, H), page)
        dlg.close()
        page.deleteLater()
        dlg.deleteLater()
        app.processEvents()

    print("\n═══ B. 主控制台容器 (studio 的配置中心页; 窗口大小由老倪自己拉) ═══")
    page = V.ConfigCenterPage(model_page=None)
    for W, H in ((2744, 1670), (2744, 1500), (2744, 1100), (1280, 820)):
        page.resize(W, H)
        page.show()
        for _ in range(10):
            app.processEvents()
        _select_task_tab(app, page)
        print("\n──────── 容器 %dx%d ────────" % (W, H))
        measure(page, page.tabs.widget(page.tabs.currentIndex()), "容器 %dx%d" % (W, H))
        shot(W, "container_%dx%d" % (W, H), page)
    page.close()
    page.deleteLater()

    print("\n═══ 汇总: %d 档实测 · ① 全部行在表内 %d/%d · ② 打开即看全 %d/%d ═══"
          % (len(RESULT),
             sum(1 for r in RESULT if r["c1_all_rows_in_table"]), len(RESULT),
             sum(1 for r in RESULT if r["c2_table_fully_visible"]), len(RESULT)))
    for r in RESULT:
        if not (r["c1_all_rows_in_table"] and r["c2_table_fully_visible"]):
            print("  ⚠ %s: 表内滚动 max=%d · 页需滚 %dpx (小屏分档, 如实列出)"
                  % (r["label"], r["table_vbar"], max(0, r["tasks_y1"] - r["sa_vp"])))
    # 硬判据只压"本机默认尺寸"这一档 (小屏分档如实打印, 不装作一样好)
    hard = [r for r in RESULT if "本机 3200x2000" in r["label"]]
    ok = bool(hard) and all(r["c1_all_rows_in_table"] and r["c2_table_fully_visible"] for r in hard)
    print("═══ 判据: 本机默认窗口下 ① + ② 必须成立 ⇒ %s ═══" % ("✅ PASS" if ok else "⛔ FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
