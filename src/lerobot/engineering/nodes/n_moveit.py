# -*- coding: utf-8 -*-
"""n_moveit — 节点实现正文 (文件名 = 画布节点: n_moveit)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_moveit   ·   registry key: n_moveit
"""

def node_moveit(ctx):
    """🧭 运动规划 (plan) 节点 —— 薄壳: 真实现已迁到 nodes/plan_impl.py::run

    老倪 2026-10-28: 「运动规划节点的源代码怎么能是 library.py 呢？应该是 plan 的代码」
      ⇒ 规划正文(段表生成)搬到 src/lerobot/engineering/nodes/plan_impl.py, 这里只转调,
        右键「打开源代码」经 _EXTERNAL_LOC 直接落到 plan_impl.py:def run。
    """
    from .plan_impl import run as _plan_run
    return _plan_run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_moveit
