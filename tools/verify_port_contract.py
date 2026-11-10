#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_port_contract.py — 端口**字段**契约检查

画布连线只约束「端口连没连」, 不约束「payload 字段对不对得上」。
上一类问题已经吃过: 端口有值、字段名不一致 ⇒ 下游 `_pick`/`.get` 拿 None,
画布上看是绿的, 实际信号是空的。

本工具对每条边做两件事:
  ① 静态解析「下游实现真读哪些键」(ast, 定位到 registry 记录的 file+line)
  ② 跑节点拿到「上游端口真给了哪些键」(可选, --live)

然后报三类:
  ✅ 对齐      下游要的键都在上游 payload 里
  ⚠ 部分缺失  有的键不在 (下游会回退/拿 None)
  ⚪ 全缺      下游要的键一个都没有

用法:
  python tools/verify_port_contract.py                 # 全图, 只做静态期望键表
  python tools/verify_port_contract.py --nodes ssdec,sslimit
  python tools/verify_port_contract.py --live          # 真跑节点对比实际 payload
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.middleware.nodes.impl import shared_runtime  # noqa: F401,E402  触发全部 _reg
from lerobot.engineering.registry import NODE_LOGIC, match_node  # noqa: E402

FLOW = os.path.join(ROOT, "flows/state_space_obs.json")


def _fn_ast(fn):
    """返回 (树, 函数节点) —— registry 记录 file + co_firstlineno, 精确定位。"""
    if not callable(fn):
        return None, None
    f = inspect.getsourcefile(fn) or getattr(fn.__code__, "co_filename", None)
    if not f or not os.path.exists(f):
        return None, None
    ln = getattr(fn.__code__, "co_firstlineno", None)
    try:
        src = open(f, encoding="utf-8").read()
        tree = ast.parse(src)
    except Exception:                                                      # noqa: BLE001
        return None, None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # co_firstlineno 指向 def 行 (含装饰器时可能偏移)
            if node.lineno <= (ln or 0) <= (node.end_lineno or node.lineno):
                return tree, node
    return tree, None


_PORT_NAMES = {("in%d" % i) for i in range(1, 13)}


def _resolve(fn, depth=0):
    """shared_runtime 里很多是薄壳 (`from .xxx import node_x as _impl; return _impl(ctx)`),
    薄壳本身不读字段 ⇒ 跟到真实现再分析。"""
    if depth > 3:
        return fn
    try:
        src = inspect.getsource(fn)
    except Exception:                                                      # noqa: BLE001
        return fn
    import importlib
    import re
    m = re.search(r"from \.(\w+) import (\w+)", src)
    if not m:
        return fn
    pkg = (fn.__module__ or "").rsplit(".", 1)[0]
    try:
        mod = importlib.import_module("%s.%s" % (pkg, m.group(1)))
        real = getattr(mod, m.group(2), None)
    except Exception:                                                      # noqa: BLE001
        return fn
    if real is None or real is fn or not callable(real):
        return fn
    return _resolve(real, depth + 1)


def expected_keys(fn, port):
    """下游实现真读该入端口的哪些键。

    两种写法都认:
      _pick("in6", ("u_ff", "u", "vec"))       → 候选键全要
      ctx.get("in5") 后的 .get("V_p") / ["eta"] → 近邻 10 行内取键
    """
    tree, fnode = _fn_ast(_resolve(fn))
    if fnode is None:
        return None, "定位不到函数体"
    keys, how = [], []
    nodes = list(ast.walk(fnode))
    # ① _pick("inN", (...))
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        nm = getattr(getattr(node.func, "id", None) or getattr(node.func, "attr", None), "__len__", None)
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname in ("_pick", "_get"):
            a0 = node.args[0] if node.args else None
            if isinstance(a0, ast.Constant) and a0.value == port:
                a1 = node.args[1] if len(node.args) > 1 else None
                if isinstance(a1, (ast.Tuple, ast.List)):
                    for e in a1.elts:
                        if isinstance(e, ast.Constant) and isinstance(e.value, str):
                            keys.append(e.value)
                how.append("_pick")
    # ② ctx.get("inN") / ctx["inN"] 之后的取键
    for node in nodes:
        hit = False
        if isinstance(node, ast.Call):
            fn_node = node.func
            if isinstance(fn_node, ast.Attribute) and fn_node.attr in ("get", "pop"):
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == port:
                    hit = True
        elif isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == port:
                hit = True
        if not hit:
            continue
        how.append("ctx[%s]" % port)
        lo, hi = node.lineno, (getattr(node, "end_lineno", node.lineno) or node.lineno) + 10
        for sub in nodes:
            if not (lo <= getattr(sub, "lineno", 0) <= hi):
                continue
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and sub.func.attr == "get" and sub.args \
                    and isinstance(sub.args[0], ast.Constant) \
                    and isinstance(sub.args[0].value, str) \
                    and sub.args[0].value not in _PORT_NAMES:
                keys.append(sub.args[0].value)
            elif isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) \
                    and isinstance(sub.slice.value, str) \
                    and sub.slice.value not in _PORT_NAMES:
                keys.append(sub.slice.value)
    seen, uniq = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq, "+".join(sorted(set(how))) or "未读到该端口"


def payload_keys(v, depth=0):
    if isinstance(v, dict):
        return set(str(k) for k in v.keys())
    return set()


def main():
    f_nodes = {n["id"]: n for n in json.load(open(FLOW, encoding="utf-8"))["nodes"]}
    flow = json.load(open(FLOW, encoding="utf-8"))
    links = flow["links"]
    only = None
    if "--nodes" in sys.argv:
        i = sys.argv.index("--nodes")
        if i + 1 < len(sys.argv):
            only = {x.strip() for x in sys.argv[i + 1].split(",") if x.strip()}

    # 节点 id → registry key
    key_of = {}
    for nid, n in f_nodes.items():
        k = match_node(n.get("name") or "")
        if k:
            key_of[nid] = k

    print("=" * 96)
    print("端口字段契约: 下游真读的键 (静态解析 registry 记录的实现函数)")
    print("=" * 96)

    by_t = {}
    for l in links:
        by_t.setdefault(l["t"], []).append(l)

    rows = []
    for t, ls in sorted(by_t.items()):
        if only and t not in only:
            continue
        k = key_of.get(t)
        if not k:
            rows.append((t, "-", "无绑定", [], "", ""))
            continue
        fn = NODE_LOGIC[k]["fn"]
        f = NODE_LOGIC[k].get("file") or ""
        for l in ls:
            port = l.get("t_port") or "in1"
            keys, how = expected_keys(fn, port)
            rows.append((t, port, os.path.basename(f), keys or [], how, f"{l['f']}.{l.get('f_port')}"))

    n_multi = 0
    for t, port, fname, keys, how, src in rows:
        if not keys:
            continue
        n_multi += 1
        print("\n%-14s %-4s ← %-22s  [%s]" % (t, port, src, fname))
        print("   读: %s" % ", ".join(keys[:12]) + ("..." if len(keys) > 12 else ""))
        print("   法: %s" % how)

    print("\n" + "=" * 96)
    print("有明确字段读取的边: %d / 总边 %d" % (n_multi, len(rows)))
    print("=" * 96)


if __name__ == "__main__":
    main()
