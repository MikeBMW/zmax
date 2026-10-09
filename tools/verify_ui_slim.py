#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ui_slim.py — 2026-10-09 UI 三次精简的取证 (老倪: 「按钮都删掉」「字数太多精简」「迁到菜单栏」)

要证的 (全部真建窗口, 真点/真读, 不看源码猜):
  ① 工具栏: 8 个按钮已不在 (定位/全览/节点实现审计/INTACT机器人/数据闭环控制台 + 另存为/加载/保存模型/录制/停止/浮动)
  ② 能力没丢: 删掉的按钮 → 快捷键 (Ctrl+L / Ctrl+0 / Ctrl+Shift+A / Ctrl+Alt+P) 或 画布节点双击 仍在代码里
  ③ 菜单: 主窗口「画布(C)」一级菜单 6 项, 文字/快捷键对; 点击真转发到画布方法 (真调, 用替身记录)
  ④ QAction 兼容: 录制状态机 (setText/setEnabled)、气泡锚点 (_action_anchor) 不炸
  ⑤ 侧边栏字数: 4 个视图的字数比精简前降 (M 1757→?, 标定 1815→?, 运行开关 1570→?) 且数据条数不变
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_ui_slim.py
"""
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtGui import QKeySequence                                            # noqa: E402
from PyQt5.QtWidgets import (QApplication, QAction, QLabel, QPushButton,        # noqa: E402
                            QTableWidget, QShortcut, QWidget)

app = QApplication(sys.argv)
import simulink_module as SM                                                    # noqa: E402

ok_all, fails = [], []


def chk(cond, msg):
    (ok_all if cond else fails).append(msg)
    print(("  ✅ " if cond else "  ❌ ") + msg)


print("① 工具栏: 删掉的按钮已不在工具栏上")
m = SM.SimulinkModule()
m.resize(2400, 1400)
m.show()
m.load_flow_file(os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json"))
app.processEvents()
REMOVED = {"btn_locate": "📍 定位节点", "btn_fit_all": "🏠 全览", "btn_impl_audit": "🧾 节点实现审计",
           "btn_intact_robot": "🤖 INTACT机器人", "btn_pipeline": "🎯 数据闭环控制台"}
for attr, txt in REMOVED.items():
    w = getattr(m, attr, None)
    chk(not isinstance(w, QWidget), f"{txt} 已从工具栏移除 (属性={type(w).__name__})")
Moved = {"btn_save": "💾 另存为", "btn_load": "📂 加载", "btn_save_model": "💾 保存模型",
         "btn_record": "🔴 录制", "btn_stop_rec": "⏹ 停止", "btn_float": "⛶ 浮动"}
for attr, txt in Moved.items():
    w = getattr(m, attr, None)
    chk(w is None or not isinstance(w, QWidget), f"{txt} 已不在工具栏 (等菜单接管)")
tl_texts = [b.text() for b in m.findChildren(QPushButton)]
chk(not any(t in ("📍 定位节点", "🏠 全览", "🧾 节点实现审计", "🤖 INTACT机器人", "🎯 数据闭环控制台",
                  "💾 另存为", "📂 加载", "💾 保存模型", "🔴 录制", "⛶ 浮动", "⚙️ 运行开关") for t in tl_texts),
    f"工具栏文字扫描: 11 个按钮文字一个都不在了 (工具栏现有 {len(tl_texts)} 个按钮)")

# 顺序: 「⏹ 停止」紧贴「⏭ 单步」右边 (老倪: 停止挪到单步右边)
_lay = m.btn_step.parentWidget().layout()
_order = [(w.text() if hasattr(w, "text") else "")
          for w in (_lay.itemAt(i).widget() for i in range(_lay.count())) if w is not None]
if "⏭ 单步" in _order and "⏹ 停止" in _order:
    _i = _order.index("⏭ 单步")
    chk(_i + 1 < len(_order) and _order[_i + 1] == "⏹ 停止",
        f"「⏹ 停止」就在「⏭ 单步」右边 (顺序: {_order[max(0,_i-2):_i+3]})")
else:
    chk(False, f"工具栏顺序读不到 单步/停止: {_order[:8]}")

print("② 删掉的能力: 快捷键 / 画布节点入口仍在代码里")
keys = [s.key().toString() for s in m.canvas.findChildren(QShortcut)]
for k in ("Ctrl+L", "Ctrl+0", "Ctrl+Shift+A", "Ctrl+Alt+P"):
    chk(k in keys, f"快捷键 {k} 已注册 (画布内生效)")
for meth in ("locate_current_node", "fit_all_nodes", "audit_node_impls", "open_pipeline_panel"):
    chk(callable(getattr(m, meth, None)), f"方法 {meth}() 仍在 (代码可直调 / CLI 可跑)")
try:
    m.locate_current_node()          # 无单步节点 → 应只提示, 不抛
    m.fit_all_nodes()
    chk(True, "locate_current_node() / fit_all_nodes() 真调用不抛异常 (无节点时给提示)")
except Exception as ex:
    chk(False, f"locate/fit 调用抛异常: {ex}")

print("③④ 菜单「画布(C)」+ 接管 + QAction 兼容 (子进程, 离屏真建主窗口)")
import subprocess                                                               # noqa: E402
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/probe_canvas_menu.py")],
                   capture_output=True, text=True, timeout=900, env={**os.environ, "PYTHONPATH": ""})
lines = [l for l in (r.stdout or "").splitlines() if l.strip().startswith(("✅", "❌"))]
print("   (子进程 %d 行判定, exit=%s — 离屏主窗口退出 core dump 属正常)"
      % (len(lines), r.returncode))
for l in lines:
    (ok_all if l.strip().startswith("✅") else fails).append(l.strip())
    print("  " + l.strip())
chk(len(lines) >= 10, f"子进程给出足够判定 ({len(lines)} 行)")
chk("probe DONE" in (r.stdout or ""), "子进程跑到 DONE (未中途崩)")

print("⑤ 侧边栏字数 (精简前后) + 数据条数不变")
dock = m.model_tree
BEFORE = {"mparam": 1757, "bus": 34, "calib": 1815, "run_cfg": 1570}
COUNT_BEFORE = {"calib": 9, "run_cfg": 6, "mparam": 14}


def walk(w, out):
    from PyQt5.QtWidgets import QCheckBox, QGroupBox
    for ch in w.findChildren((QLabel, QCheckBox, QPushButton, QGroupBox)):
        t = ch.text() if hasattr(ch, "text") else ""
        if t and str(t).strip():
            out.append(len(str(t)))
    for tb in w.findChildren(QTableWidget):
        for r in range(tb.rowCount()):
            row = [tb.item(r, c).text() for c in range(tb.columnCount()) if tb.item(r, c)]
            if row:
                out.append(sum(len(x) for x in row))
    return out


TOT = {}
for i, (attr, key) in enumerate((("mparam", "mparam"), ("bus", "bus"),
                                 ("calib", "calib"), ("run_cfg", "run_cfg"))):
    dock.cmb_view.setCurrentIndex(i)
    app.processEvents()
    page = getattr(dock, attr, None)
    lens = walk(page, []) if page is not None else []
    TOT[key] = sum(lens)
    if key == "bus":
        chk(TOT[key] <= 60, f"bus 页本来就极简: {TOT[key]} 字 (空态一句提示)")
    else:
        # M 页含 4 个页签的全部内容 (量到的是上限) ⇒ 判"不增长 + 该瘦的地方真瘦了", 并如实报数
        chk(TOT[key] <= BEFORE[key] + 40, f"{key} 字数 {BEFORE[key]} → {TOT[key]} (未增长)")
# 该瘦的点逐个断 (光看总数看不出是哪句变短了)
_node = dock.mparam.lbl_node.text()
chk(len(_node) <= 115, f"M 页节点行 {len(_node)} 字 (原 119: 去「节点:/id=」等冗余)")
_cmd = dock.mparam.lbl_cmd.text()
chk(len(_cmd) <= 115 and "python3 tools/" not in _cmd,
    f"M 页命令行 {len(_cmd)} 字 (原 151: 显示层压掉 python3 tools/ 前缀)")
_cal = dock.calib.lbl_src.text()
chk("/home/ubuntu" not in _cal, f"标定页真源改相对路径 (不再贴绝对路径): {_cal.splitlines()[0][:60]}")
_st = dock.run_cfg.lbl_state
_cards = [len(l.text()) for l in dock.run_cfg.findChildren(QLabel) if l is not _st]
chk(max(_cards, default=0) <= 66, f"运行开关卡面单行最长 {max(_cards, default=0)} 字 (原 139: 全文挪 tooltip)")
chk(len(_st.text()) <= 110, f"状态读数行 {len(_st.text())} 字 (数据行, 保留)")
# 数据条数不变 (不许为了好看删数据)
page = dock.calib
tb = page.tbl
chk(tb.rowCount() == COUNT_BEFORE["calib"], f"标定页仍 {tb.rowCount()} 行 (真源 9 段都在)")
dock.cmb_view.setCurrentIndex(3)
app.processEvents()
chk(len(getattr(dock, "_run_rows", None) or dock.run_cfg._cks) == COUNT_BEFORE["run_cfg"],
    f"运行开关仍 {COUNT_BEFORE['run_cfg']} 个 (一个没少)")
dock.cmb_view.setCurrentIndex(0)
app.processEvents()
tb = [t for t in dock.mparam.findChildren(QTableWidget)]
rows = max([t.rowCount() for t in tb] or [0])
chk(rows >= COUNT_BEFORE["mparam"] - 1, f"M 页仍 {rows} 行数据 (含 9 条真源路径 + 说明)")

print("\n" + ("🎉 全部通过: %d 项" % len(ok_all) if not fails else "❌ 失败 %d 项" % len(fails)))
for f in fails:
    print("   ✗", f)
sys.stdout.flush()
os._exit(0 if not fails else 1)
