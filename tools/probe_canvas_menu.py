#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_canvas_menu.py — 子进程: 主窗口「画布」菜单 + 画布接管 + QAction 兼容 (离屏真建真点)

为什么要子进程: 离屏建整个主窗口退出时 DDS 线程会 core dump (已知, 正常)。
放子进程 + 每行 flush, 父进程只读 stdout 的判定行 —— 崩了也不丢结果。
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/probe_canvas_menu.py
"""
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QAction                                # noqa: E402

app = QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402
import studio as ST                                                              # noqa: E402


def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + str(msg), flush=True)


print("probe ③ 菜单「画布(C)」6 项 + 点击真转发", flush=True)
win = ST.StudioMainWindow()
app.processEvents()
menu_titles = [a.text() for a in win.menuBar().actions()]
chk(any("画布" in t for t in menu_titles), f"主窗口一级菜单含「画布」 (共 {len(menu_titles)} 个: {menu_titles})")
acts = getattr(win, "_canvas_menu_acts", {})
chk(set(acts) == {"save_canvas", "load_canvas", "save_model", "record", "stop_rec", "float"},
    f"菜单 6 项齐全: {sorted(acts)}")
for k, sc in (("save_canvas", "Ctrl+Shift+S"), ("load_canvas", "Ctrl+Shift+L"),
              ("record", "Ctrl+Shift+R"), ("float", "Ctrl+Alt+F")):
    got = acts[k].shortcut().toString() if acts.get(k) else "—"
    chk(got == sc, f"{k} 快捷键 {got} (期望 {sc})")
chk(all(a.toolTip() for a in acts.values()), "6 项都有悬停说明")
win.simulink = None
try:
    win._canvas_menu_click("save_model")
    chk(True, "画布未就绪时点菜单: 只提示不崩")
except Exception as ex:
    chk(False, f"画布未就绪时点菜单崩了: {ex}")

print("probe ④ 画布接管 + 真触发 + QAction 兼容", flush=True)
m = SM.SimulinkModule()
called = []
for meth in ("export_flow", "import_flow", "save_trained_model", "start_recording",
             "stop_recording", "toggle_float_canvas"):
    setattr(m, meth, (lambda n: (lambda *a, **k: called.append(n)))(meth))
r = m.attach_canvas_actions(acts)
chk(r.get("ok") and r.get("n") == 6, f"attach_canvas_actions 接管 6 项 ({r})")
win.simulink = m
for k in ("save_canvas", "load_canvas", "save_model", "record", "stop_rec", "float"):
    acts[k].trigger()
chk(sorted(called) == sorted(["export_flow", "import_flow", "save_trained_model",
                              "start_recording", "stop_recording", "toggle_float_canvas"]),
    f"6 项菜单真触发到画布方法: {sorted(called)}")
chk(isinstance(getattr(m, "btn_record", None), QAction), "btn_record 现在是菜单项 (QAction)")
chk(getattr(m, "btn_stop_rec", None) is not None and m.btn_stop_rec.isEnabled() is False,
    "接管后「停止录制」初始不可点 (没在录)")
m.btn_record.setText("⏺ 录制中…")
m._rec_idx = 7
try:
    m._rec_blink_tick()
    chk(True, "_rec_blink_tick() 不炸 (样式表调用已去掉 → 改画布横幅报帧数)")
except Exception as ex:
    chk(False, f"_rec_blink_tick 抛异常: {ex}")
try:
    p = m._action_anchor(m.btn_save)
    chk(p is not None, f"_action_anchor() 给得出气泡锚点 ({p.x()},{p.y()})")
except Exception as ex:
    chk(False, f"_action_anchor 抛异常: {ex}")
print("probe ④ 画布工具栏: 🧮 状态空间 + 🛰 工位总览 两个按钮必须在 (2026-10-09 老倪要求找回)", flush=True)
try:
    m = SM.SimulinkModule()
    app.processEvents()
    for attr, txt in (("btn_state_space", "状态空间"), ("btn_station", "工位总览")):
        b = getattr(m, attr, None)
        chk(b is not None and txt in b.text(), f"工具栏有「{txt}」按钮 (attr={attr}, 文本={getattr(b, 'text', lambda: '—')() if b else '无'})")
        chk(bool(b) and b.isVisibleTo(m), f"「{txt}」按钮已挂进工具栏布局 (isVisibleTo=True, 没被 setVisible(False) 藏掉)")
    # 真点: 在**类**上替换两个方法 → 新建实例 → 点按钮 (构造时绑定的就是替身 ⇒ 真验证"点击→方法")
    hit = {}
    SM.SimulinkModule.open_state_space = lambda self, *a, **k: hit.setdefault("ss", True)
    SM.SimulinkModule.open_station_page = lambda self, *a, **k: hit.setdefault("station", True)
    m2 = SM.SimulinkModule()
    app.processEvents()
    m2.btn_state_space.click()
    m2.btn_station.click()
    app.processEvents()
    chk(hit.get("ss") and hit.get("station"),
        f"两个按钮点击真转发到 open_state_space / open_station_page (实测 {hit})")
    # 视觉证据: 把工具栏这一行真渲染成 PNG (老倪要"看得到", 不只看打印)
    try:
        _tb = m2.btn_state_space.parentWidget()
        _png = "/home/ubuntu/.hermes/cache/scratch/shots/canvas_toolbar.png"
        _tb.grab().save(_png)
        print("   工具栏截图: %s (%dx%d)" % (_png, _tb.width(), _tb.height()), flush=True)
    except Exception as _e:
        print("   ⚠️ 工具栏截图失败: %r" % _e, flush=True)

    # 信号真连上 (没连的按钮 receivers=0)
    chk(m2.btn_state_space.receivers(m2.btn_state_space.clicked) >= 1
        and m2.btn_station.receivers(m2.btn_station.clicked) >= 1,
        "两个按钮的 clicked 信号都有接收者 (不是摆设按钮)")
except Exception as ex:
    chk(False, f"工具栏按钮检查崩了: {ex!r}")

print("probe DONE", flush=True)
sys.stdout.flush()
os._exit(0)
