# -*- coding: utf-8 -*-
"""话题 → 信号清单 (Trace 的 Signal 列真源)。

老倪 2026-10-17: 「signal列的信号呢? 这些信号, 是每个 topic 的 signal 哪里去了? 添加」

一个话题里到底有哪些信号, 按**证据强度**排序取:
  ① 实测: live.json / busdb / trace.jsonl 里真实出现过的载荷字段 (程序真的发过)
  ② 声明: 工程库 mw_signal (老库目前 113 条都是端口占位 "value", 视作未声明)
  ③ 画布: 节点 params._port_labels 里的英文标识 (如 "⚡ u_ff 建议动作" → u_ff)
  ④ 都没有 ⇒ 显式 "value (端口整体值, 未声明)", 不编造信号名

对外只暴露:
    signals_of(topic) -> [(name, unit, source)]    # source ∈ 实测/声明/画布/占位
    coverage()        -> dict(topic 数, 有实测信号的话题, 有声明, 占位)
"""
from __future__ import annotations

import json
import os
import re
import time

_CACHE = {"t": 0.0, "data": None}
_TTL = 5.0

_STOP = {
    "l2", "l3", "l4", "l5", "mlp", "dim", "http", "https", "id", "ids", "ok",
    "json", "npz", "pt", "png", "jpg", "csv", "yaml", "yml", "py", "s", "ms",
    "ts", "n", "x", "y", "z", "w", "h", "in", "out", "obs", "act", "api",
}
_META = {"ts", "t", "n", "count", "bytes", "seq", "age_s", "__ts", "node", "extra"}


def _root():
    return os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"


def _live_fields():
    """live.json / busdb.json 里真实出现过的字段 (topic → set)。"""
    out = {}
    for name in ("live.json", "busdb.json"):
        p = os.path.join(_root(), "zmax_data", "dataspace", name)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:                                                    # noqa: BLE001
            continue
        topics = d.get("topics") or d.get("messages") or {}
        for k, v in topics.items():
            f = (v or {}).get("fields") or {}
            if not isinstance(f, dict):
                continue
            keep = {str(x) for x in f if str(x) not in _META}
            if keep:
                t = str((v or {}).get("topic") or k)
                out.setdefault(t, set()).update(keep)
    return out


def _trace_fields(limit=4000):
    """trace.jsonl 尾部若干帧的真实字段。"""
    out = {}
    p = os.path.join(_root(), "zmax_data", "dataspace", "trace.jsonl")
    if not os.path.exists(p):
        return out
    rows = []
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            for line in f:
                rows.append(line)
        rows = rows[-limit:]
    except Exception:                                                        # noqa: BLE001
        return out
    for line in rows:
        try:
            r = json.loads(line)
        except Exception:                                                    # noqa: BLE001
            continue
        d = r.get("digest")
        if isinstance(d, str) and d.strip().startswith("{"):
            try:
                d = json.loads(d)
            except Exception:                                                # noqa: BLE001
                d = None
        if isinstance(d, dict):
            keep = {str(x) for x in d if str(x) not in _META}
            if keep:
                out.setdefault(str(r.get("topic") or ""), set()).update(keep)
    return out


def _declared():
    """工程库 mw_signal (排除端口占位 value)。"""
    out = {}
    try:
        import sys
        sys.path.insert(0, os.path.join(_root(), "src"))
        from lerobot.middleware import db
        for r in db.signals():
            nm = str(r.get("signal") or "")
            if not nm or nm == "value":
                continue
            out.setdefault(str(r.get("topic") or ""), {})[nm] = r.get("unit") or ""
    except Exception:                                                        # noqa: BLE001
        pass
    return out


def _label_tokens(text):
    """从 "⚡ u_ff 建议动作 (L2 MLP 快通道, 4D)" 抽出 u_ff。"""
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_]{1,30}", str(text or ""))
    keep = []
    for t in toks:
        tl = t.lower()
        if tl in _STOP or len(tl) < 2:
            continue
        if "_" not in t and not re.match(r"^(u|q|x|y|z|kp|kd|mae|corr)", tl):
            continue                    # 无下划线的裸词多半是英文单词(dim/mlp), 不当信号名
        keep.append(t)
    return keep


def _canvas_labels():
    """画布 params._port_labels → topic → 英文标识。"""
    out = {}
    p = os.path.join(_root(), "flows", "state_space_obs.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return out
    nodes = d.get("nodes") if isinstance(d, dict) else d
    for n in nodes or []:
        nid = n.get("id") or n.get("node_id")
        labels = ((n.get("params") or {}).get("_port_labels") or {})
        for port, txt in labels.items():
            toks = _label_tokens(txt)
            if toks:
                out.setdefault("ss.node.%s.%s" % (nid, port), set()).update(toks)
    return out


def _link_map():
    """输入 topic ← 上游出端口: 入口信号 = 上游出口信号 (真源 mw_link)。"""
    out = {}
    try:
        import sys
        sys.path.insert(0, os.path.join(_root(), "src"))
        from lerobot.middleware import db
        for l in db.links():
            out["ss.node.%s.%s" % (l.get("t"), l.get("t_port"))] = "ss.node.%s.%s" % (l.get("f"), l.get("f_port"))
    except Exception:                                                        # noqa: BLE001
        pass
    return out


def _registry():
    """config/platform/dds_signals.json (由 tools/gen_signal_dict.py 从端口标签/实现抽取)。"""
    out = {}
    p = os.path.join(_root(), "config", "platform", "dds_signals.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return out
    for t, lst in (d.get("topics") or {}).items():
        out[t] = {str(x.get("name")): str(x.get("src") or "实现") for x in (lst or []) if x.get("name")}
    return out


def _build():
    live = _live_fields()
    trace = _trace_fields()
    decl = _declared()
    labels = _canvas_labels()
    reg = _registry()
    links = _link_map()
    topics = {}
    for t, s in trace.items():
        topics.setdefault(t, {})["observed"] = set(s)
    for t, s in live.items():
        topics.setdefault(t, {}).setdefault("observed", set()).update(s)
    for t, m in decl.items():
        topics.setdefault(t, {})["declared"] = dict(m)
    for t, s in labels.items():
        topics.setdefault(t, {})["canvas"] = set(s)
    for t, m in reg.items():
        topics.setdefault(t, {})["registry"] = dict(m)
    # 入口 topic 继承上游出口的信号清单 (fan-in 取所有上游的并集)
    inherited = {}
    for dst, src in links.items():
        if dst in reg:
            continue
        if src in reg:
            inherited.setdefault(dst, {}).update(reg[src])
    for t, m in inherited.items():
        topics.setdefault(t, {})["inherited"] = dict(m)
    return topics


def _data():
    now = time.time()
    if _CACHE["data"] is None or now - _CACHE["t"] > _TTL:
        _CACHE.update(t=now, data=_build())
    return _CACHE["data"]


def signals_of(topic):
    """topic → [(name, unit, source)]; 无任何证据时给一条占位 (source=占位)。"""
    t = str(topic or "")
    d = (_data() or {}).get(t) or {}
    out, seen = [], set()

    def push(nm, unit, src):
        if nm in seen:
            return
        seen.add(nm)
        out.append((nm, unit or "", src))

    for nm in sorted(d.get("observed") or []):
        push(nm, "", "实测")
    for nm, unit in sorted((d.get("declared") or {}).items()):
        push(nm, unit, "声明")
    for nm in sorted(d.get("canvas") or []):
        push(nm, "", "画布")
    for nm, src in sorted((d.get("registry") or {}).items()):
        push(nm, "", "实现" if src != "port_label" else "画布")
    for nm in sorted((d.get("inherited") or {}).keys()):
        push(nm, "", "上游")
    if not out:
        if t.startswith("ss.node."):
            # 📌 2026-10-17 老倪: 「moveit 节点输出的信号呢? topic 怎么不在 trace L2 层里?」
            #   原来这里给的是信封字段 topic/ts/json —— 全是元数据, 被 is_meta() 全滤掉 ⇒ 整个端口
            #   一行都不剩 (out1 就这么消失的)。端口没声明信号时, 用**端口名**占一行 (值 —, 标未实测),
            #   至少让人看得到"这个节点有这个输出口、这拍没数据", 不硬造 payload 里的字段名。
            out.append((t.split(".")[-1], "", "端口(未声明信号)"))
        else:
            out.append(("value", "", "占位"))
    return out


def coverage():
    d = _data() or {}
    obs = sum(1 for v in d.values() if v.get("observed"))
    dec = sum(1 for v in d.values() if v.get("declared"))
    can = sum(1 for v in d.values() if v.get("canvas"))
    reg = sum(1 for v in d.values() if v.get("registry"))
    inh = sum(1 for v in d.values() if v.get("inherited"))
    return {"topics_with_signals": len(d), "observed": obs, "declared": dec,
            "canvas": can, "registry": reg, "inherited": inh,
            "total_signals": sum(len(signals_of(t)) for t in d)}
