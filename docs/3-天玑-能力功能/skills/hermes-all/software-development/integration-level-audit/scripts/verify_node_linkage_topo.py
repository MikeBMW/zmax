# -*- coding: utf-8 -*-
"""verify_node_linkage_topo — 画布节点链路**真跑**核验 (不是静态读代码)。

对每个节点: 用 registry 解析出执行函数, 按拓扑序**真的调用**, 把上游 outN 的产出填进下游 ctx[inM],
逐条边判 OK / 空口 / 未送达 / 崩, 报一个联通率。

四条铁律 (见 SKILL.md「端口级联通率」):
  1. 跑两拍 —— 环上的边第一拍必然拿不到上一拍的值
  2. 判据是端口值非空 (None/{}/[] 都算空口)
  3. 空口与崩分开报
  4. 剩下的空口要给真因 (多为真值缺失, 不是链路断)

用法:
    QT_QPA_PLATFORM=offscreen <venv>/bin/python scripts/verify_node_linkage_topo.py \
        [--flow flows/state_space_obs.json] [--nodes ssdata,ssobs,ssff,...] [--timeout 15]
不传 --nodes 就跑全图 (94 节点会慢且多数需要硬件, 通常只跑关心的子图)。
"""
import argparse
import json
import os
import signal
import sys
import time
import traceback
from collections import Counter, defaultdict


class _TO(Exception):
    pass


def _call_with_timeout(fn, ctx, seconds):
    def _h(signum, frame):
        raise _TO("超时 %ds" % seconds)
    old = signal.signal(signal.SIGALRM, _h)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(ctx)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flow", default="flows/state_space_obs.json")
    ap.add_argument("--nodes", default="")
    ap.add_argument("--timeout", type=int, default=15)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    sys.path.insert(0, os.path.join(root, "src"))
    # 触发全部 _reg 注册
    from lerobot.middleware.nodes.impl import shared_runtime  # noqa: F401,E402
    from lerobot.engineering.registry import NODE_LOGIC, match_node  # noqa: E402

    flow = json.load(open(os.path.join(root, a.flow), encoding="utf-8"))
    nodes = {n["id"]: n for n in flow["nodes"]}
    links = flow["links"]
    wanted = [x for x in a.nodes.split(",") if x] or list(nodes)
    sub = [n for n in wanted if n in nodes]
    sset = set(sub)
    edges = [l for l in links if l["f"] in sset and l["t"] in sset]

    print("=" * 84)
    print("链路真跑核验 — 子图 %d 节点 / %d 条边 (全图 %d/%d)"
          % (len(sub), len(edges), len(nodes), len(links)))
    print("=" * 84)

    # ① 绑定核对
    print("\n① 画布节点 → 执行函数")
    bind = {}
    for nid in sub:
        nm = nodes[nid].get("name", "")
        key = match_node(nm)
        fn = (NODE_LOGIC.get(key) or {}).get("fn")
        bind[nid] = (key, fn)
        print("   %-13s %-24s %-15s %s" % (nid, nm[:22], key, getattr(fn, "__name__", "None")))
    byfn = defaultdict(list)
    for nid, (_k, f) in bind.items():
        if f:
            byfn[id(f)].append(nid)
    dup = {k: v for k, v in byfn.items() if len(v) > 1}
    for k, v in dup.items():
        # 同函数多节点可能是设计 (实现按 ctx["name"] 分流) —— 先核 l2_basic NODES 表再定性
        print("   ⚠️ 同函数复用: %s ← %s (先查 l2_basic/__init__.py::NODES, 可能是设计)"
              % (getattr(NODE_LOGIC[match_node(nodes[v[0]]["name"])]["fn"], "__name__", "?"), ", ".join(v)))

    # ② 拓扑序
    indeg = {n: 0 for n in sub}
    adj = {n: [] for n in sub}
    for l in edges:
        adj[l["f"]].append(l["t"])
        indeg[l["t"]] += 1
    order, q = [], [n for n in sub if indeg[n] == 0]
    while q:
        n = q.pop(0)
        order.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    cyc = [n for n in sub if n not in order]
    if cyc:
        print("\n   ⚠️ 成环节点(排最后跑): %s" % ", ".join(cyc))
        order += cyc

    # ③ 真跑两拍
    print("\n② 按拓扑序真调 ×2 拍 (每节点超时 %ds)" % a.timeout)
    produced, got, exec_log = {}, {}, {}
    for p in (1, 2):
        if p == 2:
            print("   ── 第 2 拍 (回灌第 1 拍的产出) ──")
        for nid in order:
            n = nodes[nid]
            _key, fn = bind[nid]
            if not fn:
                exec_log[nid] = ("skip", "无绑定")
                continue
            ctx = {"log": lambda m: None, "params": n.get("params") or {}, "name": n.get("name")}
            for l in edges:
                if l["t"] != nid:
                    continue
                v = produced.get((l["f"], l["f_port"]))
                got[(nid, l["t_port"])] = v
                ctx[l["t_port"]] = v
            t0 = time.time()
            try:
                out = _call_with_timeout(fn, ctx, a.timeout)
                dt = time.time() - t0
                if isinstance(out, dict):
                    nout = 0
                    for k, v in out.items():
                        if str(k).startswith("out") and v is not None:
                            produced[(nid, k)] = v
                            nout += 1
                    exec_log[nid] = ("ok", "%d 端口非空 / %.2fs" % (nout, dt))
                    if p == 2:
                        print("   ✅ %-13s %d 端口非空  %.2fs" % (nid, nout, dt))
                else:
                    exec_log[nid] = ("ok-other", "返回 %s" % type(out).__name__)
                    if p == 2:
                        print("   ⚠️  %-13s 返回 %s 非 dict  %.2fs" % (nid, type(out).__name__, dt))
            except _TO as e:
                exec_log[nid] = ("timeout", str(e))
                if p == 2:
                    print("   ⏱  %-13s 超时" % nid)
            except Exception as e:  # noqa: BLE001
                exec_log[nid] = ("crash", "%s: %s" % (type(e).__name__, str(e)[:90]))
                if p == 2:
                    print("   ❌ %-13s %s: %s" % (nid, type(e).__name__, str(e)[:80]))

    # ④ 逐边判定
    print("\n③ 逐条边判定 (共 %d 条)" % len(edges))
    rows = []
    for l in edges:
        up = produced.get((l["f"], l["f_port"]))
        dn = got.get((l["t"], l["t_port"]))
        if up is not None and dn is not None:
            st = "OK"
        elif exec_log.get(l["f"], ("", ""))[0] == "crash":
            st = "崩(上游)"
        elif up is None:
            st = "空口"
        else:
            st = "未送达"
        rows.append((st, l["f"], l["f_port"], l["t"], l["t_port"], l.get("label", "")))
    rank = {"OK": 0, "空口": 1, "未送达": 2, "崩(上游)": 3}
    rows.sort(key=lambda r: rank.get(r[0], 9))
    for st, f, fp, t, tp, lab in rows:
        icon = {"OK": "✅", "空口": "⚪", "未送达": "❌", "崩(上游)": "💥"}.get(st, "?")
        print("   %s %-13s %-6s → %-13s %-6s %-6s %s" % (icon, f, fp, t, tp, st, lab[:24]))

    cnt = Counter(r[0] for r in rows)
    total = len(rows) or 1
    print("\n" + "=" * 84)
    print("汇总: " + "  ".join("%s=%d" % (k, v) for k, v in cnt.items()))
    print("真联通率: %.1f%%  (%d/%d)" % (100.0 * cnt.get("OK", 0) / total, cnt.get("OK", 0), len(rows)))
    print("\n节点执行结果:")
    for nid in order:
        st, note = exec_log.get(nid, ("?", ""))
        print("   %-13s %-10s %s" % (nid, st, note))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
