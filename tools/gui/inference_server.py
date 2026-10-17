# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/serving/server.py (本地推理服务 (L4/策略 HTTP))

`import inference_server` / `from inference_server import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from lerobot.serving.server import ...`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.serving import server as _mod                                  # noqa: E402

sys.modules[__name__] = _mod
