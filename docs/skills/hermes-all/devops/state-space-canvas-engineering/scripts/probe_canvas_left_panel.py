# -*- coding: utf-8 -*-
"""画布左侧模块库栏「默认开/合」离屏判据 (真建 SimulinkModule, 不靠源码阅读)。

用法:
    cd <repo> && QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python \
        <skill>/scripts/probe_canvas_left_panel.py [repo_path]

判据:
  ① 默认态与 `SimulinkModule.__init__` 里 set_collapsed(<bool>) 一致 (宽度/可见性同口径)
  ② 收起态 = 20px + ▶ 可见 + 列表隐藏, 且 _lib_btns 没被清空 (撤显示不删对象)
  ③ 展开 -> 560px + 列表可见 + ▶ 隐藏; 再收起 -> 回 20px (可逆)
退出码非 0 = 有问题。
"""
import os
import sys

repo = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/zmax")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(repo, "tools", "gui"))

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
import simulink_module as SM  # noqa: E402

m = SM.SimulinkModule()
m.resize(1400, 800)
m.show()
app.processEvents()
lib = m.library

fails = []


def chk(name, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + name + ("  " + detail if detail else ""))
    if not ok:
        fails.append(name)


collapsed = getattr(lib, "_collapsed", None)
chk("默认态有 _collapsed 标记", collapsed is not None, repr(collapsed))
chk("默认收起=20px", lib.width() == lib.LIB_W_COLLAPSED, "width=%d" % lib.width())
chk("▶ 展开按钮可见", lib._btn_expand.isVisibleTo(lib))
chk("模块列表隐藏", not lib.scroll.isVisibleTo(lib))
chk("模块按钮未被删除", len(getattr(lib, "_lib_btns", {})) > 0,
    "n=%d" % len(getattr(lib, "_lib_btns", {})))

m._expand_library()
app.processEvents()
chk("展开回 560px", lib.width() == lib.LIB_W, "width=%d" % lib.width())
chk("展开后列表可见", lib.scroll.isVisibleTo(lib))
chk("展开后 ▶ 隐藏", not lib._btn_expand.isVisibleTo(lib))

m._collapse_library()
app.processEvents()
chk("再收起回 20px", lib.width() == lib.LIB_W_COLLAPSED, "width=%d" % lib.width())
chk("再收起列表隐藏", not lib.scroll.isVisibleTo(lib))

print("\n结果: %s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
sys.exit(0 if not fails else 2)
