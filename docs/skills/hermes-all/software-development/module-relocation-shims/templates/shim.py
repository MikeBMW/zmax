"""<mod> — 真身已归位到 src/<pkg>/<域>/<mod>.py。

本文件只为老 import 保名: `sys.modules[__name__] = <真身模块>`, 调用点一行不改。
复制成 <dir>/<mod>.py 后改写两处: 模块真名、目标包路径。
硬性要求: 本文件 ≤40 行; `from __future__` 若原文件有, 必须仍是第一行。
"""
from __future__ import annotations

import importlib
import os
import sys

_TARGET = "<pkg>.<域>.<mod>"          # 真身模块真名, 例: lerobot.engine.runtime


def _candidates():
    """候选 import 根: 冻结包用 _MEIPASS, 源码树按目录标记上溯(不按层数)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    roots = []
    if hasattr(sys, "_MEIPASS"):                      # PyInstaller 冻结包
        roots.append(os.path.join(sys._MEIPASS, "src"))
    d = here
    while d and d != os.path.dirname(d):
        roots.append(os.path.join(d, "src"))
        roots.append(d)
        d = os.path.dirname(d)
    return roots


for _b in _candidates():
    if os.path.isdir(os.path.join(_b, "<pkg>")) and _b not in sys.path:
        sys.path.insert(0, _b)

sys.modules[__name__] = importlib.import_module(_TARGET)
