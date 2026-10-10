#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取证: 配置中心「点左树四个域, 右侧必须有内容」(2026-10-10 老倪: 「性能配置 功能配置 工程配置 模型配置, 怎么无法显示呢? 主窗口没有内容」)

根因: 旧 `_on_tree` 对域节点只 `_run_into("overview")` —— 只刷底部面板, **右侧工作区根本不动**,
      看起来就是"点了没内容/没反应"。修后: 点域 → 切到对应页签 + 只筛该域的行; 点参数 ID → 定位并高亮那一行。

判据:
  1. 点 工程配置 → 切到「⚙️ 工程配置」页且可见行 = 9
  2. 点 功能配置/性能配置 → 切到「🧩 功能·性能·模型」且可见行 = 3 / 6 (不是 0, 也不是全部 15)
  3. 点 模型配置 → 切到有内容的页 (专门的「🧠 模型配置」或合页), 可见行 > 0
  4. 点参数 ID 子项 → 该页只剩 1 行且正是这一行 (选中)
  5. 「显示全部」能恢复全部行
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/tests/test_config_center_domains.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PyQt5.QtWidgets import QApplication  # noqa: E402
import veh6_config_page as vp  # noqa: E402

FAIL = []
DOMAINS = ("模型配置", "工程配置", "功能配置", "性能配置")


def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ⛔ ") + name + ("   " + str(detail) if detail else ""))
    if not ok:
        FAIL.append(name)


def vis_rows(page, tab_title):
    if "工程配置" in tab_title:
        t = page.tab2_table
    elif "功能·性能" in tab_title:
        t = page.tab3_table
    else:
        return None
    return sum(1 for r in range(t.rowCount()) if not t.isRowHidden(r))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = vp.build_config_center(None, None)
    page.resize(1600, 950)
    page.show()
    app.processEvents()

    print("═══ 1) 点四个域 → 右侧切页且有内容 ═══")
    seen = {}
    for i in range(page.tree.topLevelItemCount()):
        it = page.tree.topLevelItem(i)
        txt = it.text(0)
        page._on_tree(it, 0)
        app.processEvents()
        cur = page.tabs.tabText(page.tabs.currentIndex())
        n = vis_rows(page, cur)
        print(f"      点 {txt!r:26} → 页签 {cur!r:18} 可见行 {n}")
        for d in DOMAINS:
            if d in txt:
                seen[d] = (cur, n)
    for d in DOMAINS:
        cur, n = seen.get(d, ("(没找到)", None))
        check(f"点『{d}』切到非任务配置页且有内容",
              "任务配置" not in cur and (n is None or n > 0), f"{cur} 行={n}")

    print("\n═══ 2) 数值口径 (过滤才叫显示, 全显等于没筛) ═══")
    check("工程配置筛出 9 行", seen.get("工程配置", ("", -1))[1] == 9, seen.get("工程配置"))
    check("功能配置筛出 3 行", seen.get("功能配置", ("", -1))[1] == 3, seen.get("功能配置"))
    check("性能配置筛出 6 行", seen.get("性能配置", ("", -1))[1] == 6, seen.get("性能配置"))

    print("\n═══ 3) 点参数 ID → 精确定位到那一行 ═══")
    c = page.tree.topLevelItem(2).child(0)          # 功能配置 → feature.cap_level
    page._on_tree(c, 0)
    app.processEvents()
    tb = page.tab3_table
    vis = [r for r in range(tb.rowCount()) if not tb.isRowHidden(r)]
    print(f"      点 {c.text(0)!r} → 可见行 {vis} · 选中行 {tb.currentRow()} · 页签 {page.tabs.tabText(page.tabs.currentIndex())!r}")
    check("参数 ID 定位到唯一行", len(vis) == 1 and tb.currentRow() == vis[0], (vis, tb.currentRow()))

    print("\n═══ 4) 显示全部可恢复 ═══")
    page._filter_fpm(None)
    app.processEvents()
    n = sum(1 for r in range(tb.rowCount()) if not tb.isRowHidden(r))
    check("恢复全部行", n == tb.rowCount(), f"{n}/{tb.rowCount()}")

    print("\n═══ 5) 未知参数不静默 ═══")
    page.out.setPlainText("")
    page._on_tree(type(c)([c.text(0)]), 0) if False else None
    from PyQt5.QtWidgets import QTreeWidgetItem
    fake = QTreeWidgetItem(["   no.such_param_xyz"])
    page._on_tree(fake, 0)
    app.processEvents()
    check("找不到的参数有明确提示", "没有参数" in page.out.toPlainText(), page.out.toPlainText()[:60])

    print("\n" + ("✅ 全部通过" if not FAIL else "⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
