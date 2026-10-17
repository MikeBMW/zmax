# -*- coding: utf-8 -*-
"""从节点实现里抽"真实信号名" → config/platform/dds_signals.json

老倪 2026-10-17: 「signal列的信号呢? 这些信号, 是每个 topic 的 signal 哪里去了? 添加」

做法 (只认证据, 不编名字):
  ① 画布 params._port_labels 里的英文标识 → 该端口 (最强证据: 端口级)
  ② 节点只有**一个输出端口**时, 从它的实现文件里抽返回字典的字符串键 → out1
     (多输出节点的键归属不明, **不猜**, 留给实现补 _port_labels)
  ③ 抽不到 ⇒ 不写; Trace 侧显示 "value (端口整体值, 未声明)"

产出: {topic: [{name, src}]}, src ∈ port_label / impl
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.middleware import db                                        # noqa: E402

META = {"ts", "t", "n", "count", "bytes", "seq", "trace", "debug", "info"}
STOP = {"l2", "l3", "l4", "l5", "mlp", "dim", "http", "https", "npz", "json",
        "png", "jpg", "csv", "ok", "none", "true", "false", "utf", "id"}


def label_tokens(text):
    toks = re.findall(r"[A-Za-z][A-Za-z0-9_]{1,30}", str(text or ""))
    out = []
    for t in toks:
        if t.lower() in STOP or len(t) < 2:
            continue
        if "_" not in t and not re.match(r"^(u|q|x|y|z|kp|kd|mae|corr)\d*$", t):
            continue
        out.append(t)
    return out


def impl_keys(path, symbol=""):
    """从实现文件里抽字符串键; symbol 存在时优先该函数/类内部。"""
    p = os.path.join(ROOT, path.split("·")[0].strip())
    if not os.path.exists(p):
        return []
    try:
        tree = ast.parse(open(p, encoding="utf-8", errors="ignore").read())
    except Exception:                                                        # noqa: BLE001
        return []
    scope = tree.body
    sym = (symbol or "").strip()
    if sym:
        name = sym.split()[-1]
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
                scope = n.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else n.body
                break
    keys, seen = [], set()

    def add(k):
        k = str(k)
        if not k or k.lower() in META or k.lower() in STOP:
            return
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,30}$", k):
            return
        if k not in seen:
            seen.add(k)
            keys.append(k)

    def dict_keys(node):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    add(k.value)

    body = ast.Module(body=scope, type_ignores=[])
    # 只认"真正返回的字典": return {...} / return out; out/result/payload = {...}
    for n in ast.walk(body):
        if isinstance(n, ast.Return):
            dict_keys(n.value)
            if isinstance(n.value, ast.Name):
                nm = n.value.id
                for m in ast.walk(body):
                    if isinstance(m, ast.Assign) and any(
                            isinstance(tg, ast.Name) and tg.id == nm for tg in m.targets):
                        dict_keys(m.value)
    if not keys:                                    # 兜底: 惯用返回变量
        for n in ast.walk(body):
            if isinstance(n, ast.Assign) and any(
                    isinstance(tg, ast.Name) and tg.id in ("out", "result", "res", "payload", "ret")
                    for tg in n.targets):
                dict_keys(n.value)
    return keys[:14]


def main():
    nodes = db.node_rows()
    out = {}

    # ① 端口标签
    canvas = json.load(open(os.path.join(ROOT, "flows", "state_space_obs.json"), encoding="utf-8"))
    cnodes = canvas.get("nodes") if isinstance(canvas, dict) else canvas
    for n in cnodes or []:
        nid = n.get("id") or n.get("node_id")
        labels = ((n.get("params") or {}).get("_port_labels") or {})
        for port, txt in labels.items():
            toks = label_tokens(txt)
            if not toks:
                continue
            out.setdefault("ss.node.%s.%s" % (nid, port), [])
            for t in toks:
                out["ss.node.%s.%s" % (nid, port)].append({"name": t, "src": "port_label"})

    # ② 实现键 → 该节点的每个输出端口
    #    · 单输出: 键就是这一路的信号
    #    · 多输出且该端口没有 _port_labels: 键是节点级真实变量, 统一挂上并标 impl_node
    #      (宁可多列也不漏 —— 老倪: 「L1~L5 层所有 topic 的所有信号, 都要加载」)
    for r in nodes:
        if not r.get("source"):
            continue
        keys = impl_keys(r["source"], r.get("source_symbol") or "")
        if not keys:
            continue
        outs = [o for o in (r.get("outs") or []) if o.get("topic")]
        for o in outs:
            topic = str(o["topic"])
            if topic in out:                     # 端口标签已给出更精确的名字
                continue
            src = "impl" if len(outs) == 1 else "impl_node"
            out[topic] = [{"name": k, "src": src} for k in keys]

    # 去重
    for t, lst in out.items():
        seen, keep = set(), []
        for it in lst:
            if it["name"] in seen:
                continue
            seen.add(it["name"])
            keep.append(it)
        out[t] = keep

    p = os.path.join(ROOT, "config", "platform", "dds_signals.json")
    json.dump({"_doc": {"gen": "tools/gen_signal_dict.py", "src": ["port_label", "impl"]},
               "topics": out}, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_sig = sum(len(v) for v in out.values())
    print("✅ 写入 %s · 话题 %d · 信号 %d" % (p, len(out), n_sig))
    by = {}
    for v in out.values():
        for it in v:
            by[it["src"]] = by.get(it["src"], 0) + 1
    print("   来源:", by)


if __name__ == "__main__":
    main()
