# -*- coding: utf-8 -*-
"""⚖ 原子技能物理闸「关键路径真值」读口 (2026-10-16)

老倪：「u_ff 经过 接近/对位 等原子技能节点，再给仿真器，可以么」
—— 改完后闸就在**引擎关键路径上**每拍真算（`cognition.ActionModulator.decide` →
`physics_constraints.InertiaLimiter.limit`），画布上的 ①..⑧ SK 节点 / ⚖物理约束闸
显示的就是**同一次调用**的结果，不再读技能派发服务那份旁路副本。

真源文件：`zmax_data/ss_live/skill_gate.json`（引擎 5Hz 落盘，
写方 = `src/lerobot/engine/sim.py::_publish_gate` 与 `src/lerobot/engine/runtime.py::_publish_gate`）。

纪律：读不到 / 帧龄 > STALE_S → 返回 None，调用方显示「尚未生成 / 引擎未在跑」，**绝不假 0**。
"""
from __future__ import annotations

import json
import os
import time

PATH = os.path.join(os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax"),
                    "zmax_data", "ss_live", "skill_gate.json")
STALE_S = 5.0
_CACHE = {"t": 0.0, "d": None}


def read(ttl: float = 1.0):
    """整份闸门真值 (含 u_req/u_now/why/err_norm/big/phys/n_cut)。陈旧/缺失 → None。"""
    now = time.time()
    if _CACHE["d"] is not None and (now - _CACHE["t"]) < ttl:
        return _CACHE["d"]
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                                  # noqa: BLE001
        _CACHE.update(t=now, d=None)
        return None
    try:
        if now - float(d.get("ts") or 0.0) > STALE_S:                   # 停更 ⇒ 不当现在
            _CACHE.update(t=now, d=None)
            return None
    except Exception:                                                  # noqa: BLE001
        _CACHE.update(t=now, d=None)
        return None
    d["age_s"] = round(now - float(d.get("ts") or now), 2)
    _CACHE.update(t=now, d=d)
    return d


def for_stage(stage: str, ttl: float = 1.0):
    """只返回**本段**那一拍的关键路径真值；引擎当前不在这一段 → None (不冒充)。"""
    d = read(ttl)
    if not d:
        return None
    if str(d.get("stage") or "") != str(stage):
        return None
    return d


def one_line(stage: str = "", ttl: float = 1.0) -> str:
    """一行可读摘要 (给节点 LAST_STATUS / 面板)。没有真值 → 返回空串，由调用方写「尚未生成」。"""
    d = read(ttl)
    if not d:
        return ""
    if not d.get("on"):                     # 闸没接 (ZMAX_L2_GATE=0) → 没有关键路径真值, 不假 0
        return "闸未接 (ZMAX_L2_GATE=0 · 旧等比缩放) — 本拍无关键路径真值"
    if stage and str(d.get("stage") or "") != str(stage):
        return f"本段未在跑 (引擎当前: {d.get('stage') or '?'})"
    u_r = d.get("u_req") or []
    u_n = d.get("u_now") or []
    try:
        vr = (sum(float(x) ** 2 for x in u_r[:3])) ** 0.5
        vn = (sum(float(x) ** 2 for x in u_n[:3])) ** 0.5
    except Exception:                                                  # noqa: BLE001
        vr = vn = 0.0
    p = d.get("phys") or {}
    return (f"段 {d.get('stage') or '?'} · {vr:.3f}→{vn:.3f} m/s (cap {p.get('v_cap', 0):.3f}) · "
            f"削因 {d.get('why') or '可行'} · 偏差 {d.get('err_norm', 0):.4f}"
            f"{' · 大偏差' if int(d.get('big') or 0) else ''} · 帧龄 {d.get('age_s')}s · "
            f"Δt {float(p.get('dt') or 0) * 1000:.0f}ms · 内联闸(关键路径)")


def n_cut_total() -> dict:
    """累计削因计数 (引擎内联闸自己数的, 不与派发服务重复计)。"""
    d = read(1.0) or {}
    return dict(d.get("n_cut") or {})
