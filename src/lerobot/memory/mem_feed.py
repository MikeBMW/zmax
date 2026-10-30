# -*- coding: utf-8 -*-
"""🧠 记忆层 ↔ 状态空间 AR 执行链 桥 (L2 肌肉 / L3 流程工艺 / L4 安全)

2026-10-30 老倪: 「将记忆层实际接入状态空间, 保证 AR 场景 300UPH, 从 L2 肌肉记忆开始,
然后流程工艺记忆 L3, 然后安全记忆 L4」。

职责 (只有这一件事, 不做别的):
  ① 热通道  /dev/shm/zmax_mem/feed.json —— 画布记忆节点 (ss_mem_l2/l3/l4) 每拍写入,
     plan 节点 (ssplan) 每拍读取 ⇒ **记忆真的在回路里, 且影响动作**
  ② L2 肌肉记忆台账 data/memory/ar_muscle.json —— 按 (kind) 记 AR 段实测时长 (n/mean_t),
     plan 用它把段表 t 按"实测比例"重新分配 (固化标杆 → 越练越准)
  ③ L3 流程工艺台账 data/memory/ar_cycles.jsonl —— 每圈流程经验 (段序/件节拍/UPH/良态)
  ④ L4 安全记忆台账 data/memory/ar_safety.json —— 违规累积 (段间硬跳/超速) + 由此收紧的
     v_cap / dv_cap / 平滑开关; plan 用它做段间连续 + 限速 + S 曲线

设计约束 (踩过的坑):
  · 读一律按 (mtime_ns,size) 缓存 —— 10Hz 回路里不许每拍 json.load 4MB 的 muscle_memory.json
  · 写一律原子 (tmp+os.replace) 且**节流** —— 记忆是增强不是依赖, 写失败绝不断回路
  · feed 缺席/过期 ⇒ 调用方走标称值 (零回退), 不抛异常
"""
from __future__ import annotations

import json
import os
import time

_ROOT = os.path.expanduser("~/zmax")
FEED_PATH = os.environ.get("ZMAX_MEM_FEED") or "/dev/shm/zmax_mem/feed.json"
AR_MUSCLE = os.path.join(_ROOT, "data", "memory", "ar_muscle.json")
AR_CYCLES = os.path.join(_ROOT, "data", "memory", "ar_cycles.jsonl")
AR_SAFETY = os.path.join(_ROOT, "data", "memory", "ar_safety.json")

FEED_STALE_S = float(os.environ.get("ZMAX_MEM_FEED_STALE_S", "3.0"))
_CACHE: dict = {}


# ─── 基础: 按 (mtime_ns,size) 缓存的 json 读 ───────────────────────────
def _read_cached(path):
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None, None
    e = _CACHE.get(path)
    if e and e[0] == key:
        return e[1], key
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return None, key
    _CACHE[path] = (key, obj)
    return obj, key


def _write_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ─── ① 热通道 ────────────────────────────────────────────────────────
def feed():
    """读记忆节点这一拍产出的记忆视图; 过期/缺失 ⇒ {}"""
    d, _ = _read_cached(FEED_PATH)
    if not isinstance(d, dict):
        return {}
    age = time.time() - float(d.get("t") or 0)
    d = dict(d)
    d["age_s"] = round(age, 3)
    d["fresh"] = age <= FEED_STALE_S
    return d


def publish(section, payload, tick=0):
    """记忆节点写入自己那一段 (原子读改写; 只写变化)"""
    cur, _ = _read_cached(FEED_PATH)
    cur = dict(cur) if isinstance(cur, dict) else {}
    payload = dict(payload)
    payload["t"] = round(time.time(), 3)
    payload["t_str"] = time.strftime("%H:%M:%S")
    old = cur.get(section)
    if isinstance(old, dict):
        a = {k: v for k, v in old.items() if k not in ("t", "t_str")}
        b = {k: v for k, v in payload.items() if k not in ("t", "t_str")}
        if a == b:                                  # 内容没变 ⇒ 不刷盘, 只动时间戳
            return True
    cur[section] = payload
    cur["t"] = payload["t"]
    cur["tick"] = tick
    cur["pid"] = os.getpid()
    return _write_json(FEED_PATH, cur)


# ─── ② L2 肌肉记忆 (AR 段实测标杆) ────────────────────────────────────
def ar_muscle():
    d, _ = _read_cached(AR_MUSCLE)
    return d if isinstance(d, dict) else {}


def muscle_lib():
    """固化标杆库 muscle_memory.json (4.7MB) —— 必须走 mtime 缓存, 10Hz 回路里不许每拍 parse"""
    d, _ = _read_cached(os.path.join(_ROOT, "data", "memory", "muscle_memory.json"))
    return d if isinstance(d, dict) else {}


def shared():
    """共享记忆 shared_memory.json —— 同样 mtime 缓存 (节点每拍读它, 文件 60KB+)"""
    d, _ = _read_cached(os.path.join(_ROOT, "data", "memory", "shared_memory.json"))
    return d if isinstance(d, dict) else {}


def bench_kind(kind, plan_t):
    """该 kind 的实测/标称比 (n≥3 才可信) —— >1 表示实测比段表更慢"""
    b = (ar_muscle().get("kinds") or {}).get(str(kind)) or {}
    n = int(b.get("n") or 0)
    mean_t = b.get("mean_t")
    if n < 3 or not plan_t or mean_t is None:
        return {"n": n, "mean_t": mean_t, "k": 1.0, "src": "未固化(n<3)"}
    k = float(mean_t) / float(plan_t)
    k = max(0.80, min(1.30, k))
    return {"n": n, "mean_t": round(float(mean_t), 4), "k": round(k, 4), "src": "muscle_memory"}


def record_segment(kind, dur, plan_t, label="", flush=True):
    """把一次真实段时长并入 L2 台账 (增量均值)"""
    d = ar_muscle()
    if not d:
        d = {"version": 1, "kinds": {}, "updated": None, "src": "ar plan 实测段时长"}
    kinds = d.setdefault("kinds", {})
    e = kinds.setdefault(str(kind), {"n": 0, "mean_t": 0.0, "plan_t": plan_t, "labels": {}})
    n = int(e.get("n") or 0)
    mean = float(e.get("mean_t") or 0.0)
    n += 1
    mean = mean + (float(dur) - mean) / n
    e.update(n=n, mean_t=round(mean, 5), plan_t=float(plan_t or 0), last_t=round(float(dur), 4))
    lb = e.setdefault("labels", {})
    if label:
        le = lb.setdefault(str(label), {"n": 0, "mean_t": 0.0})
        ln = int(le.get("n") or 0)
        le["mean_t"] = round((float(le.get("mean_t") or 0.0) * ln + float(dur)) / (ln + 1), 5)
        le["n"] = ln + 1
    d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d["total_segs"] = int(d.get("total_segs") or 0) + 1
    if flush:
        _write_json(AR_MUSCLE, d)
    return e


# ─── ③ L3 流程工艺记忆 (每圈流程经验) ────────────────────────────────
def last_cycle():
    try:
        with open(AR_CYCLES, "rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 65536))
            lines = [x for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
        for ln in reversed(lines):
            try:
                return json.loads(ln)
            except Exception:
                continue
    except Exception:
        pass
    return {}


def record_cycle(cyc):
    try:
        os.makedirs(os.path.dirname(AR_CYCLES), exist_ok=True)
        with open(AR_CYCLES, "a", encoding="utf-8") as f:
            f.write(json.dumps(cyc, ensure_ascii=False) + "\n")
        # 只留最近 500 圈 (追加型日志, 防无限增长)
        try:
            if os.path.getsize(AR_CYCLES) > 2_000_000:
                keep = open(AR_CYCLES, encoding="utf-8").read().splitlines()[-500:]
                with open(AR_CYCLES, "w", encoding="utf-8") as f:
                    f.write("\n".join(keep) + "\n")
        except Exception:
            pass
        return True
    except Exception:
        return False


# ─── ④ L4 安全记忆 (违规 → 上限) ─────────────────────────────────────
_SAFE_DEF = {"v_cap_mm_s": 700.0, "dv_cap_mm_s": 900.0, "smooth": 1,
             "continuity_mm": 1.0, "jumps": {}, "overspeed": 0, "updated": None,
             "src": "ar_safety 默认包络 (v≤700mm/s · Δv≤900mm/s · 段间连续)"}


def safety():
    d, _ = _read_cached(AR_SAFETY)
    out = dict(_SAFE_DEF)
    if isinstance(d, dict):
        out.update({k: v for k, v in d.items() if v is not None})
    return out


def record_violation(kind, value, cap=None, note=""):
    """违规累积: 段间硬跳 / 超速 —— 记录并据此收紧上限 (每次 3%)"""
    d, _ = _read_cached(AR_SAFETY)
    d = dict(d) if isinstance(d, dict) else dict(_SAFE_DEF)
    d.setdefault("jumps", {})
    if kind == "jump":
        k = str(int(round(float(value))))
        d["jumps"][k] = int(d["jumps"].get(k) or 0) + 1
        d["n_jump"] = int(d.get("n_jump") or 0) + 1
    elif kind == "overspeed":
        d["overspeed"] = int(d.get("overspeed") or 0) + 1
        d["v_cap_mm_s"] = round(max(300.0, float(d.get("v_cap_mm_s") or 700.0) * 0.97), 1)
    d["last_violation"] = {"kind": kind, "value": round(float(value), 3),
                           "cap": cap, "note": note,
                           "t": time.strftime("%Y-%m-%d %H:%M:%S")}
    d["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_json(AR_SAFETY, d)
    return d
