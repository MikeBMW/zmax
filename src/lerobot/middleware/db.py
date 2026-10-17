# -*- coding: utf-8 -*-
"""中间件工程库 (SQLite 单文件 = 一套工程) —— 节点/端口/连线/**话题名**的落库真源。

为什么要有这一层 (工程化口径)
------------------------------
画布 JSON 是**人编辑**的真源, 但 DDS/监控/CI 这些系统需要一张**可查询的注册表**:
   · 话题名到底叫什么 (ss.node.<node>.<port>) —— 以前是运行时用字符串拼出来的, 磁盘上没有,
     外部工具想知道全量话题只能把工程跑起来;
   · 谁连到谁 (端口级) —— 现在只在 JSON 的 links 里, 用 SQL 查不了。

这里的做法: 画布 JSON 一变 (sha256 变) → 解析成 NodeSpec → **同步进库**;
加载工程时优先**从库读** (db 与 json 同源, 谁都不是二手); 话题名以 mw_topic 表为准。

表
--
  mw_project(project PK, canvas_sha, canvas_path, built_at, node_n, link_n, topic_n)
  mw_node(project, node_id, name, type, module, layer, exec_mode, impl_key, source,
          symbol, x, y, params_json, PK(project,node_id))
  mw_port(project, node_id, port, dir, label, dtype, PK(project,node_id,port,dir))
  mw_link(project, link_id, f, f_port, t, t_port, label, PK(project,link_id))
  mw_topic(project, node_id, port, dir, topic, qos, enabled, PK(project,node_id,port,dir))

用法
----
    from lerobot.middleware import db
    db.sync(specs, links, canvas_path)          # 画布 → 库 (幂等)
    specs, links, meta = db.load("state_space_obs")
命令行: tools/mw_db.py status|sync|topics|sql
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time

from . import spec as spec_mod
from .bus import TOPIC_PREFIX, bus_enabled

DEFAULT_DB = "data/database/zmax/zmax_engineering.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS mw_project (
    project      TEXT PRIMARY KEY,
    canvas_sha   TEXT,
    canvas_path  TEXT,
    built_at     TEXT,
    node_n       INTEGER DEFAULT 0,
    link_n       INTEGER DEFAULT 0,
    topic_n      INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mw_node (
    project     TEXT,
    node_id     TEXT,
    name        TEXT,
    type        TEXT,
    module      TEXT,
    layer       TEXT,
    exec_mode   TEXT,
    impl_key    TEXT,
    source      TEXT,
    symbol      TEXT,
    x           REAL,
    y           REAL,
    params_json TEXT,
    PRIMARY KEY (project, node_id)
);
CREATE TABLE IF NOT EXISTS mw_port (
    project  TEXT,
    node_id  TEXT,
    port     TEXT,
    dir      TEXT,
    label    TEXT,
    dtype    TEXT,
    PRIMARY KEY (project, node_id, port, dir)
);
CREATE TABLE IF NOT EXISTS mw_link (
    project  TEXT,
    link_id  TEXT,
    f        TEXT,
    f_port   TEXT,
    t        TEXT,
    t_port   TEXT,
    label    TEXT,
    PRIMARY KEY (project, link_id)
);
CREATE TABLE IF NOT EXISTS mw_topic (
    project  TEXT,
    node_id  TEXT,
    port     TEXT,
    dir      TEXT,
    topic    TEXT,
    qos      TEXT,
    enabled  INTEGER DEFAULT 1,
    PRIMARY KEY (project, node_id, port, dir)
);
CREATE TABLE IF NOT EXISTS mw_signal (
    project   TEXT,
    node_id   TEXT,
    port      TEXT,
    signal    TEXT,
    unit      TEXT,
    vmin      REAL,
    vmax      REAL,
    dtype     TEXT,
    src       TEXT,                     -- 声明 | 实测 | 参数中心 | 端口整体值(未声明)
    param_id  TEXT,                     -- 参数中心里对应的参数 (unit/range 来源)
    PRIMARY KEY (project, node_id, port, signal)
);
CREATE INDEX IF NOT EXISTS ix_mw_topic_name ON mw_topic(topic);
CREATE INDEX IF NOT EXISTS ix_mw_signal_name ON mw_signal(project, node_id, port);
"""


# ─────────────────────────── 连接 / 路径 ───────────────────────────
def db_path(path=None):
    """工程库路径: 显式 → env ZMAX_MW_DB → 仓库 data/database/zmax/zmax_engineering.db。"""
    if path:
        return os.path.abspath(path)
    env = os.environ.get("ZMAX_MW_DB")
    if env:
        return os.path.abspath(env)
    try:
        from lerobot.engineering import paths as _paths        # noqa: PLC0415
        root = _paths.REPO_ROOT
    except Exception:                                          # noqa: BLE001
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(root, DEFAULT_DB)


def connect(path=None):
    p = db_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p, timeout=10)
    conn.executescript(SCHEMA)
    return conn


def project_of(canvas_path=None):
    """工程名 = 画布文件名 (state_space_obs.json → state_space_obs)。"""
    p = canvas_path or spec_mod.find_canvas()
    return os.path.splitext(os.path.basename(str(p)))[0]


def canvas_sha(canvas_path=None):
    p = canvas_path or spec_mod.find_canvas()
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:                                          # noqa: BLE001
        return ""


def _topic(node_id, port):
    return "%s.%s.%s" % (TOPIC_PREFIX, node_id, port)


# ─────────────────────────── 画布 → 库 ───────────────────────────
def sync(specs, links, canvas_path=None, project=None, quiet=True):
    """把一份工程 (specs+links) 落库。幂等: 同一画布重复同步不产生重复行。"""
    project = project or project_of(canvas_path)
    sha = canvas_sha(canvas_path)
    dds_on, _why = bus_enabled()
    qos = "reliable/transient_local" if dds_on else "shm"
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM mw_node  WHERE project=?", (project,))
        cur.execute("DELETE FROM mw_port  WHERE project=?", (project,))
        cur.execute("DELETE FROM mw_link  WHERE project=?", (project,))
        cur.execute("DELETE FROM mw_topic WHERE project=?", (project,))
        cur.execute("DELETE FROM mw_signal WHERE project=?", (project,))
        n_port = n_topic = n_sig = 0
        for s in specs:
            cur.execute(
                "INSERT INTO mw_node VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (project, s.id, s.name, s.type, s.module_name, s.layer, s.exec_mode,
                 s.impl_key, s.source, s.source_symbol, float(s.x), float(s.y),
                 json.dumps(s.params or {}, ensure_ascii=False)))
            for d, ports in (("in", s.inputs), ("out", s.outputs)):
                for p in ports:
                    cur.execute("INSERT INTO mw_port VALUES (?,?,?,?,?,?)",
                                (project, s.id, p, d, (s.port_labels or {}).get(p, ""), "any"))
                    cur.execute("INSERT INTO mw_topic VALUES (?,?,?,?,?,?,?)",
                                (project, s.id, p, d, _topic(s.id, p), qos, 1 if dds_on else 0))
                    n_port += 1
                    n_topic += 1
        # 📨 信号登记: 端口是报文, 报文里的字段才是信号。
        #   来源优先级: 节点模块/画布 params 里的 _signals (声明) > 端口整体值 (未声明, 占位一条)。
        #   单位/量程由**参数中心** (params 表) 补齐 —— 见 _param_meta()。
        for s_ in specs:
            for p_ in s_.outputs:
                sigs = ((s_.params or {}).get("_signals") or {}).get(p_) or []
                if not sigs:
                    sigs = [{"name": "value", "dtype": "any", "src": "端口整体值(未声明)"}]
                for sg in sigs:
                    nm = str(sg.get("name") or "value")
                    unit, vmin, vmax, pid = _param_meta(".".join([s_.id, p_, nm]),
                                                       getattr(s_, "impl_key", "") or "", nm)
                    cur.execute("INSERT OR REPLACE INTO mw_signal VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (project, s_.id, p_, nm, sg.get("unit") or unit,
                                 sg.get("vmin", vmin), sg.get("vmax", vmax),
                                 str(sg.get("dtype") or "any"),
                                 str(sg.get("src") or ("声明" if sg.get("unit") else "端口整体值(未声明)")),
                                 pid))
                    n_sig += 1
        for l in links:
            cur.execute("INSERT INTO mw_link VALUES (?,?,?,?,?,?,?)",
                        (project, str(l.get("id") or "%s.%s->%s.%s" % (l["f"], l["f_port"], l["t"], l["t_port"])),
                         l["f"], l["f_port"], l["t"], l["t_port"], str(l.get("label") or "")))
        cur.execute("INSERT OR REPLACE INTO mw_project VALUES (?,?,?,?,?,?,?)",
                    (project, sha, str(canvas_path or spec_mod.find_canvas()),
                     time.strftime("%Y-%m-%d %H:%M:%S"), len(specs), len(links), n_topic))
        conn.commit()
        if not quiet:
            print("💾 落库 %s: 节点 %d · 连线 %d · 端口 %d · 话题 %d (sha %s)"
                  % (project, len(specs), len(links), n_port, n_topic, sha))
        return {"project": project, "nodes": len(specs), "links": len(links),
                "ports": n_port, "topics": n_topic, "signals": n_sig, "sha": sha}
    finally:
        conn.close()


def _param_meta(key, impl_key="", sig=""):
    """参数中心 (params 表) 里给某个信号找 单位/量程: 返回 (unit, vmin, vmax, param_id)。

    🔴 只认**有区分度**的键: 端口整体值占位 (signal='value') 不参与匹配 ——
    实测过它会乱命中 (value → calib:plane_z.value), 那种"凑出来的单位"比空着更坏。
    """
    keys = []
    if sig and sig not in ("value",):
        keys.append(key)                     # <node>.<port>.<signal>
        if impl_key:
            keys.append("%s.%s" % (impl_key, sig))   # ss_sched.phase
            keys.append(impl_key)                    # 节点级参数 (impl 名下)
    if not keys:
        return "", None, None, ""
    try:
        conn = connect()
        try:
            for k in keys:
                r = conn.execute(
                    "SELECT unit, min, max, param_id FROM params "
                    "WHERE lower(param_id) LIKE ? ORDER BY length(param_id) LIMIT 1",
                    ("%" + k.lower() + "%",)).fetchone()
                if r:
                    return (r[0] or ""), (r[1] if r[1] is not None else None), \
                           (r[2] if r[2] is not None else None), (r[3] or "")
        finally:
            conn.close()
    except Exception:                                          # noqa: BLE001
        pass
    return "", None, None, ""


def links(project=None, canvas_path=None):
    """连线表 (画布实际连线, 已落库)。"""
    project = project or project_of(canvas_path)
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM mw_link WHERE project=? ORDER BY link_id", (project,))]
    finally:
        conn.close()


def signals(project=None, canvas_path=None):
    """信号注册表: 每个信号一行 (报文=node.port, 信号=字段)。"""
    project = project or project_of(canvas_path)
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM mw_signal WHERE project=? ORDER BY node_id, port, signal", (project,))]
    finally:
        conn.close()


LAYER_ORDER = ("L1", "L2", "L3", "L4", "L5", "meta")


def _level_map():
    """节点 id → 层 (画布节点的 layer 字段为空时用它兜底; 真源 = 工程档位索引)。"""
    try:
        from lerobot.engineering.nodes.by_level import LEVELS_INDEX
        m = {}
        for lv, items in LEVELS_INDEX.items():
            for it in items:
                if it and it[0]:
                    m[it[0]] = lv
        return m
    except Exception:                                          # noqa: BLE001
        return {}


def node_rows(project=None, canvas_path=None):
    """每个节点一行: 输入话题 (端口 ← 上游) / 输出话题 (端口 → 下游)。

    这张表就是「全局数据空间」跟画布实际配置对齐的那张 ——
    老倪口径: 数据空间显示的必须是画布/配置中心里的实际配置, 不是另抄一份。
    """
    project = project or project_of(canvas_path)
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        nodes = {r["node_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM mw_node WHERE project=?", (project,))}
        tps = [dict(r) for r in conn.execute(
            "SELECT * FROM mw_topic WHERE project=? ORDER BY dir, port", (project,))]
        lks = [dict(r) for r in conn.execute(
            "SELECT * FROM mw_link WHERE project=?", (project,))]
    finally:
        conn.close()
    up = {}          # (dst_node, dst_in_port) → [src_node]
    down = {}        # (src_node, src_out_port) → [dst_node]
    for l in lks:
        up.setdefault((l["t"], l["t_port"]), []).append(l["f"])
        down.setdefault((l["f"], l["f_port"]), []).append(l["t"])
    lvmap = _level_map()
    rows = []
    for nid, n in sorted(nodes.items()):
        ins, outs = [], []
        for t in tps:
            if t["node_id"] != nid:
                continue
            if t["dir"] == "in":
                ins.append({"port": t["port"], "topic": t["topic"], "qos": t["qos"],
                            "enabled": t["enabled"], "from": up.get((nid, t["port"]), [])})
            else:
                outs.append({"port": t["port"], "topic": t["topic"], "qos": t["qos"],
                             "enabled": t["enabled"], "to": down.get((nid, t["port"]), [])})
        rows.append({"node_id": nid, "name": n["name"], "module": n["module"], "type": n["type"],
                     "layer": (n.get("layer") or lvmap.get(nid) or "meta"), "exec_mode": n.get("exec_mode") or "",
                     "impl_key": n.get("impl_key") or "", "source": n.get("source") or "",
                     "ins": ins, "outs": outs})
    return rows


def message_rows(project=None, canvas_path=None):
    """报文视图: 每个**输出话题**一条 message, 带它的信号清单。

    message (报文) = 一个端口的一帧 (topic, 周期=节点节拍, 载荷=JSON)
    signal  (信号) = 载荷里的一个字段 (名/单位/量程来自 参数中心, 值来自实测)
    """
    project = project or project_of(canvas_path)
    sigs = {}
    for s_ in signals(project):
        sigs.setdefault((s_["node_id"], s_["port"]), []).append(s_)
    rows = []
    for n in node_rows(project):
        for o in n["outs"]:
            rows.append({
                "topic": o["topic"], "node_id": n["node_id"], "node": n["name"],
                "layer": n.get("layer") or "meta",
                "port": o["port"], "qos": o["qos"], "enabled": o["enabled"],
                "consumers": o["to"], "n_signal": len(sigs.get((n["node_id"], o["port"]), [])),
                "signals": sigs.get((n["node_id"], o["port"]), []),
            })
    return rows


# ─────────────────────────── 库 → 规格 ───────────────────────────
def _row_spec(r):
    """mw_node 行 → NodeSpec (端口从 mw_port 回填)。"""
    (pid, nid, name, typ, module, layer, mode, key, src, sym, x, y, pjson) = r
    sp = spec_mod.NodeSpec(id=nid, name=name or nid, type=typ or "node")
    sp.x, sp.y = int(x or 0), int(y or 0)
    sp.exec_mode = mode or "pure"
    sp.impl_key = key or ""
    sp.source = src or ""
    sp.source_symbol = sym or ""
    try:
        sp.params = json.loads(pjson or "{}")
    except Exception:                                          # noqa: BLE001
        sp.params = {}
    return sp


def load(project=None, canvas_path=None):
    """从库读回 (specs, links, meta)。库里没有这套工程 → 抛 KeyError。"""
    project = project or project_of(canvas_path)
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM mw_project WHERE project=?", (project,)).fetchone()
        if row is None:
            raise KeyError("库里没有工程 %s" % project)
        specs = [_row_spec(tuple(r)) for r in conn.execute(
            "SELECT project,node_id,name,type,module,layer,exec_mode,impl_key,source,symbol,x,y,params_json "
            "FROM mw_node WHERE project=? ORDER BY node_id", (project,))]
        by_id = {s.id: s for s in specs}
        for r in conn.execute("SELECT node_id,port,dir,label FROM mw_port WHERE project=?", (project,)):
            s = by_id.get(r["node_id"])
            if s is None:
                continue
            (s.inputs if r["dir"] == "in" else s.outputs).append(r["port"])
            if r["label"]:
                s.port_labels[r["port"]] = r["label"]
        links = [{"id": r["link_id"], "f": r["f"], "t": r["t"], "f_port": r["f_port"],
                  "t_port": r["t_port"], "label": r["label"]}
                 for r in conn.execute("SELECT * FROM mw_link WHERE project=?", (project,))]
        meta = {"source": "db", "project": project, "canvas_sha": row["canvas_sha"],
                "canvas_path": row["canvas_path"], "built_at": row["built_at"]}
        return specs, links, meta
    finally:
        conn.close()


def topics(project=None, canvas_path=None):
    """话题注册表 (按节点/端口排序)。"""
    project = project or project_of(canvas_path)
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT node_id,port,dir,topic,qos,enabled FROM mw_topic WHERE project=? "
            "ORDER BY node_id, dir, port", (project,))]
    finally:
        conn.close()


def topic_map(project=None, canvas_path=None):
    """{(node_id, port): topic} —— 运行时按它发/收, 而不是临时拼字符串。"""
    return {(r["node_id"], r["port"]): r["topic"] for r in topics(project, canvas_path)}


def status(project=None):
    """库里有哪些工程 + 行数 + 与当前画布是否同源 (stale=画布改过没同步)。"""
    conn = connect()
    try:
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM mw_project" + (" WHERE project=?" if project else "") + " ORDER BY project"
        rows = conn.execute(q, ((project,) if project else ())).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["stale"] = (d["canvas_sha"] or "") != canvas_sha(d["canvas_path"])
            out.append(d)
        return out
    finally:
        conn.close()


def ensure_synced(canvas_path=None, quiet=True):
    """保证库与画布同源: sha 一致直接返回 (source=db); 不一致就重新解析画布并落库。"""
    project = project_of(canvas_path)
    for st in status(project):
        if st.get("stale"):
            continue
        # 🔴 2026-10-17: 只看 sha 不够 —— 新增 mw_signal 这类**派生表**时, 老库 sha 仍然对得上,
        #   于是永远不同步, 信号表永远空 (实测: 113 个输出端口 / 0 条信号)。派生表也要当判据。
        _conn = connect()
        try:
            _n_out = _conn.execute("SELECT COUNT(*) FROM mw_port WHERE project=? AND dir='out'",
                                   (project,)).fetchone()[0]
            _n_sig = _conn.execute("SELECT COUNT(*) FROM mw_signal WHERE project=?",
                                   (project,)).fetchone()[0]
        finally:
            _conn.close()
        if _n_sig >= _n_out and _n_out > 0:
            return {"project": project, "loaded_from": "db", "sha": st["canvas_sha"]}
    specs, links, _meta = spec_mod.parse_canvas(canvas_path)
    info = sync(specs, links, canvas_path=canvas_path, project=project, quiet=quiet)
    info["loaded_from"] = "json→db"
    return info
