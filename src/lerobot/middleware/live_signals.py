# -*- coding: utf-8 -*-
"""实时信号源 —— 与「信号分析」窗口同一份文件, 保证两处数值一致。

老倪 2026-10-17: 「数据空间的信号, 怎么不动呢? 要实时运行啊」
             + 「你要保证全局数据空间的信号, 与信号分析窗口的数据, 保持一致」

现状: 数据空间的 Trace 原来只读 `zmax_data/dataspace/live.json` —— 那是 DDS 桥的输出,
DDS 上此刻 0 个发布者 (探针 matched_pubs=0) ⇒ 值永远是 "—", 表当然不动。
而「信号分析」窗口 (canoe_graphic.py) 一直读的是本机真值文件:

    sstrace ← zmax_data/ss_live/trace_live.json     (插拔链真值帧, ~10Hz)
    sseng   ← zmax_data/ss_live/engine_trace.json   (引擎一拍, 10Hz)
    gravity ← zmax_data/ss_live/gravity_trace.json  (万有引力表力信号, 5Hz)

本模块只做一件事: **读同一批文件、同一拍数据**, 给数据空间用 ⇒ 两个窗口天然一致,
不存在"这边 0.1 那边 0.2"。不复制逻辑, 不再起第二个采集器。
"""
from __future__ import annotations

import json
import os
import time

ROOT = os.environ.get("ZMAX_REPO") or "/home/ubuntu/zmax"

# topic → (文件, 来源标签, 扁平化方式)
SOURCES = {
    "zmax/ss_state": ("zmax_data/ss_live/trace_live.json", "sstrace", "flat"),
    "zmax/ss_engine": ("zmax_data/ss_live/engine_trace.json", "sseng", "flat"),
    "zmax/ss_torque": ("zmax_data/ss_live/gravity_trace.json", "gravity", "nested_s"),
}

_TTL = 0.25
_CACHE = {"t": 0.0, "data": None}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _flatten(d, prefix=""):
    """只留数值叶子 (字符串/列表转成计数或跳过), 键名保持源文件原样。"""
    out = {}
    for k, v in (d or {}).items():
        if str(k) in ("ts", "t"):
            continue
        if _num(v):
            out[str(k)] = float(v)
        elif isinstance(v, dict) and prefix == "":
            for k2, v2 in _flatten(v, str(k) + ".").items():
                out[k2] = v2
        elif isinstance(v, (list, tuple)):
            nums = [float(x) for x in v if _num(x)]
            if nums:
                out["%s_len" % k] = float(len(v))
    return out


def _one(path, kind):
    p = os.path.join(ROOT, path)
    try:
        st = os.stat(p)
        d = json.load(open(p, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return None
    age = max(0.0, time.time() - st.st_mtime)
    if kind == "nested_s" and isinstance(d.get("s"), dict):
        body = d["s"]
        fields = _flatten(body)
        fields["阶段"] = float(d.get("运行") or 0.0)
    else:
        fields = _flatten(d)
    ts = d.get("ts") if _num(d.get("ts")) else st.st_mtime
    return {"fields": fields, "ts": float(ts), "age_s": round(age, 2),
            "mtime": st.st_mtime}


def topics_from_files():
    """读本机真值文件拼成快照 (唯一读取口径; 不再有第二套解析)。

    2026-10-17 起这是**写库方**用的入口 (tools/signal_store_daemon.py), 不做 0.25s 缓存 ——
    守护每拍都要最新值, 缓存会把同一拍写两遍。
    """
    out = {}
    for topic, (rel, src, kind) in SOURCES.items():
        got = _one(rel, kind)
        if not got or not got["fields"]:
            continue
        typ = ""
        try:
            from lerobot.middleware import topic_types as _tt
            typ = _tt.type_of_topic(topic) or ""
        except Exception:                                                    # noqa: BLE001
            typ = ""
        if not typ:                                   # 语义注册表没登记 ⇒ 用 DDS 话题注册表的类型
            try:
                from lerobot.dataspace import topics as _T
                typ = (_T.TOPICS.get(topic.split("/")[-1]) or {}).get("type") or ""
            except Exception:                                                # noqa: BLE001
                typ = ""
        # ⏱ 显示时间用 wall-clock - 帧龄: 文件里的 ts 是采集机时钟 (本机 NTP 回拨 8h 有偏差),
        #   直接上屏会显示成 8 小时前的时刻。
        _ts = time.time() - float(got.get("age_s") or 0.0)
        out[topic] = {"topic": topic, "type": typ, "qos": "state", "ts": _ts,
                      "src_ts": got.get("ts"),
                      "hz": None,
                      "hz_design": {"zmax/ss_state": 10.0, "zmax/ss_engine": 10.0,
                                    "zmax/ss_torque": 5.0}.get(topic), "count": 0,
                      "age_s": got["age_s"], "fields": got["fields"],
                      "src_file_ts": got["ts"], "source": src,
                      "producer": "", "enabled": True,
                      "layer": "SYS"}
    # 🧩 2026-10-17 老倪: 「信号分析里 L2 信号 Tx 是 ① 接近 · SK01 有十多个, Trace 里 L2 Tx 接近就没有」
    #   根因: 数据空间只看这 3 路实时快照, 技能物理量/技能派发/位姿/状态/安全/YOLO/数据空间这些
    #   本机真值文件根本没进来。这里把 host_sources.FILES 里其余文件一并并进来 (同一份读法),
    #   两个窗口的话题/字段集合从此一致。
    try:
        from lerobot.middleware import host_sources as _hs
        for topic, rec in _hs.topics().items():
            if topic in out:
                continue                              # 前三路由上面的实时快照负责 (帧龄更准)
            typ = ""
            try:
                from lerobot.middleware import topic_types as _tt
                typ = _tt.type_of_topic(topic) or ""
            except Exception:                                           # noqa: BLE001
                typ = ""
            out[topic] = {"topic": topic, "type": typ, "qos": "state",
                          "ts": time.time() - float(rec.get("age_s") or 0.0),
                          "src_ts": rec.get("ts"), "hz": None, "hz_design": None, "count": 0,
                          "age_s": rec.get("age_s"), "fields": rec["fields"],
                          "src_file_ts": rec.get("ts"), "source": rec.get("prefix"),
                          "producer": "", "enabled": True, "layer": "SYS"}
    except Exception:                                                   # noqa: BLE001
        pass
    return out


_FALLBACK_WARN = [0.0]


def topics():
    """{topic: {...}} —— **优先读统一信号库** (zmax_data/dataspace/signals.db), 0.25s 缓存。

    老倪 2026-10-17: 「Trace 窗口的 signal, 与信号分析的 signal, 都要来自统一的数据库」
      · 库新鲜 (<3s) ⇒ 两个窗口读到的就是同一张表里的同一拍, 不存在"谁先谁后"
      · 库不在/过期 ⇒ 回落文件直读, 并打印一行 (不静默降级成"两个窗口各读各的")
      · ZMAX_SIGNAL_DB_OFF=1 可强制走旧路 (排障用)
    """
    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["t"]) < _TTL:
        return _CACHE["data"]
    snap = None
    if os.environ.get("ZMAX_SIGNAL_DB_OFF") != "1":
        try:
            from lerobot.dataspace import signal_store as _ss
            snap = _ss.read_snapshot(max_age=3.0)
        except Exception:                                                # noqa: BLE001
            snap = None
    if snap:
        _CACHE.update(t=now, data=snap)
        return snap
    if now - _FALLBACK_WARN[0] > 30:
        _FALLBACK_WARN[0] = now
        print("⚠️ 统一信号库不可用/过期 → 回落文件直读 (先起 tools/signal_store_daemon.py)", flush=True)
    out = topics_from_files()
    _CACHE.update(t=now, data=out)
    return out


def stats():
    t = topics()
    return {k: {"signals": len(v["fields"]), "age_s": v["age_s"], "src": v["source"]}
            for k, v in t.items()}
