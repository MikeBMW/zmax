#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arch_graph.py — 只读「架构图数据」导出工具 (Z-MAX 控制台 · 系统架构页 / 配置中心页 的数据源)

老倪: 「把单一工程库里的 平台 → 系统 → 功能 → 模块/代码 层级, 以及
       功能 ↔ 配置/标定/诊断(三轴) ↔ 参数数值 的关联, 导成结构化 JSON, 供控制台直接渲染。」

本工具**只读** (sqlite uri `?mode=ro`), 不改任何真源/库。全部数字从库里现算, 不写死 —— 
最终答复里每个计数都能用同一库复算。

层级 (layer, 主链 0-7):
  0 平台 platform           (platform 表)
  1 产品 product            (products 表)
  2 产品特征 product_feature (product_features 表)
  3 子系统 subsystem         (subsystems 表; 含 sys0/sys1/sys2/plat 四行)
  4 功能 function            (functions 表, 74)
  5 模块 module              (modules 表, 74)
  6 代码 module_code         (module_code 表, 74 → 绝对路径文件 + 行号)
  7 参数 param               (params 表, 645)
辅助层:
  8 能力 capability          (capability_dbc 表)
  9 接口 interface           (interfaces 表)
 10 验证 verification        (verification_features 表)
 11 真源 source              (params.source 去重后的真源文件)

边 (edges) 全部带 evidence (链接来源表 + 关键字段), 可逐条回库复算。

命令行:
  python3 tools/arch_graph.py                 # 人读摘要 (每层条数 + 交叉链接数)
  python3 tools/arch_graph.py --json          # 结构化 JSON 到 stdout
  python3 tools/arch_graph.py --json-out P    # 结构化 JSON 写文件 P
  python3 tools/arch_graph.py --focus FN-SYS0-01   # 以功能为中心的局部子图
  python3 tools/arch_graph.py --focus sys0         # 以系统为中心的局部子图
  python3 tools/arch_graph.py --check         # 断言 (功能↔模块 0 悬空 / 每功能参数链接数 / 画布口径)
"""
import argparse
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DEFAULT = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
# 画布真源 (89 节点: 74 逻辑节点 + 15 row_bg 背景带 / 184 连线)
CANVAS_DEFAULT = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "state_space_obs.json")

# 主链 + 辅助层的层号与中文名 (控制台按 layer_name 分组, 不依赖数字顺序)
LAYER_NAMES = {
    0: "平台", 1: "产品", 2: "产品特征", 3: "子系统", 4: "功能", 5: "模块",
    6: "代码", 7: "参数", 8: "能力", 9: "接口", 10: "验证", 11: "真源",
}


def open_db(path=DB_DEFAULT):
    """只读打开 —— uri 里带 mode=ro, 物理上杜绝任何写库。"""
    if not os.path.exists(path):
        raise SystemExit("⛔ 工程库不存在: %s" % path)
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _canvas_counts(path=CANVAS_DEFAULT):
    """读画布真源, 报两种口径: JSON 全量节点 (含 row_bg) 与 逻辑节点 (不含 row_bg)。

    为什么要两种: 库 canvas_nodes 只存 74 条逻辑节点 (与 functions 对齐);
    画布 JSON 另有 15 条 row_bg 背景带 ⇒ 89。两个口径都得能对上, 否则控制台画布
    节点数与功能数对不上。缺失文件时全 0 并在摘要里显式标注, 不编造。
    """
    out = {"json_nodes": 0, "json_links": 0, "row_bg": 0, "logical": 0, "exists": False}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                                            # noqa: BLE001
        return out
    nodes = d.get("nodes") or []
    out["json_nodes"] = len(nodes)
    out["json_links"] = len(d.get("links") or [])
    out["row_bg"] = sum(1 for n in nodes if (n.get("type") == "row_bg"))
    out["logical"] = len(nodes) - out["row_bg"]
    out["exists"] = True
    return out


def build(con, canvas_path=CANVAS_DEFAULT):
    """从库现算整张架构图 → {nodes, edges, meta}。每个数都来自 SELECT COUNT/查询。"""
    cur = con.cursor()

    def q(sql, args=()):
        return cur.execute(sql, args).fetchall()

    nodes = {}
    edges = []
    edge_keys = set()

    def N(nid, kind, label, layer, meta):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "label": label, "layer": layer,
                          "meta": dict(meta or {})}
        return nodes[nid]

    def E(src, dst, kind, evidence):
        # 去重: 同一 (src,dst,kind) 多次命中只留一条 (多条 track 命中同一参数时不重复画线)
        key = (src, dst, kind)
        if key in edge_keys:
            # 但把补充证据并进去, 保证"每条边可追溯"不丢来源
            for e in edges:
                if e["src"] == src and e["dst"] == dst and e["kind"] == kind:
                    e["evidence"].setdefault("also", []).append(evidence)
                    break
            return
        edge_keys.add(key)
        edges.append({"src": src, "dst": dst, "kind": kind, "evidence": evidence})

    def src_node(path):
        sid = "source:" + str(path)
        return N(sid, "source", str(path), 11, {"path": path})

    # ── 0 平台 ────────────────────────────────────────────────────────────
    platform_rows = q("SELECT platform_id, name, positioning, architecture, data_contract FROM platform")
    platform_ids = []
    for r in platform_rows:
        pid = "platform:" + str(r["platform_id"])
        platform_ids.append(pid)
        N(pid, "platform", r["name"], 0,
          {"platform_id": r["platform_id"], "positioning": r["positioning"],
           "architecture": r["architecture"], "data_contract": r["data_contract"]})

    # ── 1 产品 (products) ─────────────────────────────────────────────────
    for r in q("SELECT product_id, name, cn, category, positioning, kpi, subsystems, extra FROM products"):
        nid = "product:" + str(r["product_id"])
        N(nid, "product", r["cn"] or r["name"], 1,
          {"product_id": r["product_id"], "category": r["category"], "positioning": r["positioning"],
           "kpi": r["kpi"], "subsystems": r["subsystems"], "extra": r["extra"]})
        # 平台→产品: products 表无显式 platform 外键 (库内单一平台), 证据记 products 表 + 字段
        for pl in platform_ids:
            E(pl, nid, "平台产品",
              {"table": "products", "field": "product_id", "value": r["product_id"],
               "note": "库内单一平台(Z-MAX)下产品; products 表无 platform_id 列"})

    # ── 2 产品特征 (product_features) ─────────────────────────────────────
    for r in q("SELECT pf_id, product_id, title, capability_ref, kpi, status, descr, subsys, module_refs "
               "FROM product_features"):
        nid = "pf:" + str(r["pf_id"])
        N(nid, "product_feature", r["title"], 2,
          {"pf_id": r["pf_id"], "product_id": r["product_id"], "capability_ref": r["capability_ref"],
           "kpi": r["kpi"], "status": r["status"], "descr": r["descr"],
           "subsys": r["subsys"], "module_refs": r["module_refs"]})
        E("product:" + str(r["product_id"]), nid, "产品特征",
          {"table": "product_features", "field": "product_id", "value": r["product_id"], "pf_id": r["pf_id"]})

    # ── 3 子系统 (subsystems) + 三轴定义 (subsystem_axes) ──────────────────
    sys_axes = {}
    for r in q("SELECT system_id, axis, idx, item FROM subsystem_axes"):
        sys_axes.setdefault(r["system_id"], {}).setdefault(r["axis"], []).append(
            {"idx": r["idx"], "item": r["item"]})
    subsystem_level = {}
    for r in q("SELECT system_id, name, level, role, hardware, kpi, rows, ord FROM subsystems"):
        sid = "sys:" + str(r["system_id"])
        subsystem_level[r["system_id"]] = r["level"]
        N(sid, "subsystem", r["name"], 3,
          {"system_id": r["system_id"], "level": r["level"], "role": r["role"],
           "hardware": r["hardware"], "kpi": r["kpi"], "rows": r["rows"], "ord": r["ord"],
           "axes": sys_axes.get(r["system_id"], {})})

    # ── 4 功能 (functions) + 每功能三轴 (fn_axes) ─────────────────────────
    fn_axes = {}
    for r in q("SELECT fn_id, axis, idx, item, src FROM fn_axes"):
        fn_axes.setdefault(r["fn_id"], {}).setdefault(r["axis"], []).append(
            {"idx": r["idx"], "item": r["item"], "src": r["src"]})
    functions = q("SELECT fn_id, system_id, name, layer, kind, row_name, module_ref, source FROM functions")
    for r in functions:
        nid = "fn:" + str(r["fn_id"])
        axes = fn_axes.get(r["fn_id"], {})
        N(nid, "function", r["name"], 4,
          {"fn_id": r["fn_id"], "system_id": r["system_id"], "layer": r["layer"], "kind": r["kind"],
           "row_name": r["row_name"], "module_ref": r["module_ref"], "source": r["source"],
           "axes": {ax: axes.get(ax, []) for ax in ("cfg", "cal", "dia")},
           "axes_count": {ax: len(axes.get(ax, [])) for ax in ("cfg", "cal", "dia")}})
        E("sys:" + str(r["system_id"]), nid, "系统功能",
          {"table": "functions", "field": "system_id", "value": r["system_id"], "fn_id": r["fn_id"]})

    # ── 5 模块 (modules) ─────────────────────────────────────────────────
    module_names = set()
    for r in q("SELECT name, kind, group_name, verif_layer, source FROM modules"):
        module_names.add(r["name"])
        N("mod:" + str(r["name"]), "module", r["name"], 5,
          {"name": r["name"], "kind": r["kind"], "group_name": r["group_name"],
           "verif_layer": r["verif_layer"], "source": r["source"]})

    # 功能→模块 (functions.module_ref 直连; links 表 kind='对应模块' 同源互证)
    link_fn_mod = {(r["src_id"], r["dst_id"]) for r in
                   q("SELECT src_id, dst_id FROM links WHERE src_type='function' AND dst_type='module'")}
    for r in functions:
        dst = "mod:" + str(r["module_ref"])
        E("fn:" + str(r["fn_id"]), dst, "对应模块",
          {"table": "functions", "field": "module_ref", "fn_id": r["fn_id"], "module_ref": r["module_ref"],
           "links_kind": "对应模块" if (r["fn_id"], r["module_ref"]) in link_fn_mod else None})

    # ── 6 代码 (module_code: 模块 → 绝对路径文件 + 行号) ───────────────────
    for r in q("SELECT module_name, logic_key, file, line, doc, match FROM module_code"):
        cid = "code:%s:%s" % (r["file"], r["line"])
        N(cid, "module_code", "%s:%s" % (os.path.basename(str(r["file"])), r["line"]), 6,
          {"module_name": r["module_name"], "logic_key": r["logic_key"], "file": r["file"],
           "line": r["line"], "doc": r["doc"], "match": r["match"]})
        E("mod:" + str(r["module_name"]), cid, "实现",
          {"table": "module_code", "module_name": r["module_name"], "file": r["file"], "line": r["line"]})

    # ── 7 参数 (params) + 真源文件节点 (params.source) ────────────────────
    param_rows = q("SELECT param_id, group_cn, cat, name, cn, value, default_val, min, max, unit, kind, "
                   "choices, source, ref, writable, status, color, sys_id, module_ref, impact FROM params")
    for r in param_rows:
        nid = "param:" + str(r["param_id"])
        N(nid, "param", r["cn"] or r["name"], 7,
          {"param_id": r["param_id"], "group_cn": r["group_cn"], "cat": r["cat"], "name": r["name"],
           "value": r["value"], "default_val": r["default_val"], "min": r["min"], "max": r["max"],
           "unit": r["unit"], "kind": r["kind"], "choices": r["choices"], "source": r["source"],
           "ref": r["ref"], "writable": r["writable"], "status": r["status"], "sys_id": r["sys_id"],
           "module_ref": r["module_ref"], "impact": r["impact"]})
        src_node(r["source"])
        E(nid, "source:" + str(r["source"]), "真源",
          {"table": "params", "field": "source", "param_id": r["param_id"], "source": r["source"]})

    # ── 8 能力 (capability_dbc) ──────────────────────────────────────────
    for r in q("SELECT bo_id, grp, name, dirs, brief, explain, iface, inputs, outputs, scenes, engineering, "
               "owner FROM capability_dbc"):
        N("cap:" + str(r["bo_id"]), "capability", r["name"], 8,
          {"bo_id": r["bo_id"], "grp": r["grp"], "dirs": r["dirs"], "brief": r["brief"],
           "explain": r["explain"], "iface": r["iface"], "inputs": r["inputs"], "outputs": r["outputs"],
           "scenes": r["scenes"], "engineering": r["engineering"], "owner": r["owner"]})

    # ── 9 接口 (interfaces) ──────────────────────────────────────────────
    for r in q("SELECT if_id, owner_type, owner_id, direction, name, note FROM interfaces"):
        N("iface:" + str(r["if_id"]), "interface", str(r["name"])[:60], 9,
          {"if_id": r["if_id"], "owner_type": r["owner_type"], "owner_id": r["owner_id"],
           "direction": r["direction"], "name": r["name"], "note": r["note"]})

    # ── 10 验证 (verification_features) ──────────────────────────────────
    for r in q("SELECT f_id, domain, name, where_, how, case_id, level FROM verification_features"):
        N("verif:" + str(r["f_id"]), "verification", r["name"], 10,
          {"f_id": r["f_id"], "domain": r["domain"], "where": r["where_"], "how": r["how"],
           "case_id": r["case_id"], "level": r["level"]})

    # ── links 表 (通用关联): 产品特征→子系统/模块/能力, 能力→接口, 验证→分级 ──
    for r in q("SELECT src_type, src_id, dst_type, dst_id, kind FROM links"):
        st, si, dt, di, kd = r["src_type"], r["src_id"], r["dst_type"], r["dst_id"], r["kind"]
        ev = {"table": "links", "src_type": st, "src_id": si, "dst_type": dt, "dst_id": di, "kind": kd}
        if st == "product_feature" and dt == "subsystem":
            E("pf:" + si, "sys:" + di, "归属", ev)
        elif st == "product_feature" and dt == "module":
            E("pf:" + si, "mod:" + di, "用到", ev)
        elif st == "product_feature" and dt == "capability":
            E("pf:" + si, "cap:" + di, "能力引用", ev)
        elif st == "capability" and dt == "interface":
            E("cap:" + si, "iface:" + di, "接口", ev)
        elif st == "verification" and dt == "level":
            # 分级: links dst 是档位串 (L2/L3/L4/L5), 按 subsystems.level 反查子系统
            sysid = None
            for sid2, lv in subsystem_level.items():
                if lv and di in str(lv):
                    sysid = sid2
                    break
            if sysid:
                E("verif:" + si, "sys:" + sysid, "验证分级",
                  dict(ev, level=di, subsystem=sysid, table_level="subsystems.level"))

    # ── 功能 ↔ 参数 (三条 track, 每条都记链接来源) ────────────────────────
    # 索引: param_links 的 功能/系统 两类目标; 画布参数按 ref 里的节点名反查
    pl_fn, pl_sys = {}, {}
    for r in q("SELECT param_id, kind, target FROM param_links"):
        if r["kind"] == "功能":
            pl_fn.setdefault(r["target"], []).append(r["param_id"])
        elif r["kind"] == "系统":
            pl_sys.setdefault(r["target"], []).append(r["param_id"])
    canvas_ref = {}
    for r in param_rows:
        if r["group_cn"] == "画布节点数据":
            m = re.match(r"canvas:(.*)\.params\.", str(r["ref"] or ""))
            if m:
                canvas_ref.setdefault(m.group(1), []).append(r["param_id"])
    for r in functions:
        fnid, sid, mref = r["fn_id"], r["system_id"], r["module_ref"]
        src = "fn:" + str(fnid)
        # track A: param_links kind='功能' target==fn_id  (精确; 号位/空间点 → FN-SYS0-59)
        for pid in pl_fn.get(fnid, []):
            E(src, "param:" + phi(pid), "功能参数",
              {"table": "param_links", "kind": "功能", "target": fnid, "param_id": pid,
               "link_source": "param_links:功能"})
        # track B: 画布节点数据 参数 (ref='canvas:<节点名>.params.*') 节点名 == 功能 module_ref
        for pid in canvas_ref.get(mref, []):
            E(src, "param:" + phi(pid), "功能参数",
              {"table": "params", "field": "ref", "param_id": pid, "matched_node": mref,
               "link_source": "params.ref:画布节点"})
        # track C: param_links kind='系统' target==功能 system_id (系统级口径; 广域关联)
        for pid in pl_sys.get(sid, []):
            E(src, "param:" + phi(pid), "功能参数",
              {"table": "param_links", "kind": "系统", "target": sid, "param_id": pid,
               "link_source": "param_links:系统", "scope": "system"})

    # 产品/性能指标参数 → 产品特征 (params.module_ref 存的是 pf_id)
    for r in param_rows:
        if r["group_cn"] == "产品/性能指标" and r["module_ref"]:
            E("pf:" + str(r["module_ref"]), "param:" + phi(r["param_id"]), "性能指标",
              {"table": "params", "field": "module_ref", "param_id": r["param_id"],
               "pf_id": r["module_ref"]})

    # 排序 (确定性输出)
    node_list = sorted(nodes.values(), key=lambda n: (n["layer"], n["id"]))
    edge_list = sorted(edges, key=lambda e: (e["kind"], e["src"], e["dst"]))
    meta = {
        "schema": "zmax-arch-graph/1.0",
        "db": os.path.relpath(DB_DEFAULT, ROOT),
        "canvas_json": os.path.relpath(canvas_path, ROOT),
        "layer_names": LAYER_NAMES,
        "counts": {
            "nodes": len(node_list),
            "edges": len(edge_list),
        },
    }
    return {"nodes": node_list, "edges": edge_list, "meta": meta}


def phi(param_id):
    """param_id 原样 (用于构造 param: 节点 id)。保留函数名以便将来加前缀规则。"""
    return str(param_id)


# 子图 (--focus) ────────────────────────────────────────────────────────
# 上游只沿"架构脊柱"上行 (系统功能/归属/产品特征/平台产品), 下游只沿"归属/参数/代码"下行。
# 为什么: 若把"验证分级"(57 条汇入子系统)也算进来, 一个功能会把整个子系统的验证都拖进来,
# 局部子图就退化成全图 —— focus 要的是"这一点从哪来、到哪去", 不是同层兄弟。
_FOCUS_UP = {"系统功能", "归属", "产品特征", "平台产品"}
# 系统功能 同时在下行集合: 以系统为中心时要能往下展开到它的功能 (功能为中心时该边是入边, 不受影响)
_FOCUS_DOWN = {"系统功能", "对应模块", "实现", "功能参数", "性能指标", "真源", "用到", "能力引用", "接口"}


def subgraph(graph, key):
    """以某功能/系统为中心取局部子图: 上游(祖先) + 下游(后代)。

    方向语义: 边按库内自然方向 (平台→…→参数)。上游 = 反复沿**脊柱**入边回溯;
    下游 = 反复沿**归属/参数**出边前进。
    """
    by_id = {n["id"]: n for n in graph["nodes"]}
    outs, ins = {}, {}
    for e in graph["edges"]:
        outs.setdefault(e["src"], []).append(e)
        ins.setdefault(e["dst"], []).append(e)

    if key.startswith("fn:") or key.startswith("FN-"):
        center = key if key.startswith("fn:") else "fn:" + key
    elif key.startswith("sys:") or key in ("sys0", "sys1", "sys2", "plat"):
        center = key if key.startswith("sys:") else "sys:" + key
    else:
        return None
    if center not in by_id:
        return None

    keep_nodes, keep_edges = {center}, []
    stack = [center]
    seen = set()
    while stack:                                     # 上游回溯 (仅脊柱)
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for e in ins.get(cur, []):
            if e["kind"] not in _FOCUS_UP:
                continue
            keep_nodes.add(e["src"])
            keep_edges.append(e)
            stack.append(e["src"])
    stack = [center]
    seen = set()
    while stack:                                     # 下游前进 (归属/参数/代码)
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for e in outs.get(cur, []):
            if e["kind"] not in _FOCUS_DOWN:
                continue
            keep_nodes.add(e["dst"])
            keep_edges.append(e)
            stack.append(e["dst"])

    nodes = [by_id[i] for i in keep_nodes]
    uniq = {}
    for e in keep_edges:
        uniq[(e["src"], e["dst"], e["kind"])] = e
    edges = list(uniq.values())
    nodes.sort(key=lambda n: (n["layer"], n["id"]))
    edges.sort(key=lambda e: (e["kind"], e["src"], e["dst"]))
    return {"focus": center, "nodes": nodes, "edges": edges,
            "meta": dict(graph["meta"], counts={"nodes": len(nodes), "edges": len(edges)},
                         focus=center)}


# ── 人读摘要 ──────────────────────────────────────────────────────────────
def summarize(graph, con, canvas_path=CANVAS_DEFAULT):
    nodes, edges = graph["nodes"], graph["edges"]
    cur = con.cursor()

    def n1(sql):
        return cur.execute(sql).fetchone()[0]

    by_layer = {}
    by_kind = {}
    for n in nodes:
        by_layer[n["layer"]] = by_layer.get(n["layer"], 0) + 1
        by_kind[n["kind"]] = by_kind.get(n["kind"], 0) + 1
    eby = {}
    for e in edges:
        eby[e["kind"]] = eby.get(e["kind"], 0) + 1

    print("Z-MAX 架构图数据 (只读)   库=%s   建库时间=%s" % (
        graph["meta"]["db"], n1("SELECT v FROM meta WHERE k='built_at'")))
    print("─" * 78)
    print("【层级 · 每层条数】(真源: 库表 COUNT)")
    tbl_for = {0: "platform", 1: "products", 2: "product_features", 3: "subsystems",
               4: "functions", 5: "modules", 6: "module_code", 7: "params",
               8: "capability_dbc", 9: "interfaces", 10: "verification_features"}
    for layer in sorted(by_layer):
        t = tbl_for.get(layer, "params.source(去重)" if layer == 11 else "-")
        print("  L%-2d %-6s %5d 节点   (库表 %s=%d)" % (
            layer, LAYER_NAMES.get(layer, "?"), by_layer[layer], t,
            n1("SELECT COUNT(*) FROM %s" % t) if layer != 11 else n1("SELECT COUNT(DISTINCT source) FROM params")))
    print("  ── 节点合计: %d" % len(nodes))

    print("\n【边 · 交叉链接数】(真源: 逐边 evidence 可回库复算)")
    order = ["平台产品", "产品特征", "归属", "用到", "能力引用", "接口", "系统功能",
             "对应模块", "实现", "性能指标", "功能参数", "真源", "验证分级"]
    for k in order:
        if k in eby:
            print("  %-8s %5d" % (k, eby[k]))
    for k in sorted(eby):
        if k not in order:
            print("  %-8s %5d" % (k, eby[k]))
    print("  ── 边合计: %d" % len(edges))

    # 功能↔参数 track 细分
    tracks = {}
    fns_with_param = set()
    for e in edges:
        if e["kind"] == "功能参数":
            ls = e["evidence"].get("link_source", "?")
            tracks[ls] = tracks.get(ls, 0) + 1
            fns_with_param.add(e["src"])
    print("\n【功能 ↔ 参数 链接细分】(经 param_links / 画布 ref)")
    for k in sorted(tracks):
        print("  %-24s %5d" % (k, tracks[k]))
    print("  ── 有参数链接的功能: %d/%d" % (len(fns_with_param), n1("SELECT COUNT(*) FROM functions")))

    # 画布口径
    cc = _canvas_counts(canvas_path)
    print("\n【画布口径 (两种)】")
    print("  库 canvas_nodes = %d (逻辑节点, 与 functions 对齐)" % n1("SELECT COUNT(*) FROM canvas_nodes"))
    if cc["exists"]:
        print("  画布 JSON nodes = %d  (= %d 逻辑节点 + %d row_bg 背景带)   links = %d" % (
            cc["json_nodes"], cc["logical"], cc["row_bg"], cc["json_links"]))
    else:
        print("  ⚠️ 画布 JSON 缺失: %s" % canvas_path)
    print("  canvas_links(库) = %d" % n1("SELECT COUNT(*) FROM canvas_links"))
    print("─" * 78)
    print("提示: --json 取结构化 / --focus <fn_id|sys_id> 取局部子图 / --check 跑判据")


# ── 校验 ─────────────────────────────────────────────────────────────────
def check(graph, con):
    """3 条断言: ①功能↔模块 0 悬空 ②每个功能的参数链接数 ③画布口径与功能数一致。"""
    cur = con.cursor()
    fails = []

    def ok(c, msg):
        print(("  ✅ " if c else "  ❌ ") + msg)
        if not c:
            fails.append(msg)

    # ① 功能↔模块 0 悬空
    fn_rows = cur.execute("SELECT fn_id, module_ref FROM functions").fetchall()
    mod_names = {r[0] for r in cur.execute("SELECT name FROM modules")}
    dangling = [r[0] for r in fn_rows if r[1] not in mod_names]
    n_fn = len(fn_rows)
    print("① 功能↔模块 悬空检查")
    ok(len(dangling) == 0, "功能 %d 个, module_ref 全部命中 modules (%d 个模块); 悬空 %d %s" % (
        n_fn, len(mod_names), len(dangling), dangling[:5] if dangling else ""))
    linked_mod = {e["dst"] for e in graph["edges"] if e["kind"] == "对应模块"}
    ok(len(linked_mod) == n_fn, "对应模块边 %d 条 (== 功能数 %d)" % (len(linked_mod), n_fn))

    # ② 每个功能的参数链接数
    pc = {}
    for e in graph["edges"]:
        if e["kind"] == "功能参数":
            pc[e["src"]] = pc.get(e["src"], 0) + 1
    counts = [pc.get("fn:" + r[0], 0) for r in fn_rows]
    zero = [r[0] for r in fn_rows if pc.get("fn:" + r[0], 0) == 0]
    have = [c for c in counts if c > 0]
    print("② 每个功能的参数链接数")
    ok(len(counts) == n_fn, "功能 %d 个全部计到链接数 (有链接 %d · 无链接 %d)" % (
        n_fn, len(have), len(zero)))
    if have:
        have_sorted = sorted(have)
        print("     每功能链接数: 最小 %d · 中位 %d · 最大 %d · 合计 %d" % (
            have_sorted[0], have_sorted[len(have_sorted) // 2], have_sorted[-1], sum(counts)))
        top = sorted(((pc.get("fn:" + r[0], 0), r[0]) for r in fn_rows), reverse=True)[:3]
        print("     最多: " + ", ".join("%s=%d" % (f, c) for c, f in top))
    if zero:
        print("     无链接功能 (%d): %s%s" % (len(zero), zero[:8], " …" if len(zero) > 8 else ""))
    ok(sum(counts) > 0, "功能→参数 边合计 %d (>0)" % sum(counts))

    # ③ 画布节点 89/74 与功能数对齐
    n_canvas_db = cur.execute("SELECT COUNT(*) FROM canvas_nodes").fetchone()[0]
    cc = _canvas_counts(CANVAS_DEFAULT)
    print("③ 画布节点口径 (89 / 74) 与功能数")
    ok(n_canvas_db == n_fn, "库 canvas_nodes=%d == functions=%d (逻辑节点口径 74)" % (n_canvas_db, n_fn))
    if cc["exists"]:
        ok(cc["logical"] == n_fn, "画布 JSON 逻辑节点=%d == functions=%d" % (cc["logical"], n_fn))
        ok(cc["json_nodes"] == cc["logical"] + cc["row_bg"] and cc["row_bg"] > 0,
           "画布 JSON 全量节点=%d = 逻辑 %d + row_bg %d" % (cc["json_nodes"], cc["logical"], cc["row_bg"]))
    else:
        ok(False, "画布 JSON 缺失, 无法核 89 口径: %s" % CANVAS_DEFAULT)

    print("─" * 70)
    print(("✅ 全部通过 — 架构图判据 (3 项)" if not fails else "❌ 失败 %d 项: %s" % (len(fails), fails)))
    return 1 if fails else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z-MAX 架构图数据 (只读)")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--canvas", default=CANVAS_DEFAULT)
    ap.add_argument("--json", action="store_true", help="结构化 JSON 到 stdout")
    ap.add_argument("--json-out", metavar="PATH", help="结构化 JSON 写文件")
    ap.add_argument("--focus", metavar="FN_ID|SYS_ID", help="以某功能/系统为中心的局部子图")
    ap.add_argument("--check", action="store_true", help="跑判据 (断言)")
    a = ap.parse_args(argv)

    con = open_db(a.db)
    graph = build(con, a.canvas)

    if a.focus:
        sub = subgraph(graph, a.focus)
        if sub is None:
            con.close()
            print("⛔ --focus 未命中: %s (给 fn_id 如 FN-SYS0-01 或 sys_id 如 sys0)" % a.focus)
            return 2
        if a.json or a.json_out:
            _emit(sub, a)
        else:
            _focus_text(sub)
        con.close()
        return 0

    if a.check:
        rc = check(graph, con)
        con.close()
        return rc

    if a.json or a.json_out:
        _emit(graph, a)
    else:
        summarize(graph, con, a.canvas)
    con.close()
    return 0


def _focus_text(sub):
    """局部子图的人读概览 (按层分组 + 关键连线, 不逐条铺边)。"""
    by_layer = {}
    for n in sub["nodes"]:
        by_layer.setdefault(n["layer"], []).append(n)
    eby = {}
    for e in sub["edges"]:
        eby[e["kind"]] = eby.get(e["kind"], 0) + 1
    print("聚焦 %s : 节点 %d · 边 %d" % (sub["focus"], len(sub["nodes"]), len(sub["edges"])))
    for layer in sorted(by_layer):
        labels = [n["label"] for n in by_layer[layer]]
        show = labels[:6]
        more = "" if len(labels) <= 6 else " …(+%d)" % (len(labels) - 6)
        print("  L%-2d %-6s %3d: %s%s" % (
            layer, LAYER_NAMES.get(layer, "?"), len(labels), " · ".join(show), more))
    print("  边: " + " · ".join("%s=%d" % (k, eby[k]) for k in sorted(eby)))


def _emit(graph, a):
    payload = json.dumps(graph, ensure_ascii=False, indent=2)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            f.write(payload)
        print("✅ 已写: %s (nodes %d · edges %d · %.1f KB)" % (
            a.json_out, graph["meta"]["counts"]["nodes"], graph["meta"]["counts"]["edges"],
            os.path.getsize(a.json_out) / 1024.0))
    else:
        print(payload)


if __name__ == "__main__":
    sys.exit(main())
