#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成状态空间的**每个节点的模块** → src/lerobot/middleware/nodes/<n_id>.py

为什么是生成物: 节点/端口/连线以工程 JSON 为唯一真源。JSON 变了(加节点、改接线),
跑一次本工具就把模块补齐/更新, 手写 75 个文件必然漂移。

生成物里**看得见的东西**(右键打开就是它):
    PORTS_IN / PORTS_OUT   端口清单 + 每个端口的上游/下游 (**从工程 JSON 的连线推出**)
    IMPL_KEY / SOURCE      实现绑定与真实源码位置
    compute(ctx)           输入输出代码本体: ctx 来自总线, 返回值发回总线
    PURE                   False = 只走数据面(直通), 不自动执行实现 (红线见下)

红线: 会动设备的节点 (EXEC_MODE=act) 与未逐一验证口径的节点, PURE 恒为 False ——
      不许在无人授权时跑动作实现。要开某个节点的计算面: 把它改成 True 并配判据。

用法:
    ./gui-venv311/bin/python tools/gen_middleware_nodes.py            # 生成/更新
    ./gui-venv311/bin/python tools/gen_middleware_nodes.py --check    # 只校验(幂等), 有漂移 exit 3
    ./gui-venv311/bin/python tools/gen_middleware_nodes.py --list     # 列节点
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

HEADER = '''# -*- coding: utf-8 -*-
"""%NAME%  ·  节点 %ID%%LAYER%

工程连线 (真源 flows/state_space_obs.json —— 端口就是从这些线推出来的):
%WIRING%

输出 / 输入代码:
    ctx[port] = {"value": …, "age_s": …, "fresh": bool}     ← 从总线取 (bus.latest)
    返回 {输出端口: 值}                                      → 发回总线 (bus.publish)
话题 =  ss.node.%ID%.<port>%BUSNOTE%

实现绑定: %IMPL%
执行口径: EXEC_MODE=%MODE% · PURE=%PURE_INIT% %PURE_NOTE%
"""
'''


def _ports_doc(spec, links):
    up, down = {}, {}
    for l in links or []:
        if l["t"] == spec.id:
            up.setdefault(l["t_port"], []).append(l["f"])
        if l["f"] == spec.id:
            down.setdefault(l["f_port"], []).append(l["t"])
    rows = []
    for p in spec.inputs:
        srcs = up.get(p) or []
        rows.append("    in  %-5s ← %s" % (p, ", ".join(srcs) if srcs else "(工程外注入/无上游)"))
    for p in spec.outputs:
        dsts = down.get(p) or []
        rows.append("    out %-5s → %s" % (p, ", ".join(dsts) if dsts else "(未被下游读取)"))
    return "\n".join(rows) if rows else "    (无端口)"


def render(spec, links=None, bus_note=""):
    impl = ("registry key=`%s`" % spec.impl_key) if spec.impl_key else "(未绑定注册表实现)"
    if spec.source:
        impl += " · %s%s" % (spec.source, (":" + spec.source_symbol) if spec.source_symbol else "")
    pure_init = "False"
    pure_note = ("(会动设备: 只走数据面, 需 8793 授权后由引擎执行)"
                 if spec.exec_mode == "act" else "(数据面直通; 逐个验证口径后再置 True)")
    body = HEADER
    body = body.replace("%NAME%", spec.name or spec.id)
    body = body.replace("%ID%", spec.id)
    body = body.replace("%LAYER%", (" · " + spec.layer) if spec.layer else "")
    body = body.replace("%WIRING%", _ports_doc(spec, links))
    body = body.replace("%BUSNOTE%", bus_note)
    body = body.replace("%IMPL%", impl)
    body = body.replace("%MODE%", spec.exec_mode)
    body = body.replace("%PURE_INIT%", pure_init)
    body = body.replace("%PURE_NOTE%", pure_note)
    body += '''
NODE_ID = %r
NAME = %r
LAYER = %r
TYPE = %r
EXEC_MODE = %r

# 输入端口 (从总线取) / 输出端口 (发到总线) —— 与工程 JSON 的连线一一对应
PORTS_IN = %r
PORTS_OUT = %r
PORT_LABELS = %r

IMPL_KEY = %r
SOURCE = %r
SOURCE_SYMBOL = %r
PARAMS = %r

# 计算面开关: False = 只走数据面(直通 outN←inN), 不自动执行实现
PURE = False
LAST_STATUS = ""


def manifest():
    """给画布/面板: 这个节点的输入输出与实现位置。"""
    return {
        "id": NODE_ID, "name": NAME, "layer": LAYER, "exec_mode": EXEC_MODE,
        "ports_in": list(PORTS_IN), "ports_out": list(PORTS_OUT),
        "impl_key": IMPL_KEY, "source": SOURCE, "source_symbol": SOURCE_SYMBOL,
        "pure": PURE,
    }


def _passthrough(ctx):
    """默认数据面: out1←in1, out2←in2 … (端口序号对齐); 缺输入 → None。"""
    outs = {}
    for i, op in enumerate(PORTS_OUT):
        ip = PORTS_IN[i] if i < len(PORTS_IN) else None
        outs[op] = (ctx.get(ip) or {}).get("value") if ip else None
    return outs


def compute(ctx):
    """一个周期: ctx 来自总线 → 返回要发回总线的输出。

    PURE=False 时只做直通 (数据面), 不调用真实现 —— 避免未验证/未授权的节点被自动执行。
    """
    global LAST_STATUS
    if not PURE:
        LAST_STATUS = "直通 (PURE=False: 只走数据面)"
        return _passthrough(ctx)
    try:
        from lerobot.engineering import registry as _reg
        info = _reg.get(IMPL_KEY) or {}
        fn = info.get("fn")
        if not callable(fn):
            LAST_STATUS = "直通 (实现未注册: %s)" % IMPL_KEY
            return _passthrough(ctx)
        try:
            res = fn(ctx)                       # 约定: 接 ctx 的实现
        except TypeError:
            res = fn()                          # 老实现: 无参
        if isinstance(res, dict):
            LAST_STATUS = "实现执行"
            return {k: v for k, v in res.items() if k in PORTS_OUT}
        LAST_STATUS = "实现返回非 dict → 直通"
        return _passthrough(ctx)
    except Exception as e:                                          # noqa: BLE001
        LAST_STATUS = "实现异常(%s: %s) → 直通" % (type(e).__name__, e)
        return _passthrough(ctx)
'''
    # 尾部代码块里的占位符用字符串替换(不能走 % 格式化: 代码里本身含 %s)
    for tok, val in (
        ("NODE_ID = %r", "NODE_ID = " + repr(spec.id)),
        ("NAME = %r", "NAME = " + repr(spec.name)),
        ("LAYER = %r", "LAYER = " + repr(spec.layer)),
        ("TYPE = %r", "TYPE = " + repr(spec.type)),
        ("EXEC_MODE = %r", "EXEC_MODE = " + repr(spec.exec_mode)),
        ("PORTS_IN = %r", "PORTS_IN = " + repr(list(spec.inputs))),
        ("PORTS_OUT = %r", "PORTS_OUT = " + repr(list(spec.outputs))),
        ("PORT_LABELS = %r", "PORT_LABELS = " + repr(dict(spec.port_labels or {}))),
        ("IMPL_KEY = %r", "IMPL_KEY = " + repr(spec.impl_key or "")),
        ("SOURCE = %r", "SOURCE = " + repr(spec.source or "")),
        ("SOURCE_SYMBOL = %r", "SOURCE_SYMBOL = " + repr(spec.source_symbol or "")),
        ("PARAMS = %r", "PARAMS = " + repr(dict(spec.params or {}))),
    ):
        body = body.replace(tok, val)
    body = body.lstrip("\n")
    return body


INDEX_HEAD = '''# -*- coding: utf-8 -*-
"""节点模块索引 (生成物 · 由 tools/gen_middleware_nodes.py 维护, 别手改)。

一个节点一个模块: 打开某个节点 = 打开这里的对应文件, 端口/连线/实现位置都在文件头。
"""
NODE_MODULES = {
'''
INDEX_TAIL = '''}

BY_NAME = {}


def module_for(node_id):
    """节点 id → 模块全名 (import 用)。"""
    return NODE_MODULES.get(node_id)
'''


def generate(specs, links=None, quiet=True, nodes_dir=None):
    """写 nodes/*.py + _index.py。返回 {"written":n,"unchanged":n,"removed":[...]}"""
    import importlib
    nodes_dir = nodes_dir or os.path.join(SRC, "lerobot", "middleware", "nodes")
    os.makedirs(nodes_dir, exist_ok=True)
    bus_note = ""
    written = unchanged = 0
    names = set()
    for s in specs:
        fn = os.path.join(nodes_dir, "%s.py" % s.module_name)
        names.add(os.path.basename(fn))
        txt = render(s, links=links, bus_note=bus_note)
        old = None
        if os.path.isfile(fn):
            with open(fn, encoding="utf-8") as f:
                old = f.read()
        if old == txt:
            unchanged += 1
            continue
        with open(fn, "w", encoding="utf-8") as f:
            f.write(txt)
        written += 1
        if not quiet:
            print("  ✍ %s" % os.path.relpath(fn, ROOT))
    # 索引
    idx = INDEX_HEAD
    for s in sorted(specs, key=lambda x: x.id):
        idx += "    %r: %r,\n" % (s.id, "lerobot.middleware.nodes.%s" % s.module_name)
    idx += INDEX_TAIL
    idx += "\nBY_NAME.update({%s})\n" % ", ".join(
        "%r: %r" % (s.name, s.id) for s in specs)
    ifn = os.path.join(nodes_dir, "_index.py")
    old = open(ifn, encoding="utf-8").read() if os.path.isfile(ifn) else None
    if old != idx:
        with open(ifn, "w", encoding="utf-8") as f:
            f.write(idx)
        written += 1
    # 清掉不再存在的节点模块 (只删本工具生成的 n_*.py)
    removed = []
    for fn in sorted(os.listdir(nodes_dir)):
        if fn.startswith("n_") and fn.endswith(".py") and fn not in names:
            os.remove(os.path.join(nodes_dir, fn))
            removed.append(fn)
    if not quiet:
        print("🧩 节点模块: 写 %d · 未变 %d · 删 %d → %s"
              % (written, unchanged, len(removed), os.path.relpath(nodes_dir, ROOT)))
    return {"written": written, "unchanged": unchanged, "removed": removed}


def check(specs, links=None, nodes_dir=None):
    nodes_dir = nodes_dir or os.path.join(SRC, "lerobot", "middleware", "nodes")
    drift = []
    for s in specs:
        fn = os.path.join(nodes_dir, "%s.py" % s.module_name)
        want = render(s, links=links)
        if not os.path.isfile(fn):
            drift.append("%s.py 缺失" % s.module_name)
        elif open(fn, encoding="utf-8").read() != want:
            drift.append("%s.py 与工程 JSON 不一致" % s.module_name)
    idxf = os.path.join(nodes_dir, "_index.py")
    if not os.path.isfile(idxf):
        drift.append("_index.py 缺失")
    return drift


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--canvas", default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    from lerobot.middleware import spec as spec_mod
    specs, links, meta = spec_mod.parse_canvas(a.canvas)
    if a.list:
        for s in specs:
            print("%-11s %-30s in=%s out=%s impl=%s [%s]"
                  % (s.id, (s.name or "")[:30], ",".join(s.inputs),
                     ",".join(s.outputs), s.impl_key or "-", s.exec_mode))
        print("\n节点 %d · 连线 %d · 已绑定实现 %d"
              % (meta["nodes"], meta["links"], meta["impl_bound"]))
        return 0
    if a.check:
        drift = check(specs, links)
        if drift:
            print("❌ 节点模块漂移 %d 处:" % len(drift))
            for d in drift:
                print("   -", d)
            print("   修: ./gui-venv311/bin/python tools/gen_middleware_nodes.py")
            return 3
        print("✅ 节点模块与工程 JSON 一致 (%d 个)" % len(specs))
        return 0
    r = generate(specs, links, quiet=a.quiet or False)
    print("🧩 生成完成: 写 %d · 未变 %d · 删 %d (节点 %d)"
          % (r["written"], r["unchanged"], len(r["removed"]), len(specs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
