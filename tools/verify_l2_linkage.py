# -*- coding: utf-8 -*-
"""verify_l2_linkage — L2 节点链路**真跑**核验 (不是静态读代码)。

老倪 2026-11-10: 「代码你也看到了, 你要保证这些L2的节点, 信息, 信号是真正联通的,
不要骗我」

做法:
  1. 读画布真源 flows/state_space_obs.json 的 nodes + links (94 节点 / 222 边)
  2. 取 L2 子图, 按拓扑序**真的调用**每个节点的实现函数
  3. 每个节点的 ctx 里填入上游 outN 实际产出的 payload
  4. 逐条边判定三态:
       OK    上游 outN 有值 且 下游 inM 也拿到值
       空口  上游 outN 是 None (节点没交结果)
       崩    节点执行异常 (转调缺失/依赖不全)
  5. 同时核对 registry 绑定 (画布节点名 → 执行函数) 是否正确

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_l2_linkage.py
"""
import json
import os
import signal
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.middleware.nodes.impl import shared_runtime  # noqa: F401,E402  触发全部 _reg
from lerobot.engineering.registry import NODE_LOGIC, match_node  # noqa: E402

FLOW = os.path.join(ROOT, "flows/state_space_obs.json")

# L2 链路节点 (老倪这几轮问的 + 它们的上下游)
WANTED = [
    "ssdata", "ssobs", "ssyolo", "ss2d3d", "sstactile", "ssaoi",
    "ssest", "sspred", "ssff", "ssinnov", "ss_mani_eng",
    "n_geoplan", "ssphys", "ssworld", "n_exec",
    "sssched", "sslimit", "ssact", "sssensor", "ssmode",
]

TIMEOUT_S = 15

# 可选: --nodes a,b,c 只跑指定子图 (默认 L2 主干)
if "--nodes" in sys.argv:
    _i = sys.argv.index("--nodes")
    if _i + 1 < len(sys.argv):
        WANTED = [x.strip() for x in sys.argv[_i + 1].split(",") if x.strip()]


class _TO(Exception):
    pass


def _alarm(signum, frame):
    raise _TO("节点执行超时 %ds" % TIMEOUT_S)


def call_with_timeout(fn, ctx):
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, TIMEOUT_S)
    try:
        return fn(ctx)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def main():
    flow = json.load(open(FLOW, encoding="utf-8"))
    nodes = {n["id"]: n for n in flow["nodes"]}
    links = flow["links"]
    sub = [n for n in WANTED if n in nodes]
    sub_set = set(sub)
    in_sub = [l for l in links if l["f"] in sub_set and l["t"] in sub_set]

    print("=" * 86)
    print("L2 链路真跑核验 — 子图 %d 节点 / 子图内 %d 条边 (全图 94/222)"
          % (len(sub), len(in_sub)))
    print("=" * 86)

    # ── ① registry 绑定核对 ──────────────────────────────────────────────
    print("\n① 画布节点 → 执行函数 绑定核对")
    print("   %-12s %-24s %-14s %s" % ("id", "name", "key", "fn"))
    bind = {}
    for nid in sub:
        nm = nodes[nid].get("name", "")
        key = match_node(nm)
        fn = (NODE_LOGIC.get(key) or {}).get("fn")
        fname = getattr(fn, "__name__", "None")
        bind[nid] = (key, fn)
        flag = "" if fn else "  ❌ 无绑定"
        print("   %-12s %-24s %-14s %s%s" % (nid, nm[:22], key, fname, flag))
    # 同一函数被多个节点复用 = 绑定错位
    from collections import defaultdict
    byfn = defaultdict(list)
    for nid, (k, f) in bind.items():
        if f:
            byfn[id(f)].append(nid)
    dups = {k: v for k, v in byfn.items() if len(v) > 1}
    if dups:
        print("\n   ⚠️ 同一函数被多个节点复用 (绑定错位):")
        for k, v in dups.items():
            print("      %s ← %s" % (getattr(NODE_LOGIC[match_node(nodes[v[0]]['name'])]['fn'],
                                             '__name__', '?'), ", ".join(v)))
    else:
        print("\n   ✅ 无函数复用")

    # ── ② 拓扑序 ────────────────────────────────────────────────────────
    indeg = {n: 0 for n in sub}
    adj = {n: [] for n in sub}
    for l in in_sub:
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
        print("\n   ⚠️ 成环节点(将排在最后跑): %s" % ", ".join(cyc))
        order += cyc

    # ── ③ 真跑 (跑两拍: 环上的边第一拍拿不到上一拍的值, 第二拍才通) ──────
    print("\n② 按拓扑序真调 ×2 拍 (环上边需第二拍; 每节点超时 %ds)" % TIMEOUT_S)
    produced = {}      # (nid, "out1") -> payload  (跨拍累积)
    got = {}           # (nid, "in1") -> 实际喂进的值 (取最后一拍)
    exec_log = {}
    logs = []
    _multi = []        # (节点, 端口, 上游条数, 其中非空条数)

    for _pass in (1, 2):
        if _pass == 2:
            print("   ── 第 2 拍 (用第 1 拍的产出回灌环上输入) ──")
        for nid in order:
            n = nodes[nid]
            key, fn = bind[nid]
            if not fn:
                exec_log[nid] = ("skip", "无绑定")
                continue
            ctx = {"log": lambda m, _n=nid: logs.append((_n, str(m)[:120])),
                   "params": n.get("params") or {}, "name": n.get("name")}
            # 同一入端口可能有多个上游 (如 ssdec.in5 ← 接触流形/性能流形/潜空间 三条线):
            #   判定「下游能不能拿到」要用**任一非空**, 不能只看最后一条 (后写覆盖 → 误报未送达)
            _port_vals = {}
            for l in in_sub:
                if l["t"] != nid:
                    continue
                v = produced.get((l["f"], l["f_port"]))
                _port_vals.setdefault(l["t_port"], []).append(v)
                ctx[l["t_port"]] = v          # 保真: 引擎侧也是最后一条覆盖
            for _p, _vs in _port_vals.items():
                _nb = [v for v in _vs if v is not None]
                got[(nid, _p)] = _nb[0] if _nb else None
                if len(_vs) > 1:
                    _multi.append((nid, _p, len(_vs), len(_nb)))
            t0 = time.time()
            try:
                out = call_with_timeout(fn, ctx)
                dt = time.time() - t0
                if isinstance(out, dict):
                    nout = 0
                    for k, v in out.items():
                        if str(k).startswith("out") and v is not None:
                            produced[(nid, k)] = v
                            nout += 1
                    exec_log[nid] = ("ok", "%d 个端口有值 / %.2fs" % (nout, dt))
                    if _pass == 2:
                        print("   ✅ %-12s %d 端口有值  %.2fs" % (nid, nout, dt))
                elif out is None:
                    exec_log[nid] = ("ok-empty", "返回 None")
                    if _pass == 2:
                        print("   ⚪ %-12s 返回 None (未产端口值)  %.2fs" % (nid, dt))
                else:
                    exec_log[nid] = ("ok-other", "返回 %s" % type(out).__name__)
                    if _pass == 2:
                        print("   ⚠️  %-12s 返回 %s 非 dict  %.2fs" % (nid, type(out).__name__, dt))
            except _TO as e:
                exec_log[nid] = ("timeout", str(e))
                if _pass == 2:
                    print("   ⏱  %-12s 超时" % nid)
            except Exception as e:  # noqa: BLE001
                exec_log[nid] = ("crash", "%s: %s" % (type(e).__name__, str(e)[:90]))
                if _pass == 2:
                    print("   ❌ %-12s %s: %s" % (nid, type(e).__name__, str(e)[:80]))

    # ── ④ 逐边判定 ───────────────────────────────────────────────────────
    print("\n③ 逐条边判定 (共 %d 条)" % len(in_sub))
    rows = []
    for l in in_sub:
        up = produced.get((l["f"], l["f_port"]))
        dn = got.get((l["t"], l["t_port"]))
        up_ok = up is not None
        dn_ok = dn is not None
        if up_ok and dn_ok:
            st = "OK"
        elif not up_ok and exec_log.get(l["f"], ("", ""))[0] == "crash":
            st = "崩(上游)"
        elif not up_ok:
            st = "空口"
        elif not dn_ok:
            st = "未送达"
        else:
            st = "OK"
        rows.append((st, l["f"], l["f_port"], l["t"], l["t_port"], l.get("label", "")))

    order_st = {"OK": 0, "空口": 1, "未送达": 2, "崩(上游)": 3}
    rows.sort(key=lambda r: order_st.get(r[0], 9))
    for st, f, fp, t, tp, lab in rows:
        icon = {"OK": "✅", "空口": "⚪", "未送达": "❌", "崩(上游)": "💥"}.get(st, "?")
        print("   %s %-10s %-6s → %-10s %-6s %-6s %s" % (icon, f, fp, t, tp, st, lab[:24]))

    # ── ⑤ 汇总 ───────────────────────────────────────────────────────────
    if _multi:
        print("\n④ 多上游共用同一入端口 (引擎侧是「最后一条覆盖」, 会丢掉前面的信号):")
        _last = {}
        for nid, p, n_tot, n_ok in _multi:
            _last[(nid, p)] = (n_tot, n_ok)
        for (nid, p), (n_tot, n_ok) in _last.items():
            print("   %-13s %-5s ← %d 条上游, 其中 %d 条有值%s"
                  % (nid, p, n_tot, n_ok, "" if n_ok == n_tot else "   ⚠️ 有信号被覆盖"))
    from collections import Counter
    cnt = Counter(r[0] for r in rows)
    print("\n" + "=" * 86)
    print("汇总: " + "  ".join("%s=%d" % (k, v) for k, v in cnt.items()))
    total = len(rows) or 1
    print("真联通率: %.1f%%  (%d/%d)" % (100.0 * cnt.get("OK", 0) / total,
                                          cnt.get("OK", 0), len(rows)))
    print("\n节点执行结果:")
    for nid in order:
        st, note = exec_log.get(nid, ("?", ""))
        print("   %-12s %-10s %s" % (nid, st, note))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
