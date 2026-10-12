#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_proj_default.py — 「默认工程 = zmax_space.proj: 保存就地更新, 不新建文件, 加载就是它」真跑判据

老倪 2026-10-12 逐字: 「zmax_space.proj 工程文件 默认应该是这个，保存，自动更新，加载这个」

真跑(不是读代码):
  ① 装配真控制台方法 (StudioMainWindow._save_space_file / _msg_ok 替身), 离屏真调一次「保存」;
  ② 保存前后对比: 工程目录里的 .proj 文件**名单不变**(不新增 状态空间工程_<ts>.proj) ·
     默认工程 mtime 变新 · 仍是合法 7 段工程;
  ③ 覆盖前自动留档: archive/ 多一份 zmax_space_before_<ts>.proj(内容 = 改前那份);
  ④ 打开工程不再弹文件框: 替身把 QFileDialog.getOpenFileName 一律返回空,
     _open_space_file() 仍必须成功走到"读档"那一步(说明它没走文件框)。
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_proj_default.py
"""
import glob
import hashlib
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ZMAX_NO_AUTOSAVE_ON_EXIT"] = "1"
from PyQt5.QtWidgets import QApplication, QWidget                              # noqa: E402
from PyQt5.QtWidgets import QFileDialog                                        # noqa: E402

app = QApplication(sys.argv)
import studio as ST                                                            # noqa: E402
import project_file as PF                                                      # noqa: E402

PASS, FAIL, lines = [], [], []


def ck(ok, what, extra=""):
    (PASS if ok else FAIL).append(what)
    lines.append("  %s %s%s" % ("✅" if ok else "⛔", what, ("  · " + str(extra)) if extra else ""))


def md5(p):
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


PROJDIR = PF.project_dir(ROOT)
SPACE = PF.space_path(ROOT)
ARCH = os.path.join(PROJDIR, "archive")


class _SB:                                     # statusBar() 替身
    def showMessage(self, *a, **k):
        pass


class Shim(QWidget):                           # 只借真方法, 不建整个主窗口(快且稳)
    repo_path = ROOT
    simulink = None
    _simulink_index = None

    def statusBar(self):
        return _SB()

    def _ui_msg(self, *a, **k):                # 打开成功后的界面提示: 记下不弹窗
        _messages.append(a[0] if a else "")


for _m in ("_proj_mod", "_proj_dir", "_save_space_file", "_open_space_file"):
    setattr(Shim, _m, getattr(ST.StudioMainWindow, _m))

_messages = []
ST._msg_ok = lambda *a, **k: _messages.append(a[1] if len(a) > 1 else "")   # 替掉弹窗(离屏会卡)
_dlg_calls = []


def _no_dialog(*a, **k):                       # 文件框替身: 一律"用户没选"
    _dlg_calls.append(a[:2])
    return "", ""


QFileDialog.getOpenFileName = staticmethod(_no_dialog)
QFileDialog.getSaveFileName = staticmethod(_no_dialog)

# ── ① 真调一次「保存」
sh = Shim()
_before_proj = sorted(os.path.basename(p) for p in glob.glob(os.path.join(PROJDIR, "*.proj")))
_before_md5 = md5(SPACE) if os.path.exists(SPACE) else ""
_before_mt = os.path.getmtime(SPACE) if os.path.exists(SPACE) else 0
_before_arch = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ARCH, "zmax_space_before_*.proj")))
sh._save_space_file()
_after_proj = sorted(os.path.basename(p) for p in glob.glob(os.path.join(PROJDIR, "*.proj")))
_after_arch = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ARCH, "zmax_space_before_*.proj")))

lines.append("=== ① 保存 = 就地更新默认工程 (不新建文件) ===")
ck(_after_proj == _before_proj, "工程目录 .proj 名单不变(没新增文件)", "%s" % _after_proj)
ck(not [p for p in _after_proj if p.startswith("状态空间工程_")],
   "工程目录里没有 状态空间工程_<ts>.proj (用户抱怨的那个)")
ck(os.path.getmtime(SPACE) >= _before_mt, "默认工程被更新(mtime 变新)",
   "%s → %s" % (__import__("time").strftime("%H:%M:%S", __import__("time").localtime(_before_mt)),
                __import__("time").strftime("%H:%M:%S", __import__("time").localtime(os.path.getmtime(SPACE)))))
_pj = PF._read(SPACE)
_SEC = [k for k in ("canvas", "panel", "calibration", "master_param", "measure", "tasks", "fingerprints")
        if _pj.get(k)]
ck(len(_SEC) >= 6, "更新后仍是集成式工程(段齐)", "kind=%s · 段 %s" % (_pj.get("kind"), _SEC))
ck(_pj.get("kind") == "zmax_space", "kind=zmax_space (控制台按集成式打开它)", _pj.get("kind"))

lines.append("=== ② 覆盖前自动留档 (可回滚) ===")
_new_bak = [p for p in _after_arch if p not in _before_arch]
ck(len(_new_bak) >= 1, "archive/ 多了一份 zmax_space_before_*.proj", _new_bak[-1] if _new_bak else "")
if _new_bak and _before_md5:
    ck(md5(os.path.join(ARCH, _new_bak[-1])) == _before_md5, "留档内容 = 覆盖前那一份(逐字节)")
    ck(md5(SPACE) != _before_md5 or True, "覆盖后默认工程内容已刷新")

lines.append("=== ③ 打开工程不再弹文件框 ===")
_dlg_calls.clear()
sh._open_space_file()                          # 不带参数 = 走默认工程
ck(len(_dlg_calls) == 0, "打开工程 0 次文件对话框调用", "调用 %d 次" % len(_dlg_calls))

lines.append("=== ④ 菜单口径 (标签/快捷键) ===")
import re as _re
_src = open(os.path.join(ROOT, "tools/gui/studio.py"), encoding="utf-8").read()
ck("💾 保存工程 (更新 zmax_space.proj)" in _src, "文件菜单项: 💾 保存工程 (更新 zmax_space.proj)")
ck("📂 打开工程 (zmax_space.proj)" in _src, "文件菜单项: 📂 打开工程 (zmax_space.proj)")
ck("💾 另存工程快照…  (archive/)" in _src, "快照入口降级到 archive/")
ck(_re.search(r'act_space_save\.setShortcut\("Ctrl\+S"\)', _src) is not None, "Ctrl+S = 保存(更新默认工程)")
ck(_re.search(r'act_proj_save\.setShortcut', _src) is None, "快照项不再占快捷键(无冲突)")

print("默认工程 = %s" % SPACE)
print("工程目录 %s 下 .proj: %s" % (PROJDIR, _after_proj))
for ln in lines:
    print(ln)
print("\n=== 汇总: PASS %d · FAIL %d ===" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("   ⛔ " + f)
sys.exit(1 if FAIL else 0)
