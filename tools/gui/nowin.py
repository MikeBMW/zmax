#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""nowin.py — Windows 全局静默守卫：GUI 进程里再也不许闪黑窗。

为什么要有这个
--------------
GUI 子系统进程（Qt / PyInstaller 打的 exe）没有控制台。它每 `subprocess` 调一个
控制台程序（powershell / cmd / tasklist / nvidia-smi / netstat …），Windows 就为它
新建一个控制台窗口 —— 屏幕上就是一个黑框一闪。多路探活叠加就是「一秒好几个」。

逐个调用点加 `creationflags=CREATE_NO_WINDOW` 太容易漏（786 就是漏了探活那两处，
换包后立刻复发）。这里改成**在每个 GUI 入口最早处 import 一次**，把
`subprocess.Popen.__init__` 兜住：Windows 上一律注入 CREATE_NO_WINDOW + SW_HIDE。
子进程照样创建、stdout 照样能抓，只是不再产生窗口。

用法
----
    from nowin import install_nowin   # 必须放在其它 import 之后、业务之前
    install_nowin()

    # 或者在 studio.py / local_services.py / simulink_module.py 顶部直接:
    import nowin  # noqa: F401  (import 即生效)

想恢复真实窗口（极少数要交互的场景）：
    with nowin.allow_console():
        subprocess.run(["cmd", "/c", "start", ...])

注意
----
* 只改 Popen（run/call/check_output/check_call 都走它），不改 os.system；
* 允许显式传 startupinfo/creationflags —— 已带就更不会重复注入；
* 非 Windows 平台 import 即无操作，Linux/macOS 零影响。
"""
from __future__ import annotations

import os
import subprocess
import threading

_APPLIED = False
_ALLOW = threading.local()

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
STARTF_USESHOWWINDOW = getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)


class _AllowConsole:
    """上下文管理器：临时放行真实控制台窗口（调试用）。"""

    def __enter__(self):
        _ALLOW.v = True
        return self

    def __exit__(self, *exc):
        _ALLOW.v = False
        return False


def allow_console() -> "_AllowConsole":
    return _AllowConsole()


def _hidden_startupinfo():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= STARTF_USESHOWWINDOW
    si.wShowWindow = 0          # SW_HIDE
    return si


def install_nowin() -> bool:
    """打补丁；返回是否真的改了（非 Windows 或已打过返回 False）。"""
    global _APPLIED
    if os.name != "nt" or _APPLIED:
        return False

    orig_init = subprocess.Popen.__init__

    def _patched_init(self, *args, **kwargs):
        if not getattr(_ALLOW, "v", False):
            try:
                kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | CREATE_NO_WINDOW
                if kwargs.get("startupinfo") is None:
                    kwargs["startupinfo"] = _hidden_startupinfo()
            except Exception:
                pass
        return orig_init(self, *args, **kwargs)

    _patched_init.__doc__ = orig_init.__doc__
    subprocess.Popen.__init__ = _patched_init
    _APPLIED = True
    return True


install_nowin()      # import 即生效
