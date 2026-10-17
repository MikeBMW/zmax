# -*- coding: utf-8 -*-
"""topic 语义类型 (真源: config/platform/dds_topic_types.json)

为什么要有这一层
----------------
之前所有话题的类型都写成 `zmax::SSNodePort` —— 那是 **DDS 信封** (topic/ts/json 三个字段),
不是数据的语义。老倪 2026-10-17 原话:

    「topic 的 type 太随意…一个 topic 是有明确的数据意义的, 至少有一个主要的发送 Tx 节点,
      例如 前馈加速器, 你的 topic 类型是 SSNodePort, 这根本看不出有什么含义;
      将 topic 的类型重新命名, 要与主要的发送节点关联上, 能看出主要的数据意义;
      有的节点只是复用, 你要根据状态空间工程全局检查所有 topic」

口径
----
  · 出口 topic: 类型 = 主要发送 (Tx) 节点的语义名, 例 ssff.out2 → zmax::FeedforwardAction
  · 入口 topic: 取它唯一上游出口的类型; 多个上游 (fan-in) 才退回 zmax::<Stem>In
  · 线上 DDS 信封仍是 SSNodePort (JSON 载荷) —— 换了信封要重建 IDL, 与语义命名无关
  · 节点/端口改名由注册表统一改, 不允许 UI 里再手写类型字符串

用法
----
    from lerobot.middleware import topic_types
    topic_types.type_of_topic("ss.node.ssff.out2")      # → "zmax::FeedforwardAction"
    topic_types.describe("ss.node.ssff.out2")           # → dict(type, cn, node, port, kind)
    topic_types.canonical()                             # → {topic: type} 全量
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
REG_PATH = ROOT / "config" / "platform" / "dds_topic_types.json"

_CACHE = {}


def registry() -> dict:
    """读注册表 (mtime 变了自动重读, 免得改 JSON 还要重启)。"""
    try:
        mt = REG_PATH.stat().st_mtime
    except OSError:
        return {}
    if _CACHE.get("mt") != mt:
        try:
            _CACHE["doc"] = json.loads(REG_PATH.read_text(encoding="utf-8"))
            _CACHE["mt"] = mt
        except Exception:                                        # noqa: BLE001
            _CACHE["doc"] = {}
    return _CACHE.get("doc") or {}


def _split(topic: str):
    """ss.node.<node_id>.<port> → (node_id, port); 不合规返回 (None, None)。"""
    t = str(topic or "")
    if not t.startswith("ss.node."):
        return None, None
    rest = t[len("ss.node."):]
    if "." not in rest:
        return None, None
    nid, port = rest.rsplit(".", 1)
    return nid, port


def describe(topic: str) -> dict:
    """一个 topic 的完整语义: {type, cn, node, node_name, port, dir, kind, origin}."""
    nid, port = _split(topic)
    if not nid:
        # 不是 ss.node.<节点>.<端口> 形态 (如 zmax/heartbeat) —— 这类话题的类型由 DDS 注册表声明,
        # 这里不给名字 (返回空串), 由调用方保留它自己的 type, 免得把已知类型降级成 Unknown
        return {"type": "", "cn": "非节点话题", "node": None, "port": None,
                "dir": None, "kind": "other", "origin": "not-node"}
    doc = registry()
    nd = (doc.get("nodes") or {}).get(nid)
    if not nd:
        return {"type": "zmax::SSNodePort", "cn": "未登记节点", "node": nid, "port": port,
                "node_name": nid, "dir": None, "kind": "unknown", "origin": "unregistered"}
    if port in (nd.get("outs") or {}):
        o = nd["outs"][port]
        return {"type": o["type"], "cn": _cn(nd, str(port)), "node": nid, "node_name": nd.get("name"),
                "port": port, "dir": "out", "kind": "message", "origin": "tx"}
    if port in (nd.get("ins") or {}):
        i = nd["ins"][port]
        return {"type": i["type"], "cn": _cn(nd, str(port)), "node": nid, "node_name": nd.get("name"),
                "port": port, "dir": "in", "kind": "fan-in" if i["origin"] == "fan-in" else "message",
                "origin": i.get("origin"), "producers": i.get("producers") or []}
    return {"type": "zmax::SSNodePort", "cn": "未登记端口", "node": nid, "port": port,
            "node_name": nd.get("name"), "dir": None, "kind": "unknown", "origin": "unregistered"}


def _cn(nd: dict, port: str) -> str:
    """类型的中文一句话 (tooltip 用): 节点中文名 + 出口语义。"""
    stem_cn = nd.get("cn") or ""
    ext = ((nd.get("outs") or {}).get(port) or {}).get("cn") \
        or ((nd.get("ins") or {}).get(port) or {}).get("cn") or ""
    # 有些节点的 PORT_LABELS 只是占位 (out1: 'out1'), 这种没有信息量, 不要拼进去
    if ext.strip().lower() in ("", str(port).lower(), str(port).lower() + " (默认)", "out"):
        ext = ""
    if ext:
        return "%s · %s" % (stem_cn, ext)
    import re as _re
    m = _re.fullmatch(r"out(\d+)", str(port))
    if m and int(m.group(1)) > 1:                  # 多出口且没有语义标签: 至少标清是第几路
        return "%s · 出口%s" % (stem_cn, m.group(1))
    return stem_cn


def type_of_topic(topic: str) -> str:
    return describe(topic)["type"]


def canonical() -> dict:
    """{topic: type} 全量映射 (273 条)。"""
    doc = registry()
    out = {}
    for nid, nd in (doc.get("nodes") or {}).items():
        for port, o in (nd.get("outs") or {}).items():
            out[o.get("topic") or ("ss.node.%s.%s" % (nid, port))] = o["type"]
        for port, i in (nd.get("ins") or {}).items():
            out[i.get("topic") or ("ss.node.%s.%s" % (nid, port))] = i["type"]
    return out


def type_for_port(node_id: str, port: str) -> str:
    doc = registry()
    nd = (doc.get("nodes") or {}).get(node_id) or {}
    for k in ("outs", "ins"):
        if port in (nd.get(k) or {}):
            return nd[k][port]["type"]
    return "zmax::SSNodePort"
