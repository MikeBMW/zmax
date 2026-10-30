# -*- coding: utf-8 -*-
"""完整工程 (加载后的运行时) —— 节点 + 连线 + 拓扑序 + 总线。

一次 step() = 按拓扑序把每个 node 跑一遍: 从总线取输入 → compute → 结果发回总线。
所以**下游拿到的永远是上游刚刚发到总线上的值** (不是内存里直接传参) —— 这样
换成 DDS 后端 (550B) 时, 节点可以分布在别的进程/机器上, 工程语义不变。
"""
from __future__ import annotations

import json
import os
import time


class Project:
    def __init__(self, nodes, links, order, bus, bus_info=None, meta=None,
                 feedback=None, cycles=None):
        self.nodes = dict(nodes)              # id → Node
        self.links = list(links)
        self.order = list(order)
        self.bus = bus
        self.bus_info = dict(bus_info or {})
        self.meta = dict(meta or {})
        self.feedback = list(feedback or [])
        self.cycles = list(cycles or [])
        self.n_steps = 0
        self.last_traces = []
        self.started_at = time.time()

    # ── 运行 ──────────────────────────────────────────────────────────
    def step(self, only=None):
        traces = []
        for nid in self.order:
            if only and nid not in only:
                continue
            nd = self.nodes.get(nid)
            if nd is None:
                continue
            try:
                _t0 = time.perf_counter()
                _tr = nd.step()
                if isinstance(_tr, dict):                      # 🧠 逐节点耗时 (回路预算取证用)
                    _tr["ms"] = round((time.perf_counter() - _t0) * 1000.0, 2)
                traces.append(_tr)
            except Exception as e:                                     # noqa: BLE001
                traces.append({"id": nid, "name": getattr(nd.spec, "name", nid),
                               "status": "step 异常(%s: %s)" % (type(e).__name__, e),
                               "in": {}, "out": {}, "sent": {}})
        self.n_steps += 1
        self.last_traces = traces
        # 🔎 2026-10-31 老倪「Call Stack 按画布顺序」: 调用栈只能反映真实调用 (本类是 for 循环逐个调,
        #   所以栈里一次只有一个节点)。这里把**本拍真实执行顺序**落盘, 调试时和 Call Stack 对照:
        #   帧名 = compute_<节点文件> → 看栈顶那一帧, 就知道在画布顺序的第几步。
        #   ZMAX_SS_CHAIN=1 才写 (默认不写盘)。
        if os.environ.get("ZMAX_SS_CHAIN") == "1":
            try:
                with open("/tmp/ss_chain.txt", "w", encoding="utf-8") as _f:
                    _f.write("tick=%d  %s\n" % (self.n_steps, time.strftime("%H:%M:%S")))
                    for _i, _t in enumerate(traces, 1):
                        _f.write("%2d  %-10s %-22s %7.2fms  %s\n"
                                 % (_i, _t.get("id"), _t.get("name"), _t.get("ms") or 0.0,
                                    _t.get("status")))
            except Exception:                                              # noqa: BLE001
                pass
        return traces

    def run(self, n=1, dt=0.0):
        out = []
        for _ in range(max(1, int(n))):
            out = self.step()
            if dt:
                time.sleep(dt)
        return out

    def inject(self, node_id, port, value):
        """从工程外向某个节点的输入口注值 (等价于上游节点发了一帧)。"""
        v = self.nodes.get(node_id)
        if v is None:
            raise KeyError("没有这个节点: %s" % node_id)
        if port not in v.spec.inputs:
            raise KeyError("节点 %s 没有输入口 %s (有: %s)" % (node_id, port, v.spec.inputs))
        return self.bus.publish(v.topic(port), value)

    # ── 视察 ──────────────────────────────────────────────────────────
    def manifest(self):
        return {
            "meta": self.meta, "bus": self.bus_info,
            "nodes": [self.nodes[i].manifest() for i in self.order if i in self.nodes],
            "links": self.links, "feedback": self.feedback, "cycles": self.cycles,
            "n_steps": self.n_steps,
        }

    def io_table(self):
        """输入输出一览 (给终端/面板显示, 一行一个节点)。"""
        lines = []
        for i in self.order:
            nd = self.nodes.get(i)
            if nd is None:
                continue
            s = nd.spec
            ins = ",".join(s.inputs) or "-"
            outs = ",".join(s.outputs) or "-"
            lines.append("%-9s %-26s %-7s → %-9s  实现=%-18s %s"
                         % (s.id, (s.name or "")[:26], ins, outs,
                            s.impl_key or "(未绑定)", s.exec_mode))
        return "\n".join(lines)

    def stats(self):
        st = {"nodes": len(self.nodes), "links": len(self.links),
              "order": len(self.order), "feedback": len(self.feedback),
              "cycles": self.cycles, "steps": self.n_steps,
              "bus": self.bus_info.get("backend"),
              "impl_bound": sum(1 for n in self.nodes.values() if n.spec.impl_key),
              "act_nodes": sum(1 for n in self.nodes.values() if n.spec.exec_mode == "act"),
              "module_ok": sum(1 for n in self.nodes.values() if n.module is not None)}
        return st

    def close(self):
        try:
            self.bus.close()
        except Exception:                                              # noqa: BLE001
            pass

    def __repr__(self):
        return "<Project %s nodes=%d links=%d bus=%s>" % (
            self.meta.get("canvas", "?"), len(self.nodes), len(self.links),
            self.bus_info.get("backend"))


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
