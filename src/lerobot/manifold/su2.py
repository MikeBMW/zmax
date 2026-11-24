# -*- coding: utf-8 -*-
"""[兼容壳 · 2026-11-24] 真身: src/lerobot/manifold/core/su2.py"""
import sys as _sys

from lerobot.manifold.core.su2 import *          # noqa: F401,F403
import lerobot.manifold.core.su2 as _real

_sys.modules[__name__] = _real
