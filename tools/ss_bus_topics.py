# -*- coding: utf-8 -*-
"""ss_bus_topics.py — 数据总线的**节点输出 topic** 注册与单步序列化 (老倪 2026-10-12)。

老倪原话:
> 右侧的数据总线, 要有对应的 topic; topic 数据来源于全局数据空间。我单步运行的时候, 要高亮显示
> 当前节点输出的 topic。默认每个节点至少输出一个 topic。这个 topic 数据, 在单步运行 debug 的时候
> 肯定会输出, 但是在整体运行的时候, 可以考虑性能, 不序列化输出 —— 即单步运行是为了标定系统而启用的。

口径 (三条, 逐条落到实现):
 1. **每个节点至少一个 topic**: `ensure_busdb()` 拿画布全部节点与 DBC(busdb.json) 对齐, 缺的补
    `ss/<node_id>/out`(合成 topic, 标记 synth=true; 真源里已有的绝不覆盖)。幂等 + 备份 + 回读。
 2. **单步高亮**: 单步跑到哪个节点, `step_publish()` 写 `step_current.json`(当前节点 + 其输出 topic + 载荷),
    数据总线视图据此把该节点输出 topic 的 Trace/Data 行**金色高亮并置顶**。
 3. **序列化有闸**: 单步/调试 ⇒ 真序列化载荷进 trace.jsonl; **整体运行 ⇒ 不序列化**(只登记 topic, 零载荷开销)。

真源: zmax_data/dataspace/{busdb.json, trace.jsonl} + 画布 data/database/zmax/sources/canvas/state_space_obs.json
CLI:
  python3 tools/ss_bus_topics.py ensure [--dry]   # 对齐"每节点 ≥1 topic"
  python3 tools/ss_bus_topics.py status           # 现状(节点数/topic 数/缺口)
  python3 tools/ss_bus_topics.py current          # 当前单步节点与输出 topic
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DS_DIR = os.path.join(ROOT, "zmax_data", "dataspace")
BUSDB = os.path.join(DS_DIR, "busdb.json")
TRACE = os.path.join(DS_DIR, "trace.jsonl")
CURRENT = os.path.join(DS_DIR, "step_current.json")
CANVAS_CANDIDATES = ("data/database/zmax/sources/canvas/state_space_obs.json",
                     "src/lerobot/engineering/flows/state_space_obs.json",
                     "flows/state_space_obs.json")
STEP_MODES = ("step", "debug", "单步", "调试")          # 只有这些模式才序列化
MAX_PAYLOAD_CHARS = 4000                                 # 载荷上限 (超长截断并如实标注)


def canvas_path() -> str:
    for rel in CANVAS_CANDIDATES:
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            return p
    return os.path.join(ROOT, CANVAS_CANDIDATES[-1])


def _load(p: str, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                              # noqa: BLE001
        return default


def canvas_nodes(path: str | None = None) -> list[dict]:
    """画布全部节点 (id/name/params)。"""
    d = _load(path or canvas_path(), {}) or {}
    ns = d.get("nodes") or d.get("blocks") or []
    out = []
    for n in ns:
        if not isinstance(n, dict):
            continue
        nid = n.get("id") or n.get("node_id") or ""
        if nid:
            out.append({"id": nid, "name": n.get("name") or n.get("title") or nid,
                        "params": n.get("params") or {}})
    return out


def topic_id(node_id: str) -> str:
    """合成 topic 命名 (稳定: 由节点 id 决定, 改名不改 topic)。"""
    return "ss/%s/out" % node_id


def topics_by_source(busdb: dict) -> dict:
    """节点**输出 topic** = 该节点出线的 topic (DBC signals 里 src == node_id)。

    真源语义 (2026-10-12 查明): busdb.signals 是**画布连线**的记录
    {sid, link_id, src, dst, src_port, dst_port, label, layer, topic} ⇒ 节点的"输出 topic"
    就是它所有出线携带的 topic (去重); 没有出线的节点才需要合成 topic。
    """
    by = {}
    for s in (busdb.get("signals") or []):
        if not isinstance(s, dict) or s.get("synth"):
            continue
        nid = s.get("src") or ""
        t = s.get("topic") or ""
        if not nid:
            continue
        e = by.setdefault(nid, {"topics": [], "links": []})
        if t and t not in e["topics"]:
            e["topics"].append(t)
        e["links"].append({"sid": s.get("sid"), "dst": s.get("dst"), "label": s.get("label"),
                           "src_port": s.get("src_port"), "topic": t})
    return by


def synth_topics(busdb: dict) -> dict:
    """已合成的 topic (synth=true) 按节点归组: {node_id: [topic...]}。"""
    by = {}
    for s in (busdb.get("signals") or []):
        if isinstance(s, dict) and s.get("synth"):
            nid = s.get("node_id") or s.get("src") or ""
            if nid:
                by.setdefault(nid, []).append(s.get("key") or s.get("topic"))
    return by


def status() -> dict:
    db = _load(BUSDB, {}) or {}
    nodes = canvas_nodes()
    real, syn = topics_by_source(db), synth_topics(db)
    missing, with_real = [], 0
    for n in nodes:
        if real.get(n["id"]):
            with_real += 1
        if not syn.get(n["id"]):
            missing.append(n["id"])          # 没有**独立输出 topic** = 缺 (每节点必须有自己的 topic)
    return {"canvas_nodes": len(nodes), "busdb_nodes": len(db.get("nodes") or {}),
            "links": sum(1 for x in (db.get("signals") or []) if not x.get("synth")),
            "signals_total": len(db.get("signals") or []), "messages": len(db.get("messages") or {}),
            "nodes_with_real_out_topic": with_real, "nodes_with_own_out_topic": len(syn),
            "nodes_without_topic": missing, "n_missing": len(missing)}


def ensure_busdb(*, dry: bool = False, path: str | None = None) -> dict:
    """保证**每个画布节点至少一个输出 topic** (缺的补合成 topic; 幂等; 备份 + 回读)。"""
    p = path or BUSDB
    db = _load(p, {}) or {}
    if not db:
        return {"ok": False, "why": "busdb.json 不存在或不可解析: %s" % os.path.relpath(p, ROOT)}
    nodes = canvas_nodes()
    real, syn = topics_by_source(db), synth_topics(db)
    sigs = db.setdefault("signals", [])
    msgs = db.setdefault("messages", {})
    # 合成条目只按"节点是否还在画布上"清理 (真源 182 条连线一律不动)
    alive = {n["id"] for n in nodes}
    keep, pruned = [], []
    for x in sigs:
        if isinstance(x, dict) and x.get("synth") and (x.get("node_id") or x.get("src") or "") not in alive:
            pruned.append(x.get("key"))
        else:
            keep.append(x)
    sigs[:] = keep
    syn = synth_topics(db)
    added = []
    for n in nodes:
        # 🔌 老倪: 「默认每个节点至少输出一个 topic」⇒ **每个节点**都有自己的输出 topic
        #   ss/<node_id>/out (独立、可被单步单独高亮); 该节点若还有真源出线 topic, 记录在 l2 里不丢。
        if syn.get(n["id"]):
            continue
        key = topic_id(n["id"])
        nm = str(n["name"]).replace("（", "(").replace("）", ")")
        l2 = (real.get(n["id"]) or {}).get("topics") or []
        sigs.append({"key": key, "topic": key, "name": "%s · 输出 topic" % nm, "node_id": n["id"],
                     "unit": "-", "synth": True, "kind": "node_out", "link_topics": l2,
                     "built": round(time.time(), 3),
                     "src": "canvas 节点 (每节点 ≥1 输出 topic; 单步 debug 真序列化, 整体运行不序列化)"})
        added.append({"node_id": n["id"], "topic": key, "name": nm, "link_topics": l2})
    if added:
        msgs["ss_node_out"] = {"name": "ss_node_out", "kind": "节点输出 topic",
                               "desc": "画布节点默认输出 topic (每个节点 ≥1 个独立 topic; 单步 debug 时真序列化, "
                                       "整体运行不序列化 · 性能)",
                               "signals": sorted(a["topic"] for a in added) or
                                          sorted(x.get("key") for x in sigs if x.get("synth"))}
    cnt = db.setdefault("counts", {})
    cnt["nodes"] = len(nodes)
    cnt["signals"] = len(sigs)
    cnt["messages"] = len(msgs)
    cnt["synth_topics"] = sum(1 for s in sigs if isinstance(s, dict) and s.get("synth"))
    db["built"] = round(time.time(), 3)
    db["_synth_note"] = ("2026-10-12 老倪: 默认每个节点至少输出一个 topic; 合成 topic (synth=true) 无真源信号定义, "
                         "单步 debug 时按节点输出真序列化, 整体运行不序列化 (性能)。")
    if dry:
        return {"ok": True, "dry_run": True, "added": len(added), "added_list": added[:8], "status": status()}
    bak = p + ".bak_%d" % int(time.time())
    shutil.copy2(p, bak)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    back = _load(p, {}) or {}
    ok = (len(back.get("signals") or []) == len(sigs)
          and all(any(s.get("key") == a["topic"] for s in (back.get("signals") or [])) for a in added))
    return {"ok": bool(ok), "added": len(added), "pruned": len(pruned), "added_list": added,
            "backup": os.path.relpath(bak, ROOT),
            "readback": {"signals_total": len(back.get("signals") or []), "nodes": len(back.get("nodes") or {})},
            "status": status()}


# ── 单步: 序列化闸 + 当前节点 topic 指针 ─────────────────────────────────────
def _serializable(obj, cap: int = MAX_PAYLOAD_CHARS) -> dict:
    """把节点输出转成可序列化摘要 (超长截断, 如实标注)。"""
    def conv(v):
        if isinstance(v, (str, int, float, bool)) or v is None:
            return (v[:400] + "…") if isinstance(v, str) and len(v) > 400 else v
        if isinstance(v, dict):
            return {str(k): conv(x) for k, x in list(v.items())[:40]}
        if isinstance(v, (list, tuple)):
            items = [conv(x) for x in list(v)[:20]]
            return items + (["…共 %d 项" % len(v)] if len(v) > 20 else [])
        return repr(v)[:200]
    try:
        payload = conv(obj)
        s = json.dumps(payload, ensure_ascii=False)
    except Exception as e:                                                          # noqa: BLE001
        return {"_unserializable": repr(e)[:200]}
    if len(s) > cap:
        return {"_truncated": True, "_chars": len(s), "_head": s[:cap]}
    return payload


def publish(node: dict, out, *, mode: str = "step", quiet: bool = True) -> dict:
    """单步/调试 ⇒ 真序列化输出进 trace.jsonl + 写当前节点指针; 整体运行 ⇒ 不序列化(只报闸门)。"""
    nid = node.get("id") or "?"
    topics = [topic_id(nid)]
    db = _load(BUSDB, {}) or {}
    # 单步高亮口径: 用**该节点自己的输出 topic** (ss/<id>/out)。真源里所有画布连线共用
    #   topic "zmax/link_value" ⇒ 按连线 topic 高亮会把全部连线点亮, 无法定位当前节点。
    own = synth_topics(db).get(nid) or []
    topics = list(own) or [topic_id(nid)]
    link_topics = (topics_by_source(db).get(nid) or {}).get("topics") or []
    if mode not in STEP_MODES:
        doc = {"node_id": nid, "node_name": node.get("name"), "topics": topics, "link_topics": link_topics,
               "serialized": False, "why": "整体运行: 按性能考虑不序列化输出 (topic 已登记, 载荷跳过)",
               "t": time.strftime("%Y-%m-%d %H:%M:%S")}
        os.makedirs(DS_DIR, exist_ok=True)
        with open(CURRENT, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return doc
    payload = _serializable(out)
    rec = {"t": round(time.time(), 3), "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "type": "step",
           "topic": topics[0], "topics": topics, "link_topics": link_topics,
           "node": nid, "node_name": node.get("name"),
           "value": payload, "mode": mode, "src": "ss_bus_topics.publish (单步 debug)"}
    try:
        os.makedirs(DS_DIR, exist_ok=True)
        with open(TRACE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:                                                          # noqa: BLE001
        return {"ok": False, "why": "trace 追加失败: %r" % (e,)}
    doc = {"node_id": nid, "node_name": node.get("name"), "topics": topics, "link_topics": link_topics,
           "serialized": True,
           "payload": payload, "t": rec["ts"], "trace_line": os.path.relpath(TRACE, ROOT)}
    with open(CURRENT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc


def read_current() -> dict:
    return _load(CURRENT, {}) or {}


def highlight_topics(fresh_s: float = 900.0) -> set:
    """当前单步节点的输出 topic 集合 (数据总线视图据此高亮; 过旧视为无)。"""
    d = read_current()
    if not d.get("serialized"):
        return set()
    try:
        import datetime as _dt
        ts = _dt.datetime.strptime(str(d.get("t")), "%Y-%m-%d %H:%M:%S").timestamp()
        if time.time() - ts > fresh_s:
            return set()
    except Exception:                                                               # noqa: BLE001
        return set()
    return set(d.get("topics") or [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("ensure", "status", "current"))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "ensure":
        r = ensure_busdb(dry=a.dry)
        print(json.dumps({k: v for k, v in r.items() if k != "added_list"}, ensure_ascii=False))
        if r.get("added_list"):
            print("  补的 topic 前几条:", json.dumps(r["added_list"][:5], ensure_ascii=False))
    elif a.cmd == "status":
        print(json.dumps(status(), ensure_ascii=False))
    else:
        print(json.dumps(read_current(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
