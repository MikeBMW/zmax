# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/middleware/link_bus.py (DDS 链路总线)

`import dds_link_bus` / `from dds_link_bus import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from lerobot.middleware.link_bus import ...`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.middleware import link_bus as _mod                                  # noqa: E402

sys.modules[__name__] = _mod
