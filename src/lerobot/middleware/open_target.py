# -*- coding: utf-8 -*-
"""右键「打开工程」的落点解析 —— 先进入这个节点的**中间件模块**。

规则 (2026-10-17 老倪: 「右键打开工程, 要先进入这个对应的 node 代码, 能看到输入输出」):
    ① 中间件节点模块  src/lerobot/middleware/nodes/<n_id>.py   ← 先到这里 (端口/连线/compute 都在)
    ② 真实现源码      spec.source (+ source_symbol 现搜行号)    ← 再到这里
返回 (path, line, kind)；找不到就给 (None, None, "")。
"""
from __future__ import annotations

import os

from . import spec as spec_mod


def _nodes_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes")


def node_module_path(spec):
    return os.path.join(_nodes_dir(), "%s.py" % spec.module_name)


def _line_of(path, token):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for i, ln in enumerate(f, 1):
                if ln.lstrip().startswith(token):
                    return i
    except Exception:                                                    # noqa: BLE001
        pass
    return 1


def resolve_open_target(node=None, specs=None, root=None):
    """→ {"path","line","kind","impl_path","impl_line"}

    node: 画布节点 dict (GUI 右键传进来的那个) 或 NodeSpec 或节点名/ID 字符串。
    """
    spec = None
    if isinstance(node, spec_mod.NodeSpec):
        spec = node
    elif isinstance(node, dict):
        candidates = specs if specs is not None else spec_mod.parse_canvas()[0]
        spec = spec_mod.spec_by_name_or_id(candidates, node.get("id") or node.get("name") or "")
    elif isinstance(node, str):
        candidates = specs if specs is not None else spec_mod.parse_canvas()[0]
        spec = spec_mod.spec_by_name_or_id(candidates, node)
    if spec is None:
        return {"path": None, "line": None, "kind": "", "impl_path": None, "impl_line": None}

    mpath = node_module_path(spec)
    if not os.path.isfile(mpath):
        try:                                    # 生成物缺失 ⇒ 现场补 (与 loader 同一个生成器)
            from .loader import ensure_node_modules                 # noqa: PLC0415
            ensure_node_modules([spec], quiet=True)
        except Exception:                                           # noqa: BLE001
            pass
    root = root or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", ".."))
    impl_path, impl_line = None, None
    if spec.source:
        p = spec.source if os.path.isabs(spec.source) else os.path.join(root, spec.source)
        if os.path.isfile(p):
            impl_path = os.path.abspath(p)
            impl_line = None
            if spec.source_symbol:
                impl_line = _line_of(impl_path, spec.source_symbol)
    if os.path.isfile(mpath):
        return {"path": mpath, "line": _line_of(mpath, "PORTS_IN"), "kind": "middleware-node",
                "impl_path": impl_path, "impl_line": impl_line}
    return {"path": impl_path, "line": impl_line or 1,
            "kind": "impl-only (节点模块缺失)", "impl_path": impl_path, "impl_line": impl_line}
