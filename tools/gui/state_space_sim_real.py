# -*- coding: utf-8 -*-
"""兼容层 · 真身已迁走 (2026-10-17 归位)

老倪: 「RealStateSpaceSim 是 Z-MAX 的核心物理仿真主循环, 但是这么多核心代码，却在 gui 文件夹里，
       不合理啊」—— 同意。真身现在在:

    src/lerobot/engine/runtime.py      ← 4240 行, 零 PyQt 依赖, 只有 stdlib + numpy

本文件只剩一个**模块别名**: 任何 `import state_space_sim_real` / `from state_space_sim_real import X`
都会拿到同一个模块对象 (sys.modules 直接换掉), 因此:
  · 模块级全局 (SS_LIVE_FRAME / _SS_STATE / 环境开关) 与真身共享, 不会出现两份状态
  · isinstance / 类身份一致 (老代码 detach 判断不会失效)
新代码请直接 `from lerobot.engine.runtime import RealStateSpaceSim`。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))                    # tools/gui
_ROOT = os.path.dirname(os.path.dirname(_HERE))                       # 仓库根
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from lerobot.engine import runtime as _runtime                        # noqa: E402

# 🔑 关键: 用真身替换自身, 老代码拿到的就是真身 (属性读写共享)
sys.modules[__name__] = _runtime
