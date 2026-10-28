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
    _n_params = {}
    if isinstance(node, dict):
        _n_params = node.get("params") or {}
    if isinstance(node, spec_mod.NodeSpec):
        spec = node
    elif isinstance(node, dict):
        candidates = specs if specs is not None else spec_mod.parse_canvas()[0]
        spec = spec_mod.spec_by_name_or_id(candidates, node.get("id") or node.get("name") or "")
        if spec is None and node.get("name"):
            spec = spec_mod.spec_by_name_or_id(candidates, node.get("name") or "")
    elif isinstance(node, str):
        candidates = specs if specs is not None else spec_mod.parse_canvas()[0]
        spec = spec_mod.spec_by_name_or_id(candidates, node)

    root = root or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                "..", "..", ".."))

    def _impl_from_dict():
        """🔴 2026-10-28 老倪「plan 节点还是打不开 VSCode 的源代码」:

        GUI 里右键的那个节点 dict **自带** params.source / params.source_symbol
        (画布上就有), 但它的 id 是 GUI 现场生成的 (n1793...acw), 而 resolve 去
        parse_canvas() 读的是盘上的画布 —— 两边的 id 不一定一致 ⇒ 查不到 spec 就弹
        "未配置源码映射"。**节点自己声明的 source 最高优先**, 先认它。
        """
        _s = str(_n_params.get("source") or "")
        if not _s:
            return None, None
        _p = _s if os.path.isabs(_s) else os.path.join(root, _s)
        if not os.path.isfile(_p):
            return None, None
        _y = str(_n_params.get("source_symbol") or "")
        return os.path.abspath(_p), (_line_of(_p, _y) if _y else None)

    if spec is None:
        _ip, _il = _impl_from_dict()
        if _ip:
            return {"path": _ip, "line": _il or 1, "kind": "impl-only (节点自带 source)",
                    "impl_path": _ip, "impl_line": _il}
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
    _ip0, _il0 = _impl_from_dict()          # 节点自带的 params.source 优先 (GUI 现场节点带它)
    if _ip0:
        impl_path, impl_line = _ip0, _il0
    elif spec.source:
        p = spec.source if os.path.isabs(spec.source) else os.path.join(root, spec.source)
        if os.path.isfile(p):
            impl_path = os.path.abspath(p)
            impl_line = None
            if spec.source_symbol:
                impl_line = _line_of(impl_path, spec.source_symbol)
    if not impl_path and getattr(spec, "impl_key", ""):
        # 🔴 2026-10-28 老倪「plan 节点右键打不开源代码」第二层兜底:
        #   画布 params 没写 source、中间件模块也没声明 SOURCE 时, 用注册表里登记的
        #   实现函数真实位置 (registry 的 file/line) —— 所有有 impl_key 的节点都能打开真源码。
        try:
            from lerobot.engineering import registry as _reg2               # noqa: PLC0415
            _info = _reg2.get(spec.impl_key) or {}
            _f = _info.get("file") or ""
            if _f and os.path.isfile(_f):
                impl_path = os.path.abspath(_f)
                impl_line = int(_info.get("line") or 0) or None
        except Exception:                                                   # noqa: BLE001
            pass
    if os.path.isfile(mpath):
        return {"path": mpath, "line": _line_of(mpath, "PORTS_IN"), "kind": "middleware-node",
                "impl_path": impl_path, "impl_line": impl_line}
    return {"path": impl_path, "line": impl_line or 1,
            "kind": "impl-only (节点模块缺失)", "impl_path": impl_path, "impl_line": impl_line}
