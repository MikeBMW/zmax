#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中间件工程 CLI —— 不打开控制台也能加载/跑一拍/看输入输出。

    ./gui-venv311/bin/python tools/mw_project.py load            # 加载工程, 打印统计 + 输入输出表
    ./gui-venv311/bin/python tools/mw_project.py step            # 跑一拍 (每个节点 取数→计算→发数)
    ./gui-venv311/bin/python tools/mw_project.py bus             # 只看总线档位门控 (550B=DDS)
    ./gui-venv311/bin/python tools/mw_project.py inject <node> <port> <json值>
    ./gui-venv311/bin/python tools/mw_project.py node <节点id|名字>   # 一个节点的输入输出+模块文件
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lerobot.middleware import (bus_enabled, load_project, make_bus,   # noqa: E402
                                parse_canvas, resolve_open_target)


def _load(product=None, ns="cli"):
    prj = load_project(product=product, ns=ns)
    return prj


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "load"
    product = os.environ.get("ZMAX_PRODUCT") or None
    if cmd == "bus":
        ok, why = bus_enabled(product)
        b, info = make_bus(product=product, ns="cli")
        print("DDS 启用:", ok, "|", why)
        print("实际后端:", info)
        b.close()
        return 0
    if cmd == "node":
        if len(argv) < 3:
            print("用法: mw_project.py node <节点id|名字片段>")
            return 2
        specs, links, meta = parse_canvas()
        prj = _load(product)
        for nid in prj.order:
            nd = prj.nodes[nid]
            if argv[2] in nd.spec.id or argv[2] in (nd.spec.name or ""):
                t = resolve_open_target(nd.spec, root=ROOT)
                print(json.dumps(nd.manifest(), ensure_ascii=False, indent=2))
                print("打开落点:", t.get("path"), ":", t.get("line"), "(", t.get("kind"), ")")
                print("真实现在:", t.get("impl_path"), ":", t.get("impl_line"))
                return 0
        print("没有匹配的节点:", argv[2])
        return 1
    prj = _load(product)
    st = prj.stats()
    if cmd == "load":
        print("工程:", prj.meta.get("canvas"))
        print("节点 %(nodes)d · 连线 %(links)d · 拓扑序 %(order)d · 反馈边 %(feedback)d · 模块就位 %(module_ok)d/%(nodes)d · 已绑定实现 %(impl_bound)d · 动作类节点 %(act_nodes)d" % st)
        print("总线: %s (enabled=%s) · %s" % (prj.bus_info.get("backend"), prj.bus_info.get("enabled"), prj.bus_info.get("note") or prj.bus_info.get("why")))
        if st["cycles"]:
            print("闭环 (按反馈边处理, 不阻断):", st["cycles"])
        print("-" * 100)
        print(prj.io_table())
        prj.close()
        return 0
    if cmd == "step":
        traces = prj.step()
        n_out = sum(len(t.get("out") or {}) for t in traces)
        n_sent = sum(sum(1 for v in (t.get("sent") or {}).values() if v) for t in traces)
        print("跑一拍: %d 个节点 · 输出 %d 个值 · 成功发到总线 %d 条 · 总线=%s"
              % (len(traces), n_out, n_sent, prj.bus_info.get("backend")))
        for t in traces[:5]:
            print("  %-11s in=%s → out=%s [%s]" % (t["id"], list(t["in"]), list(t["out"]), t.get("status")))
        prj.close()
        return 0
    if cmd == "inject":
        if len(argv) < 5:
            print("用法: mw_project.py inject <node> <port> <json值>")
            return 2
        val = json.loads(argv[4])
        prj.inject(argv[2], argv[3], val)
        traces = prj.step()
        print("注入 %s.%s=%r → 跑一拍 %d 节点" % (argv[2], argv[3], val, len(traces)))
        prj.close()
        return 0
    print("未知命令:", cmd)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
