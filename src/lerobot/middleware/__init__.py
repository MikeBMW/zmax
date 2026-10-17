# -*- coding: utf-8 -*-
"""Z-MAX 中间件 (middleware): 状态空间 = 一条数据总线 + 每个节点一个模块。

对外三个入口:
    load_project()  读状态空间工程 JSON (节点+连线) → Project (完整工程)
    Project.step()  一拍: 每个 node 从总线取输入 → compute → 结果发回总线
    make_bus()      按产品档建总线: 550B=**DDS**(标定版), 550A/550C=共享内存总线

分层:
    bus.py       数据总线 (DDS / 共享内存 / 进程内)
    spec.py      工程 JSON → 节点规格 (端口由连线推出)
    node.py      节点基类 (取数→计算→发数, 端口校验)
    loader.py    组装完整工程 (拓扑序 + 反馈边识别 + 模块自愈)
    project.py   运行时 (step / inject / manifest / io_table)
    nodes/       每个节点一个模块 (生成物, 打开就能看到输入输出)
"""
from .bus import bus_enabled, make_bus, topic, TOPIC_PREFIX          # noqa: F401
from .spec import parse_canvas, find_canvas, NodeSpec, spec_by_name_or_id  # noqa: F401
from .node import Node                                               # noqa: F401
from .loader import load_project, topo_order, ensure_node_modules    # noqa: F401
from .project import Project                                         # noqa: F401
from .open_target import resolve_open_target                          # noqa: F401

__all__ = [
    "load_project", "make_bus", "bus_enabled", "topic", "TOPIC_PREFIX",
    "parse_canvas", "find_canvas", "NodeSpec", "spec_by_name_or_id",
    "Node", "Project", "topo_order", "ensure_node_modules", "resolve_open_target",
]
