"""QTreeWidget/QTableWidget 周期刷新成本探针 (通用, 不依赖项目代码).

用途: 证"界面反应慢"不是机器慢, 而是刷新循环每拍把全部行写一遍。
  python3 qt_tree_refresh_cost_probe.py            # 460 行, 4Hz
  python3 qt_tree_refresh_cost_probe.py 800 20     # 800 行, 20Hz

量三件事, 与线上 py-spy 栈对照:
  ① 旧写法 (每行 setText + setToolTip) 的 ms/拍 与折算核占用
  ② 缓存写法 (值/tooltip 未变就不写) 的 ms/拍
  ③ 每拍收到的 itemChanged 次数 —— 旧写法≈行数(setToolTip 也会发 itemChanged(col=0)), 缓存写法稳态=0

退出码: 0 = 缓存写法抑制了风暴; 2 = 仍然每行都发 itemChanged (修法没生效)
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 460
HZ = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0


class _Buf:
    """最小可用的行数据 (真项目里换成你的 SignalBuffer/数据行对象)"""

    def __init__(self, key):
        self.key = key
        self.src = "probe"
        self.n = 10
        self.last_val = 1.0
        self.age = 0.1
        self.vmin = 0.0
        self.vmax = 2.0


app = QApplication(sys.argv[:1])
tree = QTreeWidget()
tree.setColumnCount(3)
tree.setHeaderLabels(["信号", "当前值", "来源"])
store = {}
for i in range(N):
    key = "probe.sig%04d" % i
    store[key] = _Buf(key)
    it = QTreeWidgetItem(tree)
    it.setText(0, key)
    it.setData(0, Qt.UserRole, key)
    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
    it.setCheckState(0, Qt.Checked)
tree.show()
app.processEvents()

hits = {"itemChanged": 0}
tree.itemChanged.connect(lambda *a: hits.__setitem__("itemChanged", hits["itemChanged"] + 1))
items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]


def legacy_tick():
    for it in items:
        b = store.get(it.data(0, Qt.UserRole))
        if b is None or b.last_val is None:
            continue
        it.setText(1, "%.4g" % b.last_val)
        it.setToolTip(0, "%s 帧龄 %.2fs" % (b.key, b.age))


cache = {}


def cached_tick():
    for it in items:
        key = it.data(0, Qt.UserRole)
        b = store.get(key)
        if b is None or b.last_val is None:
            continue
        txt = "%.4g" % b.last_val
        tt = "%s 帧龄 %.2fs" % (b.key, b.age)
        if cache.get(key) == (txt, tt):
            continue
        if it.text(1) != txt:
            it.setText(1, txt)
        it.setToolTip(0, tt)
        cache[key] = (txt, tt)


def bench(fn, label):
    hits["itemChanged"] = 0
    t0 = time.perf_counter()
    for _ in range(10):
        fn()
    ms = (time.perf_counter() - t0) / 10 * 1000
    app.processEvents()
    got = hits["itemChanged"]
    print("%-6s %8.3f ms/拍 | itemChanged %4d 次/拍 | %5.0f Hz 折算 %5.1f%% 一个核"
          % (label, ms, got, HZ, ms * HZ / 10.0))
    return ms, got


legacy_ms, legacy_hits = bench(legacy_tick, "旧写法")
cached_ms, cached_hits = bench(cached_tick, "缓存写")
bench(cached_tick, "稳态再刷")          # 第三遍: 缓存命中, itemChanged 必须 0

print("提速 %.0f×" % (legacy_ms / max(cached_ms, 1e-9)))
ok = cached_hits <= max(1, N // 100)   # 首拍允许每行写一次
if not ok:
    print("FAIL: 缓存写法仍然每行发 itemChanged ⇒ 槽里的 state-equality 早退没加上?")
    sys.exit(2)
print("PASS")
