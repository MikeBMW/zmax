#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_inproc.py — 🧩 技能派发「同进程」节拍 (550B 单进程调试用)

老倪 2026-10-31: 「550B 的调试, 都在一个进程里, 没有其它进程」。

问题: 生产的派发是**独立 systemd 单元** (tools/ss_skill_dispatch.py --hz 60), 所以在 studio/GUI
那个调试进程里打的断点 (SK01Approach.clamp / AtomicSkill.apply_physics / InertiaLimiter.limit)
永远命中不了 —— 那条语句根本不在调试进程里。

本办法: 宿主进程 (引擎循环 / GUI) 每个节拍**自己**跑一拍派发, 用的是**同一个 Dispatcher 类、
同一份 chunk_latest.json、同一个物理闸**, 所以红点就停在本进程内。默认关闭, 打开方式:

    ZMAX_DISPATCH_INPROC=1

⚠️ 生产不要开: 生产和它同时写 skill_*.json 会成为双写者 (原子写不会坏文件, 但"在职"口径会打架)。
   单进程调试时把 systemd 单元停掉 (`sudo systemctl stop zmax-ss-skill-dispatch`), 由本进程独家写。
⚠️ 同进程节拍率 = 宿主循环的频率 (引擎 10Hz ⇒ 派发 10Hz), 不是 60Hz —— 调试口径, 不是性能口径。
"""
from __future__ import annotations

import os
import sys

_H = {"d": None, "err": None, "n": 0, "last": None}


def enabled() -> bool:
    """显式开 (ZMAX_DISPATCH_INPROC=1)。默认关 —— 生产只有一个写者 (systemd 派发单元)。"""
    return str(os.environ.get("ZMAX_DISPATCH_INPROC", "")).strip() in ("1", "true", "yes", "on")


def dispatcher():
    """取(首次创建)本进程内的派发器实例; 失败只记一次错误, 不抛 (绝不拖垮宿主循环)。"""
    if _H["d"] is not None or _H["err"] is not None:
        return _H["d"]
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.join(root, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(root, "tools"))
        import ss_skill_dispatch as _sd              # noqa: PLC0415

        _H["d"] = _sd.Dispatcher(hz=float(os.environ.get("ZMAX_DISPATCH_HZ", "10")))
    except Exception as e:                            # noqa: BLE001
        _H["err"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return _H["d"]


def tick():
    """跑一拍技能派发。未启用/不可用均返回 None (宿主照常跑, 零回退)。"""
    if not enabled():
        return None
    d = dispatcher()
    if d is None:
        return None
    try:
        r = d.cycle()
        _H["n"] += 1
        _H["last"] = {k: r.get(k) for k in ("在职技能", "在职数", "闸_拍数", "块帧龄_s")} if isinstance(r, dict) else None
        return r
    except Exception as e:                            # noqa: BLE001
        _H["err"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        return None


def status() -> dict:
    return {"enabled": enabled(), "n": _H["n"], "err": _H["err"], "last": _H["last"],
            "has_dispatcher": _H["d"] is not None}
