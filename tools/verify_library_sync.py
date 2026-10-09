#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_library_sync.py — 📚 模块库 ↔ 画布: 同步/拖拽/删除/另存 判据 (2026-10-09 老倪)

老倪的四条要求 → 七条判据:
  ①  所有状态空间节点都在模块库里        → lib_sync.py verify 子进程 rc=0 (89/89, 0 死条目, 0 重名)
  ②  「模块库可以拖进画布」通道齐备        → canvas.setAcceptDrops + dragEnter/dragMove/dropEvent + MIME
  ③  真拖一次: 落点即节点位置             → 造 QDropEvent 打真 dropEvent → 节点 +1, 名字/坐标对
  ④  画布变了库跟着变 (同步是活的)        → 画布加节点 → refresh_library → 库里出现该节点
  ⑤  删除: 库条目可移除且不动画布          → _remove_entry → curation +1, 库条目 -1, 画布节点数不变
  ⑥  可以保存为新的工程文件               → export_flow (替你点文件框) → 新 JSON 落盘 + 节点数一致
  ⑦  没有联系/没有关联的都删掉            → 0 条无关联 (② 同源) + curation 名单在册

用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_library_sync.py
      (主窗口内 DDS 线程 → 退出必 core dump, 所以 os._exit 直退; 父进程看 rc/判定行)
"""
import json
import os
import subprocess
import sys

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, Qt, QMimeData                                   # noqa: E402
from PyQt5.QtGui import QDropEvent                                               # noqa: E402
from PyQt5.QtWidgets import QApplication, QFileDialog                             # noqa: E402

FAIL = []


def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + str(msg), flush=True)
    if not cond:
        FAIL.append(str(msg))


app = QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402

print("① 同步判定 (lib_sync.py verify 子进程)", flush=True)
env = dict(os.environ)
env["QT_QPA_PLATFORM"] = "offscreen"
env.pop("PYTHONPATH", None)
r = subprocess.run([PY, os.path.join(ROOT, "tools/lib_sync.py"), "verify"],
                   capture_output=True, text=True, env=env, cwd=ROOT, timeout=600)
lines = [x for x in (r.stdout or "").splitlines() if x.strip()
         and "Unknown" not in x and "plugin" not in x and "propagate" not in x]
for x in lines:
    print("     " + x, flush=True)
chk(r.returncode == 0, "lib_sync verify rc=%d (0=画布节点全在库·0死条目·0重名)" % r.returncode)

print("② 「拖进画布」通道齐备", flush=True)
import studio as ST                                                              # noqa: E402

win = ST.StudioMainWindow()
for _ in range(80):                     # 画布模块是懒创建的 (启动后 ~400ms)
    app.processEvents()
    if getattr(win, "simulink", None) is not None:
        break
    import time as _t
    _t.sleep(0.2)
mod = win.simulink
cv = mod.canvas
if not mod.nodes:                       # 主窗口默认在首页 → 显式装上状态空间画布
    _ssf = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
    mod.load_flow_file(_ssf, confirm=False)
    app.processEvents()
chk(len(mod.nodes) > 60, "画布已装上状态空间工程 (%d 节点)" % len(mod.nodes))
chk(getattr(cv, "acceptDrops", lambda: False)(), "画布 setAcceptDrops(True)")
chk(SM.LIB_MIME == "application/x-zmax-lib-item", "拖拽 MIME 常量 = %s" % SM.LIB_MIME)
chk(all(hasattr(cv, m) for m in ("dragEnterEvent", "dragMoveEvent", "dropEvent")),
    "画布有 dragEnterEvent / dragMoveEvent / dropEvent")
chk(hasattr(SM, "LibButton"), "模块库按钮类 LibButton 在")
_btns = getattr(mod.library, "_lib_btns", {}) or {}
_lib_btns = [b for b in _btns.values() if isinstance(b, SM.LibButton)]
chk(len(_btns) > 300 and len(_lib_btns) > 300,
    "库按钮 %d 个 (可拖 %d 个 LibButton)" % (len(_btns), len(_lib_btns)))

print("③ 真拖一次 (造 QDropEvent 打真 dropEvent, 落点 = 节点位置)", flush=True)
_pick = None
for nm, b in _btns.items():
    if isinstance(b, SM.LibButton):
        _pick = b
        break
_pay = _pick.drag_payload() if _pick else None
chk(bool(_pay and _pay.get("name")), "取到库条目: %s" % (_pay or {}).get("name"))
_n0 = len(mod.nodes)
_p1 = QPointF(1234.0, 567.0)
_mime1 = _pick.drag_mime()                       # ⚠️ 必须持引用 (QDropEvent 不接管所有权, 被 GC = 段错误)
_ev = QDropEvent(_p1, Qt.CopyAction, _mime1, Qt.LeftButton, Qt.NoModifier)
cv.dropEvent(_ev)
app.processEvents()
_n1 = len(mod.nodes)
chk(_n1 == _n0 + 1, "拖入后画布节点 %d → %d (+1)" % (_n0, _n1))
_last = mod.nodes[-1] if mod.nodes else {}
chk(_last.get("name") == _pay.get("name"), "新节点名字 = 库条目名 (%s)" % _last.get("name"))
# 落点 = 我点的地方: 节点左上角必须 = mapToScene(落点) - (120,42)  (与 dropEvent 同一套映射, 1px 内)
_exp = cv.mapToScene(_p1.toPoint())
chk(abs(float(_last.get("x", 0)) - (_exp.x() - 120)) < 1
    and abs(float(_last.get("y", 0)) - (_exp.y() - 42)) < 1,
    "落点即位置 (落 %s → 节点 (%s,%s), 期望 (%.0f,%.0f))"
    % ((1234, 567), _last.get("x"), _last.get("y"), _exp.x() - 120, _exp.y() - 42))
chk(bool(_ev.isAccepted()), "dropEvent 已 accept")
# 换个落点再拖一次 → 位置必须跟着变 (证明确实按落点, 不是总落画布中心)
_p2 = QPointF(1734.0, 967.0)
_mime2 = _pick.drag_mime()
cv.dropEvent(QDropEvent(_p2, Qt.CopyAction, _mime2, Qt.LeftButton, Qt.NoModifier))
app.processEvents()
_last2 = mod.nodes[-1]
_d1 = abs(float(_last2.get("x", 0)) - float(_last.get("x", 0)))
_d2 = abs(float(_last2.get("y", 0)) - float(_last.get("y", 0)))
chk(_d1 + _d2 > 10, "换个落点 → 节点位置跟着变 (Δx=%.0f Δy=%.0f; 不是固定在画布中心)" % (_d1, _d2))
_mime_bad = QMimeData()
_mime_bad.setText("hello")
_c0 = len(mod.nodes)
cv.dropEvent(QDropEvent(QPointF(10.0, 10.0), Qt.CopyAction, _mime_bad, Qt.LeftButton, Qt.NoModifier))
chk(len(mod.nodes) == _c0, "非模块库拖拽 (纯文本) 不会建节点")

print("④ 同步是活的 (画布加节点 → 库跟)", flush=True)
NEWNAME = "🧪 同步判据节点"
chk(not any(it.get("name") == NEWNAME for _t, _gn, its in SM.LIBRARY for it in its),
    "%s 此刻还不在库条目定义里" % NEWNAME)
_n_before = len(mod.nodes)
mod.add_node("model", NEWNAME, 900, 900, {"desc": "判据临时节点"})
app.processEvents()
chk(len(mod.nodes) == _n_before + 1, "画布已加节点 (%d)" % len(mod.nodes))
_grp_before = [g for _t, g, its in SM.LIBRARY if any(it.get("name") == NEWNAME for it in its)]
chk(not _grp_before, "还没刷新时库里没有它 (证明下面这条是真由同步带来的)")
mod.refresh_library(force=True)
app.processEvents()
_grp = [g for _t, g, its in SM.LIBRARY if any(it.get("name") == NEWNAME for it in its)]
_sig = [it.get("name") for _t, _gn, its in SM.LIBRARY for it in its]
chk(NEWNAME in _sig, "refresh_library 后库里出现 %s (库共 %d 条)" % (NEWNAME, len(_sig)))
chk(any("状态空间" in g for g in _grp), "它落在状态空间那一组: %s" % _grp)
# 复原画布 (别把手上的画布留脏)
mod.nodes = [n for n in mod.nodes if n.get("name") != NEWNAME]
mod.refresh_library(force=True)
app.processEvents()

print("⑤ 删除: 库条目可移除, 画布不受影响 (curation 名单, 可还原)", flush=True)
_cur_path = SM._library_curation_path()
_bak = open(_cur_path, encoding="utf-8").read() if os.path.exists(_cur_path) else None
try:
    # 用一条独立的临时条目测 (不碰真名单里的 33 条)
    _gname = "🧪 判据临时组"
    SM.LIBRARY.append(("model", _gname, [{"name": "🧪 临时条目", "type": "model", "params": {}}]))
    mod.library._rebuild()
    app.processEvents()
    _has = any(it.get("name") == "🧪 临时条目" for _t, _gn, its in SM.LIBRARY for it in its)
    chk(_has, "临时条目已在库")
    _cv_n = len(mod.nodes)
    mod.library._remove_entry(_gname, {"name": "🧪 临时条目"})
    app.processEvents()
    _has2 = any(it.get("name") == "🧪 临时条目" for _t, _gn, its in SM.LIBRARY for it in its)
    chk(not _has2, "移除后库里没有临时条目了")
    _cur = json.loads(open(_cur_path, encoding="utf-8").read())
    chk(any(x.get("name") == "🧪 临时条目" for x in (_cur.get("removed") or [])),
        "curation 名单已记 (%d 条)" % len(_cur.get("removed") or []))
    chk(len(mod.nodes) == _cv_n, "画布节点数不变 (%d)" % len(mod.nodes))
finally:
    if _bak is None:
        os.path.exists(_cur_path) and os.remove(_cur_path)
    else:
        open(_cur_path, "w", encoding="utf-8").write(_bak)
    SM._rebuild_library_globals()

print("⑥ 可以保存为新的工程文件 (替你点文件框 → 真落盘)", flush=True)
_tmp = os.path.join(ROOT, ".hermes_lib_sync_test_%s.json" % os.getpid())
# export_flow 里是真 QFileDialog(...)+dlg.exec_() → 离屏会卡住, 所以把「对话框」这一层替身掉:
#   exec_ 立刻返回 Accepted, selectedFiles 返回我们的临时路径 (保存逻辑本身一字不改, 真跑)
_o_exec, _o_sel = QFileDialog.exec_, QFileDialog.selectedFiles
QFileDialog.exec_ = lambda self: QFileDialog.Accepted
QFileDialog.selectedFiles = lambda self: [_tmp]
try:
    mod.export_flow()
finally:
    QFileDialog.exec_, QFileDialog.selectedFiles = _o_exec, _o_sel
app.processEvents()
_ok = os.path.exists(_tmp)
chk(_ok, "画出新工程文件: %s" % os.path.basename(_tmp))
if _ok:
    _d = json.loads(open(_tmp, encoding="utf-8").read())
    chk(len(_d.get("nodes") or []) == len(mod.nodes),
        "新文件节点数 = 画布节点数 (%d)" % len(_d.get("nodes") or []))
    os.remove(_tmp)

print("⑦ 没有联系/没有关联的都删掉", flush=True)
_cur = json.loads(open(_cur_path, encoding="utf-8").read()) if os.path.exists(_cur_path) else {}
rm = _cur.get("removed") or []
chk(len(rm) > 0, "删除名单在册 %d 条 (config/library_curation.json)" % len(rm))
chk(not any("🧪" in (x.get("name") or "") for x in rm), "判据用的临时条目已从真名单还原")

_tail = ("✅ 全部通过 — 模块库↔画布 同步/拖入/删除/存为新工程 (7 项)"
         if not FAIL else "❌ 失败 %d 项" % len(FAIL))
print(("✅ verify_library_sync 全绿 (0 失败)" if not FAIL else
       "❌ verify_library_sync 失败 %d 项: %s" % (len(FAIL), FAIL[:6])), flush=True)
print(_tail, flush=True)
sys.stdout.flush()
os._exit(1 if FAIL else 0)
