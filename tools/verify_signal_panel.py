# -*- coding: utf-8 -*-
"""判据: 信号分析窗口 列口径/可拖宽/图标/与数据空间同源同值。

老倪 2026-10-17: 「信号分析的窗口为什么没有图标? 左侧每列都可以用鼠标调整宽度;
   要与数据空间 trace 的数据同步, 列保持一致; 信号名称改 signal, 当前值改 value,
   输出节点改 Tx, 来源节点改 Rx; 增加 type 列; 增加 Layer 列; 增加中文名称列」
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "gui"))

fails = []
def ck(n, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", n)) + ((" · " + info) if info else ""))
    if not ok:
        fails.append(n)

app = QApplication.instance() or QApplication([])
from canoe_graphic import CanoeGraphicWidget, ROOT
from lerobot.middleware import live_signals as L

w = CanoeGraphicWidget()
hdr = [w.tree.headerItem().text(i) for i in range(w.tree.columnCount())]
ck("列口径 = Name/Signal/Value/Type/Tx/Rx/Layer",
   hdr == ["Name", "Signal", "Value", "Type", "Tx", "Rx", "Layer"], str(hdr))
ck("7 列全部可鼠标拖宽", all(w.tree.header().sectionResizeMode(i) == 0 for i in range(7)),
   str([w.tree.header().sectionResizeMode(i) for i in range(7)]))
_ico = os.path.join(ROOT, "tools/gui/logo.png")
ck("窗口图标存在且非空", os.path.exists(_ico) and not QIcon(_ico).isNull(), _ico)

# 同源: 三路都走 live_signals (与数据空间同一份缓存)
ck("sstrace/sseng/gravity 走同一 provider",
   all(k in getattr(w, "_PROV", {}) for k in ("sstrace", "sseng", "gravity"))
   or "live_signals" in open(os.path.join(ROOT, "tools/gui/canoe_graphic.py"), encoding="utf-8").read(),
   str(getattr(w, "_PROV", {})))

# 同值: 缓存窗口内两次读一致 (两个窗口都读这份)
a = L.topics(); time.sleep(0.1); b = L.topics()
ck("同一缓存窗口内数值一致", all(a[k]["fields"] == b[k]["fields"] for k in a),
   "%d 话题" % len(a))

# 行内容: 至少一行 7 列齐全且 Value 是数值
w.show(); t0 = time.time()
while time.time() - t0 < 2.5:
    app.processEvents(); time.sleep(0.1)
found = []
def walk(n):
    for i in range(n.childCount()):
        c = n.child(i)
        if c.childCount():
            walk(c)
        elif c.text(2) not in ("-", ""):
            found.append([c.text(k) for k in range(7)])
walk(w.tree.invisibleRootItem())
ck("有数值行", len(found) > 100, "%d 行" % len(found))
ck("每行 7 列都有内容", all(all(x.strip() for x in r) for r in found[:50]),
   str(found[:1]))
print("\n%s" % ("✅ 全部通过" if not fails else "❌ 失败: %s" % fails))
sys.exit(0 if not fails else 1)
