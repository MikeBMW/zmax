#!/usr/bin/env python3
"""启动静音闸 — 启动期不让 stdout 刷屏, 全量原样落到日志文件。

老倪 2026-10-31:「启动的时候，别刷屏」「你看终端，刷屏那么多无效信息」。
实测一次启动 stdout 有 365 行(📌/📚/⏱ 三行一组重复 3 遍 + 各页面自述), 真正有用的只有末尾两行。

用法(studio.py 里就这两处):
    import boot_quiet
    boot_quiet.install()        # 进程一启动就装 (必须在任何 print 之前)
    ...
    boot_quiet.release()        # 主窗口 show() 之后放开 ⇒ 终端只剩「已就绪」那两行

口径:
  · 被吞的每一行都照写 ZMAX_BOOT_LOG (默认 /tmp/zmax_boot.log), 一个字不丢, 事后可查
  · stderr **不碰** ⇒ 崩了照样看得见 traceback
  · ZMAX_BOOT_VERBOSE=1 完全恢复旧行为(排查启动流程时用)
"""
import os
import sys
import time

_BOOT_LOG = os.environ.get("ZMAX_BOOT_LOG", "/tmp/zmax_boot.log")
_VERBOSE = str(os.environ.get("ZMAX_BOOT_VERBOSE", "0")).strip().lower() in ("1", "true", "yes", "on")

_orig = None          # 真正的 stdout (装之前那份)
_sink = None          # 日志文件句柄
_n_swallowed = 0


class _Quiet(object):
    """吞掉 boot 期 stdout, 但保证 print/第三方库的常规用法都不炸。

    不继承 io.TextIOBase: 它把 encoding/errors 定义成只读属性, 覆写会报类型错;
    print/write/flush/isatty/fileno/buffer 这几个是真被用到的, 下面都补齐了。
    """

    def __init__(self, real, sink):
        self._real = real
        self._sink = sink

    # ── 核心: write 只落文件 ──
    def write(self, s):
        global _n_swallowed
        if not isinstance(s, str):
            s = str(s)
        _n_swallowed += s.count("\n")
        try:
            if self._sink is not None and not self._sink.closed:
                self._sink.write(s)
                return len(s)
        except Exception:                                                   # noqa: BLE001
            pass
        return len(s)

    def flush(self):
        try:
            if self._sink is not None and not self._sink.closed:
                self._sink.flush()
        except Exception:                                                   # noqa: BLE001
            pass

    # ── 兼容性: 让 isatty/fileno/encoding/buffer 仍然指向真 stdout ──
    def isatty(self):
        try:
            return self._real.isatty()
        except Exception:                                                   # noqa: BLE001
            return False

    def fileno(self):
        return self._real.fileno()

    def writable(self):
        return True

    def readable(self):
        return False

    def seekable(self):
        return False

    @property
    def encoding(self):
        return getattr(self._real, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._real, "errors", "replace")

    @property
    def buffer(self):
        return getattr(self._real, "buffer", None)


def install(path=None):
    """装静音闸。返回 True=已静音, False=没装(verbose 或已装过)。"""
    global _orig, _sink, _BOOT_LOG
    if path:
        _BOOT_LOG = path
    if _VERBOSE or isinstance(sys.stdout, _Quiet):
        return False
    _orig = sys.stdout
    try:
        _sink = open(path or _BOOT_LOG, "a", buffering=1, encoding="utf-8", errors="replace")
        _sink.write("\n===== 启动 %s (pid %d) =====\n" % (time.strftime("%F %T"), os.getpid()))
    except Exception:                                                       # noqa: BLE001
        _sink = None
    sys.stdout = _Quiet(_orig, _sink)
    return True


def release(mark=True):
    """放开 stdout。返回被吞掉的行数。"""
    global _orig
    n = _n_swallowed
    if isinstance(sys.stdout, _Quiet):
        try:
            sys.stdout.flush()
        except Exception:                                                   # noqa: BLE001
            pass
        sys.stdout = _orig if _orig is not None else sys.__stdout__
    if mark and n:
        try:
            print("✅ 启动静音: 吞掉 %d 行启动播报 · 全量见 %s (ZMAX_BOOT_VERBOSE=1 可恢复)"
                  % (n, _BOOT_LOG), flush=True)
        except Exception:                                                   # noqa: BLE001
            pass
    return n


def swallowed():
    return _n_swallowed
