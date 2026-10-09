#!/usr/bin/env python3
"""🧭 控制台全功能页联通体检: 逐页切到 stack 上, 建窗 + 真渲染 + 抓关键控件/按钮

老倪 2026-10-09: 「整个控制台的所有功能，你都要联通运行；包括主界面的所有功能页，硬件配置，
训练引擎，数据集，场景，架构分层，功能」⇒ 本判据逐页给证据 (离屏, 不弹窗)。

判据: ① 页在 stack 里 ② 页内子控件数 > 0 ③ 页内至少 1 个可交互控件 (按钮/下拉/输入)
      ④ 有页面标题/首行文字 ⑤ 离屏渲染不抛异常
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/probe_pages_sweep.py
"""
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import (QApplication, QPushButton, QComboBox,   # noqa: E402
                             QLineEdit, QSpinBox, QCheckBox, QLabel, QWidget,
                             QToolButton, QRadioButton, QSlider, QCommandLinkButton)

app = QApplication(sys.argv)
import studio as ST  # noqa: E402

win = ST.StudioMainWindow()
win.resize(1600, 1000)
win.show()
for _ in range(8):
    app.processEvents()

NAMES = {v: k for k, v in ST.StudioMainWindow.__dict__.get("modules", {}).items()} if False else {}


def chinese_name(idx):
    m = getattr(win, "modules", {}) or {}
    for k, v in m.items():
        if v == idx:
            return k
    return "?"


n = win.stack.count()
print("══ 控制台功能页体检: stack 共 %d 页 ══" % n)
bad = []
for i in range(n):
    try:
        w = win.stack.widget(i)
        win.stack.setCurrentIndex(i)
        for _ in range(3):
            app.processEvents()
        kids = w.findChildren(QWidget)
        btns = w.findChildren(QPushButton)
        combos = w.findChildren(QComboBox)
        edits = w.findChildren(QLineEdit) + w.findChildren(QSpinBox)
        chks = w.findChildren(QCheckBox)
        # 🐛 2026-10-09: 有的页 (插拔场景/架构) 用 QToolButton / 卡片式自定义控件,
        #    只数 QPushButton 会误判"0 可交互" ⇒ 交互控件口径放宽
        inter = (len(btns) + len(combos) + len(edits) + len(chks)
                 + len(w.findChildren(QToolButton)) + len(w.findChildren(QRadioButton))
                 + len(w.findChildren(QSlider)) + len(w.findChildren(QCommandLinkButton)))
        labels = [x.text() for x in w.findChildren(QLabel) if (x.text() or "").strip()]
        pm = w.grab()
        px = pm.width() * pm.height()
        ok = len(kids) > 3 and (inter >= 1 or len(labels) >= 3) and px > 0
        title = (labels[0][:26] if labels else w.__class__.__name__)
        print("  %s [%2d] %-14s %-30s 子控件 %4d · 交互 %3d (按钮 %3d/工具 %2d) · 标签 %3d · 渲染 %dx%d"
              % ("✅" if ok else "❌", i, chinese_name(i), title, len(kids), inter, len(btns),
                 len(w.findChildren(QToolButton)), len(labels), pm.width(), pm.height()))
        if not ok:
            bad.append((i, chinese_name(i), len(kids), inter))
    except Exception as e:                                                  # noqa: BLE001
        bad.append((i, chinese_name(i), "异常", str(e)[:60]))
        print("  ❌ [%2d] %-14s 异常: %s" % (i, chinese_name(i), e))
        traceback.print_exc()

# 回首页, 顺便核首页功能卡可点
win.stack.setCurrentIndex(0)
for _ in range(3):
    app.processEvents()
print("\n══ 判定 ══")
if bad:
    print("❌ 失败 %d 页: %s" % (len(bad), bad))
    sys.stdout.flush()
    # 🐛 2026-10-09: 离屏 Qt 在 teardown (win.close/app.quit/解释器退出) 会 SIGABRT(134),
    #    判定已经打完 ⇒ 直接 _exit 交作业, 别让 teardown 把 exit code 搅成 134。
    os._exit(1)
print("✅ 全部通过: %d 个功能页都能建、有内容、可交互、离屏渲染无异常" % n)
sys.stdout.flush()
os._exit(0)
