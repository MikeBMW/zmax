# -*- coding: utf-8 -*-
"""ss_limit — 节点实现正文 (文件名 = 画布节点: ss_limit)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_s3   ·   registry key: ss_limit
"""

def node_ss_s3(ctx):
    """认知决策层 — 🧭动作调制器(ActionModulator.decide 8阶段状态机) / 🛡安全执行边界(saturate) —— 薄壳: 真实现已迁到 nodes/safety_limit_impl.py::run (2026-10-28 执行链外迁)"""
    from .safety_limit_impl import run as _run
    return _run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_s3
