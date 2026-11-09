# -*- coding: utf-8 -*-
"""ss_dyn_gate — 节点实现正文 (文件名 = 画布节点: ss_dyn_gate)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_constraint_gate   ·   registry key: ss_dyn_gate
"""

def node_ss_constraint_gate(ctx):
    """⚖ 动力学约束闸 (前置运动学约束真跑) — 薄壳: 真实现 nodes/constraint_gates_impl.py::run"""
    from .constraint_gates_impl import run as _run
    return _run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_constraint_gate
