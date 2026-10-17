# -*- coding: utf-8 -*-
"""工程加载器 —— 读状态空间 JSON (节点+连线) ⇒ 组装成可运行的完整工程。

    from lerobot.middleware import load_project
    prj = load_project()                  # 默认读画布真源 flows/state_space_obs.json
    prj.step()                            # 一拍: 每个 node 从总线取数 → 计算 → 发回总线

排序口径 (状态空间本来就是**带闭环**的, 不能当纯 DAG 排):
    ① Tarjan 求强连通分量 (SCC) —— 画布上的 L2→L3→L4 回灌就是一个大 SCC
    ② 分量之间做拓扑序 (无环, 一定排得干净)
    ③ 分量内部按 (y, x) 排, 一个 step 内单趟通过 —— 环里的值靠总線在**下一拍**闭合
      (这才是真闭环语义: 反馈量延迟一拍生效, 与 DDS 上分布式运行完全一致)
meta 如实给出 cycles(每个环的成员) 与 feedback(环内/回边) 供界面显示。
"""
from __future__ import annotations

import os

from . import bus as bus_mod
from . import spec as spec_mod
from .node import Node


def _sccs(ids, adj):
    """Tarjan 强连通分量 (迭代实现, 避免递归深度)。"""
    index, low, onstack, stack, comps = {}, {}, set(), [], []
    counter = [0]
    for root in ids:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                onstack.add(v)
            recurse = False
            nbrs = adj.get(v, [])
            for i in range(pi, len(nbrs)):
                w = nbrs[i]
                if w not in index:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    recurse = True
                    break
                if w in onstack:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            work.pop()
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                comps.append(comp)
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    return comps


def topo_order(specs, links):
    """→ (order:list[id], feedback:list[link], cycles:list[list[id]])"""
    ids = [s.id for s in specs]
    pos = {s.id: (s.y, s.x) for s in specs}
    adj = {i: [] for i in ids}
    for l in links:
        if l["f"] in adj:
            adj[l["f"]].append(l["t"])
    comps = _sccs(ids, adj)
    comp_of = {n: ci for ci, c in enumerate(comps) for n in c}
    cadj = {ci: set() for ci in range(len(comps))}
    cindeg = {ci: 0 for ci in range(len(comps))}
    for l in links:
        a, b = comp_of.get(l["f"]), comp_of.get(l["t"])
        if a is None or b is None or a == b:
            continue
        if b not in cadj[a]:
            cadj[a].add(b)
            cindeg[b] += 1
    q = sorted([ci for ci in range(len(comps)) if cindeg[ci] == 0],
               key=lambda ci: min(pos.get(n, (0, 0)) for n in comps[ci]))
    corder = []
    while q:
        cur = q.pop(0)
        corder.append(cur)
        for nx in sorted(cadj[cur]):
            cindeg[nx] -= 1
            if cindeg[nx] == 0:
                q.append(nx)
    corder += [ci for ci in range(len(comps)) if ci not in corder]       # 兜底, 正常走不到
    order = []
    for ci in corder:
        order.extend(sorted(comps[ci], key=lambda n: pos.get(n, (0, 0))))
    cycles = [sorted(c, key=lambda n: pos.get(n, (0, 0))) for c in comps if len(c) > 1]
    rank = {n: i for i, n in enumerate(order)}
    feedback = [l for l in links
                if l["f"] in rank and l["t"] in rank
                and (comp_of[l["f"]] == comp_of[l["t"]] or rank[l["f"]] > rank[l["t"]])]
    return order, feedback, cycles


def ensure_node_modules(specs, quiet=True, links=None):
    """生成物自愈: nodes/ 里缺哪个节点的模块就补出来 (内容由生成器统一负责)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    nodes_dir = os.path.join(here, "nodes")
    missing = [s for s in specs
               if not os.path.isfile(os.path.join(nodes_dir, "%s.py" % s.module_name))]
    if not missing:
        return []
    try:
        import sys
        root = os.path.abspath(os.path.join(here, "..", "..", ".."))
        if os.path.join(root, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(root, "tools"))
        import gen_middleware_nodes as gen                              # noqa: PLC0415
        gen.generate(specs, links=links, quiet=quiet)
        if not quiet:
            print("🧩 已补生成 %d 个节点模块 (先前缺失)" % len(missing))
    except Exception as e:                                              # noqa: BLE001
        if not quiet:
            print("⚠️ 节点模块缺失且补生成失败: %s" % e)
    return [s.id for s in missing]


def load_project(canvas=None, product=None, bus=None, ns="default",
                 ensure_modules=True, quiet=True):
    """读工程 JSON → Project。bus 不给就按产品档自建 (550B=DDS)。"""
    specs, links, meta = spec_mod.parse_canvas(canvas)
    if ensure_modules:
        ensure_node_modules(specs, quiet=quiet, links=links)
    if bus is None:
        bus, binfo = bus_mod.make_bus(product=product, ns=ns)
    else:
        binfo = {"backend": getattr(bus, "backend", "?"), "enabled": False,
                 "why": "外部注入总线", "note": getattr(bus, "note", "")}
    nodes = {}
    for s in specs:
        nodes[s.id] = Node(s, bus)
    for l in links:                       # 工程连线 = 总线路由表 (输出口 → 下游输入口)
        src = nodes.get(l["f"])
        if src is not None:
            src.dst_map.setdefault(l["f_port"], []).append((l["t"], l["t_port"]))
    order, feedback, cycles = topo_order(specs, links)
    meta = dict(meta)
    meta["cycles"] = cycles
    meta["feedback_links"] = len(feedback)
    from .project import Project                                   # noqa: PLC0415 (避免环导入)
    return Project(nodes=nodes, links=links, order=order, bus=bus, bus_info=binfo,
                   meta=meta, feedback=feedback, cycles=cycles)
