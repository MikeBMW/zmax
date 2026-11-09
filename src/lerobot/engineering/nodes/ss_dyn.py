# -*- coding: utf-8 -*-
"""ss_dyn — 节点实现正文 (文件名 = 画布节点: ss_dyn)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_dyn   ·   registry key: ss_dyn
"""

def node_ss_dyn(ctx):
    """动力学预测-校正 — 📈先验动力学预测器(PriorDynamicsPredictor) / 🧪状态校正器(state_correction) —— 薄壳: 真实现已迁到 nodes/state_correct_impl.py::run (2026-10-28 执行链外迁)"""
    from .state_correct_impl import run as _run
    return _run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_dyn
