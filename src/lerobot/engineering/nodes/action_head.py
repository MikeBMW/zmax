# -*- coding: utf-8 -*-
"""action_head — 节点实现正文 (文件名 = 画布节点: action_head)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_action_head   ·   registry key: action_head
"""

def node_action_head(ctx):
    """🎯 Flow-Matching Action Head (DiT) — L3 加权修正 —— 薄壳: 真实现 nodes/flow_matching_impl.py::run

    老倪 2026-10-29: L2 是基础输出, L3 是加权修正。
    动作来自真数据 chunk_latest.chunk[0]; 修正量 Δ=chunk−ff; DiT/StateSpaceActionHead 前向只作结构自检
    (无训练权重, 不冒充推理); 产出 out1(名义动作) / out2(L3 力 → 万有引力 in3)。
    """
    from .flow_matching_impl import run as _run
    return _run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_action_head
