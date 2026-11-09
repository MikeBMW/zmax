# -*- coding: utf-8 -*-
"""n_exec — 节点实现正文 (文件名 = 画布节点: n_exec)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_exec   ·   registry key: n_exec
"""

def node_exec(ctx):
    """⚙️ 动作执行器 (l2_daemon) — 真执行函数: 读执行器真值状态与最近事件 (本节点**不下发**任何动作)。 —— 薄壳: 真实现已迁到 nodes/exec_dispatch_impl.py::run (2026-10-28 执行链外迁)"""
    from .exec_dispatch_impl import run as _run
    return _run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_exec
