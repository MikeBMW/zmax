#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白天日志 —— 「噪声日志」的唯一落盘口 (白天只写, 夜间只读)。

一条观测 = 一帧可复核的物理量: (Θ mm, p, H, K, U, tcp, tgt, 帧号, 来源)。
与 `tools/gui/phase_window.py` 同源同口径, 不另立一套。

不做 100 维硬填: 白天拿不到真值潜变量, 硬填 0 就是假数据。45 维"残差池"由夜间
从这些物理量统计得出(见 consolidate.py), 汇报里只会出现实测数字。
"""
from __future__ import annotations

import glob
import json
import os
import time

from .phase import DN_DIR

DAY_DIR = os.path.join(DN_DIR, "day")
LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))), "zmax_data", "ss_live")

FIELDS = ("th_mm", "p", "H", "K", "U")


def _ensure() -> None:
    os.makedirs(DAY_DIR, exist_ok=True)


def path(day_id: str) -> str:
    return os.path.join(DAY_DIR, "day_%s.jsonl" % day_id)


def append(day_id: str, recs: list[dict]) -> int:
    _ensure()
    n = 0
    with open(path(day_id), "a", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
        f.flush()
        os.fsync(f.fileno())
    return n


def read(day_id: str) -> list[dict]:
    p = path(day_id)
    out = []
    if not os.path.isfile(p):
        return out
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:                                       # noqa: BLE001
                continue
    return out


def days() -> list[str]:
    _ensure()
    out = []
    for p in sorted(glob.glob(os.path.join(DAY_DIR, "day_*.jsonl"))):
        out.append(os.path.basename(p)[4:-6])
    return out


def latest_with_data() -> str:
    """最新一份**真有样本**的白天日志(空日志不算; 服务启动会建空日志)。"""
    best, best_ts = "", -1.0
    for d in days():
        rs = read(d)
        if len(rs) < 10:
            continue
        ts = max(float(r.get("ts") or 0.0) for r in rs)
        if ts > best_ts:
            best, best_ts = d, ts
    return best


def collect_live(day_id: str, tail: int = 4000) -> dict:
    """把真机相点(phase_real_*.jsonl) + 引擎当前 hamiltonian.json 收进白天日志。

    去重口径: 同一个 ts 只留一条(相空间采样 20Hz, 重启会重复)。
    """
    recs: list[dict] = []
    files = sorted(glob.glob(os.path.join(LIVE, "phase_real_*.jsonl")))
    if files:
        with open(files[-1], encoding="utf-8") as f:
            lines = f.readlines()[-tail:]
        for line in lines:
            try:
                d = json.loads(line)
            except Exception:                                        # noqa: BLE001
                continue
            recs.append({"ts": d.get("ts"), "src": d.get("src"), "i": d.get("i"),
                         "th_mm": d.get("th_mm"), "p": d.get("p"), "H": d.get("H"),
                         "K": d.get("K"), "U": d.get("U"), "tcp": d.get("tcp"),
                         "tgt": d.get("tgt"), "origin": "phase_real"})
    hp = os.path.join(LIVE, "hamiltonian.json")
    if os.path.isfile(hp):
        try:
            h = json.load(open(hp, encoding="utf-8"))
            xi = h.get("xi_e") or [0, 0, 0]
            recs.append({"ts": h.get("ts"), "src": h.get("src"), "i": -1,
                         "th_mm": float(xi[2]) * 1000.0, "p": 0.0,
                         "H": h.get("H"), "K": h.get("K"), "U": h.get("U"),
                         "origin": "hamiltonian"})
        except Exception:                                            # noqa: BLE001
            pass
    old = {r.get("ts") for r in read(day_id)}
    fresh = [r for r in recs if r.get("ts") and r["ts"] not in old]
    n = append(day_id, fresh)
    return {"added": n, "scanned": len(recs), "dropped_dup": len(recs) - n, "day_id": day_id}


def summarize(day_id: str) -> dict:
    rs = read(day_id)
    ok = [r for r in rs if all(isinstance(r.get(k), (int, float)) for k in FIELDS)]
    if not ok:
        return {"day_id": day_id, "n": len(rs), "valid": 0}
    th = [r["th_mm"] for r in ok]
    H = [r["H"] for r in ok]
    K = [r["K"] for r in ok]
    p = [r["p"] for r in ok]
    ksum = sum(K)
    hsum = sum(H)
    return {
        "day_id": day_id, "n": len(rs), "valid": len(ok),
        "th_mm": [round(min(th), 2), round(max(th), 2)],
        "p": [round(min(p), 5), round(max(p), 5)],
        "H_max": round(max(H), 4), "H_mean": round(hsum / max(1, len(H)), 5),
        "k_share_pct": round(100.0 * ksum / hsum, 2) if hsum > 0 else 0.0,
        "span_s": round((max(r["ts"] for r in ok) - min(r["ts"] for r in ok)), 1),
    }


def new_day_id(prefix: str = "D") -> str:
    return time.strftime("%%s%%Y%%m%%d_%%H%%M%%S" % prefix)
