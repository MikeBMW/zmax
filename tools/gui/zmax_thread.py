#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔧 工程线程 (zmax) —— 550B 只允许两条线程: MainThread(界面) + zmax(工程)

老倪 2026-10-31: 「就两个线程。MainThread 是 GUI, zmax 是工程线程」

口径 (硬约束):
  · 进程里**只准**存在两条 Python 线程:
      - MainThread : Qt 界面 / 事件循环 / 绘制。永远不跑工程计算。
      - zmax       : 工程线程。画布步进、技能派发、状态灯取数、Orin 状态轮询、采样源轮询…
                     凡是要周期跑、要等外部 IO 的活, 全部在这**一条**线程上排队顺序执行。
  · 不许再出现第三条 Python 线程 (也不许每次动作都 `threading.Thread(...).start()`)。
  · zmax 线程是**消费者**: 主线程 submit(fn) → 队列 → zmax 顺序执行 → 需要碰 Qt 的结果
    用 `_oneshot`/信号回主线程, zmax 线程自身零 Qt 对象 (历史 segfault 教训: 跨线程碰 QObject 会崩)。

用法 (主线程里):
    from zmax_thread import zmax_thread
    zmax_thread.start()                     # 启动唯一工程线程 (幂等)
    zmax_thread.submit(fn, foo=1)           # 丢一个活进去, 立即返回
    zmax_thread.every("orin", 5.0, fn)      # 周期活: 每 5s 在 zmax 线程上跑一次
    zmax_thread.report()                    # 线程清点 (给自检/断点分诊用)
"""
from __future__ import annotations

import os
import queue
import threading
import time
import traceback
from typing import Callable, Dict, Optional


class ZmaxThread:
    """唯一工程线程: 单队列 + 周期任务表, 全部在 name='zmax' 这一条线程上执行。"""

    def __init__(self) -> None:
        self._q: "queue.Queue" = queue.Queue()
        self._every: Dict[str, tuple] = {}          # key -> (interval, fn, next_ts)
        self._th: Optional[threading.Thread] = None
        self._stop = False
        self.n_done = 0
        self.n_err = 0
        self.last_err = ""

    # ── 生命周期 ──────────────────────────────────────────────
    def start(self) -> "ZmaxThread":
        if self._th is not None and self._th.is_alive():
            return self
        self._th = threading.Thread(target=self._run, name="zmax", daemon=True)
        self._th.start()
        return self

    def stop(self) -> None:
        self._stop = True
        self.submit(lambda: None)                   # 叫醒队列

    @property
    def thread(self) -> Optional[threading.Thread]:
        return self._th

    # ── 提交工作 ──────────────────────────────────────────────
    def submit(self, fn: Callable, *a, **kw) -> None:
        self._q.put((fn, a, kw))

    def every(self, key: str, interval: float, fn: Callable) -> None:
        """登记/替换一个周期任务 (同 key 覆盖)。第一次在 interval 秒后跑。"""
        self._every[key] = (float(interval), fn, time.monotonic() + float(interval))

    def cancel(self, key: str) -> None:
        self._every.pop(key, None)

    # ── 主循环 ────────────────────────────────────────────────
    def _debugging(self) -> bool:
        """调试器在场 ⇒ 周期活暂停 (老倪 2026-10-31「而且还是跳, 别跳啊」)。

        原因: 周期任务每 2s 在本线程停一次, 断点/单步时调试器会不断从 MainThread 切到 zmax,
        看起来就是「Call Stack 一直跳」。调试期间只保留**你手动触发**的队列任务, 周期活不自动跑。
        """
        if os.environ.get("ZMAX_ZT_IDLE", "") == "1":
            return True
        try:
            import sys
            if sys.gettrace() is not None:
                return True
            return "pydevd" in sys.modules and sys.gettrace() is not None
        except Exception:                                                   # noqa: BLE001
            return False

    def _run(self) -> None:
        while not self._stop:
            idle = self._debugging()
            timeout = 0.1
            now = time.monotonic()
            if not idle:
                for k, (iv, fn, nxt) in list(self._every.items()):
                    timeout = min(timeout, max(0.0, nxt - now))
            fn, a, kw = None, (), {}
            try:
                fn, a, kw = self._q.get(timeout=timeout)
            except queue.Empty:
                pass
            if fn is not None:
                try:
                    fn(*a, **kw)
                    self.n_done += 1
                except Exception as e:                              # noqa: BLE001
                    self.n_err += 1
                    self.last_err = "%s: %s" % (type(e).__name__, e)
                    try:
                        print("🔧 zmax 线程任务异常: %s" % self.last_err, flush=True)
                        traceback.print_exc()
                    except Exception:                               # noqa: BLE001
                        pass
            # 周期任务: 到点就跑 (同一个 tick 里最多各跑一次); 调试器在场时整段跳过
            now = time.monotonic()
            if not idle:
                for k, (iv, fn, nxt) in list(self._every.items()):
                    if now >= nxt:
                        self._every[k] = (iv, fn, now + iv)
                        try:
                            fn()
                        except Exception as e:                          # noqa: BLE001
                            self.n_err += 1
                            self.last_err = "%s: %s" % (type(e).__name__, e)

    # ── 自检 ──────────────────────────────────────────────────
    def report(self) -> dict:
        py = [t.name or "unnamed" for t in threading.enumerate()]
        return {"threads": py, "n_python_threads": len(py),
                "done": self.n_done, "err": self.n_err, "last_err": self.last_err,
                "every": sorted(self._every)}


zmax_thread = ZmaxThread()
