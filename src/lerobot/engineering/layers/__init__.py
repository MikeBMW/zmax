# -*- coding: utf-8 -*-
"""L1~L5 分层设计 (engineering 的骨架)。

- by_level.py  生成物: 档位 → (画布节点 id, 名称, 逻辑 key, 实现文件, 函数)
- 本包只回答"哪一层有哪些节点、各档位必须还能干什么", 不含节点实现。

节点实现不在这里 (在 src/lerobot/middleware/nodes/impl/), 这是刻意的:
    engineering = 分层与编排的**设计**
    middleware  = 节点 (契约 + 实现)
"""
from .by_level import LEVELS_INDEX, keys_of, funcs_of, summary  # noqa: F401

__all__ = ["LEVELS_INDEX", "keys_of", "funcs_of", "summary"]
