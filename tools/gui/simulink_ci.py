# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: src/lerobot/ops/flow_ci.py (工程流程 CI 校验)

`import simulink_ci` / `from simulink_ci import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from lerobot.ops.flow_ci import ...`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(os.path.dirname(_HERE)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.ops import flow_ci as _mod                                  # noqa: E402

sys.modules[__name__] = _mod
