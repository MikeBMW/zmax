#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_open_space.py — 真建主窗口, 真跑「打开总工程」流程 (老倪: 「点击 open 怎么没反应? 应该打开 simulink 画布啊」)

做法: 把确认框/提示框换成替身 (自动 确定 / 记录文字), 调 win._open_space_file(路径),
      打印: 打开前后 stack 当前页 / simulink 是否存在 / 画布节点数 / 右侧栏视图 / 替身收到的文案 / 任何异常。
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/probe_open_space.py [工程文件]
"""
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication                                         # noqa: E402

app = QApplication(sys.argv)
import studio as ST                                                              # noqa: E402
import project_file as PF                                                        # noqa: E402

path = sys.argv[1] if len(sys.argv) > 1 else PF.space_path()
print("工程文件:", path, "存在:", os.path.exists(path), flush=True)

win = ST.StudioMainWindow()
# 等懒创建的画布模块 (启动后 400ms 建)
for _ in range(60):
    app.processEvents()
    if getattr(win, "simulink", None) is not None:
        break
    import time as _t
    _t.sleep(0.2)
print("simulink 模块:", type(getattr(win, "simulink", None)).__name__, flush=True)

# 替身: 确认框**一律返回"取消"** (若代码还要问, 打开就会被取消 → 用来证明"打开=一步, 没有二次确认")
#       提示框只记录文字
msgs, asks = [], []
def _deny_ask(*a, **k):
    asks.append(a[1] if len(a) > 1 else "?")
    return 0                                   # 0 = 用户点了取消
ST._msg_ask = _deny_ask
ST._msg_ok = lambda *a, **k: (msgs.append((a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")), 0)[1]

idx_before = win.stack.currentIndex()
sim = getattr(win, "simulink", None)
print("打开前: stack 当前页 =", idx_before, "/", win.stack.count(),
      "· 画布 tab 应 =", getattr(win, "_simulink_index", None),
      "· 画布场景项 =", len(sim.canvas.items()) if sim and getattr(sim, "canvas", None) else "-", flush=True)

try:
    win._open_space_file(path)
except Exception as ex:
    import traceback
    print("❌ _open_space_file 抛异常:", type(ex).__name__, ex, flush=True)
    traceback.print_exc()

app.processEvents()
sim = getattr(win, "simulink", None)
print("打开后: stack 当前页 =", win.stack.currentIndex(), "/", win.stack.count(),
      "· 画布 tab =", getattr(win, "_simulink_index", None), flush=True)
if sim is not None:
    _it = len(sim.canvas.items()) if getattr(sim, "canvas", None) else 0
    print("画布 tab 是不是当前页 =", win.stack.currentWidget() is sim,
      "· 画布场景项 =", _it, "(89 节点 + 184 连线 ⇒ ≥250 才算真装上)",
      "· 右侧栏当前视图 =",
          getattr(getattr(sim, "model_tree", None), "cmb_view", None) and
          sim.model_tree.cmb_view.currentText(), flush=True)
for t, b in msgs:
    print("── 对话框 [%s] ──" % t, flush=True)
    print((b or "")[:900], flush=True)
_front = (sim is not None) and (win.stack.currentWidget() is sim)
_items = len(sim.canvas.items()) if (sim is not None and getattr(sim, "canvas", None)) else 0
_noask = (len(asks) == 0)
_ok = bool(_front and _items >= 250 and _noask)
print(("  ✅ " if _front else "  ❌ ") + "打开工程后停在 Simulink 画布页 (当前页是画布=%s)" % _front, flush=True)
print(("  ✅ " if _items >= 250 else "  ❌ ") + "画布真装上 (%d 场景项 ≥ 250)" % _items, flush=True)
print(("  ✅ " if _noask else "  ❌ ") +
      "打开=一步: 没有二次确认框 (确认框调用 %d 次%s)" % (
          len(asks), "" if not asks else " → " + "、".join(asks)), flush=True)
print(("🎉 全部通过: 3 项" if _ok else "❌ 失败"), flush=True)
print("DONE", flush=True)
os._exit(0 if _ok else 1)
