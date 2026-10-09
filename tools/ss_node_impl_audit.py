#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全面检查状态空间工程「每个节点的实现」+ 单步执行序 (老倪 2026-10-09)

老倪: 「我要全面检查状态空间工程的每个节点的实现, 现在我需要单步运行, 运行到哪个节点,
       哪个节点要高亮显示, 而且画布要跳到这个节点 —— 画布太大了, 找不到单步节点在哪」

本工具把**画布上每个节点 == 哪段代码实现的**逐条查出来 (可核对), 并给出 GUI ⏭单步 的执行序:
    · 实现真源: engineering.registry (节点名→语义 key→函数) + sourceview (含 _EXTERNAL_LOC 外部源)
    · 单步序判据: 与 GUI `SimulinkModule._ss_*` **同一份逻辑** (本脚本优先直接调用 GUI 的函数;
      调用不到才用内联副本, 并在输出里注明用了哪条) —— row_bg / 能力档位开关 / 观察器 三类排除

用法:
    python3 tools/ss_node_impl_audit.py                 # 全表 + 汇总 (默认 L2 档单步序)
    python3 tools/ss_node_impl_audit.py --level L4      # 按 L4 档算单步序
    python3 tools/ss_node_impl_audit.py --json          # 机器可读
    python3 tools/ss_node_impl_audit.py --write         # 落盘 reports/node_impl_audit.{txt,json}
    python3 tools/ss_node_impl_audit.py --no-code       # 只看清单不看实现 (概览)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _load():
    from lerobot.engineering import flows, registry, sourceview
    d, probs = flows.load_canvas()
    return d, list(probs or []), registry, sourceview


def _is_observer(node):
    p = node.get("params", {}) or {}
    return bool(p.get("viz_kind") or p.get("verif_layer"))


def _level_from_rows(node, nodes):
    """节点所属功能层级 (按所在 row_bg 色带) —— 与 GUI `_ss_node_cap_level` 同逻辑"""
    y = node.get("y", 0)
    for b in nodes:
        if b.get("type") != "row_bg":
            continue
        by = b.get("y", 0)
        if by <= y < by + b.get("h", 0):
            nm = b.get("name", "")
            for lv, s in ((4, "L4"), (3, "L3"), (2, "L2")):
                if s in nm:
                    return lv
            return 0
    return 0


def _gui_predicates():
    """优先用 GUI 的真函数 (同一个判据), 失败返回 None"""
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
        import types
        import simulink_module as sm
        C = sm.SimulinkModule

        def level(node, nodes, _C=C):
            return _C._ss_node_cap_level(types.SimpleNamespace(nodes=nodes), node)

        def observer(node, _C=C):
            return _C._ss_is_observer(types.SimpleNamespace(nodes=[]), node)

        return level, observer
    except Exception:  # noqa: BLE001
        return None


def audit(level_key="L2"):
    d, probs, registry, sourceview = _load()
    nodes = d.get("nodes") or []
    cap = {"L2": 2, "L3": 3, "L4": 4, "L5": 5}.get(str(level_key).upper(), 2)
    gp = _gui_predicates()
    if gp:
        _lv, _obs = gp
        rule_src = "GUI 同源 (SimulinkModule._ss_*)"
    else:
        _lv, _obs = (lambda n, ns: _level_from_rows(n, ns)), (lambda n: _is_observer(n))
        rule_src = "内联副本 (GUI 模块不可导入)"
    rows, agreed, mism = [], 0, []
    keys_used = {}
    for i, n in enumerate(nodes, 1):
        is_bg = n.get("type") == "row_bg"
        name = n.get("name", "")
        key = None if is_bg else registry.match_node(name)
        fn = (registry.get(key) or {}).get("fn") if key else None
        fname = getattr(fn, "__name__", "")
        path = line = None
        if key:
            path, line, modified = sourceview.get_node_location(key)
            if not path:
                path, line = registry.home_file(key), registry.home_line(key)
            keys_used[key] = keys_used.get(key, 0) + 1
        else:
            modified = False
        lv = _lv(n, nodes) if not is_bg else None
        if gp and not is_bg:      # 交叉核对: 内联副本 vs GUI 真函数
            same = (_level_from_rows(n, nodes) == lv) and (_is_observer(n) == _obs(n))
            agreed += 1 if same else 0
            if not same:
                mism.append(n.get("id"))
        sw_cap = n.get("params", {}).get("cap_switch")
        obs = _obs(n) if not is_bg else None
        step_in = (not is_bg) and (not sw_cap) and (not obs) and (lv is not None) and (lv <= cap)
        rel = None
        if path:
            try:
                rel = os.path.relpath(path, ROOT)
            except Exception:  # noqa: BLE001
                rel = path
        rows.append({"i": i, "id": n.get("id"), "type": n.get("type"), "name": name,
                     "key": key, "fn": fname, "file": rel, "line": line, "modified": bool(modified),
                     "level": lv, "observer": obs, "cap_switch": bool(sw_cap),
                     "step_in": bool(step_in), "bg": is_bg})
    funcs = [r for r in rows if not r["bg"]]
    hit = [r for r in funcs if r["key"]]
    return {
        "_meta": {"canvas": "src/lerobot/engineering/flows/state_space_obs.json",
                  "nodes": len(nodes), "functional": len(funcs), "background": len(nodes) - len(funcs),
                  "impl_hit": len(hit), "impl_miss": len(funcs) - len(hit),
                  "level_for_step": str(level_key).upper(),
                  "step_nodes": sum(1 for r in funcs if r["step_in"]),
                  "shared_keys": {k: v for k, v in keys_used.items() if v > 1},
                  "rule_source": rule_src, "rule_cross_checked": agreed, "rule_mismatch": mism,
                  "problems": probs},
        "nodes": rows,
    }


def render(doc, show_code=True):
    m = doc["_meta"]
    out = []
    out.append("状态空间工程 · 逐节点实现审计")
    out.append("真源: %s · 校验 %s" % (m["canvas"], "✅ 通过" if not m["problems"] else m["problems"][:2]))
    out.append("节点 %d (功能 %d / 背景 %d) · 实现命中 %d/%d · 未命中 %d"
               % (m["nodes"], m["functional"], m["background"], m["impl_hit"], m["functional"], m["impl_miss"]))
    out.append("单步序 (档 %s): %d 节点会执行 · 判据来源: %s"
               % (m["level_for_step"], m["step_nodes"], m["rule_source"]))
    if m["rule_cross_checked"]:
        out.append("判据交叉核对: %d 个功能节点内联副本 == GUI 真函数%s"
                   % (m["rule_cross_checked"], " ✅" if not m["rule_mismatch"] else " ❌ " + str(m["rule_mismatch"])))
    if m["shared_keys"]:
        out.append("同 key 多节点: %s" % m["shared_keys"])
    out.append("")
    hdr = "%-4s %-15s %-20s %-9s %-26s %-5s %s" % ("#", "id", "名称", "层级", "实现 key", "单步", "实现位置")
    out.append(hdr)
    out.append("-" * len(hdr))
    for r in doc["nodes"]:
        nm = r["name"]
        nm = nm if len(nm) <= 20 else nm[:19] + "…"
        lv = "背景" if r["bg"] else ("L%d" % r["level"] if r["level"] else "基础")
        st = "✔" if r["step_in"] else ("·" if not r["bg"] else " ")
        if not show_code:
            out.append("%-4d %-15s %-20s %-9s %-26s %-5s" % (r["i"], r["id"], nm, lv, r["key"] or "—", st))
            continue
        loc = ("%s:%s" % (r["file"], r["line"])) if r["key"] else (
            "⚠️ 无匹配实现" if not r["bg"] else "(背景行条)")
        if r["modified"]:
            loc += " [已改版]"
        if r["observer"]:
            loc += " (观察器·单步跳过)"
        if r["cap_switch"]:
            loc += " (档位开关·单步跳过)"
        out.append("%-4d %-15s %-20s %-9s %-26s %-5s %s"
                   % (r["i"], r["id"], nm, lv, r["key"] or "—", st, loc))
    out.append("")
    out.append("说明: 单步列 ✔ = GUI ⏭单步 会执行并高亮+画布跳转; · = 该档位不执行 (更高档功能);")
    out.append("      层级 = 所在 row_bg 色带 (L2/L3/L4; 基础=数据源/大模型/回路外);")
    out.append("      观察器/档位开关按老倪 2026-09-09 口径从单步链排除 (执行=弹窗轰炸/切档副作用)。")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="L2")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-code", action="store_true")
    a = ap.parse_args()
    doc = audit(a.level)
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(render(doc, show_code=not a.no_code))
    if a.write:
        d = os.path.join(ROOT, "reports")
        os.makedirs(d, exist_ok=True)
        txt_p, js_p = os.path.join(d, "node_impl_audit.txt"), os.path.join(d, "node_impl_audit.json")
        with open(txt_p, "w", encoding="utf-8") as f:
            f.write(render(doc, show_code=True) + "\n")
        with open(js_p, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print("\n→ %s\n→ %s" % (txt_p, js_p))
    m = doc["_meta"]
    return 0 if (not m["problems"] and m["impl_miss"] == 0 and not m["rule_mismatch"]) else 2


if __name__ == "__main__":
    sys.exit(main())
