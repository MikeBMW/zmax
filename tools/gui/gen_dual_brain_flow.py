# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: tools/gen/dual_brain_flow.py (生成双脑流程)。import 本名仍拿到真身同一对象。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "src"), _ROOT, os.path.join(_ROOT, "tools", "gen")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dual_brain_flow as _mod                                                 # noqa: E402

sys.modules[__name__] = _mod
