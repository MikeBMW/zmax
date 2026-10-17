# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/ops/docs_sync.py (文档/版本同步)

`import docs_sync` / `from docs_sync import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from lerobot.ops.docs_sync import ...`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.ops import docs_sync as _mod                                  # noqa: E402

sys.modules[__name__] = _mod
