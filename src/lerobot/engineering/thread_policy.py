#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧵 功能逻辑单线程策略 (550B: 功能逻辑只能有一个线程 — GUI 线程除外)

老倪 2026-10-31: 「550B 的功能逻辑只能有一个线程; GUI 除外; 左侧的线程不要跳, 全局修改运行线程, 单线程;
                现在断点又进不去了, 所有断点都要进入。」

为什么要这一层:
  · 画布节点原来为了不让重推理拖慢节拍, 自己起 worker (`ss_yolo_detect` / `ss_vlm` / `l3-smolvla`):
    节点在**主线程**被调, 真正的实现却在 worker 里跑 ⇒
    ① 断点可能一个都不停 (你停的位置不是执行那个函数的那条线程 → VSCode 左侧线程列表来回跳);
    ② 这一拍返回的是"上一帧"的结果, 说不清输出属于哪一拍输入。
  · 550B 是单线程标定/调试档: 要的就是"一拍内从头算到尾, 断点都落在主线程"。
    慢一点没关系, 可读、可停、可单步优先。

口径 (只影响**功能逻辑**, 不动 GUI/传输线程):
  · 功能逻辑 = 画布节点实现 / 引擎 / 技能派发 (SK01~SK08) / 物理闸。
  · 允许保留线程的: Qt 主线程与渲染、WebEngine、相机取流、DDS/relay 传输、信号库落盘。
  · 开关: `ZMAX_SINGLE_THREAD=1` (studio.py 启动早期与 VSCode 调试配置都会设) 或 `ZMAX_FUNC_THREADS=1`
    ⇒ `spawn_or_inline()` 一律**当场同步执行**; 两者都没有时保持原来的异步行为 (550A/550C 不变)。

用法 (替换 `threading.Thread(target=f, name=...).start()`):
    from lerobot.engineering.thread_policy import spawn_or_inline
    th = spawn_or_inline("ss_yolo_detect", _work)      # 单线程: 当场算完, 返回 None
"""
from __future__ import annotations

import os
import sys
import threading

_TRUE = ("1", "true", "yes", "on")
_VIOL: list = []          # 单线程违规记账 (功能逻辑跑到非主线程的次数/线程名)


def single() -> bool:
    """功能逻辑是否必须单线程 (550B / 显式开关)。

    唯一依据 = nodes/_single_thread.enabled() (studio.py / vscode_launch.py 同一口径);
    取不到时退回 env 判断, 保证在节点包外被引用也能工作。
    """
    try:
        from lerobot.engineering.nodes._single_thread import enabled as _en      # noqa: PLC0415
        return bool(_en())
    except Exception:                                                          # noqa: BLE001
        pass
    if str(os.environ.get("ZMAX_MULTI_THREAD", "")).strip().lower() in _TRUE:
        return False
    for k in ("ZMAX_SINGLE_THREAD", "ZMAX_FUNC_THREADS"):
        if str(os.environ.get(k, "")).strip().lower() in _TRUE:
            return True
    return False


def is_main() -> bool:
    """当前是否在进程主线程 (节点计算必须在它上面)。"""
    return threading.current_thread() is threading.main_thread()


def spawn_or_inline(name: str, fn, daemon: bool = True):
    """单线程 ⇒ 当场同步执行并返回 None; 否则起同名后台线程并返回 Thread。

    ⚠️ 单线程时**异常照原样抛**? 不: 与线程内口径保持一致 —— 线程里的异常本来就不会冒到主循环,
    所以这里也只是记录到调用方自己的状态里 (fn 内部本来就 try/except); 本函数不额外吞异常包装,
    让调用方的现有 err 记账继续生效。
    """
    if single():
        if not is_main():                       # 严格执行: 功能逻辑跑到别的线程上必须留痕
            _VIOL.append(threading.current_thread().name)
            if len(_VIOL) == 1:
                print("🔴 单线程违规: 功能逻辑在 %r 上执行 (应为主线程) —— 断点会跳线程"
                      % threading.current_thread().name, flush=True)
        fn()
        return None
    th = threading.Thread(target=fn, name=name, daemon=daemon)
    th.start()
    return th


def report() -> dict:
    """线程清点 (给审计工具/断点分诊用): 主线程 + 其余线程名。"""
    main = threading.main_thread()
    others = [t.name for t in threading.enumerate() if t is not main]
    return {"single": single(), "n_threads": len(others) + 1,
            "main": main.name, "threads": others, "violations": list(_VIOL)}
