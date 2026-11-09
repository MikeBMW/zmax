# -*- coding: utf-8 -*-
"""n_geoplan — 节点实现正文 (文件名 = 画布节点: n_geoplan)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_geoplan   ·   registry key: n_geoplan
"""

def node_geoplan(ctx):
    """🧭 测地线块规划 — 薄壳: 真实现 nodes/geo_plan_impl.py::run

    obs43 → ManifoldEngine.project → 目标点 → compute_geodesic(H) → readout 解码 → 块[H,4]。
    只出块, 不下发; 引擎/权重/目标缺失一律 ok=False 如实上报 (不出空块冒充)。
    """
    from .geo_plan_impl import run as _geo_run
    return _geo_run(ctx)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_geoplan
