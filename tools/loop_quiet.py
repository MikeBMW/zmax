#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常驻循环终端降噪 —— 限速 + 去重, 全量落日志文件。

老倪 2026-10-31:「每次运行，你都刷屏」「一点都没变」。根因不是循环本身(它心跳默认关),
是 11 个被白名单跑到的节点实现每拍各打一行 ([sslimit]/[ssact]/[ssphys]/[ssplan]…),
10Hz ⇒ 一秒几十行, 调试终端直接糊掉。

口径:
  · 终端: 每秒最多 N 行 (默认 2), 连续重复的合并计数; 省略掉的行数写在下一行里
  · 文件: /tmp/ss_canvas_loop.log **全量**原样落盘, 一行不丢 (事后查证据用它)
  · stderr 不动 ⇒ 真报错照样看得见
  · ZMAX_LOOP_VERBOSE=1 完全恢复原样 (排查节点时用)
  · ZMAX_LOOP_TERM_LINES=5 调每秒行数
"""
import os
import sys
import time

_LOG = os.environ.get("ZMAX_LOOP_LOG", "/tmp/ss_canvas_loop.log")
_VERBOSE = str(os.environ.get("ZMAX_LOOP_VERBOSE", "0")).strip().lower() in ("1", "true", "yes", "on")
_PER_S = max(0.0, float(os.environ.get("ZMAX_LOOP_TERM_LINES", "0") or 0))
_WIN = 1.0


class _Throttle(object):
    def __init__(self, real, sink):
        self._real = real
        self._sink = sink
        self._win_t0 = time.monotonic()
        self._win_n = 0
        self._sum_t = time.monotonic()
        self._last = None
        self._dup = 0
        self._dropped = 0

    # ── 终端节流 ──
    def _emit(self, line):
        now = time.monotonic()
        if now - self._win_t0 >= _WIN:
            # 省略统计最多 10s 一行 (0 行/秒时也不会变成"每秒一行"的刷屏)
            if self._dropped and now - self._sum_t >= 10.0:
                self._real.write("   … %d 行已省略 (全量: %s)\n" % (self._dropped, _LOG))
                self._dropped = 0
                self._sum_t = now
            self._win_t0, self._win_n = now, 0
        if self._win_n < _PER_S:
            self._win_n += 1
            self._real.write(line)
        else:
            self._dropped += 1

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        try:
            if self._sink is not None and not self._sink.closed:
                self._sink.write(s)
        except Exception:                                                  # noqa: BLE001
            pass
        # 按行处理; 末尾不完整的一行也先送 (print 一般整行 arrive)
        i = 0
        while i < len(s):
            j = s.find("\n", i)
            if j < 0:
                line, i = s[i:], len(s)
            else:
                line, i = s[i:j + 1], j + 1
            if not line.strip():
                self._emit(line)
                continue
            if line == self._last:
                self._dup += 1
                self._dropped += 0        # 重复单独计数, 不混进省略
                continue
            if self._dup:
                self._emit("   … 上一行重复 %d 次\n" % self._dup)
                self._dup = 0
            self._last = line
            self._emit(line)
        return len(s)

    def flush(self):
        for f in (self._sink,):
            try:
                if f is not None and not f.closed:
                    f.flush()
            except Exception:                                              # noqa: BLE001
                pass

    def __getattr__(self, k):                  # isatty/fileno/encoding/buffer 一律透传真 stdout
        return getattr(self._real, k)


_orig = None


def install():
    global _orig
    if _VERBOSE or isinstance(sys.stdout, _Throttle):
        return False
    _orig = sys.stdout
    sink = None
    try:
        sink = open(_LOG, "a", buffering=1, encoding="utf-8", errors="replace")
        sink.write("\n===== 循环启动 %s (pid %d) · 终端限 %g 行/秒 =====\n"
                   % (time.strftime("%F %T"), os.getpid(), _PER_S))
    except Exception:                                                  # noqa: BLE001
        sink = None
    sys.stdout = _Throttle(_orig, sink)
    return True


def release():
    if isinstance(sys.stdout, _Throttle):
        try:
            sys.stdout.flush()
        except Exception:                                              # noqa: BLE001
            pass
        sys.stdout = _orig or sys.__stdout__
