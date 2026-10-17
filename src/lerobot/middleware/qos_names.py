# -*- coding: utf-8 -*-
"""QoS 显示规范化 —— 必须与 DDS 标准术语对得上。

老倪 2026-10-17: 「你再检查 QoS 列, 要跟 DDS 标准对上」

系统内部有三种简写 (beat / state / cmd, 以及库里的 reliable/transient_local), 直接显示
"beat" 外行看不懂、也跟 DDS 规范对不上。本模块把它们翻成 OMG DDS 的策略名 + 取值:

    beat  → BEST_EFFORT · KEEP_LAST(1) · VOLATILE
    state → RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL   (latch: 新订阅者立刻拿到最新一帧)
    cmd   → RELIABLE · KEEP_ALL · VOLATILE
    reliable/transient_local → RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL
    shm   → 非 DDS (共享内存后端)

判据: 每条 QoS 要么能解析成上面的标准组合, 要么明确标 "❌ 未知", 不许糊过去。
"""
from __future__ import annotations

# DDS 标准取值 (OMG DDS 1.4 / DDSI-RTPS)
RELIABILITY = {"BEST_EFFORT", "RELIABLE"}
DURABILITY = {"VOLATILE", "TRANSIENT_LOCAL", "TRANSIENT", "PERSISTENT"}
HISTORY = {"KEEP_LAST", "KEEP_ALL"}

_CLASS = {
    "beat": ("BEST_EFFORT", "KEEP_LAST", 1, "VOLATILE"),
    "state": ("RELIABLE", "KEEP_LAST", 1, "TRANSIENT_LOCAL"),
    "cmd": ("RELIABLE", "KEEP_ALL", None, "VOLATILE"),
    "stream": ("BEST_EFFORT", "KEEP_LAST", 1, "VOLATILE"),
    "shm": None,
}

_ALIASES = {
    "reliable": "RELIABLE", "best_effort": "BEST_EFFORT", "besteffort": "BEST_EFFORT",
    "transient_local": "TRANSIENT_LOCAL", "transientlocal": "TRANSIENT_LOCAL",
    "volatile": "VOLATILE", "keep_last": "KEEP_LAST", "keeplast": "KEEP_LAST",
    "keep_all": "KEEP_ALL", "keepall": "KEEP_ALL",
}


def parse(qos):
    """qos 字符串 → dict(reliability, history, depth, durability) 或 None (非 DDS / 未知)。"""
    raw = str(qos or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in ("shm", "shared_memory", "step"):
        return None
    if low in _CLASS:
        c = _CLASS[low]
        if c is None:
            return None
        rel, hist, depth, dur = c
        return {"reliability": rel, "history": hist, "depth": depth, "durability": dur}

    # "reliable/transient_local" / "RELIABLE,KEEP_LAST(1)" 这类组合串
    parts = [p.strip() for p in raw.replace(",", "/").split("/") if p.strip()]
    rel = hist = dur = None
    depth = None
    for p in parts:
        pl = p.lower()
        if "(" in pl:                                    # keep_last(5)
            base, _, num = pl.partition("(")
            depth = "".join(ch for ch in num if ch.isdigit())
            pl = base.strip()
        tok = _ALIASES.get(pl) or pl.upper()
        if tok in RELIABILITY:
            rel = tok
        elif tok in HISTORY:
            hist = tok
        elif tok in DURABILITY:
            dur = tok
    if not rel and not hist and not dur:
        return None
    return {"reliability": rel or "RELIABLE", "history": hist or "KEEP_LAST",
            "depth": int(depth) if depth else (1 if (hist or "").endswith("KEEP_LAST") else None),
            "durability": dur or "VOLATILE"}


def standard(qos) -> str:
    """QoS → DDS 标准显示 (如 "RELIABLE · KEEP_LAST(1) · TRANSIENT_LOCAL")。"""
    d = parse(qos)
    if not d:
        raw = str(qos or "").strip()
        if raw.lower() in ("shm", "shared_memory"):
            return "SHM (非 DDS)"
        if raw.lower() == "step":
            return "单步调试 (非 DDS)"
        return "❌ 未知: %s" % (raw or "—")
    hist = d["history"]
    if hist == "KEEP_LAST":
        hist = "KEEP_LAST(%s)" % (d.get("depth") or 1)
    return "%s · %s · %s" % (d["reliability"], hist, d["durability"])


def valid(qos) -> bool:
    d = parse(qos)
    if not d:
        return str(qos or "").strip().lower() in ("shm", "shared_memory", "step")
    return (d["reliability"] in RELIABILITY and d["history"] in HISTORY
            and d["durability"] in DURABILITY)
