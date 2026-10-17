# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/middleware/relay.py (ECS 中转消息通道)

`import relay_middleware` / `from relay_middleware import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from lerobot.middleware.relay import ...`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.middleware import relay as _mod                                  # noqa: E402

sys.modules[__name__] = _mod
