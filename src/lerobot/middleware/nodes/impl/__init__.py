# -*- coding: utf-8 -*-
"""节点实现 (取数 → 调算法 → 打标)。

老倪 2026-11-10 定的分层:
    算法  src/lerobot/policies/           纯计算
    节点  src/lerobot/middleware/nodes/   契约(n_xxx.py) + 实现(impl/<node_key>.py)
    分层  src/lerobot/engineering/layers/  L1~L5 各自有哪些节点
engineering 里**不再有 nodes 目录** —— node 是中间件的事, engineering 只做分层与编排。

shared_runtime.py = 所有节点共用的运行时 (状态、缓存、取帧/打标辅助), 不是某一层的逻辑。
"""
