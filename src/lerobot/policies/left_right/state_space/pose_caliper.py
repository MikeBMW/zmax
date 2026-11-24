# -*- coding: utf-8 -*-
"""兼容壳 (2026-11-24 分层归位): 真身 = lerobot.manifold.core.pose_caliper

纯 numpy 四元数工具, 属几何核 ⇒ 从 policies/left_right/state_space/ 迁到 core/。
老 `import pose_caliper`(tools/ 与 policies 侧) 一行不改。
"""
import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("lerobot.manifold.core.pose_caliper")
