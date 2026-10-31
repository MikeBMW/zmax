#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_inproc.py — 🧩 技能派发「同进程」节拍 (SK01~SK08 跑在状态空间进程里)

老倪 2026-10-31: 「把 SK01~SK08 运行在状态空间这个进程里, 别再独立派发了。550B 必须是这样。」

口径 (与改前唯一的差别就是"在哪个进程里跑"):
  · 技能派发**只有一个写者** = 状态空间画布常驻循环 `tools/ss_canvas_loop.py`, 每拍自己跑一派发
    (同一个 Dispatcher 类 · 同一份 chunk_latest.json · 同一个物理闸 ⇒ 断点就停在那个进程里)。
  · 独立的 `tools/ss_skill_dispatch.py` 服务**默认拒绝启动** (要单独跑须 ZMAX_DISPATCH_STANDALONE=1);
    systemd 单元 `zmax-ss-skill-dispatch.service` 已停用 ⇒ 不会再出现"两个写者抢 skill_phys.json"。
  · 派发频率 = 宿主节拍 (画布循环 10Hz)。chunk_latest.json 本身就是 10Hz 落的,
    原来那个 60Hz 只是把同一块重复读 6 次, 不是更高吞吐。

多宿主防双写 (谁都不许偷偷派发):
  ZMAX_DISPATCH_HOST  拥有派发的宿主名 (默认 ss_canvas_loop); 其它宿主调 tick(自己的名字) 直接返回 None。
  ZMAX_DISPATCH_INPROC=0  紧急关: 关掉进程内派发 (此时要独立派发须手工起 ss_skill_dispatch --standalone)。
  ZMAX_DISPATCH_HZ    派发器节拍 (默认跟宿主 10Hz)。

⚠️ 宿主循环里调用必须吞异常: 派发失败绝不拖垮状态空间循环 (本模块自己 try/except, 只记一行错误)。
"""
from __future__ import annotations

import os
import sys
import time

DEFAULT_HOST = "ss_canvas_loop"          # 状态空间画布常驻循环 = 技能派发的唯一宿主
_H = {"d": None, "err": None, "n": 0, "last": None, "host": None, "skip": ""}


def owner() -> str:
    """哪个宿主拥有派发 (默认画布循环)。"""
    return str(os.environ.get("ZMAX_DISPATCH_HOST", DEFAULT_HOST)).strip() or DEFAULT_HOST


def enabled(host: str | None = None) -> bool:
    """本宿主该不该派发。默认开; 只认显式关闭 (0/false/no/off)。"""
    if str(os.environ.get("ZMAX_DISPATCH_INPROC", "1")).strip().lower() in ("0", "false", "no", "off"):
        return False
    return (host or owner()) == owner()


def dispatcher(hz: float | None = None):
    """取(首次创建)本进程内的派发器实例; 失败只记一次错误, 不抛 (绝不拖垮宿主循环)。"""
    if _H["d"] is not None or _H["err"] is not None:
        return _H["d"]
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.join(root, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(root, "tools"))
        import ss_skill_dispatch as _sd              # noqa: PLC0415

        _h = hz if hz is not None else float(os.environ.get("ZMAX_DISPATCH_HZ", "10") or 10)
        _H["d"] = _sd.Dispatcher(hz=_h)
    except Exception as e:                            # noqa: BLE001
        _H["err"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return _H["d"]


def step_stage(stage: str, u_req, host: str = "canvas_node"):
    """🧭 画布节点调用口: 让 stage 这段的技能此刻真跑一次 clamp (连线即执行)。

    老倪 2026-10-31「按照连线, 强制保持数据功能与连线一致」:
      sssk1~8 节点激活 ⇒ 走这里 ⇒ 真调 atomic_skills.<SKxx>.clamp ⇒ 断点就落在那行。
    节点已经跑过这一拍的 clamp ⇒ 同拍的 tick() 自动让位 (不会一条动作过两次闸)。
    """
    if str(os.environ.get("ZMAX_DISPATCH_INPROC", "1")).strip().lower() in ("0", "false", "no", "off"):
        return None
    d = dispatcher()
    if d is None:
        return None
    try:
        r = d.step_stage(stage, u_req)
        if r is not None:
            _H["node_ts"] = time.time()
            _H["node_n"] = _H.get("node_n", 0) + 1
            _H["node_last"] = {"stage": stage, "why": r.get("why"), "err_norm": r.get("err_norm")}
        return r
    except Exception as e:                            # noqa: BLE001
        _H["err"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        return None


def tick(host: str | None = None, hz: float | None = None):
    """跑一拍技能派发。不该本宿主派发 / 未启用 / 不可用 均返回 None (宿主照常跑, 零回退)。"""
    _h = host or owner()
    if not enabled(_h):
        _H["skip"] = "非派发宿主 (owner=%s)" % owner()
        return None
    d = dispatcher(hz)
    if d is None:
        return None
    # 画布节点这一拍已经真跑过 clamp ⇒ 让位 (一条动作只过度一次闸)
    _nt = _H.get("node_ts")
    if _nt and (time.time() - float(_nt)) < 0.15:
        _H["skip"] = "本拍已由画布节点执行 (sssk*)"
        return None
    try:
        r = d.cycle()
        _H["n"] += 1
        _H["host"] = _h
        _H["last"] = {k: r.get(k) for k in ("在职技能", "在职数", "闸_拍数", "块帧龄_s")} \
            if isinstance(r, dict) else None
        return r
    except Exception as e:                            # noqa: BLE001
        _H["err"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        return None


def status() -> dict:
    """派发归属与计数 (给状态文件/验收用: 谁在哪一拍真正派发过)。"""
    return {"enabled": enabled(), "owner": owner(), "host": _H["host"], "pid": os.getpid(),
            "n": _H["n"], "err": _H["err"], "skip": _H["skip"], "last": _H["last"],
            "has_dispatcher": _H["d"] is not None}
