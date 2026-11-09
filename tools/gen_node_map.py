#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 engineering/node_map.json —— 一个节点对应三层位置, 一处查全。

老倪 2026-11-10 定的分层:
    policies/            算法       纯计算, 不知道节点、不知道总线
    middleware/nodes/    节点契约   端口/话题/执行口径 (PURE 闸) → 调 registry 的实现
    engineering/nodes/   节点实现   取数 → 调算法 → 打标 (这就是"桥梁"那一层)
    engineering/{levels,registry,runtime,flows}   L1~L5 分层与派发

以前右键只能打开其中一处 (契约), 实现藏在 registry 里没人知道在哪 ——
本文件把三层钉成一张表: node_id → {contract, impl, algo} 都是 绝对路径:行号。

用法: python tools/gen_node_map.py [--check]
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MID = SRC / "lerobot/middleware/nodes"
OUT = SRC / "lerobot/engineering/node_map.json"


def parse_adapter(p: Path) -> dict:
    """从节点契约文件里读出 NODE_ID / IMPL_KEY / SOURCE / 端口。"""
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        return {}
    got = {}
    for n in tree.body:
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id in ("NODE_ID", "IMPL_KEY", "SOURCE", "NAME",
                                                    "PORTS_IN", "PORTS_OUT", "PURE", "TYPE"):
                try:
                    got[t.id] = ast.literal_eval(n.value)
                except Exception:                                        # noqa: BLE001
                    pass
    if not got.get("IMPL_KEY"):
        return {}
    return {"node_id": got.get("NODE_ID") or p.stem, "name": got.get("NAME"),
            "impl_key": got.get("IMPL_KEY"), "algo": got.get("SOURCE"),
            "ports_in": got.get("PORTS_IN"), "ports_out": got.get("PORTS_OUT"),
            "pure": got.get("PURE"), "type": got.get("TYPE"),
            "contract_file": "src/lerobot/middleware/nodes/%s" % p.name}


def registry_locations() -> dict:
    sys.path.insert(0, str(SRC))
    import lerobot.middleware.nodes.impl.shared_runtime  # noqa: F401  (导入即注册)
    from lerobot.engineering import registry
    out = {}
    for k, v in registry.NODE_LOGIC.items():
        f = v.get("file") or ""
        out[k] = {"impl": f.replace(str(ROOT) + "/", "") if f else None,
                  "line": v.get("line")}
    return out


def layers() -> dict:
    sys.path.insert(0, str(SRC))
    from lerobot.engineering.layers.by_level import LEVELS_INDEX
    out = {}
    for lv, rows in LEVELS_INDEX.items():
        for r in rows:
            if len(r) >= 3 and r[2]:
                out[r[2]] = lv
    return out


def rel(p: str | None) -> str | None:
    if not p:
        return None
    return p.replace(str(ROOT) + "/", "")


def build() -> dict:
    reg = registry_locations()
    lv = layers()
    nodes = {}
    for p in sorted(MID.glob("n_*.py")):
        a = parse_adapter(p)
        if not a:
            continue
        key = a["impl_key"]
        r = reg.get(key) or {}
        nodes[a["node_id"]] = {
            "name": a.get("name"),
            "impl_key": key,
            "layer": lv.get(key),
            "contract": a["contract_file"] + ":1",
            "impl": (r.get("impl") or "?") + (":%s" % r["line"] if r.get("line") else ""),
            "algo": (rel(a.get("algo")) or "?") + ":1",
            "ports_in": a.get("ports_in"), "ports_out": a.get("ports_out"),
            "pure": a.get("pure"),
        }
    return nodes


def main():
    nodes = build()
    doc = {"note": "一节点三处: contract(契约/端口) · impl(编排实现) · algo(算法)。"
                   "由 tools/gen_node_map.py 生成。",
           "layers": {"policies": "算法 (纯计算)", "middleware/nodes": "节点契约 (端口/总线/执行口径)",
                      "engineering/nodes": "节点实现 (取数→算法→打标)",
                      "engineering": "L1~L5 分层 + 注册表 + 派发 + 画布真源"},
           "nodes": nodes}
    text = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True)
    if "--check" in sys.argv:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        print("CHANGED" if old != text else "SAME")
        return
    OUT.write_text(text, encoding="utf-8")
    miss = [k for k, v in nodes.items() if "?" in (v["impl"] + v["algo"])]
    print("节点", len(nodes), "→", OUT.relative_to(ROOT))
    print("三层都齐", len(nodes) - len(miss), "· 缺", len(miss), miss[:6])


if __name__ == "__main__":
    main()
