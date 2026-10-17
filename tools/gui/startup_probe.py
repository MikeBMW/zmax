#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""startup_probe.py — 启动即落盘「这台机器还能给多少内存」(2026-10-10)

为什么需要它
------------
老倪 Windows 双击 exe 报:
    studio.py:284 -> simulink_module.py:1701 -> numpy ... -> pyimod01_archive.py:134 extract
    MemoryError: Unable to allocate output buffer.
本机复现证明: 这行字 = **zlib 解压时为输出缓冲分配内存失败**(CPython `_BlocksOutputBuffer`),
即启动那几秒**进程拿不到内存**, 不是包坏/不是代码 bug。
但「拿不到内存」是机器侧的, 远端看不见 -> 所以在任何重依赖 import **之前**先把机器状态落盘。
下次再崩, 这个日志就是根因证据(可用内存/页面文件/TEMP 在哪块盘/一次到底能分到多少 MB)。

铁律: 本模块**绝不抛异常**。探测失败也只是少一行日志, 不许拖垮控制台。
"""
import os
import sys
import time

LOG_NAME = "zmax_startup.log"


def _log_dirs():
    """按优先级给日志落点: exe(或脚本)同目录 -> %LOCALAPPDATA% -> 系统临时目录。"""
    out = []
    try:
        if getattr(sys, "frozen", False):
            out.append(os.path.dirname(os.path.abspath(sys.executable)))
        else:
            out.append(os.path.dirname(os.path.abspath(__file__)))
    except Exception:
        pass
    for env in ("LOCALAPPDATA", "APPDATA"):
        v = os.environ.get(env)
        if v:
            out.append(v)
    try:
        import tempfile
        out.append(tempfile.gettempdir())
    except Exception:
        pass
    # 去重保序
    seen, uniq = set(), []
    for d in out:
        d = os.path.abspath(d)
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def _memory_status():
    """Windows: GlobalMemoryStatusEx(物理/页面文件/提交量)。非 Windows 返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m
    except Exception:
        return None
    return None


def _max_alloc_mb(step=16, cap=1024):
    """实测「一次性还能分到多少 MB」—— 这是 MemoryError 最直接的判据。

    ⚡ 2026-10-17 启动提速 (实测): 原实现逐档 `bytearray(n)` 会**真写零** (CPython 分配即 memset),
       16/32/…/1024MB 逐档跑一遍 = 累计写 32.5GB, 本机实测 **11.8 秒**, 且整段压在控制台启动路径上
       (py-spy 采样: 栈顶 `_max_alloc_mb` 占 64%)。
    改法: Linux/macOS 上「一次能分到多少」与 MemAvailable 等价 ⇒ 直接读 /proc/meminfo (亚毫秒);
       Windows (该探测的初衷 = exe 双击 MemoryError 留证, 无 /proc) 保留真分配, 但 cap 1024→256、
       step 16→32 (累计 1.0GB ⇒ 约 0.6 秒)。要还原全量实测: ZMAX_ALLOC_PROBE_MB=1024。
    """
    _env = os.environ.get("ZMAX_ALLOC_PROBE_MB", "")
    if _env.isdigit():
        cap = max(16, int(_env))
    if not sys.platform.startswith("win"):
        try:
            with open("/proc/meminfo", "r", encoding="ascii") as _f:
                for _ln in _f:
                    if _ln.startswith("MemAvailable:"):
                        # kB → MB, 上限仍按 cap 收口 (口径与实测版一致: 「最多还能分到 cap MB」)
                        return min(int(_ln.split()[1]) // 1024, cap)
        except Exception:
            pass
    got = 0
    while got < cap:
        try:
            buf = bytearray((got + step) * 1024 * 1024)
            buf[0] = 1
            buf[-1] = 1  # 真碰一下, 防 lazy alloc 假绿
            del buf
            got += step
        except (MemoryError, OverflowError):
            break
        except Exception:
            break
    return got


def _tmp_probe():
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    line = "TEMP=%s TMP=%s" % (os.environ.get("TEMP"), os.environ.get("TMP"))
    if tmp:
        try:
            import shutil
            du = shutil.disk_usage(tmp)
            line += " | TEMP盘 可用%.1fGB/共%.1fGB" % (du.free / 2 ** 30, du.total / 2 ** 30)
        except Exception as e:  # noqa: BLE001
            line += " | TEMP盘 探测失败 %r" % (e,)
    return line


def snapshot(tag="startup"):
    """返回本次快照文本(不落盘), 便于 CI/自检断言。"""
    lines = ["[zmax-probe] tag=%s time=%s" % (tag, time.strftime("%Y-%m-%d %H:%M:%S"))]
    lines.append("pid=%s frozen=%s MEIPASS=%s" % (
        os.getpid(), bool(getattr(sys, "frozen", False)), getattr(sys, "_MEIPASS", None)))
    try:
        lines.append("exe=%s" % sys.executable)
        lines.append("cwd=%s" % os.getcwd())
    except Exception:
        pass
    m = _memory_status()
    if m is not None:
        lines.append(
            "RAM 共%.0fMB 可用%.0fMB 负载%d%% | 提交(页面文件) 共%.0fMB 可用%.0fMB"
            % (m.ullTotalPhys / 1048576, m.ullAvailPhys / 1048576, m.dwMemoryLoad,
               m.ullTotalPageFile / 1048576, m.ullAvailPageFile / 1048576))
    else:
        lines.append("RAM 探测: 非 Windows 或无权限 (platform=%s)" % sys.platform)
    lines.append(_tmp_probe())
    lines.append("实测一次可分配=%dMB" % _max_alloc_mb())
    try:
        if hasattr(sys, "getwindowsversion"):
            w = sys.getwindowsversion()
            lines.append("Windows version=%s.%s build=%s" % (w.major, w.minor, w.build))
    except Exception:
        pass
    return "\n".join(lines)


def run(tag="startup"):
    """落盘快照到所有可写落点。任何异常都吞掉 —— 探测不许影响启动。"""
    try:
        blob = snapshot(tag) + "\n" + "-" * 60 + "\n"
    except Exception:
        return
    for d in _log_dirs():
        try:
            os.makedirs(d, exist_ok=True)  # noqa: BLE001
            with open(os.path.join(d, LOG_NAME), "a", encoding="utf-8") as f:
                f.write(blob)
        except Exception:
            continue


if __name__ == "__main__":
    print(snapshot("cli"))
    run("cli")
    for d in _log_dirs():
        print("log dir:", d)
