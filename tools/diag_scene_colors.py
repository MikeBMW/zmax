"""诊断: 信号目录里各"场景分组"实际有哪些行/什么颜色 (老倪: 「信号全都变成白色了? 应该分颜色, 绿蓝紫等」)

真建窗(offscreen) → 等数据源加载 → 遍历树: 分组标题 / 行数 / 每行颜色(去重取前 3) / 未分类数。
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/diag_scene_colors.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets                                            # noqa: E402

import canoe_graphic as cg                                             # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
w = cg.CanoeGraphicWidget()
w.resize(1720, 1010)
w.show()
for _ in range(60):                     # 等各数据源把快照读进来
    app.processEvents()
    time.sleep(0.1)

print("=" * 78)
print("信号目录: 分组 / 行数 / 行色 (真源 trace_live.json + engine_trace.json + trace.jsonl)")
print("=" * 78)
tot = 0
for i in range(w.tree.topLevelItemCount()):
    root = w.tree.topLevelItem(i)
    n = root.childCount()
    tot += n
    cols = {}
    for j in range(n):
        it = root.child(j)
        c = it.foreground(0).color().name()
        cols[c] = cols.get(c, 0) + 1
    top = ", ".join("%s×%d" % (c, k) for c, k in sorted(cols.items(), key=lambda x: -x[1])[:4]) or "—"
    print("  [%d 行] %-28s 行色: %s" % (n, root.text(0)[:28], top))
    for j in range(min(3, n)):
        print("        · %s" % root.child(j).text(0))
print("  合计 %d 行" % tot)
print("\n判定口径: 绿=插拔 #2e8b57 · 蓝=摆盘 #1f6feb · 紫=AR #8957e5 · 白=未分类(#ffffff) / 灰=#8b949e")
