"""诊断: 主窗口各条曲线的**横轴口径**是否一致 (老倪: 「时间轴怎么不同步呢? 八阶段序号单独跑, 下面几个信号一起跑」)

真建窗(offscreen) → 等数据源加载 → 逐条打印: key / 来源 / scene 标记(横轴=场景时刻?) / 点数 /
x 范围(min~max, 首/末) —— 一眼看出哪条曲线的横轴跟别人不是一个口径。
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/diag_signal_x.py
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
for _ in range(80):
    app.processEvents()
    time.sleep(0.1)

print("=" * 96)
print("主窗口曲线横轴口径 (scene=True ⇒ 横轴=3D 场景时刻 时间_s; False ⇒ 横轴=数据到达时刻)")
print("=" * 96)
print("%-26s %-9s %-4s %6s  %-30s %s" % ("信号", "横轴", "点数", "n", "x 范围(min~max)", "来源"))
for k in list(w.selected):
    b = w.store.bufs.get(k)
    if b is None:
        print("%-26s （缓冲区不存在）" % k)
        continue
    try:
        t, _ = b.arrays()
        rng = "%.3f ~ %.3f  (末 %.3f)" % (float(t.min()), float(t.max()), float(t[-1])) if len(t) else "—"
    except Exception as e:                                                 # noqa: BLE001
        rng = "取 x 失败 %s" % type(e).__name__
    print("%-26s %-9s %-4s %6d  %-30s %s" % (k, "场景时刻" if getattr(b, "scene", False) else "到达时刻",
                                             "是" if getattr(b, "scene", False) else "否", b.n, rng, b.src))
print("\n判定: 同屏所有曲线要么都走**场景时刻**(回放进度, 0~时长), 要么都走**到达时刻**; 混着就不同步。")
