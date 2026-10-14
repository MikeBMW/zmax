#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""show_config_center_7star.py — 在真显示器上打开配置中心页 (北斗七星阵版) 并出图。

用途: 离屏判据 (verify_config_center_seven_stars.py) 证明的是**数据与次序**; 这个脚本出**真渲染**的图,
供人目检字体/间距/是否截断 (老倪会把画面当结果看)。跑完自动退出, 不动生产控制台。
用法: DISPLAY=:0 gui-venv311/bin/python tools/show_config_center_7star.py [出图目录]
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout
    import veh6_config_page as V

    dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "docs", "data_snapshots", "20261015_config_center_seven_stars")
    os.makedirs(dst, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    dlg = QDialog()
    dlg.setWindowTitle("配置中心 (北斗七星阵) · 出图用临时窗口")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    page = V.ConfigCenterPage(model_page=None)
    lay.addWidget(page, 1)
    dlg.resize(1720, 950)
    dlg.show()

    # (页签关键字, 出图名, 要点的星 key 或 None) —— 单独出一张「只亮玉衡」证明一致性修复
    shots = [("任务配置", "天璇", None), ("产品配置", "天枢", None),
             ("功能·性能·模型", "天玑", "func"), ("功能·性能·模型", "玉衡", "perf")]
    state = {"i": 0}

    def _step():
        i = state["i"]
        if i >= len(shots):
            page.grab().save(os.path.join(dst, "real_page_full.png"))
            print("出图完成 →", dst)
            app.quit()
            return
        kw, star, key = shots[i]
        j = page._tab_index_by_title(kw)
        if j >= 0:
            page.tabs.setCurrentIndex(j)
        if key:
            page._goto_star(key)          # 点星 = 只亮这一颗 (一页三星时验证一致性)
        app.processEvents()
        f = os.path.join(dst, "real_%d_%s.png" % (i + 1, star))
        page.grab().save(f)
        print("  %s → %s (%d bytes)" % (star, os.path.basename(f), os.path.getsize(f)))
        state["i"] += 1
        QTimer.singleShot(600, _step)

    QTimer.singleShot(1500, _step)
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
