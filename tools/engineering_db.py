#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""engineering_db.py — Z-MAX 工程数据库 (单一文件承载全部工程数据)  (2026-10-09 老倪)

老倪:
  「所有的产品特性, 系统配置, 标定参数, 功能清单等汇总的数据库, 要和状态空间的工程文件,
    一起形成一个统一的数据结构, 可以通过加载工程, 一起将所有 特性 配置 参数 功能 模块代码
    都链接出来; 最好只用一个数据库文件, 承载所有工程数据; 这样控制台的 GUI 就与整个工程解耦;
    我可以随时迁移数据库工程文件, 用统一的 GUI 加载我的工程数据。总数据库放在 data/database。」
  2026-10-09 路径定版: 产品数据统一放 data/database/<产品>/ (本平台 = data/database/zmax/)。

单一文件: data/database/zmax/zmax_engineering.db (SQLite)   ← 标准产品数据路径
  真源 (人可编·进 git)                    →  表
  ─────────────────────────────────────────────────────────────────────────
  config/platform/zmax_platform.json      →  platform / products / product_features / subsystems / subsystem_axes
  data/database/zmax/*.proj (7 段)       →  projects / project_sections
  <project>.canvas.nodes/links            →  canvas_nodes / canvas_links / functions / fn_axes
  config/calib/zmax_calib.json + manifold →  calib_params
  feature.dbc (能力数据库)                 →  capability_dbc / interfaces(输入输出)
  src/.../verification_layer.py FEATURES  →  verification_features
  src/.../nodes/library.py NODE_LOGIC     →  module_code (模块 → 代码文件/行号)
  画布节点 (模块库同源)                     →  modules / library_removed
  关系图                                    →  links (pf→subsys, fn→module, pf→capability, module→code)

用法:
  engineering_db.py build [--project X.proj] [--db 路径]    # 重建库 (真源 → 单文件)
  engineering_db.py stats                                   # 各表行数
  engineering_db.py check                                   # 同步判据 (真源↔库↔模块↔代码 一致)
  engineering_db.py query "product Z700" / "system sys2" / "fn FN-…" / "modules" / "sql SELECT …"
  engineering_db.py load --json out.json                    # 导出 (GUI 也可直接 import 本模块 load())
  engineering_db.py serve [--port 8798]                     # 只读 JSON 服务 (GUI/外部消费者)
  engineering_db.py migrate --to 新路径                      # 迁移库文件 (工程带走 = 换机器)
"""
import argparse
import ast
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DEFAULT = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
PLATFORM_SRC = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
CALIB_SRC = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
MANIFOLD_SRC = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
FEATURE_DBC = os.path.join(ROOT, "feature.dbc")
VERIF_SRC = os.path.join(ROOT, "src", "lerobot", "verification", "verification_layer.py")
NODES_SRC = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "library.py")
CANVAS = os.path.join(ROOT, "src", "lerobot", "engineering", "flows", "state_space_obs.json")
CURATION = os.path.join(ROOT, "config", "library_curation.json")
PROJ_DIR = os.path.join(ROOT, "data", "database", "zmax")   # 标准产品数据路径: data/database/<产品>/

SCHEMA = """
DROP TABLE IF EXISTS meta;                    CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
DROP TABLE IF EXISTS platform;                CREATE TABLE platform(platform_id TEXT PRIMARY KEY, name TEXT, positioning TEXT, architecture TEXT, data_contract TEXT);
DROP TABLE IF EXISTS products;                CREATE TABLE products(product_id TEXT PRIMARY KEY, name TEXT, cn TEXT, category TEXT, positioning TEXT, kpi TEXT, subsystems TEXT, extra TEXT);
DROP TABLE IF EXISTS subsystems;              CREATE TABLE subsystems(system_id TEXT PRIMARY KEY, name TEXT, level TEXT, role TEXT, hardware TEXT, kpi TEXT, rows TEXT, ord INTEGER);
DROP TABLE IF EXISTS subsystem_axes;          CREATE TABLE subsystem_axes(system_id TEXT, axis TEXT, idx INTEGER, item TEXT);
DROP TABLE IF EXISTS product_features;        CREATE TABLE product_features(pf_id TEXT PRIMARY KEY, product_id TEXT, title TEXT, capability_ref TEXT, kpi TEXT, status TEXT, descr TEXT, subsys TEXT, module_refs TEXT);
DROP TABLE IF EXISTS functions;               CREATE TABLE functions(fn_id TEXT PRIMARY KEY, system_id TEXT, name TEXT, layer TEXT, kind TEXT, row_name TEXT, module_ref TEXT, params TEXT, source TEXT);
DROP TABLE IF EXISTS fn_axes;                 CREATE TABLE fn_axes(fn_id TEXT, axis TEXT, idx INTEGER, item TEXT, src TEXT);
DROP TABLE IF EXISTS calib_params;            CREATE TABLE calib_params(path TEXT, key TEXT, value TEXT, unit TEXT, src TEXT, status TEXT, PRIMARY KEY(path, key));
DROP TABLE IF EXISTS modules;                 CREATE TABLE modules(name TEXT PRIMARY KEY, kind TEXT, group_name TEXT, params TEXT, verif_layer INTEGER, source TEXT);
DROP TABLE IF EXISTS library_removed;         CREATE TABLE library_removed(group_name TEXT, name TEXT, why TEXT, ts TEXT);
DROP TABLE IF EXISTS params;                  CREATE TABLE params(param_id TEXT PRIMARY KEY, group_cn TEXT, cat TEXT, name TEXT, cn TEXT, value TEXT, default_val TEXT, min REAL, max REAL, unit TEXT, kind TEXT, choices TEXT, source TEXT, ref TEXT, writable INT, status TEXT, color TEXT, sys_id TEXT, module_ref TEXT, impact TEXT);
CREATE TABLE IF NOT EXISTS param_events(ts TEXT, param_id TEXT, cn TEXT, old_val TEXT, new_val TEXT, cat TEXT, source TEXT, written INT, msg TEXT);   -- ⚠️ 运行时表: 改数事件由程序直接写入, build 不清空 (唯一留痕处, 不再有 param_events.jsonl)
DROP TABLE IF EXISTS param_links;             CREATE TABLE param_links(param_id TEXT, kind TEXT, target TEXT);
DROP TABLE IF EXISTS mcd;                     CREATE TABLE mcd(scope TEXT, scope_id TEXT, scope_cn TEXT, m INTEGER, c INTEGER, d INTEGER, note TEXT, PRIMARY KEY(scope, scope_id));
CREATE INDEX IF NOT EXISTS ix_prm_grp ON params(group_cn);
DROP TABLE IF EXISTS module_code;             CREATE TABLE module_code(module_name TEXT, logic_key TEXT, file TEXT, line INTEGER, doc TEXT, match TEXT);
DROP TABLE IF EXISTS capability_dbc;          CREATE TABLE capability_dbc(bo_id TEXT PRIMARY KEY, grp TEXT, name TEXT, dirs TEXT, brief TEXT, explain TEXT, iface TEXT, inputs TEXT, outputs TEXT, scenes TEXT, engineering TEXT, owner TEXT);
DROP TABLE IF EXISTS verification_features;   CREATE TABLE verification_features(f_id TEXT PRIMARY KEY, domain TEXT, name TEXT, where_ TEXT, how TEXT, case_id TEXT, level TEXT);
DROP TABLE IF EXISTS interfaces;              CREATE TABLE interfaces(if_id TEXT PRIMARY KEY, owner_type TEXT, owner_id TEXT, direction TEXT, name TEXT, note TEXT);
DROP TABLE IF EXISTS links;                   CREATE TABLE links(src_type TEXT, src_id TEXT, dst_type TEXT, dst_id TEXT, kind TEXT);
DROP TABLE IF EXISTS projects;                CREATE TABLE projects(project_id TEXT PRIMARY KEY, path TEXT, saved_at TEXT, version TEXT, canvas_md5 TEXT, sha256 TEXT);
DROP TABLE IF EXISTS project_sections;        CREATE TABLE project_sections(project_id TEXT, section TEXT, json TEXT, sha256 TEXT);
DROP TABLE IF EXISTS canvas_nodes;            CREATE TABLE canvas_nodes(project_id TEXT, name TEXT, type TEXT, x REAL, y REAL, w REAL, h REAL, params TEXT);
DROP TABLE IF EXISTS canvas_links;            CREATE TABLE canvas_links(project_id TEXT, src TEXT, dst TEXT, kind TEXT);
CREATE INDEX IF NOT EXISTS ix_fn_sys ON functions(system_id);
CREATE INDEX IF NOT EXISTS ix_pf_prod ON product_features(product_id);
CREATE INDEX IF NOT EXISTS ix_cn_name ON canvas_nodes(name);
"""


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _j(x):
    return json.dumps(x, ensure_ascii=False)


def _read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:                                                            # noqa: BLE001
        return None


# ── 真源读取 ──────────────────────────────────────────────────────────────
def load_platform():
    return json.loads(_read(PLATFORM_SRC) or "{}")


def load_project(proj_path=None):
    """工程存档 (.proj) — 不依赖 GUI: project_file 里是纯函数, 直接读文件。"""
    if not proj_path:
        cands = sorted(glob.glob(os.path.join(PROJ_DIR, "*.proj")), key=os.path.getmtime)
        proj_path = cands[-1] if cands else None
    if not proj_path or not os.path.exists(proj_path):
        return None, {}
    raw = _read(proj_path) or "{}"
    try:
        d = json.loads(raw)
    except Exception:                                                            # noqa: BLE001
        return None, {}
    return {"path": proj_path, "sha": _sha(raw), "doc": d}, d


def flatten_calib(d, pre=""):
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k in ("_doc", "_generated_at"):
                continue
            p = (pre + "." + k) if pre else k
            if isinstance(v, dict):
                if any(x in v for x in ("value", "_src", "_reason")):
                    val = v.get("value", v.get("points"))
                    status = "已标定" if (val is not None and v.get("_reason") is None) else "缺口/待标定"
                    if isinstance(v.get("points"), list) and val is None:
                        status = "缺口/待标定"
                    out.append((p, k, _j(val if val is not None else v), v.get("unit", ""),
                                v.get("_src", "") or "", status))
                    for k2, v2 in v.items():
                        if k2.startswith("_") or k2 in ("unit", "value", "points"):
                            continue
                        out.append((p, k2, _j(v2), "", v.get("_src", "") or "", status))
                else:
                    out += flatten_calib(v, p)
            elif isinstance(v, list):
                out.append((p, k, _j(v), "", d.get("_src", "") if isinstance(d, dict) else "", "已标定"))
            else:
                out.append((p, k, _j(v), "", "", "已标定"))
    return out


def parse_feature_dbc():
    """feature.dbc → 能力块 (BO_) + 输入输出接口"""
    txt = _read(FEATURE_DBC) or ""
    caps, cur = [], None
    for ln in txt.splitlines():
        m = re.match(r"^BO_\s+(\S+)\s+([^:]+):\s*(\S*)\s*(\S*)", ln)
        if m:
            cur = {"bo_id": m.group(1), "name": m.group(2).strip(), "dirs": m.group(3),
                   "grp": m.group(4), "brief": "", "explain": "", "iface": "",
                   "inputs": "", "outputs": "", "scenes": "", "engineering": "", "owner": ""}
            caps.append(cur)
            continue
        m = re.match(r'^\s*SG_\s+(简述|解释|接口定义|输入|输出|场景|工程|归属)\s*:\s*\d+\s*"(.*)"\s*$', ln)
        if m and cur is not None:
            key = {"简述": "brief", "解释": "explain", "接口定义": "iface", "输入": "inputs",
                   "输出": "outputs", "场景": "scenes", "工程": "engineering", "归属": "owner"}[m.group(1)]
            cur[key] = m.group(2)
    return caps


def parse_verification_features():
    """verification_layer.py 的 FEATURES 列表 (ast 静态解析, 不 import) → 验证/诊断项真源"""
    src = _read(VERIF_SRC)
    if not src:
        return []
    try:
        tree = ast.parse(src)
    except Exception:                                                            # noqa: BLE001
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "FEATURES" for t in node.targets):
            try:
                return [list(x) for x in ast.literal_eval(node.value)]
            except Exception:                                                    # noqa: BLE001
                return []
    return []


def load_node_logic():
    """引擎节点逻辑真源 → [(逻辑key, 匹配关键字, doc, 文件, 行号)] (模块↔代码 链接用)"""
    out = []
    try:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.engineering.registry import NODE_LOGIC                     # noqa: E402
        for key, info in (NODE_LOGIC or {}).items():
            fn = (info or {}).get("fn") if isinstance(info, dict) else None
            f = getattr(getattr(fn, "__code__", None), "co_filename", "")
            ln = getattr(getattr(fn, "__code__", None), "co_firstlineno", 0)
            out.append((str(key), ",".join((info or {}).get("match", []) or []),
                        (info or {}).get("doc", "") or "", f, int(ln or 0)))
    except Exception:                                                            # noqa: BLE001
        pass
    return out


def engine_code_for(module_name, logics):
    """按 lib_sync 同一口径: 名字命中 match 关键字 ⇒ 模块背后有真代码"""
    for key, match, doc, f, ln in logics:
        for kw in [x for x in match.split(",") if x]:
            if kw and kw in module_name:
                return {"logic_key": key, "file": f, "line": ln, "doc": doc, "match": match}
    return None


# ── 建库 ──────────────────────────────────────────────────────────────────
def build(db=DB_DEFAULT, proj_path=None, quiet=False):
    os.makedirs(os.path.dirname(db), exist_ok=True)
    plat = load_platform()
    prj, pdoc = load_project(proj_path)
    calib = json.loads(_read(CALIB_SRC) or "{}")
    manifold = json.loads(_read(MANIFOLD_SRC) or "{}")
    caps = parse_feature_dbc()
    verifs = parse_verification_features()
    logics = load_node_logic()
    canvas = json.loads(_read(CANVAS) or "{}")
    nodes = canvas.get("nodes", [])
    links = canvas.get("links", [])
    curation = json.loads(_read(CURATION) or "{}")

    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    c = con.cursor()
    cnt = {}

    # 改数事件: 唯一留痕处 = 本库 param_events 表 (build 不清空)。
    # 若还留着老的 param_events.jsonl (2026-10-09 之前的历史), 一次性并入去重; 之后该文件可删。
    _legacy_ev = os.path.join(ROOT, "data", "database", "zmax", "param_events.jsonl")
    if os.path.exists(_legacy_ev):
        n_new = 0
        for _ln in open(_legacy_ev, encoding="utf-8"):
            try:
                _e = json.loads(_ln)
            except Exception:                                                       # noqa: BLE001
                continue
            _row = (_e.get("ts"), _e.get("param"), _j(_e.get("old")), _j(_e.get("new")))
            if c.execute("SELECT 1 FROM param_events WHERE ts=? AND param_id=? AND old_val=? AND new_val=?",
                         _row).fetchone():
                continue
            c.execute("INSERT INTO param_events VALUES (?,?,?,?,?,?,?,?,?)",
                      (_e.get("ts"), _e.get("param"), _e.get("cn"), _j(_e.get("old")), _j(_e.get("new")),
                       _e.get("cat"), _e.get("source"), 1 if _e.get("written") else 0, _e.get("msg", "")))
            n_new += 1
        if n_new:
            print("  ↪ 旧 param_events.jsonl 并入 %d 条 (库内事件唯一留痕, 该文件已可删)" % n_new)

    # meta
    meta = {
        "schema": "zmax-engineering-db/1.0",
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_tables": "param_events — 改数事件由程序直接写入本表, build 不清空 (唯一留痕处, 不再有 param_events.jsonl)",
        "sources": _j({
            "platform": [PLATFORM_SRC, os.path.exists(PLATFORM_SRC) and _sha(_read(PLATFORM_SRC) or "")],
            "project": [prj["path"] if prj else None, prj["sha"] if prj else None],
            "canvas": [CANVAS, _sha(_read(CANVAS) or "")],
            "calib": [CALIB_SRC, _sha(_read(CALIB_SRC) or "")],
            "manifold": [MANIFOLD_SRC, _sha(_read(MANIFOLD_SRC) or "")],
            "feature_dbc": [FEATURE_DBC, _sha(_read(FEATURE_DBC) or "")],
            "verification": [VERIF_SRC, _sha(_read(VERIF_SRC) or "")],
            "node_logic": [NODES_SRC, _sha(_read(NODES_SRC) or "")],
            "curation": [CURATION, _sha(_read(CURATION) or "")],
        }),
    }
    c.executemany("INSERT INTO meta(k,v) VALUES(?,?)", list(meta.items()))

    # platform / products / subsystems / axes / features
    p = plat.get("platform", {})
    c.execute("INSERT INTO platform VALUES(?,?,?,?,?)", (p.get("platform_id", "Z-MAX"), p.get("name", ""),
                                                         p.get("positioning", ""), p.get("architecture", ""),
                                                         p.get("data_contract", "")))
    for x in plat.get("products", []):
        c.execute("INSERT INTO products VALUES(?,?,?,?,?,?,?,?)",
                  (x.get("product_id"), x.get("name"), x.get("name"), x.get("category"),
                   x.get("positioning"), _j(x.get("kpi", {})), _j(x.get("subsystems", [])),
                   _j({"differentiators": x.get("differentiators", [])})))
    for i, s in enumerate(plat.get("subsystems", [])):
        c.execute("INSERT INTO subsystems VALUES(?,?,?,?,?,?,?,?)",
                  (s.get("system_id"), s.get("name"), s.get("level"), s.get("role"),
                   s.get("hardware"), _j(s.get("kpi", {})), _j(s.get("rows", [])), i))
        for ax in ("cfg", "cal", "dia"):
            for j, it in enumerate((s.get("axes", {}) or {}).get(ax, []) or []):
                c.execute("INSERT INTO subsystem_axes VALUES(?,?,?,?)", (s.get("system_id"), ax, j, it))
    for f in plat.get("product_features", []):
        c.execute("INSERT INTO product_features VALUES(?,?,?,?,?,?,?,?,?)",
                  (f.get("pf_id"), f.get("product_id"), f.get("title"), f.get("capability_ref"),
                   f.get("kpi"), f.get("status"), f.get("desc"), _j(f.get("subsys", [])),
                   _j(f.get("module_refs", []))))
        for sid in f.get("subsys", []) or []:
            c.execute("INSERT INTO links VALUES(?,?,?,?,?)", ("product_feature", f.get("pf_id"),
                                                              "subsystem", sid, "归属"))
        for mr in f.get("module_refs", []) or []:
            c.execute("INSERT INTO links VALUES(?,?,?,?,?)", ("product_feature", f.get("pf_id"),
                                                              "module", mr, "用到"))
        if f.get("capability_ref"):
            for bo in re.findall(r"BO_\s*(\S+)", f["capability_ref"]):
                c.execute("INSERT INTO links VALUES(?,?,?,?,?)", ("product_feature", f.get("pf_id"),
                                                                  "capability", bo, "能力引用"))

    # 子系统 → 画布行 → 功能: 每个非 row_bg 节点归**唯一一行**(最具体的行带), 一行归**唯一子系统**
    #  (2026-10-09 修: 原来用 rname[:14] 前缀匹配 ⇒ 所有「🔧 L2 基础辅助功能 · X」都命中同一行,
    #   6 条 L2 行把同一批节点数了 6 遍 → 85 条功能/74 个节点。现在按行尾关键词唯一解析 + 全局归属。)
    rows = [n for n in nodes if n.get("type") == "row_bg"]

    out_of_band = []

    def _row_of_node(n):
        """节点 → 画布行带。落在带内的取**最具体**的行; 落在行带缝隙的按**最近行**归属
        (2026-10-09 实测: 画布有两个行外节点「🛡 安全执行边界」「① 接近 · SK01」在行带缝隙里 —
         不能丢, 就近归属 + 标 kind=行外节点(就近归属))"""
        cy = float(n.get("y", 0)) + float(n.get("h", 0) or 0) / 2.0
        cand = [(float(r.get("h", 0) or 0), r) for r in rows
                if float(r.get("y", 0)) - 4 <= cy <= float(r.get("y", 0)) + float(r.get("h", 0) or 0) + 4]
        if cand:
            cand.sort(key=lambda t: t[0])
            return cand[0][1].get("name")
        if not rows:
            return None
        def _dist(r):
            y0 = float(r.get("y", 0))
            h = float(r.get("h", 0) or 0)
            return 0.0 if y0 <= cy <= y0 + h else min(abs(cy - y0), abs(cy - (y0 + h)))
        best = min(rows, key=_dist)
        out_of_band.append((n.get("name"), best.get("name")))
        return best.get("name")

    node_row = {n.get("name"): _row_of_node(n) for n in nodes if n.get("type") != "row_bg"}

    def _row_key(nm):
        nm = nm or ""
        return nm.split("·")[-1].strip() if "·" in nm else nm.strip()

    def _resolve(rname):
        """声明的行名 → 画布行 (按「· 后缀」关键词唯一命中, 再退回最长公共前缀)"""
        rk = _row_key(rname)
        exact = [r for r in rows if (r.get("name") or "") == rname]
        if exact:
            return exact[0]
        by_tail = [r for r in rows if rk and rk[:10] in (r.get("name") or "")]
        if len(by_tail) == 1:
            return by_tail[0]
        if by_tail:
            return max(by_tail, key=lambda r: len(r.get("name") or ""))
        best, score = None, 0
        for r in rows:
            cn = r.get("name") or ""
            k = 0
            for a, b in zip(rname, cn):
                if a != b:
                    break
                k += 1
            if k > score:
                best, score = r, k
        return best if score >= 6 else None

    used_rows, unmatched = set(), []
    fno = 0
    for s_ in plat.get("subsystems", []):
        sid = s_.get("system_id")
        for rname in s_.get("rows", []) or []:
            hit = _resolve(rname)
            if hit is None or hit.get("name") in used_rows:
                if hit is None:
                    unmatched.append((sid, rname))
                continue
            used_rows.add(hit.get("name"))
            hname = hit.get("name")
            for n in nodes:
                if n.get("type") == "row_bg" or node_row.get(n.get("name")) != hname:
                    continue
                fno += 1
                fid = "FN-%s-%02d" % (sid.upper(), fno)
                nm = n.get("name") or "?"
                pp = dict(n.get("params", {}) or {})
                ref = engine_code_for(nm, logics)
                _kind = "模块节点" if not any(x[0] == nm for x in out_of_band) else "行外节点(就近归属)"
                c.execute("INSERT INTO functions VALUES(?,?,?,?,?,?,?,?,?)",
                          (fid, sid, nm, s_.get("level"), _kind, hname, nm,
                           _j({k: v for k, v in pp.items() if k != "desc"}),
                           (ref or {}).get("file", "") + ((":%d" % ref["line"]) if ref and ref.get("line") else "")))
                c.execute("INSERT INTO links VALUES(?,?,?,?,?)", ("function", fid, "module", nm, "对应模块"))
                jx = 0
                for k, v in pp.items():
                    if k in ("state_space", "verif_layer", "desc"):
                        continue
                    c.execute("INSERT INTO fn_axes VALUES(?,?,?,?,?)",
                              (fid, "cfg", jx, "%s = %s" % (k, str(v)[:160]), "画布节点 params")); jx += 1
                for ax in ("cfg", "cal", "dia"):
                    for it in (s_.get("axes", {}) or {}).get(ax, []) or []:
                        c.execute("INSERT INTO fn_axes VALUES(?,?,?,?,?)",
                                  (fid, ax, 900 + len(it), it, "子系统 %s 轴" % ax))
    if unmatched:
        print("⚠️ 未命中画布行的声明 (需修 config/platform/zmax_platform.json): %s" % unmatched, flush=True)
    if out_of_band:
        print("ℹ️ 行带缝隙里的节点按最近行归属 (%d 个): %s" % (len(out_of_band), out_of_band), flush=True)

    # 画布节点 / 连线 (模块 + 工程画布)
    for n in nodes:
        if n.get("type") == "row_bg":
            continue
        c.execute("INSERT INTO canvas_nodes VALUES(?,?,?,?,?,?,?,?)",
                  (os.path.basename(prj["path"]) if prj else "state_space_obs.json", n.get("name"),
                   n.get("type"), n.get("x", 0), n.get("y", 0), n.get("w", 0), n.get("h", 0),
                   _j(n.get("params", {}))))
        ref = engine_code_for(n.get("name") or "", logics)
        c.execute("INSERT OR REPLACE INTO modules VALUES(?,?,?,?,?,?)",
                  (n.get("name"), n.get("type"), "状态空间画布", _j(n.get("params", {})),
                   1 if (n.get("params", {}) or {}).get("verif_layer") else 0,
                   "canvas:" + CANVAS))
        if ref:
            c.execute("INSERT INTO module_code VALUES(?,?,?,?,?,?)",
                      (n.get("name"), ref["logic_key"], ref["file"], ref["line"], ref["doc"], ref["match"]))
            c.execute("INSERT INTO links VALUES(?,?,?,?,?)",
                      ("module", n.get("name"), "code", "%s:%d" % (ref["file"], ref["line"]), "实现"))
    for l in links:
        c.execute("INSERT INTO canvas_links VALUES(?,?,?,?)",
                  (os.path.basename(prj["path"]) if prj else "state_space_obs.json",
                   l.get("src") or l.get("from"), l.get("dst") or l.get("to"), l.get("kind", "")))

    # 标定参数
    for (path, key, val, unit, src, status) in flatten_calib(calib):
        c.execute("INSERT OR REPLACE INTO calib_params VALUES(?,?,?,?,?,?)", (path, key, val, unit, src, status))
    for (path, key, val, unit, src, status) in flatten_calib({"manifold_engine_file": manifold}):
        c.execute("INSERT OR REPLACE INTO calib_params VALUES(?,?,?,?,?,?)", (path, key, val, unit, src, status))

    # 能力数据库 (feature.dbc) + 接口
    for cap in caps:
        c.execute("INSERT INTO capability_dbc VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cap["bo_id"], cap["grp"], cap["name"], cap["dirs"], cap["brief"], cap["explain"],
                   cap["iface"], cap["inputs"], cap["outputs"], cap["scenes"], cap["engineering"], cap["owner"]))
        for d, txt in (("IN", cap["inputs"]), ("OUT", cap["outputs"])):
            if txt:
                c.execute("INSERT INTO interfaces VALUES(?,?,?,?,?,?)",
                          ("IF-%s-%s" % (cap["bo_id"], d), "capability", cap["bo_id"], d, txt[:80], txt))
                c.execute("INSERT INTO links VALUES(?,?,?,?,?)", ("capability", cap["bo_id"],
                                                                  "interface", "IF-%s-%s" % (cap["bo_id"], d), d))

    # 验证/诊断项真源
    for v in verifs:
        try:
            c.execute("INSERT OR REPLACE INTO verification_features VALUES(?,?,?,?,?,?,?)",
                      tuple([str(x) for x in (list(v) + [""] * 7)[:7]]))
        except Exception:                                                        # noqa: BLE001
            continue
    for v in verifs:
        if len(v) >= 7:
            c.execute("INSERT INTO links VALUES(?,?,?,?,?)", ("verification", str(v[0]), "level", str(v[6]), "分级"))

    # 库删除名单
    for x in (curation.get("removed") or []):
        c.execute("INSERT INTO library_removed VALUES(?,?,?,?)",
                  (x.get("group"), x.get("name"), x.get("why"), x.get("ts")))

    # 工程存档 7 段
    if prj:
        d = prj["doc"]
        meta_p = d.get("meta", {}) if isinstance(d.get("meta"), dict) else {}
        c.execute("INSERT INTO projects VALUES(?,?,?,?,?,?)",
                  (os.path.basename(prj["path"]), prj["path"],
                   str(meta_p.get("saved_at", d.get("saved_at", ""))),
                   str(d.get("version", meta_p.get("version", ""))),
                   str(meta_p.get("canvas_md5", "")), prj["sha"]))
        # 真实 .proj 顶层键 ↔ 7 段语义 (2026-10-09 实测: canvas/panel/calibration/master_param/
        #   measure/tasks + 元信息在顶层) —— 全部顶层键都入库(一段不丢), 另记语义映射供判据/UI 用
        SECMAP = {"canvas": "canvas", "panel": "pane", "calibration": "calib",
                  "measure": "measure", "master_param": "mparam", "tasks": "task"}
        META_KEYS = [k for k in d.keys() if k not in SECMAP and k not in ("canvas",)]
        for k, v in d.items():
            js = _j(v)
            c.execute("INSERT INTO project_sections VALUES(?,?,?,?)",
                      (os.path.basename(prj["path"]), k, js, _sha(js)))
            if k in SECMAP:      # 同时按 7 段语义名存一份 (老倪的统一结构口径: 两种叫法都能取到)
                c.execute("INSERT OR REPLACE INTO project_sections VALUES(?,?,?,?)",
                          (os.path.basename(prj["path"]), SECMAP[k], js, _sha(js)))
        c.execute("INSERT INTO project_sections VALUES(?,?,?,?)",
                  (os.path.basename(prj["path"]), "meta", _j({k: d[k] for k in META_KEYS}), _sha(_j(META_KEYS))))
        c.execute("UPDATE meta SET v=? WHERE k=?", (_j(SECMAP), "section_map"))

    # ── 参数注册表: 全局可改数字 (产品性能/配置/标定/代码常量/运行开关) ──
    try:
        import importlib.util as _iu
        _pf = os.path.join(ROOT, "tools", "param_registry.py")
        if os.path.exists(_pf):
            _spec = _iu.spec_from_file_location("_pr", _pf)
            _pr = _iu.module_from_spec(_spec)
            _spec.loader.exec_module(_pr)                                       # type: ignore[union-attr]
            _reg = _pr.registry()
            for p_ in _reg["params"]:
                sid = ""
                if p_["group"] == "calib":
                    seg = p_["param_id"].split(":", 1)[1].split(".")[0]
                    sid = "sys2" if seg == "manifold_engine" else "sys0"
                elif p_["group"] == "switch":
                    sid = p_.get("sys_hint") or "sys1"
                c.execute("INSERT OR REPLACE INTO params VALUES (" + ",".join(["?"] * 20) + ")",
                          (p_["param_id"], p_["cat_cn"], p_["group"], p_["name"], p_["cn"], _j(p_["value"]),
                           _j(p_["default"]), p_["min"], p_["max"], p_["unit"], p_["kind"], _j(p_["choices"]),
                           p_["source"], p_["ref"], 1 if p_["writable"] else 0, p_["status"], p_["color"],
                           sid, p_.get("fn_ref") or "", p_.get("impact") or ""))
                _fn = p_.get("fn_ref") or ""
                c.execute("INSERT INTO param_links VALUES (?,?,?)", (p_["param_id"], "功能", _fn or p_["name"]))
                c.execute("INSERT INTO param_links VALUES (?,?,?)", (p_["param_id"], "模块", p_["name"]))
                if sid:
                    c.execute("INSERT INTO param_links VALUES (?,?,?)", (p_["param_id"], "系统", sid))
            # 改数事件不在这里读 —— param_events 是运行时表, 由 build() 开头的旧 jsonl 并入 + 程序直接写入
    except Exception as _e:                                                    # noqa: BLE001
        print("[engineering_db] 参数注册表摄取失败: %r" % (_e,))

    # ── 性能指标定义 (光模块精细操作: 机器人学口径 + 光模块工艺口径) ──
    # 真源 config/platform/zmax_perf_spec.json。value = **目标值/规格** (不是实测值), 指标类记 kind='spec'。
    # 入库理由: ① 单一工程库要能看到「性能指标清单」(配置中心/功能清单页取同一份)
    #           ② 改指标 ⇒ 工程库 sha 变 ⇒ 文档 manifest 一致性判据能抓到 (否则会被漏掉)
    try:
        _pf = os.path.join(ROOT, "config", "platform", "zmax_perf_spec.json")
        if os.path.exists(_pf):
            _d = json.load(open(_pf, encoding="utf-8"))
            _n = 0
            for _g in _d.get("groups", []):
                for _m in _g.get("metrics", []):
                    _tgt = _m.get("target")
                    _ok = bool(_tgt) and not str(_tgt).startswith("待")
                    _pid = "spec:" + _m["id"]
                    c.execute("INSERT OR REPLACE INTO params VALUES (" + ",".join(["?"] * 20) + ")",
                              (_pid, "性能指标定义", "spec", _m["id"], _m["cn"],
                               _j(_tgt if _ok else "null"), "null", None, None,
                               _m.get("unit") or "-", "spec", "null",
                               "config/platform/zmax_perf_spec.json", "perf_spec:" + _m["id"], 0,
                               ("指标定义(目标值=规格; 实测值待验收阶段填入)" if _ok
                                else "目标值待确认 (需按工件/工艺规格定)"),
                               "#7fb3ff", "sys1", "", " · ".join(_m.get("links") or [])))
                    for _l, _v in (("指标组", "%s %s" % (_g["gid"], _g["name"])),
                                   ("阶段", _m.get("stage", "-")),
                                   ("标准", _m.get("std", "-"))):
                        c.execute("INSERT INTO param_links VALUES (?,?,?)", (_pid, _l, _v))
                    for _lk in (_m.get("links") or []):
                        c.execute("INSERT INTO param_links VALUES (?,?,?)", (_pid, "功能", _lk))
                    _n += 1
            print("   性能指标定义 (spec)      %d" % _n)
    except Exception as _e:                                                    # noqa: BLE001
        print("[engineering_db] 性能指标体系摄取失败: %r" % (_e,))

    # ── MCD 三轴 (测量 Measurement · 标定 Calibration · 诊断 Diagnosis) — 「用数据定义产品框架」 ──
    try:
        _mv = {}
        _row = c.execute("SELECT json FROM project_sections WHERE section='measure'").fetchone()
        if _row:
            _mv = json.loads(_row[0]) or {}
        _m_view = _mv.get("measure_view") or {}
        _d_view = _mv.get("diagnose_view") or {}
        n_m = int(_m_view.get("测量量") or 0)
        n_d = int(_d_view.get("断言") or 0) or c.execute("SELECT COUNT(*) FROM verification_features").fetchone()[0]
        n_c = c.execute("SELECT COUNT(*) FROM params WHERE cat='calib'").fetchone()[0]
        lv = {r[0]: r[1] for r in c.execute("SELECT level, COUNT(*) FROM verification_features GROUP BY level")}
        sadm = {r[0]: r[1] for r in c.execute("SELECT sys_id, COUNT(*) FROM params WHERE cat='calib' GROUP BY sys_id")}
        sys_rows = []
        for sid, name, level in c.execute("SELECT system_id, name, level FROM subsystems ORDER BY ord"):
            if sid == "plat":
                continue
            sys_rows.append((sid, name, level))
        # 每系统: D=该层断言数 (L2/L3/L4), C=该系统的标定参数, M=按层摊 (L2 承担感知/取流 → 平台层计入)
        for sid, name, level in sys_rows:
            _lv = {"sys0": "L2", "sys1": "L3", "sys2": "L4"}.get(sid, "")
            d_ = lv.get(_lv, 0)
            c_ = sadm.get(sid, 0)
            m_ = 0
            if sid == "sys0":
                m_ = n_m          # 测量量: 位姿/关节/深度/力/触觉 由 L2 基石执行真正落数
            c.execute("INSERT OR REPLACE INTO mcd VALUES (?,?,?,?,?,?,?)",
                      ("system", sid, name, m_, c_, d_, "%s · 断言 %s 条 · 标定参数取自 zmax_calib.json" % (level, _lv)))
        c.execute("INSERT OR REPLACE INTO mcd VALUES (?,?,?,?,?,?,?)",
                  ("product", "Z-MAX", "Z-MAX 平台产品", n_m, n_c, n_d,
                   "产品级 MCD: 测量 %d 项(帧龄<2s) · 标定 %d 项 · 诊断 %d 断言 + 故障码 MCD-E0x"
                   % (n_m, n_c, n_d)))
        c.execute("INSERT OR REPLACE INTO mcd VALUES (?,?,?,?,?,?,?)",
                  ("platform", "plat", "平台支撑 (跨子系统)", n_m, n_c, n_d, "数据源/质量门/观察器 — 平台统一治理"))
    except Exception as _e:                                                    # noqa: BLE001
        print("[engineering_db] MCD 计算失败: %r" % (_e,))

    con.commit()
    for t in ("platform", "products", "product_features", "subsystems", "subsystem_axes", "functions",
              "fn_axes", "calib_params", "modules", "module_code", "capability_dbc",
              "verification_features", "interfaces", "links", "canvas_nodes", "canvas_links",
              "project_sections", "library_removed", "params", "param_events", "param_links", "mcd"):
        cnt[t] = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
    con.close()
    if not quiet:
        print("✅ 建库完成: %s (%.2f MB)" % (db, os.path.getsize(db) / 1048576))
        for k, v in cnt.items():
            print("   %-22s %d" % (k, v))
    return cnt


# ── 改数事件 (运行时唯一留痕处 = 本库 param_events 表; 没有 param_events.jsonl) ──
def log_param_event(ev, db=DB_DEFAULT):
    """把一条改数事件写进唯一工程库的 param_events 表 (运行时唯一留痕处, 没有 jsonl)。

    ev: {param, cn, old, new, unit, cat, source, written, msg} —— 由 param_registry._log_event 调用。
    返回 True/False (库不可写时不抛, 只报错 —— 改数本身已经落真源, 留痕失败不该让改数看起来失败)。
    """
    try:
        os.makedirs(os.path.dirname(db), exist_ok=True)
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE IF NOT EXISTS param_events(ts TEXT, param_id TEXT, cn TEXT, "
                    "old_val TEXT, new_val TEXT, cat TEXT, source TEXT, written INT, msg TEXT)")
        con.execute("INSERT INTO param_events VALUES (?,?,?,?,?,?,?,?,?)",
                    (ev.get("ts") or time.strftime("%Y-%m-%d %H:%M:%S"), ev.get("param"), ev.get("cn"),
                     _j(ev.get("old")), _j(ev.get("new")), ev.get("cat"), ev.get("source"),
                     1 if ev.get("written") else 0, ev.get("msg", "")))
        con.commit()
        con.close()
        return True
    except Exception as e:                                                          # noqa: BLE001
        print("[engineering_db] 事件留痕失败: %r" % (e,))
        return False


def read_param_events(limit=None, db=DB_DEFAULT):
    """读改数事件 (新→旧)。limit=None 读全部。库不存在/表不存在 ⇒ 空表。"""
    try:
        con = sqlite3.connect(db)
        sql = "SELECT ts, param_id, cn, old_val, new_val, cat, source, written, msg FROM param_events"
        if limit:
            sql += " ORDER BY rowid DESC LIMIT %d" % int(limit)
            rows = con.execute(sql).fetchall()
        else:
            rows = con.execute(sql + " ORDER BY rowid").fetchall()
        con.close()
        return [dict(zip(("ts", "param", "cn", "old", "new", "cat", "source", "written", "msg"), r)) for r in rows]
    except Exception:                                                               # noqa: BLE001
        return []


def count_param_events(db=DB_DEFAULT):
    try:
        con = sqlite3.connect(db)
        n = con.execute("SELECT COUNT(*) FROM param_events").fetchone()[0]
        con.close()
        return n
    except Exception:                                                               # noqa: BLE001
        return 0


# ── 判据 ──────────────────────────────────────────────────────────────────
def check(db=DB_DEFAULT):
    con = sqlite3.connect(db)
    c = con.cursor()
    bad = []

    def q1(s, *a):
        return c.execute(s, a).fetchone()[0]

    # ① 每个产品特征必须挂到已存在的子系统
    miss = c.execute("SELECT DISTINCT l.src_id FROM links l WHERE l.src_type='product_feature' "
                     "AND l.kind='归属' AND l.dst_id NOT IN (SELECT system_id FROM subsystems)").fetchall()
    print(("  ❌ " if miss else "  ✅ ") + "① 产品特征→子系统 全部命中 (%d 个悬空)" % len(miss), flush=True)
    if miss:
        bad.append("pf→subsys %s" % miss[:3])
    # ② 每条功能必须对应模块库里的模块
    miss2 = c.execute("SELECT DISTINCT l.src_id, l.dst_id FROM links l WHERE l.src_type='function' "
                      "AND l.kind='对应模块' AND l.dst_id NOT IN (SELECT name FROM canvas_nodes)").fetchall()
    print(("  ❌ " if miss2 else "  ✅ ") + "② 功能→模块 全部命中画布/模块库 (%d 个悬空)" % len(miss2), flush=True)
    if miss2:
        bad.append("fn→module %s" % miss2[:3])
    # ③ 三轴不得为空 (每条功能 cfg/cal/dia 都覆盖)
    nfn = q1("SELECT COUNT(*) FROM functions")
    for ax in ("cfg", "cal", "dia"):
        k = q1("SELECT COUNT(DISTINCT fn_id) FROM fn_axes WHERE axis=?", ax)
        ok = k >= nfn
        print(("  ✅ " if ok else "  ❌ ") + "③ 功能三轴 %s 覆盖 %d/%d" % (ax, k, nfn), flush=True)
        if not ok:
            bad.append("axis %s %d/%d" % (ax, k, nfn))
    # ④ 能力引用必须存在于 feature.dbc
    miss4 = c.execute("SELECT DISTINCT l.dst_id FROM links l WHERE l.src_type='product_feature' "
                      "AND l.kind='能力引用' AND l.dst_id NOT IN (SELECT bo_id FROM capability_dbc)").fetchall()
    print(("  ❌ " if miss4 else "  ✅ ") + "④ 特征→能力(BO_) 全部命中 feature.dbc (%d 个悬空)" % len(miss4), flush=True)
    if miss4:
        bad.append("cap %s" % miss4[:3])
    # ⑤ 工程 7 段齐 (缺段只在没有 .proj 时才允许)
    secs = [r[0] for r in c.execute("SELECT section FROM project_sections").fetchall()]
    want = ["canvas", "pane", "calib", "measure", "mparam", "task", "meta"]
    miss5 = [s for s in want if s not in secs]
    print(("  ✅ " if not miss5 else "  ❌ ") + "⑤ 工程段齐 (%d/7%s)" %
          (len([s for s in want if s in secs]), "" if not miss5 else " 缺 " + str(miss5)), flush=True)
    if miss5:
        bad.append("sections %s" % miss5)
    # ⑤b 功能数必须 == 画布功能节点数 (一行一子系统, 不重复计数)
    nfn2 = q1("SELECT COUNT(*) FROM functions")
    ncn = q1("SELECT COUNT(*) FROM canvas_nodes")
    print(("  ✅ " if nfn2 == ncn else "  ❌ ") + "⑤b 功能 %d == 画布功能节点 %d (无重复计数)" % (nfn2, ncn), flush=True)
    if nfn2 != ncn:
        bad.append("fn %d != nodes %d" % (nfn2, ncn))
    dupn = q1("SELECT COUNT(*) FROM (SELECT name FROM functions GROUP BY name HAVING COUNT(*)>1)")
    print(("  ✅ " if not dupn else "  ❌ ") + "⑤c 同名功能 %d 条 (每节点只算一次)" % dupn, flush=True)
    if dupn:
        bad.append("dup fn %d" % dupn)

    # ⑥ 数据库 ↔ 真源 哈希一致 (重建幂等)
    srcs = json.loads(q1("SELECT v FROM meta WHERE k='sources'"))
    drift = []
    for name, (path, h) in srcs.items():
        if not path or not os.path.exists(path):
            continue
        now = _sha(_read(path) or "")
        if h and now != h:
            drift.append(name)
    print(("  ✅ " if not drift else "  ❌ ") + "⑥ 库与真源一致 (漂移 %s)" % (drift or "无"), flush=True)
    if drift:
        bad.append("drift %s" % drift)
    # ⑦ 模块→代码 链接非空
    nmod = q1("SELECT COUNT(*) FROM modules")
    ncode = q1("SELECT COUNT(DISTINCT module_name) FROM module_code")
    print("  ✅ ⑦ 模块 %d 个, 其中 %d 个链到引擎代码真源 (%s)" %
          (nmod, ncode, q1("SELECT COUNT(*) FROM module_code") and "nodes/library.py"), flush=True)
    # ⑧ 参数面: 全局可改数字 (系统 ↔ 功能 ↔ 代码 同步的数据面)
    try:
        n_par = q1("SELECT COUNT(*) FROM params")
        n_wr = q1("SELECT COUNT(*) FROM params WHERE writable=1")
        n_gap = q1("SELECT COUNT(*) FROM params WHERE status LIKE '%缺口%' OR status LIKE '%未定义%'")
        n_def = q1("SELECT COUNT(*) FROM params WHERE min IS NOT NULL AND status NOT LIKE '%未定义%'")
        print("  %s ⑧ 全局可改数字 %d 个 (可写 %d · 明确范围 %d · 未定/缺口 %d)" %
              ("✅" if n_par >= 100 else "❌", n_par, n_wr, n_def, n_gap), flush=True)
        if n_par < 100:
            bad.append("params<100")
        srcs_p = [r[0] for r in con.execute("SELECT DISTINCT source FROM params").fetchall()]
        miss_p = [s_ for s_ in srcs_p if not os.path.exists(os.path.join(ROOT, s_))]
        print("  %s ⑧b 每个数字的真源都在盘上 (%d 个来源%s)" %
              ("✅" if not miss_p else "❌", len(srcs_p), "" if not miss_p else " 缺:" + str(miss_p)), flush=True)
        if miss_p:
            bad.append("param_src_missing %s" % miss_p)
        n_link = q1("SELECT COUNT(*) FROM param_links")
        print("  %s ⑧c 数字→功能/模块/系统 链接 %d 条" % ("✅" if n_link >= n_par * 2 else "❌", n_link), flush=True)
    except Exception as _e:                                                   # noqa: BLE001
        print("  ❌ ⑧ 参数面判据异常: %r" % (_e,), flush=True)
        bad.append("param_judge")

    # ⑨ MCD 三轴 (测量/标定/诊断) 用数据定义产品框架
    try:
        rows = c.execute("SELECT scope, scope_id, scope_cn, m, c, d FROM mcd ORDER BY scope, scope_id").fetchall()
        pr_row = next((r for r in rows if r[0] == "product"), None)
        ok9 = bool(pr_row) and pr_row[3] > 0 and pr_row[4] > 0 and pr_row[5] > 0
        print("  %s ⑨ MCD 三轴 %d 层: 产品 M%d/C%d/D%d · 系统 %s" %
              ("✅" if ok9 else "❌", len(rows), pr_row[3] if pr_row else -1, pr_row[4] if pr_row else -1,
               pr_row[5] if pr_row else -1,
               " ".join("%s M%d/C%d/D%d" % (r[1], r[3], r[4], r[5]) for r in rows if r[0] == "system")), flush=True)
        if not ok9:
            bad.append("mcd")
    except Exception as _e:                                                   # noqa: BLE001
        print("  ❌ ⑨ MCD 判据异常: %r" % (_e,), flush=True)
        bad.append("mcd_judge")

    print("  📦 单文件: %s (%.2f MB)" % (db, os.path.getsize(db) / 1048576), flush=True)
    con.close()
    print(("✅ 判据全绿" if not bad else "❌ 判据失败: %s" % bad), flush=True)
    return 0 if not bad else 1


# ── 查询 / 导出 / 加载 ────────────────────────────────────────────────────
def query(q, db=DB_DEFAULT):
    con = sqlite3.connect(db)
    c = con.cursor()
    q = (q or "").strip()
    if q.startswith("product "):
        pid = q.split()[1]
        rows = c.execute("SELECT pf_id,title,kpi,status,subsys,module_refs FROM product_features "
                         "WHERE product_id=?", (pid,)).fetchall()
        p = c.execute("SELECT name,positioning,kpi FROM products WHERE product_id=?", (pid,)).fetchone()
        print("■ %s — %s" % (pid, (p or ("",))[0]))
        if p:
            print("  定位: %s\n  KPI: %s" % (p[1], p[2]))
        for r in rows:
            print("  [%s] %s\n      KPI: %s · 状态 %s · 子系统 %s\n      模块: %s" % r)
    elif q.startswith("system "):
        sid = q.split()[1]
        s = c.execute("SELECT name,level,role,rows FROM subsystems WHERE system_id=?", (sid,)).fetchone()
        print("■ %s" % (s[0] if s else sid))
        if s:
            print("  %s · %s\n  行: %s" % (s[1], s[2], s[3]))
            for ax in ("cfg", "cal", "dia"):
                print("  ── %s ──" % ax.upper())
                for r in c.execute("SELECT item FROM subsystem_axes WHERE system_id=? AND axis=? ORDER BY idx",
                                   (sid, ax)).fetchall():
                    print("     · " + r[0])
            n = c.execute("SELECT COUNT(*) FROM functions WHERE system_id=?", (sid,)).fetchone()[0]
            print("  功能 %d 条" % n)
    elif q.startswith("fn "):
        fid = q.split()[1]
        f = c.execute("SELECT name,system_id,layer,params,source FROM functions WHERE fn_id=?", (fid,)).fetchone()
        print("■ %s" % (f[0] if f else fid))
        if f:
            for r in c.execute("SELECT axis,item,src FROM fn_axes WHERE fn_id=? ORDER BY axis,idx", (fid,)).fetchall():
                print("   [%s] %s  (%s)" % r)
    elif q == "modules":
        for r in c.execute("SELECT name,kind,group_name FROM modules ORDER BY group_name,name").fetchall():
            print("  %s  [%s] %s" % r)
    elif q == "products":
        for r in c.execute("SELECT product_id,name,category,kpi FROM products").fetchall():
            print("  %s  %s  (%s)\n      %s" % r)
    elif q.startswith("sql "):
        for r in c.execute(q[4:]).fetchall():
            print("  " + str(r))
    else:
        print("用法: product <id> | system <id> | fn <id> | products | modules | sql <SELECT…>")
    con.close()
    return 0


def load(db=DB_DEFAULT):
    """给 GUI/服务用的统一加载: 一次拿到 平台 + 工程 + 图 (不需要 GUI 依赖)"""
    con = sqlite3.connect(db)
    c = con.cursor()
    out = {"meta": dict(c.execute("SELECT k,v FROM meta").fetchall())}
    out["platform"] = dict(zip(("platform_id", "name", "positioning", "architecture", "data_contract"),
                               c.execute("SELECT * FROM platform").fetchone() or ("",) * 5))
    cols = ("product_id", "name", "category", "positioning", "kpi", "subsystems")
    out["products"] = [dict(zip(cols, r)) for r in c.execute(
        "SELECT product_id,name,category,positioning,kpi,subsystems FROM products").fetchall()]
    out["subsystems"] = [dict(zip(("system_id", "name", "level", "role", "hardware", "kpi", "rows"), r))
                         for r in c.execute("SELECT system_id,name,level,role,hardware,kpi,rows FROM subsystems "
                                            "ORDER BY ord").fetchall()]
    out["axes"] = {}
    for r in c.execute("SELECT system_id,axis,item FROM subsystem_axes ORDER BY system_id,axis,idx").fetchall():
        out["axes"].setdefault(r[0], {}).setdefault(r[1], []).append(r[2])
    out["product_features"] = [dict(zip(("pf_id", "product_id", "title", "capability_ref", "kpi",
                                         "status", "desc", "subsys", "module_refs"), r))
                               for r in c.execute("SELECT * FROM product_features").fetchall()]
    out["functions"] = [dict(zip(("fn_id", "system_id", "name", "layer", "kind", "row_name",
                                  "module_ref", "params", "source"), r))
                        for r in c.execute("SELECT * FROM functions ORDER BY system_id,fn_id").fetchall()]
    out["fn_axes"] = {}
    for r in c.execute("SELECT fn_id,axis,item FROM fn_axes ORDER BY fn_id,axis,idx").fetchall():
        out["fn_axes"].setdefault(r[0], {}).setdefault(r[1], []).append(r[2])
    out["modules"] = [dict(zip(("name", "kind", "group_name", "params", "verif_layer", "source"), r))
                      for r in c.execute("SELECT * FROM modules").fetchall()]
    out["module_code"] = [dict(zip(("module_name", "logic_key", "file", "line", "doc", "match"), r))
                          for r in c.execute("SELECT * FROM module_code").fetchall()]
    out["calib"] = [dict(zip(("path", "key", "value", "unit", "src", "status"), r))
                    for r in c.execute("SELECT * FROM calib_params").fetchall()]
    out["capabilities"] = [dict(zip(("bo_id", "grp", "name", "dirs", "brief", "explain", "iface",
                                     "inputs", "outputs", "scenes", "engineering", "owner"), r))
                           for r in c.execute("SELECT * FROM capability_dbc").fetchall()]
    out["verification"] = [dict(zip(("f_id", "domain", "name", "where", "how", "case_id", "level"), r))
                           for r in c.execute("SELECT * FROM verification_features").fetchall()]
    out["links"] = [dict(zip(("src_type", "src_id", "dst_type", "dst_id", "kind"), r))
                    for r in c.execute("SELECT * FROM links").fetchall()]
    out["project"] = {r[0]: json.loads(r[1]) for r in
                      c.execute("SELECT section,json FROM project_sections").fetchall()}
    out["canvas"] = {"nodes": [dict(zip(("name", "type", "x", "y", "w", "h", "params"), r))
                               for r in c.execute("SELECT name,type,x,y,w,h,params FROM canvas_nodes").fetchall()],
                     "links": [dict(zip(("src", "dst", "kind"), r)) for r in
                               c.execute("SELECT src,dst,kind FROM canvas_links").fetchall()]}
    con.close()
    return out


def export_json(out_path, db=DB_DEFAULT):
    d = load(db)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("✅ 导出 %s (%.2f MB, 段: %s)" % (out_path, os.path.getsize(out_path) / 1048576,
                                            ",".join(sorted(d["project"].keys()))))
    return 0


def stats(db=DB_DEFAULT):
    con = sqlite3.connect(db)
    print("📦 %s (%.2f MB)" % (db, os.path.getsize(db) / 1048576))
    for (t, ) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
        n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        if n:
            print("   %-24s %d" % (t, n))
    con.close()
    return 0


# ── 只读服务 ──────────────────────────────────────────────────────────────
def serve(port=8798, db=DB_DEFAULT):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer               # noqa: E402
    D = load(db)

    def payload(tag, obj):
        return json.dumps({"ok": True, "tag": tag, "built_at": D["meta"].get("built_at"),
                           "data": obj}, ensure_ascii=False).encode("utf-8")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):                                                # noqa: A003
            pass

        def do_GET(self):                                                         # noqa: N802
            p = self.path.split("?")[0].rstrip("/")
            try:
                if p in ("", "/", "/platform"):
                    body = payload("platform", {"platform": D["platform"], "products": D["products"],
                                                "subsystems": D["subsystems"], "axes": D["axes"]})
                elif p == "/summary":
                    body = payload("summary", {k: (len(v) if isinstance(v, (list, dict)) else v)
                                               for k, v in D.items() if k != "meta"})
                elif p == "/products":
                    body = payload("products", D["products"])
                elif p.startswith("/product/"):
                    pid = p.split("/")[2]
                    body = payload("product", {"product": [x for x in D["products"] if x["product_id"] == pid],
                                               "features": [x for x in D["product_features"] if x["product_id"] == pid]})
                elif p == "/systems":
                    body = payload("systems", D["subsystems"])
                elif p.startswith("/system/"):
                    sid = p.split("/")[2]
                    body = payload("system", {"system": [x for x in D["subsystems"] if x["system_id"] == sid],
                                              "axes": D["axes"].get(sid, {}),
                                              "functions": [x for x in D["functions"] if x["system_id"] == sid]})
                elif p == "/functions":
                    body = payload("functions", D["functions"])
                elif p.startswith("/function/"):
                    fid = p.split("/")[2]
                    body = payload("function", {"function": [x for x in D["functions"] if x["fn_id"] == fid],
                                                "axes": D["fn_axes"].get(fid, {})})
                elif p == "/modules":
                    body = payload("modules", D["modules"])
                elif p == "/capabilities":
                    body = payload("capabilities", D["capabilities"])
                elif p == "/calib":
                    body = payload("calib", D["calib"])
                elif p == "/project":
                    body = payload("project", D["project"])
                elif p.startswith("/project/"):
                    sec = p.split("/")[2]
                    body = payload("project:" + sec, D["project"].get(sec, {}))
                elif p == "/graph":
                    body = payload("graph", {"links": D["links"], "canvas": D["canvas"]})
                elif p == "/sync":
                    body = payload("sync", {"module_code": D["module_code"], "sources": json.loads(D["meta"]["sources"])})
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'{"ok":false,"error":"not found"}')
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:                                                # noqa: BLE001
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())

    srv = ThreadingHTTPServer(("127.0.0.1", int(port)), H)
    print("📡 工程数据库只读服务 http://127.0.0.1:%d/  (/summary /platform /products /systems /functions /graph /project …)" % port)
    print("   库: %s" % db, flush=True)
    srv.serve_forever()
    return 0


def main():
    ap = argparse.ArgumentParser(description="Z-MAX 工程数据库 (单一文件承载全部工程数据)")
    ap.add_argument("cmd", nargs="?", default="stats",
                    choices=["build", "check", "stats", "query", "load", "serve", "migrate"])
    ap.add_argument("arg", nargs="?", default="")
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--project", default=None)
    ap.add_argument("--port", type=int, default=8798)
    a = ap.parse_args()
    if a.cmd == "build":
        return 0 if build(a.db, a.project) else 1
    if a.cmd == "check":
        return check(a.db)
    if a.cmd == "stats":
        return stats(a.db)
    if a.cmd == "query":
        return query(a.arg, a.db)
    if a.cmd == "load":
        return export_json(a.arg or os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.json"), a.db)
    if a.cmd == "serve":
        return serve(a.port, a.db)
    if a.cmd == "migrate":
        import shutil
        shutil.copy2(a.db, a.arg)
        print("✅ 已迁移库文件 → %s (%.2f MB)" % (a.arg, os.path.getsize(a.arg) / 1048576))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
