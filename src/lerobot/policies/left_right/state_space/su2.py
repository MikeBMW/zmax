# -*- coding: utf-8 -*-
"""兼容壳 (2026-11-24 归位): 真身 = lerobot.manifold.core.su2"""
import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("lerobot.manifold.core.su2")
