# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/ops/platform_info.py (平台信息/能力清单)

`import zmax_platform_info` / `from zmax_platform_info import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from lerobot.ops.platform_info import ...`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.ops import platform_info as _mod                                  # noqa: E402

sys.modules[__name__] = _mod
