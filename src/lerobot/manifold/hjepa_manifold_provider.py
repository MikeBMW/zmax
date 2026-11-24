# -*- coding: utf-8 -*-
"""兼容壳 (2026-11-24 分层归位): 真身 = lerobot.manifold.engine.hjepa_manifold_provider。

老 import 一行不改; 判据: import 后 realpath(__file__) == 真身, 且 is 真身模块。
"""
import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("lerobot.manifold.engine.hjepa_manifold_provider")
