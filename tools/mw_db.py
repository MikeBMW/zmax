#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中间件工程库 CLI —— 节点/端口/连线/话题的落库真源。

    python tools/mw_db.py status             # 库里有几套工程, 与画布是否同源
    python tools/mw_db.py sync               # 画布 JSON → 库 (幂等)
    python tools/mw_db.py topics [前缀]       # 话题注册表 (全量/过滤)
    python tools/mw_db.py node sssched       # 一个节点的端口 + 话题 + 连到谁
    python tools/mw_db.py sql "select ..."   # 只读查询 (方便接 CI/大屏)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lerobot.middleware import db, spec                      # noqa: E402


def main(argv):
    cmd = (argv[1] if len(argv) > 1 else "status").lower()
    if cmd == "status":
        rows = db.status()
        if not rows:
            print("库是空的 — 先跑 `python tools/mw_db.py sync`")
            return 0
        print("库: %s\n" % db.db_path())
        for r in rows:
            print("工程 %-22s 节点 %3d · 连线 %3d · 话题 %3d · sha %s · %s%s"
                  % (r["project"], r["node_n"], r["link_n"], r["topic_n"],
                     r["canvas_sha"], r["built_at"], "  ⚠️ 画布已改, 库过期" if r["stale"] else ""))
        return 0
    if cmd == "sync":
        specs, links, meta = spec.parse_canvas(None)
        info = db.sync(specs, links, canvas_path=spec.find_canvas())
        print("✅ %s → %s" % (info, db.db_path()))
        return 0
    if cmd == "topics":
        pref = argv[2] if len(argv) > 2 else ""
        rows = db.topics()
        hit = [r for r in rows if not pref or pref in r["topic"] or pref in r["node_id"]]
        print("话题 %d 条 (dds=%s)" % (len(hit), rows[0]["enabled"] if rows else "?"))
        for r in hit:
            print("  %-8s %-10s %s" % (r["dir"], r["port"], r["topic"]))
        return 0
    if cmd == "node":
        nid = argv[2]
        rows = [r for r in db.topics() if r["node_id"] == nid]
        if not rows:
            print("库里没有节点 %s" % nid)
            return 1
        print("节点 %s" % nid)
        for r in rows:
            print("  %-4s %-8s %s" % (r["dir"], r["port"], r["topic"]))
        return 0
    if cmd == "sql":
        q = argv[2]
        conn = db.connect()
        try:
            cur = conn.execute(q)
            cols = [d[0] for d in cur.description or []]
            print(" | ".join(cols))
            for row in cur.fetchall():
                print(" | ".join("" if v is None else str(v) for v in row))
        finally:
            conn.close()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
