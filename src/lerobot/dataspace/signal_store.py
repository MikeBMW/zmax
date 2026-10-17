# -*- coding: utf-8 -*-
"""统一信号库 (SQLite) —— Trace 窗口与信号分析窗口的**唯一数据源**。

老倪 2026-10-17: 「现在的 Trace 窗口的 signal, 与信号分析的 signal, 是同一个数据源么？
                都要来自统一的数据库」

在此之前两者的"同源"只做到**同一份快照函数**(live_signals.topics()), 底下仍是 7 个 JSON 文件
由各自进程写、随时可能一拍有一拍没。本模块把它们收进一个库:

  zmax_data/dataspace/signals.db     (WAL)
    topics(topic PK, type, qos, source, ts, src_ts, age_s, hz, hz_design, count, producer, enabled, layer)
    signals(topic, name, value, PRIMARY KEY(topic, name))
    meta(k, v)   ← updated = 最后一次写入的 epoch (窗口据此判"库是不是活的")

写入方: tools/signal_store_daemon.py (2Hz, 单实例; 读 live_signals.topics_from_files 落库)
读取方: live_signals.topics() 先读库 (新鲜 <3s), 库不在/过期才回落文件并打印一行。

口径: 值一律 float; 非数值字段本来就不进信号 (与 is_meta/is-numeric 口径一致)。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

ROOT = os.environ.get("ZMAX_REPO") or "/home/ubuntu/zmax"
DB = os.environ.get("ZMAX_SIGNAL_DB") or os.path.join(ROOT, "zmax_data", "dataspace", "signals.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics(
  topic TEXT PRIMARY KEY, type TEXT, qos TEXT, source TEXT,
  ts REAL, src_ts REAL, age_s REAL, hz REAL, hz_design REAL,
  count INTEGER, producer TEXT, enabled INTEGER, layer TEXT);
CREATE TABLE IF NOT EXISTS signals(
  topic TEXT NOT NULL, name TEXT NOT NULL, value REAL, PRIMARY KEY(topic, name));
CREATE INDEX IF NOT EXISTS ix_signals_topic ON signals(topic);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def _con(path=None):
    p = path or DB
    os.makedirs(os.path.dirname(p), exist_ok=True)
    c = sqlite3.connect(p, timeout=5.0)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init(path=None):
    c = _con(path)
    with c:
        c.executescript(SCHEMA)
    c.close()


def write_snapshot(snap: dict, path=None) -> int:
    """整份快照落库 (单事务: 先清后写, 保证读到的是同一拍, 不会半新半旧)。返回写入信号条数。"""
    c = _con(path)
    n = 0
    try:
        with c:
            c.executescript(SCHEMA)
            c.execute("DELETE FROM signals")
            c.execute("DELETE FROM topics")
            for topic, rec in (snap or {}).items():
                c.execute(
                    "INSERT OR REPLACE INTO topics(topic,type,qos,source,ts,src_ts,age_s,hz,hz_design,"
                    "count,producer,enabled,layer) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (topic, rec.get("type") or "", rec.get("qos") or "", rec.get("source") or "",
                     _f(rec.get("ts")), _f(rec.get("src_ts")), _f(rec.get("age_s")), _f(rec.get("hz")),
                     _f(rec.get("hz_design")), int(rec.get("count") or 0), rec.get("producer") or "",
                     1 if rec.get("enabled", True) else 0, rec.get("layer") or ""))
                rows = [(_f(v) is not None, topic, str(k), _f(v)) for k, v in (rec.get("fields") or {}).items()]
                rows = [r for r in rows if r[0]]
                if rows:
                    c.executemany("INSERT OR REPLACE INTO signals(topic,name,value) VALUES(?,?,?)",
                                  [(r[1], r[2], r[3]) for r in rows])
                    n += len(rows)
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('updated',?)", (repr(time.time()),))
    finally:
        c.close()
    return n


def _f(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except Exception:                                                    # noqa: BLE001
        return None


def updated(path=None) -> float:
    try:
        c = _con(path)
        r = c.execute("SELECT v FROM meta WHERE k='updated'").fetchone()
        c.close()
        return float(r[0]) if r else 0.0
    except Exception:                                                    # noqa: BLE001
        return 0.0


def read_snapshot(max_age=3.0, path=None):
    """库新鲜 (<max_age) 才返回快照; 否则 None (调用方回落文件)。形状与 live_signals.topics() 一致。"""
    up = updated(path)
    if not up or (time.time() - up) > max_age:
        return None
    out = {}
    c = _con(path)
    try:
        fields = {}
        for topic, name, val in c.execute("SELECT topic,name,value FROM signals"):
            fields.setdefault(topic, {})[name] = float(val)
        for row in c.execute("SELECT topic,type,qos,source,ts,src_ts,age_s,hz,hz_design,count,"
                             "producer,enabled,layer FROM topics"):
            topic = row[0]
            out[topic] = {
                "topic": topic, "type": row[1], "qos": row[2], "source": row[3],
                "ts": row[4], "src_ts": row[5], "src_file_ts": row[5], "age_s": row[6], "hz": row[7],
                "hz_design": row[8], "count": row[9], "producer": row[10],
                "enabled": bool(row[11]), "layer": row[12],
                "fields": fields.get(topic, {}),
            }
    finally:
        c.close()
    return out


def stats(path=None):
    up = updated(path)
    c = _con(path)
    try:
        n_topics = c.execute("SELECT count(*) FROM topics").fetchone()[0]
        n_sig = c.execute("SELECT count(*) FROM signals").fetchone()[0]
    finally:
        c.close()
    return {"db": DB, "topics": n_topics, "signals": n_sig,
            "age_s": round(max(0.0, time.time() - up), 2) if up else None}


if __name__ == "__main__":
    print(json.dumps(stats(), ensure_ascii=False))
