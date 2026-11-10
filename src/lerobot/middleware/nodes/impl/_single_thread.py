# -*- coding: utf-8 -*-
"""🔒 单线程执行闸 — 除 GUI 显示之外, 所有节点都在调用线程里算, 不起后台线程。

老倪 2026-10-29: 「550B VSCode 变成单线程模式, 除了显示的 GUI, 其它所有的 node 节点, 全都单线程运行」。

⚠️ 2026-11-10 恢复本文件:
   原源码只存在 `engineering/nodes/__pycache__/_single_thread.cpython-311.pyc`(源码丢失, 仅剩 pyc)。
   而 `middleware/nodes/impl/` 下 ssworld / sssched / sslimit / ssact / flow_matching /
   grav_impedance 全部 `from ._single_thread import brk` ⇒ ModuleNotFoundError,
   实测 3 个 L2 节点(ssworld/sssched/sslimit)直接崩。
   本文件按 pyc 反汇编逐函数还原, 语义与 pyc 一致:
     enabled()          = ZMAX_SINGLE_THREAD=='1' and ZMAX_MULTI_THREAD!='1'
     enforce(log)       = 未启用 → 打印一次横幅 + {enabled:False, why:...}; 启用 → 检查并缓存
     in_caller_thread() = current_thread() is main_thread()
     brk(tag)           = pyc 里函数体为空(LOADS None / RETURN), 此处保持 no-op + 留钩子
"""
import os
import threading

_DONE = {}
_SEEN = {}
_ANNOUNCED = set()
_LAST_STOP = 0.0


def enabled():
    """单线程闸是否开启 (VSCode/studio 同一口径)。"""
    return (os.environ.get("ZMAX_SINGLE_THREAD", "") == "1"
            and os.environ.get("ZMAX_MULTI_THREAD", "") != "1")


def in_caller_thread():
    """当前是否跑在调用线程(主线程)。"""
    return threading.current_thread() is threading.main_thread()


def enforce(log=None):
    """执行闸检查 → {enabled, why} (+ in_caller)。未启用时只提示一次, 不阻断。"""
    if not enabled():
        if not _DONE.get("said_off"):
            _DONE["said_off"] = True
            print("🔓 单线程闸: 未启用 (ZMAX_SINGLE_THREAD=%r / ZMAX_MULTI_THREAD=%r)"
                  " · ZMAX_DEBUG_BREAK=%r · OMP=%r" % (
                      os.environ.get("ZMAX_SINGLE_THREAD"),
                      os.environ.get("ZMAX_MULTI_THREAD"),
                      os.environ.get("ZMAX_DEBUG_BREAK"),
                      os.environ.get("OMP_NUM_THREADS")), flush=True)
        return {"enabled": False, "why": "ZMAX_SINGLE_THREAD!=1"}
    if _DONE.get("v") is not None:
        return _DONE["v"]
    ok = in_caller_thread()
    res = {"enabled": True, "in_caller": ok,
           "why": "" if ok else "节点跑在后台线程 (单线程闸开启时应走调用线程)"}
    _DONE["v"] = res
    if not ok and log:
        log("⚠️ " + res["why"])
    return res


def brk(tag=""):
    """调试断点钩子 — pyc 原实现函数体为空 (直接 return None), 此处保持 no-op。

    ZMAX_DEBUG_BREAK=1 时按 ZMAX_BREAK_GAP(默认 1.5s) 记一次停靠计数, 不阻塞执行。
    """
    global _LAST_STOP
    if os.environ.get("ZMAX_DEBUG_BREAK", "") != "1":
        return None
    try:
        import time
        now = time.time()
        gap = float(os.environ.get("ZMAX_BREAK_GAP", "1.5") or 1.5)
        if now - _LAST_STOP >= gap:
            _LAST_STOP = now
            _SEEN[tag] = _SEEN.get(tag, 0) + 1
            if tag not in _ANNOUNCED:
                _ANNOUNCED.add(tag)
                print("⏸ 调试停靠: %s (第 %d 次)" % (tag or "-", _SEEN[tag]), flush=True)
    except Exception:  # noqa: BLE001  断点钩子不许影响主流程
        return None
    return None
