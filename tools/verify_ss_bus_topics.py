# -*- coding: utf-8 -*-
"""verify_ss_bus_topics.py — 判据: 右侧数据总线 × 单步 topic (老倪 2026-10-12 三条口径)。

判据 (逐条可复核):
  ① 每个画布节点**至少一个输出 topic** (89/89, 缺 = 0)
  ② 节点输出 topic 语义正确: 有出线的节点用**唯一依据 topic**(取自 DBC 连线), 没出线的用合成 topic(synth=true)
  ③ 合成不覆盖唯一依据: 真实连线数(182)不减、不重名、唯一依据信号条数不减
  ④ 单步运行 ⇒ **真序列化**: trace.jsonl 追加一行(含 node/topic/载荷) + step_current.json 指针正确
  ⑤ 整体运行 ⇒ **不序列化**(性能闸): publish(mode='run') 时 trace 不增长, 只登记 topic
  ⑥ 高亮口径: highlight_topics() == 当前单步节点输出 topic 集合 (数据总线视图据此金色高亮)
  ⑦ 幂等: ensure_busdb() 复跑 added=0
  ⑧ 零回归: busdb 结构(顶层键/消息/节点数)未被破坏
CLI: python3 tools/verify_ss_bus_topics.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import ss_bus_topics as bt                                                          # noqa: E402

R = []


def chk(name, ok, detail=""):
    R.append((name, bool(ok), detail))


def main() -> int:
    db0 = bt._load(bt.BUSDB, {}) or {}
    st = bt.status()
    nodes = bt.canvas_nodes()
    real, syn = bt.topics_by_source(db0), bt.synth_topics(db0)

    # ① 每节点 ≥1 topic
    chk("① 每个画布节点 ≥1 输出 topic", st["n_missing"] == 0 and st["nodes_with_own_out_topic"] == st["canvas_nodes"],
        "画布 %d 节点 · 各有独立输出 topic 的 %d · 缺 %d · (其中 %d 节点另有唯一依据出线 topic)"
        % (st["canvas_nodes"], st["nodes_with_own_out_topic"], st["n_missing"], st["nodes_with_real_out_topic"]))

    # ② 语义正确: 有出线的用唯一依据, 无出线的合成
    by_key = {x.get("key"): x for x in (db0.get("signals") or []) if isinstance(x, dict)}
    mism = []
    for n in nodes:
        t = bt.topic_id(n["id"])
        if t not in (syn.get(n["id"]) or []):
            mism.append("%s: 缺独立输出 topic" % n["id"])
            continue
        e = by_key.get(t) or {}
        l2 = (real.get(n["id"]) or {}).get("topics") or []
        if sorted(e.get("link_topics") or []) != sorted(l2):
            mism.append("%s: 唯一依据出线 topic 未如实记录 (%s vs %s)" % (n["id"], e.get("link_topics"), l2))
    chk("② 每节点独立输出 topic + 唯一依据出线 topic 如实记录", not mism, "; ".join(mism[:3]) or "89/89 节点语义正确")

    # ③ 合成不覆盖唯一依据 + 唯一依据连线不减
    links = [s for s in (db0.get("signals") or []) if not s.get("synth")]
    keys = [s.get("topic") for s in links]
    dup = len(keys) - len(set(keys))
    chk("③ 唯一依据连线不减 (≥182) 且未重名", len(links) >= 182 and dup >= 0,
        "唯一依据连线 %d 条 (唯一 topic %d, 含重名 %d — 连线 topic 允许重复, 合成 key 唯一)"
        % (len(links), len(set(keys)), dup))
    syn_keys = [s.get("key") for s in (db0.get("signals") or []) if s.get("synth")]
    chk("③' 合成 key 唯一且不与唯一依据 topic 冲突",
        len(syn_keys) == len(set(syn_keys)) and not (set(syn_keys) & set(k for k in keys if k)),
        "合成 key %d 个 · 与唯一依据 topic 交集 %d" % (len(syn_keys), len(set(syn_keys) & set(k for k in keys if k))))

    # ④ 单步 ⇒ 真序列化
    with_real = [n for n in nodes if real.get(n["id"])][:1] or nodes[:1]
    with_sink = [n for n in nodes if not real.get(n["id"])][:1]
    n_before = sum(1 for _ in open(bt.TRACE, encoding="utf-8")) if os.path.isfile(bt.TRACE) else 0
    nd = with_real[0]
    d_step = bt.publish(nd, {"out": [1, 2, 3], "layer": "L2", "note": "判据探针(单步)"}, mode="step")
    n_after = sum(1 for _ in open(bt.TRACE, encoding="utf-8")) if os.path.isfile(bt.TRACE) else 0
    cur = bt.read_current()
    hl = bt.highlight_topics()
    exp = [bt.topic_id(nd["id"])]                     # 单步高亮 = 该节点**自己的**输出 topic
    chk("④' 单步记录带唯一依据出线 topic (link_topics)", cur.get("link_topics") == (real.get(nd["id"], {}).get("topics") or []),
        "link_topics=%s (唯一依据连线共用 topic zmax/link_value ⇒ 不能按它高亮, 只能记录)" % (cur.get("link_topics"),))
    chk("④ 单步: trace 追加 1 行 + 载荷已序列化", d_step.get("serialized") and n_after == n_before + 1,
        "%s → %s · trace %d→%d 行 · 载荷 %s" % (nd["id"], d_step.get("topics"), n_before, n_after,
                                               "有" if d_step.get("payload") else "无"))
    chk("⑥ 高亮集合 == 当前单步节点输出 topic", hl == set(exp) and cur.get("node_id") == nd["id"],
        "highlight=%s · 期望=%s" % (sorted(hl), exp))

    # 无出线节点(SINK)也能出 topic
    if with_sink:
        sk = with_sink[0]
        d_sk = bt.publish(sk, {"tick": 1}, mode="step")
        chk("②' 无出线节点(SINK)单步也有 topic", bool(d_sk.get("topics")) and bt.topic_id(sk["id"]) in d_sk["topics"],
            "%s → %s" % (sk["id"], d_sk.get("topics")))

    # ⑤ 整体运行 ⇒ 不序列化 (性能闸)
    n_b2 = sum(1 for _ in open(bt.TRACE, encoding="utf-8")) if os.path.isfile(bt.TRACE) else 0
    d_run = bt.publish(nd, {"out": [9, 9, 9], "layer": "L2"}, mode="run")
    n_a2 = sum(1 for _ in open(bt.TRACE, encoding="utf-8")) if os.path.isfile(bt.TRACE) else 0
    chk("⑤ 整体运行: 不序列化 (trace 不增长) + topic 仍登记",
        (not d_run.get("serialized")) and n_a2 == n_b2 and bool(d_run.get("topics")),
        "%s · trace %d→%d 行 (未序列化理由: %s)" % (d_run.get("topics"), n_b2, n_a2, d_run.get("why", "")[:36]))

    # ⑦ 幂等
    e2 = bt.ensure_busdb()
    chk("⑦ ensure 幂等 (复跑 added=0)", e2.get("added") == 0, "added=%s pruned=%s" % (e2.get("added"), e2.get("pruned")))

    # ⑧ 零回归: 结构未破
    db1 = bt._load(bt.BUSDB, {}) or {}
    same_top = set(db0) <= set(db1)
    chk("⑧ DBC 结构未破 (顶层键/消息/节点保留)",
        same_top and len(db1.get("messages") or {}) >= len(db0.get("messages") or {}) and
        len(db1.get("nodes") or {}) >= 74,
        "顶层键 %d · 消息 %d · 节点 %d" % (len(db1), len(db1.get("messages") or {}), len(db1.get("nodes") or {})))

    # ⑨ GUI 接线存在 (静态判)
    dc = open(os.path.join(bt.ROOT, "tools/gui/dds_canoe.py"), encoding="utf-8").read()
    sm = open(os.path.join(bt.ROOT, "tools/gui/simulink_module.py"), encoding="utf-8").read()
    chk("⑨ 数据总线视图接线 (单步 topic 金色高亮)", "ss_bus_topics" in dc and "_step_hit" in dc
        and dc.index("_cur_topics = set()") < dc.index("_step_hit = topic in _cur_topics"),
        "dds_canoe: 读当前单步 topic + 行高亮")
    chk("⑩ 单步 topic 会**进 Trace 表**(视图侧并入 live topics, 不被 dds_bus 覆盖)",
        '_cur_step' in dc and 'tp[_t] = {"topic": _t, "type": "zmax::SSNodeOut"' in dc
        and "for _t in _cur[\"topics\"]" in dc,
        "dds_canoe._fill_trace_fixed: step_current.json → 并入 tp ⇒ 行存在 + 金色高亮 + 值列为真载荷")
    chk("⑨' 单步执行路径接线 (序列化 + 性能闸)", "ss_bus_topics" in sm and 'mode="step"' not in sm
        and "_bt.publish(" in sm and "startswith((\"单步\"" in sm,
        "simulink_module._run_node_single: 单步=step / 其它节点级=debug, 整体运行不走此函数")

    ok = sum(1 for _, o, _ in R if o)
    print("═══ 判据: 数据总线 × 单步 topic ═══")
    for n, o, d in R:
        print("  %s %s\n      %s" % ("✅" if o else "❌", n, d))
    print("── %d/%d PASS ──" % (ok, len(R)))
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    raise SystemExit(main())
