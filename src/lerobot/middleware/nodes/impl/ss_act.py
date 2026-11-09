# -*- coding: utf-8 -*-
"""ss_act — 节点实现正文 (文件名 = 画布节点: ss_act)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_exec   ·   registry key: ss_act
"""

def node_ss_exec(ctx):
    """执行层 — 🤖机器人执行器(RobotExecutor.execute) / 🌍物理世界(PhysicalWorld 质量/惯量) —— 薄壳: 真实现已迁到 nodes/robot_actuator_impl.py::run (2026-10-28 执行链外迁)"""
    from .robot_actuator_impl import run as _run
    return _run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_exec
