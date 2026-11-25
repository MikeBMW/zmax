#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""昼夜双模世界模型 (Day-Night World Model) —— 状态空间的作息层。

白天: 在线推理, 面对噪声世界, 只落"噪声日志"(daylog)
夜间: 离线对齐, 用日志对齐高维先验, 过闸门后**原子**切换(consolidate)
相位唯一真源: zmax_data/daynight/state.json (phase.py)

对外只用这四个入口: phase.start_day / phase.start_night / consolidate.night_run / phase.guard_online
"""
from . import consolidate, daylog, phase  # noqa: F401

__all__ = ["phase", "daylog", "consolidate"]
