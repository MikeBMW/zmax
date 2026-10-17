# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/engine/ss3d_live.py (3D 实时联动)。import 本名仍拿到真身同一对象。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "src"), _ROOT, os.path.join(_ROOT, "tools", "gen")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lerobot.engine.ss3d_live as _mod                                                 # noqa: E402

sys.modules[__name__] = _mod
