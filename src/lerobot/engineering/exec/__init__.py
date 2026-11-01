# -*- coding: utf-8 -*-
"""执行层 — 真机动作契约 (contract) 与常驻执行器 (daemon)。

位置约定 (2026-11-01 老倪「l2_daemon 不能脱离状态空间工程」):
  · 契约 contract.py: 段表 schema / 闸序 / 回执字段 —— 随工程走, 进 git
  · 进程 daemon.py:   常驻 FIFO 执行器 —— 代码随工程, 生命周期仍由 systemd 管
  · tools/l2_daemon.py 只是薄启动壳, 不写逻辑
"""
from . import contract  # noqa: F401

__all__ = ["contract"]
