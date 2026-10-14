#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针: 「单独开的模型引擎窗口」与「功能区里内嵌的模型引擎面板」渲染是否一致 (2026-10-14 老倪要求)。

现状嫌疑: 权重路径列是 Stretch ⇒ 面板宽度随父容器变 ⇒ 同一层路径尾部截断不同 = 两处显示两个样。
本探针把同一个 ModelEnginePanel 分别放进 (a) 1900 宽窗口 (b) 1400 宽窄容器, 逐格比对。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.chdir("/home/ubuntu/zmax")

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout  # noqa: E402

app = QApplication.instance() or QApplication([])
import model_engine_window as MEW  # noqa: E402

inv = MEW._inv() if hasattr(MEW, "_inv") else None
if inv is None:
    import json
    import subprocess
    inv = json.loads(subprocess.run(MEW.INV_CMD, cwd=MEW.ROOT, capture_output=True, text=True,
                                    timeout=180).stdout)
st = {}
try:
    import urllib.request
    st = json.load(urllib.request.urlopen("http://127.0.0.1:8796/status/all", timeout=3))
except Exception:                                                             # noqa: BLE001
    st = {}


def dumppanel(p, tag):
    p.feed(inv, st)
    tb = p.tb
    rows = [[(tb.item(r, c).text() if tb.item(r, c) else "") for c in range(tb.columnCount())]
            for r in range(tb.rowCount())]
    return {"tag": tag, "w": p.width(), "minw": p.minimumWidth(), "cols": [tb.columnWidth(c) for c in range(tb.columnCount())],
            "rows": rows, "head": p.lb_head.text(), "font": tb.font().pointSize()}


win = MEW.ModelEngineWindow(poll=False)
win.resize(1900, 660)
win.show()
app.processEvents()
a = dumppanel(win.panel, "窗口(1900)")

box = QWidget()
box.resize(1400, 700)                       # 模拟功能区页面: 面板被塞进更窄的容器
lay = QVBoxLayout(box)
p2 = MEW.ModelEnginePanel(box, poll=False)
lay.addWidget(p2)
box.show()
app.processEvents()
b = dumppanel(p2, "窄容器(1400)")

print("列宽  窗口: %s" % a["cols"])
print("列宽 窄容器: %s" % b["cols"])
print("面板宽 窗口=%s(min %s) / 窄容器=%s(min %s)" % (a["w"], a["minw"], b["w"], b["minw"]))
print("表头 同? %s" % (a["head"] == b["head"]))
diff = []
for r in range(max(len(a["rows"]), len(b["rows"]))):
    ra = a["rows"][r] if r < len(a["rows"]) else []
    rb = b["rows"][r] if r < len(b["rows"]) else []
    for c in range(max(len(ra), len(rb))):
        va = ra[c] if c < len(ra) else ""
        vb = rb[c] if c < len(rb) else ""
        if va != vb:
            diff.append("r%d c%d\n    窗口: %s\n  窄容器: %s" % (r, c, va, vb))
print("逐格差异 %d 处:" % len(diff))
for d in diff[:8]:
    print("  " + d)
