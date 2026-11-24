# -*- coding: utf-8 -*-
"""[兼容壳 · 2026-11-24] 真身: src/lerobot/manifold/core/pose_caliper.py"""
import sys as _sys

from lerobot.manifold.core.pose_caliper import *          # noqa: F401,F403
import lerobot.manifold.core.pose_caliper as _real

_sys.modules[__name__] = _real
