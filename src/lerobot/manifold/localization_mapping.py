# -*- coding: utf-8 -*-
"""[兼容壳 · 2026-11-24 分层归位] 真身已移到 src/lerobot/app/workcell/localization_mapping.py

只做 sys.modules 别名 (同一模块对象, isinstance/模块级全局不分裂), 不要再往这里加逻辑。
"""
import sys as _sys

from lerobot.app.workcell.localization_mapping import *          # noqa: F401,F403
import lerobot.app.workcell.localization_mapping as _real

_sys.modules[__name__] = _real
