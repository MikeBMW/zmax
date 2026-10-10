#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「配置中心 → 文档配置/文档预览」真渲染成 PNG (老倪要看画面, 不看日志)。

用离屏真渲染 (不碰现场正在用的窗口), 出图:
  1_左树文档配置_预览SOR.png      —— 左树展开「📄 文档配置」, 内置窗口显示 SOR 的实际内容
  2_一致性核对.png                —— 三份文档 × 当前真源 逐条比对
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/shots_config_docs.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PyQt5.QtWidgets import QApplication  # noqa: E402
import veh6_config_page as vp  # noqa: E402

OUT = os.path.join(ROOT, "outputs", "ui_shots")
os.makedirs(OUT, exist_ok=True)


def save(widget, name):
    widget.repaint()
    QApplication.processEvents()
    p = os.path.join(OUT, name)
    widget.grab().save(p)
    print(f"  ✅ {p}  ({os.path.getsize(p) / 1024:.0f} KB)")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = vp.build_config_center(None, None)
    page.resize(1600, 950)
    page.show()
    QApplication.processEvents()

    # 展开文档配置节点
    for i in range(page.tree.topLevelItemCount()):
        it = page.tree.topLevelItem(i)
        if "文档配置" in it.text(0):
            it.setExpanded(True)
    QApplication.processEvents()

    def click(node_kw):
        for i in range(page.tree.topLevelItemCount()):
            t = page.tree.topLevelItem(i)
            if "文档配置" in t.text(0):
                for j in range(t.childCount()):
                    if node_kw in t.child(j).text(0):
                        page._on_tree(t.child(j), 0)
                        return True
        return False

    assert click("SOR"), "找不到 SOR 节点"
    QApplication.processEvents()
    save(page, "1_左树文档配置_预览SOR.png")

    page._show_consistency()
    QApplication.processEvents()
    save(page, "2_一致性核对.png")

    # 3) 点左树「性能配置」→ 右侧只剩该域的行 (老倪 2026-10-10: 点域右侧必须有内容)
    for i in range(page.tree.topLevelItemCount()):
        it = page.tree.topLevelItem(i)
        if "性能配置" in it.text(0):
            page._on_tree(it, 0)
            break
    QApplication.processEvents()
    save(page, "3_点性能配置_右侧只筛该域.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
